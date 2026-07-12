"""Atlas Advisor models: structured, evidence-cited responses.

Advisor is an evidence ORCHESTRATION layer, never an answer-generation
layer. Every response follows one fixed structure — Summary, Evidence,
Confidence, Recommended Next Action, optional Follow-ups — plus the
list of steps Advisor actually performed (real orchestration, never
simulated reasoning). When evidence is unavailable the response says
so; nothing is ever invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ADVISOR_SCHEMA_VERSION = "1.0.0"

CONFIDENCE_HIGH = "High"
CONFIDENCE_MEDIUM = "Medium"
CONFIDENCE_LOW = "Low"
CONFIDENCE_UNKNOWN = "Unknown"

NO_EVIDENCE_MESSAGE = "I don't currently have enough evidence."


def confidence_from_band(band: str | None) -> str:
    """Map the engines' shared confidence bands onto Advisor labels."""

    folded = str(band or "").casefold()
    if folded in ("very-high", "high"):
        return CONFIDENCE_HIGH
    if folded == "medium":
        return CONFIDENCE_MEDIUM
    if folded == "low":
        return CONFIDENCE_LOW
    return CONFIDENCE_UNKNOWN


@dataclass(frozen=True)
class EvidenceItem:
    """One piece of evidence a response rests on — always openable."""

    label: str
    detail: str
    href: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "detail": self.detail, "href": self.href}


@dataclass(frozen=True)
class FollowUp:
    """A suggested next question or workflow."""

    label: str
    question: str | None = None  # resubmitted to Advisor
    href: str | None = None      # or a direct workflow link

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "question": self.question, "href": self.href}


@dataclass(frozen=True)
class AdvisorResponse:
    """The fixed response structure — no free-form generation."""

    question: str
    intent: str
    summary: str
    evidence: tuple[EvidenceItem, ...]
    confidence: str
    confidence_basis: str
    next_action_label: str
    next_action_href: str
    followups: tuple[FollowUp, ...] = ()
    unknowns: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()  # the REAL orchestration performed
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ADVISOR_SCHEMA_VERSION,
            "generated_by": "founderos atlas advisor",
            "question": self.question,
            "intent": self.intent,
            "summary": self.summary,
            "evidence": [item.to_dict() for item in self.evidence],
            "confidence": self.confidence,
            "confidence_basis": self.confidence_basis,
            "next_action": {
                "label": self.next_action_label,
                "href": self.next_action_href,
            },
            "followups": [item.to_dict() for item in self.followups],
            "unknowns": list(self.unknowns),
            "steps": list(self.steps),
            "generated_at": self.generated_at,
        }


@dataclass(frozen=True)
class ConversationEntry:
    """One stored question/response pair (local workspace only)."""

    asked_at: str
    response: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"asked_at": self.asked_at, "response": dict(self.response)}
