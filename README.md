# cog-brain

Agent-agnostic **second brain** over an Obsidian vault: an MCP server plus an
incremental indexer with **pluggable memory backends**.

The vault is the source of truth — plain, human-editable Markdown. The index is
derived and rebuildable, and the storage/retrieval **engine is swappable without
changing a single tool**. That combination is the point: markdown-first tools
usually have weak retrieval; vector tools usually aren't human-editable.

Cog-brain is the product; `~/SECOND_BRAIN` is the default vault it points at.

## Install

### As a plugin (omp / Claude Code) — recommended

```bash
# oh-my-pi
omp plugin marketplace add cog-sh/cog-brain-plugins
omp plugin install cog-brain@cog-brain-plugins
```

Then `/reload-plugins` (skills, slash commands, MCP). The plugin registers the
MCP server via `uvx` — nothing to clone.

### Plain MCP client

```json
{
  "mcpServers": {
    "cog-brain": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/cog-sh/cog-brain", "cog-brain"],
      "env": { "COG_BRAIN_BACKEND": "sqlite" }
    }
  }
}
```

### From source

```bash
uv sync
uv run cog-brain-index        # build the index
uv run cog-brain doctor       # verify vault + backend
```

## Memory backends

Pick the engine with `COG_BRAIN_BACKEND` (or `cog-brain --backend <name> …`).

| backend | storage | needs | ranking |
| --- | --- | --- | --- |
| `sqlite` **(default)** | one SQLite file (chunks + manifest) | nothing | FTS5 BM25 |
| `qdrant` | Qdrant collection | Qdrant + an embedding endpoint | dense + BM25, RRF fusion |
| `markdown` | none — the filesystem is the index | nothing | in-process BM25 |

Adding a backend is one module in `src/cog_brain/backends/` implementing the
`Backend` protocol (`sync` · `search` · `status` · `reset` · `health`).

## Operator CLI

```bash
cog-brain status                 # index health (notes on disk vs indexed, staleness)
cog-brain doctor                 # diagnose vault, state dir, active backend
cog-brain backends               # list engines, show the active one
cog-brain reindex [--full]       # rebuild the index
cog-brain inspect chunks <note>  # how one note is chunked
cog-brain inspect query "<q>" -k 10   # retrieved notes + scores
```

A bare `cog-brain` (no subcommand) is the MCP stdio server.

## MCP tools

- **read**: `semantic_search`, `outline`, `read_note`, `find_related`, `backlinks`,
  `broken_links`, `graph_overview`, `list_notes`, `vault_status`
- **write**: `write_note`, `update_note`
- **index**: `index_now`

Writes re-index automatically. Retracted notes stay searchable and are flagged.

## Configuration

| variable | meaning | default |
| --- | --- | --- |
| `COG_BRAIN_VAULT` | vault root | `~/SECOND_BRAIN` |
| `COG_BRAIN_BACKEND` | `sqlite` · `qdrant` · `markdown` | `sqlite` |
| `COG_BRAIN_STATE_DIR` | index + manifest location | `~/.local/state/cog-brain` |
| `COG_BRAIN_SQLITE_DB` | sqlite db path | `<state>/sqlite.db` |
| `COG_BRAIN_QDRANT_URL` | Qdrant endpoint (`qdrant` only) | `http://127.0.0.1:6333` |
| `COG_BRAIN_OLLAMA` | embedding endpoint (`qdrant` only) | `http://127.0.0.1:11434/api/embed` |
| `COG_BRAIN_EMBED_MODEL` | embedding model (`qdrant` only) | `qwen3-embedding:0.6b` |
| `COG_BRAIN_COLLECTION` | Qdrant collection (`qdrant` only) | `cog_brain` |

## Layout

```
src/cog_brain/
  config.py     paths + endpoints (env-overridable)
  chunking.py   vault scan / frontmatter / chunking (pure, shared)
  manifest.py   per-note hash manifest + staleness
  backends/     Backend protocol + registry
    sqlite.py   · qdrant.py · markdown.py
  server.py     MCP server (stdio / --http / --simple-http) + CLI dispatch
  cli.py        operator commands
  indexer.py    incremental sync CLI
  harnesses.py  per-harness MCP config emitter
tests/          smoke (every tool) + real MCP stdio probe
```

## Verify

```bash
uv run python tests/test_server.py    # every tool against the live vault
uv run python tests/probe_e2e.py      # real MCP protocol over stdio
```

## Related

- Plugins marketplace: <https://github.com/cog-sh/cog-brain-plugins>
