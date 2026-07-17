"""Health states, dimensions, and aggregation — the one vocabulary.

States (mutually exclusive, applied per dimension and overall):

healthy
    Evaluated against current evidence and no problem found.
degraded
    Evaluated and a non-critical problem found (partial coverage, drift,
    active non-critical issues, failed policies).
critical
    Evaluated and a problem requiring immediate attention found.
stale
    The evidence behind the dimension is older than the freshness
    window; the last known answer may no longer be true.
unavailable
    The subsystem that would produce this dimension is not in use for
    the scope (e.g. configuration collection disabled, policy engine
    never run). Deliberate absence — stated, never counted as a pass.
unknown
    Atlas tried to evaluate and could not reach a verdict from the
    evidence it holds.

The overall state is the worst dimension state under the severity order
critical > degraded > stale > unknown > healthy. ``unavailable``
dimensions never make a scope unhealthy by themselves, but they are
always named in the overall detail — an environment with unavailable
dimensions is "healthy where evaluated", and the sentence says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


STATE_HEALTHY = "healthy"
STATE_DEGRADED = "degraded"
STATE_CRITICAL = "critical"
STATE_STALE = "stale"
STATE_UNAVAILABLE = "unavailable"
STATE_UNKNOWN = "unknown"

HEALTH_STATES = (
    STATE_HEALTHY,
    STATE_DEGRADED,
    STATE_CRITICAL,
    STATE_STALE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)

_SEVERITY = {
    STATE_CRITICAL: 5,
    STATE_DEGRADED: 4,
    STATE_STALE: 3,
    STATE_UNKNOWN: 2,
    STATE_HEALTHY: 1,
    STATE_UNAVAILABLE: 0,
}

DIMENSION_REACHABILITY = "reachability"
DIMENSION_FRESHNESS = "discovery-freshness"
DIMENSION_EVIDENCE = "evidence-coverage"
DIMENSION_POLICY = "policy-compliance"
DIMENSION_DRIFT = "configuration-drift"
DIMENSION_INCIDENTS = "active-incidents"
DIMENSION_IDENTITY = "topology-identity-confidence"

HEALTH_DIMENSIONS: dict[str, str] = {
    DIMENSION_REACHABILITY: "Reachability",
    DIMENSION_FRESHNESS: "Discovery freshness",
    DIMENSION_EVIDENCE: "Evidence coverage",
    DIMENSION_POLICY: "Policy compliance",
    DIMENSION_DRIFT: "Configuration drift",
    DIMENSION_INCIDENTS: "Active incidents",
    DIMENSION_IDENTITY: "Topology & identity confidence",
}


@dataclass(frozen=True)
class HealthDimension:
    """One independently calculated dimension with its full working."""

    key: str
    state: str
    summary: str                       # how the state was concluded, in words
    numerator: int | None = None
    denominator: int | None = None
    unit: str = ""
    observed_at: str | None = None     # timestamp of the underlying evidence
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.key not in HEALTH_DIMENSIONS:
            raise ValueError(f"unknown health dimension {self.key!r}")
        if self.state not in HEALTH_STATES:
            raise ValueError(f"unknown health state {self.state!r}")

    @property
    def label(self) -> str:
        return HEALTH_DIMENSIONS[self.key]

    @property
    def ratio_text(self) -> str:
        """``numerator/denominator unit`` when both are known, else ``—``."""

        if self.numerator is None or self.denominator is None:
            return "—"
        text = f"{self.numerator}/{self.denominator}"
        return f"{text} {self.unit}".strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "state": self.state,
            "summary": self.summary,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "unit": self.unit,
            "ratio": self.ratio_text,
            "observed_at": self.observed_at,
            "evidence": list(self.evidence),
        }


def overall_state(
    dimensions: tuple[HealthDimension, ...],
) -> tuple[str, str]:
    """The worst-of overall verdict and an honest one-sentence detail."""

    if not dimensions:
        return STATE_UNKNOWN, "No health dimensions were evaluated."
    worst = STATE_UNAVAILABLE
    for dimension in dimensions:
        if _SEVERITY[dimension.state] > _SEVERITY[worst]:
            worst = dimension.state
    if worst == STATE_UNAVAILABLE:
        return STATE_UNKNOWN, (
            "No health dimension could be evaluated for this scope."
        )
    causes = [d for d in dimensions if d.state == worst]
    unavailable = [d for d in dimensions if d.state == STATE_UNAVAILABLE]
    if worst == STATE_HEALTHY:
        if unavailable:
            names = ", ".join(d.label for d in unavailable)
            return STATE_HEALTHY, (
                f"Healthy where evaluated — not assessed: {names}."
            )
        return STATE_HEALTHY, "All health dimensions are healthy."
    names = "; ".join(f"{d.label}: {d.summary}" for d in causes)
    return worst, names


@dataclass(frozen=True)
class HealthAssessment:
    """The canonical health of one scope at one moment."""

    scope_id: str
    scope_label: str
    generated_at: str
    dimensions: tuple[HealthDimension, ...] = field(default_factory=tuple)

    @property
    def overall(self) -> str:
        return overall_state(self.dimensions)[0]

    @property
    def overall_detail(self) -> str:
        return overall_state(self.dimensions)[1]

    def dimension(self, key: str) -> HealthDimension | None:
        for item in self.dimensions:
            if item.key == key:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        state, detail = overall_state(self.dimensions)
        return {
            "scope_id": self.scope_id,
            "scope_label": self.scope_label,
            "generated_at": self.generated_at,
            "overall": state,
            "overall_detail": detail,
            "dimensions": [item.to_dict() for item in self.dimensions],
        }


def aggregate_assessments(
    assessments: tuple[HealthAssessment, ...] | list[HealthAssessment],
    *,
    scope_id: str,
    scope_label: str,
    generated_at: str,
) -> HealthAssessment:
    """Enterprise health from per-network assessments.

    Per dimension: the worst contributing state wins; numerators and
    denominators sum where every contributor reports them (a single
    unknown denominator makes the aggregate ratio honest ``—`` rather
    than a partial sum passed off as a total); the oldest evidence
    timestamp is kept, because the aggregate is only as fresh as its
    stalest contributor.
    """

    resolved = tuple(assessments)
    dimensions: list[HealthDimension] = []
    for key in HEALTH_DIMENSIONS:
        contributions = [
            (assessment, assessment.dimension(key))
            for assessment in resolved
        ]
        present = [
            (assessment, dim) for assessment, dim in contributions
            if dim is not None
        ]
        if not present:
            continue
        worst_state = STATE_UNAVAILABLE
        for _, dim in present:
            if _SEVERITY[dim.state] > _SEVERITY[worst_state]:
                worst_state = dim.state
        numerators = [dim.numerator for _, dim in present]
        denominators = [dim.denominator for _, dim in present]
        numerator = (
            sum(numerators) if all(v is not None for v in numerators) else None
        )
        denominator = (
            sum(denominators)
            if all(v is not None for v in denominators) else None
        )
        observed = [
            dim.observed_at for _, dim in present if dim.observed_at
        ]
        causes = [
            f"{assessment.scope_label}: {dim.summary}"
            for assessment, dim in present
            if dim.state == worst_state and worst_state != STATE_HEALTHY
        ]
        summary = (
            "; ".join(causes)
            if causes
            else f"healthy across {len(present)} network(s)"
        )
        dimensions.append(
            HealthDimension(
                key=key,
                state=worst_state,
                summary=summary,
                numerator=numerator,
                denominator=denominator,
                unit=present[0][1].unit,
                observed_at=min(observed) if observed else None,
                evidence=tuple(
                    f"{assessment.scope_label}: {dim.state} — {dim.ratio_text}"
                    for assessment, dim in present
                ),
            )
        )
    return HealthAssessment(
        scope_id=scope_id,
        scope_label=scope_label,
        generated_at=generated_at,
        dimensions=tuple(dimensions),
    )
