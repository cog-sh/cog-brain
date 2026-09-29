"""Wiki-link graph + vault health — pure, backend-independent.

Shared by the MCP tools (`backlinks`, `broken_links`, `graph_overview`) and the
operator CLI (`cog-brain health`), so the definition of a link and the health
thresholds live in one place.

Health model (thresholds from the second-brain-os guide):
orphan rate <5% healthy / >15% broken; average degree 3-8; the largest connected
component holds >=~80% of pages; a concept is stale when `updated` is >90 days old.
Deliberately **not** measured: raw page/word counts (they grow without meaning).
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from cog_brain import chunking

ATTACHMENT_RE = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|avif|pdf|mp4|mov|webm|m4a|mp3|excalidraw|canvas)$", re.IGNORECASE)
CODE_FENCE_RE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")

ORPHAN_HEALTHY, ORPHAN_BROKEN = 0.05, 0.15
DEGREE_MIN, DEGREE_MAX = 3.0, 8.0
MAIN_COMPONENT_MIN = 0.80
STALE_DAYS = 90


def strip_code(text: str) -> str:
    """Drop fenced blocks and inline spans: Obsidian does not render a wiki-link
    inside code, so ``supersedes: [[olds-note]]`` in a note ABOUT the format is
    not a link to a note."""
    return INLINE_CODE_RE.sub(" ", CODE_FENCE_RE.sub(" ", text))


def raw_links(text: str) -> list[str]:
    """Wiki-link targets, code spans and attachment embeds excluded."""
    targets = {m.group(1).split("#")[0].strip()
               for m in re.finditer(r"\[\[([^\]|#]+)", strip_code(text))}
    return sorted(t for t in targets if t and not ATTACHMENT_RE.search(t))


def link_index() -> dict[str, str]:
    """lowercased note stem AND lowercased title -> vault-relative path."""
    idx: dict[str, str] = {}
    for p, rel in chunking.iter_notes():
        idx.setdefault(p.stem.lower(), rel)
        try:
            title = chunking.parse_note(p)[1]
        except Exception as e:  # noqa: BLE001
            print(f"link index: cannot parse {rel}: {e}", file=sys.stderr)
            continue
        if title:
            idx.setdefault(str(title).lower(), rel)
    return idx


def graph() -> dict:
    """Resolved directed graph plus the pages with no edges at all."""
    idx = link_index()
    notes = {rel: p for p, rel in chunking.iter_notes()}
    out: dict[str, set[str]] = {rel: set() for rel in notes}
    inbound: dict[str, set[str]] = defaultdict(set)
    for rel, p in notes.items():
        for tgt in raw_links(p.read_text(encoding="utf-8", errors="replace")):
            dest = idx.get(tgt.lower())
            if dest and dest != rel:
                out[rel].add(dest)
                inbound[dest].add(rel)
    return {"notes": notes, "out": out, "inbound": inbound}


def _components(out: dict[str, set[str]]) -> list[list[str]]:
    parent = {n: n for n in out}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for src, dsts in out.items():
        for d in dsts:
            union(src, d)
    groups: dict[str, list[str]] = defaultdict(list)
    for n in out:
        groups[find(n)].append(n)
    return sorted(groups.values(), key=len, reverse=True)


def _stale_days(p: Path) -> int | None:
    try:
        fm, _title, _tags, _aliases, _body = chunking.parse_note(p)
    except Exception:  # noqa: BLE001
        return None
    raw = str(fm.get("updated") or fm.get("date") or "").strip().strip('"')
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            d = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None
    return (date.today() - d).days


def health() -> dict:
    """The four-metric health snapshot, with verdicts against thresholds."""
    g = graph()
    out, inbound, notes = g["out"], g["inbound"], g["notes"]
    n = len(notes)
    links = sum(len(v) for v in out.values())
    orphans = [r for r in notes if not out[r] and not inbound.get(r)]
    comps = _components(out) if n else []
    main_share = (len(comps[0]) / n) if (comps and n) else 0.0
    sub_pages = sum(len(c) for c in comps[1:])  # pages outside the main component
    stale = [r for r, p in notes.items()
             if (d := _stale_days(p)) is not None and d > STALE_DAYS]

    orphan_rate = len(orphans) / n if n else 0.0
    avg_degree = links / n if n else 0.0

    def orphan_verdict() -> str:
        if orphan_rate >= ORPHAN_BROKEN:
            return "broken"
        return "healthy" if orphan_rate < ORPHAN_HEALTHY else "watch"

    def degree_verdict() -> str:
        return "healthy" if DEGREE_MIN <= avg_degree <= DEGREE_MAX else "watch"

    def connectivity_verdict() -> str:
        return "healthy" if main_share >= MAIN_COMPONENT_MIN else "watch"

    return {
        "pages": n,
        "links": links,
        "avg_degree": round(avg_degree, 2),
        "orphan_count": len(orphans),
        "orphan_rate": round(orphan_rate, 3),
        "main_component_share": round(main_share, 3),
        "disconnected_pages": sub_pages,
        "stale_count": len(stale),
        "stale_rate": round(len(stale) / n, 3) if n else 0.0,
        "verdicts": {"orphans": orphan_verdict(), "degree": degree_verdict(),
                     "connectivity": connectivity_verdict()},
        "thresholds": {"orphan_healthy": ORPHAN_HEALTHY, "orphan_broken": ORPHAN_BROKEN,
                       "degree": [DEGREE_MIN, DEGREE_MAX], "main_component": MAIN_COMPONENT_MIN,
                       "stale_days": STALE_DAYS},
    }
