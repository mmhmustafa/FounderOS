"""The built-in operational intent catalog (PR-164, INTENT).

Two layers of deterministic knowledge live here:

1. ``ENGINE_RULES`` — the fixed-order phrase table that maps a question
   onto an ANSWERING ENGINE. This is the exact table the Advisor router
   has always used, moved here so there is one source of truth; the
   Advisor's ``classify()`` now delegates to it (Part 12: one
   orchestration engine).

2. The intent catalog — every operational intent Atlas understands,
   registered with the evidence it needs, the workflows that serve it,
   why each is suggested, and its honest limitations. Detection refines
   an engine family into one of these intents using declared keywords
   and known entities; it never guesses.
"""

from __future__ import annotations

from .registry import FollowUpSeed, IntentDefinition, IntentRegistry, Workflow


ENGINE_HEALTH = "health"
ENGINE_CHANGES = "changes"
ENGINE_DISCOVERY = "discovery"
ENGINE_PATH = "path"
ENGINE_PREDICTION = "prediction"
ENGINE_COMPASS = "compass"
ENGINE_CONTINUE = "continue"
ENGINE_SEARCH = "search"
ENGINE_ENTERPRISE = "enterprise"
ENGINE_INVESTIGATION = "investigation"
ENGINE_UNKNOWN = "unknown"


# Fixed-order rules: the FIRST match wins, deterministically. Each rule
# is (engine, tuple of phrases); a phrase matches as a substring of the
# casefolded question. Moved verbatim from advisor/router.py — the
# pinned routing behaviour every existing test asserts.
ENGINE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ENGINE_CONTINUE, ("continue", "resume", "pick up where")),
    (ENGINE_PREDICTION, (
        "what happens if", "what would happen", "predict", "impact of",
        "blast radius", "if i disable", "if i shut", "if we disable",
        "if we shut", "if i reboot", "if i upgrade",
    )),
    (ENGINE_PATH, (
        "cannot reach", "can't reach", "cant reach", "unable to reach",
        "not reachable", "unreachable from", "reach", "connectivity",
        "path from", "path between", "path to",
    )),
    (ENGINE_COMPASS, (
        "maintenance", "plan a change", "help me plan", "plan tonight",
        "change window", "maintenance window", "execution order",
    )),
    (ENGINE_CHANGES, (
        "what changed", "changed today", "changed overnight",
        "changed since", "recent changes", "any changes", "changes",
    )),
    (ENGINE_HEALTH, (
        "health", "healthy", "how is the enterprise", "how is the network",
        "status of the enterprise",
        "problem", "problems", "any issue", "issues", "anything wrong",
        "what's wrong", "whats wrong", "is anything wrong", "any concern",
        "is the network fine", "network fine", "is everything fine",
        "everything fine", "is everything ok", "everything ok",
        "everything okay", "all good", "is it healthy", "is everything healthy",
        "anything critical", "any critical", "is anything critical",
        "any risk", "any risks", "are there risks", "what are the risks",
        "top risks", "how is ", "how healthy", "is it okay", "is it ok",
        "is it fine", "any alerts", "anything to worry", "should i worry",
    )),
    (ENGINE_DISCOVERY, (
        "run discovery", "run a discovery", "start discovery",
        "resume discovery", "discover ", "scan ", "onboard",
        "summarize discovery", "discovery summary", "last discovery",
        "latest discovery", "discovery", "discovered",
    )),
    (ENGINE_INVESTIGATION, (
        "investigation summary", "summarize investigation",
        "last investigation", "latest investigation", "investigations",
        "investigation",
    )),
    (ENGINE_ENTERPRISE, (
        "enterprise summary", "summarize the enterprise",
        "summarize enterprise", "inventory", "how many devices",
        "what is my enterprise",
    )),
    (ENGINE_SEARCH, (
        "find", "search", "where is", "show me", "look up", "locate",
    )),
)


def engine_rule_match(question: str) -> tuple[str, str] | None:
    """(engine, matched phrase) for the first rule hit, else None."""

    folded = " ".join(str(question or "").casefold().split())
    if not folded:
        return None
    for engine, phrases in ENGINE_RULES:
        for phrase in phrases:
            if phrase in folded:
                return engine, phrase
    return None


def _wf(label: str, href: str, why: str) -> Workflow:
    return Workflow(label=label, href=href, why=why)


def _fu(label: str, question: str) -> FollowUpSeed:
    return FollowUpSeed(label=label, question=question)


