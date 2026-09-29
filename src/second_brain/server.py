"""MCP server for the SECOND_BRAIN vault: hybrid semantic search over Qdrant + safe read/write.

Read:
  vault_status()                       -> index health (notes on disk vs indexed, last run, what changed)
  list_notes(tag, folder, limit)       -> cheap inventory of notes
  outline(file_path)                   -> headings only, no body
  read_note(file_path, max_chars)      -> full note text
  semantic_search(query, k, tag, folder, chunks_per_note) -> ranked chunks with file_path citations
  find_related(file_path, k)           -> semantic neighbours + 1-hop wiki-link expansion
  backlinks(file_path, k)              -> who links here + where this note points
  broken_links(limit)                  -> wiki-links that resolve to no existing note

Write:
  write_note(...)   -> creates a schema-valid note (description required; link targets checked)
  update_note(...)  -> patches frontmatter and/or body in place, bumps `updated`
  index_now(full)   -> runs the incremental indexer (write/update call it automatically)

Everything here resolves wiki-link targets by note STEM and TITLE, so `[[some-note]]` and a
Russian `title` both work. The index lives in ``$SECOND_BRAIN_STATE_DIR/index.db`` + Qdrant;
``vault_status()`` is the authority on whether it is current — trust it before trusting a
search result.

Verify after editing this file: ``uv run python tests/test_server.py`` (exercises every tool
below against the live vault and exits non-zero on failure).
"""
import json, re, sqlite3, subprocess, sys
from pathlib import Path
from datetime import date, datetime

from mcp.server.fastmcp import FastMCP
from qdrant_client import QdrantClient, models
import requests
from fastembed import SparseTextEmbedding

from second_brain import config
from second_brain import indexer as vix

VAULT = config.VAULT
QDRANT_URL = config.QDRANT_URL
COLLECTION = config.COLLECTION
EMBED_MODEL = config.EMBED_MODEL
OLLAMA = config.OLLAMA
QUERY_PREFIX = "Instruct: Given a user query, retrieve relevant notes from a personal knowledge base\nQuery: "

SYSTEM_PREFIXES = ("daily/", "attachments/", "90-meta/", "90-archive/", ".obsidian/", ".trash/")
ATTACHMENT_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp|avif|pdf|mp4|mov|webm|m4a|mp3|excalidraw|canvas)$", re.IGNORECASE)
FM_ORDER = ["title", "type", "status", "date", "updated", "tags", "moc", "aliases", "description",
            "retracted", "supersedes", "superseded_by"]

mcp = FastMCP("second-brain")
client = QdrantClient(url=QDRANT_URL, timeout=60)
_sparse = None


# --------------------------------------------------------------------------- search

def embed_query(q: str) -> list[float]:
    r = requests.post(OLLAMA, json={"model": EMBED_MODEL, "input": [QUERY_PREFIX + q], "keep_alive": "24h"}, timeout=300)
    r.raise_for_status()
    return r.json()["embeddings"][0]

def sparse_one(text: str) -> models.SparseVector:
    global _sparse
    if _sparse is None:
        _sparse = SparseTextEmbedding(model_name="Qdrant/bm25")
    v = next(iter(_sparse.embed([text])))
    return models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist())

