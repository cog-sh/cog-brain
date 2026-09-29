"""graph.lint / graph.export_* / ingest.import_chats against a synthetic vault."""
import json
import os
import sys
import tempfile
from pathlib import Path

TD = tempfile.mkdtemp()
os.environ["COG_BRAIN_VAULT"] = TD
os.environ["COG_BRAIN_BACKEND"] = "markdown"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cog_brain import graph, ingest  # noqa: E402

V = Path(TD)
fails = []


def check(name, cond, detail=""):
    print(("  ok  " if cond else " FAIL ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def note(name, fm, body):
    (V / name).write_text(f"{fm}\n{body}", encoding="utf-8")


FM = '---\ntitle: "{t}"\ntype: concept\ndescription: "d"\n---'
note("a.md", FM.format(t="A"), "# A\nsee [[b]]\n")
note("b.md", FM.format(t="B"), "# B\nsee [[a]]\n")
note("orphan.md", FM.format(t="Orphan"), "# O\n" + "word " * 50 + "\n")
note("stub.md", FM.format(t="Stub"), "short\n")
note("c.md", FM.format(t="C"), "# C\nsee [[missing-target]] and [[a]]\n")
(V / "noname.md").write_text("no frontmatter\n", encoding="utf-8")

lint = graph.lint()
check("pages counted", lint["pages"] == 6, str(lint["pages"]))
check("broken link found", any(b["link"] == "missing-target" for b in lint["broken_links"]),
      json.dumps(lint["broken_links"]))
check("orphans include orphan+stub", {"orphan.md", "stub.md"} <= set(lint["orphans"]),
      json.dumps(lint["orphans"]))
check("stub detected", "stub.md" in lint["stubs"], json.dumps(lint["stubs"]))
check("missing frontmatter flagged",
      any(m["file_path"] == "noname.md" for m in lint["missing_frontmatter"]),
      json.dumps(lint["missing_frontmatter"]))
check("linked pages are not orphans", "a.md" not in lint["orphans"] and "b.md" not in lint["orphans"])

csvout = graph.export_csv()
check("csv header", csvout.startswith("source,target"))
check("csv has an edge", "a.md,b.md" in csvout, csvout)
gml = graph.export_graphml()
check("graphml root", "<graphml" in gml and gml.strip().endswith("</graphml>"))
check("graphml node + attr", 'id="a.md"' in gml and 'key="type"' in gml)
check("graphml edge", "<edge " in gml)

h = graph.health()
check("health pages", h["pages"] == 6, str(h["pages"]))
check("health orphans >=2", h["orphan_count"] >= 2, str(h["orphan_count"]))
check("health has verdicts", set(h["verdicts"]) == {"orphans", "degree", "connectivity"})

export = [
    {"title": "Empty ChatGPT", "create_time": 1730000000, "mapping": {}},
    {"name": "Claude Chat", "created_at": "2026-01-02T00:00:00Z",
     "chat_messages": [{"sender": "human", "text": "hello " * 60},
                       {"sender": "assistant", "text": [{"type": "text", "text": "hi " * 60}]}]},
]
src = V / "chats.json"
src.write_text(json.dumps(export), encoding="utf-8")
r = ingest.import_chats(src, V / "raw", min_words=10)
check("ingest wrote one note", len(r["written"]) == 1, json.dumps(r))
made = Path(r["written"][0]).read_text(encoding="utf-8")
check("ingest note has frontmatter+source", "type: source" in made and "source: chats.json" in made)
check("ingest flattened both senders", "**human:**" in made and "**assistant:**" in made)

print()
print("FAILED:" if fails else "ALL PASSED", ", ".join(fails) if fails else "")
sys.exit(1 if fails else 0)
