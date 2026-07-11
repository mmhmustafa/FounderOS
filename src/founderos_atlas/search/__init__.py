"""Atlas Universal Search (PR-038, codename SEARCH).

The front door to Atlas: one search box (Ctrl+K) over everything the
enterprise evidence contains — canonical devices, interfaces (including
SVI-derived VLAN ids), sites, topology links, profiles, credential
NAMES, predictions, path investigations, change summaries, and discovery
history.

Deterministic end to end: entries exist only because evidence produced
them; ranking is exact → canonical identity → prefix → partial, with
historical objects after live ones; identical evidence yields identical
results. No Elasticsearch, no fuzzy AI ranking, no invented objects,
and never a secret in the index.
"""

from .builder import (
    entries_from_graph,
    entries_from_workspace,
    health_by_profile_from_scopes,
)
from .index import DEFAULT_GROUP_LIMIT, SearchIndex
from .models import (
    GROUP_LABELS,
    GROUPS,
    SearchEntry,
    SearchGroup,
    SearchHit,
    SearchKey,
    SearchResponse,
)
from .service import (
    SearchService,
    build_search_index,
    search_devices,
    search_enterprise,
    search_interfaces,
    search_predictions,
    workspace_fingerprint,
)

__all__ = [
    "DEFAULT_GROUP_LIMIT",
    "GROUP_LABELS",
    "GROUPS",
    "SearchEntry",
    "SearchGroup",
    "SearchHit",
    "SearchIndex",
    "SearchKey",
    "SearchResponse",
    "SearchService",
    "build_search_index",
    "entries_from_graph",
    "entries_from_workspace",
    "health_by_profile_from_scopes",
    "search_devices",
    "search_enterprise",
    "search_interfaces",
    "search_predictions",
    "workspace_fingerprint",
]
