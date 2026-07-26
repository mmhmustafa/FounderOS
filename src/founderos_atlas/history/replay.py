"""Historical topology replay and comparison.

The replay service reads immutable history artifacts on demand.  It does not
copy historical graphs into a second store and never derives a path when the
selected snapshot lacks the evidence needed to prove it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from founderos_atlas.change import ChangeDetector
from founderos_atlas.topology import TopologySnapshot

from .repository import HistoryRepository


@dataclass(frozen=True)
class ReplayChange:
    category: str
    subject: str
    description: str
    severity: str = "informational"
    before: str | None = None
    after: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "subject": self.subject,
            "description": self.description,
            "severity": self.severity,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True)
class ReplayComparison:
    previous_record_id: str
    current_record_id: str
    previous_snapshot_id: str
    current_snapshot_id: str
    previous_created_at: str | None
    current_created_at: str | None
    changes: tuple[ReplayChange, ...]
    previous_facts: Mapping[str, Any] | None = None
    current_facts: Mapping[str, Any] | None = None
    warnings: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    @property
    def summary(self) -> Mapping[str, int]:
        counts: dict[str, int] = {}
        for change in self.changes:
            counts[change.category] = counts.get(change.category, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_record_id": self.previous_record_id,
            "current_record_id": self.current_record_id,
            "previous_snapshot_id": self.previous_snapshot_id,
            "current_snapshot_id": self.current_snapshot_id,
            "previous_created_at": self.previous_created_at,
            "current_created_at": self.current_created_at,
            "changed": self.changed,
            "summary": dict(self.summary),
            "changes": [item.to_dict() for item in self.changes],
            "previous_facts": (
                dict(self.previous_facts) if self.previous_facts else None
            ),
            "current_facts": (
                dict(self.current_facts) if self.current_facts else None
            ),
            "warnings": list(self.warnings),
        }


class ReplayUnavailableError(ValueError):
    """A requested historical record cannot be compared safely."""


class TopologyReplayService:
    def __init__(self, repository: HistoryRepository) -> None:
        self._repository = repository

    def records(self, *, profile_id: str | None = None):
        records = self._repository.load().records
        if profile_id:
            records = tuple(
                item for item in records if item.profile_id == profile_id
            )
        return records

    def load_snapshot(self, record_id: str) -> TopologySnapshot:
        path = self._repository.snapshot_path(record_id)
        root = self._repository.root.resolve()
        resolved = path.resolve()
        if root != resolved and root not in resolved.parents:
            raise ReplayUnavailableError("history record escaped the history root")
        if not resolved.is_file():
            raise ReplayUnavailableError(
                f"history record {record_id!r} has no topology snapshot"
            )
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            return TopologySnapshot.from_dict(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ReplayUnavailableError(
                f"history record {record_id!r} has an invalid snapshot: {error}"
            ) from error

    def compare(
        self, previous_record_id: str, current_record_id: str
    ) -> ReplayComparison:
        if previous_record_id == current_record_id:
            raise ReplayUnavailableError(
                "choose two different discovery records to compare"
            )
        records = {
            item.record_id: item for item in self._repository.load().records
        }
        before_record = records.get(previous_record_id)
        after_record = records.get(current_record_id)
        if before_record is None or after_record is None:
            raise ReplayUnavailableError("one of the discovery records is missing")
        if (
            before_record.profile_id
            and after_record.profile_id
            and before_record.profile_id != after_record.profile_id
        ):
            raise ReplayUnavailableError(
                "snapshots from different observation profiles are not "
                "directly comparable"
            )

        before = self.load_snapshot(previous_record_id)
        after = self.load_snapshot(current_record_id)
        before_facts = _snapshot_operational_facts(before)
        after_facts = _snapshot_operational_facts(after)
        report = ChangeDetector().compare(before, after)
        changes = [
            ReplayChange(
                category=item.category,
                subject=item.subject,
                description=item.description,
                severity=item.severity,
                before=item.previous_value,
                after=item.current_value,
            )
            for item in report.changes
        ]
        changes.extend(_site_changes(before, after, before_facts, after_facts))
        changes.extend(_protocol_changes(before, after, "ospf"))
        changes.extend(_protocol_changes(before, after, "bgp"))
        changes.sort(
            key=lambda item: (
                item.category,
                item.subject.casefold(),
                item.description.casefold(),
            )
        )
        warnings: list[str] = []
        if before.warnings:
            warnings.append(
                f"The earlier snapshot contains {len(before.warnings)} "
                "discovery warning(s)."
            )
        if after.warnings:
            warnings.append(
                f"The later snapshot contains {len(after.warnings)} "
                "discovery warning(s)."
            )
        for protocol, label in (("ospf", "OSPF"), ("bgp", "BGP")):
            if (
                not before_facts["routing"][protocol]["covered_devices"]
                and not after_facts["routing"][protocol]["covered_devices"]
            ):
                warnings.append(
                    f"No {label} operational or configured membership is "
                    "preserved in either selected snapshot. Atlas cannot "
                    f"compare {label} boundaries."
                )
        if (
            not before_facts["sites"]["membership"]
            and not after_facts["sites"]["membership"]
        ):
            warnings.append(
                "Neither snapshot contains enough hostname, topology or "
                "catalog evidence to reconstruct historical site membership."
            )
        if before_record.discovery_version != after_record.discovery_version:
            warnings.append(
                "The selected records were produced by different discovery "
                f"schema versions ({before_record.discovery_version} and "
                f"{after_record.discovery_version}); only canonical fields "
                "understood by both are compared."
            )
        if before.created_at and after.created_at and before.created_at > after.created_at:
            warnings.append(
                "The selected From snapshot is newer than the To snapshot; "
                "the comparison is intentionally shown in the selected "
                "direction."
            )
        return ReplayComparison(
            previous_record_id=previous_record_id,
            current_record_id=current_record_id,
            previous_snapshot_id=before.snapshot_id,
            current_snapshot_id=after.snapshot_id,
            previous_created_at=before.created_at,
            current_created_at=after.created_at,
            changes=tuple(changes),
            previous_facts=before_facts,
            current_facts=after_facts,
            warnings=tuple(warnings),
        )


def _device_key(device: Mapping[str, Any]) -> str:
    serial = str(device.get("serial_number") or "").strip().casefold()
    if serial and serial not in {"unknown", "none"}:
        return f"serial:{serial}"
    hostname = str(device.get("hostname") or "").strip().casefold()
    if hostname:
        return f"hostname:{hostname}"
    return f"id:{str(device.get('device_id') or '').casefold()}"


def _site_memberships(
    snapshot: TopologySnapshot,
    facts: Mapping[str, Any] | None = None,
) -> dict[str, tuple[str, str]]:
    if facts:
        membership = dict((facts.get("sites") or {}).get("membership") or {})
        names = dict((facts.get("sites") or {}).get("names") or {})
        devices = {
            str(device.get("device_id") or ""): device
            for device in snapshot.devices
        }
        resolved: dict[str, tuple[str, str]] = {}
        for device_id, site_id in membership.items():
            if site_id == "__none__" or device_id not in devices:
                continue
            device = devices[device_id]
            resolved[_device_key(device)] = (
                str(device.get("hostname") or device_id),
                str(names.get(site_id) or site_id),
            )
        if resolved:
            return resolved
    memberships: dict[str, tuple[str, str]] = {}
    for device in snapshot.devices:
        metadata = device.get("metadata") or {}
        site = str(
            metadata.get("site_id")
            or metadata.get("site")
            or device.get("site_id")
            or device.get("site")
            or ""
        ).strip()
        if not site:
            continue
        memberships[_device_key(device)] = (
            str(device.get("hostname") or device.get("device_id") or "device"),
            site,
        )
    return memberships


def _site_changes(
    before: TopologySnapshot,
    after: TopologySnapshot,
    before_facts: Mapping[str, Any] | None = None,
    after_facts: Mapping[str, Any] | None = None,
) -> list[ReplayChange]:
    left = _site_memberships(before, before_facts)
    right = _site_memberships(after, after_facts)
    changes: list[ReplayChange] = []
    for key in sorted(set(left) & set(right)):
        name_before, site_before = left[key]
        name_after, site_after = right[key]
        if site_before.casefold() == site_after.casefold():
            continue
        changes.append(ReplayChange(
            category="site-membership",
            subject=name_after or name_before,
            description=(
                f"{name_after or name_before} moved from site {site_before} "
                f"to {site_after}"
            ),
            severity="medium",
            before=site_before,
            after=site_after,
        ))
    return changes


def _protocol_fact_set(
    snapshot: TopologySnapshot, protocol: str
) -> set[tuple[str, str, str, str]]:
    facts: set[tuple[str, str, str, str]] = set()
    plural = "ospf_adjacencies" if protocol == "ospf" else "bgp_sessions"
    for device in snapshot.devices:
        hostname = str(device.get("hostname") or device.get("device_id") or "")
        metadata = device.get("metadata") or {}
        routing = metadata.get("routing_evidence") or metadata
        entries = routing.get(plural) if isinstance(routing, Mapping) else ()
        for entry in entries or ():
            if not isinstance(entry, Mapping):
                continue
            peer = str(
                entry.get("neighbor_router_id")
                or entry.get("neighbor_id")
                or entry.get("peer")
                or entry.get("peer_address")
                or entry.get("router_id")
                or "unknown"
            )
            region = str(
                entry.get("area_id")
                or entry.get("area")
                or entry.get("remote_as")
                or entry.get("peer_as")
                or entry.get("local_as")
                or "unknown"
            )
            state = str(entry.get("state") or entry.get("status") or "unknown")
            facts.add((hostname, peer, region, state))
    return facts


def _protocol_changes(
    before: TopologySnapshot, after: TopologySnapshot, protocol: str
) -> list[ReplayChange]:
    left = _protocol_fact_set(before, protocol)
    right = _protocol_fact_set(after, protocol)
    left_by_relationship = {
        (host, peer, region): state for host, peer, region, state in left
    }
    right_by_relationship = {
        (host, peer, region): state for host, peer, region, state in right
    }
    changes: list[ReplayChange] = []
    label = protocol.upper()
    shared = set(left_by_relationship) & set(right_by_relationship)
    for relationship in sorted(shared):
        before_state = left_by_relationship[relationship]
        after_state = right_by_relationship[relationship]
        if before_state.casefold() == after_state.casefold():
            continue
        host, peer, region = relationship
        healthy = (
            {"full", "2-way"} if protocol == "ospf" else {"established"}
        )
        changes.append(ReplayChange(
            category=protocol,
            subject=host,
            description=(
                f"{label} relationship to {peer} in {region} changed from "
                f"{before_state} to {after_state}"
            ),
            severity=(
                "low" if after_state.casefold() in healthy else "high"
            ),
            before=before_state,
            after=after_state,
        ))
    removed = set(left_by_relationship) - set(right_by_relationship)
    for relationship in sorted(removed):
        host, peer, region = relationship
        state = left_by_relationship[relationship]
        changes.append(ReplayChange(
            category=protocol,
            subject=host,
            description=(
                f"{label} relationship to {peer} in {region} is no longer "
                f"observed (previous state {state})"
            ),
            severity="high",
            before=state,
        ))
    added = set(right_by_relationship) - set(left_by_relationship)
    for relationship in sorted(added):
        host, peer, region = relationship
        state = right_by_relationship[relationship]
        changes.append(ReplayChange(
            category=protocol,
            subject=host,
            description=(
                f"{label} relationship to {peer} in {region} is now observed "
                f"(state {state})"
            ),
            severity="low",
            after=state,
        ))
    return changes


def _snapshot_operational_facts(
    snapshot: TopologySnapshot,
) -> dict[str, Any]:
    """Bounded, evidence-only facts for one immutable snapshot.

    Empty curation catalogs are injected deliberately.  Applying today's
    operator overrides to an old snapshot would rewrite history and could
    manufacture a site move that never occurred in the collected evidence.
    """

    from founderos_atlas.identity import PeerResolutionCatalog
    from founderos_atlas.sites import SiteCatalog, SiteOverrideCatalog
    from founderos_atlas.topology.vocabulary import count_topology
    from founderos_atlas.visualization import TopologyRenderer

    renderer = TopologyRenderer(
        snapshot,
        site_catalog=SiteCatalog(),
        site_overrides=SiteOverrideCatalog(),
        identity_resolutions=PeerResolutionCatalog(),
        viewer_context={"last_discovered": snapshot.created_at or ""},
    )
    elements = renderer.elements()
    site_view = renderer.site_view(elements)
    routing = renderer.routing_view(elements)
    counts = count_topology(
        elements, site_membership=site_view.get("membership")
    ).to_dict()
    names = {
        str(site.get("site_id") or ""): str(site.get("label") or "")
        for site in site_view.get("sites") or ()
        if site.get("site_id")
    }

    def protocol(value: Mapping[str, Any], *, sessions: str) -> dict[str, Any]:
        fields = (
            "covered_devices", "total_devices", sessions,
            "health",
        )
        result = {field: value.get(field) for field in fields}
        if sessions == "adjacencies":
            result.update({
                "adjacencies_full": value.get("adjacencies_full"),
                "adjacencies_two_way": value.get("adjacencies_two_way"),
            })
        else:
            result["sessions_established"] = value.get(
                "sessions_established"
            )
        result["groups"] = [
            {
                key: group.get(key)
                for key in (
                    "label", "area_id", "process_id", "local_as", "vrf",
                    "address_family", "count", "adjacency_count",
                    "session_count", "states", "health",
                )
                if group.get(key) is not None
            }
            for group in value.get("groups") or ()
        ]
        return result

    return {
        "snapshot_id": snapshot.snapshot_id,
        "created_at": snapshot.created_at,
        "topology": {
            "devices": snapshot.device_count,
            "relationships": counts["relationships"],
            "physical_links": counts["physical_links"],
            "logical_adjacencies": counts["logical_adjacencies"],
            "inter_site_links": counts["inter_site_links"],
            "unresolved_identities": counts["unresolved_peer_identities"],
            "warnings": len(snapshot.warnings),
        },
        "sites": {
            "count": len([
                site for site in site_view.get("sites") or ()
                if site.get("site_id") != "__none__"
            ]),
            "membership": dict(site_view.get("membership") or {}),
            "names": names,
            "groups": [
                {
                    "site_id": site.get("site_id"),
                    "name": site.get("label"),
                    "site_type": site.get("site_type"),
                    "devices": site.get("count"),
                }
                for site in site_view.get("sites") or ()
            ],
        },
        "routing": {
            "ospf": protocol(
                dict(routing.get("ospf") or {}), sessions="adjacencies"
            ),
            "bgp": protocol(
                dict(routing.get("bgp") or {}), sessions="sessions"
            ),
        },
    }
