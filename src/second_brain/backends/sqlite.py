"""SQLite backend — the zero-service default.

One SQLite file holds both the FTS5 chunk index and the incremental manifest.
No daemon, no docker, no embedding server: works on a bare machine and scales to
large vaults. Ranking is BM25 (FTS5).

Optional vector recall is an explicit extension point (``SECOND_BRAIN_SQLITE_VEC``)
to be layered on top of the same table; today BM25 is the whole story.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import sys
import time
from pathlib import Path

from second_brain import chunking, config
from second_brain.backends.base import Hit
from second_brain.manifest import iso, staleness

NAME = "sqlite"
_TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁё_]+")


class SqliteBackend:
    name = NAME

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or config.SQLITE_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5("
            "rel_path UNINDEXED, tags UNINDEXED, note_title, heading_path, text, "
            "tokenize='unicode61')")
        self.con.execute("CREATE TABLE IF NOT EXISTS files (rel_path TEXT PRIMARY KEY, text_hash TEXT)")
        self.con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.con.commit()

    # ---------------------------------------------------------------- indexing

    def _forget(self, rel: str) -> None:
        self.con.execute("DELETE FROM chunks WHERE rel_path=?", (rel,))
        self.con.execute("DELETE FROM files WHERE rel_path=?", (rel,))
        self.con.commit()

    def _index_file(self, p: Path, rel: str, full: bool) -> bool:
        chunks = chunking.chunks_for(p, rel)
        h = hashlib.sha256("\n\x00\n".join(c["embed_text"] for c in chunks).encode()).hexdigest()
        row = self.con.execute("SELECT text_hash FROM files WHERE rel_path=?", (rel,)).fetchone()
        if row and row[0] == h and not full:
            return False
        self._forget(rel)
        for c in chunks:
            self.con.execute(
                "INSERT INTO chunks(rel_path, tags, note_title, heading_path, text) VALUES (?,?,?,?,?)",
                (rel, "," + ",".join(c["tags"]) + ",", c["note_title"], c["heading_path"], c["text"]))
        self.con.execute("INSERT OR REPLACE INTO files VALUES (?,?)", (rel, h))
        self.con.commit()
        return True

    def sync(self, notes=None, full: bool = False) -> dict:
        notes = list(notes if notes is not None else chunking.iter_notes())
        changed = deleted = 0
        t0 = time.time()
        current = set()
        for p, rel in notes:
            current.add(rel)
            try:
                if self._index_file(p, rel, full):
                    changed += 1
            except Exception as e:  # noqa: BLE001
                print(f"  !! {rel}: {e}", file=sys.stderr)
        for (rel,) in self.con.execute("SELECT rel_path FROM files").fetchall():
            if rel not in current:
                self._forget(rel)
                deleted += 1
        self.con.execute("INSERT OR REPLACE INTO meta VALUES ('last_run', ?)", (str(time.time()),))
        self.con.commit()
        return {"changed": changed, "deleted": deleted, "total": self.count(),
                "elapsed": round(time.time() - t0, 1)}

    # ------------------------------------------------------------------ search

    def search(self, query: str, k: int, *, tag: str | None = None,
               folder: str | None = None, exclude: str | None = None) -> list[Hit]:
        toks = _TOKEN.findall(query)
        if not toks:
            return []
        sql = ("SELECT rel_path, note_title, heading_path, text, bm25(chunks) AS s "
               "FROM chunks WHERE chunks MATCH ?")
        args: list = [" OR ".join(f"{t}*" for t in toks)]
        if tag:
            sql += " AND tags LIKE ?"
            args.append(f"%,{tag},%")
        if folder:
            sql += " AND rel_path LIKE ?"
            args.append(folder.rstrip("/") + "%")
        if exclude:
            sql += " AND rel_path <> ?"
            args.append(exclude)
        sql += " ORDER BY s LIMIT ?"
        args.append(k)
        rows = self.con.execute(sql, args).fetchall()
        return [Hit(payload={"file_path": r[0], "note_title": r[1], "heading_path": r[2],
                             "text": r[3]}, score=round(-r[4], 4)) for r in rows]

    # ------------------------------------------------------------------- state

    def count(self) -> int:
        return self.con.execute("SELECT count(*) FROM chunks").fetchone()[0]

    def status(self) -> dict:
        indexed = [r for (r,) in self.con.execute("SELECT rel_path FROM files").fetchall()]
        last = self.con.execute("SELECT value FROM meta WHERE key='last_run'").fetchone()
        last = float(last[0]) if last else None
        disk = [rel for _, rel in chunking.iter_notes()]
        stale = staleness(disk, last)
        return {"backend": NAME, "notes_on_disk": len(disk), "notes_indexed": len(indexed),
                "last_run": iso(last), "stale_count": len(stale), "stale": stale[:50]}

    def reset(self) -> None:
        self.con.execute("DELETE FROM chunks")
        self.con.execute("DELETE FROM files")
        self.con.execute("DELETE FROM meta")
        self.con.commit()

    def health(self) -> dict:
        return {"backend": NAME, "db": str(self.path), "chunks": self.count(),
                "infra": "none", **{k: v for k, v in self.status().items()
                                    if k in ("notes_on_disk", "notes_indexed", "last_run")}}
