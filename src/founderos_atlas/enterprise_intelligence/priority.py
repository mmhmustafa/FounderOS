"""Priority ranking: the top things a manager should care about first.

Deterministic weighted scoring — documented, auditable, and stable:

    rank score = (urgency + severity + risk + blast radius + recurrence)
                 x confidence multiplier

| Component     | Values                                              |
|---------------|-----------------------------------------------------|
| Urgency       | immediate 40 · soon 25 · scheduled 10               |
| Severity      | high 30 · medium 20 · low 10                        |
| Risk          | high 20 · medium 12 · low 5                         |
| Blast radius  | +2 per directly connected neighbor (max +10)        |
| Recurrence    | +5 when seen across multiple recent discoveries     |
| Confidence    | x1.0 high · x0.85 medium · x0.7 low                 |

Ties break on category then subject then finding id, so the queue is
byte-stable for identical evidence.
"""

from __future__ import annotations

from .models import Finding


TOP_PRIORITIES = 5

_URGENCY_POINTS = {"immediate": 40, "soon": 25, "scheduled": 10}
_SEVERITY_POINTS = {"high": 30, "medium": 20, "low": 10}
_RISK_POINTS = {"high": 20, "medium": 12, "low": 5}
_CONFIDENCE_MULTIPLIER = {"high": 1.0, "medium": 0.85, "low": 0.7}


def rank_score(finding: Finding) -> float:
    base = (
        _URGENCY_POINTS.get(finding.urgency, 10)
        + _SEVERITY_POINTS.get(finding.severity, 10)
        + _RISK_POINTS.get(finding.risk, 5)
        + min(finding.blast_radius * 2, 10)
        + (5 if finding.recurring else 0)
    )
    return base * _CONFIDENCE_MULTIPLIER.get(finding.confidence, 0.7)


def prioritize(
    findings: tuple[Finding, ...], *, limit: int = TOP_PRIORITIES
) -> tuple[Finding, ...]:
    """The top findings, highest rank first, deterministic ties."""

    ordered = sorted(
        findings,
        key=lambda item: (
            -rank_score(item),
            item.category,
            item.subject,
            item.finding_id,
        ),
    )
    return tuple(ordered[:limit])
