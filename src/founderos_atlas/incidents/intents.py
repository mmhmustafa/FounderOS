"""Incidents capability: intent registrations (PR-164.1).

Declares DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import (
    FollowUpSeed,
    IntentDefinition,
    Workflow,
)

CAPABILITY = "Incidents"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Incident Investigation", key="incident-investigation",
        description="Investigate an active or recorded incident.",
        engine="investigation", domain="incident", capability=CAPABILITY,
        # Moved verbatim from the old static table.
        routing_phrases=(
            "investigation summary", "summarize investigation",
            "last investigation", "latest investigation", "investigations",
            "investigation",
        ),
        routing_priority=80,
        default_for_engine=True,
        examples=("Summarize the last investigation",),
        required_evidence=("Investigation History", "Incident Cases"),
        workflows=(
            Workflow("Open Incidents", "/incidents",
                     "Active and resolved cases with their evidence."),
            Workflow("Open Investigations", "/paths",
                     "Path investigations and their verdicts."),
        ),
        recommendations=(),
        followups=(FollowUpSeed("Is everything healthy?",
                                "Is everything healthy?"),),
        fallback_keywords=("incident",),
        confidence_rule="High on an investigation phrase; Medium when "
                        "inferred from 'incident'.",
    ))
