"""Zero-infrastructure backend: lexical BM25 straight off the filesystem.

No daemon, no index file, no embeddings — it tokenizes the vault on demand and
ranks by BM25. Ships so the product works on a bare machine (`COG_BRAIN_BACKEND=markdown`)
and as the fallback when the vector stack is down. Quality is lexical, not
semantic; use `qdrant` when you want embeddings.
"""
from __future__ import annotations

import math
import re
import time
from collections import Counter

from cog_brain import chunking
from cog_brain.backends.base import Hit

NAME = "markdown"
_TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁё_]+")
_K1, _B = 1.5, 0.75
_TTL = 2.0  # seconds; vault scan cache
_CACHE: dict = {"at": 0.0, "chunks": [], "df": Counter(), "avg": 1.0, "n": 0}


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def _load() -> dict:
    now = time.time()
    if _CACHE["n"] and now - _CACHE["at"] < _TTL:
        return _CACHE
    chunks: list[dict] = []
    for p, rel in chunking.iter_notes():
        for c in chunking.chunks_for(p, rel):
            toks = _tokens(c["embed_text"])
            c["_tf"], c["_len"] = Counter(toks), len(toks)
            chunks.append(c)
    df: Counter = Counter()
    for c in chunks:
        df.update(c["_tf"].keys())
    _CACHE.update(at=now, chunks=chunks, df=df, n=len(chunks),
                  avg=(sum(c["_len"] for c in chunks) / len(chunks)) if chunks else 1.0)
    return _CACHE


class MarkdownBackend:
    name = NAME

    def _score(self, qtf: Counter, c: dict, df: Counter, n: int, avg: float) -> float:
        score = 0.0
        for term, qn in qtf.items():
            f = c["_tf"].get(term)
            if not f:
                continue
            idf = math.log(1 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
            score += qn * idf * (f * (_K1 + 1)) / (f + _K1 * (1 - _B + _B * c["_len"] / avg))
        return score

    def search(self, query: str, k: int, *, tag: str | None = None,
               folder: str | None = None, exclude: str | None = None) -> list[Hit]:
        qtf = Counter(_tokens(query))
        if not qtf:
            return []
        cache = _load()
        n, df, avg = cache["n"], cache["df"], cache["avg"]
        scored: list[tuple[float, dict]] = []
        for c in cache["chunks"]:
            if exclude and c["rel_path"] == exclude:
                continue
            if tag and tag not in c["tags"]:
                continue
            if folder and not c["rel_path"].startswith(folder.rstrip("/")):
                continue
            s = self._score(qtf, c, df, n, avg)
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            Hit(payload={
                "file_path": c["rel_path"], "note_title": c["note_title"],
                "heading_path": c["heading_path"], "text": c["text"],
                "tags": c["tags"], "aliases": c["aliases"], "links": c["links"],
                "type": c["type"], "status": c["status"], "mtime": c["mtime"],
            }, score=round(s, 4))
            for s, c in scored[:k]
        ]

    def count(self) -> int:
        return _load()["n"]

    def health(self) -> dict:
        cache = _load()
        return {"backend": NAME, "chunks": cache["n"], "terms": len(cache["df"]),
                "infra": "none"}

    def sync(self, notes=None, full: bool = False) -> dict:
        """No index to build — the filesystem is the index."""
        _CACHE.update(at=0.0)
        n = sum(1 for _ in chunking.iter_notes())
        return {"changed": 0, "deleted": 0, "total": n, "elapsed": 0.0}

    def status(self) -> dict:
        disk = sum(1 for _ in chunking.iter_notes())
        return {"backend": NAME, "notes_on_disk": disk, "notes_indexed": disk,
                "last_run": None, "stale_count": 0, "stale": []}

    def reset(self) -> None:
        _CACHE.update(at=0.0, chunks=[], df=Counter(), n=0, avg=1.0)
