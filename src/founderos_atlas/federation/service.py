"""Enterprise federation services: reusable APIs over the Enterprise Graph.

These are the entry points the GUI, CLI, future REST APIs, and the
assistant share:

- ``get_enterprise_graph``    — build the graph from every profile scope
- ``get_enterprise_inventory``— canonical devices with provenance rows
- ``resolve_canonical_device``— one device from any identifier, or an
                                honest ambiguity/none answer
- ``search_enterprise``       — deterministic substring search
- ``merge_observations``      — the merge engine as a standalone API
- ``build_enterprise_snapshot`` (re-exported) — the federated snapshot
  every existing engine consumes unchanged
- ``write_enterprise_artifacts`` — persist the enterprise snapshot,
  graph, and interactive topology for the GUI

Federation happens AFTER discovery: discovery stays per profile, profile
scopes stay isolated, and this layer only reads their artifacts.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path

from founderos_atlas.config import safe_artifact_name
from founderos_atlas.enterprise import (
    ScopeContribution,
    gather_scope_contributions,
)
from founderos_atlas.history import HistoryRepository
from founderos_atlas.identity.canonical import normalize_hostname
from founderos_atlas.sites import SiteCatalog
from founderos_atlas.topology import TopologySnapshot
from founderos_atlas.visualization import TopologyRenderer
from founderos_atlas.workspace import profile_scope

from .builder import build_enterprise_graph
from .models import ContributionSummary, EnterpriseGraph
from .snapshot import build_enterprise_snapshot


STALE_AFTER_HOURS = 24
ENTERPRISE_SCOPE_SUBDIR = Path(".atlas") / "enterprise"


def enterprise_scope_dir(base_output_dir: str | Path) -> Path:
    """Where enterprise-scope artifacts live (reports, snapshot, history)."""

    return Path(base_output_dir) / ENTERPRISE_SCOPE_SUBDIR


def get_enterprise_graph(
    base_output_dir: str | Path,
    profiles,
    *,
    catalog: SiteCatalog | None = None,
    credential_memory=None,
    now: str | None = None,
) -> EnterpriseGraph:
    """The federated graph from every profile's latest scoped evidence.

    ``now`` (ISO timestamp) marks each contribution fresh or stale; when
    omitted, freshness stays None (unknown) rather than being guessed.
    """

    graph = build_enterprise_graph(
        gather_scope_contributions(base_output_dir, profiles),
        catalog=catalog,
        credential_memory=credential_memory,
    )
    if now is not None:
        graph = replace(
            graph,
            contributions=tuple(
                replace(
                    contribution,
                    fresh=_is_fresh(contribution.observed_at, now),
                )
                for contribution in graph.contributions
            ),
        )
    return graph


def get_enterprise_inventory(graph: EnterpriseGraph) -> list[dict]:
    """Canonical devices with provenance and merge explanation — no secrets."""

    rows: list[dict] = []
    for device in graph.devices:
        decision = graph.decision_for(device.enterprise_id)
        rows.append(
            {
                "enterprise_id": device.enterprise_id,
                "hostname": device.hostname,
                "aliases": list(device.aliases),
                "management_ips": list(device.management_ips),
                "platform": device.platform or "—",
                "serial_number": device.serial_number or "—",
                "site": device.site.label,
                "observed_by": list(device.profile_names),
                "observation_count": len(device.observations),
                "last_seen": max(
                    (
                        observation.observed_at
                        for observation in device.observations
                        if observation.observed_at
                    ),
                    default=None,
                ),
                "merged": decision.merged if decision else False,
                "merge_reason": decision.reason if decision else "",
                "merge_evidence": list(decision.evidence) if decision else [],
                "merge_confidence_percent": (
                    decision.confidence_percent if decision else None
                ),
                "merge_confidence_band": (
                    decision.confidence_band if decision else None
                ),
                "observations": [
                    observation.to_dict() for observation in device.observations
                ],
                "credential_ref": device.credential_ref,
            }
        )
    return rows


def resolve_canonical_device(graph: EnterpriseGraph, query: str):
    """Resolve any identifier to exactly one canonical device.

    Returns ``(device, None)`` on a unique match, ``(None, reason)``
    otherwise — ambiguity names every candidate instead of guessing.
    Matches enterprise id, hostname, alias, management address, or
    serial number (all case-insensitive, exact).
    """

    wanted = str(query or "").strip()
    if not wanted:
        return None, "an empty query matches nothing"
    folded = wanted.casefold()
    matches = []
    for device in graph.devices:
        keys = {
            device.enterprise_id.casefold(),
            normalize_hostname(device.hostname),
            *(normalize_hostname(alias) for alias in device.aliases),
            *(ip.casefold() for ip in device.management_ips),
        }
        if device.serial_number:
            keys.add(device.serial_number.casefold())
        if folded in keys or normalize_hostname(wanted) in keys:
            matches.append(device)
    if not matches:
        return None, f"no enterprise device matches '{wanted}'"
    if len(matches) > 1:
        names = ", ".join(device.hostname for device in matches)
        return None, (
            f"'{wanted}' is ambiguous across {len(matches)} enterprise "
            f"devices ({names}); use a serial number, management address, "
            "or enterprise id"
        )
    return matches[0], None


def search_enterprise(graph: EnterpriseGraph, query: str) -> tuple:
    """Deterministic substring search over the canonical inventory."""

    needle = str(query or "").strip().casefold()
    if not needle:
        return ()
    found = []
    for device in graph.devices:
        haystack = " ".join(
            (
                device.hostname,
                *device.aliases,
                *device.management_ips,
                device.serial_number or "",
                device.site.label,
                device.enterprise_id,
            )
        ).casefold()
        if needle in haystack:
            found.append(device)
    return tuple(found)


def merge_observations(
    contributions: tuple[ScopeContribution, ...] | list[ScopeContribution],
    *,
    catalog: SiteCatalog | None = None,
):
    """The merge engine as a standalone API: observations in, canonical
    devices and explainable merge decisions out."""

    graph = build_enterprise_graph(tuple(contributions), catalog=catalog)
    return graph.devices, graph.merge_decisions


def enterprise_failed_hosts(base_output_dir: str | Path, profiles) -> tuple[str, ...]:
    """Hosts the most recent run of ANY profile could not reach."""

    failed: list[str] = []
    for profile in profiles:
        scope = profile_scope(base_output_dir, profile.profile_id, profile.name)
        record = HistoryRepository(scope.history_root).latest()
        if record is None:
            continue
        for host in record.failures:
            value = str(host)
            if value not in failed:
                failed.append(value)
    return tuple(failed)


def enterprise_captured_configs(
    base_output_dir: str | Path, profiles, graph: EnterpriseGraph
) -> tuple[str, ...]:
    """Canonical devices whose running configuration ANY profile captured."""

    captured: list[str] = []
    for device in graph.devices:
        names = {device.hostname, *device.aliases}
        for profile in profiles:
            scope = profile_scope(
                base_output_dir, profile.profile_id, profile.name
            )
            if any(
                (
                    scope.output_dir
                    / "configs"
                    / safe_artifact_name(name)
                    / "running_config.txt"
                ).is_file()
                for name in names
            ):
                captured.append(device.hostname)
                break
    return tuple(sorted(captured))


def enterprise_seed_addresses(profiles) -> tuple[str, ...]:
    """Every profile's proven entry addresses, order-preserving."""

    seeds: list[str] = []
    for profile in profiles:
        for seed in getattr(profile, "all_seeds", ()) or ():
            value = str(seed)
            if value not in seeds:
                seeds.append(value)
    return tuple(seeds)


