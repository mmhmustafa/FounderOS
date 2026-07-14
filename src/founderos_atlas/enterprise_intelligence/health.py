"""Deterministic enterprise health scoring. Every point is documented.

The score starts at 100 and each signal contributes a named, capped
factor. Weights are deliberately simple integers so a person can audit any
score by adding up the factor list — ``score == clamp(100 + sum(points))``
always holds. No AI, no randomness, no hidden inputs.

| Signal                              | Points                     | Cap  |
|-------------------------------------|----------------------------|------|
| Interface currently down            | -8 each                    | -24  |
| Other active operational issue      | -4 each                    | -12  |
| Authentication failure (device)     | -8 each                    | -16  |
| Unreachable device (discovery fail) | -6 each                    | -18  |
| High-severity topology change       | -3 each                    | -9   |
| Other topology change               | -1 each                    | -4   |
| High-severity configuration change  | -4 each                    | -8   |
| Device with configuration changes   | -2 each                    | -6   |
| Repeated device instability         | -3 per recurring device    | -9   |
| Open incident investigation         | -2 flat                    | -2   |
| Stale discovery (>24h old)          | -5 flat                    | -5   |
| Recovery observed this run          | +2 flat                    | +2   |
| Topology stable vs baseline         | +1 flat                    | +1   |

Confidence reflects evidence quality, not health: high when a baseline
exists, the discovery is fresh, and every device answered; medium when the
baseline is missing or some devices failed; low when discovery is stale or
a large share of devices failed.
"""

from __future__ import annotations

from .models import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    HealthScore,
    ScoreFactor,
)


STALE_AFTER_HOURS = 24


def score_health(evidence) -> HealthScore:
    """Compute the explained health score from one scope's evidence."""

    factors: list[ScoreFactor] = []

    def deduct(name: str, per_item: int, count: int, cap: int, detail: str, items=()):
        if count <= 0:
            return
        points = max(per_item * count, -abs(cap))  # cap is a positive magnitude
        factors.append(
            ScoreFactor(
                name=name,
                points=points,
                detail=detail,
                evidence=tuple(str(item) for item in items)[:5],
            )
        )

    interfaces_down = evidence.interfaces_down
    deduct(
        "interface-failures", -8, interfaces_down, 24,
        f"{interfaces_down} interface(s) currently down",
        evidence.active_issue_subjects,
    )
    other_active = max(0, evidence.active_issue_count - interfaces_down)
    deduct(
        "active-operational-issues", -4, other_active, 12,
        f"{other_active} additional active operational issue(s)",
    )
    auth_failures = len(evidence.auth_failed_hosts)
    deduct(
        "authentication-failures", -8, auth_failures, 16,
        f"authentication failed for {auth_failures} device(s)",
        evidence.auth_failed_hosts,
    )
    unreachable = len(evidence.unreachable_hosts)
    deduct(
        "unreachable-devices", -6, unreachable, 18,
        f"{unreachable} device(s) could not be discovered",
        evidence.unreachable_hosts,
    )
    deduct(
        "high-severity-topology-changes", -3, evidence.topology_high_changes, 9,
        f"{evidence.topology_high_changes} high-severity topology change(s)",
    )
    deduct(
        "topology-changes", -1, evidence.topology_other_changes, 4,
        f"{evidence.topology_other_changes} other topology change(s)",
    )
    deduct(
        "high-severity-configuration-changes", -4, evidence.config_high_changes, 8,
        f"{evidence.config_high_changes} high-severity configuration change(s)",
    )
    deduct(
        "configuration-drift", -2, evidence.config_devices_changed, 6,
        f"configuration changed on {evidence.config_devices_changed} device(s)",
    )
    recurring = len(evidence.recurring_unstable_hosts)
    deduct(
        "repeated-instability", -3, recurring, 9,
        f"{recurring} device(s) failed in multiple recent discoveries",
        evidence.recurring_unstable_hosts,
    )
    if evidence.incident_open:
        factors.append(
            ScoreFactor(
                name="open-incident",
                points=-2,
                detail="an incident investigation is on file for this network",
            )
        )
    if evidence.is_stale:
        factors.append(
            ScoreFactor(
                name="stale-discovery",
                points=-5,
                detail=(
                    f"the latest discovery is older than {STALE_AFTER_HOURS}h; "
                    "evidence may no longer reflect the network"
                ),
            )
        )
    if evidence.recovery_count > 0:
        factors.append(
            ScoreFactor(
                name="recovered-devices",
                points=2,
                detail=f"{evidence.recovery_count} recovery(ies) observed this run",
            )
        )
    if evidence.baseline_available and evidence.topology_change_count == 0:
        factors.append(
            ScoreFactor(
                name="topology-stable",
                points=1,
                detail="no topology changes against the previous baseline",
            )
        )

    score = 100 + sum(factor.points for factor in factors)
    score = max(0, min(100, score))
    return HealthScore(
        score=score,
        confidence=_confidence(evidence),
        factors=tuple(factors),
    )


def _confidence(evidence) -> str:
    # PR-043.10 (POLISH, Part 2): confidence reflects DISCOVERY COVERAGE of
    # real devices — reachable devices Atlas could not authenticate — never
    # unused CIDR addresses. Unused addresses are coverage information, not a
    # failure to observe a device.
    coverage_failed = evidence.coverage_failed_count
    attempted = evidence.device_count + coverage_failed
    failure_share = coverage_failed / attempted if attempted else 0.0
    if evidence.is_stale or failure_share > 0.25:
        return CONFIDENCE_LOW
    if not evidence.baseline_available or coverage_failed:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_HIGH
