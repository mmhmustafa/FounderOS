"""Universal search models: entries, hits, grouped responses.

Every searchable object is a ``SearchEntry`` derived from deterministic
evidence (the Enterprise Graph, profile scopes' reports, discovery
history). Search never invents objects: an entry exists only because
evidence produced it, and every hit names the field that matched.
No entry ever contains a secret — credentials are indexed by name only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SEARCH_SCHEMA_VERSION = "1.0.0"

# Deterministic ranking (spec order): exact → canonical identity →
# prefix → partial; historical objects follow live objects.
RANK_EXACT = 0
RANK_CANONICAL = 1
RANK_PREFIX = 2
RANK_PARTIAL = 3
HISTORICAL_PENALTY = 10

RANK_LABELS = {
    RANK_EXACT: "exact",
    RANK_CANONICAL: "canonical",
    RANK_PREFIX: "prefix",
    RANK_PARTIAL: "partial",
}

# Result groups in display order (spec).
GROUPS = (
    ("devices", "Devices"),
    ("interfaces", "Interfaces"),
    ("sites", "Sites"),
    ("topology", "Topology"),
    ("predictions", "Predictions"),
    ("investigations", "Investigations"),
    ("changes", "Changes"),
    ("plans", "Plans"),
    ("profiles", "Profiles"),
    ("credentials", "Credentials"),
    ("history", "History"),
)
GROUP_ORDER = {group_id: index for index, (group_id, _) in enumerate(GROUPS)}
GROUP_LABELS = dict(GROUPS)


@dataclass(frozen=True)
class SearchKey:
    """One searchable string of an entry.

    ``canonical`` marks canonical-identity values (enterprise id, serial
    number, canonical alias) — an exact match on them ranks just below an
    exact match on the entry's primary name.
    """

    field: str
    value: str
    canonical: bool = False


@dataclass(frozen=True)
class SearchEntry:
    """One searchable object with evidence-derived display fields."""

    group: str
    title: str
    subtitle: str
    href: str
    keys: tuple[SearchKey, ...]
    detail: dict[str, Any] = field(default_factory=dict)
    historical: bool = False

    def __post_init__(self) -> None:
        if self.group not in GROUP_ORDER:
            raise ValueError(f"unknown search group: {self.group}")


@dataclass(frozen=True)
class SearchHit:
    """One entry matched by a query, with WHY it matched."""

    entry: SearchEntry
    rank: int
    match_field: str
    match_value: str

    @property
    def rank_label(self) -> str:
        base = self.rank % HISTORICAL_PENALTY
        label = RANK_LABELS.get(base, "partial")
        if self.rank >= HISTORICAL_PENALTY:
            return f"{label} (historical)"
        return label

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.entry.group,
            "title": self.entry.title,
            "subtitle": self.entry.subtitle,
            "href": self.entry.href,
            "detail": dict(self.entry.detail),
            "match": {
                "field": self.match_field,
                "value": self.match_value,
                "rank": self.rank_label,
            },
        }


@dataclass(frozen=True)
class SearchGroup:
    group_id: str
    label: str
    count: int                      # total matches BEFORE the display limit
    results: tuple[SearchHit, ...]  # limited, rank-ordered

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.group_id,
            "label": self.label,
            "count": self.count,
            "results": [hit.to_dict() for hit in self.results],
        }


@dataclass(frozen=True)
class SearchResponse:
    query: str
    total: int
    groups: tuple[SearchGroup, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SEARCH_SCHEMA_VERSION,
            "query": self.query,
            "total": self.total,
            "groups": [group.to_dict() for group in self.groups],
        }
