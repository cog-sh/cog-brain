"""Shared configuration for the cog-brain MCP server and indexer.

Resolution order, highest first:

1. environment variable (``COG_BRAIN_*``),
2. the config file (``COG_BRAIN_CONFIG``, default ``~/.config/cog-brain/config.toml``),
3. the built-in default.

The config file is TOML with one key per setting (see the template below), so a
machine keeps its settings out of ``.zshrc`` and in one readable file. Paths are
tilde-expanded. A missing or malformed file is ignored, never fatal.

```toml
# ~/.config/cog-brain/config.toml
backend    = "qdrant"          # sqlite (default) | qdrant | markdown
vault      = "~/SECOND_BRAIN"  # Obsidian vault root
state_dir  = "~/.local/state/cog-brain"
qdrant_url = "http://127.0.0.1:6333"
ollama     = "http://127.0.0.1:11434/api/embed"
embed_model = "qwen3-embedding:0.6b"
collection = "cog_brain"
```
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("COG_BRAIN_CONFIG", "~/.config/cog-brain/config.toml")).expanduser()

# key (in the TOML file) -> environment variable
_KEYS = {
    "vault": "COG_BRAIN_VAULT",
    "state_dir": "COG_BRAIN_STATE_DIR",
    "sqlite_db": "COG_BRAIN_SQLITE_DB",
    "backend": "COG_BRAIN_BACKEND",
    "qdrant_url": "COG_BRAIN_QDRANT_URL",
    "ollama": "COG_BRAIN_OLLAMA",
    "embed_model": "COG_BRAIN_EMBED_MODEL",
    "collection": "COG_BRAIN_COLLECTION",
}


def _load_file() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        with CONFIG_PATH.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return {k: v for k, v in data.items() if k in _KEYS and isinstance(v, (str, int, float))}


_FILE = _load_file()


def _sources() -> dict[str, str]:
    """For each key: 'env' | 'file' | 'default' (for `cog-brain config`)."""
    return {
        k: ("env" if os.environ.get(env) is not None else "file" if k in _FILE else "default")
        for k, env in _KEYS.items()
    }


_SOURCES = _sources()


def _get(key: str, default: str) -> str:
    env = os.environ.get(_KEYS[key])
    if env is not None:
        return env
    if key in _FILE:
        return str(_FILE[key])
    return default


VAULT = Path(_get("vault", "~/SECOND_BRAIN")).expanduser()
STATE_DIR = Path(_get("state_dir", "~/.local/state/cog-brain")).expanduser()
DB = STATE_DIR / "index.db"
LOCK = STATE_DIR / ".index.lock"

BACKEND = _get("backend", "sqlite")
SQLITE_PATH = Path(_get("sqlite_db", str(STATE_DIR / "sqlite.db"))).expanduser()
QDRANT_URL = _get("qdrant_url", "http://127.0.0.1:6333")
OLLAMA = _get("ollama", "http://127.0.0.1:11434/api/embed")
EMBED_MODEL = _get("embed_model", "qwen3-embedding:0.6b")
COLLECTION = _get("collection", "cog_brain")


def describe() -> dict:
    return {
        "config_file": str(CONFIG_PATH),
        "config_file_exists": CONFIG_PATH.is_file(),
        "precedence": "env > file > default",
        "resolved": {
            "vault": str(VAULT), "state_dir": str(STATE_DIR), "backend": BACKEND,
            "sqlite_db": str(SQLITE_PATH), "qdrant_url": QDRANT_URL, "ollama": OLLAMA,
            "embed_model": EMBED_MODEL, "collection": COLLECTION,
        },
        "sources": _SOURCES,
    }
