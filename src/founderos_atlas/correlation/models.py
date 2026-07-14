"""Canonical models for Atlas evidence correlation (PR-043.7, FUSION).

Drivers collect facts. Normalization creates canonical observations.
Evidence Correlation creates Enterprise Knowledge. Topology is generated
from Enterprise Knowledge — no parser, protocol, or platform driver may
directly build topology.

Everything here is immutable, deterministic, and JSON-plain via
``to_dict``. Nothing holds a secret, calls a clock, or touches a wire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# -- address ownership -------------------------------------------------------------

# How a canonical device owns an address, strongest first. When one
# device claims the same address several ways (a loopback that is also
# the router ID), the strongest kind is kept as the canonical claim.
KIND_MANAGEMENT = "management"
KIND_LOOPBACK = "loopback"
KIND_INTERFACE = "interface"
KIND_SECONDARY = "secondary"
KIND_ROUTER_ID = "router-id"
KIND_VIRTUAL = "virtual"

OWNERSHIP_KINDS = (
    KIND_MANAGEMENT, KIND_LOOPBACK, KIND_INTERFACE,
    KIND_SECONDARY, KIND_ROUTER_ID, KIND_VIRTUAL,
)
_KIND_RANK = {kind: rank for rank, kind in enumerate(OWNERSHIP_KINDS)}


@dataclass(frozen=True, order=True)
class AddressClaim:
    """One canonical device's claim to one address, with provenance."""

    address: str
    device_id: str
    kind: str
    interface: str | None = None
    source_command: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in OWNERSHIP_KINDS:
            raise ValueError(f"unknown ownership kind: {self.kind!r}")

    @property
    def rank(self) -> int:
        return _KIND_RANK[self.kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "device_id": self.device_id,
            "kind": self.kind,
            "interface": self.interface,
            "source_command": self.source_command,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class OwnershipConflict:
    """Two canonical devices claim the same address — reported, not guessed."""

    address: str
    claims: tuple[AddressClaim, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "claims": [claim.to_dict() for claim in self.claims],
        }


class AddressOwnershipIndex:
    """The enterprise-wide address → canonical-device map.

    Every discovered address belongs to exactly one canonical device;
    an address claimed by two devices is a recorded conflict and
    resolves to no one (Atlas never guesses an owner).
    """

    def __init__(self, claims: tuple[AddressClaim, ...] = ()) -> None:
        by_address: dict[str, list[AddressClaim]] = {}
        for claim in claims:
            by_address.setdefault(claim.address, []).append(claim)
        self._owners: dict[str, AddressClaim] = {}
        conflicts: list[OwnershipConflict] = []
        for address in sorted(by_address):
            entries = sorted(by_address[address], key=lambda c: (c.rank, c.device_id))
            devices = {entry.device_id for entry in entries}
            if len(devices) > 1:
                conflicts.append(OwnershipConflict(address, tuple(entries)))
                continue
            self._owners[address] = entries[0]  # strongest claim wins
        self._conflicts = tuple(conflicts)
        self._claims = tuple(sorted(claims))

    def owner_of(self, address: str) -> AddressClaim | None:
        """The single canonical claim for an address, or None (unknown
        address, or a conflicted one)."""

        return self._owners.get(str(address).strip())

    def claims_for(self, device_id: str) -> tuple[AddressClaim, ...]:
        return tuple(
            claim for claim in self._claims if claim.device_id == device_id
        )

    @property
    def conflicts(self) -> tuple[OwnershipConflict, ...]:
        return self._conflicts

    @property
    def address_count(self) -> int:
        return len(self._owners)

    def to_dict(self) -> dict[str, Any]:
        return {
            "addresses": {
                address: self._owners[address].to_dict()
                for address in sorted(self._owners)
            },
            "conflicts": [conflict.to_dict() for conflict in self._conflicts],
        }


# -- evidence -----------------------------------------------------------------------

# Deterministic correlation priority (Part 5A). Lower number = stronger.
# Lower-priority observations strengthen confidence; they never override
# stronger evidence.
PRIORITY_INTERFACE_OWNERSHIP = 1   # verified interface IP/MAC ownership
PRIORITY_P2P_SUBNET = 2            # matching point-to-point subnets
PRIORITY_LINK_LAYER = 3            # LLDP / CDP
PRIORITY_OSPF = 4                  # OSPF neighbor
PRIORITY_BGP = 5                   # BGP peer
PRIORITY_STATIC_ROUTE = 6          # static routes
PRIORITY_ARP_MAC = 7               # ARP / MAC correlation
PRIORITY_CONFIG_REFERENCE = 8      # configuration references (descriptions)
PRIORITY_HOSTNAME = 9              # hostname matching

EVIDENCE_KINDS = {
    PRIORITY_INTERFACE_OWNERSHIP: "interface-ownership",
    PRIORITY_P2P_SUBNET: "p2p-subnet",
    PRIORITY_LINK_LAYER: "link-layer",
    PRIORITY_OSPF: "ospf-neighbor",
    PRIORITY_BGP: "bgp-peer",
    PRIORITY_STATIC_ROUTE: "static-route",
    PRIORITY_ARP_MAC: "arp-mac",
    PRIORITY_CONFIG_REFERENCE: "config-reference",
    PRIORITY_HOSTNAME: "hostname-match",
}

# Deterministic base confidence per priority; each additional
# independent evidence kind adds CORROBORATION_BONUS. Atlas confidence
# never exceeds CONFIDENCE_CAP.
CONFIDENCE_BASE = {1: 90, 2: 85, 3: 80, 4: 70, 5: 65, 6: 55, 7: 50, 8: 45, 9: 40}
CORROBORATION_BONUS = 5
CONFIDENCE_CAP = 95


@dataclass(frozen=True, order=True)
class RelationshipEvidence:
    """One independent observation supporting a relationship, with the
    full provenance chain: which device, which command, which driver."""

    priority: int
    kind: str
    detail: str
    observed_by: str = ""            # device_id whose evidence this is
    source_command: str | None = None
    platform_family: str | None = None
    local_interface: str | None = None
    remote_interface: str | None = None

    def __post_init__(self) -> None:
        if self.priority not in EVIDENCE_KINDS:
            raise ValueError(f"unknown evidence priority: {self.priority!r}")
        if self.kind != EVIDENCE_KINDS[self.priority]:
            raise ValueError(
                f"evidence kind {self.kind!r} does not match priority "
                f"{self.priority} ({EVIDENCE_KINDS[self.priority]!r})"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "kind": self.kind,
            "detail": self.detail,
            "observed_by": self.observed_by,
            "source_command": self.source_command,
            "platform_family": self.platform_family,
            "local_interface": self.local_interface,
            "remote_interface": self.remote_interface,
        }


# -- correlated relationships --------------------------------------------------------

# Relationship types (Part 8), decided deterministically from the
# evidence kinds present — never from a single protocol alone.
REL_VERIFIED_PHYSICAL = "verified-physical"
REL_VERIFIED_ROUTED = "verified-routed"
REL_LAYER2 = "layer-2"
REL_LAYER3 = "layer-3"
REL_BGP = "bgp"
REL_OSPF = "ospf"
REL_STATIC = "static"
REL_INFERRED = "inferred"
REL_UNKNOWN = "unknown"

RELATIONSHIP_TYPES = (
    REL_VERIFIED_PHYSICAL, REL_VERIFIED_ROUTED, REL_LAYER2, REL_LAYER3,
    REL_BGP, REL_OSPF, REL_STATIC, REL_INFERRED, REL_UNKNOWN,
)


@dataclass(frozen=True)
class CorrelatedRelationship:
    """One fused enterprise relationship: type, confidence, and every
    observation that produced it (Part 8A provenance)."""

    left_device_id: str
    right_device_id: str
    relationship_type: str
    confidence: int
    evidence: tuple[RelationshipEvidence, ...]
    left_interface: str | None = None
    right_interface: str | None = None
    observed_at: str | None = None
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError(
                f"unknown relationship type: {self.relationship_type!r}"
            )
        if not (0 <= self.confidence <= CONFIDENCE_CAP):
            raise ValueError(
                f"confidence must be within [0, {CONFIDENCE_CAP}]"
            )
        if not self.evidence:
            raise ValueError("a relationship requires at least one evidence item")

    @property
    def strongest_priority(self) -> int:
        return min(item.priority for item in self.evidence)

    @property
    def contributing_devices(self) -> tuple[str, ...]:
        return tuple(sorted({e.observed_by for e in self.evidence if e.observed_by}))

    @property
    def contributing_commands(self) -> tuple[str, ...]:
        return tuple(
            sorted({e.source_command for e in self.evidence if e.source_command})
        )

    @property
    def contributing_drivers(self) -> tuple[str, ...]:
        return tuple(
            sorted({e.platform_family for e in self.evidence if e.platform_family})
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_device_id": self.left_device_id,
            "right_device_id": self.right_device_id,
            "left_interface": self.left_interface,
            "right_interface": self.right_interface,
            "relationship_type": self.relationship_type,
            "confidence": self.confidence,
            "strongest_priority": self.strongest_priority,
            "observed_at": self.observed_at,
            "evidence": [item.to_dict() for item in self.evidence],
            "contributing_devices": list(self.contributing_devices),
            "contributing_commands": list(self.contributing_commands),
            "contributing_drivers": list(self.contributing_drivers),
            "conflicts": list(self.conflicts),
        }


@dataclass(frozen=True)
class UnresolvedObservation:
    """A neighbor observation whose remote identity Atlas cannot prove.

    Unknown stays unknown: the observation is preserved as evidence and
    displayed as unresolved, never guessed into a relationship."""

    local_device_id: str
    local_interface: str
    remote_identity: str
    protocol: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_device_id": self.local_device_id,
            "local_interface": self.local_interface,
            "remote_identity": self.remote_identity,
            "protocol": self.protocol,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CorrelationResult:
    """Everything one fusion pass produced, ready for the snapshot."""

    relationships: tuple[CorrelatedRelationship, ...]
    unresolved: tuple[UnresolvedObservation, ...]
    ownership: AddressOwnershipIndex
    warnings: tuple[str, ...] = field(default=())

    def summary(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for relationship in self.relationships:
            by_type[relationship.relationship_type] = (
                by_type.get(relationship.relationship_type, 0) + 1
            )
        return {
            "relationships": len(self.relationships),
            "by_type": dict(sorted(by_type.items())),
            "unresolved_observations": len(self.unresolved),
            "addresses_indexed": self.ownership.address_count,
            "ownership_conflicts": len(self.ownership.conflicts),
            "warnings": list(self.warnings),
            "deterministic": True,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationships": [item.to_dict() for item in self.relationships],
            "unresolved": [item.to_dict() for item in self.unresolved],
            "ownership_conflicts": [
                conflict.to_dict() for conflict in self.ownership.conflicts
            ],
            "summary": self.summary(),
        }
