"""Platform-owned registrations (PR-164.1).

Only the honest fallback lives here: the Unknown intent belongs to the
router itself, because "no capability claims this question" is a
platform fact, not a capability's.
"""

from __future__ import annotations

from .registry import IntentDefinition, Workflow

CAPABILITY = "Atlas Platform"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Unknown", key="unknown",
        description="No operational pattern matched.",
        engine="unknown", domain="unknown", capability=CAPABILITY,
        default_for_engine=True,
        examples=(),
        required_evidence=(),
        workflows=(
            Workflow("Run Discovery", "/discovery",
                     "More evidence is the honest way to more answers."),
        ),
        recommendations=(),
        followups=(),
        confidence_rule="Unknown — Atlas will not guess.",
    ))
