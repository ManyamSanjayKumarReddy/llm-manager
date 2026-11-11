"""The envelope every list endpoint answers with."""

import math

from llm_manager.schemas.base import ResponseSchema


class Page[T](ResponseSchema):
    """One page of ``items`` plus what a client needs to build page controls."""

    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def of(cls, items: list[T], total: int, page: int, page_size: int) -> "Page[T]":
        """Wrap ``items`` (already cut to this page) with the paging numbers."""
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=max(1, math.ceil(total / page_size)),
        )