def build_default_registry() -> IntentRegistry:
    """The built-in catalog. Registration order is the tie-break order."""

    registry = IntentRegistry()

    # -- health family ----------------------------------------------------
    registry.register(IntentDefinition(
        name="Enterprise Health", key="enterprise-health",
        description="Overall operational state of the whole estate.",
        engine=ENGINE_HEALTH, domain="health",
        examples=("Is the network healthy?", "Explain enterprise health"),
        required_evidence=("Enterprise Graph", "Change Timeline",
                           "Incident Signals"),
        workflows=(
            _wf("View Enterprise Health", "/?scope=all",
                "The health overview shows every dimension this verdict "
                "came from."),
            _wf("Open Incidents", "/incidents",
                "Active incidents are the fastest path to what is wrong."),
        ),
        recommendations=(
            _wf("Open Topology", "/topology",
                "See the estate the health verdict describes."),
        ),
        followups=(
            _fu("Show unhealthy devices", "Show unhealthy devices"),
            _fu("What changed yesterday?", "What changed yesterday?"),
        ),
        confidence_rule="High on a direct health phrase; the site variant "
                        "wins when a known site is named.",
    ))
    registry.register(IntentDefinition(
        name="Site Health", key="site-health",
        description="Operational state of one named site.",
        engine=ENGINE_HEALTH, domain="health",
        examples=("Is Mumbai healthy?", "How is the Delhi site?"),
        required_evidence=("Enterprise Graph", "Site Membership"),
        workflows=(
            _wf("Open Topology", "/topology",
                "Focus the named site to see its devices and links."),
        ),
        recommendations=(
            _wf("Open Incidents", "/incidents",
                "Check whether the site has active incidents."),
        ),
        followups=(
            _fu("Show recent changes", "What changed?"),
        ),
        refine_entities=("site",),  # a named known site, not keywords
        confidence_rule="High when the question names a known site.",
    ))
    registry.register(IntentDefinition(
        name="Routing Investigation", key="routing-investigation",
        description="State of the routed control plane as observed.",
        engine=ENGINE_HEALTH, domain="routing",
        examples=("Show routing health", "Is routing stable?"),
        required_evidence=("Enterprise Graph", "Routing Observations"),
        workflows=(
            _wf("Open Topology (routing views)", "/topology",
                "The OSPF and BGP views draw the observed adjacencies."),
        ),
        recommendations=(
            _wf("Review Changes", "/changes",
                "Routing trouble usually follows a change."),
        ),
        followups=(
            _fu("Show BGP", "Show me BGP"),
            _fu("Show OSPF", "Show me OSPF"),
        ),
        refine_keywords=("routing", "route ", "routes"),
        fallback_keywords=("routing",),
        confidence_rule="High on an explicit routing phrase; Medium when "
                        "inferred from routing keywords alone.",
    ))
    registry.register(IntentDefinition(
        name="BGP Investigation", key="bgp-investigation",
        description="Observed BGP sessions and their stability.",
        engine=ENGINE_HEALTH, domain="routing",
        examples=("Why is BGP unstable?", "Is BGP healthy?"),
        required_evidence=("Enterprise Graph", "BGP Observations"),
        workflows=(
            _wf("Open BGP view", "/topology?view=bgp",
                "The BGP view draws every observed session and AS."),
        ),
        recommendations=(
            _wf("Review Changes", "/changes",
                "A flapping session often follows a config change."),
        ),
        followups=(
            _fu("Show recent changes", "What changed?"),
            _fu("Show OSPF", "Show me OSPF"),
        ),
        refine_keywords=("bgp",),
        fallback_keywords=("bgp",),
        confidence_rule="High on a health phrase mentioning BGP; Medium "
                        "when inferred from the keyword alone.",
    ))
    registry.register(IntentDefinition(
        name="OSPF Investigation", key="ospf-investigation",
        description="Observed OSPF adjacencies and areas.",
        engine=ENGINE_HEALTH, domain="routing",
        examples=("Is OSPF healthy?", "OSPF adjacency status"),
        required_evidence=("Enterprise Graph", "OSPF Observations"),
        workflows=(
            _wf("Open OSPF view", "/topology?view=ospf",
                "The OSPF view draws every observed adjacency and area."),
        ),
        recommendations=(
            _wf("Review Changes", "/changes",
                "Adjacency loss usually follows a change."),
        ),
        followups=(
            _fu("Show BGP", "Show me BGP"),
            _fu("Show recent changes", "What changed?"),
        ),
        refine_keywords=("ospf",),
        fallback_keywords=("ospf",),
        confidence_rule="High on a health phrase mentioning OSPF; Medium "
                        "when inferred from the keyword alone.",
    ))
    registry.register(IntentDefinition(
        name="WAN Investigation", key="wan-investigation",
        description="State of the wide-area fabric between sites.",
        engine=ENGINE_HEALTH, domain="routing",
        examples=("Is the WAN healthy?",),
        required_evidence=("Enterprise Graph", "Inter-site Links"),
        workflows=(
            _wf("Open Topology", "/topology",
                "The site overview shows the WAN fabric and its links."),
        ),
        recommendations=(),
        followups=(_fu("Show routing health", "Show routing health"),),
        refine_keywords=("wan",),
        confidence_rule="High on a health phrase mentioning the WAN.",
    ))
    registry.register(IntentDefinition(
        name="LAN Investigation", key="lan-investigation",
        description="State of a local switching domain.",
        engine=ENGINE_HEALTH, domain="routing",
        examples=("Is the LAN healthy?",),
        required_evidence=("Enterprise Graph", "Switch Inventory"),
        workflows=(
            _wf("Open Topology", "/topology",
                "Open the site to see its switching layer."),
        ),
        recommendations=(),
        followups=(),
        refine_keywords=("lan", "vlan", "switch"),
        confidence_rule="High on a health phrase mentioning the LAN.",
    ))
    registry.register(IntentDefinition(
        name="Policy Compliance", key="policy-compliance",
        description="How the estate measures against declared policy.",
        engine=ENGINE_HEALTH, domain="policy",
        examples=("Are we policy compliant?", "Show policy violations"),
        required_evidence=("Policy Engine Results",),
        workflows=(
            _wf("Review Policy", "/policy",
                "The policy page lists every judgement and violation."),
        ),
        recommendations=(
            _wf("Open Audit", "/audit",
                "Policy changes and exceptions are audited."),
        ),
        followups=(_fu("What changed?", "What changed?"),),
        refine_keywords=("policy", "compliance", "violation"),
        fallback_keywords=("policy", "compliance", "violation"),
        confidence_rule="High on an explicit policy phrase; Medium when "
                        "inferred from the keyword alone.",
    ))

    # -- connectivity -----------------------------------------------------
    registry.register(IntentDefinition(
        name="Connectivity Validation", key="connectivity-validation",
        description="Whether one endpoint can reach another, and how.",
        engine=ENGINE_PATH, domain="connectivity",
        examples=("Can Mumbai reach Chennai?", "A1 cannot reach B1"),
        required_evidence=("Topology", "Routing Tables", "Policies on the "
                           "path"),
        workflows=(
            _wf("Open Path Intelligence", "/paths",
                "The full investigation with every hop and verdict."),
        ),
        recommendations=(
            _wf("View Topology", "/topology",
                "See the links the path rides on."),
            _wf("Compare with yesterday", "/changes",
                "If this worked before, the change history says what "
                "moved."),
        ),
        followups=(
            _fu("Compare yesterday", "What changed?"),
        ),
        confidence_rule="High on a reachability phrase.",
    ))

    # -- changes family ---------------------------------------------------
    registry.register(IntentDefinition(
        name="Change Analysis", key="change-analysis",
        description="What changed in the estate, and where.",
        engine=ENGINE_CHANGES, domain="timeline",
        examples=("What changed yesterday?", "Any changes overnight?"),
        required_evidence=("Change Timeline", "Configuration Memory"),
        workflows=(
            _wf("Review Changes", "/changes",
                "Every recorded change with its evidence."),
        ),
        recommendations=(
            _wf("Open Timeline", "/timeline",
                "The same changes in time order, across the estate."),
        ),
        followups=(
            _fu("Is everything healthy?", "Is everything healthy?"),
        ),
        confidence_rule="High on a change phrase.",
    ))
    registry.register(IntentDefinition(
        name="Timeline Review", key="timeline-review",
        description="The estate's history in time order.",
        engine=ENGINE_CHANGES, domain="timeline",
        examples=("Show the timeline",),
        required_evidence=("Change Timeline", "Discovery History"),
        workflows=(
            _wf("Open Timeline", "/timeline",
                "The chronological view of everything recorded."),
        ),
        recommendations=(),
        followups=(_fu("What changed?", "What changed?"),),
        refine_keywords=("timeline", "history of"),
        fallback_keywords=("timeline",),
        confidence_rule="High on an explicit timeline phrase.",
    ))
    registry.register(IntentDefinition(
        name="Configuration Comparison", key="configuration-comparison",
        description="How a configuration differs between versions.",
        engine=ENGINE_CHANGES, domain="configuration",
        examples=("Compare configurations", "Compare config versions"),
        required_evidence=("Configuration Memory",),
        workflows=(
            _wf("Open Configuration", "/configuration",
                "Every stored version, diffable side by side."),
        ),
        recommendations=(),
        followups=(_fu("What changed?", "What changed?"),),
        refine_keywords=("config",),
        fallback_keywords=("compare config", "compare configuration"),
        confidence_rule="High on a change phrase mentioning configs; "
                        "Medium when inferred from 'compare config'.",
    ))

    # -- search family ----------------------------------------------------
    registry.register(IntentDefinition(
        name="Device Lookup", key="device-lookup",
        description="Find one device and what Atlas knows about it.",
        engine=ENGINE_SEARCH, domain="inventory",
        examples=("Find SW2", "Where is 10.0.9.9?"),
        required_evidence=("Evidence Index", "Enterprise Graph"),
        workflows=(
            _wf("Open Evidence", "/evidence",
                "Every stored artifact for the device."),
        ),
        recommendations=(),
        followups=(),
        confidence_rule="High on a lookup phrase.",
    ))
    registry.register(IntentDefinition(
        name="Configuration Review", key="configuration-review",
        description="Read a device's stored configuration.",
        engine=ENGINE_SEARCH, domain="configuration",
        examples=("Show me the config of SW2",),
        required_evidence=("Configuration Memory",),
        workflows=(
            _wf("Open Configuration", "/configuration",
                "Stored configurations with history and search."),
        ),
        recommendations=(),
        followups=(_fu("Compare versions", "Compare configurations"),),
        refine_keywords=("config",),
        confidence_rule="High on a lookup phrase mentioning configuration.",
    ))
    registry.register(IntentDefinition(
        name="Interface Investigation", key="interface-investigation",
        description="One interface's state and evidence.",
        engine=ENGINE_SEARCH, domain="inventory",
        examples=("Find eth2 on chennai-core",),
        required_evidence=("Evidence Index", "Interface Inventory"),
        workflows=(
            _wf("Open Evidence", "/evidence",
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
        engine=ENGINE_SEARCH, domain="evidence",
        examples=("Find the evidence for chennai-core",),
        required_evidence=("Evidence Index",),
        workflows=(
            _wf("Open Evidence Explorer", "/evidence",
                "Search and open every stored artifact."),
        ),
        recommendations=(),
        followups=(),
        refine_keywords=("evidence", "artifact"),
        fallback_keywords=(),
        confidence_rule="High on a lookup phrase mentioning evidence.",
    ))

    # -- discovery --------------------------------------------------------
    registry.register(IntentDefinition(
        name="Discovery Health", key="discovery-health",
        description="Coverage and freshness of what Atlas has discovered.",
        engine=ENGINE_DISCOVERY, domain="discovery",
        examples=("Summarize discovery", "When did discovery last run?"),
        required_evidence=("Discovery History",),
        workflows=(
            _wf("Open Discovery", "/discovery",
                "Run, resume, or review discovery for any network."),
        ),
        recommendations=(
            _wf("Open History", "/history",
                "Every archived run with its results."),
        ),
        followups=(_fu("Is everything healthy?", "Is everything healthy?"),),
        confidence_rule="High on a discovery phrase.",
    ))

    # -- maintenance / risk ----------------------------------------------
    registry.register(IntentDefinition(
        name="Maintenance Planning", key="maintenance-planning",
        description="Plan a change window with its risks understood.",
        engine=ENGINE_COMPASS, domain="maintenance",
        examples=("Help me plan maintenance", "Plan a change window"),
        required_evidence=("Maintenance Plans", "Topology"),
        workflows=(
            _wf("Open Compass", "/compass",
                "Plans, dependencies, readiness, and execution order."),
        ),
        recommendations=(
            _wf("Run a Prediction", "/predict",
                "Model the impact before the window."),
        ),
        followups=(_fu("What are the risks?", "What are the risks?"),),
        confidence_rule="High on a maintenance phrase.",
    ))
    registry.register(IntentDefinition(
        name="Risk Assessment", key="risk-assessment",
        description="What would break if a device or link changed.",
        engine=ENGINE_PREDICTION, domain="maintenance",
        examples=("Can I reboot Core1?", "What happens if I disable Gi0/1?"),
        required_evidence=("Topology", "Routing Tables"),
        workflows=(
            _wf("Open Predict", "/predict",
                "The full impact analysis for the modelled change."),
        ),
        recommendations=(
            _wf("Plan it in Compass", "/compass",
                "Turn the assessment into a maintenance plan."),
        ),
        followups=(
            _fu("Plan maintenance", "Help me plan maintenance"),
        ),
        # "Can I reboot X?" carries no legacy what-if phrase; these
        # deterministic shapes route it to a real impact prediction
        # (the prediction engine parses the reboot/upgrade target).
        fallback_keywords=("can i reboot", "can i shut", "can i shutdown",
                           "can i upgrade", "can i reload", "can i replace",
                           "safe to reboot", "safe to shut",
                           "safe to upgrade", "is it safe to"),
        confidence_rule="High on a what-if phrase; Medium when inferred "
                        "from a can-I-safely shape.",
    ))

    # -- resume / investigation ------------------------------------------
    registry.register(IntentDefinition(
        name="Resume Investigation", key="resume-investigation",
        description="Pick up the most recent unfinished work.",
        engine=ENGINE_CONTINUE, domain="incident",
        examples=("Continue yesterday's investigation",),
        required_evidence=("Investigation History",),
        workflows=(
            _wf("Open Investigations", "/paths",
                "Recent investigations, resumable where they stopped."),
        ),
        recommendations=(),
        followups=(),
        confidence_rule="High on a continue/resume phrase.",
    ))
    registry.register(IntentDefinition(
        name="Incident Investigation", key="incident-investigation",
        description="Investigate an active or recorded incident.",
        engine=ENGINE_INVESTIGATION, domain="incident",
        examples=("Summarize the last investigation",),
        required_evidence=("Investigation History", "Incident Cases"),
        workflows=(
            _wf("Open Incidents", "/incidents",
                "Active and resolved cases with their evidence."),
            _wf("Open Investigations", "/paths",
                "Path investigations and their verdicts."),
        ),
        recommendations=(),
        followups=(_fu("Is everything healthy?", "Is everything healthy?"),),
        fallback_keywords=("incident",),
        confidence_rule="High on an investigation phrase; Medium when "
                        "inferred from 'incident'.",
    ))

    # -- inventory / identity --------------------------------------------
    registry.register(IntentDefinition(
        name="Inventory", key="inventory",
        description="What the estate contains, by the numbers.",
        engine=ENGINE_ENTERPRISE, domain="inventory",
        examples=("How many devices do we have?", "Summarize the enterprise"),
        required_evidence=("Enterprise Graph",),
        workflows=(
            _wf("Open Topology", "/topology",
                "The estate drawn whole."),
        ),
        recommendations=(),
        followups=(_fu("Is everything healthy?", "Is everything healthy?"),),
        confidence_rule="High on an inventory phrase.",
    ))
    registry.register(IntentDefinition(
        name="Identity Resolution", key="identity-resolution",
        description="Duplicate or conflicting device identities.",
        engine=ENGINE_ENTERPRISE, domain="identity",
        examples=("Resolve duplicate devices", "Any identity conflicts?"),
        required_evidence=("Enterprise Graph", "Identity Conflicts"),
        workflows=(
            _wf("Open Resolution Center", "/evidence/resolution-center",
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

    # -- honest gaps ------------------------------------------------------
    registry.register(IntentDefinition(
        name="Performance Investigation", key="performance-investigation",
        description="Latency, load, or slowness questions.",
        engine=ENGINE_UNKNOWN, domain="performance",
        examples=("Why is SAP slow?",),
        required_evidence=("Operational Telemetry",),
        workflows=(
            _wf("Open Timeline", "/timeline",
                "Recent changes are the first suspect for new slowness."),
            _wf("Open Path Intelligence", "/paths",
                "Verify the path the application rides on."),
        ),
        recommendations=(),
        followups=(
            _fu("What changed?", "What changed?"),
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
    registry.register(IntentDefinition(
        name="Security Investigation", key="security-investigation",
        description="Security posture and rule questions.",
        engine=ENGINE_UNKNOWN, domain="security",
        examples=("Any security violations?",),
        required_evidence=("Policy Engine Results", "Audit Log"),
        workflows=(
            _wf("Review Policy", "/policy",
                "Declared security policy and every judgement."),
            _wf("Open Audit", "/audit",
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
    registry.register(IntentDefinition(
        name="Unknown", key="unknown",
        description="No operational pattern matched.",
        engine=ENGINE_UNKNOWN, domain="unknown",
        examples=(),
        required_evidence=(),
        workflows=(
            _wf("Run Discovery", "/discovery",
                "More evidence is the honest way to more answers."),
        ),
        recommendations=(),
        followups=(),
        confidence_rule="Unknown — Atlas will not guess.",
    ))

    return registry


DEFAULT_REGISTRY = build_default_registry()
