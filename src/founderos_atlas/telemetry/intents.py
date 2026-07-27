"""Telemetry capability: intent registrations (PR-164.1).

Owns performance questions — honestly bounded, because Atlas holds no
performance telemetry unless an adapter is configured. Declares DATA
only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import (
    FollowUpSeed,
    IntentDefinition,
    Workflow,
)

CAPABILITY = "Telemetry"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Performance Investigation", key="performance-investigation",
        description="Latency, load, or slowness questions.",
        engine="unknown", domain="performance", capability=CAPABILITY,
        examples=("Why is SAP slow?",),
        required_evidence=("Operational Telemetry",),
        workflows=(
            Workflow("Open Timeline", "/timeline",
                     "Recent changes are the first suspect for new "
                     "slowness."),
            Workflow("Open Path Intelligence", "/paths",
                     "Verify the path the application rides on."),
        ),
        recommendations=(),
        followups=(
            FollowUpSeed("What changed?", "What changed?"),
        ),
        fallback_keywords=("slow", "latency", "performance", "cpu",
                           "memory"),
        confidence_rule="Medium — inferred from performance keywords; "
                        "Atlas holds no performance telemetry unless an "
                        "adapter is configured.",
        limitations=("Atlas holds no performance telemetry unless a "
                     "telemetry adapter is configured; it can show the "
                     "path and the change history, not utilisation.",),
    ))
