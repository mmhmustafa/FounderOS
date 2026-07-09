"""Immutable incident investigation models."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any


CONFIDENCE_LEVELS = ("low", "medium", "high")

EVIDENCE_TOPOLOGY = "topology_snapshot"
EVIDENCE_CHANGES = "change_report"
EVIDENCE_CONFIG = "config_change_report"
EVIDENCE_HISTORY = "history"
EVIDENCE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class EvidenceItem:
    """One factual statement and the artifact it came from."""

    statement: str
    source: str

    def __post_init__(self) -> None:
        for name in ("statement", "source"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        return {"statement": self.statement, "source": self.source}


@dataclass(frozen=True)
class IncidentReport:
    """A structured, evidence-based investigation — facts only, no invention."""

    incident_id: str
    title: str
    description: str
    generated_at: str
    affected_devices: tuple[str, ...]
    possible_related_changes: tuple[str, ...]
    topology_context: tuple[str, ...]
    configuration_context: tuple[str, ...]
    investigation_steps: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]
    confidence: str
    recommendations: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("incident_id", "title", "description", "generated_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"confidence must be one of {CONFIDENCE_LEVELS}")
        if not all(isinstance(item, EvidenceItem) for item in self.evidence):
            raise ValueError("evidence must contain EvidenceItem values")
        for name in (
            "affected_devices", "possible_related_changes", "topology_context",
            "configuration_context", "investigation_steps", "recommendations",
            "limitations",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not all(
                isinstance(value, str) for value in values
            ):
                raise ValueError(f"{name} must be a tuple of strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "description": self.description,
            "generated_at": self.generated_at,
            "affected_devices": list(self.affected_devices),
            "possible_related_changes": list(self.possible_related_changes),
            "topology_context": list(self.topology_context),
            "configuration_context": list(self.configuration_context),
            "investigation_steps": list(self.investigation_steps),
            "evidence": [item.to_dict() for item in self.evidence],
            "confidence": self.confidence,
            "recommendations": list(self.recommendations),
            "limitations": list(self.limitations),
        }


def incident_id_for(title: str, description: str, snapshot_id: str | None) -> str:
    """Deterministic content-addressed incident identifier."""

    digest = sha256(
        f"{title}|{description}|{snapshot_id or 'no-snapshot'}".encode("utf-8")
    ).hexdigest()
    return f"INC-{digest[:10]}"
