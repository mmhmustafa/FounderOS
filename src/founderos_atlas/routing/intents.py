"""Routing Intelligence capability: intent registrations (PR-164.1).

Declares DATA only; imports nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import (
    FollowUpSeed,
    IntentDefinition,
    Workflow,
)

CAPABILITY = "Routing Intelligence"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Configuration Validation",
        key="configuration-validation",
        description="Judge a subject's configuration against the "
                    "enterprise's policy rules — pass, fail, warning, "
                    "not applicable and unknown per device. ONE intent "
                    "for every subject (PR-172): the intent says what "
                    "SHAPE of answer (a validation), the subject "
                    "registry says what it is about, and the two axes "
                    "never multiply.",
        engine="health", domain="configuration", capability="Policy",
        # PR-171: the objective is the second dispatch axis; dispatch
        # reads (engine, objective), so validation questions reach the
        # validate handler instead of the enterprise summary.
        objective="validate",
        examples=("Is all the OSPF configuration fine across the "
                  "enterprise?",
                  "Is the BGP configuration compliant?",
                  "Is OSPF configured correctly?"),
        required_evidence=("Policy Engine Results", "Configuration Memory"),
        workflows=(
            Workflow("Open Policy", "/policy",
                     "The policy page holds every evaluation this "
                     "verdict is built from."),
        ),
        recommendations=(
            Workflow("Open Configuration", "/configuration",
                     "The collected configurations the policies "
                     "judged."),
        ),
        followups=(
            FollowUpSeed("Show recent changes", "What changed?"),
            FollowUpSeed("Open policy results", "Show policy compliance"),
        ),
        # SUBJECT-FREE validation wording, deliberately: the subject
        # comes from extraction, never from routing keywords. Each
        # keyword pairs configuration context with a judgement word (or
        # is self-contained, like "misconfigured"), so a lookup —
        # "Show me the OSPF configuration" — never lands here. This
        # intent registers FIRST in this module because fallback ties
        # break toward the earlier registration: a question carrying
        # validation wording AND a protocol name ("is the BGP
        # configuration compliant?") must be a validation, not a
        # protocol investigation.
        fallback_keywords=("configuration fine", "configuration correct",
                           "configuration compliant", "configuration ok",
                           "configured correctly", "correctly configured",
                           "config fine", "config compliant",
                           "misconfigured"),
        confidence_rule="Medium — reached by validation keywords, since "
                        "no direct routing phrase claims configuration "
                        "wording estate-wide.",
        limitations=("Validation covers the subjects the active policy "
                     "pack carries rules for; a subject with no rules is "
                     "refused, never passed.",),
    ))
    registry.register(IntentDefinition(
        name="Routing Investigation", key="routing-investigation",
        description="State of the routed control plane as observed.",
        engine="health", domain="routing", capability=CAPABILITY,
        examples=("Show routing health", "Is routing stable?"),
        required_evidence=("Enterprise Graph", "Routing Observations"),
        workflows=(
            Workflow("Open Topology (routing views)", "/topology",
                     "The OSPF and BGP views draw the observed "
                     "adjacencies."),
        ),
        recommendations=(
            Workflow("Review Changes", "/changes",
                     "Routing trouble usually follows a change."),
        ),
        followups=(
            FollowUpSeed("Show BGP", "Show me BGP"),
            FollowUpSeed("Show OSPF", "Show me OSPF"),
        ),
        refine_keywords=("routing", "route ", "routes"),
        fallback_keywords=("routing",),
        confidence_rule="High on an explicit routing phrase; Medium when "
                        "inferred from routing keywords alone.",
    ))
    registry.register(IntentDefinition(
        name="BGP Investigation", key="bgp-investigation",
        description="Observed BGP sessions and their stability.",
        engine="health", domain="routing", capability=CAPABILITY,
        examples=("Why is BGP unstable?", "Is BGP healthy?"),
        required_evidence=("Enterprise Graph", "BGP Observations"),
        workflows=(
            Workflow("Open BGP view", "/topology?view=bgp",
                     "The BGP view draws every observed session and AS."),
        ),
        recommendations=(
            Workflow("Review Changes", "/changes",
                     "A flapping session often follows a config change."),
        ),
        followups=(
            FollowUpSeed("Show recent changes", "What changed?"),
            FollowUpSeed("Show OSPF", "Show me OSPF"),
        ),
        refine_keywords=("bgp",),
        fallback_keywords=("bgp",),
        confidence_rule="High on a health phrase mentioning BGP; Medium "
                        "when inferred from the keyword alone.",
    ))
    registry.register(IntentDefinition(
        name="OSPF Investigation", key="ospf-investigation",
        description="Observed OSPF adjacencies and areas.",
        engine="health", domain="routing", capability=CAPABILITY,
        examples=("Is OSPF healthy?", "OSPF adjacency status"),
        required_evidence=("Enterprise Graph", "OSPF Observations"),
        workflows=(
            Workflow("Open OSPF view", "/topology?view=ospf",
                     "The OSPF view draws every observed adjacency and "
                     "area."),
        ),
        recommendations=(
            Workflow("Review Changes", "/changes",
                     "Adjacency loss usually follows a change."),
        ),
        followups=(
            FollowUpSeed("Show BGP", "Show me BGP"),
            FollowUpSeed("Show recent changes", "What changed?"),
        ),
        refine_keywords=("ospf",),
        fallback_keywords=("ospf",),
        confidence_rule="High on a health phrase mentioning OSPF; Medium "
                        "when inferred from the keyword alone.",
    ))
    registry.register(IntentDefinition(
        name="WAN Investigation", key="wan-investigation",
        description="State of the wide-area fabric between sites.",
        engine="health", domain="routing", capability=CAPABILITY,
        examples=("Is the WAN healthy?",),
        required_evidence=("Enterprise Graph", "Inter-site Links"),
        workflows=(
            Workflow("Open Topology", "/topology",
                     "The site overview shows the WAN fabric and its "
                     "links."),
        ),
        recommendations=(),
        followups=(FollowUpSeed("Show routing health",
                                "Show routing health"),),
        refine_keywords=("wan",),
        confidence_rule="High on a health phrase mentioning the WAN.",
    ))
    registry.register(IntentDefinition(
        name="LAN Investigation", key="lan-investigation",
        description="State of a local switching domain.",
        engine="health", domain="routing", capability=CAPABILITY,
        examples=("Is the LAN healthy?",),
        required_evidence=("Enterprise Graph", "Switch Inventory"),
        workflows=(
            Workflow("Open Topology", "/topology",
                     "Open the site to see its switching layer."),
        ),
        recommendations=(),
        followups=(),
        refine_keywords=("lan", "vlan", "switch"),
        confidence_rule="High on a health phrase mentioning the LAN.",
    ))
