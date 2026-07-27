"""Enterprise Knowledge capability: intent registrations (PR-164.1).

Declares DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import (
    FollowUpSeed,
    IntentDefinition,
    Workflow,
)

CAPABILITY = "Enterprise Knowledge"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Inventory", key="inventory",
        description="What the estate contains, by the numbers.",
        engine="enterprise", domain="inventory", capability=CAPABILITY,
        # Moved verbatim from the old static table.
        routing_phrases=(
            "enterprise summary", "summarize the enterprise",
            "summarize enterprise", "inventory", "how many devices",
            "what is my enterprise",
        ),
        routing_priority=90,
        default_for_engine=True,
        examples=("How many devices do we have?",
                  "Summarize the enterprise"),
        required_evidence=("Enterprise Graph",),
        workflows=(
            Workflow("Open Topology", "/topology",
                     "The estate drawn whole."),
        ),
        recommendations=(),
        followups=(FollowUpSeed("Is everything healthy?",
                                "Is everything healthy?"),),
        confidence_rule="High on an inventory phrase.",
    ))
