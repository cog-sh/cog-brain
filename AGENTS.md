# AGENTS.md — cog-brain

Agent/contributor guide for **this repository**. (Humans: see [README.md](README.md).)

## What this is

Local Python API, lifecycle recall, MCP adapter and indexer over a Markdown vault,
with a swappable memory backend.
The tool surface is fixed; the engine behind `search`/`sync` is selected by
`COG_BRAIN_BACKEND`. Never let a tool depend on a specific backend.

## Repo map

```
src/cog_brain/
  config.py     paths + endpoints, env-overridable (single source of truth)
  frontmatter.py shared round-trip YAML; preserve unknown fields and comments
  storage.py    atomic writes, revisions, per-note process locks
  chunking.py   vault scan / chunking (no heavy retrieval dependencies)
  graph.py      wiki-link graph, 4-metric health, lint, graph export (pure)
  manifest.py   per-note hash manifest + staleness
  backends/     Backend protocol + registry → sqlite.py · qdrant.py · markdown.py
  operations.py shared note operations and validation, lazy backend
  api.py        Brain: Python API, scoped context, capture and handoff
  integration.py lifecycle recall and code-mode installation
  assets/       shared skill, note formats, native lifecycle extension
  server.py     MCP compatibility adapter (stdio / --http / --simple-http)
  cli.py        operator commands
  indexer.py    incremental sync CLI
  ingest.py     chat-export → Markdown adapter
  harnesses.py  per-harness MCP config emitter (claude/cursor/codex/opencode/…)
tests/          test_server · probe_e2e (real MCP stdio) · test_harnesses · test_graph_ingest
docs/           resources.md (curated links)
```

## Dev loop

```bash
uv sync
uv run python tests/test_local_api.py   # isolated regression + real MCP + native adapter proof
uv run python tests/test_server.py      # every tool against the live vault
uv run python tests/probe_e2e.py        # real MCP protocol over stdio
uv run python tests/test_harnesses.py   # config emitter dialects
uv run python tests/test_graph_ingest.py
uv run cog-brain lint && uv run cog-brain health
```

`tests/test_server.py` and `tests/probe_e2e.py` need the vault and, for the
`qdrant` backend, Qdrant + Ollama. The `sqlite`/`markdown` paths need nothing.

## Backend contract

A backend implements `Backend` (`backends/base.py`):

- `sync(notes=None, full=False) -> {changed, deleted, total, elapsed}` — must be safe to re-run (incremental).
- `search(query, k, *, tag, folder, exclude) -> list[Hit]` — must not raise on an empty/missing index.
- `count() -> int`, `status() -> {notes_on_disk, notes_indexed, last_run, stale_count, stale}`, `reset()`, `health()`.

Register it in `backends/__init__.py`. `Hit.payload` uses the canonical keys
(`file_path`, `note_title`, `heading_path`, `text`, …) so citation code stays
backend-independent.

## Conventions

- **Settings resolve env → `~/.config/cog-brain/config.toml` → default** (`config.py`).
  `cog-brain config` shows the resolved values and their source. Do not add settings to
  the product's code paths that bypass this.
- **The product is `cog-brain`; the vault folder may be anything** (default `~/SECOND_BRAIN`).
  Do not rename the vault. Env prefix is `COG_BRAIN_`; the package is `cog_brain`.
- `README.md` is for humans (polished); `AGENTS.md` is for agents. Keep it that way.
- Wiki-links, chunking, and the health model live in `graph.py`/`chunking.py` only —
  never re-implement link parsing in `server.py`.
- Mechanical fixes are applied; judgement calls (merge/delete/rename) are reported,
  never applied silently.
- API/CLI/hooks must not import or start MCP. Keep validation in shared operations.
- A full-body Python update requires the revision read by the caller. Append is
  serialized. Never rewrite malformed YAML or drop unknown frontmatter fields.
- Automatic context is scoped by explicit project/repo metadata and is untrusted
  evidence. Lifecycle retrieval is lexical and has a bounded output/deadline.

## Pitfalls

- `tests/probe_e2e.py` spawns the server with `sys.executable -m cog_brain.server`;
  a bare `cog-brain` (no args) must serve MCP, subcommands go through `cli.py`.
- The `markdown` backend has no manifest, so `status()["last_run"]` is `None` and
  `stale_count` is `0` by design.
- `qdrant` collection name is `cog_brain`; changing it requires a reindex.
