"""Health capability: operational intent registrations (PR-164.1).

Owned here, consumed by the Operational Intent Router. This module
declares DATA only — phrases, workflows, evidence — and may import
nothing but the OIR contract.
"""

from __future__ import annotations

from founderos_atlas.oir.registry import (
    FollowUpSeed,
    IntentDefinition,
    Workflow,
)

CAPABILITY = "Health"


def register(registry) -> None:
    registry.register(IntentDefinition(
        name="Enterprise Health", key="enterprise-health",
        description="Overall operational state of the whole estate.",
        engine="health", domain="health", capability=CAPABILITY,
        # The direct health phrases, moved verbatim from the old static
        # table (PR-043.8 / PR-043.10 wordings preserved exactly).
        routing_phrases=(
            "health", "healthy", "how is the enterprise",
            "how is the network", "status of the enterprise",
            "problem", "problems", "any issue", "issues", "anything wrong",
            "what's wrong", "whats wrong", "is anything wrong",
            "any concern",
            "is the network fine", "network fine", "is everything fine",
            "everything fine", "is everything ok", "everything ok",
            "everything okay", "all good", "is it healthy",
            "is everything healthy",
            "anything critical", "any critical", "is anything critical",
            "any risk", "any risks", "are there risks",
            "what are the risks",
            "top risks", "how is ", "how healthy", "is it okay", "is it ok",
            "is it fine", "any alerts", "anything to worry",
            "should i worry",
        ),
        routing_priority=60,
        default_for_engine=True,
        examples=("Is the network healthy?", "Explain enterprise health"),
        required_evidence=("Enterprise Graph", "Change Timeline",
                           "Incident Signals"),
        workflows=(
            Workflow("View Enterprise Health", "/?scope=all",
                     "The health overview shows every dimension this "
                     "verdict came from."),
            Workflow("Open Incidents", "/incidents",
                     "Active incidents are the fastest path to what is "
                     "wrong."),
        ),
        recommendations=(
            Workflow("Open Topology", "/topology",
                     "See the estate the health verdict describes."),
        ),
        followups=(
            FollowUpSeed("Show unhealthy devices", "Show unhealthy devices"),
            FollowUpSeed("What changed yesterday?", "What changed yesterday?"),
        ),
        confidence_rule="High on a direct health phrase; the site variant "
                        "wins when a known site is named.",
    ))
    registry.register(IntentDefinition(
        name="Site Health", key="site-health",
        description="Operational state of one named site.",
        engine="health", domain="health", capability=CAPABILITY,
        examples=("Is Mumbai healthy?", "How is the Delhi site?"),
        required_evidence=("Enterprise Graph", "Site Membership"),
        workflows=(
            Workflow("Open Topology", "/topology",
                     "Focus the named site to see its devices and links."),
        ),
        recommendations=(
            Workflow("Open Incidents", "/incidents",
                     "Check whether the site has active incidents."),
        ),
        followups=(
            FollowUpSeed("Show recent changes", "What changed?"),
        ),
        refine_entities=("site",),  # a named known site, not keywords
        confidence_rule="High when the question names a known site.",
    ))