def enterprise_evidence_fingerprint(
    base_output_dir: str | Path, profiles, *, workspace_root: str | Path | None = None
) -> tuple:
    """Deterministic identity of the evidence the enterprise graph is
    built FROM: every profile scope's snapshot and run history plus the
    workspace's saved state. Deliberately EXCLUDES the derived
    ``.atlas/enterprise/`` artifacts — a cache keyed on its own output
    would invalidate itself on every write."""

    parts: list[tuple] = []
    for profile in profiles:
        scope = profile_scope(base_output_dir, profile.profile_id, profile.name)
        parts.append(
            (
                "profile",
                profile.profile_id,
                profile.name,
                getattr(profile, "site_hint", None),
                getattr(profile, "domain_hint", None),
            )
        )
        parts.append(_file_stamp(scope.snapshot_path))
        root = scope.history_root
        runs = (
            tuple(sorted(entry.name for entry in root.iterdir() if entry.is_dir()))
            if root.is_dir()
            else ()
        )
        parts.append(("history", str(root), runs))
    if workspace_root is not None:
        workspace = Path(workspace_root)
        if workspace.is_dir():
            for path in sorted(workspace.glob("*.json")):
                parts.append(_file_stamp(path))
    return tuple(parts)


def _file_stamp(path: Path) -> tuple:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def contribution_is_fresh(observed_at: str | None, now: str) -> bool:
    """Whether evidence observed at ``observed_at`` is still fresh at
    ``now`` (public: freshness is a function of the current clock and
    callers with cached graphs must be able to re-evaluate it)."""

    return _is_fresh(observed_at, now)


def overall_freshness(contributions: tuple[ContributionSummary, ...]) -> bool:
    """The enterprise evidence is fresh only when every contribution is."""

    return bool(contributions) and all(
        contribution.fresh for contribution in contributions
    )


def write_enterprise_artifacts(
    base_output_dir: str | Path, graph: EnterpriseGraph
) -> TopologySnapshot:
    """Persist the enterprise snapshot, graph, and interactive topology.

    Artifacts live under ``.atlas/enterprise/`` (gitignored with the rest
    of the Atlas state) and are regenerated deterministically from the
    profile scopes' evidence — they are a view, never a source of truth.
    """

    snapshot = build_enterprise_snapshot(graph)
    out = enterprise_scope_dir(base_output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "topology_snapshot.json").write_text(
        json.dumps(
            snapshot.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "enterprise_graph.json").write_text(
        json.dumps(
            graph.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "atlas_topology.html").write_text(
        TopologyRenderer(
            snapshot,
            viewer_context={
                "last_discovered": snapshot.created_at or "unrecorded",
            },
        ).render(),
        encoding="utf-8",
    )
    return snapshot


# -- internals -----------------------------------------------------------------


def _is_fresh(observed_at: str | None, now: str) -> bool:
    if not observed_at:
        return False
    try:
        observed = datetime.fromisoformat(observed_at)
        reference = datetime.fromisoformat(now)
    except ValueError:
        return False
    return (reference - observed).total_seconds() <= STALE_AFTER_HOURS * 3600
