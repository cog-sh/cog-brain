"""Shared configuration for the cog-brain MCP server and indexer.

The tooling used to live *inside* the vault (`~/SECOND_BRAIN/tools/`) and derived
every path from its own location. It now lives in its own project, so each path
and endpoint is resolved here (env-overridable) and imported by both modules —
one source of truth instead of the two copies that used to drift apart.

Environment overrides
---------------------
- ``COG_BRAIN_VAULT``      Obsidian vault root           (default ``~/SECOND_BRAIN``)
- ``COG_BRAIN_STATE_DIR``  manifest + lock location       (default ``~/.local/state/cog-brain``)
- ``COG_BRAIN_QDRANT_URL`` Qdrant endpoint                (default ``http://127.0.0.1:6333``)
- ``COG_BRAIN_OLLAMA``     Ollama embeddings endpoint     (default ``http://127.0.0.1:11434/api/embed``)
- ``COG_BRAIN_EMBED_MODEL`` embedding model name          (default ``qwen3-embedding:0.6b``)
- ``COG_BRAIN_COLLECTION`` Qdrant collection name         (default ``cog_brain``)
"""
from __future__ import annotations

import os
from pathlib import Path

VAULT = Path(os.environ.get("COG_BRAIN_VAULT", "~/SECOND_BRAIN")).expanduser()
STATE_DIR = Path(os.environ.get("COG_BRAIN_STATE_DIR", "~/.local/state/cog-brain")).expanduser()
DB = STATE_DIR / "index.db"
LOCK = STATE_DIR / ".index.lock"

QDRANT_URL = os.environ.get("COG_BRAIN_QDRANT_URL", "http://127.0.0.1:6333")
OLLAMA = os.environ.get("COG_BRAIN_OLLAMA", "http://127.0.0.1:11434/api/embed")
EMBED_MODEL = os.environ.get("COG_BRAIN_EMBED_MODEL", "qwen3-embedding:0.6b")
COLLECTION = os.environ.get("COG_BRAIN_COLLECTION", "cog_brain")

# Storage/retrieval engine behind the tool surface. Default "sqlite": one file,
# FTS5 index + incremental manifest, no external services. "qdrant" = semantic
# (dense + BM25, RRF; needs Qdrant + Ollama). "markdown" = no index at all.
BACKEND = os.environ.get("COG_BRAIN_BACKEND", "sqlite")
SQLITE_PATH = Path(os.environ.get("COG_BRAIN_SQLITE_DB", str(STATE_DIR / "sqlite.db"))).expanduser()
