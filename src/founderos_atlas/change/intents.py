"""Change Intelligence capability: intent registrations (PR-164.1).

Declares DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import (
    FollowUpSeed,
    IntentDefinition,
    Workflow,
)

CAPABILITY = "Change Intelligence"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Change Analysis", key="change-analysis",
        description="What changed in the estate, and where.",
        engine="changes", domain="timeline", capability=CAPABILITY,
        # Moved verbatim from the old static table.
        routing_phrases=(
            "what changed", "changed today", "changed overnight",
            "changed since", "recent changes", "any changes", "changes",
        ),
        routing_priority=50,
        default_for_engine=True,
        examples=("What changed yesterday?", "Any changes overnight?"),
        required_evidence=("Change Timeline", "Configuration Memory"),
        workflows=(
            Workflow("Review Changes", "/changes",
                     "Every recorded change with its evidence."),
        ),
        recommendations=(
            Workflow("Open Timeline", "/timeline",
                     "The same changes in time order, across the estate."),
        ),
        followups=(
            FollowUpSeed("Is everything healthy?", "Is everything healthy?"),
        ),
        confidence_rule="High on a change phrase.",
    ))
    registry.register(IntentDefinition(
        name="Timeline Review", key="timeline-review",
        description="The estate's history in time order.",
        engine="changes", domain="timeline", capability=CAPABILITY,
        examples=("Show the timeline",),
        required_evidence=("Change Timeline", "Discovery History"),
        workflows=(
            Workflow("Open Timeline", "/timeline",
                     "The chronological view of everything recorded."),
        ),
        recommendations=(),
        followups=(FollowUpSeed("What changed?", "What changed?"),),
        refine_keywords=("timeline", "history of"),
        fallback_keywords=("timeline",),
        confidence_rule="High on an explicit timeline phrase.",
    ))
    registry.register(IntentDefinition(
        name="Configuration Comparison", key="configuration-comparison",
        description="How a configuration differs between versions.",
        engine="changes", domain="configuration", capability=CAPABILITY,
        examples=("Compare configurations", "Compare config versions"),
        required_evidence=("Configuration Memory",),
        workflows=(
            Workflow("Open Configuration", "/configuration",
                     "Every stored version, diffable side by side."),
        ),
        recommendations=(),
        followups=(FollowUpSeed("What changed?", "What changed?"),),
        refine_keywords=("config",),
        fallback_keywords=("compare config", "compare configuration"),
        confidence_rule="High on a change phrase mentioning configs; "
                        "Medium when inferred from 'compare config'.",
    ))
    registry.register(IntentDefinition(
        name="Configuration Review", key="configuration-review",
        description="Read a device's stored configuration.",
        engine="search", domain="configuration", capability=CAPABILITY,
        examples=("Show me the config of SW2",),
        required_evidence=("Configuration Memory",),
        workflows=(
            Workflow("Open Configuration", "/configuration",
                     "Stored configurations with history and search."),
        ),
        recommendations=(),
        followups=(FollowUpSeed("Compare versions",
                                "Compare configurations"),),
        refine_keywords=("config",),
        confidence_rule="High on a lookup phrase mentioning configuration.",
    ))
