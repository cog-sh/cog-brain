"""Smoke test for cog_brain.server — exercises every tool against the real vault."""
import json, sys

import cog_brain.server as vm

VAULT = vm.VAULT
fails = []

def check(name, cond, detail=""):
    print(("  ok  " if cond else " FAIL ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)

def brief(s, n=110):
    return s.replace("\n", " ")[:n]

print("== pure: frontmatter round-trip ==")
fm = {"title": "Rust: владение, Drop", "type": "zettel", "status": "seedling",
      "date": "2026-09-14", "updated": "2026-09-14",
      "tags": ["rust", "learning"], "moc": "[[Rust MOC]]",
      "aliases": ["владение в rust"], "description": "Одно предложение про владение."}
rt = vm.parse_frontmatter(vm.dump_frontmatter(fm)[3:-3])
check("title with ':' survives", rt.get("title") == fm["title"], repr(rt.get("title")))
check("tags survive as list", rt.get("tags") == fm["tags"], repr(rt.get("tags")))
check("moc keeps double brackets", rt.get("moc") == "[[Rust MOC]]", repr(rt.get("moc")))
check("description survives", rt.get("description") == fm["description"], repr(rt.get("description")))
check("aliases survive", rt.get("aliases") == fm["aliases"], repr(rt.get("aliases")))

linkfm = dict(fm, retracted="true", supersedes=[], superseded_by=["[[Rust MOC]]"])
dumped = vm.dump_frontmatter(linkfm)
check("raw_links reads a superseded_by link back as the bare target",
      vm.raw_links(dumped) == ["Rust MOC"], json.dumps(vm.raw_links(dumped)))
check("superseded_by parses back to the bracketed form",
      vm.parse_frontmatter(dumped[3:-3]).get("superseded_by") == ["[[Rust MOC]]"],
      json.dumps(vm.parse_frontmatter(dumped[3:-3]).get("superseded_by")))
_comma = vm.parse_frontmatter(vm.dump_frontmatter(dict(fm, tags=["rust, wasm", "ok"]))[3:-3]).get("tags")
check("a comma inside a quoted list item stays one item", _comma == ["rust, wasm", "ok"], json.dumps(_comma))

print("== read tools ==")
hub = vm.read_note("rust-dlya-novichka-na-primere-cog-sh.md")
check("read_note returns text (the old dead-return bug)", isinstance(hub, str) and len(hub) > 500, brief(hub))
check("read_note max_chars truncates", "[truncated" in vm.read_note("rust-dlya-novichka-na-primere-cog-sh.md", 200))
check("read_note missing file", vm.read_note("nope.md").startswith("not found"))
check("read_note rejects traversal", vm.read_note("../etc/passwd").startswith("error"))

st = json.loads(vm.vault_status())
check("vault_status has counts", st["notes_on_disk"] > 100 and st["notes_indexed"] > 100, json.dumps(st["notes_indexed"]))

li = json.loads(vm.list_notes(tag="rust"))
check("list_notes(tag=rust) finds my notes", li["count"] >= 9, str(li["count"]))
check("list_notes has titles", all(n["title"] for n in li["notes"]), brief(str(li["notes"][0])))

ol = json.loads(vm.outline("cog-sh-rust-runtime-architecture.md"))
check("outline lists headings", len(ol["headings"]) >= 8, str(len(ol["headings"])))
check("outline skips code fences", not any(h["heading"].startswith("flowchart") for h in ol["headings"]))

bl = json.loads(vm.backlinks("Rust MOC.md"))
check("backlinks(Rust MOC) has inbound", bl["inbound_count"] >= 10, str(bl["inbound_count"]))

br = json.loads(vm.broken_links())
check("broken_links finds the known dangling link", any(l["link"] == "How to learn Rust" for l in br["links"]),
      json.dumps(br["links"][:5], ensure_ascii=False))
check("broken_links ignores attachment embeds", not any(
    l["link"].lower().endswith((".png", ".jpg", ".pdf", ".svg")) for l in br["links"]),
    json.dumps([l for l in br["links"] if "." in l["link"]][:5], ensure_ascii=False))
check("broken_links ignores wiki-links inside code spans",
      not any(l["link"] in ("старая-заметка", "wikilinks", "olds-note") for l in br["links"]),
      json.dumps([l for l in br["links"] if l["link"] in ("старая-заметка", "wikilinks", "olds-note")], ensure_ascii=False))
check("raw_links keeps real links and drops code examples",
      vm.raw_links("см. [[Rust MOC]] и `[[нет-такой]]`\n```\n[[тоже-нет]]\n```\n") == ["Rust MOC"],
      json.dumps(vm.raw_links("см. [[Rust MOC]] и `[[нет-такой]]`\n```\n[[тоже-нет]]\n```\n"), ensure_ascii=False))

fr = json.loads(vm.find_related("cog-sh-rust-runtime-architecture.md"))
check("find_related resolves links by stem", any(l.get("file_path") for l in fr["linked_notes"]),
      brief(json.dumps(fr["linked_notes"][:3], ensure_ascii=False)))
check("find_related has semantic neighbours", len(fr["semantic_neighbors"]) >= 3, str(len(fr["semantic_neighbors"])))

ss = json.loads(vm.semantic_search("владение и заимствование в Rust", k=4, chunks_per_note=2))
check("semantic_search carries index_stale", all("index_stale" in it for it in ss), str(ss[0]["index_stale"]) if ss else "empty")
check("semantic_search returns results", len(ss) >= 2, str(len(ss)))

print("== guard rails ==")
check("write_note requires description",
      vm.write_note("tmp-smoke-note.md", "T", "x [[Rust MOC]]", description="  ", auto_index=False).startswith("error"))
check("write_note rejects links that resolve nowhere",
      vm.write_note("tmp-smoke-note.md", "T", "x [[no-such-note-xyz]]", description="d", auto_index=False).startswith("error"))
check("write_note rejects system folders",
      vm.write_note("90-meta/x.md", "T", "x [[Rust MOC]]", description="d", auto_index=False).startswith("error"))
check("update_note without changes errors",
      vm.update_note("rust-cargo-lints-and-gates.md").startswith("error"))

print("== write -> update -> read -> delete cycle (auto-index) ==")
w = json.loads(vm.write_note("tmp-smoke-note.md", "Smoke: временная заметка",
                             "Тело со ссылкой на [[cog-sh-rust-runtime-architecture]].",
                             description="Временная заметка для смоук-теста MCP-сервера.",
                             tags=["smoke"], moc="Rust MOC", aliases=["smoke"], auto_index=True))
check("write_note created + auto-indexed", w["created"] == "tmp-smoke-note.md" and "changed=" in w["index"], brief(str(w)))
check("write_note wrote the description",
      "Временная заметка для смоук-теста" in (VAULT / "tmp-smoke-note.md").read_text())
check("write_note moc is single-wrapped",
      'moc: "[[Rust MOC]]"' in (VAULT / "tmp-smoke-note.md").read_text())

u = json.loads(vm.update_note("tmp-smoke-note.md", content="Дописано.", append=True,
                              tags=["smoke", "updated"], auto_index=True))
check("update_note appended", u["changed"] == ["tags", "body(append)"] and "changed=" in u["index"], brief(str(u)))
after = (VAULT / "tmp-smoke-note.md").read_text()
check("update_note kept the body and appended", "Тело со ссылкой" in after and "Дописано." in after)
check("update_note bumped tags", "updated" in after)
check("update_note preserved title", 'title: "Smoke: временная заметка"' in after, brief(after[:200]))

check("the note is searchable after auto-index", any(
    it["file_path"] == "tmp-smoke-note.md" for it in json.loads(vm.semantic_search("временная заметка smoke", k=5))))

print("== retraction convention (AI-GUIDE failure-path preservation) ==")
r1 = json.loads(vm.write_note("tmp-smoke-retracted.md", "Smoke: снятая заметка",
                              "Почему снято: не сработало потому что тест. См. [[cog-sh-rust-runtime-architecture]].",
                              description="Временная снятая заметка для смоук-теста.",
                              tags=["smoke"], moc="Rust MOC", retracted=True, auto_index=False))
fmr = (VAULT / "tmp-smoke-retracted.md").read_text()
check("write_note records retracted: true", "retracted: true" in fmr, fmr[:160])
check("write_note records an empty superseded_by", "superseded_by: []" in fmr)
check("read_note banners a retracted note", vm.read_note("tmp-smoke-retracted.md").startswith("[RETRACTED NOTE"), 
      vm.read_note("tmp-smoke-retracted.md")[:60])
r2 = json.loads(vm.update_note("tmp-smoke-retracted.md", retracted=False,
                               superseded_by=["cog-sh-rust-runtime-architecture"], auto_index=False))
check("update_note can clear the flag and set superseded_by",
      r2["changed"] == ["superseded_by", "retracted"] and "retracted: false" in (VAULT / "tmp-smoke-retracted.md").read_text(),
      json.dumps(r2["changed"]))
vm.update_note("tmp-smoke-retracted.md", retracted=True, auto_index=False)
idx = vm.index_now()
hits = json.loads(vm.semantic_search("снятая заметка smoke тест", k=6))
mine = [h for h in hits if h["file_path"] == "tmp-smoke-retracted.md"]
check("a retracted note stays searchable but is flagged", bool(mine) and mine[0].get("retracted") is True,
      json.dumps(mine[0] if mine else hits[0], ensure_ascii=False)[:200])
ln = json.loads(vm.list_notes(tag="smoke"))
check("list_notes surfaces the flag", any(n["retracted"] for n in ln["notes"]), json.dumps(ln["notes"], ensure_ascii=False)[:150])

(VAULT / "tmp-smoke-note.md").unlink()
(VAULT / "tmp-smoke-retracted.md").unlink()
print("  index after delete:", vm.index_now())
check("temp note removed from disk", not (VAULT / "tmp-smoke-note.md").exists())
st2 = json.loads(vm.vault_status())
check("vault_status reports last_run after a run", st2["last_run"] is not None, str(st2["last_run"]))
check("vault_status is fresh right after a run", st2["stale_count"] == 0, json.dumps(st2["stale"][:5]))
check("indexed count matches disk after cleanup", st2["notes_indexed"] == st2["notes_on_disk"],
      f"{st2['notes_indexed']} vs {st2['notes_on_disk']}")

print()
print("FAILED:" if fails else "ALL PASSED", ", ".join(fails) if fails else "")
sys.exit(1 if fails else 0)
