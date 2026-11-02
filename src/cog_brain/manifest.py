"""Per-note hash manifest + staleness — shared by index-backed backends.

Tracks which note content hash was last indexed and when a scan finished, so
``vault_status`` can tell what changed and each backend can index incrementally.
"""
from __future__ import annotations

import sqlite3
import hashlib
from pathlib import Path

from cog_brain import chunking


class Manifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS files "
            "(rel_path TEXT PRIMARY KEY, text_hash TEXT, chunker_version TEXT, embed_model TEXT)")
        self.con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.con.execute("CREATE TABLE IF NOT EXISTS snapshots (rel_path TEXT PRIMARY KEY, raw_hash TEXT)")
        self.con.execute("CREATE TABLE IF NOT EXISTS failures (rel_path TEXT PRIMARY KEY, error TEXT)")
        self.con.commit()

    def get(self, rel: str):
        return self.con.execute(
            "SELECT text_hash, chunker_version, embed_model FROM files WHERE rel_path=?",
            (rel,)).fetchone()

    def set(self, rel: str, h: str, chunker: str, model: str) -> None:
        self.con.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?)", (rel, h, chunker, model))
        self.con.commit()

    def delete(self, rel: str) -> None:
        self.con.execute("DELETE FROM files WHERE rel_path=?", (rel,))
        self.con.execute("DELETE FROM snapshots WHERE rel_path=?", (rel,))
        self.con.execute("DELETE FROM failures WHERE rel_path=?", (rel,))
        self.con.commit()

    def snapshot(self, rel: str, raw_hash: str) -> None:
        self.con.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?)", (rel, raw_hash))
        self.con.execute("DELETE FROM failures WHERE rel_path=?", (rel,))
        self.con.commit()

    def fail(self, rel: str, error: str) -> None:
        self.con.execute("INSERT OR REPLACE INTO failures VALUES (?,?)", (rel, error))
        self.con.commit()

    def status(self) -> dict:
        indexed = dict.fromkeys(self.rels(), "")
        indexed.update(dict(self.con.execute("SELECT * FROM snapshots")))
        return snapshot_status(indexed, self.last_run(),
                               dict(self.con.execute("SELECT * FROM failures")))

    def rels(self) -> list[str]:
        return [r for (r,) in self.con.execute("SELECT rel_path FROM files").fetchall()]

    def last_run(self) -> float | None:
        row = self.con.execute("SELECT value FROM meta WHERE key='last_run'").fetchone()
        return float(row[0]) if row else None

    def set_last_run(self, ts: float) -> None:
        self.con.execute("INSERT OR REPLACE INTO meta VALUES ('last_run', ?)", (str(ts),))
        self.con.commit()

    def clear(self) -> None:
        self.con.execute("DELETE FROM files")
        self.con.execute("DELETE FROM meta")
        self.con.execute("DELETE FROM snapshots")
        self.con.execute("DELETE FROM failures")
        self.con.commit()


def staleness(rels: list[str], last_run: float | None) -> list[str]:
    """Vault-relative paths whose mtime is newer than the last finished scan."""
    if last_run is None:
        return []
    out = []
    for rel in rels:
        try:
            if (chunking.config.VAULT / rel).stat().st_mtime > last_run:
                out.append(rel)
        except OSError:
            pass
    return out


def iso(ts: float | None) -> str | None:
    from datetime import datetime
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else None


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_status(indexed: dict[str, str], last_run: float | None,
                    failures: dict[str, str] | None = None) -> dict:
    """Compare actual contents and membership; mtimes cannot prove freshness."""
    disk = {rel: path for path, rel in chunking.iter_notes()}
    added = sorted(disk.keys() - indexed.keys())
    deleted = sorted(indexed.keys() - disk.keys())
    changed = []
    failures = {r: error for r, error in (failures or {}).items() if r in disk or r in indexed}
    for rel in disk.keys() & indexed.keys():
        try:
            if file_hash(disk[rel]) != indexed[rel]:
                changed.append(rel)
        except OSError as error:
            failures[rel] = str(error)
    stale = sorted(set(added + deleted + changed) | set(failures))
    return {"notes_on_disk": len(disk), "notes_indexed": len(indexed),
            "last_run": iso(last_run), "stale_count": len(stale) if last_run else -1,
            "stale": stale[:50], "added": added[:50], "deleted": deleted[:50],
            "failed": failures, "state": "uninitialized" if last_run is None else
            "stale" if stale else "ready"}
