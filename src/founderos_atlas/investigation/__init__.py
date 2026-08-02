"""Atlas INVESTIGATOR — deterministic investigation planning (PR-167).

Atlas answers operational questions by investigating them: understand
the question structurally, resolve what it named against discovered
entities, plan the checks, execute several engines over one shared
context, and report findings with what could not be determined.

No AI participates. Extraction is fixed vocabularies and shapes;
resolution matches discovered entities and reports ambiguity instead of
choosing; the plan is a template's declared steps; every finding comes
from stored evidence.

A question that names nothing specific is not an investigation —
:func:`investigate` returns None and Atlas's existing estate-wide
answer stands, because inventing a scope would be worse than a general
answer.
"""

from .extraction import APPLICATIONS, PROTOCOLS, SEVERITIES, extract
from .models import (
    AMBIGUOUS,
    RESOLVED,
    STEP_BLOCKED,
    STEP_DONE,
    STEP_PENDING,
    STEP_SKIPPED,
    UNKNOWN,
    Finding,
    InvestigationContext,
    InvestigationPlan,
    InvestigationRequest,
    InvestigationResult,
    PlanStep,
    ResolvedEntities,
    ResolvedEntity,
)
from .orchestrator import investigate, plan_for, understand
from .resolution import (
    devices_in_scope,
    resolve,
    resolve_device,
    resolve_endpoint,
    resolve_site,
    site_members,
)
from .templates import TEMPLATE_BY_KEY, TEMPLATES, InvestigationTemplate, select

__all__ = [
    "AMBIGUOUS",
    "APPLICATIONS",
    "Finding",
    "InvestigationContext",
    "InvestigationPlan",
    "InvestigationRequest",
    "InvestigationResult",
    "InvestigationTemplate",
    "PROTOCOLS",
    "PlanStep",
    "RESOLVED",
    "ResolvedEntities",
    "ResolvedEntity",
    "SEVERITIES",
    "STEP_BLOCKED",
    "STEP_DONE",
    "STEP_PENDING",
    "STEP_SKIPPED",
    "TEMPLATES",
    "TEMPLATE_BY_KEY",
    "UNKNOWN",
    "devices_in_scope",
    "extract",
    "investigate",
    "plan_for",
    "resolve",
    "resolve_device",
    "resolve_endpoint",
    "resolve_site",
    "select",
    "site_members",
    "understand",
    "templates",
]
