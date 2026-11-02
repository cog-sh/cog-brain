# cog-brain

**Your notes. Your agents. One memory.**

Keep decisions, sources and next steps in Markdown. Let your coding agents bring
that knowledge into your work, so the next session can pick up where you left off.

cog-brain connects a personal knowledge base to your coding agents. You read and
edit the notes in Obsidian or your editor; agents search them, save useful findings
and maintain a short handoff for each project.

[Get started](#get-started) · [Daily workflow](#a-day-with-cog-brain) ·
[Integrations](#choose-your-integration) · [Reference](docs/reference.md)

## What it helps with

- **Continue a project.** Bring its goal, constraints and next action into a new
  session, including when you switch agents.
- **Remember the reason.** Keep the decision, the evidence and the conditions
  under which it applies, alongside links to the original sources.
- **Capture without organizing first.** Save an idea or a link in today's daily
  note. Turn it into lasting knowledge when it proves useful.
- **Keep corrections visible.** Withdrawn claims remain searchable with a warning
  and a link to their replacement.

The working loop is small: recall context, do the work, save what you verified,
leave a useful next step.

## Get started

You'll need **macOS or Linux, Python 3.12+, [uv](https://docs.astral.sh/uv/), and an
existing folder of Markdown notes**. Obsidian is optional. The default search
engine runs locally without Docker or an embedding service.

### 1. Install and point it at your notes

```bash
uv tool install git+https://github.com/cog-sh/cog-brain
```

Point it at your existing vault and build the local index:

```bash
cog-brain setup --vault ~/Notes
cog-brain doctor
```

Setup saves the vault and backend to `~/.config/cog-brain/config.toml`, preserving
other settings and backing up changes. SQLite is the default: no Docker, account
or model download. Replace `~/Notes` with your folder of notes.

### 2. Connect your agent

Choose your client (the [integration table](#choose-your-integration) lists all options):

```bash
cog-brain install --harness codex --mode code
# Other examples:
cog-brain install --harness claude-code --mode code
cog-brain install --harness opencode --mode code
```

Restart the client and enable its hooks if prompted. In Codex, open **`/hooks`**
and approve the new cog-brain handlers. A managed instruction provides CLI recall
while those hooks await review.

Installation adds a skill and the client's hooks, extension or instructions.
It backs up changes, preserves unrelated settings and disables only the existing
cog-brain MCP entry. Use `--keep-mcp` to retain it. Add `--scope project` to install
in the current repository (required for VS Code).

### 3. Give your project a starting point

Open a repository in your agent and ask:

> Create a cog-brain project card for this repository. Link it to a relevant
> existing note. Record the goal, current state, constraints and next step.

That card binds the repository to its memory. Future tasks can retrieve the card
and relevant notes automatically. If a project has no card, cog-brain reports
that explicitly.

Try it with an ordinary question:

> Where should we pick up on this project?

## A day with cog-brain

| When | What you do | What the agent keeps |
| --- | --- | --- |
| Start a session | Describe the task | The project card and relevant evidence in context |
| Find something interesting | “Capture this link for later” | Raw material in `daily/`, with its source |
| Settle a decision | “Save why we chose this” | A linked note with the reason, scope and verification |
| Finish or switch projects | “Update the handoff” | Current state, checks, blockers and the next action |

Once a week, review the captures worth developing and the projects still active.
Daily notes stay out of ordinary knowledge retrieval, so an unprocessed thought
doesn't become a confirmed fact just because it was saved.

You can keep using your existing vault. New knowledge notes use a short
description and a link to an existing note; project cards stay brief enough to
read at the start of a session.

See the [note formats and writing guide](src/cog_brain/assets/notes.md) for the
conventions shared by you and your agents.

## Choose your integration

| Client (`--harness`) | How memory reaches the agent |
| --- | --- |
| Codex (`codex`) | Session/prompt hooks; AGENTS fallback; hook approval required |
| Oh My Pi (`omp`), Pi (`pi`) | Native extensions before work and after compaction |
| Claude Code (`claude-code`) | SessionStart and UserPromptSubmit hooks; CLAUDE.md fallback |
| Gemini CLI (`gemini-cli`) | SessionStart and BeforeAgent hooks; GEMINI.md fallback |
| Cursor (`cursor`) | SessionStart hook; project rule for task-time recall |
| OpenCode (`opencode`) | Native context hook; V2 default, `--opencode-version 1` for V1 |
| Copilot CLI (`copilot`) | Instructions ask the agent to recall through its executor |
| VS Code Copilot (`vscode`) | Repository instructions and skill; project scope only |
| Windsurf (`windsurf`) | Global/project rules ask the agent to recall through its executor |
| Other MCP clients | Optional [MCP adapter](docs/reference.md#mcp-clients) |

All code integrations use the existing executor and local runtime. Hook-based
clients can receive a bounded project packet before answering; instruction-based
clients depend on the agent following the recall rule. Cursor's startup hook
loads context once per session; its prompt-validation hook cannot inject context.
Client permissions and hook support still apply.

For marketplace installation and `/brain-*` commands, see
[cog-brain-plugins](https://github.com/cog-sh/cog-brain-plugins).

**Code Mode** means an agent can search, read several notes and filter the results
inside one program. Only what the program returns needs to enter the model's
context. MCP remains available for clients that use it.

For example, inside a Python environment with cog-brain installed:

```python
import json
from cog_brain import Brain

brain = Brain()
found = brain.search("why did we choose this database?", project="my-project", limit=4)
notes = [
    brain.read(hit["file_path"], max_chars=1200)
    for hit in found["hits"][:2]
]
print(json.dumps({"notes": notes, "warnings": found["warnings"]}, ensure_ascii=False))
```

Replace `my-project` with your project card's identifier. See the
[API and integration reference](docs/reference.md) for setup details and commands.

## Your knowledge stays readable

The vault is the source of truth. Notes remain ordinary Markdown with YAML
properties and `[[wiki-links]]`. The search index can be rebuilt from those files.

cog-brain preserves existing YAML fields and comments when editing notes.
Writes are atomic, concurrent appends are serialized, and replacing a note's
body through the Python API requires the revision you read. Indexing failures
are reported separately from a successful note save.

You can edit in Obsidian or another editor. External editors do not participate
in cog-brain's locks; detected conflicts require a fresh read. Malformed YAML is
reported instead of silently rewritten.

Files and indexes live locally by default. Retrieved notes become part of the
context sent to your chosen agent's model provider. With vector search enabled,
embedding requests go to the endpoint you configure.

## Search that fits your setup

| Engine | Best starting point for | What it needs |
| --- | --- | --- |
| **SQLite — default** | Local keyword search with a persistent index | No background services |
| **Markdown** | Searching directly from the vault without a persistent index | No background services |
| **Qdrant** | Hybrid semantic and keyword search | Qdrant and an embedding endpoint |

Automatic lifecycle context uses local keyword search even when Qdrant is your
configured engine, so it doesn't wait for the vector services to start.

After editing notes outside cog-brain, run `cog-brain reindex`. During a longer
editing session, `cog-brain-index --watch` keeps the index updated.

### Want semantic search?

```bash
cog-brain setup --backend qdrant --vault ~/Notes --dry-run
cog-brain setup --backend qdrant --vault ~/Notes
```

Setup reuses healthy Qdrant/Ollama endpoints. If either service is missing locally,
it needs a running [Docker installation](https://docs.docker.com/get-started/get-docker/)
and starts only that service. It downloads the embedding model when needed,
checks its 1024-dimensional output and collection compatibility, then saves the
backend and indexes your vault. The first run needs internet, disk space and time.

Managed services bind to `127.0.0.1`, restart with Docker and keep data in named
volumes. Setup never deletes a container, volume or collection. You can return to
service-free search with `cog-brain setup --backend sqlite`; vector data stays in
place. See [bootstrap details](docs/reference.md#service-setup).

## Project status

cog-brain is an **early release**. Local API, note safety and integration behavior
have [isolated regression coverage](tests/test_local_api.py). Autonomous CLI recall
has also been checked in a live Codex session. Additional client adapters and
service bootstrap have isolated regression coverage; complete live LLM workflows
across every client and fresh Docker downloads are not yet validated.

Automatic recall requires a bound project card and an enabled client integration.
The agent saves decisions and handoffs through the API; hooks do not archive
every conversation or turn every answer into a note.

## Go further

- [Configuration, integrations and troubleshooting](docs/reference.md)
- [Note formats and daily workflow](src/cog_brain/assets/notes.md)
- [Contributing and running checks](AGENTS.md)
- [Background reading](docs/resources.md)

[MIT licensed](LICENSE). Built by [cog-sh](https://github.com/cog-sh).
