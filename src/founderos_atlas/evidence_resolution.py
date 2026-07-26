"""Evidence coverage and operator-guided resolution work.

This module deliberately separates three kinds of truth:

* immutable observations collected from devices;
* deterministic proposals derived from those observations; and
* durable operator decisions about a proposal or collection gap.

It never edits a discovery snapshot.  Confirmed peer identities continue to
use :mod:`founderos_atlas.identity.resolutions`, the canonical curation layer.
The small repository below only remembers queue dispositions (reject/defer)
so an operator can manage a large evidence-improvement queue without hiding
the underlying evidence or losing an audit trail.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from founderos_atlas.workspace.exceptions import WorkspaceCorruptedError
from founderos_atlas.workspace.repository import default_workspace_root


DECISION_SCHEMA_VERSION = "1.0.0"
DECISION_FILENAME = "evidence-resolution-decisions.json"
DECISION_AUDIT_FILENAME = "evidence-resolution-decisions.audit.jsonl"
DECISION_STATUSES = frozenset({"rejected", "deferred"})


class ResolutionDecisionConflictError(RuntimeError):
    """The submitted form was based on an older decision catalog."""


def queue_item_key(kind: str, *parts: object) -> str:
    """Return a stable, non-sensitive identifier for one grouped queue item."""

    material = "\0".join(
        [str(kind).strip().casefold()]
        + [str(part or "").strip().casefold() for part in parts]
    )
    return f"{str(kind).strip().casefold()}:{sha256(material.encode()).hexdigest()[:24]}"


@dataclass(frozen=True)
class ResolutionDecision:
    item_key: str
    status: str
    reason: str | None
    actor: str
    updated_at: str
    revision: int

    def __post_init__(self) -> None:
        if self.status not in DECISION_STATUSES:
            raise ValueError("decision status must be rejected or deferred")

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_key": self.item_key,
            "status": self.status,
            "reason": self.reason,
            "actor": self.actor,
            "updated_at": self.updated_at,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResolutionDecision":
        return cls(
            item_key=str(value["item_key"]),
            status=str(value["status"]),
            reason=(str(value["reason"]) if value.get("reason") else None),
            actor=str(value.get("actor") or "local-operator"),
            updated_at=str(value["updated_at"]),
            revision=int(value["revision"]),
        )


@dataclass(frozen=True)
class ResolutionDecisionCatalog:
    revision: int = 0
    decisions: tuple[ResolutionDecision, ...] = ()

    def find(self, item_key: str) -> ResolutionDecision | None:
        return next(
            (item for item in self.decisions if item.item_key == item_key), None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DECISION_SCHEMA_VERSION,
            "revision": self.revision,
            "decisions": [item.to_dict() for item in self.decisions],
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "ResolutionDecisionCatalog":
        decisions = tuple(
            ResolutionDecision.from_dict(item)
            for item in value.get("decisions") or ()
        )
        if len({item.item_key for item in decisions}) != len(decisions):
            raise ValueError("resolution decision subjects must be unique")
        return cls(
            revision=int(value.get("revision") or 0),
            decisions=decisions,
        )


class ResolutionDecisionRepository:
    """Atomic current state plus append-only decision history."""

    _locks: dict[str, RLock] = {}
    _locks_guard = RLock()

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.root = (
            Path(workspace_root)
            if workspace_root is not None
            else default_workspace_root()
        )
        resolved = str(self.root.resolve())
        with self._locks_guard:
            self._lock = self._locks.setdefault(resolved, RLock())

    @property
    def path(self) -> Path:
        return self.root / DECISION_FILENAME

    @property
    def audit_path(self) -> Path:
        return self.root / DECISION_AUDIT_FILENAME

    def load(self) -> ResolutionDecisionCatalog:
        if not self.path.is_file():
            return ResolutionDecisionCatalog()
        try:
            return ResolutionDecisionCatalog.from_dict(
                json.loads(self.path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The evidence resolution catalog {self.path} could not be read: "
                f"{error}"
            ) from error

    def history(self, item_key: str | None = None) -> tuple[dict[str, Any], ...]:
        if not self.audit_path.is_file():
            return ()
        try:
            rows = tuple(
                json.loads(line)
                for line in self.audit_path.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The evidence resolution audit {self.audit_path} could not be "
                f"read: {error}"
            ) from error
        return tuple(
            row for row in rows
            if item_key is None or row.get("item_key") == item_key
        )

    def decide(
        self,
        *,
        item_key: str,
        status: str,
        reason: str | None,
        actor: str,
        expected_revision: int | None,
        occurred_at: str | None = None,
    ) -> tuple[ResolutionDecisionCatalog, dict[str, Any]]:
        if status not in DECISION_STATUSES:
            raise ValueError("status must be rejected or deferred")
        key = str(item_key or "").strip()
        if not key:
            raise ValueError("item_key is required")
        clean_reason = (str(reason).strip() or None) if reason else None
        if clean_reason is not None and len(clean_reason) > 500:
            raise ValueError("reason must be 500 characters or fewer")
        with self._lock:
            current = self.load()
            self._check_revision(current, expected_revision)
            before = current.find(key)
            revision = current.revision + 1
            stamp = occurred_at or datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            decision = ResolutionDecision(
                item_key=key,
                status=status,
                reason=clean_reason,
                actor=actor,
                updated_at=stamp,
                revision=revision,
            )
            remaining = [
                item for item in current.decisions if item.item_key != key
            ]
            catalog = ResolutionDecisionCatalog(
                revision=revision,
                decisions=tuple(
                    sorted((*remaining, decision), key=lambda item: item.item_key)
                ),
            )
            event = {
                "event_id": f"evidence-resolution-event:{uuid4().hex}",
                "action": status,
                "item_key": key,
                "before": before.to_dict() if before else None,
                "after": decision.to_dict(),
                "actor": actor,
                "reason": decision.reason,
                "occurred_at": stamp,
                "revision": revision,
            }
            self._commit(catalog, event)
            return catalog, event

    def undo(
        self,
        *,
        item_key: str,
        actor: str,
        expected_revision: int | None,
        occurred_at: str | None = None,
    ) -> tuple[ResolutionDecisionCatalog, dict[str, Any]]:
        key = str(item_key or "").strip()
        with self._lock:
            current = self.load()
            self._check_revision(current, expected_revision)
            existing = current.find(key)
            if existing is None:
                raise ValueError("no queue decision exists for this item")
            revision = current.revision + 1
            stamp = occurred_at or datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            catalog = ResolutionDecisionCatalog(
                revision=revision,
                decisions=tuple(
                    item for item in current.decisions if item.item_key != key
                ),
            )
            event = {
                "event_id": f"evidence-resolution-event:{uuid4().hex}",
                "action": "undo",
                "item_key": key,
                "before": existing.to_dict(),
                "after": None,
                "actor": actor,
                "reason": None,
                "occurred_at": stamp,
                "revision": revision,
            }
            self._commit(catalog, event)
            return catalog, event

    @staticmethod
    def _check_revision(
        current: ResolutionDecisionCatalog, expected_revision: int | None
    ) -> None:
        if (
            expected_revision is not None
            and expected_revision != current.revision
        ):
            raise ResolutionDecisionConflictError(
                "The resolution queue changed while this page was open; "
                "reload before saving."
            )

    def _commit(
        self, catalog: ResolutionDecisionCatalog, event: Mapping[str, Any]
    ) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        state_tmp = self.path.with_name(
            f".{self.path.name}.{uuid4().hex}.writing"
        )
        audit_tmp = self.audit_path.with_name(
            f".{self.audit_path.name}.{uuid4().hex}.writing"
        )
        try:
            state_tmp.write_text(
                json.dumps(
                    catalog.to_dict(), indent=2, sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            existing = (
                self.audit_path.read_text(encoding="utf-8")
                if self.audit_path.is_file()
                else ""
            )
            audit_tmp.write_text(
                existing
                + json.dumps(dict(event), sort_keys=True, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            state_tmp.replace(self.path)
            audit_tmp.replace(self.audit_path)
        finally:
            state_tmp.unlink(missing_ok=True)
            audit_tmp.unlink(missing_ok=True)


def _percentage(observed: int | None, total: int | None) -> int | None:
    if observed is None or total is None or total <= 0:
        return None
    return round(100 * max(0, min(observed, total)) / total)


def _dimension(
    key: str,
    label: str,
    observed: int | None,
    total: int | None,
    explanation: str,
    *,
    href: str | None = None,
) -> dict[str, Any]:
    percent = _percentage(observed, total)
    if percent is None:
        status = "unknown"
    elif percent == 100:
        status = "complete"
    elif percent >= 80:
        status = "partial"
    else:
        status = "gap"
    return {
        "key": key,
        "label": label,
        "observed": observed,
        "total": total,
        "percent": percent,
        "status": status,
        "explanation": explanation,
        "href": href,
    }


def coverage_dimensions(
    session: Mapping[str, Any] | None,
    records: Iterable[Mapping[str, Any]],
    snapshots: Iterable[Mapping[str, Any]],
    topology_facts: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    """Return separate, honest coverage dimensions for one evidence scope."""

    session = dict(session or {})
    rows = [dict(row) for row in records]
    snaps = [dict(row) for row in snapshots]
    attempted = len(rows)
    captured = sum(
        1 for row in rows
        if row.get("collection_status") in {"collected", "empty"}
    )
    transported = sum(1 for row in rows if row.get("transport"))
    parsed = sum(
        1 for row in rows
        if row.get("content_sha256") and row.get("parser_version")
    )
    devices = {
        str(row.get("device_id"))
        for row in rows
        if row.get("device_id")
    }
    config_devices = {
        str(row.get("device_id"))
        for row in snaps
        if row.get("device_id") and row.get("config_sha256")
    }
    reached = int(session.get("device_count") or 0)
    authenticated = int(session.get("authenticated_count") or 0)
    topology_facts = dict(topology_facts or {})
    counts = topology_facts.get("counts")
    if hasattr(counts, "to_dict"):
        counts = counts.to_dict()
    counts = dict(counts or {})
    unresolved = int(counts.get("unresolved_peer_identities") or 0)
    canonical = max(reached, len(devices))
    relationships = int(counts.get("relationships") or 0)
    verified = (
        int(counts.get("physical_links") or 0)
        + int(counts.get("verified_routed_links") or 0)
        + int(counts.get("routing_adjacencies") or 0)
        + int(counts.get("bgp_peerings") or 0)
    )
    verified = min(relationships, verified)
    routing = dict(topology_facts.get("routing_view") or {})
    ospf = dict(routing.get("ospf") or {})
    bgp = dict(routing.get("bgp") or {})

    return (
        _dimension(
            "candidate-reachability", "Candidate reachability", reached, None,
            "Discovery remembers reached devices, but this evidence record "
            "does not preserve the complete candidate-address denominator.",
            href="/discovery",
        ),
        _dimension(
            "transport", "Transport provenance", transported, attempted,
            "Evidence records naming the transport that collected them.",
            href="/evidence",
        ),
        _dimension(
            "authentication", "Authentication", authenticated, reached,
            "Reached devices for which discovery authenticated successfully.",
            href="/discovery",
        ),
        _dimension(
            "configuration", "Configuration", len(config_devices),
            max(authenticated, len(devices)),
            "Authenticated devices with a captured configuration snapshot.",
            href="/configuration",
        ),
        _dimension(
            "commands", "Command execution", captured, attempted,
            "Attempted commands that completed with output or an honest empty "
            "response. Unsupported and failed commands remain gaps.",
            href="/evidence",
        ),
        _dimension(
            "parser", "Parser provenance", parsed,
            sum(1 for row in rows if row.get("content_sha256")),
            "Captured outputs that name the parser version available for "
            "deterministic reprocessing.",
            href="/evidence",
        ),
        _dimension(
            "normalized-facts", "Normalized facts", None, None,
            "Record-level normalized-fact coverage is not yet preserved for "
            "every command. Atlas will not infer a percentage from blob count.",
            href="/evidence",
        ),
        _dimension(
            "identity", "Identity resolution", canonical,
            canonical + unresolved,
            "Canonical devices compared with observed peer identities still "
            "awaiting corroboration.",
            href="/evidence/resolution-center?kind=identity",
        ),
        _dimension(
            "relationships", "Topology relationships", verified, relationships,
            "Relationships supported by physical, routed, OSPF or BGP evidence.",
            href="/topology",
        ),
        _dimension(
            "ospf", "OSPF operational coverage",
            int(ospf.get("covered_devices") or 0),
            int(ospf.get("total_devices") or 0),
            "Devices with observed or configured OSPF membership. A device "
            "not running OSPF may correctly remain outside this denominator.",
            href="/topology?view=ospf",
        ),
        _dimension(
            "bgp", "BGP operational coverage",
            int(bgp.get("covered_devices") or 0),
            int(bgp.get("total_devices") or 0),
            "Devices with observed or configured BGP membership. A device "
            "not running BGP may correctly remain outside this denominator.",
            href="/topology?view=bgp",
        ),
    )


def _proposal(candidate: Mapping[str, Any], candidate_count: int) -> dict[str, Any]:
    rank = int(candidate.get("rank") or 99)
    confidence = "high" if rank == 1 else "medium" if rank == 2 else "low"
    return {
        **dict(candidate),
        "confidence": confidence,
        "auto_eligible": rank == 1 and candidate_count == 1,
    }


def build_resolution_queue(
    *,
    unresolved: Iterable[Mapping[str, Any]],
    records: Iterable[Mapping[str, Any]],
    snapshots: Iterable[Mapping[str, Any]],
    decisions: ResolutionDecisionCatalog | None = None,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(hours=24),
) -> tuple[dict[str, Any], ...]:
    """Build a grouped, deterministic queue without reading evidence blobs."""

    catalog = decisions or ResolutionDecisionCatalog()
    items: list[dict[str, Any]] = []
    for raw in unresolved:
        peer = str(raw.get("peer") or "").strip()
        if not peer:
            continue
        candidates = [
            _proposal(candidate, len(raw.get("candidates") or ()))
            for candidate in raw.get("candidates") or ()
        ]
        key = queue_item_key("identity", peer)
        decision = catalog.find(key)
        conflicts = (
            [str(item.get("hostname")) for item in candidates]
            if len(candidates) > 1 else []
        )
        items.append({
            "item_key": key,
            "kind": "identity",
            "kind_label": "Unresolved identity",
            "title": peer,
            "detail": str(raw.get("why_unresolved") or ""),
            "status": decision.status if decision else "open",
            "decision": decision.to_dict() if decision else None,
            "occurrences": int(raw.get("occurrences") or 1),
            "devices": (),
            "proposals": candidates,
            "conflicts": conflicts,
            "impact": {
                "boundaries_resolved": 1,
                "devices_merged": 0,
                "relationships_recomputed": int(raw.get("occurrences") or 1),
                "note": (
                    "Confirmation re-renders canonical topology and may change "
                    "site links, paths and policy context. Discovery evidence "
                    "remains immutable."
                ),
            },
            "href": f"/topology#identity",
            "peer_label": peer,
        })

    rows = [dict(row) for row in records]
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    status_kind = {
        "error": ("collection-failure", "Collection failure"),
        "unavailable": ("unsupported-command", "Unsupported command"),
        "empty": ("empty-response", "Empty response"),
    }
    for row in rows:
        status = str(row.get("collection_status") or "")
        if status not in status_kind:
            continue
        kind, label = status_kind[status]
        group = (
            kind,
            str(row.get("platform") or "Unknown platform"),
            str(row.get("command") or "Unknown command"),
            str(row.get("detail") or ""),
        )
        grouped.setdefault(group, []).append(row)
    for (kind, platform, command, detail), occurrences in grouped.items():
        key = queue_item_key(kind, platform, command, detail)
        decision = catalog.find(key)
        device_ids = tuple(sorted({
            str(row.get("device_id"))
            for row in occurrences if row.get("device_id")
        }))
        items.append({
            "item_key": key,
            "kind": kind,
            "kind_label": status_kind[
                str(occurrences[0].get("collection_status"))
            ][1],
            "title": command,
            "detail": detail or (
                f"{len(occurrences)} occurrence(s) on {platform}."
            ),
            "status": decision.status if decision else "open",
            "decision": decision.to_dict() if decision else None,
            "occurrences": len(occurrences),
            "devices": device_ids[:20],
            "proposals": (),
            "conflicts": (),
            "impact": {
                "note": "This gap remains part of immutable collection evidence."
            },
            "href": (
                "/evidence?"
                + urlencode({
                    "status": str(
                        occurrences[0].get("collection_status") or ""
                    ),
                    "command": command,
                })
            ),
        })

    captured = [row for row in rows if row.get("content_sha256")]
    for field, kind, label in (
        ("parser_version", "missing-parser", "Missing parser provenance"),
        ("transport", "missing-transport", "Missing transport provenance"),
    ):
        missing = [row for row in captured if not row.get(field)]
        if missing:
            key = queue_item_key(kind, "all")
            decision = catalog.find(key)
            items.append({
                "item_key": key,
                "kind": kind,
                "kind_label": label,
                "title": f"{len(missing)} captured record(s)",
                "detail": (
                    f"The evidence index does not name {field.replace('_', ' ')} "
                    "for these records."
                ),
                "status": decision.status if decision else "open",
                "decision": decision.to_dict() if decision else None,
                "occurrences": len(missing),
                "devices": tuple(sorted({
                    str(row.get("device_id"))
                    for row in missing if row.get("device_id")
                }))[:20],
                "proposals": (),
                "conflicts": (),
                "impact": {"note": "No automatic repair is attempted."},
                "href": "/evidence",
            })

    snapshot_devices = {
        str(row.get("device_id"))
        for row in snapshots if row.get("device_id") and row.get("config_sha256")
    }
    evidence_devices = {
        str(row.get("device_id"))
        for row in rows if row.get("device_id")
    }
    missing_config = tuple(sorted(evidence_devices - snapshot_devices))
    if missing_config:
        key = queue_item_key("missing-configuration", "all")
        decision = catalog.find(key)
        items.append({
            "item_key": key,
            "kind": "missing-configuration",
            "kind_label": "Missing configuration",
            "title": f"{len(missing_config)} device(s)",
            "detail": "Command evidence exists, but no configuration snapshot was captured.",
            "status": decision.status if decision else "open",
            "decision": decision.to_dict() if decision else None,
            "occurrences": len(missing_config),
            "devices": missing_config[:20],
            "proposals": (),
            "conflicts": (),
            "impact": {"note": "Configuration and policy coverage remain partial."},
            "href": "/configuration",
        })

    latest: datetime | None = None
    for row in rows:
        stamp = _timestamp(str(row.get("collected_at") or ""))
        if stamp is not None and (latest is None or stamp > latest):
            latest = stamp
    current = now or datetime.now(timezone.utc)
    if latest is not None and current - latest > stale_after:
        key = queue_item_key("stale-evidence", latest.isoformat())
        decision = catalog.find(key)
        age_hours = int((current - latest).total_seconds() // 3600)
        items.append({
            "item_key": key,
            "kind": "stale-evidence",
            "kind_label": "Stale evidence",
            "title": f"Latest evidence is {age_hours} hours old",
            "detail": "Run discovery when it is safe to refresh operational conclusions.",
            "status": decision.status if decision else "open",
            "decision": decision.to_dict() if decision else None,
            "occurrences": len(rows),
            "devices": (),
            "proposals": (),
            "conflicts": (),
            "impact": {"note": "Stale evidence is never treated as recovery."},
            "href": "/discovery",
        })

    priority = {
        "identity": 0,
        "collection-failure": 1,
        "missing-configuration": 2,
        "missing-parser": 3,
        "missing-transport": 4,
        "unsupported-command": 5,
        "stale-evidence": 6,
        "empty-response": 7,
    }
    return tuple(sorted(
        items,
        key=lambda item: (
            1 if item["status"] != "open" else 0,
            priority.get(str(item["kind"]), 99),
            str(item["title"]).casefold(),
        ),
    ))


def filter_resolution_queue(
    items: Iterable[Mapping[str, Any]],
    *,
    kind: str = "",
    status: str = "",
    query: str = "",
) -> tuple[dict[str, Any], ...]:
    needle = query.strip().casefold()
    visible: list[dict[str, Any]] = []
    for raw in items:
        item = dict(raw)
        if kind and item.get("kind") != kind:
            continue
        if status and item.get("status") != status:
            continue
        if needle:
            haystack = " ".join([
                str(item.get("title") or ""),
                str(item.get("detail") or ""),
                " ".join(str(value) for value in item.get("devices") or ()),
                " ".join(
                    " ".join((
                        str(proposal.get("hostname") or ""),
                        str(proposal.get("signal") or ""),
                        str(proposal.get("detail") or ""),
                    ))
                    for proposal in item.get("proposals") or ()
                ),
            ]).casefold()
            if needle not in haystack:
                continue
        visible.append(item)
    return tuple(visible)


def _timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
