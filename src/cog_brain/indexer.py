"""Second-brain indexer CLI — drives the configured memory backend's ``sync``.

The storage/retrieval engine is selected by ``COG_BRAIN_BACKEND`` (default
``sqlite``); this entry point only acquires the run lock and reports the diff.
"""
from __future__ import annotations

import argparse
import sys
import time

from cog_brain import config
from cog_brain.backends import get_backend


def run(full: bool = False) -> str:
    backend = get_backend()
    r = backend.sync(full=full)
    return (f"backend={backend.name} changed={r['changed']} deleted={r['deleted']} "
            f"total={r['total']} elapsed={r['elapsed']}s")


def watch(full: bool = False) -> None:
    print("watch mode: polling every 3s")
    while True:
        print(run(full), flush=True)
        time.sleep(3)


def main() -> None:
    import fcntl
    config.LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(config.LOCK, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another indexer is already running — exit")
        sys.exit(0)
    ap = argparse.ArgumentParser(prog="cog-brain-index")
    ap.add_argument("--full", action="store_true", help="re-index every note")
    ap.add_argument("--watch", action="store_true", help="poll the vault every 3s")
    ap.add_argument("--backend", default=None, help="override COG_BRAIN_BACKEND")
    a = ap.parse_args()
    if a.backend:
        config.BACKEND = a.backend
    if a.watch:
        watch(a.full)
    else:
        print(run(a.full))


if __name__ == "__main__":
    main()
