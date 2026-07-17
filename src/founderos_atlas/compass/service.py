"""Compass services: plan persistence and workspace-level analysis.

Plans live in ``.atlas/compass/plans.json`` (enterprise scope; gitignored
with the rest of the Atlas state) together with each plan's latest
assessment so the GUI, CLI, search, and future REST/assistant clients
share one source. Analysis evidence comes from the UNITY enterprise
snapshot — Compass never builds its own topology.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from founderos_atlas.federation import (
    build_enterprise_snapshot,
    enterprise_seed_addresses,
    get_enterprise_graph,
    overall_freshness,
)
from founderos_atlas.sites import SiteCatalog

from .engine import analyse_plan
from .models import (
    ChangePlan,
    PLAN_STATUS_ANALYSED,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_REJECTED,
    PlanAssessment,
    PlannedChange,
)


class PlanConflictError(RuntimeError):
    """The caller edited an older revision of the plan."""


COMPASS_SUBDIR = Path(".atlas") / "compass"
PLANS_FILENAME = "plans.json"


def compass_dir(base_output_dir: str | Path) -> Path:
    return Path(base_output_dir) / COMPASS_SUBDIR


class PlanRepository:
    """JSON persistence for plans and their latest assessments."""

    def __init__(self, base_output_dir: str | Path) -> None:
        self._path = compass_dir(base_output_dir) / PLANS_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[dict]:
        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [entry for entry in data if isinstance(entry, dict)] if isinstance(
            data, list
        ) else []

    def list_plans(self) -> tuple[ChangePlan, ...]:
        return tuple(
            ChangePlan.from_dict(entry["plan"])
            for entry in self.load()
            if isinstance(entry.get("plan"), dict)
        )

    def get(self, plan_id: str) -> tuple[ChangePlan | None, dict | None]:
        """The plan and its latest stored assessment dict, if any."""

        for entry in self.load():
            plan = entry.get("plan")
            if isinstance(plan, dict) and plan.get("plan_id") == plan_id:
                return ChangePlan.from_dict(plan), entry.get("assessment")
        return None, None

    def check_revision(
        self, plan_id: str, expected_revision: int | None
    ) -> ChangePlan | None:
        """The current plan, after verifying the caller saw its latest
        revision. ``None`` expected revision skips the check (legacy and
        non-form callers)."""

        plan, _assessment = self.get(plan_id)
        if plan is None:
            return None
        if (
            expected_revision is not None
            and int(expected_revision) != plan.revision
        ):
            raise PlanConflictError(
                f"The plan changed while you were editing (revision "
                f"{plan.revision}, you edited {expected_revision}). "
                "Review the current plan and reapply your change."
            )
        return plan

    def save(
        self, plan: ChangePlan, assessment: PlanAssessment | dict | None = None
    ) -> None:
        entries = self.load()
        from dataclasses import replace as _replace

        plan = _replace(plan, revision=plan.revision + 1)
        record = {
            "plan": plan.to_dict(),
            "assessment": (
                assessment.to_dict()
                if isinstance(assessment, PlanAssessment)
                else assessment
            ),
        }
        for index, entry in enumerate(entries):
            existing = entry.get("plan")
            if isinstance(existing, dict) and existing.get("plan_id") == plan.plan_id:
                if record["assessment"] is None:
                    record["assessment"] = entry.get("assessment")
                entries[index] = record
                break
        else:
            entries.append(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                entries, indent=2, sort_keys=True, ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )


def create_plan(
    repository: PlanRepository,
    *,
    title: str,
    maintenance_window: str,
    engineer: str,
    created_at: str,
    cab_reference: str | None = None,
) -> ChangePlan:
    """Create and persist a new draft plan with a stable unique id."""

    if not isinstance(title, str) or not title.strip():
        raise ValueError("a plan title is required")
    taken = {plan.plan_id for plan in repository.list_plans()}
    base = _slug(title)
    plan_id, suffix = base, 2
    while plan_id in taken:
        plan_id = f"{base}-{suffix}"
        suffix += 1
    plan = ChangePlan(
        plan_id=plan_id,
        title=title.strip(),
        maintenance_window=maintenance_window.strip(),
        engineer=engineer.strip(),
        cab_reference=(cab_reference or "").strip() or None,
        created_at=created_at,
        updated_at=created_at,
    )
    repository.save(plan)
    return plan


def add_change(
    repository: PlanRepository,
    plan: ChangePlan,
    change: PlannedChange,
    *,
    updated_at: str,
) -> ChangePlan:
    """Append one planned change; the plan returns to draft status."""

    from dataclasses import replace

    updated = replace(
        plan,
        changes=(*plan.changes, change),
        status="draft",
        updated_at=updated_at,
    )
    repository.save(updated)
    return updated


def remove_change(
    repository: PlanRepository,
    plan: ChangePlan,
    change_id: str,
    *,
    updated_at: str,
) -> ChangePlan:
    from dataclasses import replace

    updated = replace(
        plan,
        changes=tuple(
            change for change in plan.changes if change.change_id != change_id
        ),
        status="draft",
        updated_at=updated_at,
    )
    repository.save(updated)
    return updated


def decide_plan(
    repository: PlanRepository,
    plan: ChangePlan,
    *,
    approve: bool,
    actor: str,
    decided_at: str,
    reason: str | None = None,
) -> ChangePlan:
    """Approve or reject an analysed plan.

    Approval is only meaningful over an analysed plan — a draft has no
    assessment to approve. Any later edit returns the plan to draft, so
    an approval can never silently cover changes the approver never saw.
    """

    from dataclasses import replace

    if plan.status != PLAN_STATUS_ANALYSED:
        raise ValueError(
            "Only an analysed plan can be approved or rejected — run the "
            "analysis first so the decision covers a concrete assessment."
        )
    if not approve and not str(reason or "").strip():
        raise ValueError("Rejecting a plan requires a reason.")
    updated = replace(
        plan,
        status=PLAN_STATUS_APPROVED if approve else PLAN_STATUS_REJECTED,
        updated_at=decided_at,
        approval={
            "actor": actor,
            "decided_at": decided_at,
            "decision": "approved" if approve else "rejected",
            "reason": str(reason or "").strip() or None,
        },
    )
    repository.save(updated)
    return updated


def analyse_plan_for_workspace(
    repository: PlanRepository,
    plan: ChangePlan,
    *,
    base_output_dir: str | Path,
    profiles,
    generated_at: str,
    catalog: SiteCatalog | None = None,
    credential_memory=None,
) -> tuple[ChangePlan, PlanAssessment]:
    """Analyse a plan against the enterprise evidence and persist both.

    Reuses UNITY end to end: the enterprise snapshot is the topology,
    per-profile freshness feeds confidence, and profile seeds feed the
    management-plane evaluation — nothing is re-derived here.
    """

    from dataclasses import replace

    graph = get_enterprise_graph(
        base_output_dir,
        profiles,
        catalog=catalog,
        credential_memory=credential_memory,
        now=generated_at,
    )
    snapshot = build_enterprise_snapshot(graph).to_dict() if graph.devices else None
    assessment = analyse_plan(
        plan,
        snapshot=snapshot,
        generated_at=generated_at,
        fresh=overall_freshness(graph.contributions),
        seed_addresses=enterprise_seed_addresses(profiles),
    )
    analysed = replace(
        plan, status=PLAN_STATUS_ANALYSED, updated_at=generated_at
    )
    repository.save(analysed, assessment)
    return analysed, assessment


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.strip().casefold()).strip("-")
    return cleaned or "plan"
