"""Query parameters shared by every paginated endpoint."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
_MAX_PAGE = 1_000_000


@dataclass(frozen=True)
class PageParams:
    """Which slice of a list the client asked for (``page`` starts at 1)."""

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        """Rows to skip."""
        return (self.page - 1) * self.page_size


def _page_params(
    page: Annotated[int, Query(ge=1, le=_MAX_PAGE)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    return PageParams(page, page_size)


PageDep = Annotated[PageParams, Depends(_page_params)]
