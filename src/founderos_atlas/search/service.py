"""Reusable enterprise search service with automatic index rebuilds.

No Elasticsearch, no daemon: the index is a lightweight in-memory
structure built from the Enterprise Graph and the workspace's artifacts.
A deterministic fingerprint over the evidence files detects change —
after a discovery, federation, prediction, path investigation, or
change-report update the fingerprint differs and the next search
rebuilds automatically. Identical evidence yields an identical index and
identical results.

The GUI, CLI, future REST clients, and the future Atlas Assistant all
share this service.
"""

from __future__ import annotations

from pathlib import Path

from founderos_atlas.federation import get_enterprise_graph
from founderos_atlas.sites import SiteCatalog
from founderos_atlas.workspace import profile_scope

from .builder import (
    entries_from_graph,
    entries_from_workspace,
    health_by_profile_from_scopes,
)
from .index import DEFAULT_GROUP_LIMIT, SearchIndex
from .models import SearchResponse


# Per-scope artifacts whose content feeds the index.
_SCOPE_ARTIFACTS = (
    "topology_snapshot.json",
    "prediction_report.json",
    "path_investigations.json",
    "state_change_report.json",
    "intelligence_report.json",
)


def build_search_index(
    base_output_dir: str | Path,
    profiles,
    *,
    catalog: SiteCatalog | None = None,
    credential_sets=(),
    credential_memory=None,
) -> SearchIndex:
    """One deterministic index over the whole workspace's evidence."""

    graph = get_enterprise_graph(
        base_output_dir,
        profiles,
        catalog=catalog,
        credential_memory=credential_memory,
    )
    entries = entries_from_graph(
        graph,
        health_by_profile=health_by_profile_from_scopes(base_output_dir, profiles),
    ) + entries_from_workspace(
        base_output_dir, profiles, credential_sets=credential_sets
    )
    return SearchIndex(entries)


def search_enterprise(
    index: SearchIndex, query: str, *, limit_per_group: int = DEFAULT_GROUP_LIMIT
) -> SearchResponse:
    """Universal grouped search over everything Atlas knows."""

    return index.search(query, limit_per_group=limit_per_group)


def search_devices(index: SearchIndex, query: str) -> SearchResponse:
    return _only(index.search(query), ("devices",))


def search_interfaces(index: SearchIndex, query: str) -> SearchResponse:
    return _only(index.search(query), ("interfaces",))


def search_predictions(index: SearchIndex, query: str) -> SearchResponse:
    return _only(index.search(query), ("predictions",))


def workspace_fingerprint(
    base_output_dir: str | Path, profiles, *, workspace_root: str | Path | None = None
) -> tuple:
    """Deterministic identity of the evidence the index is built from.

    Covers every profile scope's report artifacts and discovery-run list,
    the enterprise scope's snapshot, and the workspace's saved state
    (profiles, credentials metadata, site catalog). When any of it
    changes — discovery, federation, prediction, investigation, change
    report, history — the fingerprint changes and the index rebuilds.
    """

    parts: list[tuple] = []
    base = Path(base_output_dir)
    for profile in profiles:
        scope = profile_scope(base, profile.profile_id, profile.name)
        parts.append(("profile", profile.profile_id, profile.name))
        for name in _SCOPE_ARTIFACTS:
            parts.append(_file_stamp(scope.output_dir / name))
        root = scope.history_root
        runs = (
            tuple(sorted(entry.name for entry in root.iterdir() if entry.is_dir()))
            if root.is_dir()
            else ()
        )
        parts.append(("history", str(root), runs))
    enterprise = base / ".atlas" / "enterprise"
    for name in _SCOPE_ARTIFACTS + ("enterprise_graph.json",):
        parts.append(_file_stamp(enterprise / name))
    if workspace_root is not None:
        workspace = Path(workspace_root)
        if workspace.is_dir():
            for path in sorted(workspace.glob("*.json")):
                parts.append(_file_stamp(path))
    return tuple(parts)


class SearchService:
    """Caches the index and rebuilds it automatically when evidence changes."""

    def __init__(self) -> None:
        self._fingerprint: tuple | None = None
        self._index: SearchIndex | None = None

    def index_for(
        self,
        base_output_dir: str | Path,
        profiles,
        *,
        workspace_root: str | Path | None = None,
        catalog: SiteCatalog | None = None,
        credential_sets=(),
        credential_memory=None,
    ) -> SearchIndex:
        profiles = tuple(profiles)
        fingerprint = workspace_fingerprint(
            base_output_dir, profiles, workspace_root=workspace_root
        )
        if self._index is None or fingerprint != self._fingerprint:
            self._index = build_search_index(
                base_output_dir,
                profiles,
                catalog=catalog,
                credential_sets=credential_sets,
                credential_memory=credential_memory,
            )
            self._fingerprint = fingerprint
        return self._index


# -- internals -----------------------------------------------------------------


def _only(response: SearchResponse, group_ids: tuple[str, ...]) -> SearchResponse:
    groups = tuple(
        group for group in response.groups if group.group_id in group_ids
    )
    return SearchResponse(
        query=response.query,
        total=sum(group.count for group in groups),
        groups=groups,
    )


def _file_stamp(path: Path) -> tuple:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None)
    return (str(path), stat.st_mtime_ns, stat.st_size)
