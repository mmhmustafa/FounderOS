"""Durable scheduled discovery and maintenance-window contracts.

Atlas supports one process per workspace.  The scheduler therefore uses one
in-process worker, while persisted leases and idempotency keys make restart
recovery explicit and prevent a due schedule from being launched twice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from founderos_atlas.audit import AuditEvent, AuditLog

SCHEDULES_FILENAME = "schedules.json"
SCHEDULES_SCHEMA_VERSION = "1.0.0"

RECURRENCE_ONCE = "once"
RECURRENCE_INTERVAL = "interval"
RECURRENCE_DAILY = "daily"
RECURRENCES = (RECURRENCE_ONCE, RECURRENCE_INTERVAL, RECURRENCE_DAILY)
MISFIRE_SKIP = "skip"
MISFIRE_RUN_ONCE = "run-once"
MISFIRE_POLICIES = (MISFIRE_SKIP, MISFIRE_RUN_ONCE)

RUN_CLAIMED = "claimed"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"
RUN_STATUSES = (RUN_CLAIMED, RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED)


class ScheduleConflictError(RuntimeError):
    """The caller attempted to replace a newer schedule catalog."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("scheduled timestamps must include a timezone")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value))


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"unknown timezone {name!r}") from error


@dataclass(frozen=True)
class DiscoverySchedule:
    schedule_id: str
    profile_id: str
    name: str
    recurrence: str
    timezone_name: str
    next_run_at: str
    created_at: str
    updated_at: str
    enabled: bool = True
    interval_minutes: int | None = None
    daily_time: str | None = None
    misfire_policy: str = MISFIRE_RUN_ONCE
    max_retries: int = 0
    retry_delay_minutes: int = 5
    last_run_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    lease_owner: str | None = None
    lease_until: str | None = None
    active_run_id: str | None = None
    retry_attempt: int = 1
    retry_origin_at: str | None = None
    revision: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > 120:
            raise ValueError("schedule name must contain 1 to 120 characters")
        if not self.profile_id.strip() or len(self.profile_id) > 256:
            raise ValueError("schedule profile id is invalid")
        if self.recurrence not in RECURRENCES:
            raise ValueError(f"recurrence must be one of {RECURRENCES}")
        if self.misfire_policy not in MISFIRE_POLICIES:
            raise ValueError(f"misfire_policy must be one of {MISFIRE_POLICIES}")
        _zone(self.timezone_name)
        _parse(self.next_run_at)
        if self.retry_origin_at:
            _parse(self.retry_origin_at)
        if self.recurrence == RECURRENCE_INTERVAL and (
            self.interval_minutes is None
            or not 1 <= self.interval_minutes <= 525_600
        ):
            raise ValueError(
                "interval schedules require 1 to 525600 minutes"
            )
        if self.recurrence == RECURRENCE_DAILY:
            _parse_daily_time(self.daily_time)
        if (
            not 0 <= self.max_retries <= 10
            or not 1 <= self.retry_delay_minutes <= 1440
        ):
            raise ValueError("retry settings must be non-negative and bounded")

    def to_dict(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiscoverySchedule":
        return cls(
            schedule_id=str(value["schedule_id"]),
            profile_id=str(value["profile_id"]),
            name=str(value["name"]),
            recurrence=str(value["recurrence"]),
            timezone_name=str(value.get("timezone_name") or "UTC"),
            next_run_at=str(value["next_run_at"]),
            created_at=str(value["created_at"]),
            updated_at=str(value.get("updated_at") or value["created_at"]),
            enabled=bool(value.get("enabled", True)),
            interval_minutes=(
                int(value["interval_minutes"])
                if value.get("interval_minutes") is not None else None
            ),
            daily_time=(
                str(value["daily_time"]) if value.get("daily_time") else None
            ),
            misfire_policy=str(
                value.get("misfire_policy") or MISFIRE_RUN_ONCE
            ),
            max_retries=int(value.get("max_retries") or 0),
            retry_delay_minutes=int(value.get("retry_delay_minutes") or 5),
            last_run_at=(
                str(value["last_run_at"]) if value.get("last_run_at") else None
            ),
            last_status=(
                str(value["last_status"]) if value.get("last_status") else None
            ),
            last_error=(
                str(value["last_error"]) if value.get("last_error") else None
            ),
            lease_owner=(
                str(value["lease_owner"]) if value.get("lease_owner") else None
            ),
            lease_until=(
                str(value["lease_until"]) if value.get("lease_until") else None
            ),
            active_run_id=(
                str(value["active_run_id"])
                if value.get("active_run_id") else None
            ),
            retry_attempt=max(1, int(value.get("retry_attempt") or 1)),
            retry_origin_at=(
                str(value["retry_origin_at"])
                if value.get("retry_origin_at") else None
            ),
            revision=max(1, int(value.get("revision") or 1)),
        )


@dataclass(frozen=True)
class ScheduledRun:
    run_id: str
    schedule_id: str
    profile_id: str
    idempotency_key: str
    due_at: str
    claimed_at: str
    status: str = RUN_CLAIMED
    attempt: int = 1
    job_id: str | None = None
    completed_at: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id or not self.schedule_id or not self.profile_id:
            raise ValueError("scheduled run identity is incomplete")
        if not self.idempotency_key or not self.due_at or not self.claimed_at:
            raise ValueError("scheduled run provenance is incomplete")
        if self.status not in RUN_STATUSES:
            raise ValueError("scheduled run has an invalid status")
        if int(self.attempt) < 1:
            raise ValueError("scheduled run attempt must be positive")
        _parse(self.due_at)
        _parse(self.claimed_at)
        if self.completed_at:
            _parse(self.completed_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScheduledRun":
        return cls(
            run_id=str(value["run_id"]),
            schedule_id=str(value["schedule_id"]),
            profile_id=str(value["profile_id"]),
            idempotency_key=str(value["idempotency_key"]),
            due_at=str(value["due_at"]),
            claimed_at=str(value["claimed_at"]),
            status=str(value.get("status") or RUN_CLAIMED),
            attempt=max(1, int(value.get("attempt") or 1)),
            job_id=(str(value["job_id"]) if value.get("job_id") else None),
            completed_at=(
                str(value["completed_at"])
                if value.get("completed_at") else None
            ),
            error=(str(value["error"]) if value.get("error") else None),
        )


@dataclass(frozen=True)
class MaintenanceWindow:
    window_id: str
    name: str
    starts_at: str
    ends_at: str
    timezone_name: str
    scope_type: str = "global"
    scope_id: str | None = None
    suppress_notifications: bool = True
    reason: str = ""
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > 120:
            raise ValueError(
                "maintenance window name must contain 1 to 120 characters"
            )
        if len(self.reason) > 1000:
            raise ValueError("maintenance reason is too long")
        _zone(self.timezone_name)
        if _parse(self.ends_at) <= _parse(self.starts_at):
            raise ValueError("maintenance window end must be after its start")
        if self.scope_type not in {"global", "profile", "site"}:
            raise ValueError("maintenance scope must be global, profile, or site")
        if self.scope_type != "global" and not self.scope_id:
            raise ValueError("profile/site maintenance needs a scope id")

    def to_dict(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MaintenanceWindow":
        return cls(**{
            key: value.get(key, field.default)
            for key, field in cls.__dataclass_fields__.items()
        })


def validate_schedule_catalog(value: Any) -> None:
    """Validate persisted scheduling state beyond JSON syntax."""

    if not isinstance(value, Mapping):
        raise ValueError("schedule catalog must be an object")
    schema = value.get("schema_version")
    if schema not in (None, SCHEDULES_SCHEMA_VERSION):
        raise ValueError(f"unsupported schedule schema version {schema!r}")
    revision = value.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("schedule catalog revision must be non-negative")
    raw_schedules = value.get("schedules", [])
    raw_runs = value.get("runs", [])
    raw_windows = value.get("maintenance_windows", [])
    if not all(isinstance(items, list) for items in (
        raw_schedules, raw_runs, raw_windows
    )):
        raise ValueError("schedule catalog collections must be arrays")
    if not all(
        isinstance(item, Mapping)
        for items in (raw_schedules, raw_runs, raw_windows)
        for item in items
    ):
        raise ValueError("schedule catalog records must be objects")
    schedules = [DiscoverySchedule.from_dict(item) for item in raw_schedules]
    runs = [ScheduledRun.from_dict(item) for item in raw_runs]
    windows = [MaintenanceWindow.from_dict(item) for item in raw_windows]

    def unique(values, label: str) -> None:
        if len(values) != len(set(values)):
            raise ValueError(f"schedule catalog contains duplicate {label}")

    unique([item.schedule_id for item in schedules], "schedule ids")
    unique([item.run_id for item in runs], "run ids")
    unique([item.idempotency_key for item in runs], "idempotency keys")
    unique([item.window_id for item in windows], "maintenance ids")
    runs_by_id = {item.run_id: item for item in runs}
    for schedule in schedules:
        if schedule.active_run_id:
            active = runs_by_id.get(schedule.active_run_id)
            if (
                active is None
                or active.schedule_id != schedule.schedule_id
                or active.status != RUN_CLAIMED
                or not schedule.lease_owner
                or not schedule.lease_until
            ):
                raise ValueError(
                    f"schedule {schedule.schedule_id!r} has an invalid "
                    "active-run lease"
                )
        elif schedule.lease_owner or schedule.lease_until:
            raise ValueError(
                f"schedule {schedule.schedule_id!r} has an orphaned lease"
            )


_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


def _lock_for(path: Path) -> RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path.resolve()), RLock())


class ScheduleStore:
    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root)
        self.path = self.root / SCHEDULES_FILENAME
        self._lock = _lock_for(self.path)
        self._audit = AuditLog(self.root)

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "schema_version": SCHEDULES_SCHEMA_VERSION,
                "revision": 0,
                "schedules": [],
                "runs": [],
                "maintenance_windows": [],
            }
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"could not read schedules: {error}") from error
        if not isinstance(value, dict):
            raise ValueError("schedule catalog must be an object")
        validate_schedule_catalog(value)
        return value

    def _write(self, value: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.writing")
        try:
            temporary.write_text(
                json.dumps(dict(value), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def revision(self) -> int:
        return int(self._read().get("revision") or 0)

    def schedules(self) -> list[DiscoverySchedule]:
        return [
            DiscoverySchedule.from_dict(item)
            for item in self._read().get("schedules") or ()
        ]

    def runs(self, *, limit: int = 100) -> list[ScheduledRun]:
        values = [
            ScheduledRun.from_dict(item)
            for item in self._read().get("runs") or ()
        ]
        return list(reversed(values[-max(1, min(limit, 1000)):]))

    def maintenance_windows(self) -> list[MaintenanceWindow]:
        return [
            MaintenanceWindow.from_dict(item)
            for item in self._read().get("maintenance_windows") or ()
        ]

    def _check(self, expected_revision: int | None) -> None:
        if (
            expected_revision is not None
            and int(expected_revision) != self.revision()
        ):
            raise ScheduleConflictError(
                "Schedules changed while you were editing. Reload and retry."
            )

    def create_schedule(
        self,
        *,
        profile_id: str,
        name: str,
        recurrence: str,
        timezone_name: str,
        first_run_at: datetime,
        interval_minutes: int | None = None,
        daily_time: str | None = None,
        misfire_policy: str = MISFIRE_RUN_ONCE,
        max_retries: int = 0,
        retry_delay_minutes: int = 5,
        actor: str = "local-operator",
        expected_revision: int | None = None,
    ) -> DiscoverySchedule:
        stamp = _stamp(datetime.now(timezone.utc))
        schedule = DiscoverySchedule(
            schedule_id=f"schedule:{uuid4().hex}",
            profile_id=str(profile_id),
            name=str(name).strip(),
            recurrence=recurrence,
            timezone_name=timezone_name,
            next_run_at=_stamp(first_run_at),
            created_at=stamp,
            updated_at=stamp,
            interval_minutes=interval_minutes,
            daily_time=daily_time,
            misfire_policy=misfire_policy,
            max_retries=max_retries,
            retry_delay_minutes=retry_delay_minutes,
        )
        if not schedule.name:
            raise ValueError("schedule name is required")
        with self._lock:
            self._check(expected_revision)
            value = self._read()
            value["schedules"] = [
                *value.get("schedules", []), schedule.to_dict()
            ]
            value["revision"] = int(value.get("revision") or 0) + 1
            self._write(value)
        self._audit.append(AuditEvent.create(
            category="schedule",
            operation="create",
            subject=schedule.schedule_id,
            actor=actor,
            after={
                "profile_id": schedule.profile_id,
                "recurrence": schedule.recurrence,
                "next_run_at": schedule.next_run_at,
            },
        ))
        return schedule

    def set_enabled(
        self,
        schedule_id: str,
        enabled: bool,
        *,
        actor: str = "local-operator",
        expected_revision: int | None = None,
    ) -> DiscoverySchedule:
        with self._lock:
            self._check(expected_revision)
            value = self._read()
            schedules = [
                DiscoverySchedule.from_dict(item)
                for item in value.get("schedules") or ()
            ]
            current = next(
                (item for item in schedules if item.schedule_id == schedule_id),
                None,
            )
            if current is None:
                raise ValueError("no such schedule")
            updated = replace(
                current,
                enabled=bool(enabled),
                updated_at=_stamp(datetime.now(timezone.utc)),
                revision=current.revision + 1,
            )
            value["schedules"] = [
                (updated if item.schedule_id == schedule_id else item).to_dict()
                for item in schedules
            ]
            value["revision"] = int(value.get("revision") or 0) + 1
            self._write(value)
        self._audit.append(AuditEvent.create(
            category="schedule",
            operation="resume" if enabled else "pause",
            subject=schedule_id,
            actor=actor,
            after={"enabled": bool(enabled)},
        ))
        return updated

    def claim_due(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int = 300,
    ) -> list[ScheduledRun]:
        moment = _utc(now)
        claimed: list[ScheduledRun] = []
        catalog_changed = False
        with self._lock:
            value = self._read()
            schedules = [
                DiscoverySchedule.from_dict(item)
                for item in value.get("schedules") or ()
            ]
            runs = [
                ScheduledRun.from_dict(item)
                for item in value.get("runs") or ()
            ]
            updated: list[DiscoverySchedule] = []
            for schedule in schedules:
                lease_active = bool(
                    schedule.lease_until
                    and _parse(schedule.lease_until) > moment
                )
                # A process can stop after claiming an occurrence.  Once its
                # lease expires, close that exact run explicitly before
                # applying the configured retry/recurrence policy.  Leaving
                # it forever "claimed" makes restart recovery look healthy
                # while silently losing the occurrence.
                if schedule.active_run_id and not lease_active:
                    abandoned = next(
                        (
                            run for run in runs
                            if run.run_id == schedule.active_run_id
                        ),
                        None,
                    )
                    if abandoned is not None and abandoned.status == RUN_CLAIMED:
                        recovered = replace(
                            abandoned,
                            status=RUN_FAILED,
                            completed_at=_stamp(moment),
                            error=(
                                "The scheduler worker lease expired before "
                                "completion; the discovery outcome is unknown."
                            ),
                        )
                        runs = [
                            recovered if run.run_id == recovered.run_id else run
                            for run in runs
                        ]
                        updated.append(_after_terminal(
                            schedule,
                            attempt=abandoned.attempt,
                            status=RUN_FAILED,
                            moment=moment,
                            error=recovered.error,
                        ))
                        catalog_changed = True
                        continue
                    # A stale lease referencing no active run is repaired
                    # without manufacturing a successful occurrence.
                    schedule = replace(
                        schedule,
                        lease_owner=None,
                        lease_until=None,
                        active_run_id=None,
                        updated_at=_stamp(moment),
                        revision=schedule.revision + 1,
                    )
                    catalog_changed = True
                if (
                    not schedule.enabled
                    or _parse(schedule.next_run_at) > moment
                    or lease_active
                ):
                    updated.append(schedule)
                    continue
                if (
                    schedule.misfire_policy == MISFIRE_SKIP
                    and (moment - _parse(schedule.next_run_at)).total_seconds()
                    > 300
                ):
                    updated.append(
                        _advance(
                            schedule,
                            moment,
                            status="skipped-misfire",
                            error="A missed run was skipped by policy.",
                        )
                    )
                    catalog_changed = True
                    continue
                due = schedule.next_run_at
                key = f"{schedule.schedule_id}:{due}"
                duplicate = next(
                    (run for run in runs if run.idempotency_key == key),
                    None,
                )
                if duplicate is not None:
                    updated.append(
                        _after_terminal(
                            schedule,
                            attempt=duplicate.attempt,
                            status=(
                                duplicate.status
                                if duplicate.status != RUN_CLAIMED
                                else RUN_FAILED
                            ),
                            moment=moment,
                            error=(
                                duplicate.error
                                or "An incomplete duplicate occurrence was "
                                "reconciled without relaunching it."
                            ),
                        )
                    )
                    catalog_changed = True
                    continue
                run = ScheduledRun(
                    run_id=f"scheduled-run:{uuid4().hex}",
                    schedule_id=schedule.schedule_id,
                    profile_id=schedule.profile_id,
                    idempotency_key=key,
                    due_at=due,
                    claimed_at=_stamp(moment),
                    attempt=schedule.retry_attempt,
                )
                runs.append(run)
                claimed.append(run)
                catalog_changed = True
                updated.append(replace(
                    schedule,
                    lease_owner=worker_id,
                    lease_until=_stamp(
                        moment + timedelta(seconds=max(30, lease_seconds))
                    ),
                    active_run_id=run.run_id,
                    updated_at=_stamp(moment),
                    revision=schedule.revision + 1,
                ))
            if catalog_changed:
                value["schedules"] = [item.to_dict() for item in updated]
                value["runs"] = [item.to_dict() for item in runs[-1000:]]
                value["revision"] = int(value.get("revision") or 0) + 1
                self._write(value)
        return claimed

    def attach_job(
        self,
        run_id: str,
        *,
        worker_id: str,
        job_id: str,
        now: datetime,
        lease_seconds: int = 300,
    ) -> ScheduledRun:
        """Persist the job/run relationship and renew its owning lease."""

        moment = _utc(now)
        with self._lock:
            value = self._read()
            runs = [
                ScheduledRun.from_dict(item)
                for item in value.get("runs") or ()
            ]
            current = next((item for item in runs if item.run_id == run_id), None)
            if current is None or current.status != RUN_CLAIMED:
                raise ScheduleConflictError(
                    "The scheduled run is no longer claimable."
                )
            schedules = [
                DiscoverySchedule.from_dict(item)
                for item in value.get("schedules") or ()
            ]
            owner = next(
                (
                    item for item in schedules
                    if item.schedule_id == current.schedule_id
                ),
                None,
            )
            if (
                owner is None
                or owner.active_run_id != run_id
                or owner.lease_owner != worker_id
            ):
                raise ScheduleConflictError(
                    "The scheduler worker no longer owns this run."
                )
            attached = replace(current, job_id=str(job_id))
            renewed = replace(
                owner,
                lease_until=_stamp(
                    moment + timedelta(seconds=max(30, lease_seconds))
                ),
            )
            value["runs"] = [
                (attached if item.run_id == run_id else item).to_dict()
                for item in runs
            ]
            value["schedules"] = [
                (
                    renewed if item.schedule_id == owner.schedule_id else item
                ).to_dict()
                for item in schedules
            ]
            self._write(value)
        return attached

    def renew_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int = 300,
    ) -> bool:
        """Heartbeat a running job without changing its due occurrence."""

        moment = _utc(now)
        with self._lock:
            value = self._read()
            runs = [
                ScheduledRun.from_dict(item)
                for item in value.get("runs") or ()
            ]
            current = next((item for item in runs if item.run_id == run_id), None)
            if current is None or current.status != RUN_CLAIMED:
                return False
            schedules = [
                DiscoverySchedule.from_dict(item)
                for item in value.get("schedules") or ()
            ]
            owner = next(
                (
                    item for item in schedules
                    if item.schedule_id == current.schedule_id
                ),
                None,
            )
            if (
                owner is None
                or owner.active_run_id != run_id
                or owner.lease_owner != worker_id
            ):
                return False
            renewed = replace(
                owner,
                lease_until=_stamp(
                    moment + timedelta(seconds=max(30, lease_seconds))
                ),
            )
            value["schedules"] = [
                (
                    renewed if item.schedule_id == owner.schedule_id else item
                ).to_dict()
                for item in schedules
            ]
            self._write(value)
        return True

    def complete_run(
        self,
        run_id: str,
        *,
        status: str,
        now: datetime,
        error: str | None = None,
    ) -> ScheduledRun:
        if status not in {RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED}:
            raise ValueError("scheduled run has an invalid terminal status")
        moment = _utc(now)
        with self._lock:
            value = self._read()
            runs = [
                ScheduledRun.from_dict(item)
                for item in value.get("runs") or ()
            ]
            current = next((item for item in runs if item.run_id == run_id), None)
            if current is None:
                raise ValueError("no such scheduled run")
            if current.status != RUN_CLAIMED:
                return current
            completed = replace(
                current,
                status=status,
                completed_at=_stamp(moment),
                error=(str(error)[:1000] if error else None),
            )
            schedules = [
                DiscoverySchedule.from_dict(item)
                for item in value.get("schedules") or ()
            ]
            updated_schedules: list[DiscoverySchedule] = []
            for schedule in schedules:
                if schedule.schedule_id != current.schedule_id:
                    updated_schedules.append(schedule)
                    continue
                # A late worker result may arrive after its lease was
                # recovered and a newer occurrence claimed.  Preserve the
                # attempt result, but never let it advance or overwrite the
                # schedule now owned by another run.
                if schedule.active_run_id != current.run_id:
                    updated_schedules.append(schedule)
                    continue
                updated_schedules.append(_after_terminal(
                    schedule,
                    attempt=current.attempt,
                    status=status,
                    moment=moment,
                    error=completed.error,
                ))
            value["runs"] = [
                (completed if item.run_id == run_id else item).to_dict()
                for item in runs
            ]
            value["schedules"] = [
                item.to_dict() for item in updated_schedules
            ]
            value["revision"] = int(value.get("revision") or 0) + 1
            self._write(value)
        return completed

    def add_maintenance_window(
        self,
        *,
        name: str,
        starts_at: datetime,
        ends_at: datetime,
        timezone_name: str,
        scope_type: str = "global",
        scope_id: str | None = None,
        suppress_notifications: bool = True,
        reason: str = "",
        actor: str = "local-operator",
        expected_revision: int | None = None,
    ) -> MaintenanceWindow:
        window = MaintenanceWindow(
            window_id=f"maintenance:{uuid4().hex}",
            name=str(name).strip(),
            starts_at=_stamp(starts_at),
            ends_at=_stamp(ends_at),
            timezone_name=timezone_name,
            scope_type=scope_type,
            scope_id=scope_id,
            suppress_notifications=bool(suppress_notifications),
            reason=str(reason).strip(),
        )
        if not window.name:
            raise ValueError("maintenance window name is required")
        if not window.reason:
            raise ValueError("maintenance reason is required")
        with self._lock:
            self._check(expected_revision)
            value = self._read()
            value["maintenance_windows"] = [
                *value.get("maintenance_windows", []), window.to_dict()
            ]
            value["revision"] = int(value.get("revision") or 0) + 1
            self._write(value)
        self._audit.append(AuditEvent.create(
            category="maintenance",
            operation="create",
            subject=window.window_id,
            actor=actor,
            after={
                "name": window.name,
                "starts_at": window.starts_at,
                "ends_at": window.ends_at,
                "scope_type": window.scope_type,
                "scope_id": window.scope_id,
                "suppress_notifications": window.suppress_notifications,
                "reason": window.reason,
            },
        ))
        return window

    def active_maintenance(
        self,
        *,
        now: datetime,
        profile_id: str | None = None,
        site_id: str | None = None,
    ) -> list[MaintenanceWindow]:
        moment = _utc(now)
        return [
            item
            for item in self.maintenance_windows()
            if item.enabled
            and _parse(item.starts_at) <= moment < _parse(item.ends_at)
            and (
                item.scope_type == "global"
                or (item.scope_type == "profile" and item.scope_id == profile_id)
                or (item.scope_type == "site" and item.scope_id == site_id)
            )
        ]


def _parse_daily_time(value: str | None) -> tuple[int, int]:
    if not value or len(value.split(":")) != 2:
        raise ValueError("daily schedules require daily_time as HH:MM")
    try:
        hour, minute = (int(item) for item in value.split(":"))
    except ValueError as error:
        raise ValueError("daily_time must be HH:MM") from error
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("daily_time must be a valid 24-hour time")
    return hour, minute


def _next_daily(schedule: DiscoverySchedule, after: datetime) -> datetime:
    zone = _zone(schedule.timezone_name)
    hour, minute = _parse_daily_time(schedule.daily_time)
    moment = _utc(after)
    local_day = moment.astimezone(zone).date()
    candidate = _daily_occurrence(local_day, hour, minute, zone)
    if candidate <= moment:
        candidate = _daily_occurrence(
            local_day + timedelta(days=1), hour, minute, zone
        )
    return candidate


def _valid_local_instants(value: datetime, zone: ZoneInfo) -> list[datetime]:
    """Return the distinct UTC instants represented by a local wall time."""

    if value.tzinfo is not None:
        raise ValueError("local wall time must be naive")
    instants: dict[datetime, datetime] = {}
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold)
        utc_value = candidate.astimezone(timezone.utc)
        round_trip = utc_value.astimezone(zone).replace(tzinfo=None)
        if round_trip == value:
            instants[utc_value] = utc_value
    return sorted(instants)


def resolve_local_datetime(value: datetime, timezone_name: str) -> datetime:
    """Resolve an operator-entered local time without DST guesswork.

    Browser ``datetime-local`` fields cannot express which side of a fall-back
    fold was intended.  Ambiguous and nonexistent values are therefore
    rejected instead of silently running an hour early or late.  An explicit
    offset supplied by an API client is already unambiguous and is preserved.
    """

    if value.tzinfo is not None:
        return value
    zone = _zone(timezone_name)
    instants = _valid_local_instants(value, zone)
    if not instants:
        raise ValueError(
            f"{value:%Y-%m-%d %H:%M} does not exist in {timezone_name} "
            "because of a daylight-saving clock change."
        )
    if len(instants) > 1:
        raise ValueError(
            f"{value:%Y-%m-%d %H:%M} occurs twice in {timezone_name} "
            "because of a daylight-saving clock change. Choose another "
            "time or submit an explicit UTC offset."
        )
    return instants[0].astimezone(zone)


def _daily_occurrence(
    day: date, hour: int, minute: int, zone: ZoneInfo
) -> datetime:
    """Resolve a recurring wall time deterministically across DST changes.

    A spring-forward gap runs at the first valid local minute after the gap.
    A fall-back fold runs once, at the first occurrence.  The policy is stable
    across restarts because the resulting UTC instant is persisted.
    """

    wall = datetime.combine(day, time(hour=hour, minute=minute))
    for offset in range(181):
        candidate = wall + timedelta(minutes=offset)
        instants = _valid_local_instants(candidate, zone)
        if instants:
            return instants[0]
    raise ValueError(
        f"could not resolve daily time {hour:02d}:{minute:02d} in {zone.key}"
    )


def _after_terminal(
    schedule: DiscoverySchedule,
    *,
    attempt: int,
    status: str,
    moment: datetime,
    error: str | None = None,
) -> DiscoverySchedule:
    moment = _utc(moment)
    if status == RUN_FAILED and attempt <= schedule.max_retries:
        return replace(
            schedule,
            next_run_at=_stamp(
                moment + timedelta(minutes=schedule.retry_delay_minutes)
            ),
            enabled=True,
            updated_at=_stamp(moment),
            last_run_at=_stamp(moment),
            last_status=status,
            last_error=(str(error)[:1000] if error else None),
            lease_owner=None,
            lease_until=None,
            active_run_id=None,
            retry_attempt=attempt + 1,
            retry_origin_at=(
                schedule.retry_origin_at or schedule.next_run_at
            ),
            revision=schedule.revision + 1,
        )
    return _advance(schedule, moment, status=status, error=error)


def _advance(
    schedule: DiscoverySchedule,
    after: datetime,
    *,
    status: str | None,
    error: str | None = None,
) -> DiscoverySchedule:
    moment = _utc(after)
    if schedule.recurrence == RECURRENCE_ONCE:
        next_run = schedule.next_run_at
        enabled = False
    elif schedule.recurrence == RECURRENCE_INTERVAL:
        interval = timedelta(minutes=int(schedule.interval_minutes or 1))
        candidate = _parse(
            schedule.retry_origin_at or schedule.next_run_at
        )
        while candidate <= moment:
            candidate += interval
        next_run = _stamp(candidate)
        enabled = schedule.enabled
    else:
        next_run = _stamp(_next_daily(schedule, moment))
        enabled = schedule.enabled
    return replace(
        schedule,
        next_run_at=next_run,
        enabled=enabled,
        updated_at=_stamp(moment),
        last_run_at=_stamp(moment),
        last_status=status,
        last_error=(str(error)[:1000] if error else None),
        lease_owner=None,
        lease_until=None,
        active_run_id=None,
        retry_attempt=1,
        retry_origin_at=None,
        revision=schedule.revision + 1,
    )


class ScheduleWorker:
    """Small adapter between durable schedules and the existing job manager.

    The store owns timing, leases, idempotency and restart recovery.  This
    worker only translates a claimed profile id into a discovery job and
    records its eventual terminal result.  It never resolves credentials.
    """

    def __init__(
        self,
        *,
        store: ScheduleStore,
        job_manager,
        profile_service,
        worker_id: str,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = 15.0,
    ) -> None:
        self.store = store
        self.job_manager = job_manager
        self.profile_service = profile_service
        self.worker_id = str(worker_id)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.poll_seconds = max(1.0, float(poll_seconds))
        self._stop = Event()
        self._thread: Thread | None = None
        # The job/run link is durable.  DiscoveryJobManager restores an
        # interrupted in-process job after restart, so the first tick can
        # reconcile it immediately rather than waiting for a lease timeout.
        self._active: dict[str, set[str]] = {}
        for persisted in self.store.runs(limit=1000):
            if persisted.status == RUN_CLAIMED and persisted.job_id:
                self._active.setdefault(persisted.job_id, set()).add(
                    persisted.run_id
                )
        self.last_tick_at: str | None = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def tick(self) -> int:
        """Reconcile completed jobs, then launch each newly due run once."""

        now = self.clock()
        terminal = {
            "completed": RUN_SUCCEEDED,
            "failed": RUN_FAILED,
            "cancelled": RUN_CANCELLED,
            "interrupted": RUN_FAILED,
        }
        for job_id, run_ids in list(self._active.items()):
            try:
                job = self.job_manager.get(job_id)
            except Exception as error:
                for run_id in run_ids:
                    self.store.complete_run(
                        run_id,
                        status=RUN_FAILED,
                        now=now,
                        error=(
                            "The discovery job backend could not be read: "
                            f"{type(error).__name__}"
                        ),
                    )
                self._active.pop(job_id, None)
                continue
            if job is None:
                for run_id in run_ids:
                    self.store.complete_run(
                        run_id,
                        status=RUN_FAILED,
                        now=now,
                        error="The discovery job record is unavailable.",
                    )
                self._active.pop(job_id, None)
            elif job.status in terminal:
                for run_id in run_ids:
                    self.store.complete_run(
                        run_id,
                        status=terminal[job.status],
                        now=now,
                        error=getattr(job, "error", None),
                    )
                self._active.pop(job_id, None)
            else:
                lost = {
                    run_id for run_id in run_ids
                    if not self.store.renew_lease(
                        run_id,
                        worker_id=self.worker_id,
                        now=now,
                    )
                }
                if lost:
                    run_ids.difference_update(lost)
                if not run_ids:
                    # A recovered/newer worker owns the schedule.  Cooperate
                    # with cancellation when this backend supports it, but do
                    # not let the late result mutate the newer occurrence.
                    cancel = getattr(self.job_manager, "request_cancel", None)
                    if callable(cancel):
                        cancel(job_id)
                    self._active.pop(job_id, None)

        launched = 0
        profiles = {
            profile.profile_id: profile
            for profile in self.profile_service.list_profiles()
        }
        for run in self.store.claim_due(worker_id=self.worker_id, now=now):
            profile = profiles.get(run.profile_id)
            if profile is None:
                self.store.complete_run(
                    run.run_id,
                    status=RUN_FAILED,
                    now=now,
                    error="The scheduled discovery profile is unavailable.",
                )
                continue
            try:
                job, created = self.job_manager.start(profile.name)
            except Exception as error:  # adapter boundary; sanitize persisted text
                self.store.complete_run(
                    run.run_id,
                    status=RUN_FAILED,
                    now=now,
                    error=f"Discovery could not be started: {type(error).__name__}",
                )
                continue
            try:
                self.store.attach_job(
                    run.run_id,
                    worker_id=self.worker_id,
                    job_id=job.job_id,
                    now=now,
                )
            except Exception as error:
                if created:
                    cancel = getattr(self.job_manager, "request_cancel", None)
                    if callable(cancel):
                        cancel(job.job_id)
                self.store.complete_run(
                    run.run_id,
                    status=RUN_FAILED,
                    now=now,
                    error=(
                        "The discovery job could not be attached safely: "
                        f"{type(error).__name__}"
                    ),
                )
                continue
            self._active.setdefault(job.job_id, set()).add(run.run_id)
            launched += 1
        self.last_tick_at = _stamp(now)
        self.last_error = None
        return launched

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()

        def run_loop() -> None:
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as error:  # worker remains alive and observable
                    self.last_error = type(error).__name__
                self._stop.wait(self.poll_seconds)

        self._thread = Thread(
            target=run_loop,
            name="atlas-schedule-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(max(0.0, timeout))
