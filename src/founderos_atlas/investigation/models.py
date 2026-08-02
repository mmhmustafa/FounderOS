"""Investigation models (PR-167, INVESTIGATOR).

Atlas answers questions by INVESTIGATING, not by picking one engine.
These are the objects that make that deterministic and inspectable:

    question  ->  InvestigationRequest   (what was asked, structurally)
              ->  ResolvedEntities       (what those names ARE, in Atlas)
              ->  InvestigationPlan      (what Atlas will check, shown first)
              ->  InvestigationContext   (what each step learned, shared)
              ->  InvestigationResult    (findings, gaps, confidence)

Nothing here reasons. Extraction is keyword and shape matching over the
operator's own words; resolution matches against entities Atlas has
actually discovered; the plan is a template's declared steps. When a
name is ambiguous or an entity is unknown, that is recorded as such and
reported — never resolved by preference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# -- Part 1: the structured request ----------------------------------------

@dataclass(frozen=True)
class InvestigationRequest:
    """One question, understood structurally.

    Every field is either something the operator actually said or the
    empty value. Nothing is inferred to fill a gap.
    """

    question: str
    objective: str = ""            # the template's objective, once chosen
    protocol: str = ""             # bgp | ospf | hsrp | stp | vpn | ...
    source: str = ""               # named source site/device, as typed
    destination: str = ""          # named destination, as typed
    devices: tuple[str, ...] = ()
    sites: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    vrfs: tuple[str, ...] = ()
    vlans: tuple[str, ...] = ()
    applications: tuple[str, ...] = ()
    addresses: tuple[str, ...] = ()
    time_range: str = ""           # "last 24 hours", "yesterday", ...
    severity: str = ""             # down | degraded | slow | unstable
    direction: str = ""            # inbound | outbound | bidirectional

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "objective": self.objective,
            "protocol": self.protocol,
            "source": self.source,
            "destination": self.destination,
            "devices": list(self.devices),
            "sites": list(self.sites),
            "interfaces": list(self.interfaces),
            "vrfs": list(self.vrfs),
            "vlans": list(self.vlans),
            "applications": list(self.applications),
            "addresses": list(self.addresses),
            "time_range": self.time_range,
            "severity": self.severity,
            "direction": self.direction,
        }

    @property
    def has_endpoints(self) -> bool:
        return bool(self.source and self.destination)

    @property
    def named_anything(self) -> bool:
        """Did the operator name a specific thing at all? A question
        that names nothing is an estate-wide question, and answering it
        with a site-specific investigation would be inventing scope."""

        return bool(
            self.source or self.destination or self.devices or self.sites
            or self.interfaces or self.addresses or self.applications
        )


# -- Part 2: entity resolution ---------------------------------------------

RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class ResolvedEntity:
    """One name the operator used, and what Atlas found it to be.

    ``status`` is RESOLVED, AMBIGUOUS or UNKNOWN. An ambiguous name
    carries every candidate; Atlas reports the ambiguity and stops
    rather than choosing.
    """

    query: str
    kind: str                       # site | device | interface | address
    status: str
    identifier: str = ""            # site_id or enterprise_id when resolved
    label: str = ""
    candidates: tuple[str, ...] = ()
    detail: str = ""
    device_ids: tuple[str, ...] = ()   # members, for a site

    @property
    def ok(self) -> bool:
        return self.status == RESOLVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query, "kind": self.kind, "status": self.status,
            "identifier": self.identifier, "label": self.label,
            "candidates": list(self.candidates), "detail": self.detail,
            "device_count": len(self.device_ids),
        }


@dataclass(frozen=True)
class ResolvedEntities:
    """Everything the request named, resolved against Atlas."""

    source: ResolvedEntity | None = None
    destination: ResolvedEntity | None = None
    devices: tuple[ResolvedEntity, ...] = ()
    sites: tuple[ResolvedEntity, ...] = ()

    def all(self) -> tuple[ResolvedEntity, ...]:
        items = list(self.devices) + list(self.sites)
        for endpoint in (self.source, self.destination):
            if endpoint is not None:
                items.append(endpoint)
        return tuple(items)

    @property
    def problems(self) -> tuple[ResolvedEntity, ...]:
        return tuple(item for item in self.all() if not item.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict() if self.source else None,
            "destination": (
                self.destination.to_dict() if self.destination else None
            ),
            "devices": [item.to_dict() for item in self.devices],
            "sites": [item.to_dict() for item in self.sites],
        }


# -- Parts 3 and 6: the plan and its execution -----------------------------

STEP_PENDING = "pending"
STEP_DONE = "done"
STEP_SKIPPED = "skipped"
STEP_BLOCKED = "blocked"     # its evidence is missing, stated honestly


@dataclass
class PlanStep:
    """One check in the plan. The label is what the operator reads."""

    key: str
    label: str
    engine: str
    required: bool = True
    status: str = STEP_PENDING
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "engine": self.engine,
            "required": self.required, "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class InvestigationPlan:
    """What Atlas intends to check, shown BEFORE it checks it."""

    template: str
    title: str
    objective: str
    steps: tuple[PlanStep, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template, "title": self.title,
            "objective": self.objective,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass
class Finding:
    """One thing an engine established. ``detail`` is evidence-derived
    text; ``href`` deep-links to where the operator can see it."""

    label: str
    detail: str
    href: str = ""
    engine: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "detail": self.detail,
                "href": self.href, "engine": self.engine}


@dataclass
class InvestigationContext:
    """Shared state across steps (Part 5).

    Later engines reuse what earlier ones resolved instead of
    recomputing it — the graph is read once, sites resolve once, and a
    device list gathered for step 2 is the same list step 5 uses.
    """

    request: InvestigationRequest
    entities: ResolvedEntities
    graph: Any = None
    snapshot: dict | None = None
    device_ids: tuple[str, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    evidence: list[dict[str, str]] = field(default_factory=list)

    def add_finding(self, label: str, detail: str, *, href: str = "",
                    engine: str = "") -> None:
        self.findings.append(Finding(label, detail, href, engine))

    def add_gap(self, text: str) -> None:
        if text and text not in self.gaps:
            self.gaps.append(text)

    def cite(self, label: str, detail: str, href: str = "") -> None:
        item = {"label": label, "detail": detail, "href": href}
        if item not in self.evidence:
            self.evidence.append(item)


@dataclass(frozen=True)
class InvestigationResult:
    """The finished investigation, ready to become an answer."""

    request: InvestigationRequest
    entities: ResolvedEntities
    plan: InvestigationPlan
    findings: tuple[Finding, ...]
    gaps: tuple[str, ...]
    evidence: tuple[dict[str, str], ...]
    summary: str
    confidence: str
    confidence_basis: str
    engines_used: tuple[str, ...]
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "entities": self.entities.to_dict(),
            "plan": self.plan.to_dict(),
            "findings": [item.to_dict() for item in self.findings],
            "gaps": list(self.gaps),
            "evidence": [dict(item) for item in self.evidence],
            "summary": self.summary,
            "confidence": self.confidence,
            "confidence_basis": self.confidence_basis,
            "engines_used": list(self.engines_used),
            "duration_ms": self.duration_ms,
        }
