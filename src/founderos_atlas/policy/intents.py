"""Policy capability: intent registrations (PR-164.1).

Declares DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import (
    FollowUpSeed,
    IntentDefinition,
    Workflow,
)

CAPABILITY = "Policy"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Policy Compliance", key="policy-compliance",
        description="How the estate measures against declared policy.",
        engine="health", domain="policy", capability=CAPABILITY,
        examples=("Are we policy compliant?", "Show policy violations"),
        required_evidence=("Policy Engine Results",),
        workflows=(
            Workflow("Review Policy", "/policy",
                     "The policy page lists every judgement and "
                     "violation."),
        ),
        recommendations=(
            Workflow("Open Audit", "/audit",
                     "Policy changes and exceptions are audited."),
        ),
        followups=(FollowUpSeed("What changed?", "What changed?"),),
        refine_keywords=("policy", "compliance", "violation"),
        fallback_keywords=("policy", "compliance", "violation"),
        confidence_rule="High on an explicit policy phrase; Medium when "
                        "inferred from the keyword alone.",
    ))
