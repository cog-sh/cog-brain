"""Shared note operations for the local API and MCP compatibility adapter.

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
Russian `title` both work. The index lives in ``$COG_BRAIN_STATE_DIR/index.db`` + Qdrant;
``vault_status()`` is the authority on whether it is current — trust it before trusting a
search result.

Verify after editing this file: ``uv run python tests/test_server.py`` (exercises every tool
below against the live vault and exits non-zero on failure).
"""
import json
import re
import subprocess
import sys
from pathlib import Path
from datetime import date


from cog_brain import chunking, config
from cog_brain.backends import get_backend
from cog_brain.graph import link_index, raw_links

VAULT = config.VAULT.resolve()

SYSTEM_PREFIXES = ("daily/", "attachments/", "90-meta/", "90-archive/", ".obsidian/", ".trash/", ".git/", ".smart-env/")
FM_ORDER = ["title", "type", "status", "date", "updated", "tags", "moc", "aliases", "description",
            "retracted", "supersedes", "superseded_by"]

from cog_brain import frontmatter, storage
from threading import local
from functools import wraps

class _Backend:
    """Lazy, thread-local connections: no transport startup or SQLite thread leak."""
    def __init__(self):
        self._state = local()

    def __getattr__(self, name):
        if not hasattr(self._state, "value"):
            self._state.value = get_backend()
        return getattr(self._state.value, name)

backend = _Backend()


# --------------------------------------------------------------------------- search

def cite(p) -> dict:
    pl = p.payload
    return {
        "file_path": pl.get("file_path"),
        "title": pl.get("note_title"),
        "heading_path": pl.get("heading_path"),
        "score": round(p.score, 4),
        "text": pl.get("text"),
        **note_flags(pl.get("file_path", "")),
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

split_frontmatter = frontmatter.split
parse_frontmatter = frontmatter.parse
dump_frontmatter = frontmatter.dump


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
    try:
        fm = parse_frontmatter(split_frontmatter(p.read_text(encoding="utf-8", errors="replace"))[0])
    except Exception as error:
        return {"metadata_error": type(error).__name__}
    flag = str(fm.get("retracted", "")).strip().lower() in ("true", "yes", "1")
    if not flag:
        return {}
    out = {"retracted": True}
    by = _as_list(fm.get("superseded_by"))
    if by:
        out["superseded_by"] = by
    return out


# --------------------------------------------------------------------------- wiki-links

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
    return backend.status()

def stale_count() -> int:
    """-1 when the index has never run; otherwise how many notes are newer than it."""
    try:
        return backend.status()["stale_count"]
    except Exception:
        return -1


# --------------------------------------------------------------------------- indexing

def run_indexer(full: bool = False) -> str:
    if config.BACKEND == "markdown":
        result = backend.sync(full=full)
        return f"backend=markdown changed=0 deleted=0 total={result['total']} elapsed=0s"
    # Same venv/package as this server, so no `uv` dependency resolution on every write.
    cmd = [sys.executable, "-m", "cog_brain.indexer"] + (["--full"] if full else [])
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


def index_after_write(auto_index: bool) -> str:
    """Index failures must never hide an already committed Markdown write."""
    if not auto_index:
        return "skipped (auto_index=False)"
    try:
        return run_indexer()
    except Exception as error:
        return f"error: {error}"


# --------------------------------------------------------------------------- read tools

def vault_status() -> str:
    """Index health: notes on disk vs indexed, when the index last ran, and which notes changed since.

    Call this before trusting a search result: after a write the index is refreshed
    automatically, but a manual file edit from outside this server leaves it stale."""
    return json.dumps(index_stats(), ensure_ascii=False, indent=1)

def list_notes(tag: str | None = None, folder: str | None = None, limit: int = 200) -> str:
    """Cheap inventory of notes: file_path, title, type, status, tags. Filter by tag or folder prefix."""
    out = []
    if not 1 <= limit <= 1000:
        return "error: limit must be 1..1000"
    daily = folder is not None and (folder.rstrip("/") == "daily" or folder.startswith("daily/"))
    for p, rel in chunking.iter_notes(include_daily=daily):
        if folder and not rel.startswith(folder.rstrip("/") + "/"):
            continue
        try:
            fm, title, tags, _aliases, _body = chunking.parse_note(p)
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

def read_note(file_path: str, max_chars: int | None = None, section: str | None = None) -> str:
    """Read the full text of a vault note by its relative path (path from semantic_search/list_notes).

    `max_chars` bounds the result for a large note; the truncation is marked explicitly."""
    p, err = load_note(file_path)
    if err:
        return err
    text = p.read_text(encoding="utf-8", errors="replace")
    if section:
        text = section_text(text, section)
    if max_chars is not None and max_chars < 1:
        return "error: max_chars must be positive"
    flags = note_flags(p.relative_to(VAULT).as_posix())
    if flags:
        by = ", ".join(flags.get("superseded_by", []))
        text = ("[RETRACTED NOTE — its claim was withdrawn; the text is kept on purpose. "
                + (f"Superseded by: {by}. " if by else "")
                + "See its `Почему снято` / `Почему не сработало` section.]\n\n") + text
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars] + f"\n\n…[truncated: {len(text) - max_chars} of {len(text)} chars elided; use outline() to navigate]"
    return text


