"""Opt-in local vector services; existing data and unrelated containers are never replaced."""
from __future__ import annotations

import json
import os
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from cog_brain import config

QDRANT_IMAGE = "qdrant/qdrant:v1.20.0"
OLLAMA_IMAGE = "ollama/ollama:0.40.13"
LABEL = "io.cog-brain.managed"


def _command(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} {argv[1]} failed: {(result.stderr or result.stdout)[-1000:]}")
    return result


def _json(url: str, *, required: bool = False):
    try:
        response = requests.get(url, timeout=(2, 3))
        if required:
            if response.status_code == 404:
                return None
            response.raise_for_status()
        if response.ok:
            data = response.json()
            if required and (not isinstance(data, dict) or not isinstance(data.get("result"), dict)):
                raise ValueError("Invalid Qdrant collection response; configuration was not switched.")
            return data
    except (requests.RequestException, ValueError):
        if required:
            raise
    return None


def _local_port(url: str) -> int:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1") or parsed.username:
        raise ValueError("Automatic containers require a loopback HTTP endpoint. Start remote services separately.")
    return parsed.port or 80


def _container(service: str, image: str, port: int, target: int) -> list[str]:
    return ["docker", "run", "--detach", "--name", f"cog-brain-{service}",
            "--label", f"{LABEL}=true", "--label", f"io.cog-brain.port={port}",
            "--restart", "unless-stopped", "--publish", f"127.0.0.1:{port}:{target}",
            "--mount", f"type=volume,source=cog-brain-{service}-data,target=" +
            ("/qdrant/storage" if service == "qdrant" else "/root/.ollama"), image]


