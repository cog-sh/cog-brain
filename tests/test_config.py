"""Config resolution: env > file > default (spawned so import happens per-case)."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
fails = []


def check(name, cond, detail=""):
    print(("  ok  " if cond else " FAIL ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def describe(env):
    code = "import json;from cog_brain import config;print(json.dumps(config.describe()))"
    e = {k: v for k, v in os.environ.items() if not k.startswith("COG_BRAIN_")}
    e.update({"PYTHONPATH": str(ROOT / "src")})
    e.update(env)
    r = subprocess.run([sys.executable, "-c", code], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


td = tempfile.mkdtemp()
cfg = Path(td) / "config.toml"
cfg.write_text('backend = "markdown"\nvault = "~/some-vault"\n')

d = describe({"COG_BRAIN_CONFIG": str(cfg)})
check("file backend wins over default", d["resolved"]["backend"] == "markdown", str(d["resolved"]))
check("file source recorded", d["sources"]["backend"] == "file", str(d["sources"]))
check("file vault expanded", d["resolved"]["vault"].endswith("/some-vault"), d["resolved"]["vault"])
check("unset key stays default", d["sources"]["qdrant_url"] == "default", str(d["sources"]))

d = describe({"COG_BRAIN_CONFIG": str(cfg), "COG_BRAIN_BACKEND": "qdrant"})
check("env overrides file", d["resolved"]["backend"] == "qdrant" and d["sources"]["backend"] == "env",
      json.dumps(d["sources"]))

d = describe({"COG_BRAIN_CONFIG": str(Path(td) / "missing.toml")})
check("missing file ignored", d["config_file_exists"] is False and d["resolved"]["backend"] == "sqlite",
      str(d["resolved"]))

bad = Path(td) / "bad.toml"
bad.write_text("this is not = = toml [[[")
d = describe({"COG_BRAIN_CONFIG": str(bad)})
check("malformed file ignored", d["resolved"]["backend"] == "sqlite", str(d["resolved"]))

print()
print("FAILED:" if fails else "ALL PASSED", ", ".join(fails) if fails else "")
sys.exit(1 if fails else 0)
