"""Service bootstrap and client adapters on temporary configuration only."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cog_brain import bootstrap as B, config
from cog_brain.integration import install_code


class SetupClients(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.path = self.root / "config.toml"
        patcher = patch.multiple(config, VAULT=self.vault, STATE_DIR=self.root / "state",
            CONFIG_PATH=self.path, QDRANT_URL="http://127.0.0.1:6333",
            OLLAMA="http://127.0.0.1:11434/api/embed", EMBED_MODEL="qwen3-embedding:0.6b", COLLECTION="test")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.dict(os.environ, COG_BRAIN_CONFIG=str(self.path), COG_BRAIN_VAULT=str(self.vault),
                             COG_BRAIN_STATE_DIR=str(self.root / "state"), COG_BRAIN_BACKEND="markdown")
        patcher.start()
        self.addCleanup(patcher.stop)

    def response(self, dimensions=1024):
        response = MagicMock()
        response.json.return_value = {"embeddings": [[0.1] * dimensions]}
        return response

    def healthy(self, url, **kwargs):
        if url.endswith("/api/tags"):
            return {"models": [{"name": config.EMBED_MODEL}]}
        if url.endswith("/collections"):
            return {"result": {"collections": []}}
        return None

    def test_dry_run_does_not_require_docker_or_modify_config(self):
        with patch.object(B, "_json") as get, patch.object(B, "_command") as command:
            result = B.setup(backend="qdrant", dry_run=True)
        self.assertEqual(len(result["commands"]), 2)
        self.assertIn("127.0.0.1:6333:6333", result["commands"][0])
        self.assertIn("type=volume,source=cog-brain-qdrant-data,target=/qdrant/storage", result["commands"][0])
        self.assertFalse(self.path.exists())
        get.assert_not_called()
        command.assert_not_called()

    def test_sqlite_setup_preserves_other_toml_and_comments(self):
        self.path.write_text('# keep comment\nbackend = "markdown"\n[other]\nvalue = 42\n')
        with patch.object(B, "_command") as command, patch.object(B, "_json") as get:
            B.setup(backend="sqlite", no_index=True)
        text = self.path.read_text()
        self.assertIn("# keep comment", text)
        self.assertIn("[other]", text)
        self.assertIn("value = 42", text)
        self.assertIn('backend = "sqlite"', text)
        self.assertTrue(list(self.root.glob("config.toml.bak-cogbrain-*")))
        command.assert_not_called()
        get.assert_not_called()

    def test_missing_docker_gives_action_without_switching_backend(self):
        self.path.write_text('backend = "sqlite"\n')
        with patch.object(B, "_json", return_value=None), patch.object(B.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Docker is not installed"):
                B.setup(backend="qdrant", no_index=True)
        self.assertEqual(self.path.read_text(), 'backend = "sqlite"\n')

    def test_existing_services_are_reused_without_container_commands(self):
        with patch.object(B, "_json", side_effect=self.healthy), patch.object(B, "_command") as command, \
             patch.object(B.requests, "post", return_value=self.response()), patch.object(B, "_start") as start:
            result = B.setup(backend="qdrant", no_index=True)
        self.assertEqual(result["reused_services"], ["qdrant", "ollama"])
        self.assertIn('backend = "qdrant"', self.path.read_text())
        command.assert_not_called()
        start.assert_not_called()

    def test_embedding_failure_does_not_switch_configuration(self):
        self.path.write_text('backend = "sqlite"\n')
        with patch.object(B, "_json", side_effect=self.healthy), \
             patch.object(B.requests, "post", return_value=self.response(768)):
            with self.assertRaisesRegex(ValueError, "1024"):
                B.setup(backend="qdrant", no_index=True)
        self.assertEqual(self.path.read_text(), 'backend = "sqlite"\n')

    def test_foreign_container_is_never_started_or_replaced(self):
        result = MagicMock(returncode=0, stdout=json.dumps([{"Config": {"Labels": {}}, "State": {"Running": False}}]))
        with patch.object(B.subprocess, "run", return_value=result), patch.object(B, "_command") as command:
            with self.assertRaisesRegex(RuntimeError, "ownership"):
                B._start("qdrant", B.QDRANT_IMAGE, 6333, 6333)
        command.assert_not_called()

    def test_managed_stopped_container_is_restarted_not_recreated(self):
        info = {"Config": {"Labels": {B.LABEL: "true", "io.cog-brain.port": "6333"}}, "State": {"Running": False}}
        with patch.object(B.subprocess, "run", return_value=MagicMock(returncode=0, stdout=json.dumps([info]))), \
             patch.object(B, "_command") as command:
            B._start("qdrant", B.QDRANT_IMAGE, 6333, 6333)
        command.assert_called_once_with(["docker", "start", "cog-brain-qdrant"])

    def test_malformed_config_is_refused_before_network(self):
        self.path.write_text('backend = [broken')
        with patch.object(B, "_json") as get:
            with self.assertRaises(Exception):
                B.setup(backend="qdrant", no_index=True)
        get.assert_not_called()
        self.assertEqual(self.path.read_text(), 'backend = [broken')

    def test_missing_services_are_started_before_configuration_switch(self):
        self.path.write_text('backend = "sqlite"\n')
        def start(*args):
            self.assertEqual(self.path.read_text(), 'backend = "sqlite"\n')
        with patch.object(B, "_json", side_effect=[None, None, {"models": []}, None]), \
             patch.object(B.shutil, "which", return_value="docker"), \
             patch.object(B, "_command") as command, patch.object(B, "_start", side_effect=start) as launch, \
             patch.object(B, "_wait"), patch.object(B, "_pull") as pull, \
             patch.object(B.requests, "post", return_value=self.response()):
            B.setup(backend="qdrant", no_index=True)
        self.assertEqual(launch.call_count, 2)
        self.assertEqual(command.call_args.args[0][:2], ["docker", "info"])
        pull.assert_called_once()
        self.assertIn('backend = "qdrant"', self.path.read_text())

    def test_incompatible_collection_does_not_switch_configuration(self):
        self.path.write_text('backend = "sqlite"\n')
        def healthy(url, **kwargs):
            if "/collections/" in url:
                return {"result": {"config": {"params": {"vectors": {"dense": {"size": 768}}}}}}
            return self.healthy(url)
        with patch.object(B, "_json", side_effect=healthy), \
             patch.object(B.requests, "post", return_value=self.response()):
            with self.assertRaisesRegex(ValueError, "incompatible"):
                B.setup(backend="qdrant", no_index=True)
        self.assertEqual(self.path.read_text(), 'backend = "sqlite"\n')

    def test_collection_auth_error_is_not_treated_as_missing(self):
        import requests
        response = MagicMock(status_code=403)
        response.raise_for_status.side_effect = requests.HTTPError("forbidden")
        with patch.object(B.requests, "get", return_value=response):
            with self.assertRaises(requests.HTTPError):
                B._json("https://example.invalid/collections/test", required=True)

    def test_remote_dry_run_never_plans_local_containers(self):
        with patch.multiple(config, QDRANT_URL="https://qdrant.example.invalid", OLLAMA="https://ollama.example.invalid/api/embed"):
            result = B.setup(backend="qdrant", dry_run=True)
        self.assertEqual(result["commands"], [])
        self.assertEqual(len(result["remote_services"]), 2)

    def test_copilot_project_uses_github_instructions(self):
        install_code("copilot", scope="project", home=self.home, cwd=self.root)
        self.assertTrue((self.root / ".github/copilot-instructions.md").exists())
        self.assertTrue((self.root / ".github/skills/cog-brain/notes.md").exists())

    def test_opencode_generated_bridges_execute_native_contracts(self):
        paths = install_code("opencode", scope="project", home=self.home, cwd=self.root)
        plugin = next(Path(p) for p in paths if p.endswith("index.js"))
        script = self.root / "check.mjs"
        script.write_text("""
