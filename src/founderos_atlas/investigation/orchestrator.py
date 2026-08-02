"""The investigation orchestrator (PR-167, Parts 3, 5, 6).

    understand -> resolve -> plan -> execute -> summarise

The plan is built and returned whether or not execution succeeds, so
an operator always sees what Atlas set out to check. Execution walks
the plan in order, sharing one context, and records each step's
outcome: done, skipped (an optional step with nothing to work on), or
blocked (the evidence it needs is absent — stated, never hidden).

The summary is composed from what the steps found. It is not a
template with holes: a BGP investigation that found three established
sessions says so with the numbers, and one that found none says that
instead. No investigation ever falls back to an estate-wide summary —
if Atlas cannot answer the question asked, it says which part it
cannot answer.
"""

from __future__ import annotations

import time
from typing import Any

from .extraction import extract
from .models import (
    STEP_BLOCKED,
    STEP_DONE,
    STEP_SKIPPED,
    InvestigationContext,
    InvestigationPlan,
    InvestigationResult,
)
from .resolution import devices_in_scope, resolve
from .templates import InvestigationTemplate, select


CONFIDENCE_HIGH = "High"
CONFIDENCE_MEDIUM = "Medium"
CONFIDENCE_LOW = "Low"
CONFIDENCE_UNKNOWN = "Unknown"


def scope_vocabulary(graph) -> tuple[str, ...]:
    """The scope names this enterprise actually contains.

    Assigned sites first. Where site inference has assigned nothing —
    common, and true of estates that encode location in the hostname —
    the leading hostname token is included as well, so "chennai" is
    recognisable as a scope when `chennai-regional-edge` exists.
    Resolution labels any match made this way as a naming-convention
    grouping, so the weaker basis is never hidden.
    """

    names: list[str] = []
    seen: set[str] = set()
    for site in getattr(graph, "sites", ()) or ():
        text = str(site)
        if text in ("unknown", "ambiguous") or text.casefold() in seen:
            continue
        names.append(text)
        seen.add(text.casefold())
    for device in getattr(graph, "devices", ()) or ():
        hostname = str(getattr(device, "hostname", "") or "")
        token = hostname.split(".")[0].split("-")[0].strip()
        if len(token) < 3 or token.casefold() in seen:
            continue
        if not token.isalpha():          # skip rack/serial-ish prefixes
            continue
        names.append(token)
        seen.add(token.casefold())
    return tuple(names)


def understand(question: str, graph) -> Any:
    """Question -> structured request, using the scopes Atlas knows."""

    return extract(question, known_sites=scope_vocabulary(graph))


def plan_for(template: InvestigationTemplate, request) -> InvestigationPlan:
    endpoints = ""
    if request.has_endpoints:
        endpoints = f" — {request.source} and {request.destination}"
    elif request.sites:
        endpoints = f" — {', '.join(request.sites)}"
    elif request.devices:
        endpoints = f" — {', '.join(request.devices)}"
    title = template.title + endpoints
    return InvestigationPlan(
        template=template.key, title=title,
        objective=template.objective, steps=template.plan_steps(),
    )