def hybrid_search(query: str, k: int, flt: models.Filter | None):
    dense = embed_query(query)
    bm25 = sparse_one(query)
    return client.query_points(
        COLLECTION,
        prefetch=[
            models.Prefetch(query=dense, using="dense", limit=20, filter=flt),
            models.Prefetch(query=bm25, using="bm25", limit=20, filter=flt),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=k,
        with_payload=True,
    ).points

def build_filter(tag: str | None, folder: str | None) -> models.Filter | None:
    must = []
    if tag:
        must.append(models.FieldCondition(key="tags", match=models.MatchValue(value=tag)))
    if folder:
        must.append(models.FieldCondition(key="file_path", match=models.MatchText(text=folder)))
    return models.Filter(must=must) if must else None

def cite(p) -> dict:
    pl = p.payload
    return {
        "file_path": pl.get("file_path"),
        "title": pl.get("note_title"),
        "heading_path": pl.get("heading_path"),
        "score": round(p.score, 4),
        "text": pl.get("text"),
    }


# --------------------------------------------------------------------------- paths & frontmatter

def resolve_path(file_path: str) -> Path | None:
    """Absolute path inside the vault, or None when it escapes."""
    p = (VAULT / file_path).resolve()
    return p if p.is_relative_to(VAULT) else None

def load_note(file_path: str) -> tuple[Path | None, str]:
    """(path, error). Error is "" on success."""
    if not file_path.endswith(".md"):
        return None, "error: file must be .md"
    p = resolve_path(file_path)
    if p is None:
        return None, f"error: path escapes the vault: {file_path}"
    if not p.is_file():
        return None, f"not found: {file_path}"
    return p, ""

def split_frontmatter(raw: str) -> tuple[str, str]:
    """(frontmatter block without delimiters, body)."""
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end > 0:
            return raw[3:end], raw[end + 4:]
    return "", raw

def _split_list_items(s: str) -> list[str]:
    """Split on commas OUTSIDE quotes: `["a, b", c]` is two items, not three."""
    items, buf, quote = [], "", ""
    for ch in s:
        if quote:
            buf += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ",":
            items.append(buf)
            buf = ""
        else:
            buf += ch
    items.append(buf)
    return items

def parse_frontmatter(block: str) -> dict:
    fm: dict = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip().strip('"').strip("'") for v in _split_list_items(val[1:-1]) if v.strip()]
        else:
            val = val.strip('"').strip("'")
        fm[key] = val
    return fm

def fmt_scalar(s: str) -> str:
    return s if re.fullmatch(r"[A-Za-z0-9_./+-]+", s) else '"' + s.replace('"', "'") + '"'

def dump_frontmatter(fm: dict) -> str:
    keys = [k for k in FM_ORDER if k in fm] + [k for k in fm if k not in FM_ORDER]
    lines = ["---"]
    for k in keys:
        v = fm[k]
        if isinstance(v, list):
            # quote each item: `superseded_by: [["[[X]]"]]` would otherwise be written as
            # `[[[X]]]`, which YAML still reads back but the link regex reads as `[X` —
            # the edge vanished from backlinks/graph and appeared as a phantom in broken_links.
            lines.append(f"{k}: [{', '.join(fmt_scalar(str(x)) for x in v)}]")
        else:
            lines.append(f"{k}: {fmt_scalar(str(v))}")
    lines.append("---")
    return "\n".join(lines)

def note_body(p: Path) -> str:
    return split_frontmatter(p.read_text(encoding="utf-8", errors="replace"))[1]

def _as_list(v) -> list[str]:
    return v if isinstance(v, list) else ([v] if v else [])

def note_flags(rel: str) -> dict:
    """Retraction state of a note, or {} when it is not retracted: `retracted` is
    the whole point of the convention only if a reader can SEE it (AI-GUIDE §failure-path)."""
    p = VAULT / rel
    if not p.is_file():
        return {}
    fm = parse_frontmatter(split_frontmatter(p.read_text(encoding="utf-8", errors="replace"))[0])
    flag = str(fm.get("retracted", "")).strip().lower() in ("true", "yes", "1")
    if not flag:
        return {}
    out = {"retracted": True}
    by = _as_list(fm.get("superseded_by"))
    if by:
        out["superseded_by"] = by
    return out


# --------------------------------------------------------------------------- wiki-links

def link_index() -> dict[str, str]:
    """lowercased note stem AND lowercased title -> vault-relative path."""
    idx: dict[str, str] = {}
    for p, rel in vix.iter_notes():
        idx.setdefault(p.stem.lower(), rel)
        try:
            title = vix.parse_note(p)[1]
        except Exception as e:
            print(f"link index: cannot parse {rel}: {e}", file=sys.stderr)
            title = p.stem
        if title:
            idx.setdefault(str(title).lower(), rel)
    return idx

CODE_FENCE_RE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")

def strip_code(text: str) -> str:
    """Drop fenced blocks and inline spans: Obsidian does not render a wiki-link inside code,
    so ``supersedes: [[olds-note]]`` in a note ABOUT the format is not a link to a note."""
    return INLINE_CODE_RE.sub(" ", CODE_FENCE_RE.sub(" ", text))

def raw_links(text: str) -> list[str]:
    """Wiki-link targets, code spans and attachment embeds excluded (`![[Pasted image …png]]` is not a note)."""
    targets = {m.group(1).split("#")[0].strip() for m in re.finditer(r"\[\[([^\]|#]+)", strip_code(text))}
    return sorted(t for t in targets if t and not ATTACHMENT_RE.search(t))

