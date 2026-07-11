"""Operational risk estimation: Low / Medium / High / Critical, documented.

    score = +25 when known forwarding paths break (critical paths)
            + 5 per device losing connectivity (cap +15)
            + 5 when the change touches production links at all
            +10 when redundancy is UNKNOWN (never assume it exists)
            -10 when redundancy is verified (alternate path confirmed)
            +25 when the change removes the device's ACTIVE management
                address (this single factor covers the shared dependency:
                SSH management, future discovery, configuration collection,
                and monitoring via that address — never double-counted)
            +10 when no alternate management path is verified for that loss
            -10 when a verified alternate management path exists
            +15 when verified gateway role evidence is lost (data plane)
            +15 when verified protocol role evidence is lost (control plane)
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
    management_lost: bool = False,
    management_alternate_verified: bool | None = None,
    gateway_lost: bool = False,
    control_lost: bool = False,
) -> RiskAssessment:
    factors: list[RiskFactor] = []

    def add(name: str, points: int, detail: str) -> None:
        factors.append(RiskFactor(name=name, points=points, detail=detail))

    if management_lost:
        add(
            "management-address-loss", 25,
            "the change removes the active management address — SSH "
            "management, future discovery, configuration collection, and "
            "monitoring via that address may become unavailable",
        )
        if management_alternate_verified:
            add(
                "verified-alternate-management", -10,
                "a verified alternate management address exists on the device",
            )
        else:
            add(
                "no-alternate-management", 10,
                "no alternate management path is verified — Atlas never "
                "assumes one exists",
            )
    if gateway_lost:
        add(
            "verified-gateway-loss", 15,
            "verified gateway role: devices using this interface as their "
            "default gateway lose reachability",
        )
    if control_lost:
        add(
            "control-plane-loss", 15,
            "verified protocol role: adjacencies or gateway protocols on "
            "this interface will drop",
        )

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
        # Unknown forwarding redundancy only matters when the change
        # actually touches forwarding (links, paths, or downstream
        # devices); a link-less logical interface is charged through the
        # management factors instead — never twice.
        if carries_links or critical_path_count or affected_device_count:
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
