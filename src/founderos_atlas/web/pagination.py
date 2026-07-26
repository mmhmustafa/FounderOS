"""Small, deterministic server-side pagination primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class Page(Generic[T]):
    items: Sequence[T]
    total: int
    number: int
    page_count: int
    page_size: int


def paginate(
    items: Sequence[T],
    *,
    requested_page: int = 1,
    page_size: int = 50,
) -> Page[T]:
    """Return one bounded page without copying the complete collection."""

    if page_size < 1:
        raise ValueError("page_size must be positive")
    total = len(items)
    page_count = max(1, (total + page_size - 1) // page_size)
    number = min(max(1, requested_page), page_count)
    start = (number - 1) * page_size
    return Page(
        items=items[start:start + page_size],
        total=total,
        number=number,
        page_count=page_count,
        page_size=page_size,
    )
