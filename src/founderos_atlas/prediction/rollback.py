"""Rollback model: how hard is it to get back?

Every prediction carries a rollback estimate — complexity band,
prerequisites, dependencies, recovery effort, and confidence. The first
estimator is rule-based per change type (an interface shutdown reverses
with one command; a firmware upgrade does not reverse at all without the
previous image); future estimators can weigh captured configuration
snapshots and platform specifics without changing the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .change_requests import change_type
from .models import ChangeRequest


COMPLEXITY_TRIVIAL = "trivial"
COMPLEXITY_LOW = "low"
COMPLEXITY_MODERATE = "moderate"
COMPLEXITY_HIGH = "high"
COMPLEXITY_UNKNOWN = "unknown"


@dataclass(frozen=True)
class RollbackEstimate:
    complexity: str
    reversible: bool
    confidence_band: str
    prerequisites: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    estimated_effort: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "complexity": self.complexity,
            "reversible": self.reversible,
            "confidence_band": self.confidence_band,
            "prerequisites": list(self.prerequisites),
            "dependencies": list(self.dependencies),
            "estimated_effort": self.estimated_effort,
        }


def estimate_rollback(
    request: ChangeRequest, *, configuration_captured: bool = False
) -> RollbackEstimate:
    spec = change_type(request.change_type)
    if request.change_type == "shutdown-interface":
        return RollbackEstimate(
            complexity=COMPLEXITY_TRIVIAL,
            reversible=True,
            confidence_band="high",
            prerequisites=("management access to the device",),
            estimated_effort="one command: 'no shutdown' on the interface",
        )
    if request.change_type in ("delete-route", "remove-vlan", "modify-acl", "disable-protocol"):
        prerequisites = ["management access to the device"]
        if configuration_captured:
            complexity, band = COMPLEXITY_LOW, "high"
            prerequisites.append(
                "the previous configuration is captured in Atlas history"
            )
        else:
            complexity, band = COMPLEXITY_MODERATE, "medium"
            prerequisites.append(
                "capture the current configuration BEFORE the change "
                "(enable configuration collection)"
            )
        return RollbackEstimate(
            complexity=complexity,
            reversible=True,
            confidence_band=band,
            prerequisites=tuple(prerequisites),
            estimated_effort="restore the removed statements from the captured configuration",
        )
    if request.change_type == "reboot-device":
        return RollbackEstimate(
            complexity=COMPLEXITY_MODERATE,
            reversible=False,
            confidence_band="high",
            prerequisites=("console or out-of-band access in case the device does not return",),
            estimated_effort="a reboot cannot be undone; recovery means waiting or intervening out-of-band",
        )
    if request.change_type == "upgrade-firmware":
        return RollbackEstimate(
            complexity=COMPLEXITY_HIGH,
            reversible=False,
            confidence_band="medium",
            prerequisites=(
                "the previous image retained on the device or a file server",
                "a maintenance window sized for a second reload",
                "console or out-of-band access",
            ),
            dependencies=("boot configuration", "image storage"),
            estimated_effort="reinstall the previous image and reload — a full second maintenance operation",
        )
    return RollbackEstimate(
        complexity=COMPLEXITY_UNKNOWN,
        reversible=bool(spec.reversible_by_default) if spec else False,
        confidence_band="low",
        prerequisites=("model this change type to estimate rollback",),
        estimated_effort="unknown — this change type has no rollback rules yet",
    )
