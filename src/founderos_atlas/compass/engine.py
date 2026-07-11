"""The Compass planning engine: analyse, order, and explain many changes.

Deterministic end to end and evidence-based only:

- Every change is analysed through the EXISTING prediction engine
  (risk, blast radius, confidence, unknowns) — no duplicated impact
  logic; unmodeled change types predict honestly with low confidence.
- Dependencies are derived ONLY from cited evidence:
    * a change whose blast radius contains another change's device must
      run AFTER that change (you cannot configure a device you just cut
      off) — evidence: the prediction's blast radius;
    * work on a device must complete BEFORE that device's IOS upgrade
      or reload — evidence: the upgrade reloads the device.
  Nothing else is inferred. Unknown remains unknown and is listed.
- The recommended order is a deterministic topological sort: among the
  currently runnable steps, lowest predicted risk first; steps whose
  blast radius spans a large share of the enterprise are scheduled last
  and flagged for a separate window. Dependency cycles are reported —
  Atlas says it cannot determine a safe order rather than guessing.
- Conflicts (same interface touched twice, duplicate changes, multiple
  upgrades of one device, mutually exclusive operations) WARN and never
  block: the engineer stays in control.
"""

from __future__ import annotations

from founderos_atlas.prediction import (
    ChangeRequest,
    predict,
    registered_evaluators,
)

from .models import (
    CHANGE_TYPES,
    ChangeAnalysis,
    ChangePlan,
    Conflict,
    Dependency,
    PlanAssessment,
    PlannedChange,
    PlanStep,
    RiskSummary,
)


RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
# A blast radius covering at least this share of the visible enterprise
# (and at least this many devices) earns a separate-window flag.
SEPARATE_WINDOW_SHARE = 0.5
SEPARATE_WINDOW_MIN_DEVICES = 2


def analyse_plan(
    plan: ChangePlan,
    *,
    snapshot: dict | None,
    generated_at: str,
    fresh: bool = True,
    seed_addresses: tuple[str, ...] = (),
    health_score: int | None = None,
) -> PlanAssessment:
    """The complete deterministic assessment of one maintenance plan."""

    analyses = tuple(
        _analyse_change(
            change,
            snapshot=snapshot,
            generated_at=generated_at,
            fresh=fresh,
            seed_addresses=seed_addresses,
            health_score=health_score,
        )
        for change in plan.changes
    )
    changes_by_id = {change.change_id: change for change in plan.changes}
    dependencies = detect_dependencies(plan, analyses)
    conflicts = detect_conflicts(plan)
    steps, cycle_unknowns = recommend_order(
        plan, analyses, dependencies, device_count=_device_count(snapshot)
    )
    unknowns: list[str] = list(cycle_unknowns)
    for analysis in analyses:
        change = changes_by_id[analysis.change_id]
        if not analysis.prediction_modeled:
            unknowns.append(
                f"{change.title}: no impact model exists for this change "
                "type yet — its dependencies on other steps are unknown, "
                "not absent."
            )
        unknowns.extend(analysis.unknowns)
    if not fresh:
        unknowns.append(
            "Contributing discovery evidence is older than the freshness "
            "window; the network may have changed since it was collected."
        )
    evidence_refs = [_snapshot_ref(snapshot)] if snapshot else []
    seen: set[str] = set()
    return PlanAssessment(
        plan_id=plan.plan_id,
        generated_at=generated_at,
        steps=steps,
        analyses=analyses,
        dependencies=dependencies,
        conflicts=conflicts,
        risk=estimate_plan_risk(plan, analyses),
        unknowns=tuple(
            item for item in unknowns if not (item in seen or seen.add(item))
        ),
        evidence_refs=tuple(evidence_refs),
        basis={
            "snapshot_id": str((snapshot or {}).get("snapshot_id") or None),
            "fresh": fresh,
            "change_count": len(plan.changes),
        },
    )


# -- per-change analysis (reuses the prediction engine) --------------------------


