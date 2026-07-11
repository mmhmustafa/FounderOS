"""Redundancy model: does an alternate path exist?

The assessment is a first-class model with confidence — future engines
(routing tables, LACP/HSRP awareness, WAN/SD-WAN policies) will refine
*how* redundancy is established; the model and its consumers stay put.
The first evaluation answers the topology-layer question honestly:
reachability with the changed node removed from the dependency graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .dependency import DependencyGraph


@dataclass(frozen=True)
class RedundancyAssessment:
    redundant: bool | None            # None = unknown (not enough evidence)
    alternate_path_exists: bool
    detail: str
    confidence_band: str = "medium"   # topology-only evidence is medium

    def to_dict(self) -> dict[str, Any]:
        return {
            "redundant": self.redundant,
            "alternate_path_exists": self.alternate_path_exists,
            "detail": self.detail,
            "confidence_band": self.confidence_band,
        }


def assess_redundancy(
    graph: DependencyGraph,
    from_id: str,
    to_id: str,
    *,
    removed: frozenset[str] = frozenset(),
) -> RedundancyAssessment:
    """Topology-layer redundancy: reachability without the removed nodes."""

    alternate = graph.path_exists(from_id, to_id, without=removed)
    if alternate:
        return RedundancyAssessment(
            redundant=True,
            alternate_path_exists=True,
            detail="an alternate topology path exists without the changed element",
        )
    # Atlas can verify redundancy, but it cannot verify its ABSENCE —
    # undiscovered links may exist. Never assume; say Unknown.
    return RedundancyAssessment(
        redundant=None,
        alternate_path_exists=False,
        detail=(
            "no alternate path is known in the discovered topology; "
            "redundancy is unknown, not assumed"
        ),
    )
