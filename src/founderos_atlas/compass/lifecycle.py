"""The Compass plan lifecycle: transitions, checks, execution, export.

State machine (every transition validated, audited by the caller):

    draft ──analyse──▶ analysed ──submit──▶ in-review ──approve──▶ approved
      ▲                                        │reject                │schedule
      └────────── any edit returns here ◀──────┘                      ▼
    cancelled ◀── cancel (any pre-terminal)                     scheduled
                                                                      │start
    rolled-back ◀──rollback── failed ◀──fail── running ──complete──▶ completed

Execution is honest about what Atlas can do: it does not push
configuration to devices, so "Running" tracks explicit manual
checkpoints — each planned change is marked done/failed/skipped by the
operator with a note, timestamped and attributed. Completing requires
every change checkpointed and every post-check recorded; that record
IS the resulting evidence, and it links back to the incident case.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .models import (
    ChangePlan,
    PLAN_STATUS_ANALYSED,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_CANCELLED,
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_FAILED,
    PLAN_STATUS_IN_REVIEW,
    PLAN_STATUS_ROLLED_BACK,
    PLAN_STATUS_RUNNING,
    PLAN_STATUS_SCHEDULED,
)

CHECK_PENDING = "pending"
CHECK_PASSED = "passed"
CHECK_FAILED = "failed"

CHECKPOINT_DONE = "done"
CHECKPOINT_FAILED = "failed"
CHECKPOINT_SKIPPED = "skipped"

_TERMINAL = frozenset({
    PLAN_STATUS_COMPLETED, PLAN_STATUS_ROLLED_BACK, PLAN_STATUS_CANCELLED,
})


class PlanLifecycleError(ValueError):
    """A transition or edit the current plan state does not allow."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_status(plan: ChangePlan, *allowed: str) -> None:
    if plan.status not in allowed:
        raise PlanLifecycleError(
            f"A {plan.status} plan cannot do this — it requires the plan "
            f"to be {' or '.join(allowed)}."
        )


# -- ordering and dependencies ----------------------------------------------

def validate_order(changes) -> list[str]:
    """Problems with the current execution order (empty = valid).

    Every dependency must exist and must run BEFORE its dependent —
    unless both share a concurrency group (they run together)."""

    problems: list[str] = []
    position = {change.change_id: index for index, change in enumerate(changes)}
    groups = {change.change_id: change.concurrency_group for change in changes}
    for change in changes:
        for needed in change.depends_on:
            if needed not in position:
                problems.append(
                    f"{change.change_id} depends on {needed}, which is not "
                    "in the plan."
                )
            elif position[needed] >= position[change.change_id] and not (
                groups.get(needed)
                and groups.get(needed) == groups.get(change.change_id)
            ):
                problems.append(
                    f"{change.change_id} depends on {needed} but is ordered "
                    "before it."
                )
    return problems


def reorder_change(plan: ChangePlan, change_id: str, direction: int) -> ChangePlan:
    """Move one change up (-1) or down (+1); the result must stay valid."""

    _require_status(plan, PLAN_STATUS_DRAFT, PLAN_STATUS_ANALYSED)
    changes = list(plan.changes)
    index = next(
        (i for i, change in enumerate(changes) if change.change_id == change_id),
        None,
    )
    if index is None:
        raise PlanLifecycleError("No such change in this plan.")
    target = index + (1 if direction > 0 else -1)
    if not 0 <= target < len(changes):
        return plan
    changes[index], changes[target] = changes[target], changes[index]
    problems = validate_order(changes)
    if problems:
        raise PlanLifecycleError(
            "That order would break a dependency: " + "; ".join(problems)
        )
    return replace(
        plan, changes=tuple(changes), status=PLAN_STATUS_DRAFT,
        updated_at=_now(),
    )


def set_dependencies(
    plan: ChangePlan, change_id: str, *, depends_on, concurrency_group,
) -> ChangePlan:
    _require_status(plan, PLAN_STATUS_DRAFT, PLAN_STATUS_ANALYSED)
    known = {change.change_id for change in plan.changes}
    wanted = tuple(
        item for item in (str(d).strip() for d in depends_on)
        if item and item != change_id
    )
    unknown = [item for item in wanted if item not in known]
    if unknown:
        raise PlanLifecycleError(
            f"Unknown change id(s) in dependencies: {', '.join(unknown)}."
        )
    changes = tuple(
        replace(
            change, depends_on=wanted,
            concurrency_group=(
                str(concurrency_group).strip() or None
                if concurrency_group is not None else None
            ),
        )
        if change.change_id == change_id else change
        for change in plan.changes
    )
    problems = validate_order(changes)
    if problems:
        raise PlanLifecycleError("; ".join(problems))
    return replace(plan, changes=changes, status=PLAN_STATUS_DRAFT,
                   updated_at=_now())