def investigate(
    question: str, *, graph, snapshot: dict | None = None,
    change_report: dict | None = None,
) -> InvestigationResult | None:
    """Run one investigation, or return None when the question is not
    an investigation (no named scope) and Atlas's estate-wide answer
    should stand."""

    started = time.perf_counter()
    request = understand(question, graph)
    template = select(request)
    if template is None:
        return None

    entities = resolve(graph, request)
    # The objective belongs to the template, so the request stays
    # exactly as it was extracted from the operator's words.
    plan = plan_for(template, request)
    context = InvestigationContext(
        request=request, entities=entities, graph=graph, snapshot=snapshot,
    )
    context.device_ids = devices_in_scope(graph, entities)
    if change_report is not None:
        context.facts["change_report"] = change_report

    engines_used: list[str] = []
    for spec, step in zip(template.steps, plan.steps):
        try:
            ran = bool(spec.run(context))
        except Exception as error:  # an engine must never break an answer
            step.status = STEP_BLOCKED
            step.detail = f"this check could not run: {error}"
            context.add_gap(
                f"The “{spec.label}” check could not run, so its part of "
                "the question is unanswered."
            )
            continue
        if ran:
            step.status = STEP_DONE
            if spec.engine not in engines_used:
                engines_used.append(spec.engine)
        else:
            step.status = STEP_SKIPPED if not spec.required else STEP_BLOCKED
            step.detail = (
                "nothing in scope for this check"
                if not spec.required
                else "the entities this check needs were not resolved"
            )

    summary, confidence, basis = _summarise(template, context)
    return InvestigationResult(
        request=request, entities=entities, plan=plan,
        findings=tuple(context.findings), gaps=tuple(context.gaps),
        evidence=tuple(context.evidence), summary=summary,
        confidence=confidence, confidence_basis=basis,
        engines_used=tuple(engines_used),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _unresolved_sentence(entities) -> str:
    """What Atlas could not find, said exactly (Part 9)."""

    parts = []
    for entity in entities.problems:
        parts.append(entity.detail or f"“{entity.query}” is not known.")
    return " ".join(parts)


def _summarise(template, context: InvestigationContext
               ) -> tuple[str, str, str]:
    request = context.request
    entities = context.entities
    facts = context.facts

    unresolved = _unresolved_sentence(entities)
    if unresolved:
        # A named thing Atlas cannot find is the answer — not a reason
        # to answer a different question.
        return (
            f"Atlas cannot investigate this as asked. {unresolved}",
            CONFIDENCE_UNKNOWN,
            "the question named something Atlas has not discovered",
        )

    source = entities.source.label if entities.source else ""
    destination = entities.destination.label if entities.destination else ""
    scope = " and ".join(part for part in (source, destination) if part)
    if not scope:
        named = [item.label for item in entities.all() if item.ok]
        scope = ", ".join(named) or "the named scope"

    sentences: list[str] = []
    confidence = CONFIDENCE_MEDIUM
    basis = "composed from stored evidence for the named scope"

    if template.key == "bgp-between":
        between = int(facts.get("bgp_sessions_between") or 0)
        established = int(facts.get("bgp_established") or 0)
        if between:
            sentences.append(
                f"BGP between {scope}: {between} session(s) observed, "
                f"{established} established."
            )
            confidence = (
                CONFIDENCE_HIGH if established == between
                else CONFIDENCE_MEDIUM
            )
            basis = (
                f"{between} BGP session(s) read from stored device "
                "evidence"
            )
        else:
            total = int(facts.get("bgp_sessions_total") or 0)
            sentences.append(
                f"Atlas found no BGP peering between {scope}."
                + (f" {total} BGP session(s) exist at {source}, none of "
                   f"them to {destination}." if total else "")
            )
            confidence = CONFIDENCE_MEDIUM if total else CONFIDENCE_LOW
            basis = "no BGP session in the stored evidence matches"
    elif template.key in ("bgp-scope",):
        total = int(facts.get("bgp_sessions_total") or 0)
        established = int(facts.get("bgp_established") or 0)
        sentences.append(
            f"BGP for {scope}: {total} session(s) observed, "
            f"{established} established." if total
            else f"Atlas holds no BGP evidence for {scope}."
        )
        confidence = CONFIDENCE_HIGH if total else CONFIDENCE_LOW
        basis = f"{total} BGP session(s) read from stored device evidence"
    elif template.key == "ospf-scope":
        total = int(facts.get("ospf_adjacencies_total") or 0)
        full = int(facts.get("ospf_full") or 0)
        sentences.append(
            f"OSPF for {scope}: {total} adjacency(ies) observed, "
            f"{full} in Full state." if total
            else f"Atlas holds no OSPF evidence for {scope}."
        )
        confidence = CONFIDENCE_HIGH if total else CONFIDENCE_LOW
        basis = f"{total} OSPF adjacency(ies) read from stored evidence"
    elif template.key == "connectivity-between":
        status = str(facts.get("path_status") or "")
        start = facts.get("path_start") or source
        end = facts.get("path_end") or destination
        if status == "connected":
            hops = " → ".join(facts.get("path_hops") or ())
            sentences.append(
                f"{start} can reach {end} on the known path {hops}: "
                "every hop passed validation."
                if hops else f"{start} can reach {end}."
            )
            confidence = CONFIDENCE_HIGH
            basis = "path walked hop by hop against the captured routing "\
                    "tables"
        elif status:
            failure = facts.get("path_failure") or "see the investigation."
            sentences.append(
                f"{start} cannot reach {end}: {failure}"
                if status == "failed"
                else f"The {start} → {end} path is {status}: {failure}"
            )
            confidence = CONFIDENCE_MEDIUM
            basis = "path walked against the captured routing tables"
        else:
            links = int(facts.get("links_between") or 0)
            sentences.append(
                f"Atlas has discovered {links} direct link(s) between "
                f"{scope}." if links else
                f"Atlas has discovered no direct link between {scope}."
            )
            confidence = CONFIDENCE_MEDIUM if links else CONFIDENCE_LOW
            basis = "links read from the federated topology"
    else:
        devices = len(context.device_ids)
        sentences.append(
            f"{scope}: {devices} device(s) in scope, "
            f"{facts.get('interfaces_total', 0)} interface(s), "
            f"{facts.get('bgp_sessions_total', 0)} BGP session(s), "
            f"{facts.get('ospf_adjacencies_total', 0)} OSPF adjacency(ies)."
        )
        confidence = CONFIDENCE_HIGH if devices else CONFIDENCE_LOW

    interfaces_down = int(facts.get("interfaces_down") or 0)
    if interfaces_down:
        sentences.append(
            f"{interfaces_down} interface(s) in scope are reported down."
        )
    if context.gaps:
        sentences.append(
            f"{len(context.gaps)} limitation(s) are stated below rather "
            "than left implied."
        )
    return " ".join(sentences), confidence, basis
