"""Path Intelligence capability: intent registrations (PR-164.1).

Owns connectivity questions and investigation continuation. Declares
DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import (
    FollowUpSeed,
    IntentDefinition,
    Workflow,
)

CAPABILITY = "Path Intelligence"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Connectivity Validation", key="connectivity-validation",
        description="Whether one endpoint can reach another, and how.",
        engine="path", domain="connectivity", capability=CAPABILITY,
        # Moved verbatim from the old static table.
        routing_phrases=(
            "cannot reach", "can't reach", "cant reach", "unable to reach",
            "not reachable", "unreachable from", "reach", "connectivity",
            "path from", "path between", "path to",
        ),
        routing_priority=30,
        default_for_engine=True,
        examples=("Can Mumbai reach Chennai?", "A1 cannot reach B1"),
        required_evidence=("Topology", "Routing Tables", "Path Policies"),
        workflows=(
            Workflow("Open Path Intelligence", "/paths",
                     "The full investigation with every hop and verdict."),
        ),
        recommendations=(
            Workflow("View Topology", "/topology",
                     "See the links the path rides on."),
            Workflow("Compare with yesterday", "/changes",
                     "If this worked before, the change history says what "
                     "moved."),
        ),
        followups=(
            FollowUpSeed("Compare yesterday", "What changed?"),
        ),
        confidence_rule="High on a reachability phrase.",
    ))
    registry.register(IntentDefinition(
        name="Resume Investigation", key="resume-investigation",
        description="Pick up the most recent unfinished work.",
        engine="continue", domain="incident", capability=CAPABILITY,
        routing_phrases=("continue", "resume", "pick up where"),
        routing_priority=10,
        default_for_engine=True,
        examples=("Continue yesterday's investigation",),
        required_evidence=("Investigation History",),
        workflows=(
            Workflow("Open Investigations", "/paths",
                     "Recent investigations, resumable where they "
                     "stopped."),
        ),
        recommendations=(),
        followups=(),
        confidence_rule="High on a continue/resume phrase.",
    ))
