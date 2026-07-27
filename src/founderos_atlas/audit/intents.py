"""Audit capability: intent registrations (PR-164.1).

Owns security-posture questions: Atlas answers them from policy
judgements and the audit trail — the evidence this capability holds.
Declares DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import IntentDefinition, Workflow

CAPABILITY = "Audit"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Security Investigation", key="security-investigation",
        description="Security posture and rule questions.",
        engine="unknown", domain="security", capability=CAPABILITY,
        examples=("Any security violations?",),
        required_evidence=("Policy Engine Results", "Audit Log"),
        workflows=(
            Workflow("Review Policy", "/policy",
                     "Declared security policy and every judgement."),
            Workflow("Open Audit", "/audit",
                     "Who did what, when, across the estate."),
        ),
        recommendations=(),
        followups=(),
        fallback_keywords=("security", "firewall rule", "threat",
                           "breach"),
        confidence_rule="Medium — inferred from security keywords.",
        limitations=("Firewall rule contents are only visible where "
                     "configuration collection reached the firewall.",),
    ))
