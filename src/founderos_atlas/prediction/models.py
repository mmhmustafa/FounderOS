"""Predictive change intelligence domain models (PR-036A).

First-class concepts for answering "what happens if I make this change?":
ChangeRequest, Boundary, PredictedOutcome, ConfidenceAssessment, and the
Prediction that ties dependency resolution, critical paths, redundancy,
blast radius, risk, rollback, and recommendations together.

Design rules (shared with every Atlas engine):

- deterministic and rule-based — no AI, no randomness, no guessing;
- every number explains itself (confidence is its factors);
- unknowns are stated, never papered over (``Prediction.unknowns``);
- plain-JSON serialization so the GUI, reports, tests — and a future AI
  explanation layer — consume the same structures;
- no field ever holds a secret.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PREDICTION_SCHEMA_VERSION = "1.0.0"

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

LIKELIHOOD_EXPECTED = "expected"      # deterministic consequence
LIKELIHOOD_PROBABLE = "probable"      # follows unless redundancy absorbs it
LIKELIHOOD_POSSIBLE = "possible"      # depends on evidence Atlas lacks


@dataclass(frozen=True)
class ChangeRequest:
    """A proposed change, before anyone touches the network.

    ``change_type`` is an open registry name (see ``change_requests``) —
    new kinds of change never require a model change. ``parameters`` carry
    type-specific detail (route prefix, ACL name, target version, ...).
    """

    request_id: str
    change_type: str
    target_device: str
    target_object: str | None = None      # interface, vlan, route, acl, ...
    description: str = ""
    requested_at: str | None = None
    profile_id: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    # Change-management context (PR-036B) — optional, never required.
    reason: str | None = None
    maintenance_window: str | None = None
    requester: str | None = None

    def __post_init__(self) -> None:
        for name in ("request_id", "change_type", "target_device"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

    @property
    def subject(self) -> str:
        if self.target_object:
            return f"{self.target_device} {self.target_object}"
        return self.target_device

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "change_type": self.change_type,
            "target_device": self.target_device,
            "target_object": self.target_object,
            "description": self.description,
            "requested_at": self.requested_at,
            "profile_id": self.profile_id,
            "parameters": dict(self.parameters),
            "reason": self.reason,
            "maintenance_window": self.maintenance_window,
            "requester": self.requester,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ChangeRequest":
        return cls(
            request_id=value["request_id"],
            change_type=value["change_type"],
            target_device=value["target_device"],
            target_object=value.get("target_object"),
            description=str(value.get("description") or ""),
            requested_at=value.get("requested_at"),
            profile_id=value.get("profile_id"),
            parameters=dict(value.get("parameters") or {}),
            reason=value.get("reason"),
            maintenance_window=value.get("maintenance_window"),
            requester=value.get("requester"),
        )


@dataclass(frozen=True)
class Boundary:
    """What part of the enterprise a prediction evaluates against.

    Empty dimensions mean "the whole visible enterprise". Boundaries let
    future predictions scope to profiles, sites, or explicit device sets
    without changing the pipeline.
    """

    profile_ids: tuple[str, ...] = ()
    sites: tuple[str, ...] = ()
    devices: tuple[str, ...] = ()

    @property
    def is_enterprise_wide(self) -> bool:
        return not (self.profile_ids or self.sites or self.devices)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_ids": list(self.profile_ids),
            "sites": list(self.sites),
            "devices": list(self.devices),
        }


@dataclass(frozen=True)
class PredictedOutcome:
    """One deterministic consequence of the proposed change."""

    category: str          # connectivity, protocol, service, discovery, ...
    description: str
    likelihood: str        # expected | probable | possible
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "description": self.description,
            "likelihood": self.likelihood,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class ConfidenceFactor:
    name: str
    points: float
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "points": self.points, "detail": self.detail}


@dataclass(frozen=True)
class ConfidenceAssessment:
    """Prediction confidence: a documented calculation, never 100%."""

    score: float           # 0.05 .. 0.95
    band: str              # very-high | high | medium | low
    factors: tuple[ConfidenceFactor, ...] = ()

    @property
    def percent(self) -> int:
        return int(round(self.score * 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "percent": self.percent,
            "band": self.band,
            "factors": [factor.to_dict() for factor in self.factors],
        }


@dataclass(frozen=True)
class Prediction:
    """The deterministic answer to "what happens if I make this change?"."""

    prediction_id: str
    generated_at: str
    change_request: ChangeRequest
    boundary: Boundary
    outcomes: tuple[PredictedOutcome, ...]
    blast_radius: Any                     # impact.BlastRadius
    critical_paths: tuple[Any, ...]       # critical_paths.CriticalPath
    redundancy: Any                       # redundancy.RedundancyAssessment
    rollback: Any                         # rollback.RollbackEstimate
    severity: str
    confidence: ConfidenceAssessment
    recommendations: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()        # what Atlas cannot see (stated!)
    evidence_refs: tuple[str, ...] = ()   # artifacts this rests on
    basis: dict[str, Any] = field(default_factory=dict)
    # PR-036B vertical slice: documented risk, structured advice, and a
    # human-readable explanation that cites its evidence.
    risk: Any = None                      # risk.RiskAssessment
    advice: Any = None                    # recommendations.Advice
    explanation: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PREDICTION_SCHEMA_VERSION,
            "generated_by": "founderos atlas prediction",
            "prediction_id": self.prediction_id,
            "generated_at": self.generated_at,
            "change_request": self.change_request.to_dict(),
            "boundary": self.boundary.to_dict(),
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "blast_radius": self.blast_radius.to_dict(),
            "critical_paths": [path.to_dict() for path in self.critical_paths],
            "redundancy": self.redundancy.to_dict(),
            "rollback": self.rollback.to_dict(),
            "severity": self.severity,
            "confidence": self.confidence.to_dict(),
            "recommendations": list(self.recommendations),
            "unknowns": list(self.unknowns),
            "evidence_refs": list(self.evidence_refs),
            "basis": dict(self.basis),
            "risk": self.risk.to_dict() if self.risk is not None else None,
            "advice": self.advice.to_dict() if self.advice is not None else None,
            "explanation": list(self.explanation),
        }
