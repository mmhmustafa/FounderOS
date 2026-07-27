"""Compass (maintenance) capability: intent registrations (PR-164.1).

Declares DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import (
    FollowUpSeed,
    IntentDefinition,
    Workflow,
)

CAPABILITY = "Compass"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Maintenance Planning", key="maintenance-planning",
        description="Plan a change window with its risks understood.",
        engine="compass", domain="maintenance", capability=CAPABILITY,
        # Moved verbatim from the old static table.
        routing_phrases=(
            "maintenance", "plan a change", "help me plan", "plan tonight",
            "change window", "maintenance window", "execution order",
        ),
        routing_priority=40,
        default_for_engine=True,
        examples=("Help me plan maintenance", "Plan a change window"),
        required_evidence=("Maintenance Plans", "Topology"),
        workflows=(
            Workflow("Open Compass", "/compass",
                     "Plans, dependencies, readiness, and execution "
                     "order."),
        ),
        recommendations=(
            Workflow("Run a Prediction", "/predict",
                     "Model the impact before the window."),
        ),
        followups=(FollowUpSeed("What are the risks?",
                                "What are the risks?"),),
        confidence_rule="High on a maintenance phrase.",
    ))