def resolve_links(text: str, idx: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    """(resolved vault-relative paths, unresolved link targets)."""
    idx = idx or link_index()
    resolved, unresolved = [], []
    for tgt in raw_links(text):
        hit = idx.get(tgt.lower())
        (resolved if hit else unresolved).append(hit or tgt)
    return resolved, unresolved


# --------------------------------------------------------------------------- index health

def index_stats() -> dict:
    """Notes on disk, notes in the index, when it last ran, which notes changed since."""
    on_disk = [rel for _, rel in vix.iter_notes()]
    indexed: set[str] = set()
    last_run = None
    if vix.DB.exists():
        try:
            con = sqlite3.connect(vix.DB)
            try:
                indexed = {r[0] for r in con.execute("SELECT rel_path FROM files").fetchall()}
            except sqlite3.OperationalError as e:
                print(f"index stats: no files table yet ({e})", file=sys.stderr)
            try:
                row = con.execute("SELECT value FROM meta WHERE key='last_run'").fetchone()
                last_run = float(row[0]) if row else None
            except sqlite3.OperationalError:
                pass  # meta appears with the first run of the current indexer
            con.close()
        except Exception as e:
            print(f"index stats: cannot read {vix.DB}: {e}", file=sys.stderr)
    stale = []
    for rel in on_disk:
        mtime = (VAULT / rel).stat().st_mtime
        if rel not in indexed:
            stale.append(rel)                                   # written after the last scan
        elif last_run is not None and mtime > last_run:
            stale.append(rel)                                   # edited after the last run
    return {
        "notes_on_disk": len(on_disk),
        "notes_indexed": len(indexed),
        "last_run": datetime.fromtimestamp(last_run).isoformat(timespec="seconds") if last_run else None,
        "stale_count": len(stale),
        "stale": sorted(stale)[:25],
    }

def stale_count() -> int:
    """-1 when the index has never run; otherwise how many notes are newer than it."""
    try:
        return index_stats()["stale_count"]
    except Exception:
        return -1


# --------------------------------------------------------------------------- indexing

def run_indexer(full: bool = False) -> str:
    # Same venv/package as this server, so no `uv` dependency resolution on every write.
    cmd = [sys.executable, "-m", "second_brain.indexer"] + (["--full"] if full else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=False)
    except FileNotFoundError:
        return "error: python interpreter not found"
    except subprocess.TimeoutExpired:
        return "error: indexer timed out after 1800s"
    out = (r.stdout or "").strip()
    if "already running" in out:
        return "skipped: another indexer is already running"
    summary = out.splitlines()[-1] if out else "(no output)"
    if r.returncode != 0:
        err = (r.stderr or "").strip().splitlines()
        return f"error: indexer exit {r.returncode}: {err[-1] if err else summary}"
    return summary


# --------------------------------------------------------------------------- read tools

@mcp.tool()
def vault_status() -> str:
    """Index health: notes on disk vs indexed, when the index last ran, and which notes changed since.

    Call this before trusting a search result: after a write the index is refreshed
    automatically, but a manual file edit from outside this server leaves it stale."""
    return json.dumps(index_stats(), ensure_ascii=False, indent=1)

@mcp.tool()
def list_notes(tag: str | None = None, folder: str | None = None, limit: int = 200) -> str:
    """Cheap inventory of notes: file_path, title, type, status, tags. Filter by tag or folder prefix."""
    out = []
    for p, rel in vix.iter_notes():
        if folder and not rel.startswith(folder.rstrip("/")):
            continue
        try:
            fm, title, tags, _aliases, _body = vix.parse_note(p)
        except Exception as e:
            print(f"list_notes: cannot parse {rel}: {e}", file=sys.stderr)
            continue
        if tag and tag not in tags:
            continue
        out.append({"file_path": rel, "title": str(title), "type": fm.get("type"),
                    "status": fm.get("status"), "tags": tags,
                    "retracted": str(fm.get("retracted", "")).strip().lower() in ("true", "yes", "1")})
    out.sort(key=lambda x: x["file_path"])
    return json.dumps({"count": len(out), "notes": out[:limit]}, ensure_ascii=False, indent=1)

@mcp.tool()
def outline(file_path: str) -> str:
    """Headings of a note with their levels — cheap context before reading the whole thing."""
    p, err = load_note(file_path)
    if err:
        return err
    body = re.sub(r"```.*?```", "", note_body(p), flags=re.DOTALL)
    heads = [{"level": len(m.group(1)), "heading": m.group(2).strip()}
             for m in re.finditer(r"^(#{1,6})\s+(.*)$", body, flags=re.MULTILINE)]
    return json.dumps({"file_path": p.relative_to(VAULT).as_posix(), "chars": len(note_body(p)),
                       "headings": heads}, ensure_ascii=False, indent=1)

@mcp.tool()
def read_note(file_path: str, max_chars: int | None = None) -> str:
    """Read the full text of a vault note by its relative path (path from semantic_search/list_notes).

    `max_chars` bounds the result for a large note; the truncation is marked explicitly."""
    p, err = load_note(file_path)
    if err:
        return err
    text = p.read_text(encoding="utf-8", errors="replace")
    flags = note_flags(p.relative_to(VAULT).as_posix())
    if flags:
        by = ", ".join(flags.get("superseded_by", []))
        text = ("[RETRACTED NOTE — its claim was withdrawn; the text is kept on purpose. "
                + (f"Superseded by: {by}. " if by else "")
                + "See its `Почему снято` / `Почему не сработало` section.]\n\n") + text
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars] + f"\n\n…[truncated: {len(text) - max_chars} of {len(text)} chars elided; use outline() to navigate]"
    return text

