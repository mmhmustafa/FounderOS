"""Investigation templates (PR-167, Part 7).

Each template is what an experienced operations engineer would actually
check for one kind of question, written down: the steps, which engines
run them, which are required, and what makes the investigation
complete.

Selection is deterministic and specific-first: a question naming a
protocol AND two endpoints is a protocol-between-sites investigation; a
question naming nothing specific is not an investigation at all and
falls through to Atlas's existing estate-wide answer. That last rule is
what stops Atlas inventing scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import engines
from .models import InvestigationRequest, PlanStep


@dataclass(frozen=True)
class StepSpec:
    key: str
    label: str
    engine: str
    run: Callable[..., bool]
    required: bool = True


@dataclass(frozen=True)
class InvestigationTemplate:
    """One kind of investigation."""

    key: str
    title: str
    objective: str
    steps: tuple[StepSpec, ...]
    completion: str
    domain: str = "investigation"

    def plan_steps(self) -> tuple[PlanStep, ...]:
        return tuple(
            PlanStep(key=spec.key, label=spec.label, engine=spec.engine,
                     required=spec.required)
            for spec in self.steps
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "title": self.title,
            "objective": self.objective, "domain": self.domain,
            "completion": self.completion,
            "engines": sorted({spec.engine for spec in self.steps}),
        }


def _locate(required: bool = True) -> StepSpec:
    return StepSpec("locate", "Locate the named sites and devices",
                    "graph", engines.locate_entities, required)


TEMPLATES: tuple[InvestigationTemplate, ...] = (
    InvestigationTemplate(
        key="bgp-between", domain="routing",
        title="BGP between two endpoints",
        objective="Establish whether BGP peering exists between the two "
                  "named endpoints and what state it is in.",
        completion="Both endpoints resolved and every BGP session "
                   "between them reported, or the absence stated.",
        steps=(
            _locate(),
            StepSpec("wan-path", "Locate the path between them",
                     "topology", engines.wan_path, False),
            StepSpec("bgp", "Retrieve BGP neighbours and compare them",
                     "routing", engines.bgp_between),
            StepSpec("interfaces", "Review interface health on the path",
                     "graph", engines.interface_health, False),
            StepSpec("changes", "Check recent recorded changes",
                     "changes", engines.recent_changes, False),
        ),
    ),
    InvestigationTemplate(
        key="ospf-scope", domain="routing",
        title="OSPF adjacencies",
        objective="Report the OSPF adjacencies Atlas has observed for "
                  "the named scope.",
        completion="Every observed adjacency reported, or the absence "
                   "stated.",
        steps=(
            _locate(),
            StepSpec("ospf", "Retrieve OSPF neighbours and their state",
                     "routing", engines.ospf_for_devices),
            StepSpec("interfaces", "Review interface health",
                     "graph", engines.interface_health, False),
            StepSpec("changes", "Check recent recorded changes",
                     "changes", engines.recent_changes, False),
        ),
    ),
    InvestigationTemplate(
        key="bgp-scope", domain="routing",
        title="BGP for the named scope",
        objective="Report the BGP sessions Atlas has observed for the "
                  "named site or device.",
        completion="Every observed session reported, or the absence "
                   "stated.",
        steps=(
            _locate(),
            StepSpec("bgp", "Retrieve BGP neighbours and their state",
                     "routing", engines.bgp_for_devices),
            StepSpec("interfaces", "Review interface health",
                     "graph", engines.interface_health, False),
            StepSpec("changes", "Check recent recorded changes",
                     "changes", engines.recent_changes, False),
        ),
    ),
    InvestigationTemplate(
        key="connectivity-between", domain="connectivity",
        title="Connectivity between two endpoints",
        objective="Establish what connects the two named endpoints and "
                  "what state it is in.",
        completion="The path between the endpoints reported, or its "
                   "absence stated.",
        steps=(
            _locate(),
            StepSpec("path", "Walk the path hop by hop",
                     "path", engines.path_walk),
            StepSpec("wan-path", "Locate the links between them",
                     "topology", engines.wan_path, False),
            StepSpec("interfaces", "Review interface health on the path",
                     "graph", engines.interface_health, False),
            StepSpec("bgp", "Check routing between them",
                     "routing", engines.bgp_between, False),
            StepSpec("changes", "Check recent recorded changes",
                     "changes", engines.recent_changes, False),
        ),
    ),
    InvestigationTemplate(
        key="site-scope", domain="health",
        title="Investigation of a named scope",
        objective="Report what Atlas knows about the named site or "
                  "device.",
        completion="The scope's devices, interfaces and routing "
                   "evidence reported.",
        steps=(
            _locate(),
            StepSpec("interfaces", "Review interface health",
                     "graph", engines.interface_health),
            StepSpec("bgp", "Check routing evidence",
                     "routing", engines.bgp_for_devices, False),
            StepSpec("ospf", "Check OSPF adjacencies",
                     "routing", engines.ospf_for_devices, False),
            StepSpec("changes", "Check recent recorded changes",
                     "changes", engines.recent_changes, False),
        ),
    ),
)

TEMPLATE_BY_KEY = {item.key: item for item in TEMPLATES}

# Protocols that have a dedicated routing investigation today. A
# protocol Atlas does not collect evidence for still routes to the
# scope investigation, which will state the gap honestly rather than
# pretend to check it.
ROUTING_PROTOCOLS = frozenset(("bgp", "ospf"))


def select(request: InvestigationRequest) -> InvestigationTemplate | None:
    """The template for one request, or None to leave the question to
    Atlas's existing estate-wide answer.

    Specific first: protocol + two endpoints, then protocol + scope,
    then endpoints alone, then a named scope alone. A question naming
    nothing returns None — inventing a scope would be worse than the
    general answer.
    """

    if not request.named_anything:
        return None
    protocol = request.protocol
    if request.has_endpoints:
        if protocol == "bgp":
            return TEMPLATE_BY_KEY["bgp-between"]
        if protocol == "ospf":
            return TEMPLATE_BY_KEY["ospf-scope"]
        return TEMPLATE_BY_KEY["connectivity-between"]
    if protocol == "bgp":
        return TEMPLATE_BY_KEY["bgp-scope"]
    if protocol == "ospf":
        return TEMPLATE_BY_KEY["ospf-scope"]
    if request.sites or request.devices:
        return TEMPLATE_BY_KEY["site-scope"]
    return None