def section_text(text: str, section: str) -> str:
    """Read a heading and its descendants, ignoring headings in code fences."""
    lines = text.splitlines(keepends=True)
    start = None
    level = 0
    fenced = False
    wanted = section.split(" > ")[-1].strip()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line) if not fenced else None
        if match:
            if start is not None and len(match[1]) <= level:
                return "".join(lines[start:i])
            if start is None and match[2].strip() == wanted:
                start, level = i, len(match[1])
    if start is None:
        raise ValueError(f"section not found: {section}")
    return "".join(lines[start:])

def semantic_search(query: str, k: int = 8, tag: str | None = None, folder: str | None = None,
                    chunks_per_note: int = 1) -> str:
    """Hybrid (dense+BM25, RRF) semantic search over the Obsidian vault. Returns chunks with file_path citations.

    `chunks_per_note` raises how many chunks one long note may contribute (default 1, the previous
    behaviour). Every result carries `index_stale`: how many notes changed since the last index —
    0 means the results are current, -1 means the index has never run. Trust accordingly."""
    per_note = max(1, chunks_per_note)
    if not 1 <= k <= 50 or not 1 <= per_note <= 10:
        return "error: k must be 1..50 and chunks_per_note 1..10"
    pts = backend.search(query, k * 3 * per_note, tag=tag, folder=folder)
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

def find_related(file_path: str, k: int = 10) -> str:
    """Find notes related to the given note: semantic neighbours + 1-hop wiki-link expansion."""
    p, err = load_note(file_path)
    if err:
        return err
    rel = p.relative_to(VAULT).as_posix()
    body = note_body(p)
    k = max(1, min(k, 50))
    sem = backend.search(body[:2000], k, exclude=rel)
    idx = link_index()
    out = {
        "semantic_neighbors": [cite(x) | {"text": (x.payload.get("text") or "")[:300]} for x in sem],
        "linked_notes": [],
    }
    for name in raw_links(body)[:k]:
        target = idx.get(name.lower())
        out["linked_notes"].append({"link": name, "file_path": target, "resolved": target is not None})
    return json.dumps(out, ensure_ascii=False, indent=1)

def backlinks(file_path: str, k: int = 50) -> str:
    """Who links to this note (`inbound`) and where this note points (`outbound`, with resolution).

    Frontmatter links count: `moc: "[[Rust MOC]]"` is a real reference."""
    p, err = load_note(file_path)
    if err:
        return err
    rel = p.relative_to(VAULT).as_posix()
    idx = link_index()
    inbound = []
    for q, qrel in chunking.iter_notes():
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

def broken_links(limit: int = 200) -> str:
    """Wiki-links that resolve to no existing note (by stem or title), grouped by source note."""
    idx = link_index()
    out = []
    for p, rel in chunking.iter_notes():
        raw = p.read_text(encoding="utf-8", errors="replace")
        for tgt in raw_links(raw):
            if tgt.lower() not in idx:
                out.append({"file_path": rel, "link": tgt})
    return json.dumps({"count": len(out), "links": out[:limit]}, ensure_ascii=False, indent=1)

def graph_overview(k: int = 15) -> str:
    """Knowledge-graph overview: hub notes (most outgoing wiki-links — MOC candidates) and orphans (no links at all)."""
    idx = link_index()
    outdegree, inbound_targets, all_fps = {}, set(), set()
    for p, rel in chunking.iter_notes():
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
    p = resolve_path(file_path)
    if p is None:
        return None, f"error: path escapes the vault: {file_path}"
    rel = p.relative_to(VAULT)
    if len(rel.parts) != 1:
        return None, "error: system folders are off-limits; create notes in the vault root"
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.md", rel.name):
        return None, "error: new note name must be kebab-case EN"
    return p, ""


def guard_update(file_path: str) -> None:
    p = resolve_path(file_path)
    if p is None:
        raise ValueError("path escapes the vault")
    if any(part in {x.rstrip('/') for x in SYSTEM_PREFIXES} for part in p.relative_to(VAULT).parts[:-1]):
        raise ValueError("system folders are off-limits")


def serialized_note(fn):
    @wraps(fn)
    def call(file_path, *args, **kwargs):
        try:
            guard_update(file_path)
            with storage.note_lock(resolve_path(file_path)):
                return fn(file_path, *args, **kwargs)
        except Exception as error:
            return f"error: {error}"
    return call

def _link_guard(content: str) -> tuple[str, list[str]]:
    """(error, unresolved link targets). At least ONE link must resolve to an existing note."""
    resolved, unresolved = resolve_links(content)
    if not resolved:
        msg = ("error: no [[wiki-link]] resolves to an existing note — the note must link at "
               "least one real note (targets resolve by file stem or by title)")
        return msg, unresolved
    return "", unresolved

