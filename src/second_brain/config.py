"""Shared configuration for the second-brain MCP server and indexer.

The tooling used to live *inside* the vault (`~/SECOND_BRAIN/tools/`) and derived
every path from its own location. It now lives in its own project, so each path
and endpoint is resolved here (env-overridable) and imported by both modules —
one source of truth instead of the two copies that used to drift apart.

Environment overrides
---------------------
- ``SECOND_BRAIN_VAULT``      Obsidian vault root           (default ``~/SECOND_BRAIN``)
- ``SECOND_BRAIN_STATE_DIR``  manifest + lock location       (default ``~/.local/state/second-brain``)
- ``SECOND_BRAIN_QDRANT_URL`` Qdrant endpoint                (default ``http://127.0.0.1:6333``)
- ``SECOND_BRAIN_OLLAMA``     Ollama embeddings endpoint     (default ``http://127.0.0.1:11434/api/embed``)
- ``SECOND_BRAIN_EMBED_MODEL`` embedding model name          (default ``qwen3-embedding:0.6b``)
- ``SECOND_BRAIN_COLLECTION`` Qdrant collection name         (default ``second_brain``)
"""
from __future__ import annotations

import os
from pathlib import Path

VAULT = Path(os.environ.get("SECOND_BRAIN_VAULT", "~/SECOND_BRAIN")).expanduser()
STATE_DIR = Path(os.environ.get("SECOND_BRAIN_STATE_DIR", "~/.local/state/second-brain")).expanduser()
DB = STATE_DIR / "index.db"
LOCK = STATE_DIR / ".index.lock"

QDRANT_URL = os.environ.get("SECOND_BRAIN_QDRANT_URL", "http://127.0.0.1:6333")
OLLAMA = os.environ.get("SECOND_BRAIN_OLLAMA", "http://127.0.0.1:11434/api/embed")
EMBED_MODEL = os.environ.get("SECOND_BRAIN_EMBED_MODEL", "qwen3-embedding:0.6b")
COLLECTION = os.environ.get("SECOND_BRAIN_COLLECTION", "second_brain")
