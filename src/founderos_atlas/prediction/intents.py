"""Prediction capability: intent registrations (PR-164.1).

Declares DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import (
    FollowUpSeed,
    IntentDefinition,
    Workflow,
)

CAPABILITY = "Prediction"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Risk Assessment", key="risk-assessment",
        description="What would break if a device or link changed.",
        engine="prediction", domain="maintenance", capability=CAPABILITY,
        # Moved verbatim from the old static table.
        routing_phrases=(
            "what happens if", "what would happen", "predict", "impact of",
            "blast radius", "if i disable", "if i shut", "if we disable",
            "if we shut", "if i reboot", "if i upgrade",
        ),
        routing_priority=20,
        default_for_engine=True,
        examples=("Can I reboot Core1?", "What happens if I disable Gi0/1?"),
        required_evidence=("Topology", "Routing Tables"),
        workflows=(
            Workflow("Open Predict", "/predict",
                     "The full impact analysis for the modelled change."),
        ),
        recommendations=(
            Workflow("Plan it in Compass", "/compass",
                     "Turn the assessment into a maintenance plan."),
        ),
        followups=(
            FollowUpSeed("Plan maintenance", "Help me plan maintenance"),
        ),
        # "Can I reboot X?" carries no what-if phrase; these
        # deterministic shapes route it to a real impact prediction
        # (the prediction engine parses the reboot/upgrade target).
        fallback_keywords=("can i reboot", "can i shut", "can i shutdown",
                           "can i upgrade", "can i reload", "can i replace",
                           "safe to reboot", "safe to shut",
                           "safe to upgrade", "is it safe to"),
        confidence_rule="High on a what-if phrase; Medium when inferred "
                        "from a can-I-safely shape.",
    ))
