"""The Advisor engine: route a question, orchestrate engines, cite evidence.

Every handler REUSES an existing Atlas service — search, federation,
path intelligence (pure engine, no persistence), prediction (pure
engine), Compass repository, discovery history, intelligence reports —
and records the steps it actually performed. Nothing here computes
network facts of its own; when the evidence is missing, the response
says so and recommends the workflow that would produce it.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from founderos_atlas.federation import (
    enterprise_failed_hosts,
    overall_freshness,
)
from founderos_atlas.history import HistoryRepository
from founderos_atlas.workspace import profile_scope

from .models import (
    AdvisorResponse,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNKNOWN,
    EvidenceItem,
    FollowUp,
    NO_EVIDENCE_MESSAGE,
    confidence_from_band,
)
from . import router


@dataclass(frozen=True)
class AdvisorContext:
    """Everything Advisor consults — provided by the caller, cached
    upstream (the same enterprise graph and search index the GUI uses)."""

    base_output_dir: Path
    profiles: tuple
    graph: object            # federation EnterpriseGraph
    snapshot: dict | None    # the federated snapshot dict (or None)
    search_index: object     # search SearchIndex
    generated_at: str
    # PR-172: the caller may supply its own policy evaluation — the web
    # layer passes the SAME governed, context-rich evaluation the
    # /policy page renders, so a validation verdict and the policy page
    # can never disagree about the same estate. None -> the advisor's
    # own ungoverned fallback (headless/tests).
    policy_runner: object = None
    # PR-173: the workspace's state-staleness horizon in minutes — how
    # old an observation may be and still support a health verdict.
    # None -> the engine's 60-minute default.
    state_horizon_minutes: int | None = None


def answer(question: str, context: AdvisorContext) -> AdvisorResponse:
    """One structured, evidence-cited response for one question.

    PR-164: the Operational Intent Router decides WHICH engine answers
    and WHAT the operator's goal is; the matching handler produces the
    evidence-cited answer exactly as before; the route's decision —
    intent, domain, routing confidence, why, and the intent's declared
    workflows and limitations — is attached ADDITIVELY so presentation
    can explain the routing without any engine recomputing anything.
    """

    from dataclasses import replace

    sites = tuple(getattr(context.graph, "sites", ()) or ())
    route = router.route(question, sites=sites)

    # PR-171: ONE understanding, attached to every answer. The same
    # extraction the investigator uses — never a second classifier —
    # with each dimension carrying the basis for its own determination,
    # so the answer can show why it was read the way it was.
    understanding = _understanding_payload(question, context)

    # PR-167: a question that NAMES something specific is an
    # investigation, not a request for one engine. The investigator
    # plans and runs several engines over the named scope and answers
    # about THAT. It returns None for estate-wide questions, which then
    # take the existing single-engine path unchanged — so "Explain
    # enterprise health" still answers exactly as it always has.
    investigation = _investigate(question, context)
    if investigation is not None:
        return replace(
            _investigation_response(question, route.engine, investigation,
                                    context),
            operational_intent=_intent_payload(route),
            understanding=understanding,
        )

    # PR-171: dispatch reads the OBJECTIVE as well as the engine. The
    # resolved intent used to survive only as display decoration — Atlas
    # recognised "OSPF" in a configuration question and still answered
    # with the enterprise summary, because dispatch saw only
    # engine="health". An (engine, objective) pair now selects a
    # specific handler first; every pre-existing intent declares the
    # default objective ("assess"), so the fallback to the engine-only
    # table reproduces the old behaviour exactly.
    objective = getattr(route.intent, "objective", "assess")
    handler = _OBJECTIVE_HANDLERS.get(
        (route.engine, objective)
    ) or _HANDLERS.get(route.engine, _answer_unknown)
    response = handler(question, route.engine, context)
    return replace(
        response, operational_intent=_intent_payload(route),
        understanding=understanding,
    )


def _understanding_payload(question: str, context: AdvisorContext) -> dict:
    """The five dimensions of one question, as stored JSON.

    Every value is the investigator's own extraction — deterministic
    vocabularies over the operator's words — and ``basis`` states why
    each dimension was chosen. Tolerant by design: understanding is
    presentation support, and a failure here must never cost an answer.
    """

    try:
        from founderos_atlas.investigation.orchestrator import understand
        from founderos_atlas.investigation.subjects import label_for

        request = understand(question, context.graph)
        relationship = None
        if request.source or request.destination or request.direction:
            relationship = {
                "source": request.source,
                "destination": request.destination,
                "direction": request.direction,
            }
        return {
            "subject": request.subject,
            "subject_label": (
                label_for(request.subject) if request.subject else ""
            ),
            "objective": request.objective,
            "scope": request.scope,
            "sites": list(request.sites),
            "time_range": request.time_range,
            "relationship": relationship,
            "basis": list(request.basis),
        }
    except Exception:  # noqa: BLE001 - understanding must not cost answers
        import logging

        logging.getLogger("atlas").warning(
            "question understanding failed; answering without it",
            exc_info=True,
        )
        return {}


def _investigate(question: str, context: AdvisorContext):
    """Run the investigator, or None.

    The operator must never lose an answer to a failing investigation,
    so this falls back to the single-engine path. But a swallowed
    failure once made the whole feature silently do nothing, so the
    reason is LOGGED rather than discarded — an invisible fallback is
    indistinguishable from a feature that was never wired up.
    """

    import logging

    from founderos_atlas.investigation import investigate

    try:
        return investigate(
            question, graph=context.graph, snapshot=context.snapshot,
            change_report=_change_report_summary(context),
            policy_runner=_policy_runner(context),
            state_horizon_minutes=context.state_horizon_minutes,
        )
    except Exception:  # noqa: BLE001 - fall back to the single engine
        logging.getLogger("atlas").warning(
            "investigation failed; falling back to the single engine",
            exc_info=True,
        )
        return None


def _policy_runner(context: AdvisorContext):
    """A lazy policy evaluation over every profile's Enterprise Memory.

    The investigator deliberately cannot reach the workspace — it reads
    the graph and snapshot it is handed. Policy evaluation needs the
    per-scope memory stores, so the ADVISOR builds this closure and the
    validation template invokes it only when it actually runs. Returns
    None when no scope has a memory store, which the engine reports as
    "could not be judged" — never as compliant.

    When the caller supplied its own runner (PR-172: the web layer's
    governed, device-context-aware evaluation — the same one /policy
    renders), that runner wins: two surfaces, one judgement.
    """

    if callable(context.policy_runner):
        return context.policy_runner

    def run():
        from founderos_atlas.enterprise_memory import (
            EnterpriseMemory,
            EnterpriseMemoryStore,
        )
        from founderos_atlas.policy import PolicyEngine

        memories = []
        for profile in context.profiles or ():
            scope = profile_scope(
                context.base_output_dir, profile.profile_id, profile.name
            )
            store_dir = scope.output_dir / "enterprise-memory"
            if not store_dir.is_dir():
                continue
            memories.append((
                profile.name,
                EnterpriseMemory(EnterpriseMemoryStore(store_dir)),
            ))
        if not memories:
            return None
        return PolicyEngine().evaluate_scopes(
            memories, scope_label="Enterprise"
        )

    return run


def _change_report_summary(context: AdvisorContext) -> dict | None:
    """A count of recorded changes for the scope, if one is stored."""

    total = 0
    found = False
    for profile in context.profiles or ():
        scope = profile_scope(
            context.base_output_dir, profile.profile_id, profile.name
        )
        report = _read_json(scope.output_dir / "state_change_report.json")
        if isinstance(report, dict):
            found = True
            for key in ("changes", "entries", "items"):
                value = report.get(key)
                if isinstance(value, list):
                    total += len(value)
                    break
    return {"count": total} if found else None


def _investigation_response(
    question: str, engine: str, result, context: AdvisorContext
) -> AdvisorResponse:
    """Turn an investigation into Atlas's standard answer shape.

    The investigation's own summary, findings, gaps and citations
    become the answer — no estate-wide summary is substituted, which is
    the entire point of PR-167.
    """

    evidence = tuple(
        EvidenceItem(label=item.get("label", ""),
                     detail=item.get("detail", ""),
                     href=item.get("href") or None)
        for item in result.evidence
    ) or (_graph_evidence(context),)
    steps = tuple(
        f"{step.label} — {step.status}" for step in result.plan.steps
    )
    followups = [
        FollowUp("Open Topology", href="/topology?scope=all"),
        FollowUp("What changed?", question="What changed?"),
    ]
    if result.request.protocol == "bgp":
        followups.insert(0, FollowUp("Open BGP view",
                                     href="/topology?view=bgp"))
    elif result.request.protocol == "ospf":
        followups.insert(0, FollowUp("Open OSPF view",
                                     href="/topology?view=ospf"))
    return AdvisorResponse(
        question=question, intent=engine,
        summary=result.summary,
        evidence=evidence,
        confidence=result.confidence,
        confidence_basis=result.confidence_basis,
        next_action_label="Open Topology",
        next_action_href="/topology?scope=all",
        followups=tuple(followups),
        unknowns=tuple(result.gaps),
        steps=steps,
        generated_at=context.generated_at,
        investigation=result.to_dict(),
    )


def _intent_payload(route) -> dict:
    """The stored form of one routing decision — plain JSON data, so
    stored conversations replay it without importing OIR."""

    intent = route.intent
    return {
        "name": intent.name,
        "key": intent.key,
        "domain": intent.domain,
        "objective": getattr(intent, "objective", "assess"),
        "description": intent.description,
        "routing_confidence": route.confidence,
        "why": list(route.why),
        "escalated": route.escalated,
        "workflows": [item.to_dict() for item in intent.workflows],
        "recommendations": [
            item.to_dict() for item in intent.recommendations
        ],
        "followups": [item.to_dict() for item in intent.followups],
        "limitations": list(intent.limitations),
        "required_evidence": list(intent.required_evidence),
    }


# -- handlers -------------------------------------------------------------------


def _answer_health(question, intent, context) -> AdvisorResponse:
    """Answer enterprise-health and "is there a problem?" questions from
    the Enterprise Knowledge Graph itself (PR-043.8).

    The graph is the single source of truth: managed devices,
    relationships, routing observations, discovery completeness,
    reconciliation warnings, and unresolved evidence all come from it.
    Intelligence reports, when present, ENRICH the answer with per-profile
    health scores — but Advisor never claims "no evidence" while the graph
    holds managed devices. Missing evidence lowers confidence, not health.
    """

    from founderos_atlas.enterprise import EnterpriseKnowledge
    from founderos_atlas.search import health_by_profile_from_scopes

    steps = ["Reading the Enterprise Knowledge Graph…",
             "Checking discovery completeness and evidence freshness…"]
    knowledge = EnterpriseKnowledge(context.snapshot)
    if not knowledge.has_evidence:
        return _no_evidence(question, intent, steps, context)

    contributions = tuple(getattr(context.graph, "contributions", ()))
    fresh = overall_freshness(contributions) if contributions else True
    stats = knowledge.statistics
    health_level, health_reason = knowledge.health()
    band_raw, basis = knowledge.confidence(fresh=fresh)
    band = confidence_from_band(band_raw)

    summary_bits = [
        f"{knowledge.device_count} managed device(s)",
        f"{knowledge.relationship_count} relationship(s)",
    ]
    if knowledge.routing_observations:
        summary_bits.append(
            f"{knowledge.routing_observations} routing observation(s)"
        )
    summary_bits.append(
        f"discovery {stats.discovery_completeness_percent}% complete"
    )
    if knowledge.unresolved_count:
        summary_bits.append(
            f"{knowledge.unresolved_count} unresolved peer(s)"
        )
    if knowledge.ownership_conflicts:
        summary_bits.append(
            f"{knowledge.ownership_conflicts} ownership conflict(s)"
        )

    # Enrich with per-profile intelligence health scores when they exist.
    scores = health_by_profile_from_scopes(
        context.base_output_dir, context.profiles
    )
    evidence = [_graph_evidence(context)]
    profile_lines = []
    for contribution in contributions:
        score = scores.get(contribution.profile_name)
        if score is not None:
            profile_lines.append(f"{contribution.profile_name} {score}/100")
            evidence.append(
                EvidenceItem(
                    label=f"Intelligence report — {contribution.profile_name}",
                    detail=f"health score {score}/100",
                    href=f"/?scope={contribution.profile_id}",
                )
            )

    summary = (
        f"Enterprise health is {health_level} — {health_reason} "
        f"The graph holds " + ", ".join(summary_bits) + "."
    )
    if profile_lines:
        summary += " Health scores: " + "; ".join(profile_lines) + "."

    unknowns = []
    if stats.authentication_failures:
        unknowns.append(
            f"{stats.authentication_failures} reachable device(s) could not "
            "be authenticated — discovery is incomplete."
        )
    if knowledge.unresolved_count:
        unknowns.append(
            f"{knowledge.unresolved_count} observed peer(s) are not yet "
            "resolved to a managed device."
        )
    return AdvisorResponse(
        question=question, intent=intent,
        summary=summary,
        evidence=tuple(evidence),
        confidence=band, confidence_basis=basis,
        next_action_label="Open Mission", next_action_href="/?scope=all",
        followups=(
            FollowUp("What changed?", question="What changed?"),
            FollowUp("Summarize discovery", question="Summarize discovery"),
            FollowUp("Open enterprise topology", href="/topology?scope=all"),
        ),
        unknowns=tuple(unknowns),
        steps=tuple(steps), generated_at=context.generated_at,
    )


def _answer_changes(question, intent, context) -> AdvisorResponse:
    steps = ["Reviewing change reports per profile…"]
    rows = []
    evidence = []
    for profile in context.profiles:
        scope = profile_scope(
            context.base_output_dir, profile.profile_id, profile.name
        )
        report = _read_json(scope.output_dir / "state_change_report.json")
        if not isinstance(report, dict):
            continue
        changes = report.get("change_count") or 0
        issues = report.get("active_issue_count") or 0
        rows.append((profile.name, changes, issues))
        evidence.append(
            EvidenceItem(
                label=f"Operational state report — {profile.name}",
                detail=f"{changes} change(s), {issues} active issue(s)",
                href=f"/changes?scope={profile.profile_id}",
            )
        )
    if not rows:
        return _no_evidence(
            question, intent, steps, context,
            extra="Change intelligence needs at least two discoveries of "
            "the same profile to compare.",
        )
    total = sum(row[1] for row in rows)
    issues = sum(row[2] for row in rows)
    summary = (
        f"{total} operational change(s) detected across "
        f"{len(rows)} profile(s)"
        + (f", {issues} active issue(s) outstanding" if issues else "")
        + ": " + "; ".join(
            f"{name} — {changes} change(s)"
            + (f", {active} active" if active else "")
            for name, changes, active in rows
        )
        + "."
    )
    return AdvisorResponse(
        question=question, intent=intent, summary=summary,
        evidence=tuple(evidence),
        confidence=CONFIDENCE_HIGH,
        confidence_basis="read directly from each profile's latest "
        "state-change report",
        next_action_label="Review Changes",
        next_action_href="/changes?scope=all",
        followups=(
            FollowUp("Explain enterprise health",
                     question="Explain enterprise health"),
            FollowUp("Investigate a path", href="/paths?scope=all"),
        ),
        steps=tuple(steps), generated_at=context.generated_at,
    )


def _answer_discovery(question, intent, context) -> AdvisorResponse:
    launch = router.discovery_launch(question)
    if launch is not None:
        # A launch/resume request: Advisor guides to the wizard — it
        # never runs side-effectful discovery itself.
        if launch["kind"] == "subnet":
            summary = (
                f"To discover the management network {launch['cidr']}, open "
                "the Discovery Wizard, choose Management Network, and enter "
                f"{launch['cidr']}. Atlas expands it to candidate addresses, "
                "detects each platform, and builds the enterprise graph."
            )
            next_label = "Open the Discovery Wizard"
        elif launch["kind"] == "resume":
            summary = (
                "Interrupted discoveries can be resumed from the Discover "
                "page — already-discovered devices stay cached and only "
                "unfinished candidates are re-attempted."
            )
            next_label = "Open Discovery"
        else:
            summary = (
                "Start discovery from the Discovery Wizard — seed device, "
                "management subnet, multiple seeds, or an imported device "
                "list. Every method produces the same canonical enterprise "
                "model."
            )
            next_label = "Open the Discovery Wizard"
        return AdvisorResponse(
            question=question, intent=intent, summary=summary,
            evidence=(),
            confidence=CONFIDENCE_HIGH,
            confidence_basis="a discovery-launch request routed to its workflow",
            next_action_label=next_label,
            next_action_href=(
                "/discovery" if launch["kind"] == "resume" else "/discovery/wizard"
            ),
            followups=(
                FollowUp("Summarize discovery",
                         question="Summarize discovery"),
                FollowUp("Explain enterprise health",
                         question="Explain enterprise health"),
            ),
            steps=("Classifying the question as a discovery request…",),
            generated_at=context.generated_at,
        )
    steps = ["Reading discovery history per profile…"]
    lines = []
    evidence = []
    unknowns = []
    for profile in context.profiles:
        scope = profile_scope(
            context.base_output_dir, profile.profile_id, profile.name
        )
        record = HistoryRepository(scope.history_root).latest()
        if record is None:
            unknowns.append(f"{profile.name} has never been discovered.")
            continue
        line = (
            f"{profile.name}: {record.device_count} device(s) at "
            f"{record.completed_at}"
        )
        if record.failures:
            line += f" ({len(record.failures)} host(s) unreachable)"
        lines.append(line)
        evidence.append(
            EvidenceItem(
                label=f"Discovery run — {profile.name}",
                detail=f"run {record.record_id}",
                href=f"/history?scope={profile.profile_id}",
            )
        )
    if not lines:
        return _no_evidence(question, intent, steps, context)
    return AdvisorResponse(
        question=question, intent=intent,
        summary="Latest discoveries — " + "; ".join(lines) + ".",
        evidence=tuple(evidence),
        confidence=CONFIDENCE_HIGH,
        confidence_basis="read directly from the archived discovery runs",
        next_action_label="Open History", next_action_href="/history?scope=all",
        followups=(
            FollowUp("Run Discovery", href="/discovery"),
            FollowUp("What changed?", question="What changed?"),
        ),
        unknowns=tuple(unknowns),
        steps=tuple(steps), generated_at=context.generated_at,
    )


def _answer_search(question, intent, context) -> AdvisorResponse:
    from founderos_atlas.search import search_enterprise

    query = router.search_query(question)
    steps = [f"Searching the enterprise for “{query}”…"]
    if not query:
        return _answer_unknown(question, intent, context)
    response = search_enterprise(context.search_index, query)
    if response.total == 0:
        return _no_evidence(
            question, intent, steps, context,
            extra=f"Nothing in the collected evidence matches “{query}”.",
        )
    hit = response.groups[0].results[0]
    detail_bits = []
    detail = hit.entry.detail
    for key in ("management_ips", "platform", "site", "observed_by"):
        value = detail.get(key)
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        if value and value != "—":
            detail_bits.append(f"{key.replace('_', ' ')}: {value}")
    rank = hit.rank_label
    confidence = (
        CONFIDENCE_HIGH if rank.startswith(("exact", "canonical"))
        else CONFIDENCE_MEDIUM if rank.startswith("prefix")
        else CONFIDENCE_LOW
    )
    evidence = [
        EvidenceItem(
            label=hit.entry.title,
            detail=f"matched on {hit.match_field} ({rank})",
            href=hit.entry.href,
        ),
        _graph_evidence(context),
    ]
    if detail.get("confidence_percent"):
        detail_bits.append(
            f"identity confidence {detail['confidence_percent']}%"
        )
    return AdvisorResponse(
        question=question, intent=intent,
        summary=(
            f"Found {hit.entry.title} ({hit.entry.group.rstrip('s')})"
            + (" — " + "; ".join(detail_bits) if detail_bits else "")
            + f". {response.total} result(s) matched in total."
        ),
        evidence=tuple(evidence),
        confidence=confidence,
        confidence_basis=f"search matched on {hit.match_field} ({rank})",
        next_action_label=f"Open {hit.entry.title}",
        next_action_href=hit.entry.href,
        followups=(
            FollowUp("Show enterprise topology", href="/topology?scope=all"),
            FollowUp(
                "Investigate a path from it",
                href="/paths?scope=all",
            ),
            FollowUp("Predict a change on it", href="/predict?scope=all"),
        ),
        steps=tuple(steps), generated_at=context.generated_at,
    )


def _resolves(name: str | None, snapshot: dict | None) -> bool:
    """Whether a name matches a discovered hostname or management IP."""

    if not name or not isinstance(snapshot, dict):
        return False
    wanted = name.casefold()
    for device in snapshot.get("devices") or ():
        if not isinstance(device, dict):
            continue
        if str(device.get("hostname") or "").casefold() == wanted:
            return True
        if str(device.get("management_ip") or "").casefold() == wanted:
            return True
    return False


def _answer_path(question, intent, context) -> AdvisorResponse:
    source, destination = router.path_endpoints(question)
    # A parse that resolves to NO evidence (e.g. "Users cannot reach the
    # branch") is treated as unparsed: route to the workflow instead of
    # investigating tokens that are plainly not devices.
    if source and destination and not (
        _resolves(source, context.snapshot)
        or _resolves(destination, context.snapshot)
    ):
        source = destination = None
    if not source or not destination or context.snapshot is None:
        steps = ["Classifying the question as a connectivity investigation…"]
        return AdvisorResponse(
            question=question, intent=intent,
            summary=(
                "This is a connectivity investigation. Pick the source and "
                "destination devices and Atlas will walk the evidence hop "
                "by hop, stopping at the first deterministic failure."
                if context.snapshot is not None
                else "This is a connectivity investigation, but no topology "
                "evidence exists yet — run a discovery first."
            ),
            evidence=(_graph_evidence(context),) if context.snapshot else (),
            confidence=CONFIDENCE_HIGH if context.snapshot else CONFIDENCE_UNKNOWN,
            confidence_basis="deterministic intent match"
            if context.snapshot else "no topology snapshot exists",
            next_action_label="Open Path Intelligence",
            next_action_href="/paths?scope=all",
            steps=tuple(steps), generated_at=context.generated_at,
        )
    steps = [
        f"Running a path investigation {source} → {destination} against "
        "the enterprise snapshot…",
        "Checking the latest discovery failures…",
    ]
    from founderos_atlas.path_intelligence import investigate_path

    result = investigate_path(
        source,
        destination,
        snapshot=context.snapshot,
        generated_at=context.generated_at,
        fresh=overall_freshness(tuple(context.graph.contributions)),
        failed_hosts=enterprise_failed_hosts(
            context.base_output_dir, context.profiles
        ),
    )
    if result.status == "connected":
        summary = (
            f"{source} can reach {destination} on the known path "
            f"{' → '.join(result.path)}: every hop passed validation."
        )
    elif result.status == "failed":
        summary = (
            f"{source} cannot reach {destination}: {result.failure_summary}"
        )
    else:
        summary = (
            f"The {source} → {destination} path is {result.status}: "
            f"{result.failure_summary or 'see the investigation detail.'}"
        )
    evidence = [_graph_evidence(context)]
    evidence.extend(
        EvidenceItem(label="Path evidence", detail=item,
                     href="/paths?scope=all")
        for item in result.evidence_refs[:2]
    )
    return AdvisorResponse(
        question=question, intent=intent, summary=summary,
        evidence=tuple(evidence),
        confidence=confidence_from_band(result.confidence_band),
        confidence_basis=(
            f"path investigation confidence {result.confidence_percent}% "
            f"({result.confidence_band})"
        ),
        next_action_label="Open Path Intelligence",
        next_action_href="/paths?scope=all",
        followups=(
            FollowUp("Show enterprise topology", href="/topology?scope=all"),
            FollowUp("What changed?", question="What changed?"),
        ),
        unknowns=result.unknowns[:3],
        steps=tuple(steps), generated_at=context.generated_at,
    )


def _answer_prediction(question, intent, context) -> AdvisorResponse:
    device, interface = router.prediction_target(question)
    snapshot = context.snapshot or {}
    entry = None
    if device:
        entry = next(
            (
                item
                for item in snapshot.get("devices") or ()
                if isinstance(item, dict)
                and str(item.get("hostname") or "").casefold()
                == device.casefold()
            ),
            None,
        )
    if entry is None:
        steps = ["Classifying the question as a change prediction…"]
        return AdvisorResponse(
            question=question, intent=intent,
            summary=(
                "This is a change prediction. Pick the device and interface "
                "and Atlas will predict blast radius, risk, and confidence "
                "before anything is touched."
                if device is None
                else f"'{device}' is not in the enterprise's discovered "
                "evidence, so Atlas cannot predict against it — check the "
                "name or run a discovery."
            ),
            evidence=(_graph_evidence(context),) if context.snapshot else (),
            confidence=CONFIDENCE_HIGH if device is None else CONFIDENCE_UNKNOWN,
            confidence_basis="deterministic intent match"
            if device is None else "the named device has no evidence",
            next_action_label="Open Predict",
            next_action_href="/predict?scope=all",
            steps=tuple(steps), generated_at=context.generated_at,
        )
    from founderos_atlas.prediction import ChangeRequest, predict, resolve_interface

    device = str(entry.get("hostname"))
    change_type = "shutdown-interface"
    canonical = None
    if interface:
        inventory = tuple(
            str(item.get("name"))
            for item in entry.get("interfaces") or ()
            if isinstance(item, dict) and item.get("name")
        )
        canonical, problem = resolve_interface(interface, inventory)
        if canonical is None:
            return _no_evidence(
                question, intent,
                [f"Resolving interface “{interface}” on {device}…"],
                context,
                extra=f"Interface not accepted for {device}: {problem}.",
            )
    else:
        change_type = "reboot-device"
    steps = [
        f"Running a {change_type} prediction for "
        f"{device}{' ' + canonical if canonical else ''}…",
    ]
    prediction = predict(
        ChangeRequest(
            request_id="advisor",
            change_type=change_type,
            target_device=device,
            target_object=canonical,
            requested_at=context.generated_at,
        ),
        snapshot=context.snapshot,
        generated_at=context.generated_at,
        fresh=overall_freshness(tuple(context.graph.contributions)),
    )
    blast = prediction.blast_radius
    return AdvisorResponse(
        question=question, intent=intent,
        summary=(
            f"Predicted risk of {change_type} on "
            f"{device}{' ' + canonical if canonical else ''}: "
            f"{prediction.risk.level} (score {prediction.risk.score}). "
            f"{blast.summary} Recommendation: {prediction.advice.action}"
        ),
        evidence=(
            _graph_evidence(context),
            EvidenceItem(
                label="Prediction",
                detail=f"{len(prediction.risk.factors)} documented risk "
                "factor(s); evidence-based blast radius",
                href="/predict?scope=all",
            ),
        ),
        confidence=confidence_from_band(prediction.confidence.band),
        confidence_basis=(
            f"prediction confidence {prediction.confidence.percent}% "
            f"({prediction.confidence.band})"
        ),
        next_action_label="Open Predict",
        next_action_href="/predict?scope=all",
        followups=(
            FollowUp("Plan it with Compass", href="/compass"),
            FollowUp("Show enterprise topology", href="/topology?scope=all"),
        ),
        unknowns=prediction.unknowns[:3],
        steps=tuple(steps), generated_at=context.generated_at,
    )


def _answer_compass(question, intent, context) -> AdvisorResponse:
    from founderos_atlas.compass import PlanRepository

    steps = ["Reading maintenance plans from Compass…"]
    repository = PlanRepository(context.base_output_dir)
    plans = repository.list_plans()
    if not plans:
        return AdvisorResponse(
            question=question, intent=intent,
            summary=(
                "No maintenance plans exist yet. Create one in Compass and "
                "Atlas will analyse every change, derive evidence-based "
                "dependencies, and recommend a safer execution order."
            ),
            evidence=(),
            confidence=CONFIDENCE_HIGH,
            confidence_basis="the Compass plan repository is empty",
            next_action_label="Open Compass", next_action_href="/compass",
            steps=tuple(steps), generated_at=context.generated_at,
        )
    drafts = [plan for plan in plans if plan.status != "analysed"]
    latest = plans[-1]
    _, assessment = repository.get(latest.plan_id)
    risk = (assessment or {}).get("risk", {}).get("overall_risk") if assessment else None
    summary = (
        f"{len(plans)} maintenance plan(s): "
        f"{len(drafts)} awaiting analysis, "
        f"{len(plans) - len(drafts)} analysed. Latest: “{latest.title}” "
        f"({latest.maintenance_window or 'no window'}, "
        f"{len(latest.changes)} change(s)"
        + (f", plan risk {risk}" if risk else "")
        + ")."
    )
    return AdvisorResponse(
        question=question, intent=intent, summary=summary,
        evidence=(
            EvidenceItem(
                label=f"Maintenance plan — {latest.title}",
                detail=f"status {latest.status}",
                href=f"/compass/{latest.plan_id}",
            ),
        ),
        confidence=CONFIDENCE_HIGH,
        confidence_basis="read directly from the Compass plan repository",
        next_action_label=f"Open “{latest.title}”",
        next_action_href=f"/compass/{latest.plan_id}",
        followups=(
            FollowUp("Open Compass", href="/compass"),
            FollowUp("Predict a change first", href="/predict?scope=all"),
        ),
        steps=tuple(steps), generated_at=context.generated_at,
    )


def _latest_investigation(context) -> dict | None:
    from founderos_atlas.federation import enterprise_scope_dir
    from founderos_atlas.path_intelligence import load_investigation_history

    candidates: list[tuple[str, str, dict]] = []
    for entry in load_investigation_history(
        enterprise_scope_dir(context.base_output_dir)
    )[:3]:
        candidates.append((str(entry.get("generated_at") or ""), "all", entry))
    for profile in context.profiles:
        scope = profile_scope(
            context.base_output_dir, profile.profile_id, profile.name
        )
        for entry in load_investigation_history(scope.output_dir)[:3]:
            candidates.append(
                (str(entry.get("generated_at") or ""), profile.profile_id, entry)
            )
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    when, scope_id, entry = candidates[0]
    return {"scope_id": scope_id, "entry": entry}


def _answer_continue(question, intent, context) -> AdvisorResponse:
    steps = ["Looking up your most recent investigation…"]
    latest = _latest_investigation(context)
    if latest is None:
        return _no_evidence(
            question, intent, steps, context,
            extra="No stored investigation exists to continue.",
        )
    entry = latest["entry"]
    href = f"/paths?scope={latest['scope_id']}"
    return AdvisorResponse(
        question=question, intent=intent,
        summary=(
            f"Your most recent investigation is "
            f"{entry.get('source')} → {entry.get('destination')} "
            f"({entry.get('status')}, {entry.get('generated_at')}). "
            "It is stored with its full evidence — resume it in Path "
            "Intelligence."
        ),
        evidence=(
            EvidenceItem(
                label="Stored investigation",
                detail=(
                    f"{entry.get('source')} → {entry.get('destination')}, "
                    f"confidence {entry.get('confidence_percent')}%"
                ),
                href=href,
            ),
        ),
        confidence=CONFIDENCE_HIGH,
        confidence_basis="the investigation is stored with its evidence",
        next_action_label="Resume Investigation", next_action_href=href,
        followups=(
            FollowUp("What changed since?", question="What changed?"),
            FollowUp("Open Mission", href="/?scope=all"),
        ),
        steps=tuple(steps), generated_at=context.generated_at,
    )


def _answer_investigation(question, intent, context) -> AdvisorResponse:
    response = _answer_continue(question, intent, context)
    return response


def _answer_enterprise(question, intent, context) -> AdvisorResponse:
    steps = ["Reading the enterprise graph…"]
    graph = context.graph
    if not getattr(graph, "devices", ()):
        return _no_evidence(question, intent, steps, context)
    sites = ", ".join(graph.sites) or "no sites inferred"
    return AdvisorResponse(
        question=question, intent=intent,
        summary=(
            f"The enterprise has {graph.device_count} canonical device(s) "
            f"from {graph.observation_count} observation(s) across "
            f"{len(graph.contributions)} profile(s); "
            f"{graph.merged_device_count} device(s) merged on strong "
            f"evidence; {len(graph.cross_profile_links)} cross-profile "
            f"link(s); {len(graph.boundaries)} unknown boundary(ies). "
            f"Sites: {sites}."
        ),
        evidence=(
            _graph_evidence(context),
            EvidenceItem(
                label="Enterprise inventory",
                detail="canonical devices with provenance",
                href="/topology?scope=all",
            ),
        ),
        confidence=CONFIDENCE_HIGH,
        confidence_basis="counted directly from the federated graph",
        next_action_label="Open Enterprise Topology",
        next_action_href="/topology?scope=all",
        followups=(
            FollowUp("Explain enterprise health",
                     question="Explain enterprise health"),
            FollowUp("Summarize discovery", question="Summarize discovery"),
        ),
        steps=tuple(steps), generated_at=context.generated_at,
    )


def _answer_unknown(question, intent, context) -> AdvisorResponse:
    return AdvisorResponse(
        question=question, intent=router.INTENT_UNKNOWN,
        summary=(
            f"{NO_EVIDENCE_MESSAGE} Atlas Advisor answers only from "
            "collected evidence — it never guesses. I can explain "
            "enterprise health, summarize discoveries and changes, find "
            "devices, walk connectivity paths, predict change impact, and "
            "summarize maintenance plans."
        ),
        evidence=(),
        confidence=CONFIDENCE_UNKNOWN,
        confidence_basis="the question does not map onto collected evidence",
        next_action_label="Search the Enterprise",
        next_action_href="/topology?scope=all",
        followups=(
            FollowUp("Run Discovery", href="/discovery"),
            FollowUp("Open an Investigation", href="/paths?scope=all"),
            FollowUp("Run a Prediction", href="/predict?scope=all"),
            FollowUp("Explain enterprise health",
                     question="Explain enterprise health"),
        ),
        unknowns=("This question is outside the evidence Atlas collects.",),
        steps=("Classifying the question…",),
        generated_at=context.generated_at,
    )


# -- shared helpers ---------------------------------------------------------------


def _no_evidence(question, intent, steps, context, *, extra: str | None = None):
    return AdvisorResponse(
        question=question, intent=intent,
        summary=NO_EVIDENCE_MESSAGE + (f" {extra}" if extra else ""),
        evidence=(),
        confidence=CONFIDENCE_UNKNOWN,
        confidence_basis="the required evidence has not been collected",
        next_action_label="Run Discovery", next_action_href="/discovery",
        followups=(
            FollowUp("Open an Investigation", href="/paths?scope=all"),
            FollowUp("Run a Prediction", href="/predict?scope=all"),
            FollowUp("Search the Enterprise", href="/topology?scope=all"),
        ),
        unknowns=(NO_EVIDENCE_MESSAGE,),
        steps=tuple(steps), generated_at=context.generated_at,
    )


def _graph_evidence(context) -> EvidenceItem:
    snapshot_id = str((context.snapshot or {}).get("snapshot_id") or "none")
    return EvidenceItem(
        label="Enterprise Graph",
        detail=f"federated snapshot {snapshot_id.split(':')[-1][:12]}",
        href="/topology?scope=all",
    )


def _read_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _answer_validate(question, intent, context) -> AdvisorResponse:
    """Answer a configuration-validation question by orchestrating the
    EXISTING policy engine (PR-171).

    The investigator normally owns this path — it runs before dispatch
    and produces the richer plan-and-findings answer. This handler is
    the resilience path for when the investigation itself failed: it
    reuses the SAME extraction and the SAME aggregation helper, so the
    two paths cannot disagree, and it re-implements no matching. When
    the subject cannot be judged, it refuses — the estate summary is
    never substituted for a validation question.
    """

    from founderos_atlas.investigation.engines import (
        aggregate_policy_report,
    )
    from founderos_atlas.investigation.orchestrator import understand
    from founderos_atlas.investigation.subjects import (
        label_for,
        subject as subject_of,
    )

    steps = ["Understanding the validation question…",
             "Evaluating the enterprise policy pack…"]
    request = understand(question, context.graph)
    descriptor = subject_of(request.subject or request.protocol)
    label = label_for(request.subject or request.protocol)
    tags = tuple(descriptor.policy_tags) if descriptor else ()

    def refusal(reason: str, basis: str) -> AdvisorResponse:
        return AdvisorResponse(
            question=question, intent=intent,
            summary=reason,
            evidence=(_graph_evidence(context),),
            confidence=CONFIDENCE_UNKNOWN,
            confidence_basis=basis,
            next_action_label="Open Policy",
            next_action_href="/policy",
            followups=(
                FollowUp("Open Policy results", href="/policy"),
                FollowUp("Is the network healthy?",
                         question="Is the network healthy?"),
            ),
            unknowns=(reason,),
            steps=tuple(steps), generated_at=context.generated_at,
        )

    from founderos_atlas.investigation.validation import (
        capabilities as _capabilities,
        capability as _capability,
    )

    # PR-172: the "can currently validate" list is READ from the
    # capability registry — the same single source of truth the
    # orchestrator's refusal reads, so the two paths can never
    # disagree about what Atlas can do.
    supported = ", ".join(
        item.title for item in _capabilities()
    ) or "nothing yet"
    subject_key = request.subject or request.protocol
    if not subject_key or subject_key == "configuration":
        # A validation-worded question that names NO subject Atlas
        # recognises ("is anything misconfigured?"). The orchestrator's
        # refusal phrasing, not "the  configuration" with a hole in it.
        return refusal(
            "Atlas cannot validate this configuration as asked — the "
            "question names no subject it recognises. It can currently "
            f"validate: {supported}. It will not claim compliance it "
            "has not checked.",
            "the question names no subject Atlas can validate",
        )
    if _capability(subject_key) is None:
        return refusal(
            f"Atlas cannot validate the {label} configuration — it has "
            f"no validation rules for {label}. It can currently "
            f"validate: {supported}. It will not claim compliance it "
            "has not checked.",
            "no policy in the active pack judges this subject",
        )
    report = _policy_runner(context)()
    if report is None:
        return refusal(
            f"Atlas cannot judge the {label} configuration: no scope "
            "has collected configuration evidence yet.",
            "no Enterprise Memory store exists for any scope",
        )
    # Vetted rules come from the pack THIS REPORT was judged with —
    # the governance-effective pack when the web layer supplied the
    # runner — so verdict and /policy read one rule set (PR-172).
    report_pack = getattr(report, "pack", None)
    cap = (
        _capability(subject_key, report_pack)
        if report_pack is not None else _capability(subject_key)
    )
    aggregate = aggregate_policy_report(
        report, tags=tags, scope_hostnames=frozenset(),
        rule_ids=frozenset(cap.rules) if cap else frozenset(),
    )
    if not aggregate["policies"]:
        if report_pack is not None and cap is not None:
            return refusal(
                f"The policy engine produced no {label} evaluations "
                "for this scope, so the configuration could not be "
                "judged.",
                "no evaluations were produced for the scope",
            )
        return refusal(
            f"Atlas has no configuration policies for {label} in the "
            "active policy pack, so it cannot judge this configuration.",
            "the active pack carries no policy tagged for this subject",
        )

    from founderos_atlas.investigation.validation import (
        VERDICT_NON_COMPLIANT,
        VERDICT_NOT_APPLICABLE,
        VERDICT_PARTIAL,
        verdict_for,
    )

    counts = aggregate["counts"]
    judged = counts["pass"] + counts["fail"] + counts["warning"]
    not_applicable = int(counts.get("not_applicable") or 0)
    na_devices = len(aggregate.get("devices_not_applicable") or ())
    scope_count = len(tuple(getattr(context.graph, "devices", ()) or ()))
    projection = verdict_for(aggregate, scope_count=scope_count)
    term = projection["verdict"]
    if term == VERDICT_NOT_APPLICABLE:
        # PR-172 (R1): nothing applied — the subject is not configured
        # anywhere in scope. A determination, never a compliance claim.
        summary = (
            f"No device in scope has {label} configured — the "
            f"{not_applicable} evaluation(s) were not applicable. "
            "Atlas does not report absence as compliance."
        )
    elif term == VERDICT_NON_COMPLIANT and projection["tone"] == "warning":
        summary = (
            f"{label} configuration: Non-compliant — "
            f"{counts['fail'] + counts['warning']} violation(s) at "
            f"medium or low severity; {counts['pass']} of {judged} "
            "judged pass."
        )
    elif term == VERDICT_NON_COMPLIANT:
        summary = (
            f"{label} configuration: Non-compliant — "
            f"{counts['fail'] + counts['warning']} evaluation(s) "
            f"failed; {counts['pass']} of {judged} judged pass."
        )
    elif term == VERDICT_PARTIAL:
        summary = (
            f"{label} configuration: Partially verified — "
            f"{counts['pass']} of {judged} judged evaluation(s) pass; "
            "the rest could not be judged."
        )
    elif judged == 0:
        # "Not enough evidence" — the projection's own words; never
        # a compliance sentence over zero judged devices.
        summary = (
            f"{label} configuration: nothing in scope could be judged "
            f"— {projection['cause']}."
        )
    else:
        summary = (
            f"{label} configuration: Compliant — every judged "
            f"evaluation passed ({counts['pass']} of {judged})."
        )
    if na_devices and judged:
        summary += (
            f" {na_devices} device(s) in scope do not have {label} "
            "configured and were reported as not applicable, never as "
            "compliant."
        )
    if counts["unknown"]:
        summary += (
            f" {counts['unknown']} evaluation(s) could not be judged "
            "and remain unknown."
        )
    evidence = [
        EvidenceItem(
            label="Policy Engine Results",
            detail=f"{aggregate['evaluated']} evaluation(s) across "
                   f"{len(aggregate['policies'])} {label} policy rule(s)",
            href="/policy",
        ),
        _graph_evidence(context),
    ]
    return AdvisorResponse(
        question=question, intent=intent,
        summary=summary,
        evidence=tuple(evidence),
        confidence=(
            CONFIDENCE_UNKNOWN if judged == 0
            and term not in (VERDICT_NOT_APPLICABLE,)
            # "Partially verified" is Medium even when the unjudged
            # remainder is unevaluated devices rather than unknown
            # evaluations — a partial answer never claims High.
            else CONFIDENCE_MEDIUM if term == VERDICT_PARTIAL
            or counts["unknown"]
            else CONFIDENCE_HIGH
        ),
        confidence_basis=(
            f"{judged + counts['unknown']} evaluation(s) by the policy "
            "engine"
        ),
        next_action_label="Open Policy",
        next_action_href="/policy",
        followups=(
            FollowUp("Open Policy results", href="/policy"),
            FollowUp("What changed?", question="What changed?"),
        ),
        unknowns=tuple(
            f"{count} evaluation(s) unknown: {reason}"
            for reason, count in sorted(
                aggregate["unknown_reasons"].items()
            )
        ),
        steps=tuple(steps), generated_at=context.generated_at,
    )


_HANDLERS = {
    router.INTENT_HEALTH: _answer_health,
    router.INTENT_CHANGES: _answer_changes,
    router.INTENT_DISCOVERY: _answer_discovery,
    router.INTENT_SEARCH: _answer_search,
    router.INTENT_PATH: _answer_path,
    router.INTENT_PREDICTION: _answer_prediction,
    router.INTENT_COMPASS: _answer_compass,
    router.INTENT_CONTINUE: _answer_continue,
    router.INTENT_INVESTIGATION: _answer_investigation,
    router.INTENT_ENTERPRISE: _answer_enterprise,
}

# PR-171: dispatch on (engine, objective) — consulted BEFORE the
# engine-only table, so an intent's declared objective finally reaches
# execution instead of surviving as display decoration. Sparse by
# design: every pre-existing intent declares objective="assess" and no
# (engine, "assess") key exists here, so their dispatch is untouched.
_OBJECTIVE_HANDLERS = {
    ("health", "validate"): _answer_validate,
}
