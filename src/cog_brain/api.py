"""Local, JSON-friendly API for code execution. No MCP imports or model calls."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from cog_brain import chunking, config, frontmatter, storage


def project_root(cwd: str | Path) -> Path:
    cwd = Path(cwd).expanduser().resolve()
    try:
        result = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--git-common-dir"],
                                capture_output=True, text=True, timeout=2, check=True)
        common = (cwd / result.stdout.strip()).resolve()
        if common.name == ".git":
            return common.parent
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd


class Brain:
    """Use configured vault/backend; every write shares the server's guards.

    Results are ordinary dictionaries/lists, suitable for JSON or composition.
    Creating a client does not initialize a backend or import the MCP package.
    """

    def __init__(self):
        from cog_brain import operations
        self.ops = operations

    @staticmethod
    def _result(text: str):
        if text.startswith(("error:", "not found:")):
            raise ValueError(text)
        return json.loads(text)

    def read(self, file_path: str, *, section: str | None = None,
             max_chars: int = 8000) -> dict:
        path, error = self.ops.load_note(file_path)
        if error:
            raise ValueError(error)
        raw = path.read_text(encoding="utf-8")
        fm = frontmatter.parse(frontmatter.split(raw)[0])
        text = self.ops.section_text(raw, section) if section else raw
        if not 1 <= max_chars <= 100_000:
            raise ValueError("max_chars must be 1..100000")
        return {"file_path": path.relative_to(config.VAULT).as_posix(),
                "title": str(fm.get("title", path.stem)), "text": text[:max_chars],
                "truncated": len(text) > max_chars, "revision": storage.revision(raw),
                "updated": str(fm.get("updated", "")),
                "retracted": str(fm.get("retracted", "")).lower() in ("true", "yes", "1"),
                "superseded_by": self.ops._as_list(fm.get("superseded_by")),
                "verified_at": str(fm.get("verified_at", ""))}

    def _project(self, project: str | None = None, cwd: str | Path | None = None) -> dict:
        root = project_root(cwd) if cwd is not None else None
        cards = []
        for path, rel in chunking.iter_notes():
            try:
                fm, title, tags, _, body = chunking.parse_note(path)
            except Exception:
                continue
            if fm.get("type") != "project":
                continue
            match = (project is not None and project in (rel, path.stem, fm.get("project"), title))
            if project is None and root is not None and fm.get("repo"):
                match = match or Path(str(fm["repo"])).expanduser().resolve() == root
            if match:
                cards.append({"file_path": rel, "project": str(fm.get("project") or path.stem),
                              "body": body})
        if len(cards) > 1:
            raise ValueError("ambiguous project: multiple cards match; specify the exact file_path")
        return cards[0] if cards else {"project": project or (root.name if root else ""),
                                     "file_path": None, "body": ""}

    def search(self, query: str, *, project: str | None = None, limit: int = 5,
               max_chars: int = 8000, lexical: bool = False) -> dict:
        if not 1 <= limit <= 50 or not 1 <= max_chars <= 100_000:
            raise ValueError("limit must be 1..50; max_chars must be 1..100000")
        from cog_brain.backends.markdown import MarkdownBackend
        backend = MarkdownBackend() if lexical else self.ops.backend
        status = backend.status()
        card = self._project(project) if project else None
        allowed = set()
        if card and card["file_path"]:
            from cog_brain.graph import link_index, raw_links
            idx = link_index()
            allowed.add(card["file_path"])
            allowed.update(idx[t.lower()] for t in raw_links(card["body"]) if t.lower() in idx)
        hits, remaining, seen = [], max_chars, set()
        for hit in backend.search(query, max(limit * 5, 50)):
            rel = hit.payload.get("file_path")
            if rel in seen:
                continue
            path, error = self.ops.load_note(rel)
            if error:
                continue
            if project:
                fm, _, tags, _, _ = chunking.parse_note(path)
                identity = card["project"] if card else project
                if rel not in allowed and fm.get("project") != identity and identity not in tags:
                    continue
            item = self.ops.cite(hit)
            text = item.get("text") or ""
            allowance = min(remaining, max(200, max_chars // limit))
            item["text"], item["truncated"] = text[:allowance], len(text) > allowance
            remaining -= len(item["text"])
            hits.append(item)
            seen.add(rel)
            if len(hits) >= limit or remaining <= 0:
                break
        warnings = ["lexical retrieval"] if lexical else []
        if status.get("failed"):
            warnings.append(f"{len(status['failed'])} notes could not be indexed; inspect index.failed")
        return {"hits": hits, "index": status, "backend": backend.name, "warnings": warnings}

    def context(self, *, project: str | None = None, query: str = "",
                cwd: str | Path | None = None, budget: int = 2000,
                lexical: bool = False) -> dict:
        """Bound the complete serialized packet in characters, including metadata.

        This is an output ceiling, not a tokenizer-dependent token count.
        Lifecycle integrations use lexical=True to avoid network startup delays.
        """
        if not 512 <= budget <= 16_000:
            raise ValueError("budget must be 512..16000")
        card = self._project(project, cwd)
        result = {"project": card["project"], "card": None, "notes": [], "warnings": []}
        if card["file_path"]:
            result["card"] = self.read(card["file_path"], max_chars=100_000)
            body = frontmatter.split(result["card"]["text"])[1].strip()
            result["card"]["text"] = body[:max(128, budget // 3)]
            result["card"]["truncated"] = len(body) > budget // 3
        else:
            result["warnings"].append("No project card bound to this repository; use brain.project(...).")
        if query and card["project"] and (card["file_path"] or project is not None):
            try:
                found = self.search(query, project=card["project"], max_chars=budget // 2,
                                    limit=4, lexical=lexical)
                result["notes"] = [hit for hit in found["hits"] if hit["file_path"] != card["file_path"]]
                result["warnings"].extend(found["warnings"])
                index = found["index"]
                result["index"] = {k: index.get(k) for k in
                                   ("backend", "state", "last_run", "stale_count")}
            except Exception as error:
                result["warnings"].append(f"Retrieval unavailable: {type(error).__name__}")
        while len(json.dumps(result, ensure_ascii=False)) > budget:
            if result["notes"]:
                result["notes"].pop()
            elif result["card"] and result["card"]["text"]:
                result["card"]["text"] = result["card"]["text"][:len(result["card"]["text"]) // 2]
                result["card"]["truncated"] = True
            else:
                return {"project": card["project"][:100], "warnings": ["Context exceeds budget"]}
        return result

    def create(self, file_path: str, title: str, content: str, **fields) -> dict:
        return self._result(self.ops.write_note(file_path, title, content, **fields))

    def list_notes(self, *, tag: str | None = None, folder: str | None = None,
                   limit: int = 200) -> dict:
        return self._result(self.ops.list_notes(tag=tag, folder=folder, limit=limit))

    def outline(self, file_path: str) -> dict:
        return self._result(self.ops.outline(file_path))

    def find_related(self, file_path: str, *, k: int = 10) -> dict:
        return self._result(self.ops.find_related(file_path, k=k))

    def backlinks(self, file_path: str, *, k: int = 50) -> dict:
        return self._result(self.ops.backlinks(file_path, k=k))

    def update(self, file_path: str, **fields) -> dict:
        if fields.get("content") is not None and not fields.get("append") and not fields.get("expected_hash"):
            raise ValueError("expected_hash from read().revision is required to replace a body")
        return self._result(self.ops.update_note(file_path, **fields))

    def project(self, file_path: str, title: str, *, cwd: str | Path,
                content: str, description: str, **fields) -> dict:
        """Create an explicitly bound project card; no guessed note paths."""
        return self.create(file_path, title, content, description=description, type="project",
                           repo=str(project_root(cwd)), project=Path(file_path).stem, **fields)

    def capture(self, content: str, *, source: str = "", event_id: str | None = None) -> dict:
        """Append raw material to today's daily; repeated event IDs are idempotent."""
        if not content.strip() or len(content) > 30_000 or len(source) > 2000:
            raise ValueError("capture needs 1..30000 characters and a source up to 2000 characters")
        now = datetime.now().astimezone()
        key = hashlib.sha256((event_id or (content + source)).encode()).hexdigest()
        path = config.VAULT / "daily" / f"daily-{now.date()}.md"
        resolved = path.resolve()
        if not resolved.is_relative_to(config.VAULT) or resolved.parent != config.VAULT / "daily":
            raise ValueError("capture path escapes daily directory")
        marker = f"<!-- cog-brain-event:{key} -->"
        with storage.note_lock(path):
            exists = path.exists()
            raw = path.read_text(encoding="utf-8") if exists else frontmatter.render(
                {"title": f"Daily {now.date()}", "type": "daily", "date": now.date()}, "\n")
            if marker in raw:
                return {"file_path": path.relative_to(config.VAULT).as_posix(), "duplicate": True}
            addition = f"\n## {now.isoformat(timespec='seconds')}\n\n{marker}\n"
            if source:
                addition += f"Source: {source}\n\n"
            addition += content.strip() + "\n"
            storage.atomic_write(path, raw + addition, create=not exists,
                                 expected=storage.revision(raw) if exists else None)
        return {"file_path": path.relative_to(config.VAULT).as_posix(), "duplicate": False,
                "revision": storage.revision(raw + addition)}

    def handoff(self, file_path: str, *, state: str, next_step: str,
                verification: str = "", blockers: str = "", auto_index: bool = True) -> dict:
        """Update the operational sections of a project card using its revision."""
        note = self.read(file_path, max_chars=100_000)
        if note["truncated"]:
            raise ValueError("project card exceeds handoff limit")
        fm, body = frontmatter.split(note["text"])
        if frontmatter.parse(fm).get("type") != "project":
            raise ValueError("handoff requires a project card")
        import re
        for heading, value in (("Current state", state), ("Next step", next_step),
                               ("Verification", verification), ("Blockers", blockers)):
            replacement = f"## {heading}\n\n{value.strip()}\n\n"
            pattern = rf"(?ms)^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)"
            if re.search(pattern, body):
                body = re.sub(pattern, lambda _: replacement, body, count=1)
            else:
                body = body.rstrip() + "\n\n" + replacement
        return self.update(file_path, content=body, expected_hash=note["revision"], auto_index=auto_index)