@mcp.tool()
def semantic_search(query: str, k: int = 8, tag: str | None = None, folder: str | None = None,
                    chunks_per_note: int = 1) -> str:
    """Hybrid (dense+BM25, RRF) semantic search over the Obsidian vault. Returns chunks with file_path citations.

    `chunks_per_note` raises how many chunks one long note may contribute (default 1, the previous
    behaviour). Every result carries `index_stale`: how many notes changed since the last index —
    0 means the results are current, -1 means the index has never run. Trust accordingly."""
    per_note = max(1, chunks_per_note)
    pts = hybrid_search(query, k * 3 * per_note, build_filter(tag, folder))
    seen: dict[str, int] = {}
    uniq = []
    for p in pts:
        fp = p.payload.get("file_path")
        used = seen.get(fp, 0)
        if used >= per_note:
            continue
        seen[fp] = used + 1
        uniq.append(cite(p))
        if len(uniq) >= k:
            break
    stale = stale_count()
    for item in uniq:
        item["index_stale"] = stale
        item.update(note_flags(item["file_path"]))   # a retracted note stays searchable, but says so
    return json.dumps(uniq, ensure_ascii=False, indent=1)

@mcp.tool()
def find_related(file_path: str, k: int = 10) -> str:
    """Find notes related to the given note: semantic neighbours + 1-hop wiki-link expansion."""
    p, err = load_note(file_path)
    if err:
        return err
    rel = p.relative_to(VAULT).as_posix()
    body = note_body(p)
    sem = hybrid_search(body[:2000], 8, models.Filter(
        must_not=[models.FieldCondition(key="file_path", match=models.MatchValue(value=rel))]))
    idx = link_index()
    out = {
        "semantic_neighbors": [cite(x) | {"text": (x.payload.get("text") or "")[:300]} for x in sem],
        "linked_notes": [],
    }
    for name in raw_links(body)[:20]:
        target = idx.get(name.lower())
        out["linked_notes"].append({"link": name, "file_path": target, "resolved": target is not None})
    return json.dumps(out, ensure_ascii=False, indent=1)

@mcp.tool()
def backlinks(file_path: str, k: int = 50) -> str:
    """Who links to this note (`inbound`) and where this note points (`outbound`, with resolution).

    Frontmatter links count: `moc: "[[Rust MOC]]"` is a real reference."""
    p, err = load_note(file_path)
    if err:
        return err
    rel = p.relative_to(VAULT).as_posix()
    idx = link_index()
    inbound = []
    for q, qrel in vix.iter_notes():
        if qrel == rel:
            continue
        raw = q.read_text(encoding="utf-8", errors="replace")
        for tgt in raw_links(raw):
            if idx.get(tgt.lower()) == rel:
                inbound.append({"file_path": qrel, "link": tgt})
                break
    outbound = [{"link": t, "file_path": idx.get(t.lower()), "resolved": t.lower() in idx}
                for t in raw_links(p.read_text(encoding="utf-8", errors="replace"))]
    return json.dumps({"file_path": rel, "inbound_count": len(inbound), "inbound": inbound[:k],
                       "outbound": outbound[:k]}, ensure_ascii=False, indent=1)

