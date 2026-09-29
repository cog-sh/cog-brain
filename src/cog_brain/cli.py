"""Operator CLI for cog-brain.

The MCP server (``cog-brain``) is what agents call; this is for humans at a
shell: inspect index health, diagnose, pick a backend, reindex, and trace a
retrieval query. Nothing here mutates the vault.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from cog_brain import chunking, config
from cog_brain.backends import available, get_backend


def _status(args) -> int:
    print(json.dumps(get_backend(args.backend).status(), ensure_ascii=False, indent=1))
    return 0


def _doctor(args) -> int:
    ok = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and cond
        print(("  ok   " if cond else "  FAIL ") + name + (f" — {detail}" if detail else ""))

    v = config.VAULT
    check("vault exists", v.is_dir(), str(v))
    check("vault readable", os.access(v, os.R_OK), str(v))
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        check("state dir writable", os.access(config.STATE_DIR, os.W_OK), str(config.STATE_DIR))
    except OSError as e:
        check("state dir writable", False, str(e))

    b = get_backend(args.backend)
    h = b.health()
    check(f"backend '{b.name}'", "error" not in h, json.dumps(h, ensure_ascii=False))
    print("\nbackends available:", ", ".join(available()))
    return 0 if ok else 1


def _backends(args) -> int:
    for n in available():
        print(("* " if n == config.BACKEND else "  ") + n)
    print(f"\nactive: {config.BACKEND}  (override: COG_BRAIN_BACKEND or --backend)")
    return 0


def _reindex(args) -> int:
    from cog_brain import indexer
    if args.backend:
        config.BACKEND = args.backend
    print(indexer.run(full=args.full))
    return 0


def _inspect_chunks(args) -> int:
    p = (config.VAULT / args.note).resolve()
    if not p.is_relative_to(config.VAULT) or not p.exists():
        print(f"not found: {args.note}", file=sys.stderr)
        return 1
    rel = p.relative_to(config.VAULT).as_posix()
    chunks = chunking.chunks_for(p, rel)
    print(json.dumps({"file_path": rel, "chunk_count": len(chunks), "chunks": [
        {"idx": c["idx"], "heading_path": c["heading_path"], "chars": len(c["text"]),
         "links": c["links"]} for c in chunks]}, ensure_ascii=False, indent=1))
    return 0


def _inspect_query(args) -> int:
    hits = get_backend(args.backend).search(args.query, args.k, tag=args.tag, folder=args.folder)
    for h in hits:
        hp = h.payload.get("heading_path") or ""
        print(f"{h.score:>9.4f}  {h.payload.get('file_path')}" + (f"  [{hp}]" if hp else ""))
    if not hits:
        print("(no hits)")
    return 0


def _mcp_config(args) -> int:
    from cog_brain import harnesses as H
    env = dict(kv.split("=", 1) for kv in args.env)
    spec = H.build_spec(source=args.source, env=env)
    names = [args.harness] if args.harness else sorted(H.HARNESSES)
    for n in names:
        h = H.resolve(n)
        print(f"# {h.doc}")
        print(H.render(h, spec))
    return 0


def _install(args) -> int:
    from cog_brain import harnesses as H
    env = dict(kv.split("=", 1) for kv in args.env)
    spec = H.build_spec(source=args.source, env=env)
    h = H.resolve(args.harness)
    path = H.target_path(h, args.scope)
    key = H.merge(path, h, spec)
    print(f"wrote {key} -> {path}")
    return 0


def _health(args) -> int:
    from cog_brain import graph
    h = graph.health()
    if args.json:
        print(json.dumps(h, ensure_ascii=False, indent=1))
        return 0
    v = h["verdicts"]
    print(f"pages={h['pages']}  links={h['links']}  avg_degree={h['avg_degree']} ({v['degree']})")
    print(f"orphans={h['orphan_count']} ({h['orphan_rate']:.1%}, {v['orphans']})")
    print(f"main_component={h['main_component_share']:.1%} ({v['connectivity']}), "
          f"disconnected={h['disconnected_pages']}")
    print(f"stale(>{h['thresholds']['stale_days']}d)={h['stale_count']} ({h['stale_rate']:.1%})")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="cog-brain", description="cog-brain operator CLI")
    ap.add_argument("--backend", default=None, help="override COG_BRAIN_BACKEND")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="index health (notes on disk vs indexed, staleness)")
    sub.add_parser("doctor", help="diagnose vault, state dir, and the active backend")
    sub.add_parser("backends", help="list memory backends and show the active one")
    sub.add_parser("reindex", help="rebuild the index").add_argument("--full", action="store_true")
    hp = sub.add_parser("health", help="vault health: 4 metrics with thresholds")
    hp.add_argument("--json", action="store_true")

    insp = sub.add_parser("inspect", help="retrieval inspection")
    isub = insp.add_subparsers(dest="what", required=True)
    ic = isub.add_parser("chunks", help="show how one note is chunked")
    ic.add_argument("note")
    iq = isub.add_parser("query", help="trace a query: which notes and scores")
    iq.add_argument("query")
    iq.add_argument("-k", type=int, default=10)
    iq.add_argument("--tag")
    iq.add_argument("--folder")

    mc = sub.add_parser("mcp-config", help="print paste-ready MCP config for a harness")
    mc.add_argument("--harness", help="harness name (default: all)")
    mc.add_argument("--source", help="uvx --from source (default: the cog-brain repo)")
    mc.add_argument("--env", action="append", default=[], help="K=V, repeatable")

    ins = sub.add_parser("install", help="write the MCP entry into a harness config")
    ins.add_argument("--harness", required=True)
    ins.add_argument("--scope", choices=["global", "project"], default="global")
    ins.add_argument("--source")
    ins.add_argument("--env", action="append", default=[], help="K=V, repeatable")

    a = ap.parse_args()
    if a.backend:
        config.BACKEND = a.backend
    if a.cmd == "inspect":
        rc = {"chunks": _inspect_chunks, "query": _inspect_query}[a.what](a)
    else:
        rc = {"status": _status, "doctor": _doctor, "backends": _backends,
              "reindex": _reindex, "health": _health,
              "mcp-config": _mcp_config, "install": _install}[a.cmd](a)
    sys.exit(rc)


if __name__ == "__main__":
    main()