# -- readiness metadata ------------------------------------------------------

def update_readiness(
    plan: ChangePlan,
    *,
    rollback_plan: str | None = None,
    success_criteria=None,
    reviewers=None,
    window_start: str | None = None,
    window_end: str | None = None,
    pre_checks=None,
    post_checks=None,
) -> ChangePlan:
    _require_status(
        plan, PLAN_STATUS_DRAFT, PLAN_STATUS_ANALYSED, PLAN_STATUS_IN_REVIEW,
    )

    def _checks(items, existing):
        if items is None:
            return existing
        cleaned = []
        for item in items:
            text = str(item or "").strip()
            if text:
                cleaned.append({
                    "check_id": f"chk-{uuid4().hex[:8]}", "text": text,
                    "status": CHECK_PENDING, "by": None, "at": None,
                    "note": "",
                })
        return tuple(cleaned)

    return replace(
        plan,
        rollback_plan=(
            rollback_plan.strip() if rollback_plan is not None
            else plan.rollback_plan
        ),
        success_criteria=(
            tuple(
                str(item).strip() for item in success_criteria
                if str(item or "").strip()
            )
            if success_criteria is not None else plan.success_criteria
        ),
        reviewers=(
            tuple(
                str(item).strip() for item in reviewers
                if str(item or "").strip()
            )
            if reviewers is not None else plan.reviewers
        ),
        window_start=(
            window_start if window_start is not None else plan.window_start
        ) or None,
        window_end=(
            window_end if window_end is not None else plan.window_end
        ) or None,
        pre_checks=_checks(pre_checks, plan.pre_checks),
        post_checks=_checks(post_checks, plan.post_checks),
        updated_at=_now(),
    )


def readiness_gaps(plan: ChangePlan) -> list[str]:
    """What still blocks this plan from review (empty = ready)."""

    gaps: list[str] = []
    if not plan.changes:
        gaps.append("The plan has no changes.")
    if plan.status != PLAN_STATUS_ANALYSED:
        gaps.append("The plan has not been analysed since its last edit.")
    if not plan.rollback_plan:
        gaps.append("No rollback plan is written.")
    if not plan.success_criteria:
        gaps.append("No success criteria are defined.")
    if not plan.pre_checks:
        gaps.append("No pre-checks are defined.")
    if not plan.post_checks:
        gaps.append("No post-checks are defined.")
    gaps.extend(validate_order(plan.changes))
    return gaps


# -- transitions -------------------------------------------------------------

def submit_for_review(plan: ChangePlan) -> ChangePlan:
    gaps = readiness_gaps(plan)
    if gaps:
        raise PlanLifecycleError(
            "The plan is not ready for review: " + " ".join(gaps)
        )
    return replace(plan, status=PLAN_STATUS_IN_REVIEW, updated_at=_now())


def decide_review(
    plan: ChangePlan, *, approve: bool, actor: str, reason: str | None,
) -> ChangePlan:
    _require_status(plan, PLAN_STATUS_IN_REVIEW)
    if not approve and not str(reason or "").strip():
        raise PlanLifecycleError("Rejecting a plan requires a reason.")
    return replace(
        plan,
        status=PLAN_STATUS_APPROVED if approve else PLAN_STATUS_DRAFT,
        approval={
            "actor": actor, "decided_at": _now(),
            "decision": "approved" if approve else "rejected",
            "reason": str(reason or "").strip() or None,
        },
        updated_at=_now(),
    )


def schedule(plan: ChangePlan, *, window_start: str, window_end: str) -> ChangePlan:
    _require_status(plan, PLAN_STATUS_APPROVED)
    start = str(window_start or "").strip()
    end = str(window_end or "").strip()
    if not start or not end or end <= start:
        raise PlanLifecycleError(
            "Scheduling needs a maintenance window whose end is after its "
            "start (ISO format)."
        )
    return replace(
        plan, status=PLAN_STATUS_SCHEDULED,
        window_start=start, window_end=end, updated_at=_now(),
    )


def _log(plan: ChangePlan, *, actor: str, event: str,
         change_id: str | None = None, note: str = "") -> tuple[dict, ...]:
    return (*plan.execution_log, {
        "at": _now(), "actor": actor, "event": event,
        "change_id": change_id, "note": note,
    })