@mcp.tool()
def broken_links(limit: int = 200) -> str:
    """Wiki-links that resolve to no existing note (by stem or title), grouped by source note."""
    idx = link_index()
    out = []
    for p, rel in vix.iter_notes():
        raw = p.read_text(encoding="utf-8", errors="replace")
        for tgt in raw_links(raw):
            if tgt.lower() not in idx:
                out.append({"file_path": rel, "link": tgt})
    return json.dumps({"count": len(out), "links": out[:limit]}, ensure_ascii=False, indent=1)

@mcp.tool()
def graph_overview(k: int = 15) -> str:
    """Knowledge-graph overview: hub notes (most outgoing wiki-links — MOC candidates) and orphans (no links at all)."""
    idx = link_index()
    outdegree, inbound_targets, all_fps = {}, set(), set()
    for p, rel in vix.iter_notes():
        all_fps.add(rel)
        links = raw_links(p.read_text(encoding="utf-8", errors="replace"))
        if links:
            outdegree[rel] = len(links)
            for t in links:
                tgt = idx.get(t.lower())
                if tgt: inbound_targets.add(tgt)
    hubs = sorted(outdegree.items(), key=lambda x: -x[1])[:k]
    orphans = sorted(all_fps - inbound_targets - set(outdegree))
    return json.dumps({
        "hubs_top_outgoing": [{"file_path": f, "outgoing": n} for f, n in hubs],
        "orphan_notes": orphans[:k],
        "notes_total": len(all_fps),
    }, ensure_ascii=False, indent=1)


# --------------------------------------------------------------------------- write tools

def _guard_new_path(file_path: str) -> tuple[Path | None, str]:
    if not file_path.endswith(".md"):
        return None, "error: file must be .md"
    rel = Path(file_path).as_posix()
    if rel.startswith(SYSTEM_PREFIXES):
        return None, "error: system folders are off-limits; create notes in the vault root"
    p = resolve_path(file_path)
    if p is None:
        return None, f"error: path escapes the vault: {file_path}"
    return p, ""

def _link_guard(content: str) -> tuple[str, list[str]]:
    """(error, unresolved link targets). At least ONE link must resolve to an existing note."""
    resolved, unresolved = resolve_links(content)
    if not resolved:
        msg = ("error: no [[wiki-link]] resolves to an existing note — the note must link at "
               "least one real note (targets resolve by file stem or by title)")
        return msg, unresolved
    return "", unresolved

@mcp.tool()
def write_note(file_path: str, title: str, content: str, description: str | None = None,
               tags: list[str] | None = None, moc: str | None = None, type: str = "zettel",
               status: str = "seedling", aliases: list[str] | None = None,
               retracted: bool = False, supersedes: list[str] | None = None,
               auto_index: bool = True) -> str:
    """Create a new vault note. Flat vault: file_path is kebab-case EN in the vault root.

    `description` is required (one sentence — it is the RAG chunk title) and `moc` takes either
    `Rust MOC` or `[[Rust MOC]]`. The body must link at least one EXISTING note; links that do
    not resolve yet are reported back rather than rejected, so a hub may be written before its
    spokes. The index is refreshed automatically (set `auto_index=False` to batch)."""
    if not description or not description.strip():
        return "error: description is required — one sentence, it is the RAG chunk title"
    p, err = _guard_new_path(file_path)
    if err:
        return err
    if p.exists():
        return f"error: note already exists — use update_note('{file_path}', ...) instead of duplicating"
    if "[[" not in content:
        return "error: note must link to at least one existing note via [[wiki-link]]"
    link_err, unresolved = _link_guard(content)
    if link_err:
        return link_err
    fm = {
        "title": title,
        "type": type,
        "status": status,
        "date": date.today().isoformat(),
        "updated": date.today().isoformat(),
        "tags": [str(t) for t in (tags or [])],
        "moc": f"[[{(moc or '').strip().strip('[]')}]]" if (moc or "").strip().strip("[]") else "",
        "aliases": [str(a) for a in (aliases or [])],
        "description": description.strip(),
        "retracted": "true" if retracted else "false",
        "supersedes": [f"[[{s.strip().strip('[]')}]]" for s in (supersedes or []) if s.strip()],
        "superseded_by": [],
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dump_frontmatter(fm) + "\n\n" + content.strip() + "\n", encoding="utf-8")
    result = {
        "created": p.relative_to(VAULT).as_posix(),
        "unresolved_links": unresolved,
        "index": run_indexer() if auto_index else "skipped (auto_index=False)",
    }
    return json.dumps(result, ensure_ascii=False, indent=1)

