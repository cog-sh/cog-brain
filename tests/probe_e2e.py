"""End-to-end probe of the second-brain MCP server over the REAL stdio protocol.

Spawns a fresh server (`python -m second_brain.server`), enumerates tools/list,
exercises a representative tools/call set, then proves the frontmatter
list-quoting fix on the wire: write -> update(superseded_by) -> on-disk quoting
-> backlinks edge present -> broken_links has no phantom -> cleanup.
"""
import asyncio, json, sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from second_brain import config

VAULT = config.VAULT
PROBE = "zz-mcp-probe.md"
TARGET = "rust-cargo-lints-and-gates"

fails = []

def check(name, cond, detail=""):
    print(("  ok  " if cond else " FAIL ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)

def brief(s, n=100):
    return str(s).replace("\n", " ")[:n]

async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "second_brain.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            init = await s.initialize()
            check("initialize handshake", init.serverInfo.name == "second-brain", init.serverInfo.name)

            listed = await s.list_tools()
            names = sorted(t.name for t in listed.tools)
            print("  tools:", ", ".join(names))
            for want in ["vault_status", "list_notes", "outline", "read_note", "semantic_search",
                         "find_related", "backlinks", "broken_links", "graph_overview",
                         "write_note", "update_note", "index_now"]:
                check(f"tools/list exposes {want}", want in names)

            async def call(tool, args):
                r = await s.call_tool(tool, args)
                txt = r.content[0].text
                try:
                    return json.loads(txt)
                except json.JSONDecodeError:
                    return txt

            print("== read tools over the wire ==")
            st = await call("vault_status", {})
            check("vault_status counts", st["notes_on_disk"] > 300 and st["notes_on_disk"] == st["notes_indexed"],
                  f"{st['notes_on_disk']} on disk / {st['notes_indexed']} indexed")
            note = "cog-sh-rust-runtime-architecture.md"
            ol = await call("outline", {"file_path": note})
            check("outline returns headings", len(ol.get("headings", [])) > 3, brief(json.dumps(ol, ensure_ascii=False)))
            rn = await call("read_note", {"file_path": note, "max_chars": 200})
            check("read_note truncates at max_chars", "[truncated" in rn, brief(rn, 60))
            ss = await call("semantic_search", {"query": "слои T0 T6", "k": 4, "chunks_per_note": 3})
            by_file = {}
            for c in ss:
                by_file.setdefault(c["file_path"], []).append(c["heading_path"])
            check("chunks_per_note yields >1 chunk of the same note",
                  any(len(v) > 1 for v in by_file.values()), brief(json.dumps(by_file, ensure_ascii=False)))
            check("every search hit carries index_stale", all("index_stale" in c for c in ss))
            fr = await call("find_related", {"file_path": note, "k": 2})
            check("find_related gives neighbours + links", "linked_notes" in fr and len(fr["linked_notes"]) > 0,
                  brief(json.dumps(list(fr.keys()))))
            bl = await call("backlinks", {"file_path": "Rust MOC.md"})
            check("backlinks counts inbound", bl["inbound_count"] >= 10, str(bl["inbound_count"]))
            bro = await call("broken_links", {"limit": 3})
            check("broken_links finds real breakage", bro["count"] > 0, str(bro["count"]))
            go = await call("graph_overview", {"k": 3})
            check("graph_overview finds hubs + orphans",
                  len(go["hubs_top_outgoing"]) == 3 and go["notes_total"] > 300 and len(go["orphan_notes"]) > 0,
                  f"total={go['notes_total']} orphans={len(go['orphan_notes'])} "
                  f"top={go['hubs_top_outgoing'][0]['file_path']}")
            ln = await call("list_notes", {"tag": "rust"})
            check("list_notes filters by tag", ln["count"] > 5, str(ln["count"]))

            print("== guard rails over the wire ==")
            e1 = await call("write_note", {"file_path": "zz-x.md", "title": "t", "content": "[[Rust MOC]]", "description": " "})
            check("blank description refused", isinstance(e1, str) and e1.startswith("error: description is required"), brief(e1))
            e2 = await call("write_note", {"file_path": "zz-x.md", "title": "t", "content": "[[нет-такой-xyz]]", "description": "d"})
            check("note with zero resolvable links refused", isinstance(e2, str) and e2.startswith("error: no [[wiki-link]] resolves"), brief(e2))
            e3 = await call("write_note", {"file_path": "90-meta/zz-x.md", "title": "t", "content": "[[Rust MOC]]", "description": "d"})
            check("system folder refused", isinstance(e3, str) and e3.startswith("error: system folders"), brief(e3))
            e4 = await call("update_note", {"file_path": "zz-absent.md", "title": "t"})
            check("update of a missing note refused", isinstance(e4, str) and e4.startswith("not found"), brief(e4))

            print("== the frontmatter list-quoting fix, on the wire ==")
            w = await call("write_note", {"file_path": PROBE, "title": "ZZ проба MCP",
                                          "content": "Проба. Ведёт на [[Rust MOC]].",
                                          "description": "Временная заметка для сквозной пробы MCP.",
                                          "tags": ["mcp-probe"], "auto_index": False})
            check("write_note returns unresolved_links + index status", "unresolved_links" in w and "index" in w, brief(json.dumps(w)))
            u = await call("update_note", {"file_path": PROBE, "content": "## Почему снято\n\nПроба.",
                                           "append": True, "retracted": True, "superseded_by": [TARGET], "auto_index": False})
            check("update_note reports superseded_by", "superseded_by" in u["changed"], json.dumps(u["changed"]))

            raw = (VAULT / PROBE).read_text()
            line = next(l for l in raw.splitlines() if l.startswith("superseded_by:"))
            check("the list item is quoted on disk (no [[[ merge)", line == f'superseded_by: ["[[{TARGET}]]"]', line)

            ix = await call("index_now", {})
            check("index_now reindexes", "changed=1" in ix, ix)

            bl2 = await call("backlinks", {"file_path": f"{TARGET}.md"})
            check("the supersession edge IS counted in backlinks",
                  any(i["file_path"] == PROBE for i in bl2["inbound"]),
                  f"inbound={bl2['inbound_count']} {brief(json.dumps(bl2['inbound'], ensure_ascii=False))}")
            bro2 = await call("broken_links", {"limit": 500})
            phantoms = [l for l in bro2["links"] if l["file_path"] == PROBE]
            check("broken_links has NO phantom from the probe", phantoms == [], json.dumps(phantoms, ensure_ascii=False))
            rn2 = await call("read_note", {"file_path": PROBE})
            check("read_note still banners the retraction", str(rn2).startswith("[RETRACTED NOTE"), brief(rn2, 70))

            print("== cleanup ==")
            (VAULT / PROBE).unlink()
            ix2 = await call("index_now", {})
            check("probe note deleted and de-indexed", not (VAULT / PROBE).exists() and "deleted=1" in ix2, ix2)

    print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
    return 1 if fails else 0

sys.exit(asyncio.run(main()))
