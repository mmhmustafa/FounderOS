"""Audited policy baselines and calibration previews.

The installed policy pack remains immutable data.  This catalog stores the
operator-approved intent and targeting overlay for a policy.  Draft records do
not affect evaluation; active records are applied with ``effective_pack``.
Historical reports remain readable because the added policy fields have
backward-compatible defaults.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from founderos_atlas.audit import AuditEvent, AuditLog
from founderos_atlas.workspace.exceptions import WorkspaceCorruptedError
from founderos_atlas.workspace.repository import default_workspace_root

from .applicability import (
    INTENT_REQUIRED,
    POLICY_INTENTS,
    PolicyApplicability,
    PolicyContext,
)
from .models import PolicyPack


POLICY_GOVERNANCE_FILENAME = "policy-governance.json"
POLICY_GOVERNANCE_SCHEMA_VERSION = "1.0.0"
BASELINE_STATES = ("draft", "active", "retired")


@dataclass(frozen=True)
class PolicyBaseline:
    policy_id: str
    intent: str
    applicability: PolicyApplicability
    state: str
    owner: str
    reason: str
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    revision: int = 1

    def __post_init__(self) -> None:
        if self.intent not in POLICY_INTENTS:
            raise ValueError(
                "intent must be one of " + ", ".join(POLICY_INTENTS)
            )
        if self.state not in BASELINE_STATES:
            raise ValueError(
                "state must be one of " + ", ".join(BASELINE_STATES)
            )
        if not self.policy_id.strip():
            raise ValueError("policy_id is required")
        if not self.owner.strip():
            raise ValueError("baseline owner is required")
        if not self.reason.strip():
            raise ValueError("baseline reason is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "intent": self.intent,
            "applicability": self.applicability.to_dict(),
            "state": self.state,
            "owner": self.owner,
            "reason": self.reason,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyBaseline":
        return cls(
            policy_id=str(value["policy_id"]),
            intent=str(value.get("intent") or INTENT_REQUIRED),
            applicability=PolicyApplicability.from_dict(
                value.get("applicability")
            ),
            state=str(value.get("state") or "draft"),
            owner=str(value.get("owner") or ""),
            reason=str(value.get("reason") or ""),
            created_at=str(value.get("created_at") or ""),
            created_by=str(value.get("created_by") or ""),
            updated_at=str(value.get("updated_at") or ""),
            updated_by=str(value.get("updated_by") or ""),
            revision=max(1, int(value.get("revision") or 1)),
        )


class PolicyGovernanceConflictError(RuntimeError):
    """The caller edited an older catalog revision."""


class PolicyGovernanceRepository:
    _locks: dict[str, RLock] = {}
    _locks_guard = RLock()

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self._root = (
            Path(workspace_root)
            if workspace_root is not None
            else default_workspace_root()
        )
        with self._locks_guard:
            self._lock = self._locks.setdefault(
                str(self._root.resolve()), RLock()
            )
        self._audit = AuditLog(self._root)

    @property
    def path(self) -> Path:
        return self._root / POLICY_GOVERNANCE_FILENAME

    def _document(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "schema_version": POLICY_GOVERNANCE_SCHEMA_VERSION,
                "revision": 0,
                "baselines": [],
            }
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, Mapping):
                raise ValueError("root must be an object")
            return dict(value)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The policy-governance file {self.path} could not be read: "
                f"{error}"
            ) from error

    def revision(self) -> int:
        return int(self._document().get("revision") or 0)

    def check_revision(self, expected_revision: int | None) -> None:
        if expected_revision is None:
            return
        current = self.revision()
        if int(expected_revision) != current:
            raise PolicyGovernanceConflictError(
                "Policy baselines changed while you were editing "
                f"(revision {current}, you edited {expected_revision}). "
                "Nothing was overwritten; reload and preview again."
            )

    def load(self) -> tuple[PolicyBaseline, ...]:
        try:
            return tuple(
                PolicyBaseline.from_dict(value)
                for value in self._document().get("baselines") or ()
            )
        except (KeyError, TypeError, ValueError) as error:
            raise WorkspaceCorruptedError(
                f"The policy-governance file {self.path} contains an invalid "
                f"baseline: {error}"
            ) from error

    def get(self, policy_id: str) -> PolicyBaseline | None:
        return next(
            (item for item in self.load() if item.policy_id == policy_id),
            None,
        )

    def active(self) -> tuple[PolicyBaseline, ...]:
        return tuple(item for item in self.load() if item.state == "active")

    def save(
        self,
        *,
        policy_id: str,
        intent: str,
        applicability: PolicyApplicability,
        state: str,
        owner: str,
        reason: str,
        actor: str,
        expected_revision: int | None = None,
        occurred_at: str | None = None,
    ) -> PolicyBaseline:
        stamp = occurred_at or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        with self._lock:
            self.check_revision(expected_revision)
            existing = self.get(policy_id)
            item = PolicyBaseline(
                policy_id=str(policy_id).strip(),
                intent=str(intent).strip(),
                applicability=applicability,
                state=str(state).strip(),
                owner=str(owner).strip(),
                reason=str(reason).strip(),
                created_at=existing.created_at if existing else stamp,
                created_by=existing.created_by if existing else actor,
                updated_at=stamp,
                updated_by=actor,
                revision=(existing.revision + 1 if existing else 1),
            )
            remaining = [
                baseline
                for baseline in self.load()
                if baseline.policy_id != item.policy_id
            ]
            self._write(tuple(sorted(
                (*remaining, item), key=lambda baseline: baseline.policy_id
            )))
            self._audit.append(AuditEvent.create(
                category="policy-baseline",
                operation=(
                    "create" if existing is None
                    else "activate" if item.state == "active"
                    else "update"
                ),
                subject=f"policy-baseline:{item.policy_id}",
                actor=actor,
                before=existing.to_dict() if existing else {},
                after=item.to_dict(),
                reason=item.reason,
                occurred_at=stamp,
            ))
            return item

    def _write(self, baselines: tuple[PolicyBaseline, ...]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid4().hex}.writing"
        )
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "schema_version": POLICY_GOVERNANCE_SCHEMA_VERSION,
                        "revision": self.revision() + 1,
                        "baselines": [item.to_dict() for item in baselines],
                    },
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)


def effective_pack(
    pack: PolicyPack, baselines: Sequence[PolicyBaseline]
) -> PolicyPack:
    """Overlay active governance without mutating installed policy data."""

    active = {
        baseline.policy_id: baseline
        for baseline in baselines
        if baseline.state == "active"
    }
    return replace(
        pack,
        policies=tuple(
            replace(
                policy,
                intent=active[policy.policy_id].intent,
                applicability=active[policy.policy_id].applicability,
            )
            if policy.policy_id in active
            else policy
            for policy in pack.policies
        ),
    )


def calibration_preview(
    evaluations: Sequence[Mapping[str, Any]],
    *,
    policy_id: str,
    applicability: PolicyApplicability,
    intent: str,
) -> dict[str, Any]:
    """Dry preview of one policy-baseline change over current results."""

    if intent not in POLICY_INTENTS:
        raise ValueError(
            "intent must be one of " + ", ".join(POLICY_INTENTS)
        )
    rows = [
        row
        for row in evaluations
        if str((row.get("policy") or {}).get("policy_id") or "") == policy_id
    ]
    before = 0
    after = 0
    newly_applicable = 0
    newly_excluded = 0
    projected_failures = 0
    affected: list[dict[str, str]] = []
    for row in rows:
        old = (row.get("applicability") or {}).get("applicable") is not False
        context = PolicyContext.from_mapping(
            row.get("device_context"),
            device_id=str(row.get("device_id") or ""),
            hostname=str(row.get("hostname") or ""),
            network=str(row.get("network") or ""),
        )
        decision = applicability.decide(context)
        before += int(old)
        after += int(decision.applicable)
        newly_applicable += int(not old and decision.applicable)
        newly_excluded += int(old and not decision.applicable)
        projected_failures += int(
            decision.applicable
            and str(row.get("status") or "") in ("fail", "warning")
        )
        if old != decision.applicable:
            affected.append({
                "hostname": context.hostname,
                "change": (
                    "becomes applicable"
                    if decision.applicable
                    else "becomes not applicable"
                ),
                "reason": decision.explanation,
            })

    total = len(rows)
    changed = newly_applicable + newly_excluded
    threshold = max(10, int(total * 0.25))
    broad = changed >= threshold or newly_applicable >= threshold
    preview = {
        "policy_id": policy_id,
        "intent": intent,
        "total_devices": total,
        "applicable_before": before,
        "applicable_after": after,
        "newly_applicable": newly_applicable,
        "newly_excluded": newly_excluded,
        "projected_failures": projected_failures,
        "broad_change": broad,
        "broad_threshold": threshold,
        "affected": affected[:100],
        "affected_truncated": max(0, len(affected) - 100),
    }
    preview["signature"] = sha256(
        json.dumps(preview, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return preview

