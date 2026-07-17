"""Durable, auditable operator curation of effective site membership.

Discovery snapshots and inferred assignments remain immutable evidence.  An
active override is a separate operator-intent layer applied to the current
view and future discoveries until explicitly reverted.  Every mutation uses
optimistic revision checking, an atomic replace, and an append-only audit
event so a correction is never a silent rewrite of history.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from founderos_atlas.workspace.exceptions import WorkspaceCorruptedError
from founderos_atlas.workspace.repository import default_workspace_root


SITE_OVERRIDE_SCHEMA_VERSION = "1.0.0"
SITE_OVERRIDES_FILENAME = "site-overrides.json"
SITE_OVERRIDE_AUDIT_FILENAME = "site-overrides.audit.jsonl"


class SiteOverrideConflictError(RuntimeError):
    """The caller edited an older revision of the curation catalog."""


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def device_identity_keys(
    *,
    device_id: str | None = None,
    hostname: str | None = None,
    management_ip: str | None = None,
    serial_number: str | None = None,
    vendor: str | None = None,
) -> tuple[str, ...]:
    """Strong-to-weak durable identity keys for an override subject."""

    values: list[str] = []
    serial = _clean(serial_number)
    vendor_name = (_clean(vendor) or "unknown").casefold()
    if serial:
        values.append(f"serial:{vendor_name}:{serial.casefold()}")
    identity = _clean(device_id)
    if identity:
        values.append(f"device:{identity.casefold()}")
    address = _clean(management_ip)
    if address:
        values.append(f"address:{address.casefold()}")
    name = _clean(hostname)
    if name:
        values.append(f"hostname:{name.casefold()}")
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class SiteOverride:
    subject_key: str
    identity_keys: tuple[str, ...]
    device_id: str | None
    hostname: str | None
    management_ip: str | None
    serial_number: str | None
    vendor: str | None
    site_id: str
    reason: str | None
    created_at: str
    created_by: str
    revision: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_key": self.subject_key,
            "identity_keys": list(self.identity_keys),
            "device_id": self.device_id,
            "hostname": self.hostname,
            "management_ip": self.management_ip,
            "serial_number": self.serial_number,
            "vendor": self.vendor,
            "site_id": self.site_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SiteOverride":
        return cls(
            subject_key=str(value["subject_key"]),
            identity_keys=tuple(str(item) for item in value.get("identity_keys") or ()),
            device_id=_clean(value.get("device_id")),
            hostname=_clean(value.get("hostname")),
            management_ip=_clean(value.get("management_ip")),
            serial_number=_clean(value.get("serial_number")),
            vendor=_clean(value.get("vendor")),
            site_id=str(value["site_id"]),
            reason=_clean(value.get("reason")),
            created_at=str(value["created_at"]),
            created_by=str(value.get("created_by") or "local-operator"),
            revision=int(value["revision"]),
        )


@dataclass(frozen=True)
class SiteOverrideCatalog:
    revision: int = 0
    overrides: tuple[SiteOverride, ...] = ()

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("revision must be non-negative")
        subjects = [item.subject_key for item in self.overrides]
        if len(subjects) != len(set(subjects)):
            raise ValueError("override subjects must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SITE_OVERRIDE_SCHEMA_VERSION,
            "revision": self.revision,
            "overrides": [item.to_dict() for item in self.overrides],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SiteOverrideCatalog":
        return cls(
            revision=int(value.get("revision") or 0),
            overrides=tuple(
                SiteOverride.from_dict(item)
                for item in value.get("overrides") or ()
            ),
        )

    def find(
        self,
        *,
        device_id: str | None = None,
        hostname: str | None = None,
        management_ip: str | None = None,
        serial_number: str | None = None,
        vendor: str | None = None,
    ) -> SiteOverride | None:
        wanted = device_identity_keys(
            device_id=device_id,
            hostname=hostname,
            management_ip=management_ip,
            serial_number=serial_number,
            vendor=vendor,
        )
        # Identity key order is strength order.  The first unique match wins;
        # an ambiguous weak hostname never silently chooses an override.
        for key in wanted:
            matches = [item for item in self.overrides if key in item.identity_keys]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                return None
        return None


@dataclass(frozen=True)
class SiteOverrideEvent:
    event_id: str
    action: str
    subject_key: str
    before_site_id: str | None
    after_site_id: str | None
    actor: str
    reason: str | None
    occurred_at: str
    revision: int
    identity: Mapping[str, Any]
    undoes_event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action": self.action,
            "subject_key": self.subject_key,
            "before_site_id": self.before_site_id,
            "after_site_id": self.after_site_id,
            "actor": self.actor,
            "reason": self.reason,
            "occurred_at": self.occurred_at,
            "revision": self.revision,
            "identity": dict(self.identity),
            "undoes_event_id": self.undoes_event_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SiteOverrideEvent":
        return cls(
            event_id=str(value["event_id"]),
            action=str(value["action"]),
            subject_key=str(value["subject_key"]),
            before_site_id=_clean(value.get("before_site_id")),
            after_site_id=_clean(value.get("after_site_id")),
            actor=str(value.get("actor") or "local-operator"),
            reason=_clean(value.get("reason")),
            occurred_at=str(value["occurred_at"]),
            revision=int(value["revision"]),
            identity=dict(value.get("identity") or {}),
            undoes_event_id=_clean(value.get("undoes_event_id")),
        )


class SiteOverrideRepository:
    _locks: dict[str, RLock] = {}
    _locks_guard = RLock()

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self._root = (
            Path(workspace_root) if workspace_root is not None
            else default_workspace_root()
        )
        resolved = str(self._root.resolve())
        with self._locks_guard:
            self._lock = self._locks.setdefault(resolved, RLock())

    @property
    def path(self) -> Path:
        return self._root / SITE_OVERRIDES_FILENAME

    @property
    def audit_path(self) -> Path:
        return self._root / SITE_OVERRIDE_AUDIT_FILENAME

    def load(self) -> SiteOverrideCatalog:
        if not self.path.is_file():
            return SiteOverrideCatalog()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return SiteOverrideCatalog.from_dict(value)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The site override catalog {self.path} could not be read: {error}"
            ) from error

    def history(self, *, subject_key: str | None = None) -> tuple[SiteOverrideEvent, ...]:
        if not self.audit_path.is_file():
            return ()
        events: list[SiteOverrideEvent] = []
        try:
            for line in self.audit_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = SiteOverrideEvent.from_dict(json.loads(line))
                if subject_key is None or event.subject_key == subject_key:
                    events.append(event)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The site override audit {self.audit_path} could not be read: {error}"
            ) from error
        return tuple(events)

    def assign(
        self,
        *,
        site_id: str,
        device_id: str | None = None,
        hostname: str | None = None,
        management_ip: str | None = None,
        serial_number: str | None = None,
        vendor: str | None = None,
        reason: str | None = None,
        actor: str = "local-operator",
        expected_revision: int | None = None,
        occurred_at: str | None = None,
    ) -> tuple[SiteOverrideCatalog, SiteOverrideEvent]:
        if not _clean(site_id):
            raise ValueError("site_id is required")
        keys = device_identity_keys(
            device_id=device_id, hostname=hostname,
            management_ip=management_ip, serial_number=serial_number,
            vendor=vendor,
        )
        if not keys:
            raise ValueError("a device identity is required")
        with self._lock:
            current = self.load()
            self._check_revision(current, expected_revision)
            existing = current.find(
                device_id=device_id, hostname=hostname,
                management_ip=management_ip, serial_number=serial_number,
                vendor=vendor,
            )
            subject_key = existing.subject_key if existing else keys[0]
            revision = current.revision + 1
            stamp = occurred_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
            override = SiteOverride(
                subject_key=subject_key,
                identity_keys=tuple(
                    dict.fromkeys((*keys, *(existing.identity_keys if existing else ())))
                ),
                device_id=_clean(device_id), hostname=_clean(hostname),
                management_ip=_clean(management_ip),
                serial_number=_clean(serial_number), vendor=_clean(vendor),
                site_id=str(site_id).strip(), reason=_clean(reason),
                created_at=stamp, created_by=actor, revision=revision,
            )
            remaining = [item for item in current.overrides if item.subject_key != subject_key]
            catalog = SiteOverrideCatalog(
                revision=revision,
                overrides=tuple(sorted((*remaining, override), key=lambda item: item.subject_key)),
            )
            event = self._event(
                action="assign", override=override,
                before_site_id=existing.site_id if existing else None,
                after_site_id=override.site_id, actor=actor, reason=reason,
                occurred_at=stamp, revision=revision,
            )
            self._commit(catalog, event)
            return catalog, event

    def revert(
        self,
        *,
        device_id: str | None = None,
        hostname: str | None = None,
        management_ip: str | None = None,
        serial_number: str | None = None,
        vendor: str | None = None,
        reason: str | None = None,
        actor: str = "local-operator",
        expected_revision: int | None = None,
        occurred_at: str | None = None,
    ) -> tuple[SiteOverrideCatalog, SiteOverrideEvent]:
        with self._lock:
            current = self.load()
            self._check_revision(current, expected_revision)
            existing = current.find(
                device_id=device_id, hostname=hostname,
                management_ip=management_ip, serial_number=serial_number,
                vendor=vendor,
            )
            if existing is None:
                raise ValueError("no active site override matches this device")
            revision = current.revision + 1
            stamp = occurred_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
            catalog = SiteOverrideCatalog(
                revision=revision,
                overrides=tuple(
                    item for item in current.overrides
                    if item.subject_key != existing.subject_key
                ),
            )
            event = self._event(
                action="revert", override=existing,
                before_site_id=existing.site_id, after_site_id=None,
                actor=actor, reason=reason, occurred_at=stamp,
                revision=revision,
            )
            self._commit(catalog, event)
            return catalog, event

    def undo(
        self,
        *,
        subject_key: str,
        actor: str = "local-operator",
        expected_revision: int | None = None,
        occurred_at: str | None = None,
    ) -> tuple[SiteOverrideCatalog, SiteOverrideEvent]:
        with self._lock:
            current = self.load()
            self._check_revision(current, expected_revision)
            history = self.history(subject_key=subject_key)
            if not history:
                raise ValueError("no site assignment history exists for this device")
            previous_event = history[-1]
            current_override = next(
                (item for item in current.overrides if item.subject_key == subject_key),
                None,
            )
            target_site = previous_event.before_site_id
            revision = current.revision + 1
            stamp = occurred_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
            remaining = [item for item in current.overrides if item.subject_key != subject_key]
            identity = dict(previous_event.identity)
            if target_site:
                keys = tuple(identity.get("identity_keys") or ())
                restored = SiteOverride(
                    subject_key=subject_key,
                    identity_keys=keys or (subject_key,),
                    device_id=_clean(identity.get("device_id")),
                    hostname=_clean(identity.get("hostname")),
                    management_ip=_clean(identity.get("management_ip")),
                    serial_number=_clean(identity.get("serial_number")),
                    vendor=_clean(identity.get("vendor")),
                    site_id=target_site,
                    reason=f"Undo {previous_event.event_id}",
                    created_at=stamp, created_by=actor, revision=revision,
                )
                remaining.append(restored)
                basis = restored
            else:
                basis = current_override or SiteOverride(
                    subject_key=subject_key,
                    identity_keys=tuple(identity.get("identity_keys") or (subject_key,)),
                    device_id=_clean(identity.get("device_id")),
                    hostname=_clean(identity.get("hostname")),
                    management_ip=_clean(identity.get("management_ip")),
                    serial_number=_clean(identity.get("serial_number")),
                    vendor=_clean(identity.get("vendor")),
                    site_id=previous_event.after_site_id or "unknown",
                    reason=None, created_at=stamp, created_by=actor,
                    revision=revision,
                )
            catalog = SiteOverrideCatalog(
                revision=revision,
                overrides=tuple(sorted(remaining, key=lambda item: item.subject_key)),
            )
            event = self._event(
                action="undo", override=basis,
                before_site_id=current_override.site_id if current_override else None,
                after_site_id=target_site, actor=actor,
                reason=f"Undo {previous_event.event_id}", occurred_at=stamp,
                revision=revision, undoes_event_id=previous_event.event_id,
            )
            self._commit(catalog, event)
            return catalog, event

    @staticmethod
    def _check_revision(
        current: SiteOverrideCatalog, expected_revision: int | None
    ) -> None:
        if expected_revision is not None and expected_revision != current.revision:
            raise SiteOverrideConflictError(
                f"site assignments changed from revision {expected_revision} "
                f"to {current.revision}; reload before saving"
            )

    @staticmethod
    def _event(
        *, action: str, override: SiteOverride,
        before_site_id: str | None, after_site_id: str | None,
        actor: str, reason: str | None, occurred_at: str, revision: int,
        undoes_event_id: str | None = None,
    ) -> SiteOverrideEvent:
        return SiteOverrideEvent(
            event_id=f"site-event:{uuid4().hex}", action=action,
            subject_key=override.subject_key,
            before_site_id=before_site_id, after_site_id=after_site_id,
            actor=actor, reason=_clean(reason), occurred_at=occurred_at,
            revision=revision,
            identity={
                "identity_keys": list(override.identity_keys),
                "device_id": override.device_id,
                "hostname": override.hostname,
                "management_ip": override.management_ip,
                "serial_number": override.serial_number,
                "vendor": override.vendor,
            },
            undoes_event_id=undoes_event_id,
        )

    def _commit(
        self, catalog: SiteOverrideCatalog, event: SiteOverrideEvent
    ) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid4().hex}.writing"
        )
        audit_temporary = self.audit_path.with_name(
            f".{self.audit_path.name}.{uuid4().hex}.writing"
        )
        try:
            temporary.write_text(
                json.dumps(catalog.to_dict(), indent=2, sort_keys=True,
                           ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            existing_audit = (
                self.audit_path.read_text(encoding="utf-8")
                if self.audit_path.is_file() else ""
            )
            audit_temporary.write_text(
                existing_audit
                + json.dumps(event.to_dict(), sort_keys=True, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            # The catalog is the effective state.  Replace it first; if the
            # audit replace fails the next write still preserves the catalog,
            # and callers receive the I/O failure rather than false success.
            temporary.replace(self.path)
            audit_temporary.replace(self.audit_path)
        finally:
            temporary.unlink(missing_ok=True)
            audit_temporary.unlink(missing_ok=True)
