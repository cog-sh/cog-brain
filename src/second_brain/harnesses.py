"""Per-harness MCP wiring: one stdio server, many config dialects.

``second-brain`` speaks standard MCP over stdio, so the *server* is already
harness-neutral. The only per-harness part is **where** each client keeps its
MCP config and **how** it spells a local (stdio) server. This module is that
translation table plus a render/merge layer, so ``second-brain config`` can
print a paste-ready snippet and ``second-brain install`` can merge it into the
right file without hand-editing JSON/TOML.

Adding a harness = one ``Harness`` row in :data:`HARNESSES` (+ a render branch
if its dialect is new). No other code changes.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

NAME = "second-brain"

# Source for `uvx --from <source> second-brain`. Override per-invocation with
# `--source`; override the default for everyone with SECOND_BRAIN_MCP_SOURCE.
# A git URL, a local path, or a PyPI project name all work.
DEFAULT_SOURCE = os.environ.get(
    "SECOND_BRAIN_MCP_SOURCE", "git+https://github.com/OWNER/second-brain"
)

# Formats: how a client spells a local server.
FMT_MCPSERVERS = "mcpservers"   # {"mcpServers": {name: {command, args, env}}}
FMT_VSCODE = "vscode"           # {"servers":   {name: {type, command, args, env}}}
FMT_OPENCODE = "opencode"       # {"mcp": {name: {type: local, command: [...], environment}}}
FMT_CODEX = "codex"             # [mcp_servers.name] TOML


@dataclass(frozen=True)
class Harness:
    name: str
    fmt: str
    global_path: str
    project_path: str | None
    doc: str


HARNESSES: dict[str, Harness] = {
    "omp": Harness(
        "omp", FMT_MCPSERVERS,
        "~/.omp/agent/mcp.json", None,
        "oh-my-pi — user-level MCP config",
    ),
    "claude-code": Harness(
        "claude-code", FMT_MCPSERVERS,
        "~/.claude.json", ".mcp.json",
        "Claude Code — project .mcp.json (recommended) or global ~/.claude.json",
    ),
    "cursor": Harness(
        "cursor", FMT_MCPSERVERS,
        "~/.cursor/mcp.json", ".cursor/mcp.json",
        "Cursor — project .cursor/mcp.json or global ~/.cursor/mcp.json",
    ),
    "codex": Harness(
        "codex", FMT_CODEX,
        "~/.codex/config.toml", ".codex/config.toml",
        "OpenAI Codex CLI — [mcp_servers] TOML",
    ),
    "opencode": Harness(
        "opencode", FMT_OPENCODE,
        "~/.config/opencode/opencode.json", "opencode.json",
        "opencode — mcp.<name> map",
    ),
    "vscode": Harness(
        "vscode", FMT_VSCODE,
        "~/Library/Application Support/Code/User/mcp.json", ".vscode/mcp.json",
        "VS Code (GitHub Copilot) — servers map",
    ),
    "windsurf": Harness(
        "windsurf", FMT_MCPSERVERS,
        "~/.codeium/windsurf/mcp_config.json", None,
        "Windsurf — mcpServers map",
    ),
    "gemini-cli": Harness(
        "gemini-cli", FMT_MCPSERVERS,
        "~/.gemini/settings.json", ".gemini/settings.json",
        "Gemini CLI — mcpServers map",
    ),
    "generic": Harness(
        "generic", FMT_MCPSERVERS,
        "(print only)", None,
        "Any MCP client: paste the mcpServers block into its config",
    ),
}

ALIASES = {
    "claude": "claude-code",
    "open-code": "opencode",
    "code": "vscode",
    "gemini": "gemini-cli",
    "oh-my-pi": "omp",
    "pi": "omp",
}


def resolve(name: str) -> Harness:
    key = ALIASES.get(name, name)
    if key not in HARNESSES:
        raise KeyError(f"unknown harness: {name!r} (known: {', '.join(sorted(HARNESSES))})")
    return HARNESSES[key]


# --------------------------------------------------------------------------- spec

def launch_argv(source: str | None = None, extra_args: list[str] | None = None) -> list[str]:
    """`uvx --from <source> second-brain [extra]` — clone-free."""
    return ["uvx", "--from", source or DEFAULT_SOURCE, NAME, *(extra_args or [])]


def build_spec(source: str | None = None, env: dict[str, str] | None = None,
               extra_args: list[str] | None = None) -> dict:
    argv = launch_argv(source, extra_args)
    return {
        "command": argv[0],
        "args": argv[1:],
        "env": {k: v for k, v in (env or {}).items() if v},
    }


# --------------------------------------------------------------------------- entries

def _mcpservers_entry(spec: dict) -> dict:
    entry = {"type": "stdio", "command": spec["command"], "args": spec["args"]}
    if spec.get("env"):
        entry["env"] = spec["env"]
    return entry


def _opencode_entry(spec: dict) -> dict:
    entry = {"type": "local", "command": [spec["command"], *spec["args"]], "enabled": True}
    if spec.get("env"):
        entry["environment"] = spec["env"]
    return entry


def payload_for(h: Harness, spec: dict) -> dict:
    """The JSON body a paste/merge would contain (codex returns {} — see render)."""
    if h.fmt == FMT_MCPSERVERS:
        return {"mcpServers": {NAME: _mcpservers_entry(spec)}}
    if h.fmt == FMT_VSCODE:
        return {"servers": {NAME: _mcpservers_entry(spec)}}
    if h.fmt == FMT_OPENCODE:
        return {"mcp": {NAME: _opencode_entry(spec)}}
    return {}


def render(h: Harness, spec: dict) -> str:
    """Paste-ready text for this harness."""
    if h.fmt == FMT_CODEX:
        lines = [f"[mcp_servers.{NAME}]", f'command = "{spec["command"]}"',
                 "args = [" + ", ".join(json.dumps(a) for a in spec["args"]) + "]"]
        if spec.get("env"):
            lines.append("")
            lines.append(f"[mcp_servers.{NAME}.env]")
            lines += [f'{k} = {json.dumps(v)}' for k, v in spec["env"].items()]
        return "\n".join(lines) + "\n"
    return json.dumps(payload_for(h, spec), indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- merge

def target_path(h: Harness, scope: str, cwd: Path | None = None) -> Path:
    if scope == "project":
        if not h.project_path:
            raise ValueError(f"{h.name} has no project-level config; use --scope global")
        return (cwd or Path.cwd()) / h.project_path
    return Path(os.path.expanduser(h.global_path))


def _merge_json(path: Path, h: Harness, spec: dict) -> str:
    data: dict = {}
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            data = json.loads(raw)
    if h.fmt == FMT_OPENCODE:
        data.setdefault("$schema", "https://opencode.ai/config.json")
        data.setdefault("mcp", {})[NAME] = _opencode_entry(spec)
        what = f"mcp.{NAME}"
    elif h.fmt == FMT_VSCODE:
        data.setdefault("servers", {})[NAME] = _mcpservers_entry(spec)
        what = f"servers.{NAME}"
    else:
        data.setdefault("mcpServers", {})[NAME] = _mcpservers_entry(spec)
        what = f"mcpServers.{NAME}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return what


_HEADER = re.compile(r"^\[mcp_servers\.%s(?:\.[^\]]*)?\]" % re.escape(NAME))
_ANY_HEADER = re.compile(r"^\[")


def _strip_toml_block(text: str) -> str:
    """Drop our [mcp_servers.second-brain*] tables, keep everything else."""
    out, skipping = [], False
    for line in text.splitlines():
        if _HEADER.match(line):
            skipping = True
            continue
        if skipping and _ANY_HEADER.match(line):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out).strip("\n")


def _merge_toml(path: Path, spec: dict) -> str:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    body = _strip_toml_block(existing)
    block = render(HARNESSES["codex"], spec).rstrip("\n")
    text = (body + "\n\n" + block + "\n") if body else (block + "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return f"[mcp_servers.{NAME}]"


def merge(path: Path, h: Harness, spec: dict) -> str:
    if h.fmt == FMT_CODEX:
        return _merge_toml(path, spec)
    return _merge_json(path, h, spec)
