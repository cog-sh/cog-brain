"""Memory-backend seam.

A *memory backend* is the storage + retrieval engine behind the same tool
surface. Swapping it must not change the MCP tools, the note format, or the
vault — only how chunks are stored and how a query is answered.

Built-in backends:

- ``qdrant``   — dense (Ollama embeddings) + sparse BM25, RRF fusion. Best quality;
                 needs Qdrant + an embedding endpoint.
- ``markdown`` — zero-infrastructure lexical BM25 straight off the filesystem.
                 No daemon, no index, no embeddings: works on a bare machine.

Add a backend with one module exposing ``NAME`` and a ``Backend`` subclass, then
register it in :data:`_BUILTIN`. Nothing else changes.
"""
from __future__ import annotations

from second_brain import config
from second_brain.backends.base import Backend, Hit

_BUILTIN = ("qdrant", "markdown")


def available() -> list[str]:
    return list(_BUILTIN)


def get_backend(name: str | None = None) -> Backend:
    name = (name or config.BACKEND).strip().lower()
    if name == "qdrant":
        from second_brain.backends.qdrant import QdrantBackend
        return QdrantBackend()
    if name == "markdown":
        from second_brain.backends.markdown import MarkdownBackend
        return MarkdownBackend()
    raise ValueError(f"unknown backend: {name!r} (available: {', '.join(_BUILTIN)})")


__all__ = ["Backend", "Hit", "available", "get_backend"]
