"""Operational risk estimation: Low / Medium / High / Critical, documented.

    score = +25 when known forwarding paths break (critical paths)
            + 5 per device losing connectivity (cap +15)
            + 5 when the change touches production links at all
            +10 when redundancy is UNKNOWN (never assume it exists)
            -10 when redundancy is verified (alternate path confirmed)
            +10 when enterprise health is already below 70
            + 5 when enterprise health is below 85
            +10 when the target device has been historically unstable
            + 5 when prediction confidence is low (uncertainty is risk)

    level: >= 50 critical · >= 30 high · >= 15 medium · else low

Every contribution is a named factor with its reason — a CAB reviewer can
audit the level by adding up the list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RISK_CRITICAL = "critical"
RISK_HIGH = "high"
RISK_MEDIUM = "medium"
RISK_LOW = "low"


@dataclass(frozen=True)
class RiskFactor:
    name: str
    points: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "points": self.points, "detail": self.detail}


@dataclass(frozen=True)
class RiskAssessment:
    level: str
    score: int
    factors: tuple[RiskFactor, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "score": self.score,
            "factors": [factor.to_dict() for factor in self.factors],
        }


def estimate_risk(
    *,
    critical_path_count: int,
    affected_device_count: int,
    carries_links: bool,
    redundancy_verified: bool | None,
    health_score: int | None = None,
    historically_unstable: bool = False,
    confidence_band: str = "medium",
) -> RiskAssessment:
    factors: list[RiskFactor] = []

    def add(name: str, points: int, detail: str) -> None:
        factors.append(RiskFactor(name=name, points=points, detail=detail))

    if critical_path_count:
        add(
            "broken-forwarding-paths", 25,
            f"{critical_path_count} known forwarding path(s) break with no "
            "alternate route",
        )
    if affected_device_count:
        add(
            "devices-losing-connectivity",
            min(affected_device_count * 5, 15),
            f"{affected_device_count} device(s) lose connectivity",
        )
    if carries_links:
        add("production-links", 5, "the change touches active production links")
    if redundancy_verified is None:
        add(
            "unknown-redundancy", 10,
            "redundancy could not be verified — Atlas never assumes an "
            "alternate path exists",
        )
    elif redundancy_verified:
        add(
            "verified-redundancy", -10,
            "an alternate topology path is verified to absorb the change",
        )
    if health_score is not None:
        if health_score < 70:
            add(
                "degraded-enterprise-health", 10,
                f"enterprise health is already {health_score}/100",
            )
        elif health_score < 85:
            add(
                "reduced-enterprise-health", 5,
                f"enterprise health is {health_score}/100",
            )
    if historically_unstable:
        add(
            "historical-instability", 10,
            "the target device has failed in recent discoveries",
        )
    if confidence_band == "low":
        add(
            "low-prediction-confidence", 5,
            "uncertainty itself is operational risk",
        )
    score = max(0, sum(factor.points for factor in factors))
    if score >= 50:
        level = RISK_CRITICAL
    elif score >= 30:
        level = RISK_HIGH
    elif score >= 15:
        level = RISK_MEDIUM
    else:
        level = RISK_LOW
    return RiskAssessment(level=level, score=score, factors=tuple(factors))
