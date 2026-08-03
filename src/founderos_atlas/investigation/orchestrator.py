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
    policy_runner=None,
    state_horizon_minutes: int | None = None,
    state_now: str | None = None,
) -> InvestigationResult | None:
    """Run one investigation, or return None when the question is not
    an investigation (no named scope) and Atlas's estate-wide answer
    should stand.

    ``policy_runner`` is a zero-argument callable returning a
    PolicyReport, supplied by the caller because policy evaluation
    needs the workspace's Enterprise Memory, which the investigator
    deliberately does not know how to reach. It is invoked lazily and
    only by a validation template — every other investigation never
    touches it.
    """

    started = time.perf_counter()
    request = understand(question, graph)

    # PR-173: a question about behaviour OVER TIME ("flapping",
    # "unstable", "stable") asks for a state HISTORY Atlas does not
    # retain. A single discovery cannot distinguish a link that flapped
    # from one that was simply down when observed — so the question is
    # refused honestly, quoting the operator's own word, before any
    # template could pretend to answer it.
    if request.temporal_terms and request.has_subject:
        return _temporal_refusal(request, started)

    template = select(request)
    if template is None:
        # PR-171: a VALIDATION question whose subject has no validation
        # template is refused honestly — never handed to the estate
        # summary, which answers a different question, and never run
        # through an adjacency investigation, which answers yet another.
        if request.objective == "validate" and request.has_subject:
            return _validation_refusal(request, started)
        # PR-173: the same discipline on the state axis. A
        # judgement-phrased "is X healthy?" about a subject Atlas has
        # no state capability for is refused with the missing HALF
        # named — but only when nothing else in the ladder would have
        # answered (a named site still earns its site investigation).
        if (request.objective == "assess" and request.has_subject
                and not request.named_anything):
            return _state_refusal(request, started)
        return None

    entities = resolve(graph, request)
    plan = plan_for(template, request)
    context = InvestigationContext(
        request=request, entities=entities, graph=graph, snapshot=snapshot,
    )
    context.device_ids = devices_in_scope(graph, entities)
    if change_report is not None:
        context.facts["change_report"] = change_report
    if policy_runner is not None:
        context.facts["policy_runner"] = policy_runner
    # PR-173: the state engine's freshness contract — the horizon is
    # workspace policy the caller supplies; ``state_now`` exists so
    # tests are deterministic. Neither invents anything: absent, the
    # engine defaults to 60 minutes and the wall clock.
    if state_horizon_minutes is not None:
        context.facts["state_horizon_minutes"] = int(state_horizon_minutes)
    if state_now is not None:
        context.facts["state_now"] = str(state_now)

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


