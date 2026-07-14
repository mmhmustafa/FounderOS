"""The Enterprise Knowledge Graph consumer contract (PR-043.8, CONSISTENCY).

One read interface over the graph every Atlas module consumes. Discovery
reports facts; Evidence Correlation builds knowledge; this view exposes
that knowledge so Mission, Advisor, Investigation, and Prediction all
read the SAME numbers and never re-interpret raw discovery data.

Consumers must read ONLY through this contract — never parser output,
discovery workers, protocol drivers, or raw observations. It is a pure,
deterministic read facade over the ``TopologySnapshot`` dict (the
Enterprise Knowledge Graph): no clock, no I/O, no new architecture.

Two axes are kept strictly separate (Part 7 terminology):

- **Discovery statistics** — addresses scanned, reachable, authenticated,
  managed devices, unused addresses. Unused addresses are *Information*;
  they are never operational warnings and never reduce health.
- **Operational health** — Healthy / Warning / Critical, derived from the
  managed devices and their evidence quality. Missing evidence lowers
  *confidence*, not health.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


# Health levels (Part 7). Information is a statistic, never a health state.
HEALTH_HEALTHY = "Healthy"
HEALTH_WARNING = "Warning"
HEALTH_CRITICAL = "Critical"
HEALTH_UNKNOWN = "Unknown"

# Confidence bands mirror the rest of Atlas (cap 95 elsewhere; here a
# qualitative band the consumers display).
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class DiscoveryStatistics:
    """The address-space facts of a discovery — statistics, not health.

    ``addresses_scanned`` is every address Atlas evaluated; ``reachable``
    answered a management port; ``authenticated`` additionally let Atlas
    in; ``managed_devices`` is the canonical device count after identity
    normalization. ``unused_addresses`` are scanned addresses that never
    answered — empty subnet slots, pure Information.
    """

    addresses_scanned: int
    reachable: int
    authenticated: int
    managed_devices: int
    unused_addresses: int
    authentication_failures: int
    unsupported_platforms: int

    @property
    def discovery_completeness_percent(self) -> int:
        """Managed devices discovered / reachable managed devices.

        Reachable addresses that Atlas could not authenticate or whose
        platform is unsupported are the only shortfall; unused addresses
        never count against completeness. 100% when nothing was reachable
        (there was nothing to discover)."""

        if self.reachable == 0:
            return 100
        return round(100 * self.authenticated / self.reachable)

    @property
    def address_utilization_percent(self) -> int:
        """Reachable addresses / addresses scanned — how much of the
        scanned space actually hosts a device."""

        if self.addresses_scanned == 0:
            return 0
        return round(100 * self.reachable / self.addresses_scanned)

    @property
    def reachability_percent(self) -> int:
        if self.addresses_scanned == 0:
            return 0
        return round(100 * self.reachable / self.addresses_scanned)

    @property
    def authentication_success_percent(self) -> int:
        if self.reachable == 0:
            return 100
        return round(100 * self.authenticated / self.reachable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "addresses_scanned": self.addresses_scanned,
            "reachable": self.reachable,
            "authenticated": self.authenticated,
            "managed_devices": self.managed_devices,
            "unused_addresses": self.unused_addresses,
            "authentication_failures": self.authentication_failures,
            "unsupported_platforms": self.unsupported_platforms,
            "discovery_completeness_percent": self.discovery_completeness_percent,
            "address_utilization_percent": self.address_utilization_percent,
            "reachability_percent": self.reachability_percent,
            "authentication_success_percent": self.authentication_success_percent,
        }


class EnterpriseKnowledge:
    """A read view over one Enterprise Knowledge Graph snapshot.

    Constructed from the snapshot dict every consumer already has. All
    accessors are deterministic and derive only from the graph — the
    single source of truth.
    """

    def __init__(self, snapshot: Mapping[str, Any] | None) -> None:
        self._snapshot: dict[str, Any] = dict(snapshot) if snapshot else {}
        self._metadata: dict[str, Any] = dict(self._snapshot.get("metadata") or {})

    # -- existence --------------------------------------------------------------

    @property
    def has_evidence(self) -> bool:
        return bool(self._snapshot) and self.device_count > 0

    @property
    def snapshot_id(self) -> str | None:
        value = self._snapshot.get("snapshot_id")
        return str(value) if value else None

    @property
    def created_at(self) -> str | None:
        value = self._snapshot.get("created_at")
        return str(value) if value else None

    # -- devices & relationships ------------------------------------------------

    @property
    def device_count(self) -> int:
        value = self._snapshot.get("device_count")
        if value is not None:
            return int(value)
        return len(self._snapshot.get("devices") or ())

    @property
    def devices(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            dict(device)
            for device in self._snapshot.get("devices") or ()
            if isinstance(device, Mapping)
        )

    @property
    def relationship_count(self) -> int:
        """Logical (undirected) relationship count.

        Uses the fused correlated relationships when present (the
        Enterprise Knowledge produced by Evidence Correlation), else the
        deduplicated raw edges — so every consumer counts the same way."""

        fused = self._metadata.get("correlated_relationships")
        if fused:
            pairs = {
                tuple(sorted((
                    str(item.get("left_device_id")),
                    str(item.get("right_device_id")),
                )))
                for item in fused
                if isinstance(item, Mapping)
            }
            return len(pairs)
        return self._logical_edge_count()

    @property
    def relationships_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self._metadata.get("correlated_relationships") or ():
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("relationship_type") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def routing_observations(self) -> int:
        """Routing/peering relationships (OSPF, BGP, static, routed)."""

        routed = {"verified-routed", "ospf", "bgp", "static", "layer-3"}
        return sum(
            count
            for kind, count in self.relationships_by_type.items()
            if kind in routed
        )

    @property
    def unresolved_count(self) -> int:
        return len(self._metadata.get("unresolved_observations") or ())

    @property
    def ownership_conflicts(self) -> int:
        return len(self._metadata.get("ownership_conflicts") or ())

    @property
    def warning_count(self) -> int:
        """Reconciliation warnings recorded on the graph (data quality)."""

        value = self._metadata.get("warning_count")
        if value is not None:
            return int(value)
        return len(self._snapshot.get("warnings") or ())

    # -- discovery statistics ---------------------------------------------------

    @property
    def statistics(self) -> DiscoveryStatistics:
        """The discovery statistics for the graph.

        Read from the ``discovery_statistics`` metadata the production
        discovery records. For older snapshots without it, derive a safe
        equivalent: every ``failed_hosts`` entry is treated as an unused/
        unreachable address (Information) — never a discovery failure — so
        the pre-CONSISTENCY inflation never resurfaces."""

        stats = self._metadata.get("discovery_statistics")
        if isinstance(stats, Mapping):
            return DiscoveryStatistics(
                addresses_scanned=int(stats.get("addresses_scanned") or 0),
                reachable=int(stats.get("reachable") or 0),
                authenticated=int(stats.get("authenticated") or 0),
                managed_devices=int(
                    stats.get("managed_devices") or self.device_count
                ),
                unused_addresses=int(stats.get("unused_addresses") or 0),
                authentication_failures=int(
                    stats.get("authentication_failures") or 0
                ),
                unsupported_platforms=int(
                    stats.get("unsupported_platforms") or 0
                ),
            )
        managed = self.device_count
        unused = len(self._metadata.get("failed_hosts") or ())
        return DiscoveryStatistics(
            addresses_scanned=managed + unused,
            reachable=managed,
            authenticated=managed,
            managed_devices=managed,
            unused_addresses=unused,
            authentication_failures=0,
            unsupported_platforms=0,
        )

    # -- operational health & confidence ---------------------------------------

    def health(
        self, operational: Mapping[str, Any] | None = None
    ) -> tuple[str, str]:
        """(level, reason) for enterprise operational health.

        Health reflects the state of MANAGED devices, never the address
        space: unused addresses are Information and never appear here. An
        optional operational report (state-change) layers active issues
        on top. Data-quality problems in the graph (reconciliation
        warnings, ownership conflicts) are Warnings; genuine operational
        problems (interfaces down) are Critical."""

        if not self.has_evidence:
            return HEALTH_UNKNOWN, "No discovery evidence in the graph yet."
        operational = dict(operational or {})
        interfaces_down = int(operational.get("interfaces_down") or 0)
        active_issues = int(operational.get("active_issue_count") or 0)
        op_health = str(operational.get("current_health") or "").strip()
        if op_health == HEALTH_CRITICAL or interfaces_down:
            reason = (
                f"{interfaces_down} interface(s) down"
                if interfaces_down
                else "an operational report flags a critical condition"
            )
            return HEALTH_CRITICAL, reason + "."
        concerns: list[str] = []
        if active_issues:
            concerns.append(f"{active_issues} active operational issue(s)")
        if self.ownership_conflicts:
            concerns.append(
                f"{self.ownership_conflicts} address-ownership conflict(s)"
            )
        if self.warning_count:
            concerns.append(f"{self.warning_count} reconciliation warning(s)")
        if concerns:
            return HEALTH_WARNING, "; ".join(concerns) + "."
        return HEALTH_HEALTHY, (
            f"{self.device_count} managed device(s), "
            f"{self.relationship_count} relationship(s); no active issues."
        )

    def confidence(self, *, fresh: bool = True) -> tuple[str, str]:
        """(band, basis) for how confident the graph's knowledge is.

        Driven by discovery completeness (missing evidence lowers
        confidence, per Part 7) and freshness — NOT by health."""

        stats = self.statistics
        if not self.has_evidence:
            return CONFIDENCE_UNKNOWN, "no discovery evidence exists yet"
        completeness = stats.discovery_completeness_percent
        if not fresh:
            return CONFIDENCE_MEDIUM, (
                "the graph's evidence is older than the freshness window"
            )
        if stats.authentication_failures or completeness < 100:
            return CONFIDENCE_MEDIUM, (
                f"{stats.authentication_failures} reachable device(s) could "
                f"not be authenticated — discovery is {completeness}% complete"
            )
        if self.unresolved_count:
            return CONFIDENCE_MEDIUM, (
                f"{self.unresolved_count} observed peer(s) remain unresolved "
                "in the graph"
            )
        return CONFIDENCE_HIGH, (
            "every reachable device was discovered and correlated from "
            "fresh evidence"
        )

    # -- one consolidated summary for any consumer ------------------------------

    def summary(
        self, operational: Mapping[str, Any] | None = None, *, fresh: bool = True
    ) -> dict[str, Any]:
        """The canonical enterprise summary every consumer can render."""

        level, reason = self.health(operational)
        band, basis = self.confidence(fresh=fresh)
        stats = self.statistics
        return {
            "snapshot_id": self.snapshot_id,
            "device_count": self.device_count,
            "relationship_count": self.relationship_count,
            "relationships_by_type": self.relationships_by_type,
            "routing_observations": self.routing_observations,
            "unresolved_observations": self.unresolved_count,
            "ownership_conflicts": self.ownership_conflicts,
            "reconciliation_warnings": self.warning_count,
            "discovery_statistics": stats.to_dict(),
            "discovery_completeness_percent": stats.discovery_completeness_percent,
            "health": level,
            "health_reason": reason,
            "confidence": band,
            "confidence_basis": basis,
        }

    # -- internals --------------------------------------------------------------

    def _logical_edge_count(self) -> int:
        hostname_by_id = {
            str(device.get("device_id")): str(device.get("hostname"))
            for device in self._snapshot.get("devices") or ()
            if isinstance(device, Mapping)
        }
        links: set[tuple[str, str]] = set()
        for edge in self._snapshot.get("edges") or ():
            if not isinstance(edge, Mapping):
                continue
            local = hostname_by_id.get(
                str(edge.get("local_device_id")), str(edge.get("local_device_id"))
            )
            remote = str(edge.get("remote_hostname"))
            endpoints = sorted((local.casefold(), remote.casefold()))
            links.add((endpoints[0], endpoints[1]))
        return len(links)


def classify_discovery_visits(
    connected: int,
    failed_details: tuple[str, ...],
    skipped: int,
    managed_devices: int,
) -> DiscoveryStatistics:
    """Deterministically classify discovery outcomes into statistics.

    ``failed_details`` are the per-address failure detail strings from the
    discovery report. Reachability-probe / timeout / refused failures are
    *unused addresses* (Information); authentication / permission failures
    and unsupported platforms are genuine discovery shortfalls. Shared by
    the discovery pipeline so the snapshot and every consumer agree.
    """

    auth_failed = unsupported = unreachable = 0
    for detail in failed_details:
        lowered = str(detail).casefold()
        if "unsupported platform" in lowered or "not recognize" in lowered:
            unsupported += 1
        elif any(
            token in lowered
            for token in (
                "authentication", "auth ", "password", "credential",
                "permission", "lockout", "denied",
            )
        ):
            auth_failed += 1
        else:
            # reachability probe, timeout, refused, unavailable, lost.
            unreachable += 1
    reachable = connected + auth_failed + unsupported
    addresses_scanned = reachable + unreachable + skipped
    return DiscoveryStatistics(
        addresses_scanned=addresses_scanned,
        reachable=reachable,
        authenticated=connected,
        managed_devices=managed_devices,
        unused_addresses=unreachable,
        authentication_failures=auth_failed,
        unsupported_platforms=unsupported,
    )
