# second-brain

MCP server + incremental indexer for the **SECOND_BRAIN** Obsidian vault:
hybrid semantic search (dense `qwen3-embedding` + sparse BM25, RRF) over Qdrant,
plus safe read/write tooling and wiki-link graph helpers.

This used to live inside the vault at `~/SECOND_BRAIN/tools/` and derived every
path from its own location. It is now a standalone project:

- **code** lives here;
- **state** (the incremental manifest + lock) lives in `~/.local/state/second-brain/`;
- **data** (the notes) stays in the vault, `~/SECOND_BRAIN/` by default.

## Layout

```
src/second_brain/
  config.py    # paths + endpoints (all env-overridable, one source of truth)
  indexer.py   # incremental vault -> Qdrant indexer
  server.py    # MCP server (stdio) + optional JSON HTTP API
tests/
  test_server.py   # exercises every tool against the live vault
  probe_e2e.py     # real MCP stdio protocol end-to-end probe
contrib/
  nvim-second-brain.lua   # Neovim front-end for the JSON HTTP API
```

## Install

```bash
uv sync
```

## Run the MCP server (stdio)

```bash
uv run second-brain
```

Wired into the agent in `~/.omp/agent/mcp.json`:

```json
"second-brain": {
  "type": "stdio",
  "command": "uv",
  "args": ["run", "second-brain"],
  "cwd": "/Users/acidsugarx/CODES/h/second-brain"
}
```

## Index

```bash
uv run second-brain-index            # incremental diff
uv run second-brain-index --full     # full reindex
uv run second-brain-index --watch    # poll every 3s
```

`write_note` / `update_note` re-index automatically (the server runs the indexer
in the same venv via `python -m second_brain.indexer`).

## JSON HTTP API (nvim / curl)

```bash
uv run second-brain --simple-http          # POST http://127.0.0.1:8766/search
uv run second-brain --http                 # MCP over SSE on :8765
```

## Verify

```bash
uv run python tests/test_server.py    # every tool against the live vault
uv run python tests/probe_e2e.py      # real MCP protocol over stdio
```

Both need Qdrant (`http://127.0.0.1:6333`) and Ollama
(`qwen3-embedding:0.6b`) up. On this host: `colima start && docker start qdrant`.

## Configuration

| env var | default |
| --- | --- |
| `SECOND_BRAIN_VAULT` | `~/SECOND_BRAIN` |
| `SECOND_BRAIN_STATE_DIR` | `~/.local/state/second-brain` |
| `SECOND_BRAIN_QDRANT_URL` | `http://127.0.0.1:6333` |
| `SECOND_BRAIN_OLLAMA` | `http://127.0.0.1:11434/api/embed` |
| `SECOND_BRAIN_EMBED_MODEL` | `qwen3-embedding:0.6b` |
| `SECOND_BRAIN_COLLECTION` | `second_brain` |