def _analyse_change(
    change: PlannedChange,
    *,
    snapshot: dict | None,
    generated_at: str,
    fresh: bool,
    seed_addresses: tuple[str, ...],
    health_score: int | None,
) -> ChangeAnalysis:
    prediction_type = CHANGE_TYPES[change.change_type]["prediction_type"]
    request = ChangeRequest(
        request_id=f"compass-{change.change_id}",
        change_type=prediction_type,
        target_device=change.device,
        target_object=change.interface,
        description=change.title,
        requested_at=generated_at,
        reason=change.reason or None,
    )
    prediction = predict(
        request,
        snapshot=snapshot,
        generated_at=generated_at,
        fresh=fresh,
        seed_addresses=seed_addresses,
        health_score=health_score,
    )
    impact = prediction.blast_radius.attributes.get("estimated_health_impact")
    return ChangeAnalysis(
        change_id=change.change_id,
        risk_level=prediction.risk.level if prediction.risk else "unknown",
        risk_score=prediction.risk.score if prediction.risk else 0,
        confidence=prediction.confidence.score,
        blast_devices=tuple(prediction.blast_radius.affected_devices),
        health_impact=int(impact) if isinstance(impact, (int, float)) else None,
        rollback_reversible=(
            prediction.rollback.reversible if prediction.rollback else None
        ),
        unknowns=tuple(prediction.unknowns),
        evidence=tuple(prediction.evidence_refs),
        prediction_modeled=prediction_type in registered_evaluators(),
    )


# -- dependencies (evidence only; never invented) ---------------------------------


def detect_dependencies(
    plan: ChangePlan, analyses: tuple[ChangeAnalysis, ...]
) -> tuple[Dependency, ...]:
    by_id = {analysis.change_id: analysis for analysis in analyses}
    found: list[Dependency] = []
    for change in plan.changes:
        analysis = by_id[change.change_id]
        blast = {device.casefold() for device in analysis.blast_devices}
        for other in plan.changes:
            if other.change_id == change.change_id:
                continue
            # Evidence rule 1: this change's predicted blast radius
            # contains the other change's device — the other change must
            # run first, or its device becomes unreachable.
            if other.device.casefold() in blast:
                found.append(
                    Dependency(
                        before_change_id=other.change_id,
                        after_change_id=change.change_id,
                        reason=(
                            f"{change.title} is predicted to break "
                            f"connectivity to {other.device}; "
                            f"{other.title} must complete first."
                        ),
                        evidence=(
                            f"prediction blast radius of {change.title} "
                            f"includes {other.device}",
                        ),
                    )
                )
            # Evidence rule 2: an IOS upgrade / reload of a device makes
            # it unavailable — other work on the SAME device runs first.
            if (
                change.change_type == "ios-upgrade"
                and other.device.casefold() == change.device.casefold()
            ):
                found.append(
                    Dependency(
                        before_change_id=other.change_id,
                        after_change_id=change.change_id,
                        reason=(
                            f"{change.title} reloads {change.device}; "
                            f"{other.title} on the same device must "
                            "complete before the reload."
                        ),
                        evidence=(
                            "an IOS upgrade deterministically includes a "
                            f"reload of {change.device}",
                        ),
                    )
                )
    # Deduplicate deterministically (a pair can match both rules).
    seen: set[tuple[str, str]] = set()
    unique: list[Dependency] = []
    for dependency in found:
        key = (dependency.before_change_id, dependency.after_change_id)
        if key not in seen:
            seen.add(key)
            unique.append(dependency)
    return tuple(unique)


# -- conflicts (warn, never block) -------------------------------------------------


