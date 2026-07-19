"""Incident cases: the operational lifecycle around investigation reports.

An ``IncidentReport`` (models.py) is an immutable, evidence-based
analysis. A **case** is the mutable operational record wrapped around
one: severity, status, owner, notes, and links to the paths,
predictions, and Compass plans the incident spawned. Cases live in
``incidents.json`` under the workspace root with the same contract as
every other Atlas record: atomic replace, per-store lock, a catalog
revision for optimistic concurrency, and one audit event per mutation.

Statuses: open → acknowledged → resolved (reopenable). ``suppressed``
hides a case from default views without deleting anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from founderos_atlas.audit import AuditEvent, AuditLog

INCIDENTS_FILENAME = "incidents.json"
INCIDENTS_SCHEMA_VERSION = "1.0.0"

STATUS_OPEN = "open"
STATUS_ACKNOWLEDGED = "acknowledged"
STATUS_RESOLVED = "resolved"
STATUS_SUPPRESSED = "suppressed"
CASE_STATUSES = (
    STATUS_OPEN, STATUS_ACKNOWLEDGED, STATUS_RESOLVED, STATUS_SUPPRESSED,
)

SEVERITIES = ("critical", "high", "medium", "low")


class IncidentConflictError(RuntimeError):
    """The caller edited an older revision of the incident catalog."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class CaseNote:
    note_id: str
    author: str
    text: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {"note_id": self.note_id, "author": self.author,
                "text": self.text, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CaseNote":
        return cls(
            note_id=str(value["note_id"]), author=str(value["author"]),
            text=str(value["text"]), created_at=str(value["created_at"]),
        )


@dataclass(frozen=True)
class IncidentCase:
    case_id: str
    scope_id: str
    scope_label: str
    title: str
    severity: str
    status: str
    opened_at: str
    updated_at: str
    opened_by: str
    owner: str | None = None
    description: str = ""
    report_incident_id: str | None = None   # the immutable report behind it
    report_generated_at: str | None = None
    confidence: str | None = None
    affected_devices: tuple[str, ...] = ()
    notes: tuple[CaseNote, ...] = ()
    linked_paths: tuple[str, ...] = ()        # "source→destination" labels
    linked_predictions: tuple[str, ...] = ()  # prediction summaries
    linked_plans: tuple[str, ...] = ()        # compass plan ids
    resolution: str | None = None
    resolved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "scope_id": self.scope_id,
            "scope_label": self.scope_label, "title": self.title,
            "severity": self.severity, "status": self.status,
            "opened_at": self.opened_at, "updated_at": self.updated_at,
            "opened_by": self.opened_by, "owner": self.owner,
            "description": self.description,
            "report_incident_id": self.report_incident_id,
            "report_generated_at": self.report_generated_at,
            "confidence": self.confidence,
            "affected_devices": list(self.affected_devices),
            "notes": [note.to_dict() for note in self.notes],
            "linked_paths": list(self.linked_paths),
            "linked_predictions": list(self.linked_predictions),
            "linked_plans": list(self.linked_plans),
            "resolution": self.resolution,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IncidentCase":
        return cls(
            case_id=str(value["case_id"]),
            scope_id=str(value["scope_id"]),
            scope_label=str(value.get("scope_label") or value["scope_id"]),
            title=str(value["title"]),
            severity=str(value.get("severity") or "medium"),
            status=str(value.get("status") or STATUS_OPEN),
            opened_at=str(value["opened_at"]),
            updated_at=str(value.get("updated_at") or value["opened_at"]),
            opened_by=str(value.get("opened_by") or "local-operator"),
            owner=(str(value["owner"]) if value.get("owner") else None),
            description=str(value.get("description") or ""),
            report_incident_id=value.get("report_incident_id"),
            report_generated_at=value.get("report_generated_at"),
            confidence=value.get("confidence"),
            affected_devices=tuple(
                str(item) for item in value.get("affected_devices") or ()
            ),
            notes=tuple(
                CaseNote.from_dict(item) for item in value.get("notes") or ()
            ),
            linked_paths=tuple(
                str(item) for item in value.get("linked_paths") or ()
            ),
            linked_predictions=tuple(
                str(item) for item in value.get("linked_predictions") or ()
            ),
            linked_plans=tuple(
                str(item) for item in value.get("linked_plans") or ()
            ),
            resolution=value.get("resolution"),
            resolved_at=value.get("resolved_at"),
        )


_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


def _lock_for(path: Path) -> RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path), RLock())