import assert from 'node:assert/strict';
const {default: plugin} = await import(process.argv[2]);
let handler;
const own = {disabled: false};
await plugin.setup({location: {directory: process.cwd()}, directory: "/nonexistent-wrong-directory",
  mcp: {transform: async fn => fn({get: () => own, update: (name, fn) => fn(own)})},
  session: {hook: async (name, fn) => {assert.equal(name, 'context'); handler = fn;}}});
assert.equal(own.disabled, true);
const event = {messages: [{role: 'user', content: [{type:'text', text:'current task'}]}], system: []};
await handler(event);
assert.equal(event.system[0].type, 'text');
assert.match(event.system[0].text, /cog-brain/);
assert.doesNotMatch(event.system[0].text, /unavailable|could not start/);
const old = await plugin.server({directory: process.cwd()});
const config = {mcp: {'cog-brain': {enabled: true}, foreign: {enabled: true}}};
await old.config(config);
assert.equal(config.mcp['cog-brain'].enabled, false);
assert.equal(config.mcp.foreign.enabled, true);
const output = {system: []};
await old['experimental.chat.system.transform']({}, output);
assert.match(output.system[0], /cog-brain/);
assert.doesNotMatch(output.system[0], /unavailable/);
""")
        result = subprocess.run(["node", str(script), plugin.as_uri()], cwd=self.root,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_setup_cli_default_needs_no_services(self):
        result = subprocess.run([sys.executable, "-m", "cog_brain.cli", "setup", "--no-index"],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["backend"], "sqlite")
        self.assertIn('backend = "sqlite"', self.path.read_text())

    def test_all_client_installations_are_idempotent(self):
        for harness in ("claude-code", "cursor", "gemini-cli", "copilot", "vscode", "windsurf", "opencode"):
            scope = "project" if harness == "vscode" else "global"
            first = install_code(harness, home=self.home, cwd=self.root, scope=scope)
            snapshots = {path: Path(path).read_text() for path in first}
            second = install_code(harness, home=self.home, cwd=self.root, scope=scope)
            self.assertEqual(first, second)
            self.assertEqual(snapshots, {path: Path(path).read_text() for path in second})
        cursor = json.loads((self.home / ".cursor/hooks.json").read_text())
        self.assertIn("sessionStart", cursor["hooks"])
        self.assertNotIn("beforeSubmitPrompt", cursor["hooks"])

    def test_vscode_global_does_not_leave_partial_files(self):
        with self.assertRaisesRegex(ValueError, "scope project"):
            install_code("vscode", home=self.home, cwd=self.root)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_hook_protocols_have_native_output_shapes(self):
        for harness, event in (("claude-code", "UserPromptSubmit"), ("gemini-cli", "BeforeAgent"), ("cursor", "sessionStart")):
            result = subprocess.run([sys.executable, "-m", "cog_brain.cli", "hook", "--harness", harness],
                input=json.dumps({"cwd": str(self.root), "hook_event_name": event, "prompt": "task"}),
                text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            if harness == "cursor":
                self.assertIn("additional_context", data)
            else:
                self.assertIn("additionalContext", data["hookSpecificOutput"])

    def test_settings_hooks_preserve_unrelated_configuration_and_mcp(self):
        path = self.home / ".claude/settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"permissions": {"allow": ["Read"]},
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "foreign"}]}]}}))
        install_code("claude-code", home=self.home, cwd=self.root)
        data = json.loads(path.read_text())
        self.assertEqual(data["permissions"]["allow"], ["Read"])
        self.assertEqual(data["hooks"]["SessionStart"][0]["hooks"][0]["command"], "foreign")


if __name__ == "__main__":
    unittest.main()
