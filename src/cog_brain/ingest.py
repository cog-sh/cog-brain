"""Chat-export ingestion: one Markdown note per conversation, for `raw/`.

Handles the messy real-world shapes — Claude (`chat_messages`, `sender`, `text`),
ChatGPT (`mapping` → message tree, `author.role`, `content.parts`), and a plain
`messages` list. Unknown shapes are skipped, not crashed on.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return (_SLUG.sub("-", text.lower()).strip("-")[:80]) or "conversation"


def _text_of(content) -> str:
    """Flatten str | list[parts] | dict{parts|text|content} into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for k in ("text", "content", "parts"):
                    v = item.get(k)
                    if isinstance(v, str):
                        parts.append(v)
                        break
                    if isinstance(v, list):
                        parts.append(" ".join(str(x) for x in v if isinstance(x, str)))
                        break
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        for k in ("text", "content", "parts"):
            if k in content:
                return _text_of(content[k])
    return ""


def _messages(conv: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(conv.get("chat_messages"), list):  # Claude
        for m in conv["chat_messages"]:
            out.append((str(m.get("sender") or m.get("role") or "?"),
                        _text_of(m.get("text") or m.get("content"))))
    elif isinstance(conv.get("mapping"), dict):  # ChatGPT
        for node in conv["mapping"].values():
            msg = (node or {}).get("message") or {}
            role = (msg.get("author") or {}).get("role")
            content = msg.get("content")
            if role and content:
                out.append((role, _text_of(content.get("parts") if isinstance(content, dict)
                                            else content)))
    elif isinstance(conv.get("messages"), list):  # generic
        for m in conv["messages"]:
            out.append((str(m.get("role") or m.get("sender") or "?"),
                        _text_of(m.get("content") or m.get("text"))))
    return [(r, t) for r, t in out if t.strip()]


def _created(conv: dict) -> str:
    for k in ("created_at", "create_time", "created", "timestamp"):
        v = conv.get(k)
        if isinstance(v, (int, float)):
            try:
                return time.strftime("%Y-%m-%d", time.gmtime(v))
            except (OverflowError, OSError, ValueError):
                pass
        elif isinstance(v, str) and v:
            return v[:10]
    return time.strftime("%Y-%m-%d")


def _title(conv: dict) -> str:
    for k in ("title", "name"):
        v = conv.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "Conversation"


def conversations(data) -> list[dict]:
    """Normalize an export into [{title, created, messages:[(who,text)]}]."""
    if isinstance(data, dict):
        for k in ("conversations", "chats", "data"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
        else:
            data = [data]
    out = []
    for conv in data if isinstance(data, list) else []:
        if not isinstance(conv, dict):
            continue
        msgs = _messages(conv)
        if msgs:
            out.append({"title": _title(conv), "created": _created(conv), "messages": msgs})
    return out


def to_markdown(conv: dict, source: str) -> str:
    title = conv["title"].replace('"', "'")
    fm = (f'---\ntitle: "{title}"\ntype: source\ncreated: {conv["created"]}\n'
          f'source: {source}\n---\n\n')
    body = "\n\n".join(f"**{who}:** {text}" for who, text in conv["messages"])
    return f'{fm}# {conv["title"]}\n\n{body}\n'


def import_chats(src: str | Path, out_dir: str | Path, min_words: int = 150) -> dict:
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(src.read_text(encoding="utf-8"))
    written, skipped = [], 0
    for conv in conversations(data):
        text = to_markdown(conv, src.name)
        if len(text.split()) < min_words:
            skipped += 1
            continue
        base = _slug(conv["title"])
        path = out_dir / f"{base}.md"
        n = 2
        while path.exists():
            path = out_dir / f"{base}-{n}.md"
            n += 1
        path.write_text(text, encoding="utf-8")
        written.append(str(path))
    return {"written": written, "skipped": skipped, "out_dir": str(out_dir)}
