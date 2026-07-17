"""Shared list mechanics for investigation surfaces: pagination.

One implementation for every filtered/paged view (policy results,
changes, timeline, audit), so page arithmetic and URL semantics never
drift between surfaces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200


@dataclass(frozen=True)
class Page:
    items: list
    total: int
    page: int
    pages: int
    per_page: int

    @property
    def start(self) -> int:
        return 0 if self.total == 0 else (self.page - 1) * self.per_page + 1

    @property
    def end(self) -> int:
        return min(self.page * self.per_page, self.total)


def paginate(items: Sequence, page: int, per_page: int) -> Page:
    per_page = max(1, min(int(per_page or DEFAULT_PER_PAGE), MAX_PER_PAGE))
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(int(page or 1), pages))
    start = (page - 1) * per_page
    return Page(
        items=list(items[start:start + per_page]),
        total=total, page=page, pages=pages, per_page=per_page,
    )


def int_arg(args: Mapping[str, str], name: str, default: int, maximum: int) -> int:
    try:
        value = int(str(args.get(name, "") or default))
    except ValueError:
        value = default
    return max(1, min(value, maximum))
