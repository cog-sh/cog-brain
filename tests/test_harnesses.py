"""Harness emitter: every dialect renders, TOML merge keeps foreign tables."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cog_brain import harnesses as H  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("  ok  " if cond else " FAIL ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


spec = H.build_spec(source="git+https://example.com/x", env={"COG_BRAIN_VAULT": "~/V"})
KEY = {H.FMT_MCPSERVERS: "mcpServers", H.FMT_VSCODE: "servers", H.FMT_OPENCODE: "mcp"}

for name in sorted(H.HARNESSES):
    h = H.resolve(name)
    text = H.render(h, spec)
    check(f"render {name}", bool(text.strip()))
    if h.fmt == H.FMT_CODEX:
        check(f"{name} toml table", f"[mcp_servers.{H.NAME}]" in text)
        check(f"{name} toml env table", f"[mcp_servers.{H.NAME}.env]" in text)
    else:
        d = json.loads(text)
        entry = d[KEY[h.fmt]][H.NAME]
        check(f"{name} key {KEY[h.fmt]}", H.NAME in d[KEY[h.fmt]])
        if h.fmt == H.FMT_OPENCODE:
            check(f"{name} command is an array", isinstance(entry["command"], list), str(entry["command"]))
        else:
            check(f"{name} has command+args", entry.get("command") and entry.get("args"))

check("alias claude -> claude-code", H.resolve("claude").name == "claude-code")
check("alias pi -> omp", H.resolve("pi").name == "omp")
try:
    H.resolve("nope")
    check("unknown harness raises", False)
except KeyError:
    check("unknown harness raises", True)

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "config.toml"
    p.write_text(f'[other]\nx = 1\n\n[mcp_servers.{H.NAME}]\ncommand = "old"\n')
    H.merge(p, H.resolve("codex"), spec)
    body = p.read_text()
    check("codex keeps foreign table", "[other]" in body)
    check("codex has exactly one cog-brain block", body.count(f"[mcp_servers.{H.NAME}]") == 1, body)
    check("codex updated the command", '"old"' not in body and '"uvx"' in body)

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "mcp.json"
    H.merge(p, H.resolve("cursor"), spec)
    H.merge(p, H.resolve("cursor"), spec)
    d = json.loads(p.read_text())
    check("json merge is idempotent", list(d["mcpServers"]) == [H.NAME], str(list(d)))

print()
print("FAILED:" if fails else "ALL PASSED", ", ".join(fails) if fails else "")
sys.exit(1 if fails else 0)