def detect_conflicts(plan: ChangePlan) -> tuple[Conflict, ...]:
    conflicts: list[Conflict] = []
    changes = plan.changes
    for index, first in enumerate(changes):
        for second in changes[index + 1 :]:
            same_device = first.device.casefold() == second.device.casefold()
            same_interface = (
                same_device
                and first.interface
                and second.interface
                and first.interface.casefold() == second.interface.casefold()
            )
            if (
                same_interface
                and first.change_type == second.change_type
            ):
                conflicts.append(
                    Conflict(
                        kind="duplicate-change",
                        change_ids=(first.change_id, second.change_id),
                        detail=(
                            f"Duplicate: {first.title} appears twice in "
                            "this plan."
                        ),
                    )
                )
            elif same_interface and {first.change_type, second.change_type} == {
                "shutdown-interface",
                "enable-interface",
            }:
                conflicts.append(
                    Conflict(
                        kind="mutually-exclusive",
                        change_ids=(first.change_id, second.change_id),
                        detail=(
                            f"Mutually exclusive operations on "
                            f"{first.subject}: shutdown and bring-up in "
                            "one window — verify the intended final state."
                        ),
                    )
                )
            elif same_interface:
                conflicts.append(
                    Conflict(
                        kind="same-interface",
                        change_ids=(first.change_id, second.change_id),
                        detail=(
                            f"Two changes touch {first.subject}: "
                            f"{first.label} and {second.label} — order "
                            "matters; review carefully."
                        ),
                    )
                )
            if (
                same_device
                and first.change_type == "ios-upgrade"
                and second.change_type == "ios-upgrade"
            ):
                conflicts.append(
                    Conflict(
                        kind="duplicate-upgrade",
                        change_ids=(first.change_id, second.change_id),
                        detail=(
                            f"Multiple IOS upgrades planned for "
                            f"{first.device} in one window."
                        ),
                    )
                )
    return tuple(conflicts)


# -- recommended execution order ----------------------------------------------------


def recommend_order(
    plan: ChangePlan,
    analyses: tuple[ChangeAnalysis, ...],
    dependencies: tuple[Dependency, ...],
    *,
    device_count: int = 0,
) -> tuple[tuple[PlanStep, ...], tuple[str, ...]]:
    """Deterministic topological order with a WHY per position.

    Among runnable steps: lowest predicted risk first; large-blast steps
    (≥ half the visible enterprise) are held to the end and flagged for
    a separate window. A dependency cycle is reported honestly and
    broken deterministically so a full order is still produced.
    """

    by_id = {analysis.change_id: analysis for analysis in analyses}
    changes_by_id = {change.change_id: change for change in plan.changes}
    blockers: dict[str, set[str]] = {
        change.change_id: set() for change in plan.changes
    }
    dependents: dict[str, list[Dependency]] = {}
    for dependency in dependencies:
        blockers[dependency.after_change_id].add(dependency.before_change_id)
        dependents.setdefault(dependency.before_change_id, []).append(dependency)

    def separate_window(change_id: str) -> bool:
        blast = len(by_id[change_id].blast_devices)
        return (
            device_count > 0
            and blast >= SEPARATE_WINDOW_MIN_DEVICES
            and blast >= device_count * SEPARATE_WINDOW_SHARE
        )

    def sort_key(change_id: str):
        analysis = by_id[change_id]
        return (
            1 if separate_window(change_id) else 0,
            analysis.risk_score,
            len(analysis.blast_devices),
            changes_by_id[change_id].title.casefold(),
            change_id,
        )

    remaining = {change.change_id for change in plan.changes}
    steps: list[PlanStep] = []
    unknowns: list[str] = []
    order = 0
    while remaining:
        ready = sorted(
            (cid for cid in remaining if not (blockers[cid] & remaining)),
            key=sort_key,
        )
        if not ready:
            # Dependency cycle: report it, then break it deterministically
            # at the lowest-risk member so a full order still exists.
            cycle = sorted(remaining, key=sort_key)
            names = ", ".join(changes_by_id[cid].title for cid in cycle)
            unknowns.append(
                "Circular dependency detected between: "
                f"{names}. Atlas cannot determine a provably safe order "
                "from the available evidence — review these steps "
                "manually."
            )
            ready = [cycle[0]]
        change_id = ready[0]
        remaining.discard(change_id)
        order += 1
        change = changes_by_id[change_id]
        analysis = by_id[change_id]
        satisfied = [
            dependency
            for dependency in dependencies
            if dependency.after_change_id == change_id
        ]
        flagged = separate_window(change_id)
        if flagged:
            reason = (
                f"Largest blast radius ({len(analysis.blast_devices)} "
                "device(s)) — scheduled last; consider a separate "
                "maintenance window."
            )
        elif satisfied:
            names = ", ".join(
                changes_by_id[dependency.before_change_id].title
                for dependency in satisfied
            )
            reason = (
                f"Runs after {names}: "
                + " ".join(dependency.reason for dependency in satisfied)
            )
        elif dependents.get(change_id):
            reason = (
                "Scheduled early: "
                f"{len(dependents[change_id])} later step(s) depend on "
                "this change completing first."
            )
        else:
            reason = (
                "Independent — no evidence links this change to any other "
                "step; lowest predicted risk among the remaining steps."
            )
        evidence = list(analysis.evidence)
        for dependency in satisfied:
            evidence.extend(dependency.evidence)
        steps.append(
            PlanStep(
                order=order,
                change_id=change_id,
                title=change.title,
                reason=reason,
                risk_level=analysis.risk_level,
                confidence_percent=analysis.confidence_percent,
                confidence_band=analysis.confidence_band,
                evidence=tuple(dict.fromkeys(evidence)),
                separate_window=flagged,
            )
        )
    return tuple(steps), tuple(unknowns)


