"""Bulk change triage (PR-178.2): one operator intent, many subjects.

Pure domain logic — no Flask, no I/O beyond the store handed in. The
web route validates the request (authorization, CSRF, subjects against
the current scoped rows) and hands this module the facts; this module
owns the action table, the per-subject eligibility classification, the
batched mutation, and the honest result.

The load-bearing rules, from the approved architecture:

- "Already in state" is PER ACTION: assign compares the stored OWNER,
  suppress compares the stored REASON, acknowledge/unacknowledge/
  unsuppress compare effective presence. Re-assigning to a different
  owner and re-suppressing with a different reason are real mutations.
- UNCHANGED subjects are not mutated and receive NO audit event — a
  no-op is not a mutation.
- NOT_PRESENT subjects (not in the caller-validated row set) are never
  mutated and never audited.
- Un-acting on state only a READ-ONLY legacy (v1) record asserts writes
  a scoped NEGATIVE shadow instead of touching the legacy record — the
  PR-178.2A single-row contract, applied batch-wide.
- One batch = one correlation id = at most two annotation writes (a
  clear block and/or a set block) and their audit blocks. Never one
  write per subject.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .identity import resolve_annotation, scope_of

OUTCOME_UPDATED = "updated"
OUTCOME_UNCHANGED = "unchanged"
OUTCOME_NOT_PRESENT = "not-present"

_MODE_SET = "set"
_MODE_CLEAR = "clear"
_MODE_SHADOW = "shadow"

MAX_BULK_SUBJECTS = 200

# The action table: annotation kind, required input, and the shadow a
# clear-type action writes when only a legacy record asserts the state.
BULK_ACTIONS: dict[str, dict[str, Any]] = {
    "acknowledge": {"kind": "change-ack", "requires": None},
    "unacknowledge": {
        "kind": "change-ack", "requires": None,
        "shadow": {"acknowledged": False},
    },
    "assign": {"kind": "change-assignment", "requires": "owner"},
    "suppress": {"kind": "change-suppression", "requires": "reason"},
    "unsuppress": {
        "kind": "change-suppression", "requires": None,
        "shadow": {"suppressed": False},
    },
}


def dedupe_subjects(subjects: Sequence[str]) -> list[str]:
    """First-occurrence order, duplicates dropped — the approved rule so
    repeated ids can never inflate counts or the batch size."""

    return list(dict.fromkeys(
        str(subject).strip() for subject in subjects if str(subject).strip()
    ))


@dataclass(frozen=True)
class PlanEntry:
    subject: str
    outcome: str                       # OUTCOME_*
    mode: str | None = None            # _MODE_* for UPDATED entries
    detail: str = ""                   # eligibility class for the confirm page


@dataclass(frozen=True)
class BatchPlan:
    action: str
    owner: str | None
    reason: str | None
    entries: tuple[PlanEntry, ...]

    def subjects(self, outcome: str) -> list[str]:
        return [e.subject for e in self.entries if e.outcome == outcome]

    def counts(self) -> dict[str, int]:
        found = {OUTCOME_UPDATED: 0, OUTCOME_UNCHANGED: 0,
                 OUTCOME_NOT_PRESENT: 0}
        for entry in self.entries:
            found[entry.outcome] += 1
        return found

    def detail_counts(self) -> dict[str, int]:
        """Eligibility classes for the confirm page (assign/suppress)."""

        found: dict[str, int] = {}
        for entry in self.entries:
            if entry.detail:
                found[entry.detail] = found.get(entry.detail, 0) + 1
        return found


def _effective(records, subject: str, legacy: str | None,
               positive_key: str) -> Mapping[str, Any] | None:
    """The record that currently asserts the state, or None when the
    state is effectively absent (no record, or a scoped negative)."""

    record = resolve_annotation(records, subject, legacy)
    if record is None:
        return None
    if record.get(positive_key, True) is False:
        return None
    return record


def _is_scoped_positive(records, subject: str, positive_key: str) -> bool:
    """True when the SCOPED record itself asserts the state — the case a
    clear-type action can clear; a legacy-asserted state needs a shadow."""

    record = (records or {}).get(subject)
    return record is not None and record.get(positive_key, True) is not False


def classify(
    *,
    action: str,
    subjects: Sequence[str],
    valid_subjects: Mapping[str, str | None],
    annotations: Mapping[str, Mapping[str, Any]],
    owner: str | None = None,
    reason: str | None = None,
) -> BatchPlan:
    """The mutation-time truth for each subject.

    ``valid_subjects`` maps each CURRENTLY-RENDERED subject of the
    operator's working context to its legacy (v1) twin — the caller
    builds it from the scoped rows, which is what makes a forged,
    stale, malformed or foreign-scope subject NOT_PRESENT here.
    ``annotations`` is the relevant kind's current records.
    """

    if action not in BULK_ACTIONS:
        raise ValueError(f"unknown bulk action {action!r}")
    entries: list[PlanEntry] = []
    for subject in dedupe_subjects(subjects):
        if subject not in valid_subjects:
            entries.append(PlanEntry(subject, OUTCOME_NOT_PRESENT))
            continue
        legacy = valid_subjects[subject]

        if action == "acknowledge":
            if _effective(annotations, subject, legacy, "acknowledged"):
                entries.append(PlanEntry(subject, OUTCOME_UNCHANGED))
            else:
                entries.append(PlanEntry(subject, OUTCOME_UPDATED, _MODE_SET))
        elif action == "unacknowledge":
            if not _effective(annotations, subject, legacy, "acknowledged"):
                entries.append(PlanEntry(subject, OUTCOME_UNCHANGED))
            elif _is_scoped_positive(annotations, subject, "acknowledged"):
                entries.append(PlanEntry(subject, OUTCOME_UPDATED, _MODE_CLEAR))
            else:
                entries.append(PlanEntry(subject, OUTCOME_UPDATED, _MODE_SHADOW))
        elif action == "assign":
            current = str((resolve_annotation(
                annotations, subject, legacy) or {}).get("owner") or "")
            if current == str(owner or ""):
                entries.append(PlanEntry(
                    subject, OUTCOME_UNCHANGED, detail="same-owner"))
            elif current:
                entries.append(PlanEntry(
                    subject, OUTCOME_UPDATED, _MODE_SET, detail="other-owner"))
            else:
                entries.append(PlanEntry(
                    subject, OUTCOME_UPDATED, _MODE_SET, detail="unassigned"))
        elif action == "suppress":
            record = _effective(annotations, subject, legacy, "suppressed")
            current = str((record or {}).get("reason") or "")
            if record is not None and current == str(reason or ""):
                entries.append(PlanEntry(
                    subject, OUTCOME_UNCHANGED, detail="same-reason"))
            elif record is not None:
                entries.append(PlanEntry(
                    subject, OUTCOME_UPDATED, _MODE_SET,
                    detail="different-reason"))
            else:
                entries.append(PlanEntry(
                    subject, OUTCOME_UPDATED, _MODE_SET, detail="new"))
        elif action == "unsuppress":
            if not _effective(annotations, subject, legacy, "suppressed"):
                entries.append(PlanEntry(subject, OUTCOME_UNCHANGED))
            elif _is_scoped_positive(annotations, subject, "suppressed"):
                entries.append(PlanEntry(subject, OUTCOME_UPDATED, _MODE_CLEAR))
            else:
                entries.append(PlanEntry(subject, OUTCOME_UPDATED, _MODE_SHADOW))
    return BatchPlan(
        action=action,
        owner=(str(owner).strip() if owner else None),
        reason=(str(reason).strip() if reason else None),
        entries=tuple(entries),
    )


@dataclass(frozen=True)
class BatchResult:
    action: str
    correlation_id: str
    counts: dict[str, int] = field(default_factory=dict)
    owner: str | None = None
    reason: str | None = None

    @property
    def updated(self) -> int:
        return self.counts.get(OUTCOME_UPDATED, 0)


def execute(
    store,
    plan: BatchPlan,
    *,
    actor: str,
    actor_roles=(),
    occurred_at: str | None = None,
    correlation_id: str | None = None,
) -> BatchResult:
    """Apply a plan through the batched store primitives.

    At most two annotation writes (one clear block, one set block) and
    their audit blocks, every event sharing the batch correlation id
    and carrying its subject's real scope. UNCHANGED and NOT_PRESENT
    subjects are untouched and unaudited. If the audit block fails the
    store restores its pre-image and the error propagates — the caller
    reports the batch as failed rather than half-true.
    """

    kind = BULK_ACTIONS[plan.action]["kind"]
    correlation = correlation_id or f"bulk:{uuid4().hex}"

    to_clear = [e.subject for e in plan.entries if e.mode == _MODE_CLEAR]
    to_shadow = [e.subject for e in plan.entries if e.mode == _MODE_SHADOW]
    to_set = [e.subject for e in plan.entries if e.mode == _MODE_SET]

    def scopes_for(subjects):
        return {s: (scope_of(s) or "all") for s in subjects}

    if plan.action == "acknowledge":
        fields: Mapping[str, Any] = {"acknowledged": True}
    elif plan.action == "assign":
        fields = {"owner": plan.owner}
    elif plan.action == "suppress":
        fields = {"reason": plan.reason}
    else:
        fields = {}

    if to_clear:
        store.clear_many(
            kind=kind, subjects=to_clear, actor=actor,
            reason=plan.reason, correlation_id=correlation,
            occurred_at=occurred_at, scope_ids=scopes_for(to_clear),
            actor_roles=actor_roles,
        )
    if to_shadow:
        shadow = BULK_ACTIONS[plan.action]["shadow"]
        store.set_many(
            kind=kind, records={s: shadow for s in to_shadow},
            actor=actor, reason=plan.reason, correlation_id=correlation,
            occurred_at=occurred_at, scope_ids=scopes_for(to_shadow),
            actor_roles=actor_roles,
        )
    if to_set:
        store.set_many(
            kind=kind, records={s: fields for s in to_set},
            actor=actor, reason=plan.reason, correlation_id=correlation,
            occurred_at=occurred_at, scope_ids=scopes_for(to_set),
            actor_roles=actor_roles,
        )
    return BatchResult(
        action=plan.action, correlation_id=correlation,
        counts=plan.counts(), owner=plan.owner, reason=plan.reason,
    )


_VERBS = {
    "acknowledge": ("acknowledged", "already acknowledged"),
    "unacknowledge": ("unacknowledged", "already unacknowledged"),
    "assign": ("assigned", "already assigned to this owner"),
    "suppress": ("suppressed", "already suppressed with this reason"),
    "unsuppress": ("unsuppressed", "already unsuppressed"),
}


def summary_sentence(result: BatchResult) -> str:
    """The honest four-count sentence. Never a bare "Success"."""

    updated_verb, unchanged_phrase = _VERBS[result.action]
    if result.action == "assign" and result.owner:
        updated_verb = f"assigned to {result.owner}"
    total = sum(result.counts.values())
    updated = result.counts.get(OUTCOME_UPDATED, 0)
    unchanged = result.counts.get(OUTCOME_UNCHANGED, 0)
    missing = result.counts.get(OUTCOME_NOT_PRESENT, 0)
    if updated == 0 and missing == 0 and unchanged:
        return (
            f"No change — all {unchanged} selected change(s) were "
            f"{unchanged_phrase}."
        )
    parts = [f"{total} change(s)"]
    if updated:
        parts.append(f"{updated} {updated_verb}")
    if unchanged:
        parts.append(f"{unchanged} {unchanged_phrase}")
    if missing:
        parts.append(f"{missing} no longer present in this view")
    return " · ".join(parts) + "."
