"""The OIR's controlled vocabularies (PR-164.1, FOUNDATION).

Registration validation checks every declared workflow reference and
evidence requirement against these sets, so a typo in a capability's
registration fails at STARTUP — loudly — instead of shipping a dead
link or an evidence name nothing produces.

Extending Atlas with a new workflow surface or evidence kind means
adding it here first; that is deliberate, because these names are part
of the platform contract every capability shares.
"""

from __future__ import annotations


# Workflow surfaces an intent may route to — the path part of an href,
# query strings excluded. Validation is exact.
KNOWN_WORKFLOW_PATHS = frozenset((
    "/",
    "/topology",
    "/paths",
    "/predict",
    "/compass",
    "/discovery",
    "/history",
    "/changes",
    "/timeline",
    "/policy",
    "/audit",
    "/incidents",
    "/evidence",
    "/evidence/resolution-center",
    "/configuration",
))

# First path segments that answer-level links may legitimately point at
# (the analytics choice endpoint accepts these). Wider than the intent
# vocabulary above because ENGINE answers link to dynamic detail pages
# ("/devices/<id>", "/compass/<plan>") that no intent registers.
KNOWN_WORKFLOW_AREAS = frozenset((
    "", "devices", "topology", "paths", "predict", "compass",
    "discovery", "history", "changes", "timeline", "policy", "audit",
    "incidents", "evidence", "configuration", "advisor",
))

# Evidence kinds an intent may require. One canonical name per kind.
EVIDENCE_KINDS = frozenset((
    "Enterprise Graph",
    "Site Membership",
    "Routing Observations",
    "BGP Observations",
    "OSPF Observations",
    "Inter-site Links",
    "Switch Inventory",
    "Policy Engine Results",
    "Topology",
    "Routing Tables",
    "Path Policies",
    "Change Timeline",
    "Configuration Memory",
    "Discovery History",
    "Evidence Index",
    "Interface Inventory",
    "Maintenance Plans",
    "Investigation History",
    "Incident Cases",
    "Incident Signals",
    "Identity Conflicts",
    "Operational Telemetry",
    "Audit Log",
))


def workflow_path(href: str) -> str:
    """The path part of a workflow href (query string stripped)."""

    return str(href or "").split("?", 1)[0]