class IncidentCaseRepository:
    def __init__(self, workspace_root: str | Path) -> None:
        self._root = Path(workspace_root)
        self.path = self._root / INCIDENTS_FILENAME
        self._lock = _lock_for(self.path)
        self._audit = AuditLog(self._root)

    # -- reading -----------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"schema_version": INCIDENTS_SCHEMA_VERSION,
                    "revision": 0, "cases": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def revision(self) -> int:
        return int(self._read().get("revision") or 0)

    def check_revision(self, expected_revision: int | None) -> None:
        if expected_revision is None:
            return
        current = self.revision()
        if int(expected_revision) != current:
            raise IncidentConflictError(
                "The incident changed while you were editing (revision "
                f"{current}, you edited {expected_revision}). Nothing was "
                "overwritten — reload and reapply your change."
            )

    def list(
        self, *, scope_id: str | None = None, include_suppressed: bool = False,
        status: str | None = None, include_resolved: bool = True,
    ) -> list[IncidentCase]:
        """``include_resolved`` defaults True so every existing caller
        (including the writers, which rebuild the catalog through this
        method) keeps seeing the full set; the list PAGE passes False so
        its default view shows active work only."""

        cases = [
            IncidentCase.from_dict(item)
            for item in self._read().get("cases") or ()
        ]
        if scope_id:
            cases = [case for case in cases if case.scope_id == scope_id]
        if status:
            cases = [case for case in cases if case.status == status]
        else:
            if not include_suppressed:
                cases = [
                    case for case in cases
                    if case.status != STATUS_SUPPRESSED
                ]
            if not include_resolved:
                cases = [
                    case for case in cases
                    if case.status != STATUS_RESOLVED
                ]
        cases.sort(key=lambda case: case.opened_at, reverse=True)
        return cases

    def find_active(
        self, *, scope_id: str, title: str
    ) -> IncidentCase | None:
        """The newest open/acknowledged case with this title in this
        scope — the duplicate guard's question when an investigation is
        re-run."""

        wanted = str(title or "").strip().casefold()
        for case in self.list(scope_id=scope_id):
            if (
                case.status in (STATUS_OPEN, STATUS_ACKNOWLEDGED)
                and case.title.strip().casefold() == wanted
            ):
                return case
        return None

    def get(self, case_id: str) -> IncidentCase | None:
        for item in self._read().get("cases") or ():
            if str(item.get("case_id")) == case_id:
                return IncidentCase.from_dict(item)
        return None

    # -- writing -----------------------------------------------------------

    def _write(self, cases: list[IncidentCase], revision: int) -> None:
        payload = {
            "schema_version": INCIDENTS_SCHEMA_VERSION,
            "revision": revision,
            "cases": [case.to_dict() for case in cases],
        }
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.writing")
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _audit_case(
        self, operation: str, case: IncidentCase, *, actor: str,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self._audit.append(AuditEvent.create(
            category="incident", operation=operation,
            subject=f"incident:{case.case_id}",
            scope_id=case.scope_id, actor=actor,
            before=before or {}, after=after or {}, reason=reason,
            correlation_id=correlation_id,
        ))

    def open_case(
        self,
        *,
        scope_id: str,
        scope_label: str,
        title: str,
        description: str = "",
        severity: str = "medium",
        actor: str = "local-operator",
        report: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> IncidentCase:
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
        if not str(title or "").strip():
            raise ValueError("an incident needs a title")
        stamp = _now()
        case = IncidentCase(
            case_id=f"CASE-{uuid4().hex[:10]}",
            scope_id=scope_id, scope_label=scope_label,
            title=title.strip(), severity=severity, status=STATUS_OPEN,
            opened_at=stamp, updated_at=stamp, opened_by=actor,
            description=description.strip(),
            report_incident_id=(report or {}).get("incident_id"),
            report_generated_at=(report or {}).get("generated_at"),
            confidence=(report or {}).get("confidence"),
            affected_devices=tuple(
                str(item) for item in (report or {}).get("affected_devices") or ()
            ),
        )
        with self._lock:
            revision = self.revision()
            self._write([*self.list(include_suppressed=True), case],
                        revision + 1)
        self._audit_case(
            "open", case, actor=actor,
            after={"severity": severity, "status": STATUS_OPEN},
            correlation_id=correlation_id,
        )
        return case

    def _mutate(
        self, case_id: str, expected_revision: int | None,
        mutator, *, operation: str, actor: str,
        reason: str | None = None, correlation_id: str | None = None,
    ) -> IncidentCase:
        with self._lock:
            self.check_revision(expected_revision)
            cases = self.list(include_suppressed=True)
            existing = next(
                (case for case in cases if case.case_id == case_id), None
            )
            if existing is None:
                raise ValueError("No such incident case exists.")
            updated = mutator(existing)
            updated = replace(updated, updated_at=_now())
            self._write(
                [updated if case.case_id == case_id else case
                 for case in cases],
                self.revision() + 1,
            )
        self._audit_case(
            operation, updated, actor=actor, reason=reason,
            before={"status": existing.status, "severity": existing.severity,
                    "owner": existing.owner},
            after={"status": updated.status, "severity": updated.severity,
                   "owner": updated.owner},
            correlation_id=correlation_id,
        )
        return updated

    def acknowledge(self, case_id: str, *, actor: str,
                    expected_revision: int | None = None) -> IncidentCase:
        return self._mutate(
            case_id, expected_revision,
            lambda case: replace(case, status=STATUS_ACKNOWLEDGED),
            operation="acknowledge", actor=actor,
        )

    def assign(self, case_id: str, *, owner: str, actor: str,
               expected_revision: int | None = None) -> IncidentCase:
        if not str(owner or "").strip():
            raise ValueError("an assignment needs an owner")
        return self._mutate(
            case_id, expected_revision,
            lambda case: replace(case, owner=owner.strip()),
            operation="assign", actor=actor,
        )

    def annotate(self, case_id: str, *, text: str, actor: str,
                 expected_revision: int | None = None) -> IncidentCase:
        if not str(text or "").strip():
            raise ValueError("a note needs text")
        note = CaseNote(
            note_id=f"note-{uuid4().hex[:8]}", author=actor,
            text=text.strip(), created_at=_now(),
        )
        return self._mutate(
            case_id, expected_revision,
            lambda case: replace(case, notes=(*case.notes, note)),
            operation="annotate", actor=actor, reason=text.strip()[:200],
        )

    def refresh_evidence(
        self, case_id: str, *, report, actor: str,
        correlation_id: str | None = None,
    ) -> IncidentCase:
        """Attach a newer investigation report to an existing case.
        The case's identity, status, ownership, and annotations stay;
        only the evidence pointers move to the fresh report — audited
        as a reinvestigation, never as a new case."""

        stamp = _now()
        return self._mutate(
            case_id, None,
            lambda case: replace(
                case,
                report_incident_id=(report or {}).get("incident_id"),
                report_generated_at=(report or {}).get("generated_at"),
                confidence=(report or {}).get("confidence"),
                affected_devices=tuple(
                    str(item)
                    for item in (report or {}).get("affected_devices") or ()
                ),
                updated_at=stamp,
            ),
            operation="reinvestigate", actor=actor,
            correlation_id=correlation_id,
        )

    def suppress(self, case_id: str, *, reason: str, actor: str,
                 expected_revision: int | None = None,
                 correlation_id: str | None = None) -> IncidentCase:
        if not str(reason or "").strip():
            raise ValueError("suppressing an incident requires a reason")
        return self._mutate(
            case_id, expected_revision,
            lambda case: replace(case, status=STATUS_SUPPRESSED),
            operation="suppress", actor=actor, reason=reason,
            correlation_id=correlation_id,
        )

    def resolve(self, case_id: str, *, resolution: str, actor: str,
                expected_revision: int | None = None,
                correlation_id: str | None = None) -> IncidentCase:
        if not str(resolution or "").strip():
            raise ValueError("resolving an incident requires a resolution")
        stamp = _now()
        return self._mutate(
            case_id, expected_revision,
            lambda case: replace(
                case, status=STATUS_RESOLVED,
                resolution=resolution.strip(), resolved_at=stamp,
            ),
            operation="resolve", actor=actor, reason=resolution,
            correlation_id=correlation_id,
        )

    def reopen(self, case_id: str, *, reason: str, actor: str,
               expected_revision: int | None = None) -> IncidentCase:
        if not str(reason or "").strip():
            raise ValueError("reopening an incident requires a reason")
        return self._mutate(
            case_id, expected_revision,
            lambda case: replace(
                case, status=STATUS_OPEN, resolution=None, resolved_at=None,
            ),
            operation="reopen", actor=actor, reason=reason,
        )

    def set_severity(self, case_id: str, *, severity: str, actor: str,
                     expected_revision: int | None = None) -> IncidentCase:
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
        return self._mutate(
            case_id, expected_revision,
            lambda case: replace(case, severity=severity),
            operation="set-severity", actor=actor,
        )

    def link(
        self, case_id: str, *, kind: str, value: str, actor: str,
        correlation_id: str | None = None,
    ) -> IncidentCase:
        """Attach a path/prediction/plan reference to the case."""

        fields = {
            "path": "linked_paths",
            "prediction": "linked_predictions",
            "plan": "linked_plans",
        }
        if kind not in fields:
            raise ValueError("link kind must be path, prediction, or plan")
        name = fields[kind]

        def add(case: IncidentCase) -> IncidentCase:
            existing = getattr(case, name)
            if value in existing:
                return case
            return replace(case, **{name: (*existing, value)})

        return self._mutate(
            case_id, None, add, operation=f"link-{kind}", actor=actor,
            reason=value, correlation_id=correlation_id,
        )
