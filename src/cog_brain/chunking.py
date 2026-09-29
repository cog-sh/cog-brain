"""Vault scanning, frontmatter parsing, and chunking.

Pure helpers with **no heavy dependencies** — shared by every memory backend
and by the indexer, so the definition of a "note", a "chunk", and a wiki-link
cannot drift between engines.
"""
from __future__ import annotations

import re
from pathlib import Path

from cog_brain import config

EXCLUDE_DIRS = {".obsidian", ".trash", ".git", ".smart-env", "90-archive", "attachments", "daily"}
MAX_FILE_BYTES = 1_000_000
TAU_MAX = 1500  # chars, soft max per chunk
CHUNKER_VERSION = "1"  # bump to force re-chunk of every file


def clean_wikilinks(text: str) -> str:
    text = re.sub(r"!?\[\[([^\]|#]+)#([^\]|]+)\|([^\]]+)\]\]", r"\3", text)
    text = re.sub(r"!?\[\[([^\]|#]+)#([^\]|]+)\]\]", r"\1 > \2", text)
    text = re.sub(r"!?\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"!?\[\[([^\]]+)\]\]", r"\1", text)
    return text


def extract_links(text: str) -> list[str]:
    return sorted({m.group(1).split("#")[0].strip() for m in re.finditer(r"\[\[([^\]|#]+)", text)})


def split_by_headings(title: str, tags: list[str], aliases: list[str], body: str) -> list[tuple[str, str]]:
    """Return [(heading_path, chunk_text)]. Notes <=~5000 chars -> single chunk."""
    if len(body) <= 5000:
        return [("", body)]
    lines = body.splitlines()
    chunks: list[tuple[str, str]] = []
    head_stack: list[str] = []
    cur_head = ""
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf, cur_head
        if not buf:
            return
        text = "\n".join(buf).strip()
        if text:
            chunks.append((cur_head, text))
        buf = []

    in_code = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code
            buf.append(line)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line) if not in_code else None
        if m:
            flush()
            level = len(m.group(1))
            head_stack = head_stack[: level - 1] + [m.group(2)]
            cur_head = " > ".join(head_stack)
            buf = [line]
        else:
            buf.append(line)
            if sum(len(x) for x in buf) > TAU_MAX * 2:  # hard cap fallback
                flush()
    flush()
    return chunks or [("", body)]


def contextualize(title: str, tags: list[str], aliases: list[str], heading_path: str, chunk_text: str) -> str:
    parts = [title]
    if aliases:
        parts.append("aka: " + ", ".join(aliases))
    if tags:
        parts.append("tags: " + ", ".join(tags))
    if heading_path:
        parts.append(heading_path)
    parts.append(chunk_text)
    return "\n".join(parts)


def iter_notes():
    """Yield (path, vault-relative posix path) for every indexable note."""
    for p in config.VAULT.rglob("*.md"):
        rel = p.relative_to(config.VAULT).as_posix()
        if any(rel.startswith(e.rstrip("/")) for e in EXCLUDE_DIRS):
            continue
        if p.stat().st_size > MAX_FILE_BYTES:
            continue
        yield p, rel


def parse_note(p: Path) -> tuple[dict, str, list[str], list[str], str]:
    """(frontmatter, title, tags, aliases, body)."""
    raw = p.read_text(encoding="utf-8", errors="replace")
    fm: dict = {}
    body = raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end > 0:
            for line in raw[3:end].splitlines():
                m = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
                if m:
                    val = m.group(2).strip().strip('"')
                    if val.startswith("[") and val.endswith("]"):
                        val = [v.strip().strip('"') for v in val[1:-1].split(",") if v.strip()]
                    fm[m.group(1)] = val
            body = raw[end + 4 :]
    title = fm.get("title") or p.stem
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    aliases = fm.get("aliases", []) or []
    if isinstance(aliases, str):
        aliases = [aliases]
    return fm, title, tags, aliases, body


def chunks_for(p: Path, rel: str) -> list[dict]:
    """Index-ready chunk records for one note (payload dicts, no engine specifics)."""
    fm, title, tags, aliases, body = parse_note(p)
    mtime = p.stat().st_mtime
    out = []
    for i, (heading_path, chunk_text) in enumerate(split_by_headings(title, tags, aliases, body)):
        out.append({
            "rel_path": rel,
            "note_title": str(title),
            "heading_path": heading_path,
            "text": chunk_text,
            "embed_text": contextualize(title, tags, aliases, heading_path, chunk_text),
            "tags": tags,
            "aliases": aliases,
            "links": extract_links(chunk_text),
            "type": fm.get("type", "zettel"),
            "status": fm.get("status", "seedling"),
            "mtime": mtime,
            "idx": i,
        })
    return out