def _validation_refusal(request, started: float) -> InvestigationResult:
    """The honest answer when Atlas cannot validate what was asked.

    Success criterion 3: "Is all the FOO configuration fine?" must name
    what Atlas CAN do, not fall back to the estate summary — which is
    the original failure in a different costume — and must never run an
    adjacency investigation in validation's clothing.
    """

    from .models import ResolvedEntities
    from .subjects import label_for
    from .validation import capabilities

    key = request.subject or request.protocol
    label = label_for(key)
    # "the Configuration configuration" reads like a stutter — when the
    # subject IS the configuration domain, the question named no
    # specific subject at all, and the refusal should say that.
    named = ("this configuration" if key == "configuration"
             else f"the {label} configuration")
    # PR-172: the "can currently validate" list is READ from the
    # capability registry — one source of truth, so this sentence can
    # never advertise a validation the pack cannot deliver (R3).
    supported = ", ".join(
        item.title for item in capabilities()
    ) or "nothing yet"
    plan = InvestigationPlan(
        template="validation-refusal",
        title=f"{label} configuration validation"
        if key != "configuration" else "Configuration validation",
        objective=f"Judge {named} against policy rules.",
        steps=(),
    )
    return InvestigationResult(
        request=request,
        entities=ResolvedEntities(),
        plan=plan,
        findings=(),
        gaps=(
            f"Atlas has no configuration-validation investigation for "
            f"{label}. It can currently validate: {supported}.",
        ) if key != "configuration" else (
            "The question names no subject Atlas can validate. It can "
            f"currently validate: {supported}.",
        ),
        evidence=(),
        summary=(
            f"Atlas cannot validate {named} as asked — it has no "
            f"validation rules for {label}. It can currently validate: "
            f"{supported}. It will not claim compliance it has not "
            "checked."
        ) if key != "configuration" else (
            "Atlas cannot validate this configuration as asked — the "
            "question names no subject it recognises. It can currently "
            f"validate: {supported}. It will not claim compliance it "
            "has not checked."
        ),
        confidence=CONFIDENCE_UNKNOWN,
        confidence_basis=(
            "the question asks for a validation Atlas has no rules for"
        ),
        engines_used=(),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _temporal_refusal(request, started: float) -> InvestigationResult:
    """The honest answer to a question about behaviour over time.

    Atlas retains no state history: a single discovery is one sample,
    and "flapping"/"unstable" verdicts invented from one sample would
    be the most confident-sounding wrong answers Atlas could give
    (review R2). The reserved verdict "Unstable" exists precisely so
    it can be refused by name here and never redefined to something
    weaker.
    """

    from .models import ResolvedEntities
    from .subjects import label_for

    label = label_for(request.subject or request.protocol)
    quoted = ", ".join(f"“{term}”" for term in request.temporal_terms)
    # "Are interfaces stable" vs "Is BGP stable" — the label's own
    # number decides the verb, so the refusal reads like an operator
    # wrote it.
    plural = label.casefold().endswith("s") and label.casefold() not in (
        "mpls", "dns",
    )
    verb, pronoun = ("are", "Are") if plural else ("is", "Is")
    plan = InvestigationPlan(
        template="state-refusal",
        title=f"{label} stability",
        objective=f"Judge whether {label} {verb} stable over time.",
        steps=(),
    )
    return InvestigationResult(
        request=request,
        entities=ResolvedEntities(),
        plan=plan,
        findings=(),
        gaps=(
            f"The question asks about behaviour over time ({quoted}), "
            "and Atlas retains no state history — it holds one "
            "observation per discovery, which cannot distinguish a "
            "link that flapped from one that was down when observed.",
        ),
        evidence=(),
        summary=(
            f"Atlas cannot judge whether {label} {verb} stable — that "
            f"needs state history ({quoted} describe behaviour over "
            "time), and Atlas holds one observation per discovery. "
            f"It can assess the CURRENT {label} state as of the last "
            f"discovery; ask, for example, “{pronoun} "
            f"{label} healthy?”."
        ),
        confidence=CONFIDENCE_UNKNOWN,
        confidence_basis=(
            "stability requires a state history Atlas does not retain"
        ),
        engines_used=(),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _state_refusal(request, started: float) -> InvestigationResult:
    """The honest answer when Atlas cannot assess a subject's state.

    Names WHICH half is missing — the observation shape (a parser) or
    the state rules (data) — because those lead to different actions,
    and lists what Atlas CAN assess, read live from the capability
    registry.
    """

    from .models import ResolvedEntities
    from .subjects import label_for, subject as subject_of
    from .validation import ASPECT_STATE, capabilities

    key = request.subject or request.protocol
    label = label_for(key)
    descriptor = subject_of(key)
    state_kind = str(getattr(descriptor, "state_kind", "") or "")
    if descriptor is None:
        cause = f"it does not recognise {label} as a subject"
    elif not state_kind:
        cause = (
            f"it has no canonical observation shape for {label} state "
            "— the collectors may gather the text, but nothing parses "
            "it into judgeable observations yet"
        )
    else:
        cause = (
            f"it has an observation shape for {label} "
            f"({state_kind}) but no state rules that judge it"
        )
    supported = ", ".join(
        item.title for item in capabilities(aspect=ASPECT_STATE)
    ) or "nothing yet"
    plan = InvestigationPlan(
        template="state-refusal",
        title=f"{label} state assessment",
        objective=f"Judge the operational state of {label}.",
        steps=(),
    )
    return InvestigationResult(
        request=request,
        entities=ResolvedEntities(),
        plan=plan,
        findings=(),
        gaps=(
            f"Atlas has no state capability for {label}: {cause}. It "
            f"can currently assess: {supported}.",
        ),
        evidence=(),
        summary=(
            f"Atlas cannot assess the {label} operational state — "
            f"{cause}. It can currently assess: {supported}. It will "
            "not claim health it has not checked."
        ),
        confidence=CONFIDENCE_UNKNOWN,
        confidence_basis=(
            "the question asks for a state assessment Atlas has no "
            "capability for"
        ),
        engines_used=(),
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
    elif template.domain == "validation":
        # PR-172: ONE summary for every subject's validation — the
        # subject contributes its label, nothing else.
        from .subjects import label_for

        label = label_for(
            context.request.subject or context.request.protocol
        )
        from .validation import (
            VERDICT_NON_COMPLIANT,
            VERDICT_NOT_APPLICABLE,
            VERDICT_PARTIAL,
        )

        validation = facts.get("validation") or {}
        counts = validation.get("counts") or {}
        passed = int(counts.get("pass") or 0)
        failed = int(counts.get("fail") or 0)
        warned = int(counts.get("warning") or 0)
        unknown = int(counts.get("unknown") or 0)
        not_applicable = int(counts.get("not_applicable") or 0)
        judged = passed + failed + warned
        not_judged = int(facts.get("validation_not_judged") or 0)
        na_devices = int(facts.get("validation_not_applicable") or 0)
        # PR-172: the summary SPEAKS the verdict projection the
        # validation engine already computed and stored — it never
        # re-judges, and it may never contradict it. Every branch
        # below is keyed on the projection first, raw counts second
        # (the counts-only fallbacks cover runs where the projection
        # could not be computed at all).
        projection = facts.get("validation_verdict") or {}
        term = str(projection.get("verdict") or "")
        tone = str(projection.get("tone") or "")
        if facts.get("validation_no_policies"):
            sentences.append(
                f"Atlas has no configuration policies for {label} in "
                "the active policy pack, so it cannot judge this "
                "configuration — and it will not claim compliance it "
                "has not checked."
            )
            confidence = CONFIDENCE_UNKNOWN
            basis = "no policy in the active pack judges this subject"
        elif term == VERDICT_NOT_APPLICABLE:
            # PR-172 (R1): every evaluation was not applicable AND
            # every device in scope was actually examined — the
            # projection only says "Not applicable" when nothing in
            # scope went unevaluated, so this positive claim never
            # covers a device Atlas has not seen.
            sentences.append(
                f"No device in scope has {label} configured — the "
                f"{not_applicable} evaluation(s) were not applicable. "
                "Atlas does not report absence as compliance."
            )
            confidence = CONFIDENCE_HIGH
            basis = (
                f"{not_applicable} evaluation(s) by the policy engine; "
                "none applied to the devices in scope"
            )
        elif judged == 0:
            # Not enough evidence — nothing could be judged, whether
            # because evaluations came back unknown, devices in scope
            # were never evaluated, or the engine produced nothing.
            # Never a compliance sentence, never a positive claim.
            sentences.append(
                f"The {label} configuration could not be judged: "
                "Atlas does not have enough evidence."
                if projection else
                f"The policy engine produced no {label} evaluations "
                "for this scope, so the configuration could not be "
                "judged."
            )
            if not_applicable:
                sentences.append(
                    f"{not_applicable} evaluation(s) were not "
                    "applicable — those devices do not have "
                    f"{label} configured."
                )
            if unknown:
                sentences.append(
                    f"{unknown} evaluation(s) could not be judged and "
                    "remain unknown."
                )
            if not_judged:
                sentences.append(
                    f"{not_judged} device(s) in scope have no "
                    "configuration evidence and were not judged."
                )
            confidence = CONFIDENCE_UNKNOWN
            basis = (
                "nothing in scope could be judged"
                if projection else
                "no evaluations were produced for the scope"
            )
        else:
            # Wording is deliberate: "failed" appears only for grave
            # (critical/high) violations, so the presentation layer's
            # existing markers map the verdict onto the right chip —
            # Attention for grave, Warning for medium/low, Healthy for
            # a full pass — with no new status vocabulary.
            if term == VERDICT_NON_COMPLIANT and tone == "warning":
                sentences.append(
                    f"{label} configuration: Non-compliant — "
                    f"{failed + warned} violation(s) at medium or low "
                    f"severity; {passed} of {judged} judged "
                    "evaluation(s) pass."
                )
            elif term == VERDICT_NON_COMPLIANT or failed or warned:
                sentences.append(
                    f"{label} configuration: Non-compliant — "
                    f"{failed} evaluation(s) failed; {passed} "
                    f"of {judged} judged evaluation(s) pass."
                )
            elif term == VERDICT_PARTIAL:
                sentences.append(
                    f"{label} configuration: Partially verified — "
                    f"{passed} of {judged} judged evaluation(s) pass; "
                    "the rest could not be judged."
                )
            else:
                sentences.append(
                    f"{label} configuration: Compliant — every judged "
                    f"evaluation passed ({passed} of {judged})."
                )
            if warned:
                sentences.append(f"{warned} warning(s).")
            if na_devices:
                sentences.append(
                    f"{na_devices} device(s) in scope do not have "
                    f"{label} configured and were reported as not "
                    "applicable, never as compliant."
                )
            if unknown:
                sentences.append(
                    f"{unknown} evaluation(s) could not be judged and "
                    "remain unknown."
                )
            if not_judged:
                sentences.append(
                    f"{not_judged} device(s) in scope have no "
                    "configuration evidence and were not judged."
                )
            confidence = (
                CONFIDENCE_HIGH if not unknown and not not_judged
                else CONFIDENCE_MEDIUM
            )
            basis = (
                f"{judged + unknown} evaluation(s) by the policy engine "
                f"across {int(validation.get('policies') or 0)} {label} "
                "polic" + ("y" if int(validation.get("policies") or 0) == 1
                           else "ies")
            )
    elif template.domain == "state":
        # PR-173: ONE summary for every subject's state assessment.
        # The summary SPEAKS the stored projection and never
        # re-judges; the observation age appears in every verdict
        # sentence, because state is only as true as it is recent.
        from .validation import (
            VERDICT_DEGRADED,
            VERDICT_FAILED,
            VERDICT_NOT_APPLICABLE,
        )

        state = facts.get("state_validation") or {}
        projection = facts.get("state_verdict") or {}
        term = str(projection.get("verdict") or "")
        tone = str(projection.get("tone") or "")
        title = str(state.get("title") or "Operational state")
        label = str(state.get("subject") or "the subject")
        counts = state.get("counts") or {}
        passed = int(counts.get("pass") or 0)
        failed = int(counts.get("fail") or 0)
        unknown = int(counts.get("unknown") or 0)
        stale = int(counts.get("stale") or 0)
        not_applicable = int(counts.get("not_applicable") or 0)
        judged = passed + failed
        age = str(state.get("age_sentence") or "")
        unevaluated = int(state.get("unevaluated") or 0)
        stale_devices = int(state.get("stale_devices") or 0)
        if not state:
            sentences.append(
                f"The state engine produced no evaluations for this "
                "scope, so the operational state could not be judged."
            )
            confidence = CONFIDENCE_UNKNOWN
            basis = "no evaluations were produced for the scope"
        elif term == VERDICT_NOT_APPLICABLE:
            sentences.append(
                f"No device in scope runs {label} — the graph holds "
                f"no {title} observations for them. Atlas does not "
                "report absence as health."
            )
            confidence = CONFIDENCE_HIGH
            basis = (
                f"{not_applicable} evaluation(s) by the state engine; "
                "none applied to the devices in scope"
            )
        elif judged == 0:
            sentences.append(
                f"The {title} could not be judged: "
                f"{projection.get('cause') or 'not enough evidence'}."
            )
            if stale_devices:
                sentences.append(
                    f"{stale_devices} device(s) hold observations "
                    "older than the staleness horizon — stale state "
                    "cannot prove current health."
                )
            confidence = CONFIDENCE_UNKNOWN
            basis = "nothing in scope could be judged"
        else:
            observations = state.get("observations") or {}
            in_state = int(observations.get("ok") or 0)
            total = int(observations.get("total") or 0)
            outside = max(0, total - in_state)
            if term == VERDICT_FAILED:
                sentences.append(
                    f"{title}: Failed — no observation is in its "
                    f"expected state (0 of {total}); {age}."
                )
            elif term == VERDICT_DEGRADED and tone == "warning":
                sentences.append(
                    f"{title}: {outside} of {total} observation(s) "
                    "below par at medium or low severity; "
                    f"{in_state} in their expected state; {age}."
                )
            elif term == VERDICT_DEGRADED or failed:
                sentences.append(
                    f"{title}: Degraded — {in_state} of {total} "
                    f"observation(s) in their expected state; "
                    f"{outside} outside; {age}."
                )
            else:
                sentences.append(
                    f"{title}: Healthy — every observation is in its "
                    f"expected state ({in_state} of {total}); {age}."
                )
            if state.get("ageing"):
                sentences.append(
                    "The evidence is ageing — treat this as the state "
                    "at last observation, not this instant."
                )
            if not_applicable:
                sentences.append(
                    f"{not_applicable} evaluation(s) were not "
                    f"applicable — those devices do not run {label}."
                )
            if stale_devices:
                sentences.append(
                    f"{stale_devices} device(s) were not judged: their "
                    "observations are older than the staleness horizon."
                )
            if unknown:
                sentences.append(
                    f"{unknown} evaluation(s) could not be judged and "
                    "remain unknown."
                )
            if unevaluated:
                sentences.append(
                    f"{unevaluated} device(s) in scope hold no "
                    "observations and were not judged."
                )
            confidence = (
                CONFIDENCE_HIGH
                if not unknown and not stale_devices and not unevaluated
                and not state.get("ageing")
                else CONFIDENCE_MEDIUM
            )
            basis = (
                f"{judged} evaluation(s) by the state engine across "
                f"{int(state.get('rules') or 0)} state rule(s); {age}"
            )
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