def record_check(
    plan: ChangePlan, *, phase: str, check_id: str, passed: bool,
    actor: str, note: str = "",
) -> ChangePlan:
    if phase == "pre":
        _require_status(plan, PLAN_STATUS_SCHEDULED, PLAN_STATUS_RUNNING)
        source, name = plan.pre_checks, "pre_checks"
    elif phase == "post":
        _require_status(plan, PLAN_STATUS_RUNNING)
        source, name = plan.post_checks, "post_checks"
    else:
        raise PlanLifecycleError("Check phase must be pre or post.")
    if not any(item.get("check_id") == check_id for item in source):
        raise PlanLifecycleError("No such check on this plan.")
    checks = tuple(
        {**item, "status": CHECK_PASSED if passed else CHECK_FAILED,
         "by": actor, "at": _now(), "note": note}
        if item.get("check_id") == check_id else item
        for item in source
    )
    return replace(
        plan, **{name: checks},
        execution_log=_log(
            plan, actor=actor,
            event=f"{phase}-check-{'passed' if passed else 'failed'}",
            note=note or next(
                item.get("text", "") for item in source
                if item.get("check_id") == check_id
            ),
        ),
        updated_at=_now(),
    )


def start_execution(plan: ChangePlan, *, actor: str) -> ChangePlan:
    _require_status(plan, PLAN_STATUS_SCHEDULED)
    failed = [c for c in plan.pre_checks if c.get("status") == CHECK_FAILED]
    pending = [c for c in plan.pre_checks if c.get("status") == CHECK_PENDING]
    if failed:
        raise PlanLifecycleError(
            "A pre-check failed — resolve it (or cancel the plan) before "
            "starting execution."
        )
    if pending:
        raise PlanLifecycleError(
            f"{len(pending)} pre-check(s) have not been recorded yet."
        )
    return replace(
        plan, status=PLAN_STATUS_RUNNING,
        execution_log=_log(plan, actor=actor, event="execution-started"),
        updated_at=_now(),
    )


def checkpoint_change(
    plan: ChangePlan, *, change_id: str, outcome: str, actor: str,
    note: str = "",
) -> ChangePlan:
    _require_status(plan, PLAN_STATUS_RUNNING)
    if outcome not in (CHECKPOINT_DONE, CHECKPOINT_FAILED, CHECKPOINT_SKIPPED):
        raise PlanLifecycleError("Checkpoint outcome must be done/failed/skipped.")
    if not any(change.change_id == change_id for change in plan.changes):
        raise PlanLifecycleError("No such change in this plan.")
    if outcome == CHECKPOINT_FAILED and not note.strip():
        raise PlanLifecycleError("A failed checkpoint needs a note saying what happened.")
    return replace(
        plan,
        execution_log=_log(
            plan, actor=actor, event=f"change-{outcome}",
            change_id=change_id, note=note,
        ),
        updated_at=_now(),
    )


def change_checkpoints(plan: ChangePlan) -> dict[str, str]:
    """change_id → latest checkpoint outcome (unrecorded changes absent)."""

    outcomes: dict[str, str] = {}
    for entry in plan.execution_log:
        event = str(entry.get("event") or "")
        if event.startswith("change-") and entry.get("change_id"):
            outcomes[str(entry["change_id"])] = event.removeprefix("change-")
    return outcomes


def complete(plan: ChangePlan, *, actor: str, note: str = "") -> ChangePlan:
    _require_status(plan, PLAN_STATUS_RUNNING)
    outcomes = change_checkpoints(plan)
    unrecorded = [
        change.change_id for change in plan.changes
        if change.change_id not in outcomes
    ]
    if unrecorded:
        raise PlanLifecycleError(
            f"Change(s) without a checkpoint: {', '.join(unrecorded)}. "
            "Record each change before completing."
        )
    failed_changes = [cid for cid, out in outcomes.items() if out == "failed"]
    if failed_changes:
        raise PlanLifecycleError(
            "A change failed — the plan can be marked Failed (and rolled "
            "back), not Completed."
        )
    pending_post = [
        c for c in plan.post_checks if c.get("status") == CHECK_PENDING
    ]
    if pending_post:
        raise PlanLifecycleError(
            f"{len(pending_post)} post-check(s) have not been recorded yet."
        )
    failed_post = [
        c for c in plan.post_checks if c.get("status") == CHECK_FAILED
    ]
    if failed_post:
        raise PlanLifecycleError(
            "A post-check failed — the plan can be marked Failed, not "
            "Completed."
        )
    return replace(
        plan, status=PLAN_STATUS_COMPLETED,
        execution_log=_log(plan, actor=actor, event="completed", note=note),
        updated_at=_now(),
    )