@serialized_note
def write_note(file_path: str, title: str, content: str, description: str | None = None,
               tags: list[str] | None = None, moc: str | None = None, type: str = "zettel",
               status: str = "seedling", aliases: list[str] | None = None,
               retracted: bool = False, supersedes: list[str] | None = None,
               auto_index: bool = True, project: str | None = None,
               repo: str | None = None) -> str:
    """Create a new vault note. Flat vault: file_path is kebab-case EN in the vault root.

    `description` is required (one sentence — it is the RAG chunk title) and `moc` takes either
    `Rust MOC` or `[[Rust MOC]]`. The body must link at least one EXISTING note; links that do
    not resolve yet are reported back rather than rejected, so a hub may be written before its
    spokes. The index is refreshed automatically (set `auto_index=False` to batch)."""
    if not description or not description.strip():
        return "error: description is required — one sentence, it is the RAG chunk title"
    if not title.strip() or status not in ("seedling", "sapling", "evergreen"):
        return "error: nonempty title and status seedling/sapling/evergreen are required"
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
        "retracted": retracted,
        "supersedes": [f"[[{s.strip().strip('[]')}]]" for s in (supersedes or []) if s.strip()],
        "superseded_by": [],
    }
    if project:
        fm["project"] = project
    if repo:
        fm["repo"] = str(Path(repo).expanduser().resolve())
    _, unresolved = resolve_links(content + "\n" + dump_frontmatter(fm))
    p.parent.mkdir(parents=True, exist_ok=True)
    storage.atomic_write(p, dump_frontmatter(fm) + "\n\n" + content.strip() + "\n", create=True)
    index = index_after_write(auto_index)
    result = {
        "created": p.relative_to(VAULT).as_posix(),
        "unresolved_links": unresolved,
        "index": index,
        "index_state": "failed" if index.startswith("error") else "pending" if index.startswith("skipped") else "indexed",
        "revision": storage.revision(p.read_text(encoding="utf-8")),
    }
    return json.dumps(result, ensure_ascii=False, indent=1)

@serialized_note
def update_note(file_path: str, content: str | None = None, append: bool = False,
                title: str | None = None, description: str | None = None,
                tags: list[str] | None = None, moc: str | None = None, type: str | None = None,
                status: str | None = None, aliases: list[str] | None = None,
                retracted: bool | None = None, supersedes: list[str] | None = None,
                superseded_by: list[str] | None = None,
                auto_index: bool = True, expected_hash: str | None = None,
                project: str | None = None, repo: str | None = None) -> str:
    """Patch an existing note in place: frontmatter fields and/or body, bumping `updated`.

    Only the arguments you pass are changed. `content` replaces the body, or appends to it with
    `append=True`. The result is re-checked for at least one resolvable [[wiki-link]]."""
    p, err = load_note(file_path)
    if err:
        return err
    raw = p.read_text(encoding="utf-8", errors="replace")
    if title is not None and not title.strip():
        return "error: title must not be blank"
    if description is not None and not description.strip():
        return "error: description must not be blank"
    if status is not None and status not in ("seedling", "sapling", "evergreen"):
        return "error: status must be seedling/sapling/evergreen"
    before = storage.revision(raw)
    if expected_hash is not None and before != expected_hash:
        return "error: conflict: note changed; read it again before updating"
    block, body = split_frontmatter(raw)
    fm = parse_frontmatter(block)
    changed = []
    for key, value in (("project", project), ("repo", repo)):
        if value is not None:
            fm[key] = value
            changed.append(key)
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
        fm["retracted"] = retracted
        changed.append("retracted")
    if content is not None:
        body = (body.rstrip() + "\n\n" + content.strip()) if append else content.strip()
        changed.append("body(append)" if append else "body")
    if not changed:
        return "error: nothing to update — pass content, append, or at least one frontmatter field"
    final_text = body + " " + dump_frontmatter(fm)
    if "[[" not in final_text:
        return "error: the result would have no [[wiki-link]] — a note without links is a bug"
    link_err, unresolved = _link_guard(final_text)
    if link_err:
        return link_err
    fm["updated"] = date.today().isoformat()
    storage.atomic_write(p, frontmatter.render(fm, body), expected=before)
    index = index_after_write(auto_index)
    result = {
        "updated": p.relative_to(VAULT).as_posix(),
        "changed": changed,
        "unresolved_links": unresolved,
        "index": index,
        "index_state": "failed" if index.startswith("error") else "pending" if index.startswith("skipped") else "indexed",
        "revision": storage.revision(p.read_text(encoding="utf-8")),
    }
    return json.dumps(result, ensure_ascii=False, indent=1)

def index_now(full: bool = False) -> str:
    """Run the vault indexer now (incremental; `full=True` re-embeds everything).

    Concurrent runs are safe: the indexer holds a lock and a second run exits immediately."""
    return run_indexer(full)
