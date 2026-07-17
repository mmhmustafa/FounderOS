"""Enterprise federation models: one graph, many observation points.

A discovery profile is an observation point, never an enterprise
boundary. The federation layer assembles canonical devices (reusing the
PR-033 evidence-based identity engine), canonical interfaces, canonical
links, merge decisions with their WHY, and visible unknown boundaries —
all with per-observation provenance. Observations are never destroyed;
canonical objects reference them.

Everything serializes to plain JSON. No field ever holds a secret —
credential information is carried as references only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from founderos_atlas.enterprise import EnterpriseDevice
from founderos_atlas.root_cause.confidence import band as confidence_band


FEDERATION_SCHEMA_VERSION = "1.0.0"

# Documented identity/merge confidence arithmetic (capped below 100%).
CONFIDENCE_SERIAL_MERGE = 0.95      # strong identifier proves one device
CONFIDENCE_CORROBORATED_MERGE = 0.75  # hostname+IP within a declared domain
CONFIDENCE_SINGLE_WITH_SERIAL = 0.9   # one observation, strong identifier
CONFIDENCE_SINGLE_WEAK = 0.6          # one observation, no strong identifier


@dataclass(frozen=True)
class ContributionSummary:
    """One profile's contribution to the enterprise graph."""

    profile_id: str
    profile_name: str
    run_id: str | None
    observed_at: str | None
    device_count: int
    edge_count: int
    fresh: bool | None = None  # None until a reference time is applied

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "run_id": self.run_id,
            "observed_at": self.observed_at,
            "device_count": self.device_count,
            "edge_count": self.edge_count,
            "fresh": self.fresh,
        }


@dataclass(frozen=True)
class CanonicalInterface:
    """One interface of a canonical device, with observation provenance."""

    name: str
    status: str | None
    protocol_status: str | None
    ip_address: str | None
    description: str | None
    observed_by: tuple[str, ...]  # profile names, deterministic order
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "protocol_status": self.protocol_status,
            "ip_address": self.ip_address,
            "description": self.description,
            "observed_by": list(self.observed_by),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class LinkObservation:
    """One profile's sighting of a link in one discovery run."""

    profile_id: str
    profile_name: str
    run_id: str | None
    observed_at: str | None
    protocol: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "run_id": self.run_id,
            "observed_at": self.observed_at,
            "protocol": self.protocol,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CanonicalLink:
    """One physical adjacency between canonical enterprise devices.

    ``remote_enterprise_id`` is None when the far end was only ever seen
    in neighbor announcements — an unknown boundary that stays visible
    rather than being invented into the inventory.
    """

    local_enterprise_id: str
    local_hostname: str
    local_interface: str | None
    remote_enterprise_id: str | None
    remote_hostname: str
    remote_interface: str | None
    protocol: str
    observations: tuple[LinkObservation, ...]
    cross_profile: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_boundary(self) -> bool:
        return self.remote_enterprise_id is None

    @property
    def observed_by(self) -> tuple[str, ...]:
        seen: list[str] = []
        for observation in self.observations:
            if observation.profile_name not in seen:
                seen.append(observation.profile_name)
        return tuple(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_enterprise_id": self.local_enterprise_id,
            "local_hostname": self.local_hostname,
            "local_interface": self.local_interface,
            "remote_enterprise_id": self.remote_enterprise_id,
            "remote_hostname": self.remote_hostname,
            "remote_interface": self.remote_interface,
            "protocol": self.protocol,
            "observations": [item.to_dict() for item in self.observations],
            "observed_by": list(self.observed_by),
            "cross_profile": self.cross_profile,
            "is_boundary": self.is_boundary,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MergeDecision:
    """Why observations became (or stayed) one canonical device.

    Engineers must always be able to see WHY Atlas believes two
    observations describe the same object — or why it kept them apart.
    """

    enterprise_id: str
    hostname: str
    merged: bool                      # more than one observation combined
    observation_count: int
    profiles: tuple[str, ...]
    reason: str
    evidence: tuple[str, ...]
    confidence: float

    @property
    def confidence_band(self) -> str:
        return confidence_band(self.confidence)

    @property
    def confidence_percent(self) -> int:
        return int(round(self.confidence * 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enterprise_id": self.enterprise_id,
            "hostname": self.hostname,
            "merged": self.merged,
            "observation_count": self.observation_count,
            "profiles": list(self.profiles),
            "reason": self.reason,
            "evidence": list(self.evidence),
            "confidence": round(self.confidence, 4),
            "confidence_percent": self.confidence_percent,
            "confidence_band": self.confidence_band,
        }


@dataclass(frozen=True)
class EnterpriseGraph:
    """The federated enterprise: canonical objects over raw observations.

    ``devices`` are the PR-033 canonical devices (with their untouched
    per-observation provenance); this graph adds merged interfaces,
    canonical links, explainable merge decisions, contribution summaries,
    and visible unknown boundaries.
    """

    devices: tuple[EnterpriseDevice, ...]
    interfaces: dict[str, tuple[CanonicalInterface, ...]]  # by enterprise_id
    links: tuple[CanonicalLink, ...]
    merge_decisions: tuple[MergeDecision, ...]
    contributions: tuple[ContributionSummary, ...]
    unknowns: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def device_count(self) -> int:
        return len(self.devices)

    @property
    def observation_count(self) -> int:
        return sum(len(device.observations) for device in self.devices)

    @property
    def merged_device_count(self) -> int:
        return sum(1 for decision in self.merge_decisions if decision.merged)

    @property
    def cross_profile_links(self) -> tuple[CanonicalLink, ...]:
        return tuple(link for link in self.links if link.cross_profile)

    @property
    def boundaries(self) -> tuple[CanonicalLink, ...]:
        return tuple(link for link in self.links if link.is_boundary)

    @property
    def sites(self) -> tuple[str, ...]:
        seen: list[str] = []
        for device in self.devices:
            label = device.site.label
            if label not in seen:
                seen.append(label)
        return tuple(sorted(seen))

    def device_by_id(self, enterprise_id: str) -> EnterpriseDevice | None:
        for device in self.devices:
            if device.enterprise_id == enterprise_id:
                return device
        return None

    def decision_for(self, enterprise_id: str) -> MergeDecision | None:
        for decision in self.merge_decisions:
            if decision.enterprise_id == enterprise_id:
                return decision
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FEDERATION_SCHEMA_VERSION,
            "generated_by": "founderos atlas enterprise federation",
            "device_count": self.device_count,
            "observation_count": self.observation_count,
            "merged_device_count": self.merged_device_count,
            "devices": [device.to_dict() for device in self.devices],
            "interfaces": {
                enterprise_id: [item.to_dict() for item in interfaces]
                for enterprise_id, interfaces in sorted(self.interfaces.items())
            },
            "links": [link.to_dict() for link in self.links],
            "merge_decisions": [item.to_dict() for item in self.merge_decisions],
            "contributions": [item.to_dict() for item in self.contributions],
            "sites": list(self.sites),
            "unknowns": list(self.unknowns),
            "attributes": dict(self.attributes),
        }