def fail(plan: ChangePlan, *, actor: str, note: str) -> ChangePlan:
    _require_status(plan, PLAN_STATUS_RUNNING)
    if not str(note or "").strip():
        raise PlanLifecycleError("Failing a plan requires a note saying why.")
    return replace(
        plan, status=PLAN_STATUS_FAILED,
        execution_log=_log(plan, actor=actor, event="failed", note=note),
        updated_at=_now(),
    )


def rollback(plan: ChangePlan, *, actor: str, note: str) -> ChangePlan:
    _require_status(plan, PLAN_STATUS_FAILED)
    if not str(note or "").strip():
        raise PlanLifecycleError(
            "Recording a rollback requires a note describing what was "
            "restored."
        )
    return replace(
        plan, status=PLAN_STATUS_ROLLED_BACK,
        execution_log=_log(plan, actor=actor, event="rolled-back", note=note),
        updated_at=_now(),
    )


def cancel(plan: ChangePlan, *, actor: str, reason: str) -> ChangePlan:
    if plan.status in _TERMINAL:
        raise PlanLifecycleError("A finished plan cannot be cancelled.")
    if not str(reason or "").strip():
        raise PlanLifecycleError("Cancelling a plan requires a reason.")
    return replace(
        plan, status=PLAN_STATUS_CANCELLED,
        execution_log=_log(plan, actor=actor, event="cancelled", note=reason),
        updated_at=_now(),
    )


# -- CAB export --------------------------------------------------------------

def cab_export_markdown(plan: ChangePlan, assessment: dict | None) -> str:
    """A change-advisory-board-ready document from the plan's own facts."""

    lines = [
        f"# Change Plan: {plan.title}",
        "",
        f"- Plan id: {plan.plan_id}",
        f"- Status: {plan.status}",
        f"- Engineer/owner: {plan.engineer or 'unassigned'}",
        f"- Reviewers: {', '.join(plan.reviewers) or 'none named'}",
        f"- CAB reference: {plan.cab_reference or '—'}",
        f"- Maintenance window: {plan.maintenance_window or '—'}"
        + (
            f" ({plan.window_start} → {plan.window_end})"
            if plan.window_start else ""
        ),
        f"- Incident: {plan.incident_ref or '—'}",
        f"- Created: {plan.created_at} · Updated: {plan.updated_at}",
        "",
        f"## Planned changes ({len(plan.changes)})",
        "",
    ]
    for index, change in enumerate(plan.changes, 1):
        lines.append(
            f"{index}. **{change.title}** — {change.reason or 'no reason recorded'}"
        )
        detail = []
        if change.estimated_duration_minutes:
            detail.append(f"~{change.estimated_duration_minutes} min")
        if change.rollback_available is not None:
            detail.append(
                "rollback available" if change.rollback_available
                else "NO rollback"
            )
        if change.depends_on:
            detail.append(f"after {', '.join(change.depends_on)}")
        if change.concurrency_group:
            detail.append(f"group {change.concurrency_group}")
        if detail:
            lines.append(f"   - {' · '.join(detail)}")
    if assessment:
        risk = (assessment.get("risk") or {})
        lines += [
            "",
            "## Assessment",
            "",
            f"- Overall risk: {risk.get('overall_level', 'not analysed')}",
            f"- Generated: {assessment.get('generated_at', '—')}",
        ]
    lines += ["", "## Pre-checks", ""]
    for item in plan.pre_checks or ({"text": "none defined", "status": ""},):
        lines.append(f"- [{item.get('status') or ' '}] {item.get('text')}")
    lines += ["", "## Post-checks", ""]
    for item in plan.post_checks or ({"text": "none defined", "status": ""},):
        lines.append(f"- [{item.get('status') or ' '}] {item.get('text')}")
    lines += [
        "",
        "## Rollback plan",
        "",
        plan.rollback_plan or "_none written_",
        "",
        "## Success criteria",
        "",
    ]
    for item in plan.success_criteria or ("_none defined_",):
        lines.append(f"- {item}")
    if plan.approval:
        lines += [
            "",
            "## Decision",
            "",
            f"{plan.approval.get('decision', '?').title()} by "
            f"{plan.approval.get('actor')} at {plan.approval.get('decided_at')}"
            + (
                f" — {plan.approval.get('reason')}"
                if plan.approval.get("reason") else ""
            ),
        ]
    if plan.execution_log:
        lines += ["", "## Execution record", ""]
        for entry in plan.execution_log:
            lines.append(
                f"- {entry.get('at')} · {entry.get('actor')} · "
                f"{entry.get('event')}"
                + (f" · {entry.get('change_id')}" if entry.get("change_id") else "")
                + (f" — {entry.get('note')}" if entry.get("note") else "")
            )
    return "\n".join(lines) + "\n"
