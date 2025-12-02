from __future__ import annotations

from typing import Protocol

from ..types import LoadResult


class PageLoader(Protocol):
    def load(self, url: str) -> LoadResult: ...

    def close(self) -> None: ...
