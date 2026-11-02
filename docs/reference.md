# Configuration and integrations

For the product overview and first setup, see [the README](../README.md).
For everyday note formats, see [the writing guide](../src/cog_brain/assets/notes.md).

## Configuration

Settings resolve **env → `~/.config/cog-brain/config.toml` → default**, so a machine
keeps them in one readable file instead of a shell profile:

```toml
# ~/.config/cog-brain/config.toml
backend = "qdrant"
vault   = "~/SECOND_BRAIN"
```

`cog-brain config` prints the resolved values and where each came from. A missing or
malformed file is ignored, never fatal. Point elsewhere with `COG_BRAIN_CONFIG`.

| variable | meaning | default |
| --- | --- | --- |
| `COG_BRAIN_CONFIG` | config file path | `~/.config/cog-brain/config.toml` |
| `COG_BRAIN_VAULT` | vault root | `~/SECOND_BRAIN` |
| `COG_BRAIN_BACKEND` | `sqlite` · `qdrant` · `markdown` | `sqlite` |
| `COG_BRAIN_STATE_DIR` | index + manifest location | `~/.local/state/cog-brain` |
| `COG_BRAIN_SQLITE_DB` | sqlite path | `<state>/sqlite.db` |
| `COG_BRAIN_QDRANT_URL` | Qdrant endpoint (`qdrant` only) | `http://127.0.0.1:6333` |
| `COG_BRAIN_OLLAMA` | embedding endpoint (`qdrant` only) | `http://127.0.0.1:11434/api/embed` |
| `COG_BRAIN_EMBED_MODEL` | embedding model (`qdrant` only) | `qwen3-embedding:0.6b` |
| `COG_BRAIN_COLLECTION` | Qdrant collection (`qdrant` only) | `cog_brain` |

## Local API and CLI

Use the Python environment containing cog-brain to import `Brain`. A tool install
provides the `cog-brain` executable; it does not install the package into every
Python interpreter. The lifecycle message includes the configured Python path.

```bash
cog-brain call search <<'JSON'
{"query":"deployment decisions","project":"my-project","limit":4,"lexical":true}
JSON
```

Operations: `search`, `read`, `context`, `create`, `update`, `capture`, `project`,
`handoff`, `list_notes`, `outline`, `find_related`, `backlinks`. Arguments are JSON
objects on stdin; results are JSON. See the [shared skill](../src/cog_brain/assets/SKILL.md)
for signatures and examples.

The `context --budget` option bounds serialized characters, not measured tokens.
Automatic context uses local lexical retrieval regardless of the configured
backend. Full-body `Brain.update()` requires `expected_hash` from the actual
`Brain.read()` result; append is serialized between cog-brain processes. External
editors do not share these locks, so filesystem compare-and-swap with arbitrary
editors is not guaranteed.

## Client installation

```bash
cog-brain install --harness codex --mode code
cog-brain install --harness omp --mode code
cog-brain install --harness pi --mode code
```

Choose the client you use. Code-mode installation creates a shared skill and
lifecycle integration. Changed files receive timestamped `.bak-cogbrain-*`
backups; unrelated hooks and instructions are preserved. The existing cog-brain
MCP entry is disabled by default. Pass `--keep-mcp` to keep it enabled, or
`--scope project` for installation in the current repository.

Restart the client after installing. Codex requires trusting new hooks through
`/hooks` before they can inject context. Its managed AGENTS instruction provides
an autonomous CLI fallback while the hooks await review. Codex 0.166 restores
context through `SessionStart(compact)`; its `PostCompact` event cannot emit
additional context. OMP and Pi use native extensions.

For a fresh project, ask the connected agent to create a project card bound to
this repository and linked to an existing note. A Python equivalent is:

```python
from cog_brain import Brain

brain = Brain()
brain.project(
    "my-project.md", "My project", cwd="/absolute/path/to/repo",
    description="Current project state and next action.",
    content="## Goal\nShip the project.\n\n## Next step\nRun the checks.\n\n[[existing-note]]",
)
```

Replace `existing-note` with an actual note stem or title. Existing cards can be
bound with `brain.update(file_path, repo="/canonical/repo/root", project="my-project")`.
The `repo` path must be the canonical checkout root. Worktrees resolve through
the common Git directory. Starting in a directory does not create a card or
silently borrow another project's context.

## MCP clients

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

Or let cog-brain write it for you:

```bash
cog-brain mcp-config --harness cursor        # paste-ready snippet
cog-brain install --harness codex            # merge into ~/.codex/config.toml
```

### Working from source

```bash
git clone https://github.com/cog-sh/cog-brain && cd cog-brain
uv sync
uv run cog-brain-index        # build the index
uv run cog-brain doctor       # check vault + backend
```


## Operator CLI

```bash
cog-brain status                 # index health: notes on disk vs indexed, staleness
cog-brain config                 # resolved settings + where each value comes from
cog-brain health                 # 4 metrics with verdicts (orphans, degree, connectivity, stale)
cog-brain lint                   # broken links · orphans · stubs · missing frontmatter
cog-brain doctor                 # diagnose vault, state dir, active backend
cog-brain graph --export graphml # export the wiki-link graph (type as node attr)
cog-brain inspect query "…" -k 10
cog-brain ingest chats export.json
cog-brain backends
cog-brain reindex
cog-brain mcp-config --harness cursor
cog-brain install --harness cursor --mode mcp
```

## MCP tools

- **read** — `semantic_search`, `outline`, `read_note`, `find_related`, `backlinks`,
  `broken_links`, `graph_overview`, `list_notes`, `vault_status`
- **write** — `write_note`, `update_note`
- **index** — `index_now`

## Troubleshooting

- **No project card:** bind an existing card or create one linked to an existing
  note. `cog-brain context --cwd /path/to/repo --lexical` reports the current binding.
- **Hooks do not run:** restart the client and review its hook permissions. In
  Codex, open `/hooks`. For code mode, check the installed shared skill as well.
- **Backend unavailable:** run `cog-brain doctor`; local context and searches with
  `--lexical` or `lexical=True` do not need Qdrant or Ollama.
- **Index incomplete:** review the files named in the error. Valid notes are
  processed; malformed notes are reported instead of silently rewritten.
- **A note was edited outside cog-brain:** run `cog-brain reindex`, or run
  `cog-brain-index --watch` while editing. Successful writes through the API
  request indexing automatically; raw daily captures stay outside ordinary search.

## Development

See [AGENTS.md](../AGENTS.md) for repository structure and checks. From a checkout:

```bash
uv sync
uv run python tests/test_local_api.py
uv run python tests/test_harnesses.py
uv run python tests/test_graph_ingest.py
uv run python tests/test_config.py
```

These tests use temporary data. The older `test_server.py` and `probe_e2e.py`
operate against the configured vault; review their setup before running them.
