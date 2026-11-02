"""Regression and protocol proof on isolated vaults; never touches personal notes."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cog_brain import Brain, chunking, config, frontmatter, operations
from cog_brain.backends.markdown import MarkdownBackend
from cog_brain.backends.sqlite import SqliteBackend
from cog_brain.integration import hook_context, install_code


class LocalAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "vault"
        self.vault.mkdir()
        state = self.root / "state"
        values = {"VAULT": self.vault, "STATE_DIR": state, "DB": state / "index.db",
                  "LOCK": state / ".index.lock", "SQLITE_PATH": state / "sqlite.db", "BACKEND": "markdown"}
        p = patch.multiple(config, **values)
        p.start()
        self.addCleanup(p.stop)
        p = patch.dict(os.environ, {"COG_BRAIN_VAULT": str(self.vault),
                                   "COG_BRAIN_STATE_DIR": str(state), "COG_BRAIN_BACKEND": "markdown",
                                   "COG_BRAIN_SQLITE_DB": str(state / "sqlite.db")})
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(operations, "VAULT", self.vault)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(operations, "backend", MarkdownBackend())
        p.start()
        self.addCleanup(p.stop)
        MarkdownBackend().reset()
        self.brain = Brain()
        self.note("hub.md", {"title": "Hub", "aliases": ["Центр"]}, "Existing hub [[knowledge]]")
        self.note("knowledge.md", {"title": "Knowledge", "project": "demo"}, "verified knowledge [[hub]]")

    def note(self, name, fields, body):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(frontmatter.render(fields, body), encoding="utf-8")
        return path

    def cli(self, operation, fields, **kwargs):
        return subprocess.run([sys.executable, "-m", "cog_brain.cli", "call", operation],
                              input=json.dumps(fields), text=True, capture_output=True, **kwargs)

    def test_roundtrip_preserves_unknown_yaml_and_comments(self):
        path = self.vault / "human.md"
        path.write_text('---\ntitle: "Human" # title comment\ntags:\n  - important # tag comment\ncustom:\n  nested: preserve-me\nsummary: |\n  first\n  second\n---\n\nOriginal [[hub]]\n')
        self.brain.update("human.md", content="Added", append=True, auto_index=False)
        text = path.read_text()
        fm = frontmatter.parse(frontmatter.split(text)[0])
        self.assertEqual(fm["tags"], ["important"])
        self.assertEqual(fm["custom"]["nested"], "preserve-me")
        self.assertEqual(fm["summary"], "first\nsecond\n")
        self.assertIn("# title comment", text)
        self.assertIn("# tag comment", text)
        self.assertIn("Original [[hub]]", text)

    def test_conflict_and_body_replacement(self):
        old = self.brain.read("knowledge.md")
        self.brain.update("knowledge.md", content="Concurrent", append=True, auto_index=False)
        with self.assertRaisesRegex(ValueError, "conflict"):
            self.brain.update("knowledge.md", content="Replacement [[hub]]",
                              expected_hash=old["revision"], auto_index=False)
        with self.assertRaisesRegex(ValueError, "expected_hash"):
            self.brain.update("knowledge.md", content="Replacement [[hub]]", auto_index=False)
        self.assertIn("Concurrent", self.brain.read("knowledge.md")["text"])

    def test_index_failure_does_not_hide_committed_write(self):
        with patch.object(operations, "run_indexer", side_effect=RuntimeError("index unavailable")):
            result = self.brain.create("committed.md", "Committed", "body [[hub]]", description="Saved")
        self.assertEqual(result["created"], "committed.md")
        self.assertEqual(result["index_state"], "failed")
        self.assertIn("body", self.brain.read("committed.md")["text"])

    def test_partial_index_cli_reports_failure_without_traceback(self):
        (self.vault / "broken.md").write_text('---\ntitle: [broken\n---\nbody')
        env = dict(os.environ, COG_BRAIN_BACKEND="sqlite")
        result = subprocess.run([sys.executable, "-m", "cog_brain.cli", "reindex"],
                                env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn("index incomplete: failed=1", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_protected_normalized_and_symlink_paths(self):
        self.note("90-meta/protected.md", {}, "[[hub]]")
        for path in ("90-meta/protected.md", "x/../90-meta/protected.md"):
            with self.assertRaisesRegex(ValueError, "off-limits"):
                self.brain.update(path, title="changed", auto_index=False)
        outside = self.root / "outside.md"
        outside.write_text("[[hub]]")
        (self.vault / "link.md").symlink_to(outside)
        with self.assertRaises(ValueError):
            self.brain.update("link.md", title="changed", auto_index=False)
        self.assertEqual(outside.read_text(), "[[hub]]")

    def test_description_aliases_and_related_retraction(self):
        self.brain.create("old.md", "Old", "knowledge [[hub]]", description="uniqueprobe",
                          aliases=["uniquename"], retracted=True, auto_index=False)
        self.assertIs(frontmatter.parse(frontmatter.split((self.vault / "old.md").read_text())[0])["retracted"], True)
        for backend in (MarkdownBackend(), SqliteBackend(self.root / "test.db")):
            backend.sync()
            self.assertTrue(backend.search("uniqueprobe", 5))
            self.assertTrue(backend.search("uniquename", 5))
        self.assertEqual(operations.resolve_links("[[Центр]]")[0], ["hub.md"])
        related = json.loads(operations.find_related("knowledge.md", k=2))
        old = [h for h in related["semantic_neighbors"] if h["file_path"] == "old.md"]
        self.assertTrue(old[0]["retracted"])

    def test_section_and_capture_idempotence(self):
        self.note("sections.md", {}, "# Main\n[[hub]]\n## First\nA\n### Child\nB\n## Second\nC")
        text = self.brain.read("sections.md", section="First")["text"]
        self.assertIn("Child", text)
        self.assertNotIn("Second", text)
        a = self.brain.capture("raw idea", source="test", event_id="one")
        b = self.brain.capture("raw idea", source="test", event_id="one")
        self.assertFalse(a["duplicate"])
        self.assertTrue(b["duplicate"])
        self.assertEqual((self.vault / a["file_path"]).read_text().count("raw idea"), 1)
        self.assertNotIn(a["file_path"], [r for _, r in chunking.iter_notes()])
        self.assertIn(a["file_path"], [n["file_path"] for n in self.brain.list_notes(folder="daily")["notes"]])

    def test_malformed_yaml_is_reported_and_never_rewritten(self):
        path = self.vault / "broken.md"
        raw = '---\ntitle: [broken\n---\n[[hub]]'
        path.write_text(raw)
        with self.assertRaises(ValueError):
            self.brain.update("broken.md", content="addition", append=True, auto_index=False)
        self.assertEqual(path.read_text(), raw)
        result = self.brain.search("knowledge", lexical=True)
        self.assertTrue(result["hits"])
        self.assertIn("broken.md", result["index"]["failed"])
        self.assertTrue(result["warnings"])

    def test_handoff_updates_state_and_preserves_goal_and_links(self):
        self.brain.project("demo.md", "Demo", cwd=self.root,
            content="## Goal\nKeep [[knowledge]]\n\n## Current state\nOld\n\n## Next step\nOld step",
            description="Demo", auto_index=False)
        self.brain.handoff("demo.md", state="Implemented", next_step="Verify", verification="tests passed",
                           auto_index=False)
        text = self.brain.read("demo.md")["text"]
        self.assertIn("Keep [[knowledge]]", text)
        self.assertIn("Implemented", text)
        self.assertIn("tests passed", text)
        self.assertNotIn("Old step", text)

    def test_capture_rejects_directory_symlink(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.vault / "daily").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.brain.capture("raw")
        self.assertEqual(list(outside.iterdir()), [])

    def test_native_extensions_deliver_context_and_restore_after_compaction(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("Node required for lifecycle adapter proof")
        self.brain.project("demo.md", "Demo", cwd=self.root, content="Resume this task [[knowledge]]",
                           description="Demo", auto_index=False)
        script = self.root / "extension-check.mjs"
        script.write_text('''import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const mod = await import(pathToFileURL(process.argv[2]));
const handlers = new Map(); const sent = [];
mod.default({on: (name, handler) => handlers.set(name, handler), sendMessage: message => sent.push(message)});
const context = {cwd: process.argv[3]};
const response = await handlers.get('before_agent_start')({prompt: 'knowledge'}, context);
assert.match(response.message.content, /Resume this task/);
assert.equal(response.message.display, false);
await handlers.get('session_compact')({}, context);
assert.match(sent[0].content, /Resume this task/);
''')
        for harness in ("omp", "pi"):
            extension = install_code(harness, home=self.root / "home")[-1]
            result = subprocess.run(["node", str(script), extension, str(self.root)],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_snapshot_freshness_without_mtime(self):
        backend = SqliteBackend(self.root / "index.db")
        self.assertEqual(backend.status()["stale_count"], -1)
        backend.sync()
        added = self.note("added.md", {}, "new [[hub]]")
        os.utime(added, (1, 1))
        self.assertIn("added.md", backend.status()["added"])
        backend.sync()
        stat = added.stat()
        added.write_text("different [[hub]]")
        os.utime(added, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertIn("added.md", backend.status()["stale"])
        added.unlink()
        self.assertIn("added.md", backend.status()["deleted"])

    def test_qdrant_embedding_failure_keeps_old_points_and_reports_failure(self):
        from cog_brain.backends.qdrant import QdrantBackend
        backend = QdrantBackend()
        backend.ensure = MagicMock()
        backend.count = MagicMock(return_value=2)
        backend._delete_file = MagicMock()
        backend._client = MagicMock()
        backend._embed_texts = MagicMock(side_effect=RuntimeError("embedding down"))
        result = backend.sync()
        self.assertTrue(result["errors"])
        backend._delete_file.assert_not_called()
        backend._client.upsert.assert_not_called()
        self.assertGreater(backend.status()["stale_count"], 0)
        self.assertTrue(backend.status()["failed"])

    def test_qdrant_replaces_chunks_without_deleting_before_embeddings(self):
        from qdrant_client import QdrantClient, models
        from cog_brain.backends.qdrant import QdrantBackend
        backend = QdrantBackend()
        backend._client = QdrantClient(":memory:")
        self.addCleanup(backend._client.close)
        backend._embed_texts = lambda texts: [[1.0] + [0.0] * 1023 for _ in texts]
        backend._sparse = lambda texts: [models.SparseVector(indices=[7], values=[1.0]) for _ in texts]
        path = self.note("long.md", {"title": "Long"}, "# First\n" + "word " * 1200 + "\n## Second\n" + "word " * 1200)
        first = backend.sync(notes=[(path, "long.md")])
        self.assertFalse(first["errors"])
        self.assertGreater(backend.count(), 1)
        path.write_text("# Short\nbody")
        second = backend.sync(notes=[(path, "long.md")])
        self.assertFalse(second["errors"])
        self.assertEqual(backend.count(), 1)
        path.write_text("# New\nchanged")
        backend._embed_texts = MagicMock(side_effect=RuntimeError("embedding down"))
        failed = backend.sync(notes=[(path, "long.md")])
        self.assertTrue(failed["errors"])
        self.assertEqual(backend.count(), 1)
        self.assertIn("long.md", backend.status()["stale"])

    def test_parallel_append_no_lost_updates(self):
        children = []
        for i in range(6):
            child = subprocess.Popen([sys.executable, "-m", "cog_brain.cli", "call", "update"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            child.stdin.write(json.dumps({"file_path": "knowledge.md", "content": f"parallel-{i}",
                                          "append": True, "auto_index": False}))
            child.stdin.close()
            children.append(child)
        for child in children:
            self.assertEqual(child.wait(timeout=15), 0, child.stderr.read())
            child.stdout.close()
            child.stderr.close()
        text = self.brain.read("knowledge.md")["text"]
        for i in range(6):
            self.assertIn(f"parallel-{i}", text)

    def test_project_context_is_scoped_bounded_and_automatic(self):
        repo = self.root / "repo"
        repo.mkdir()
        self.brain.project("demo.md", "Demo", cwd=repo, content="Next step: verify. [[knowledge]]",
                           description="Project demo", auto_index=False)
        self.note("unrelated.md", {"project": "another"}, "knowledge SECRET_OTHER_PROJECT [[hub]]")
        context = self.brain.context(cwd=repo, query="knowledge", budget=1800, lexical=True)
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False)), 1800)
        self.assertEqual(context["card"]["file_path"], "demo.md")
        self.assertNotIn("SECRET_OTHER_PROJECT", json.dumps(context))
        event = {"cwd": str(repo), "prompt": "knowledge", "session_id": "test", "hook_event_name": "UserPromptSubmit"}
        text = hook_context(event, harness="codex")
        self.assertIn("Next step", text)
        self.assertEqual(hook_context(event, harness="codex"), "")
        event["hook_event_name"] = "PostCompact"
        self.assertTrue(hook_context(event, harness="codex"))

    def test_install_preserves_foreign_hooks_and_is_idempotent(self):
        home = self.root / "home"
        path = home / ".codex/hooks.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": "foreign"}]}]}}))
        instructions = home / ".codex/AGENTS.md"
        instructions.write_text("Existing project policy\n")
        toml = home / ".codex/config.toml"
        toml.write_text('[mcp_servers.cog-brain]\ncommand = "uvx"\nargs = ["cog-brain"]\nenabled = true\n\n[mcp_servers.other]\ncommand = "other"\n')
        install_code("codex", home=home)
        first = path.read_text()
        install_code("codex", home=home)
        self.assertEqual(path.read_text(), first)
        self.assertIn("foreign", first)
        self.assertIn("Existing project policy", instructions.read_text())
        self.assertEqual(instructions.read_text().count("<!-- cog-brain:start -->"), 1)
        import tomllib
        data = tomllib.loads(toml.read_text())
        self.assertFalse(data["mcp_servers"]["cog-brain"]["enabled"])
        self.assertEqual(data["mcp_servers"]["other"]["command"], "other")
        project = self.root / "project"
        project.mkdir()
        guide = project / "AGENTS.md"
        guide.write_text("Repository policy\n")
        install_code("codex", scope="project", home=home, cwd=project)
        self.assertIn("Repository policy", guide.read_text())
        self.assertIn("<!-- cog-brain:start -->", guide.read_text())
        for harness in ("omp", "pi"):
            installed = install_code(harness, home=home)
            self.assertTrue(Path(installed[-1]).exists())

    def test_cli_and_import_need_no_mcp(self):
        result = self.cli("search", {"query": "knowledge", "lexical": True})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["hits"])
        result = subprocess.run([sys.executable, "-c", "import sys; from cog_brain import Brain; Brain(); assert 'mcp' not in sys.modules"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_hook_process_contract(self):
        self.brain.project("demo.md", "Demo", cwd=self.root,
                           content="Unique resume step [[knowledge]]", description="Demo", auto_index=False)
        result = subprocess.run([sys.executable, "-m", "cog_brain.cli", "hook", "--harness", "codex"],
            input=json.dumps({"cwd": str(self.root), "hook_event_name": "SessionStart", "source": "compact"}),
            text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        self.assertIn("Unique resume step", output["additionalContext"])

    def test_real_mcp_protocol_uses_same_writes(self):
        async def exercise():
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(command=sys.executable, args=["-m", "cog_brain.server"], env=dict(os.environ))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    self.assertIn("write_note", names)
                    result = await session.call_tool("write_note", {"file_path": "wire.md", "title": "Wire",
                        "content": "knowledge [[hub]]", "description": "Wire test", "auto_index": False})
                    self.assertFalse(result.isError)
                    self.assertEqual(json.loads(result.content[0].text)["created"], "wire.md")
                    result = await session.call_tool("semantic_search", {"query": "knowledge"})
                    self.assertTrue(json.loads(result.content[0].text))
                    result = await session.call_tool("read_note", {"file_path": "wire.md"})
                    self.assertIn("Wire", result.content[0].text)
                    result = await session.call_tool("write_note", {"file_path": "bad.md", "title": "Bad",
                        "content": "[[hub]]", "description": " "})
                    self.assertTrue(result.isError)
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
