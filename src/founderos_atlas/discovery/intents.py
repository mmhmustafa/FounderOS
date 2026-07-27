"""Discovery capability: intent registrations (PR-164.1).

Declares DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import (
    FollowUpSeed,
    IntentDefinition,
    Workflow,
)

CAPABILITY = "Discovery"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Discovery Health", key="discovery-health",
        description="Coverage and freshness of what Atlas has discovered.",
        engine="discovery", domain="discovery", capability=CAPABILITY,
        # Moved verbatim from the old static table. ("resume discovery"
        # stays for completeness; the continue phrases fire first at
        # priority 10, exactly as the fixed table always behaved.)
        routing_phrases=(
            "run discovery", "run a discovery", "start discovery",
            "resume discovery", "discover ", "scan ", "onboard",
            "summarize discovery", "discovery summary", "last discovery",
            "latest discovery", "discovery", "discovered",
        ),
        routing_priority=70,
        default_for_engine=True,
        examples=("Summarize discovery", "When did discovery last run?"),
        required_evidence=("Discovery History",),
        workflows=(
            Workflow("Open Discovery", "/discovery",
                     "Run, resume, or review discovery for any network."),
        ),
        recommendations=(
            Workflow("Open History", "/history",
                     "Every archived run with its results."),
        ),
        followups=(FollowUpSeed("Is everything healthy?",
                                "Is everything healthy?"),),
        confidence_rule="High on a discovery phrase.",
    ))
