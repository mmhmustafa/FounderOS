"""Enterprise intelligence models: explained scores, findings, guidance.

Design rules:

- every number explains itself (a ``HealthScore`` is its factors);
- every finding carries severity, risk, confidence, and urgency;
- everything serializes to plain JSON so dashboards, briefs, tests, and a
  future AI layer consume the same structure;
- no field ever holds a secret.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

RISK_HIGH = "high"
RISK_MEDIUM = "medium"
RISK_LOW = "low"

URGENCY_IMMEDIATE = "immediate"
URGENCY_SOON = "soon"
URGENCY_SCHEDULED = "scheduled"

TREND_IMPROVING = "improving"
TREND_DECLINING = "declining"
TREND_STABLE = "stable"
TREND_BASELINE = "baseline"  # first scored discovery; nothing to compare

INTELLIGENCE_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class ScoreFactor:
    """One documented contribution to the health score."""

    name: str
    points: int  # negative deductions, positive credits
    detail: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "points": self.points,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class HealthScore:
    """Calculated enterprise health: the score IS its factors."""

    score: int  # 0..100
    confidence: str
    factors: tuple[ScoreFactor, ...]

    @property
    def deductions(self) -> tuple[ScoreFactor, ...]:
        return tuple(factor for factor in self.factors if factor.points < 0)

    @property
    def credits(self) -> tuple[ScoreFactor, ...]:
        return tuple(factor for factor in self.factors if factor.points > 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "confidence": self.confidence,
            "factors": [factor.to_dict() for factor in self.factors],
        }


@dataclass(frozen=True)
class Finding:
    """One thing worth a network manager's attention."""

    finding_id: str
    category: str        # e.g. interface-failure, discovery-failure, ...
    title: str
    summary: str
    severity: str        # high | medium | low
    risk: str            # high | medium | low
    confidence: str      # high | medium | low
    urgency: str         # immediate | soon | scheduled
    subject: str         # device/interface the finding is about
    blast_radius: int = 0    # directly connected neighbor devices
    recurring: bool = False  # seen across multiple recent discoveries
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "category": self.category,
            "title": self.title,
            "summary": self.summary,
            "severity": self.severity,
            "risk": self.risk,
            "confidence": self.confidence,
            "urgency": self.urgency,
            "subject": self.subject,
            "blast_radius": self.blast_radius,
            "recurring": self.recurring,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class Recommendation:
    """Actionable guidance for one finding: cause first, then next step."""

    finding_id: str
    title: str
    impact: str
    likely_cause: str
    next_step: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "title": self.title,
            "impact": self.impact,
            "likely_cause": self.likely_cause,
            "next_step": self.next_step,
        }


@dataclass(frozen=True)
class TrendSignal:
    """One observed direction across recent discoveries."""

    name: str
    direction: str  # improving | declining | stable | baseline
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "direction": self.direction,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class EnterpriseIntelligence:
    """The complete intelligence output of one discovery."""

    generated_at: str
    health: HealthScore
    trend: str                    # overall health trajectory
    trend_detail: str
    findings: tuple[Finding, ...]              # everything detected
    priorities: tuple[Finding, ...]            # ranked, top N
    recommendations: tuple[Recommendation, ...]
    trends: tuple[TrendSignal, ...]
    changes_summary: tuple[str, ...] = ()      # "changes since yesterday"
    biggest_improvement: str | None = None
    biggest_regression: str | None = None
    suggested_investigation: str | None = None
    previous_score: int | None = None
    basis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": INTELLIGENCE_SCHEMA_VERSION,
            "generated_by": "founderos atlas discover",
            "generated_at": self.generated_at,
            "health": self.health.to_dict(),
            "trend": self.trend,
            "trend_detail": self.trend_detail,
            "findings": [finding.to_dict() for finding in self.findings],
            "priorities": [finding.to_dict() for finding in self.priorities],
            "recommendations": [item.to_dict() for item in self.recommendations],
            "trends": [signal.to_dict() for signal in self.trends],
            "changes_summary": list(self.changes_summary),
            "biggest_improvement": self.biggest_improvement,
            "biggest_regression": self.biggest_regression,
            "suggested_investigation": self.suggested_investigation,
            "previous_score": self.previous_score,
            "basis": dict(self.basis),
        }
