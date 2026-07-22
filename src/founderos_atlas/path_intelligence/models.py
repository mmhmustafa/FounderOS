"""Path investigation models: hops, narrative steps, the full result.

Everything serializes to plain JSON (GUI, CLI, future API/assistant read
the same structure), every conclusion cites evidence, and unknowns are
explicit. No field ever holds a secret.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from founderos_atlas.root_cause.confidence import band as confidence_band


PATH_SCHEMA_VERSION = "1.0.0"

HOP_PASS = "pass"
HOP_WARNING = "warning"
HOP_FAILED = "failed"
HOP_UNKNOWN = "unknown"

RESULT_CONNECTED = "connected"
RESULT_FAILED = "failed"
RESULT_AMBIGUOUS = "ambiguous"
RESULT_UNKNOWN = "unknown"

# Deterministic failure vocabulary — never invented protocol failures.
FAILURE_ACL_DENY = "acl-deny"
FAILURE_FIREWALL_DENY = "firewall-deny"
# The device is on a good link and still drops the packet: its captured
# routing table holds nothing that matches the destination.
FAILURE_NO_ROUTE = "no-route"
FAILURE_INTERFACE_DOWN = "interface-down"
FAILURE_ADMIN_SHUTDOWN = "administrative-shutdown"
FAILURE_MISSING_EDGE = "missing-topology-edge"
FAILURE_DEVICE_UNREACHABLE = "device-unreachable"
FAILURE_DISCOVERY_INCOMPLETE = "discovery-incomplete"
FAILURE_UNKNOWN_PATH = "unknown-path"
FAILURE_UNKNOWN_DEVICE = "unknown-device"
FAILURE_UNKNOWN_DESTINATION = "unknown-destination"
FAILURE_AMBIGUOUS_TOPOLOGY = "ambiguous-topology"


@dataclass(frozen=True)
class HopResult:
    """One validated stage of the path."""

    hop_number: int
    device: str
    ingress_interface: str | None
    egress_interface: str | None
    link_state: str          # up | down | administratively-down | unknown | n/a
    management_state: str    # reachable | failed | unknown
    status: str              # pass | warning | failed | unknown
    confidence: float
    explanation: str
    evidence: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    failure_type: str | None = None
    # The route this hop would forward on, when a routing table was
    # captured to decide it. Structured rather than only narrated, so a
    # caller can act on it — withdraw it and re-run, say — without parsing
    # an English sentence back apart.
    route: dict[str, Any] | None = None

    @property
    def confidence_band(self) -> str:
        return confidence_band(self.confidence)

    @property
    def confidence_percent(self) -> int:
        return int(round(self.confidence * 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "hop_number": self.hop_number,
            "device": self.device,
            "ingress_interface": self.ingress_interface,
            "egress_interface": self.egress_interface,
            "link_state": self.link_state,
            "management_state": self.management_state,
            "status": self.status,
            "confidence": round(self.confidence, 4),
            "confidence_percent": self.confidence_percent,
            "confidence_band": self.confidence_band,
            "explanation": self.explanation,
            "evidence": list(self.evidence),
            "missing_evidence": list(self.missing_evidence),
            "failure_type": self.failure_type,
            "route": dict(self.route) if self.route else None,
        }


@dataclass(frozen=True)
class InvestigationStep:
    """One line of the narrated investigation story."""

    number: int
    title: str
    status: str              # pass | warning | failed | unknown
    detail: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class PathInvestigationResult:
    """The complete answer to "where does communication stop, and why?"."""

    investigation_id: str
    generated_at: str
    source: str
    destination: str
    status: str                              # connected | failed | ambiguous | unknown
    path: tuple[str, ...]                    # device sequence, when known
    hops: tuple[HopResult, ...]
    steps: tuple[InvestigationStep, ...]     # the narrative
    failure_type: str | None
    failure_summary: str | None
    recommendations: tuple[str, ...]
    confidence: float
    unknowns: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    profile_id: str | None = None
    basis: dict[str, Any] = field(default_factory=dict)

    @property
    def confidence_band(self) -> str:
        return confidence_band(self.confidence)

    @property
    def confidence_percent(self) -> int:
        return int(round(self.confidence * 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PATH_SCHEMA_VERSION,
            "generated_by": "founderos atlas path intelligence",
            "investigation_id": self.investigation_id,
            "generated_at": self.generated_at,
            "source": self.source,
            "destination": self.destination,
            "status": self.status,
            "path": list(self.path),
            "hops": [hop.to_dict() for hop in self.hops],
            "steps": [step.to_dict() for step in self.steps],
            "failure_type": self.failure_type,
            "failure_summary": self.failure_summary,
            "recommendations": list(self.recommendations),
            "confidence": round(self.confidence, 4),
            "confidence_percent": self.confidence_percent,
            "confidence_band": self.confidence_band,
            "unknowns": list(self.unknowns),
            "evidence_refs": list(self.evidence_refs),
            "profile_id": self.profile_id,
            "basis": dict(self.basis),
        }
