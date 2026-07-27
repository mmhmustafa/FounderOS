"""Identity Resolution capability: intent registrations (PR-164.1).

Declares DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import IntentDefinition, Workflow

CAPABILITY = "Identity Resolution"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Identity Resolution", key="identity-resolution",
        description="Duplicate or conflicting device identities.",
        engine="enterprise", domain="identity", capability=CAPABILITY,
        examples=("Resolve duplicate devices", "Any identity conflicts?"),
        required_evidence=("Enterprise Graph", "Identity Conflicts"),
        workflows=(
            Workflow("Open Resolution Center", "/evidence/resolution-center",
                     "Review and resolve every identity conflict with its "
                     "provenance."),
        ),
        recommendations=(),
        followups=(),
        refine_keywords=("identity", "duplicate", "conflict"),
        fallback_keywords=("identity", "duplicate", "resolve"),
        confidence_rule="High on an enterprise phrase about identity; "
                        "Medium when inferred from the keywords alone.",
    ))
