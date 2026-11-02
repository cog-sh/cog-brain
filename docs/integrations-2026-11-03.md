# Integration and bootstrap verification — 2026-11-03

Core 0.2.0 and plugin distribution 0.3.0 add code-mode installers for Claude Code,
Cursor, Gemini CLI, OpenCode, Copilot CLI, VS Code and Windsurf alongside existing
Codex/OMP/Pi support. Instruction-based clients are documented separately from
native context hooks. Default plugins no longer require MCP; compatibility
packages preserve the previous MCP bridges.

## Evidence

- `tests/test_setup_clients.py`: 19 isolated tests, including configuration
  preservation, service reuse, absent Docker, failed embeddings, incompatible
  collections, collection authorization errors, owned/foreign containers,
  remote dry-run plans, installer idempotence, client output protocols and
  generated OpenCode V1/V2 execution through a real local Python hook.
- Existing `test_local_api.py`: 20 tests passed, including isolated MCP and native
  adapters. Harness, graph/ingest and config suites also passed on temporary data.
- Plugin distribution: six deterministic tests passed; runtime hashes matched
  canonical assets; Claude validated the marketplace and both package manifests.
- OpenCode 2.1.4: installed into a temporary project, with isolated XDG/config/state
  and no explicit plugin config. A private server on an ephemeral loopback port
  reported `cog-brain` as `active` through `plugin.list`. The initial response can
  be empty while startup proceeds; polling confirmed automatic directory discovery.
  No model request was made. The private server was terminated after the check.

Fresh Docker image/model downloads and complete live LLM workflows for every
client were not run. Container/bootstrap failure paths use mocks; existing local
Qdrant/Ollama and personal client configuration were not replaced. Earlier Codex,
OMP and Pi live-workflow limits remain in [the prior report](verification-2026-11-03.md).

## Primary integration references

- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Cursor hooks](https://cursor.com/docs/hooks): sessionStart supplies context;
  beforeSubmitPrompt validates/blocks and cannot inject it.
- [Gemini CLI hook reference](https://geminicli.com/docs/hooks/reference/)
- [OpenCode server plugins](https://opencode.ai/v2/docs/build/plugins/server/):
  `ctx.location.directory`, typed context parts and MCP transforms.
- [OpenCode plugin discovery](https://opencode.ai/v2/docs/plugins)
- [Copilot CLI custom instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions)
- [Qdrant quickstart](https://qdrant.tech/documentation/quickstart/)
- [Ollama model pull API](https://docs.ollama.com/api/pull)

Markdown remains authoritative; setup uses persistent named volumes and never
removes existing service data. Configuration changes happen after model/readiness
checks. `tomlkit` preserves comments and unknown settings during setup writes.
