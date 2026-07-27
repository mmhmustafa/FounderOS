"""Search capability: intent registrations (PR-164.1).

Declares DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import IntentDefinition, Workflow

CAPABILITY = "Search"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Device Lookup", key="device-lookup",
        description="Find one device and what Atlas knows about it.",
        engine="search", domain="inventory", capability=CAPABILITY,
        # Moved verbatim from the old static table.
        routing_phrases=(
            "find", "search", "where is", "show me", "look up", "locate",
        ),
        routing_priority=100,
        default_for_engine=True,
        examples=("Find SW2", "Where is 10.0.9.9?"),
        required_evidence=("Evidence Index", "Enterprise Graph"),
        workflows=(
            Workflow("Open Evidence", "/evidence",
                     "Every stored artifact for the device."),
        ),
        recommendations=(),
        followups=(),
        confidence_rule="High on a lookup phrase.",
    ))
    registry.register(IntentDefinition(
        name="Interface Investigation", key="interface-investigation",
        description="One interface's state and evidence.",
        engine="search", domain="inventory", capability=CAPABILITY,
        examples=("Find eth2 on chennai-core",),
        required_evidence=("Evidence Index", "Interface Inventory"),
        workflows=(
            Workflow("Open Evidence", "/evidence",
                     "Interface facts come from stored device evidence."),
        ),
        recommendations=(),
        followups=(),
        refine_keywords=("interface", "port ", "eth", "gi0", "ge-"),
        confidence_rule="High on a lookup phrase naming an interface.",
    ))
    registry.register(IntentDefinition(
        name="Evidence Lookup", key="evidence-lookup",
        description="Find a stored evidence artifact.",
        engine="search", domain="evidence", capability=CAPABILITY,
        examples=("Find the evidence for chennai-core",),
        required_evidence=("Evidence Index",),
        workflows=(
            Workflow("Open Evidence Explorer", "/evidence",
                     "Search and open every stored artifact."),
        ),
        recommendations=(),
        followups=(),
        refine_keywords=("evidence", "artifact"),
        confidence_rule="High on a lookup phrase mentioning evidence.",
    ))
