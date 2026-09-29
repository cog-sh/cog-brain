"""Backend contract shared by every memory engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol


@dataclass
class Hit:
    """One search result. ``payload`` mirrors the historical Qdrant payload keys
    (``file_path``, ``note_title``, ``heading_path``, ``text``, ``tags``, …) so
    citation/formatting code is backend-independent."""
    payload: Mapping
    score: float


class Backend(Protocol):
    """A storage + retrieval engine. Swapping it must not change the tools."""

    name: str

    def sync(self, notes: Iterable[tuple] | None = None, full: bool = False) -> dict:
        """Bring the index in line with the vault. Returns
        ``{"changed", "deleted", "total", "elapsed"}``. Must be safe to call when
        already current (incremental)."""
        ...

    def search(self, query: str, k: int, *, tag: str | None = None,
               folder: str | None = None, exclude: str | None = None) -> list[Hit]:
        """Ranked hits for ``query``. Must never raise on an empty/missing index."""
        ...

    def count(self) -> int:
        """Approximate number of indexed chunks (0 when there is no index)."""
        ...

    def status(self) -> dict:
        """Health for ``vault_status``: notes_on_disk, notes_indexed, last_run,
        stale_count, stale (a bounded sample), backend."""
        ...

    def reset(self) -> None:
        """Drop all indexed state (does not touch the vault)."""
        ...

    def health(self) -> dict:
        """Diagnostics for `second-brain doctor`."""
        ...
