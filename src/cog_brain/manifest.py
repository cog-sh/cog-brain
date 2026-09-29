"""Per-note hash manifest + staleness — shared by index-backed backends.

Tracks which note content hash was last indexed and when a scan finished, so
``vault_status`` can tell what changed and each backend can index incrementally.
"""
from __future__ import annotations

import sqlite3
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
        self.con.commit()

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
