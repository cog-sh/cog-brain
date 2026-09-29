"""Backend contract shared by every memory engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


@dataclass
class Hit:
    """One search result. ``payload`` mirrors the historical Qdrant payload keys
    (``file_path``, ``note_title``, ``heading_path``, ``text``, ``tags``, …) so
    citation/formatting code is backend-independent."""
    payload: Mapping
    score: float


class Backend(Protocol):
    name: str

    def search(self, query: str, k: int, *, tag: str | None = None,
               folder: str | None = None, exclude: str | None = None) -> list[Hit]:
        """Ranked hits for ``query``. Must never raise on an empty/missing index."""
        ...

    def count(self) -> int:
        """Approximate number of indexed chunks (0 when there is no index)."""
        ...

    def health(self) -> dict:
        """Diagnostics for `second-brain doctor`."""
        ...
