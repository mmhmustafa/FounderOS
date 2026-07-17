"""The in-memory search index: deterministic matching and ranking.

No external search engine, no fuzzy AI ranking. The index is a flat
tuple of evidence-derived entries; a query is matched case-insensitively
against every entry's keys and ranked deterministically:

    exact on the primary name        (rank 0)
  → exact on a canonical identifier  (rank 1: enterprise id, serial, alias)
  → prefix                           (rank 2)
  → partial (substring)              (rank 3)
  → any of the above on a historical object (+10: live objects first)

Ties break on (group order, title, subtitle) so identical evidence always
produces identical results.
"""

from __future__ import annotations

from .models import (
    GROUP_LABELS,
    GROUP_ORDER,
    GROUPS,
    HISTORICAL_PENALTY,
    SECONDARY_PENALTY,
    RANK_CANONICAL,
    RANK_EXACT,
    RANK_PARTIAL,
    RANK_PREFIX,
    SearchEntry,
    SearchGroup,
    SearchHit,
    SearchResponse,
)


DEFAULT_GROUP_LIMIT = 8


class SearchIndex:
    """Immutable, deterministic index over evidence-derived entries."""

    def __init__(self, entries: tuple[SearchEntry, ...] | list[SearchEntry]) -> None:
        self._entries = tuple(entries)

    @property
    def entries(self) -> tuple[SearchEntry, ...]:
        return self._entries

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def search(
        self, query: str, *, limit_per_group: int = DEFAULT_GROUP_LIMIT
    ) -> SearchResponse:
        needle = str(query or "").strip().casefold()
        if not needle:
            return SearchResponse(query=str(query or "").strip(), total=0, groups=())
        hits: list[SearchHit] = []
        for entry in self._entries:
            hit = _best_match(entry, needle)
            if hit is not None:
                hits.append(hit)
        hits.sort(
            key=lambda hit: (
                hit.rank,
                GROUP_ORDER[hit.entry.group],
                hit.entry.title.casefold(),
                hit.entry.subtitle.casefold(),
            )
        )
        grouped: dict[str, list[SearchHit]] = {}
        for hit in hits:
            grouped.setdefault(hit.entry.group, []).append(hit)
        groups = tuple(
            SearchGroup(
                group_id=group_id,
                label=GROUP_LABELS[group_id],
                count=len(grouped[group_id]),
                results=tuple(grouped[group_id][:limit_per_group]),
            )
            for group_id, _ in GROUPS
            if group_id in grouped
        )
        return SearchResponse(
            query=str(query or "").strip(), total=len(hits), groups=groups
        )


def _best_match(entry: SearchEntry, needle: str) -> SearchHit | None:
    best: tuple[int, str, str] | None = None
    for key in entry.keys:
        value = key.value.casefold()
        if not value:
            continue
        if value == needle:
            rank = RANK_CANONICAL if key.canonical else RANK_EXACT
        elif value.startswith(needle):
            rank = RANK_PREFIX
        elif needle in value:
            rank = RANK_PARTIAL
        else:
            continue
        if key.secondary:
            rank += SECONDARY_PENALTY
        if best is None or rank < best[0]:
            best = (rank, key.field, key.value)
            if rank == RANK_EXACT:
                break
    if best is None:
        return None
    rank, match_field, match_value = best
    if entry.historical:
        rank += HISTORICAL_PENALTY
    return SearchHit(
        entry=entry, rank=rank, match_field=match_field, match_value=match_value
    )
