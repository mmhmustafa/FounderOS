"""Advice derived from a prediction — an action plus the WHY.

The decision ladder (documented, deterministic):

- risk **critical**, or known forwarding paths break
    -> "High Risk — CAB approval recommended"
- risk **high** with unknown redundancy
    -> "Investigate redundancy first"
- risk **medium**, or the change touches production links
    -> "Proceed during a maintenance window"
- target missing from the discovered topology
    -> "Run a fresh discovery first"
- otherwise
    -> "Proceed"

Every action carries its reasons; ``Advice.lines()`` flattens to the
strings shown in reports and the GUI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .critical_paths import CriticalPath
from .impact import BlastRadius
from .models import SEVERITY_HIGH
from .redundancy import RedundancyAssessment
from .risk import RISK_CRITICAL, RISK_HIGH, RISK_MEDIUM, RiskAssessment
from .rollback import RollbackEstimate


ACTION_PROCEED = "Proceed"
ACTION_MAINTENANCE = "Proceed during a maintenance window"
ACTION_INVESTIGATE = "Investigate redundancy first"
ACTION_CAB = "High Risk — CAB approval recommended"
ACTION_DISCOVER = "Run a fresh discovery first"
ACTION_VERIFY_MGMT = (
    "Do not proceed until an alternate management path is verified"
)


@dataclass(frozen=True)
class Advice:
    action: str
    reasons: tuple[str, ...]

    def lines(self) -> tuple[str, ...]:
        return (self.action, *self.reasons)

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "reasons": list(self.reasons)}


def advise(
    *,
    risk: RiskAssessment,
    blast_radius: BlastRadius,
    critical_paths: tuple[CriticalPath, ...],
    redundancy: RedundancyAssessment,
    rollback: RollbackEstimate,
    subject: str,
    target_known: bool = True,
    touches_links: bool = False,
    management_lost: bool = False,
    management_alternate_verified: bool | None = None,
    management_detail: str = "",
) -> Advice:
    reasons: list[str] = []
    if not target_known:
        return Advice(
            action=ACTION_DISCOVER,
            reasons=(
                f"{subject} is not present in the discovered topology, so "
                "impact cannot be traced on current evidence.",
            ),
        )
    if management_lost:
        reasons.append(
            f"{subject} owns the management address Atlas uses to reach the "
            "device; services using this address may become unavailable "
            "(SSH management, future discovery, configuration collection, "
            "monitoring)."
        )
        if management_detail:
            reasons.append(management_detail + ".")
    if critical_paths:
        pairs = ", ".join(
            f"{path.hops[0]}–{path.hops[-1]}" for path in critical_paths[:3]
        )
        reasons.append(
            f"Connectivity will break between {pairs}; schedule a maintenance "
            "window and notify the affected teams."
        )
    if blast_radius.severity == SEVERITY_HIGH or blast_radius.affected_devices:
        reasons.append(
            f"Blast radius: {blast_radius.summary} Review each affected "
            "device before the change."
        )
    if redundancy.redundant is None:
        reasons.append(
            "Redundancy is unknown — no alternate path is visible in the "
            "discovered topology and Atlas never assumes one exists."
        )
    elif redundancy.redundant:
        reasons.append(
            "Alternate topology paths absorb this change; impact should be "
            "limited to the changed element itself."
        )
    for prerequisite in rollback.prerequisites:
        reasons.append(f"Before proceeding: {prerequisite}.")
    if not rollback.reversible:
        reasons.append(
            "This change cannot simply be undone — prepare the recovery plan "
            "as part of the change."
        )
    reasons.append(
        f"Risk level {risk.level} (score {risk.score}); see the risk factors "
        "for the arithmetic."
    )

    if management_lost and not management_alternate_verified:
        # Losing manageability outranks everything: an engineer must be
        # able to reach the device to roll back at all.
        action = ACTION_VERIFY_MGMT
    elif risk.level == RISK_CRITICAL or critical_paths:
        action = ACTION_CAB
    elif risk.level == RISK_HIGH and redundancy.redundant is None:
        action = ACTION_INVESTIGATE
    elif risk.level in (RISK_HIGH, RISK_MEDIUM) or touches_links:
        action = ACTION_MAINTENANCE
    else:
        action = ACTION_PROCEED
        if not reasons or len(reasons) == 1:
            reasons.insert(
                0,
                f"No downstream impact is visible for {subject} in the "
                "current evidence; normal change control applies.",
            )
    return Advice(action=action, reasons=tuple(reasons))