def _start(service: str, image: str, port: int, target: int) -> None:
    name = f"cog-brain-{service}"
    result = subprocess.run(["docker", "container", "inspect", name], capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        info = json.loads(result.stdout)[0]
        labels = info.get("Config", {}).get("Labels") or {}
        if labels.get(LABEL) != "true" or labels.get("io.cog-brain.port") != str(port):
            raise RuntimeError(f"Container {name} already exists with different ownership or port; it was not modified.")
        if not info.get("State", {}).get("Running"):
            _command(["docker", "start", name])
    else:
        # The daemon was checked first. Only our named container may be created.
        _command(_container(service, image, port, target), timeout=900)


def _wait(url: str, key: str) -> dict:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        data = _json(url)
        if isinstance(data, dict) and key in data:
            return data
        time.sleep(0.5)
    raise RuntimeError(f"Service did not become ready: {url}. Configuration was not switched.")


def _pull(base: str) -> None:
    print(f"Downloading {config.EMBED_MODEL} through Ollama…", file=sys.stderr, flush=True)
    with requests.post(base + "/api/pull", json={"model": config.EMBED_MODEL, "stream": True},
                       stream=True, timeout=(5, 300)) as response:
        response.raise_for_status()
        last = ""
        for line in response.iter_lines():
            if not line:
                continue
            item = json.loads(line)
            if item.get("error"):
                raise RuntimeError(item["error"])
            status = item.get("status", "")
            if status != last:
                print(status, file=sys.stderr, flush=True)
                last = status
        if last != "success":
            raise RuntimeError("Ollama model download did not report success")


def setup(*, backend: str = "sqlite", vault: str | None = None,
          dry_run: bool = False, no_index: bool = False) -> dict:
    if backend not in ("sqlite", "markdown", "qdrant"):
        raise ValueError("backend must be sqlite, markdown or qdrant")
    root = Path(vault).expanduser().resolve() if vault else config.VAULT
    if not root.is_dir():
        raise ValueError("Vault does not exist. Use --vault /path/to/your/existing/notes.")
    # Parse before downloading anything; a broken config must never be overwritten.
    if config.CONFIG_PATH.exists():
        import tomlkit
        tomlkit.parse(config.CONFIG_PATH.read_text())
    base = config.OLLAMA.removesuffix("/api/embed").rstrip("/")
    if backend == "qdrant" and not config.OLLAMA.endswith("/api/embed"):
        raise ValueError("Qdrant setup requires an Ollama /api/embed endpoint")
    plan = {"backend": backend, "vault": str(root), "config": str(config.CONFIG_PATH),
            "commands": [], "reindex": not no_index}
    if backend == "qdrant":
        # A dry run is a plan, not a health check or a download.
        if dry_run:
            plan["remote_services"] = []
            for service, url, image, target in (
                ("qdrant", config.QDRANT_URL, QDRANT_IMAGE, 6333),
                ("ollama", base, OLLAMA_IMAGE, 11434),
            ):
                try:
                    port = _local_port(url)
                except ValueError:
                    plan["remote_services"].append({"service": service, "requires": "existing healthy endpoint"})
                else:
                    plan["commands"].append(_container(service, image, port, target))
        plan["embedding_model"] = config.EMBED_MODEL
    if dry_run:
        return plan
    reused = []
    if backend == "qdrant":
        endpoints = [("qdrant", config.QDRANT_URL.rstrip("/") + "/collections", "result", QDRANT_IMAGE, 6333),
                     ("ollama", base + "/api/tags", "models", OLLAMA_IMAGE, 11434)]
        missing = []
        for service, url, key, image, target in endpoints:
            data = _json(url)
            if isinstance(data, dict) and key in data:
                reused.append(service)
            else:
                missing.append((service, url, key, image, target,
                                _local_port(config.QDRANT_URL if service == "qdrant" else base)))
        if missing:
            if not shutil.which("docker"):
                raise RuntimeError("Docker is not installed. Install Docker Desktop (https://docs.docker.com/get-started/get-docker/) "
                                   "or use `cog-brain setup --backend sqlite` without services.")
            try:
                _command(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=10)
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                raise RuntimeError("Docker is not running. Start Docker Desktop or your Docker daemon, then retry. "
                                   "SQLite setup needs no Docker.") from error
            for service, url, key, image, target, port in missing:
                print(f"Starting managed {service} on 127.0.0.1:{port}…", file=sys.stderr, flush=True)
                _start(service, image, port, target)
                _wait(url, key)
        tags = _json(base + "/api/tags") or {}
        names = {m.get("name") for m in tags.get("models", [])}
        if config.EMBED_MODEL not in names:
            _pull(base)
        response = requests.post(config.OLLAMA, json={"model": config.EMBED_MODEL,
                                 "input": ["cog-brain setup check"]}, timeout=(5, 120))
        response.raise_for_status()
        vectors = response.json().get("embeddings", [])
        if not isinstance(vectors, list) or len(vectors) != 1 or not isinstance(vectors[0], list) or len(vectors[0]) != 1024 or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in vectors[0]
        ):
            raise ValueError("Embedding model must return 1024 dimensions; configuration was not switched.")
        collection = _json(config.QDRANT_URL.rstrip("/") + "/collections/" + config.COLLECTION, required=True)
        if collection:
            params = collection.get("result", {}).get("config", {}).get("params", {})
            dense = params.get("vectors", {}).get("dense", {})
            if dense.get("size") != 1024 or dense.get("distance") != "Cosine" or "bm25" not in params.get("sparse_vectors", {}):
                raise ValueError("Existing collection has an incompatible dense vector layout; it was not changed.")
    values = {"backend": backend, "vault": str(root)}
    if backend == "qdrant":
        values.update(qdrant_url=config.QDRANT_URL, ollama=config.OLLAMA,
                      embed_model=config.EMBED_MODEL, collection=config.COLLECTION)
    config.write_settings(values)
    warnings = [f"{config._KEYS[k]} overrides saved {k}" for k in values if config._SOURCES[k] == "env"]
    result = {**plan, "reused_services": reused, "warnings": warnings, "index": "not requested"}
    if not no_index:
        child = subprocess.run([sys.executable, "-m", "cog_brain.cli", "--backend", backend, "reindex"],
                               env={**os.environ, "COG_BRAIN_CONFIG": str(config.CONFIG_PATH),
                                    "COG_BRAIN_VAULT": str(root)}, capture_output=True, text=True, timeout=1800)
        result["index"] = {"ok": child.returncode == 0, "summary": (child.stdout or child.stderr).strip()[-3000:]}
    return result
