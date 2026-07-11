"""Advice derived from a prediction — deterministic, CAB-meeting ready."""

from __future__ import annotations

from .critical_paths import CriticalPath
from .impact import BlastRadius
from .models import SEVERITY_HIGH
from .redundancy import RedundancyAssessment
from .rollback import RollbackEstimate


def recommend(
    *,
    blast_radius: BlastRadius,
    critical_paths: tuple[CriticalPath, ...],
    redundancy: RedundancyAssessment,
    rollback: RollbackEstimate,
    subject: str,
) -> tuple[str, ...]:
    lines: list[str] = []
    if critical_paths:
        pairs = ", ".join(
            f"{path.hops[0]}–{path.hops[-1]}" for path in critical_paths[:3]
        )
        lines.append(
            f"Connectivity will break between {pairs}; schedule a maintenance "
            "window and notify the affected teams before proceeding."
        )
    elif redundancy.redundant:
        lines.append(
            "Alternate topology paths absorb this change; impact should be "
            "limited to the changed element itself."
        )
    if blast_radius.severity == SEVERITY_HIGH:
        lines.append(
            f"High blast radius: {blast_radius.summary} Review each affected "
            "device before the change."
        )
    for prerequisite in rollback.prerequisites:
        lines.append(f"Before proceeding: {prerequisite}.")
    if not rollback.reversible:
        lines.append(
            "This change cannot simply be undone — prepare the recovery plan "
            "as part of the change, not after it."
        )
    if not lines:
        lines.append(
            f"No downstream impact is visible for {subject} in the current "
            "evidence; proceed with normal change control."
        )
    return tuple(lines)