@mcp.tool()
def update_note(file_path: str, content: str | None = None, append: bool = False,
                title: str | None = None, description: str | None = None,
                tags: list[str] | None = None, moc: str | None = None, type: str | None = None,
                status: str | None = None, aliases: list[str] | None = None,
                retracted: bool | None = None, supersedes: list[str] | None = None,
                superseded_by: list[str] | None = None,
                auto_index: bool = True) -> str:
    """Patch an existing note in place: frontmatter fields and/or body, bumping `updated`.

    Only the arguments you pass are changed. `content` replaces the body, or appends to it with
    `append=True`. The result is re-checked for at least one resolvable [[wiki-link]]."""
    p, err = load_note(file_path)
    if err:
        return err
    raw = p.read_text(encoding="utf-8", errors="replace")
    block, body = split_frontmatter(raw)
    fm = parse_frontmatter(block)
    changed = []
    for key, val in (("title", title), ("description", description), ("type", type), ("status", status)):
        if val is not None:
            fm[key] = val.strip() if isinstance(val, str) else val
            changed.append(key)
    if tags is not None:
        fm["tags"] = [str(t) for t in tags]
        changed.append("tags")
    if aliases is not None:
        fm["aliases"] = [str(a) for a in aliases]
        changed.append("aliases")
    if moc is not None:
        bare = moc.strip().strip("[]")
        fm["moc"] = f"[[{bare}]]" if bare else ""
        changed.append("moc")
    for key, val in (("supersedes", supersedes), ("superseded_by", superseded_by)):
        if val is not None:
            fm[key] = [f"[[{s.strip().strip('[]')}]]" for s in val if s.strip()]
            changed.append(key)
    if retracted is not None:
        fm["retracted"] = "true" if retracted else "false"
        changed.append("retracted")
    if content is not None:
        body = (body.rstrip() + "\n\n" + content.strip()) if append else content.strip()
        changed.append("body(append)" if append else "body")
    if not changed:
        return "error: nothing to update — pass content, append, or at least one frontmatter field"
    final_text = body + " " + json.dumps(fm, ensure_ascii=False)
    if "[[" not in final_text:
        return "error: the result would have no [[wiki-link]] — a note without links is a bug"
    link_err, unresolved = _link_guard(final_text)
    if link_err:
        return link_err
    fm["updated"] = date.today().isoformat()
    p.write_text(dump_frontmatter(fm) + "\n\n" + body.strip() + "\n", encoding="utf-8")
    result = {
        "updated": p.relative_to(VAULT).as_posix(),
        "changed": changed,
        "unresolved_links": unresolved,
        "index": run_indexer() if auto_index else "skipped (auto_index=False)",
    }
    return json.dumps(result, ensure_ascii=False, indent=1)

@mcp.tool()
def index_now(full: bool = False) -> str:
    """Run the vault indexer now (incremental; `full=True` re-embeds everything).

    Concurrent runs are safe: the indexer holds a lock and a second run exits immediately."""
    return run_indexer(full)


# --------------------------------------------------------------------------- simple HTTP API

def serve_simple_http():
    """Plain JSON API for nvim/curl: POST /search {"query":..., "k":8} -> results."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            if self.path.rstrip("/") == "/status":
                res = vault_status()
            else:
                res = semantic_search(req.get("query", ""), req.get("k", 8), req.get("tag"),
                                      req.get("folder"), req.get("chunks_per_note", 1))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(res.encode())
        def log_message(self, *a): pass
    print("simple http on 127.0.0.1:8766")
    HTTPServer(("127.0.0.1", 8766), H).serve_forever()

def main() -> None:
    if "--simple-http" in sys.argv:
        serve_simple_http()
    elif "--http" in sys.argv:
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = 8765
        mcp.run(transport="sse")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
