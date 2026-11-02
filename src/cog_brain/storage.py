"""Atomic note writes and locks shared across processes and transports."""
from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from cog_brain import config


def revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@contextmanager
def note_lock(path: Path):
    directory = config.STATE_DIR / "note-locks"
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(path.resolve()).encode()).hexdigest()
    with (directory / key).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_write(path: Path, text: str, *, create: bool = False,
                 expected: str | None = None) -> None:
    """Publish a complete file; new notes never replace another writer's note.

    The lock coordinates cog-brain writers. External editors do not share it;
    expected detects observed external edits, but cannot provide filesystem CAS.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".cog-brain-", dir=path.parent)
    try:
        if path.exists():
            os.fchmod(fd, path.stat().st_mode & 0o777)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        if create:
            os.link(temporary, path)
        else:
            if expected is not None and revision(path.read_text(encoding="utf-8")) != expected:
                raise ValueError("conflict: note changed; read it again before updating")
            os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
