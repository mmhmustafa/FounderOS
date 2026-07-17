"""Durable, auditable operator resolution of unresolved peer identities.

Discovery snapshots remain immutable evidence. A resolution is a separate
operator-intent layer: "this observed peer IS that discovered device",
applied to the current view and future discoveries until reverted. It
mirrors the site-override contract exactly — optimistic revision
checking, atomic replace, append-only audit — because a mistaken merge
must be as reversible and as explainable as a mistaken site.

Atlas itself NEVER auto-merges an ambiguous peer: the deterministic
candidate generator (see ``resolution_candidates``) only *suggests*,
with the evidence for each suggestion; the operator decides.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
import json
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from founderos_atlas.workspace.exceptions import WorkspaceCorruptedError
from founderos_atlas.workspace.repository import default_workspace_root


IDENTITY_RESOLUTION_SCHEMA_VERSION = "1.0.0"
IDENTITY_RESOLUTIONS_FILENAME = "identity-resolutions.json"
IDENTITY_RESOLUTION_AUDIT_FILENAME = "identity-resolutions.audit.jsonl"


class PeerResolutionConflictError(RuntimeError):
    """The caller edited an older revision of the resolution catalog."""


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def peer_subject_key(peer_label: str) -> str:
    """The durable subject key for an observed peer (its announced label)."""

    cleaned = _clean(peer_label)
    if cleaned is None:
        raise ValueError("a peer label is required")
    return f"peer:{cleaned.casefold()}"


@dataclass(frozen=True)
class PeerIdentityResolution:
    """One operator decision: observed peer -> discovered device."""

    subject_key: str
    peer_label: str
    resolved_hostname: str
    resolved_device_id: str | None
    reason: str | None
    created_at: str
    created_by: str
    revision: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_key": self.subject_key,
            "peer_label": self.peer_label,
            "resolved_hostname": self.resolved_hostname,
            "resolved_device_id": self.resolved_device_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PeerIdentityResolution":
        return cls(
            subject_key=str(value["subject_key"]),
            peer_label=str(value["peer_label"]),
            resolved_hostname=str(value["resolved_hostname"]),
            resolved_device_id=_clean(value.get("resolved_device_id")),
            reason=_clean(value.get("reason")),
            created_at=str(value["created_at"]),
            created_by=str(value.get("created_by") or "local-operator"),
            revision=int(value["revision"]),
        )


@dataclass(frozen=True)
class PeerResolutionCatalog:
    revision: int = 0
    resolutions: tuple[PeerIdentityResolution, ...] = ()

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("revision must be non-negative")
        subjects = [item.subject_key for item in self.resolutions]
        if len(subjects) != len(set(subjects)):
            raise ValueError("resolution subjects must be unique")

    def find(self, peer_label: str) -> PeerIdentityResolution | None:
        try:
            key = peer_subject_key(peer_label)
        except ValueError:
            return None
        for item in self.resolutions:
            if item.subject_key == key:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": IDENTITY_RESOLUTION_SCHEMA_VERSION,
            "revision": self.revision,
            "resolutions": [item.to_dict() for item in self.resolutions],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PeerResolutionCatalog":
        return cls(
            revision=int(value.get("revision") or 0),
            resolutions=tuple(
                PeerIdentityResolution.from_dict(item)
                for item in value.get("resolutions") or ()
            ),
        )


@dataclass(frozen=True)
class PeerResolutionEvent:
    event_id: str
    action: str                       # resolve | revert | undo
    subject_key: str
    peer_label: str
    before_hostname: str | None
    after_hostname: str | None
    actor: str
    reason: str | None
    occurred_at: str
    revision: int
    undoes_event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action": self.action,
            "subject_key": self.subject_key,
            "peer_label": self.peer_label,
            "before_hostname": self.before_hostname,
            "after_hostname": self.after_hostname,
            "actor": self.actor,
            "reason": self.reason,
            "occurred_at": self.occurred_at,
            "revision": self.revision,
            "undoes_event_id": self.undoes_event_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PeerResolutionEvent":
        return cls(
            event_id=str(value["event_id"]),
            action=str(value["action"]),
            subject_key=str(value["subject_key"]),
            peer_label=str(value["peer_label"]),
            before_hostname=_clean(value.get("before_hostname")),
            after_hostname=_clean(value.get("after_hostname")),
            actor=str(value.get("actor") or "local-operator"),
            reason=_clean(value.get("reason")),
            occurred_at=str(value["occurred_at"]),
            revision=int(value["revision"]),
            undoes_event_id=_clean(value.get("undoes_event_id")),
        )


class PeerResolutionRepository:
    """Same storage contract as SiteOverrideRepository, same guarantees."""

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
        return self._root / IDENTITY_RESOLUTIONS_FILENAME

    @property
    def audit_path(self) -> Path:
        return self._root / IDENTITY_RESOLUTION_AUDIT_FILENAME

    def load(self) -> PeerResolutionCatalog:
        if not self.path.is_file():
            return PeerResolutionCatalog()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return PeerResolutionCatalog.from_dict(value)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The identity resolution catalog {self.path} could not be "
                f"read: {error}"
            ) from error

    def history(
        self, *, subject_key: str | None = None
    ) -> tuple[PeerResolutionEvent, ...]:
        if not self.audit_path.is_file():
            return ()
        events: list[PeerResolutionEvent] = []
        try:
            for line in self.audit_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = PeerResolutionEvent.from_dict(json.loads(line))
                if subject_key is None or event.subject_key == subject_key:
                    events.append(event)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The identity resolution audit {self.audit_path} could not "
                f"be read: {error}"
            ) from error
        return tuple(events)

    def resolve(
        self,
        *,
        peer_label: str,
        resolved_hostname: str,
        resolved_device_id: str | None = None,
        reason: str | None = None,
        actor: str = "local-operator",
        expected_revision: int | None = None,
        occurred_at: str | None = None,
    ) -> tuple[PeerResolutionCatalog, PeerResolutionEvent]:
        if not _clean(resolved_hostname):
            raise ValueError("resolved_hostname is required")
        subject_key = peer_subject_key(peer_label)
        with self._lock:
            current = self.load()
            self._check_revision(current, expected_revision)
            existing = current.find(peer_label)
            revision = current.revision + 1
            stamp = occurred_at or datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            resolution = PeerIdentityResolution(
                subject_key=subject_key,
                peer_label=str(peer_label).strip(),
                resolved_hostname=str(resolved_hostname).strip(),
                resolved_device_id=_clean(resolved_device_id),
                reason=_clean(reason),
                created_at=stamp, created_by=actor, revision=revision,
            )
            remaining = [
                item for item in current.resolutions
                if item.subject_key != subject_key
            ]
            catalog = PeerResolutionCatalog(
                revision=revision,
                resolutions=tuple(
                    sorted((*remaining, resolution),
                           key=lambda item: item.subject_key)
                ),
            )
            event = PeerResolutionEvent(
                event_id=f"identity-event:{uuid4().hex}", action="resolve",
                subject_key=subject_key,
                peer_label=resolution.peer_label,
                before_hostname=existing.resolved_hostname if existing else None,
                after_hostname=resolution.resolved_hostname,
                actor=actor, reason=_clean(reason), occurred_at=stamp,
                revision=revision,
            )
            self._commit(catalog, event)
            return catalog, event

    def revert(
        self,
        *,
        peer_label: str,
        reason: str | None = None,
        actor: str = "local-operator",
        expected_revision: int | None = None,
        occurred_at: str | None = None,
    ) -> tuple[PeerResolutionCatalog, PeerResolutionEvent]:
        subject_key = peer_subject_key(peer_label)
        with self._lock:
            current = self.load()
            self._check_revision(current, expected_revision)
            existing = current.find(peer_label)
            if existing is None:
                raise ValueError("no identity resolution matches this peer")
            revision = current.revision + 1
            stamp = occurred_at or datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            catalog = PeerResolutionCatalog(
                revision=revision,
                resolutions=tuple(
                    item for item in current.resolutions
                    if item.subject_key != subject_key
                ),
            )
            event = PeerResolutionEvent(
                event_id=f"identity-event:{uuid4().hex}", action="revert",
                subject_key=subject_key, peer_label=existing.peer_label,
                before_hostname=existing.resolved_hostname,
                after_hostname=None,
                actor=actor, reason=_clean(reason), occurred_at=stamp,
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
    ) -> tuple[PeerResolutionCatalog, PeerResolutionEvent]:
        with self._lock:
            current = self.load()
            self._check_revision(current, expected_revision)
            history = self.history(subject_key=subject_key)
            if not history:
                raise ValueError("no resolution history exists for this peer")
            previous = history[-1]
            existing = next(
                (item for item in current.resolutions
                 if item.subject_key == subject_key),
                None,
            )
            revision = current.revision + 1
            stamp = occurred_at or datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            remaining = [
                item for item in current.resolutions
                if item.subject_key != subject_key
            ]
            target = previous.before_hostname
            if target:
                remaining.append(PeerIdentityResolution(
                    subject_key=subject_key,
                    peer_label=previous.peer_label,
                    resolved_hostname=target,
                    resolved_device_id=None,
                    reason=f"Undo {previous.event_id}",
                    created_at=stamp, created_by=actor, revision=revision,
                ))
            catalog = PeerResolutionCatalog(
                revision=revision,
                resolutions=tuple(
                    sorted(remaining, key=lambda item: item.subject_key)
                ),
            )
            event = PeerResolutionEvent(
                event_id=f"identity-event:{uuid4().hex}", action="undo",
                subject_key=subject_key, peer_label=previous.peer_label,
                before_hostname=(
                    existing.resolved_hostname if existing else None
                ),
                after_hostname=target,
                actor=actor, reason=f"Undo {previous.event_id}",
                occurred_at=stamp, revision=revision,
                undoes_event_id=previous.event_id,
            )
            self._commit(catalog, event)
            return catalog, event

    @staticmethod
    def _check_revision(
        current: PeerResolutionCatalog, expected_revision: int | None
    ) -> None:
        if expected_revision is not None and expected_revision != current.revision:
            raise PeerResolutionConflictError(
                f"identity resolutions changed from revision "
                f"{expected_revision} to {current.revision}; reload before "
                "saving"
            )

    def _commit(
        self, catalog: PeerResolutionCatalog, event: PeerResolutionEvent
    ) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.writing")
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
            temporary.replace(self.path)
            audit_temporary.replace(self.audit_path)
        finally:
            temporary.unlink(missing_ok=True)
            audit_temporary.unlink(missing_ok=True)


def resolution_candidates(
    peer: Mapping[str, Any],
    devices: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Deterministic, evidence-cited candidates for one unresolved peer.

    ``peer`` is the observed node data (label/hostname, management_ip,
    router_id, observed_via). ``devices`` are discovered device dicts
    (hostname, management_ip, interfaces with ip_address, metadata with
    identity aliases / router ids). Signals, strongest first:

    1. router-id ownership — the peer's router ID is an address a device
       owns on any interface or as its management address;
    2. address ownership — the announced address is owned by a device;
    3. hostname equality — the announced name equals a device hostname
       or alias (bare name vs FQDN label allowed);
    4. shared point-to-point subnet — the announced address sits in a
       /30 or /31 with exactly one device interface.

    Every candidate carries its signal and detail. Multiple candidates
    are returned in signal order — the operator, never Atlas, chooses.
    """

    from .canonical import normalize_hostname, short_hostname, is_bare_hostname

    label = str(peer.get("hostname") or peer.get("label") or "").strip()
    peer_addresses = [
        value for value in (
            str(peer.get("router_id") or "").strip(),
            str(peer.get("management_ip") or "").strip(),
            label,
        )
        if value and value.casefold() not in ("unknown",)
        and _is_ip(value)
    ]
    candidates: list[dict[str, Any]] = []

    def add(device: Mapping[str, Any], signal: str, detail: str, rank: int) -> None:
        hostname = str(device.get("hostname") or "")
        if any(c["hostname"] == hostname for c in candidates):
            return
        candidates.append({
            "hostname": hostname,
            "device_id": str(device.get("device_id") or "") or None,
            "signal": signal,
            "detail": detail,
            "rank": rank,
        })

    for device in devices:
        owned = _device_addresses(device)
        for address in peer_addresses:
            if address in owned:
                add(
                    device, "address-ownership",
                    f"{address} is owned by {device.get('hostname')} "
                    f"({owned[address]})",
                    1,
                )
    if label and not _is_ip(label):
        wanted = normalize_hostname(label)
        for device in devices:
            names = [str(device.get("hostname") or "")]
            metadata = device.get("metadata") or {}
            identity = metadata.get("identity") or {}
            names.extend(str(alias) for alias in identity.get("aliases") or ())
            for name in names:
                normalized = normalize_hostname(name)
                if not normalized:
                    continue
                if normalized == wanted or (
                    is_bare_hostname(label) and short_hostname(name) == wanted
                ) or (
                    is_bare_hostname(name) and short_hostname(label) == normalized
                ):
                    add(
                        device, "hostname",
                        f"announced name {label!r} matches {name!r}",
                        2,
                    )
                    break
    for device in devices:
        for interface in device.get("interfaces") or ():
            raw = str((interface or {}).get("ip_address") or "").strip()
            address, _, prefix = raw.partition("/")
            if not prefix or prefix not in ("30", "31"):
                continue
            try:
                network = ip_network(raw, strict=False)
            except ValueError:
                continue
            for peer_address in peer_addresses:
                try:
                    if ip_address(peer_address) in network:
                        add(
                            device, "p2p-subnet",
                            f"{peer_address} shares point-to-point "
                            f"{network} with {device.get('hostname')} "
                            f"{interface.get('name')}",
                            3,
                        )
                except ValueError:
                    continue
    return sorted(candidates, key=lambda item: (item["rank"], item["hostname"]))


def _is_ip(value: str) -> bool:
    try:
        ip_address(value)
    except ValueError:
        return False
    return True


def _device_addresses(device: Mapping[str, Any]) -> dict[str, str]:
    """address -> "where it lives" for one discovered device."""

    owned: dict[str, str] = {}
    management = str(device.get("management_ip") or "").strip()
    if management:
        owned[management] = "management address"
    for interface in device.get("interfaces") or ():
        raw = str((interface or {}).get("ip_address") or "").strip()
        address = raw.partition("/")[0]
        if address and _is_ip(address):
            owned.setdefault(address, f"interface {interface.get('name')}")
    metadata = device.get("metadata") or {}
    routing = metadata.get("routing_evidence") or {}
    for session in routing.get("bgp_sessions") or ():
        router_id = str((session or {}).get("router_id") or "").strip()
        if router_id and _is_ip(router_id):
            owned.setdefault(router_id, "BGP router ID")
    return owned