# -- plan-level risk summary ---------------------------------------------------------


def estimate_plan_risk(
    plan: ChangePlan, analyses: tuple[ChangeAnalysis, ...]
) -> RiskSummary:
    changes_by_id = {change.change_id: change for change in plan.changes}
    highest: ChangeAnalysis | None = None
    largest: ChangeAnalysis | None = None
    impacted: list[str] = []
    covered = missing = unknown = 0
    total_minutes: int | None = 0
    for analysis in analyses:
        change = changes_by_id[analysis.change_id]
        if highest is None or (
            RISK_ORDER.get(analysis.risk_level, 0),
            analysis.risk_score,
        ) > (RISK_ORDER.get(highest.risk_level, 0), highest.risk_score):
            highest = analysis
        if largest is None or len(analysis.blast_devices) > len(
            largest.blast_devices
        ):
            largest = analysis
        for device in (change.device, *analysis.blast_devices):
            if device not in impacted:
                impacted.append(device)
        if change.rollback_available is True:
            covered += 1
        elif change.rollback_available is False:
            missing += 1
        else:
            unknown += 1
        if total_minutes is not None:
            if change.estimated_duration_minutes is None:
                total_minutes = None
            else:
                total_minutes += change.estimated_duration_minutes
    return RiskSummary(
        overall_risk=highest.risk_level if highest else "low",
        highest_risk_change_id=highest.change_id if highest else None,
        highest_risk_title=(
            changes_by_id[highest.change_id].title if highest else None
        ),
        largest_blast_change_id=largest.change_id if largest else None,
        largest_blast_title=(
            changes_by_id[largest.change_id].title if largest else None
        ),
        largest_blast_device_count=(
            len(largest.blast_devices) if largest else 0
        ),
        total_devices_impacted=len(impacted),
        impacted_devices=tuple(impacted),
        rollback_covered=covered,
        rollback_missing=missing,
        rollback_unknown=unknown,
        estimated_total_minutes=total_minutes,
    )


# -- helpers ---------------------------------------------------------------------


def _device_count(snapshot: dict | None) -> int:
    if not isinstance(snapshot, dict):
        return 0
    return len(snapshot.get("devices") or ())


def _snapshot_ref(snapshot: dict) -> str:
    snapshot_id = str(snapshot.get("snapshot_id") or "unknown")
    created = str(snapshot.get("created_at") or "unknown time")
    return (
        f"enterprise topology snapshot {snapshot_id.split(':')[-1][:12]} "
        f"(created {created})"
    )
