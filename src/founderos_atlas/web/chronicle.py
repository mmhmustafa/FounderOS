"""The unified chronology: every event Atlas knows about, one row shape.

Extends the original two-source timeline (configuration changes and
discovery runs) to the full operational record: topology and
operational changes, incidents, predictions, Compass activity, and
every audited operator mutation (site overrides, identity resolutions
— undo included — policy exceptions, assignments, acknowledgements,
suppressions). Every event carries its exact object's URL and its
provenance (the report, record, or audit event it came from).

Pure functions over already-loaded data: filterable, pageable,
scale-testable without a browser.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote


EVENT_KINDS = (
    "discovery", "configuration", "topology-change", "operational-change",
    "incident", "prediction", "compass", "site-override",
    "identity-resolution", "policy-exception", "annotation", "policy-trend",
)

_AUDIT_KIND_MAP = {
    "site-override": "site-override",
    "identity-resolution": "identity-resolution",
    "policy-exception": "policy-exception",
    "policy-assignment": "annotation",
    "change-ack": "annotation",
    "change-assignment": "annotation",
    "change-note": "annotation",
    "change-suppression": "annotation",
}

_SEVERITY_ORDER = {"high": 0, "critical": 0, "medium": 1, "low": 2, "info": 3}


def _event(
    *,
    occurred_at: str,
    kind: str,
    title: str,
    href: str,
    detail: str = "",
    hostname: str | None = None,
    device_id: str | None = None,
    network: str = "",
    severity: str = "info",
    actor: str | None = None,
    provenance: str = "",
) -> dict[str, Any]:
    return {
        "occurred_at": occurred_at, "kind": kind, "title": title,
        "detail": detail, "href": href, "hostname": hostname,
        "device_id": device_id, "network": network, "severity": severity,
        "actor": actor, "provenance": provenance,
    }


def chronicle_events(
    *,
    config_events: Sequence[Any] = (),
    discovery_rows: Sequence[Mapping[str, Any]] = (),
    change_rows: Sequence[Mapping[str, Any]] = (),
    incident_reports: Sequence[tuple[str, Mapping[str, Any]]] = (),
    prediction_reports: Sequence[tuple[str, Mapping[str, Any]]] = (),
    compass_plans: Sequence[Mapping[str, Any]] = (),
    audit_events: Sequence[Any] = (),
    policy_trend: Sequence[tuple[str, Mapping[str, Any]]] = (),
) -> list[dict[str, Any]]:
    """Fold every source into one chronology, newest first."""

    events: list[dict[str, Any]] = []

    for event in config_events:
        events.append(_event(
            occurred_at=str(event.occurred_at),
            kind="configuration",
            title=f"{event.hostname} configuration changed",
            detail=str(event.summary),
            href=f"/configuration/{quote(str(event.device_id), safe='')}",
            hostname=str(event.hostname), device_id=str(event.device_id),
            network=str(event.network),
            severity=str(event.highest_severity or "info"),
            provenance=f"configuration memory · session {event.discovery_session}",
        ))
    for row in discovery_rows:
        record_id = str(row.get("record_id") or "")
        events.append(_event(
            occurred_at=str(row.get("started_at_iso") or ""),
            kind="discovery",
            title=f"Discovery ran on {row.get('profile') or 'the network'}",
            detail=(
                f"{row.get('device_count', 0)} device(s), "
                f"{row.get('relationship_count', 0)} relationship(s) · "
                f"{row.get('network_status', 'unknown')}"
            ),
            href=f"/history?run={quote(record_id, safe='')}" if record_id
            else "/history",
            network=str(row.get("profile") or ""),
            severity="info",
            provenance=f"discovery record {record_id}",
        ))
    for row in change_rows:
        kind = (
            "topology-change" if row.get("kind") == "topology"
            else "operational-change" if row.get("kind") == "operational"
            else "configuration"
        )
        if row.get("kind") == "configuration":
            # Configuration changes already stream from configuration
            # memory above with richer provenance; skip the report copy.
            continue
        events.append(_event(
            occurred_at=str(row.get("occurred_at") or ""),
            kind=kind,
            title=str(row.get("description") or "change detected"),
            detail=str(row.get("field") or ""),
            href=f"/changes#{row.get('subject')}",
            hostname=str(row.get("device") or "") or None,
            network=str(row.get("network") or ""),
            severity=str(row.get("severity") or "info"),
            provenance=f"{row.get('kind')} change report",
        ))
    for network, report in incident_reports:
        if not report or not report.get("title"):
            continue
        events.append(_event(
            occurred_at=str(report.get("generated_at") or ""),
            kind="incident",
            title=f"Incident investigated: {report.get('title')}",
            detail=(
                f"{report.get('confidence') or 'unknown'} confidence · "
                + ", ".join(
                    str(name) for name in report.get("affected_devices") or ()
                )
            ),
            href="/incidents",
            network=network,
            severity="high",
            hostname=next(
                (str(name)
                 for name in report.get("affected_devices") or ()), None
            ),
            provenance="incident report",
        ))
    for network, report in prediction_reports:
        if not report:
            continue
        change_request = report.get("change_request") or {}
        events.append(_event(
            occurred_at=str(report.get("generated_at") or ""),
            kind="prediction",
            title=(
                "Prediction: "
                f"{change_request.get('change_type') or 'change'} "
                f"{change_request.get('target_device') or ''} "
                f"{change_request.get('target_object') or ''}"
            ).strip(),
            detail=f"risk {((report.get('risk') or {}).get('level')) or 'unknown'}",
            href="/predict",
            hostname=str(change_request.get("target_device") or "") or None,
            network=network,
            severity=str(((report.get("risk") or {}).get("level")) or "info"),
            provenance="prediction report",
        ))
    for plan in compass_plans:
        events.append(_event(
            occurred_at=str(plan.get("updated_at") or plan.get("created_at") or ""),
            kind="compass",
            title=f"Compass plan: {plan.get('title')}",
            detail=(
                f"{plan.get('status')} · "
                f"{len(plan.get('changes') or ())} change(s)"
            ),
            href=f"/compass/{quote(str(plan.get('plan_id')), safe='')}",
            severity="info",
            provenance="compass plan repository",
        ))
    for event in audit_events:
        kind = _AUDIT_KIND_MAP.get(event.category, "annotation")
        title = f"{event.category} {event.operation}: {event.subject}"
        if event.operation == "undo":
            title = f"UNDO {event.category}: {event.subject}"
        events.append(_event(
            occurred_at=str(event.occurred_at),
            kind=kind,
            title=title,
            detail=str(event.reason or ""),
            href=f"/audit?category={quote(event.category, safe='')}",
            severity="info",
            actor=str(event.actor),
            provenance=f"audit event {event.event_id}",
        ))
    for scope_id, point in policy_trend:
        events.append(_event(
            occurred_at=str(point.get("recorded_at") or ""),
            kind="policy-trend",
            title=f"Compliance posture changed: {point.get('score')}%",
            detail=(
                f"{point.get('failed')} failed · {point.get('warnings')} "
                f"warnings · {point.get('unknown')} unknown"
            ),
            href=f"/policy?scope={quote(scope_id, safe='')}",
            network=scope_id,
            severity="medium" if point.get("failed") else "info",
            provenance="policy trend record",
        ))

    events.sort(key=lambda item: item["occurred_at"] or "", reverse=True)
    return events


@dataclass(frozen=True)
class ChronicleFilter:
    query: str = ""
    kind: str = ""
    device: str = ""
    site: str = ""
    actor: str = ""
    severity: str = ""
    date_from: str = ""
    date_to: str = ""
    page: int = 1
    per_page: int = 50

    @classmethod
    def from_args(cls, args: Mapping[str, str]) -> "ChronicleFilter":
        from founderos_atlas.listing import DEFAULT_PER_PAGE, MAX_PER_PAGE, int_arg

        return cls(
            query=str(args.get("q", "") or "").strip(),
            kind=str(args.get("kind", "") or "").strip(),
            device=str(args.get("device", "") or "").strip(),
            site=str(args.get("site", "") or "").strip(),
            actor=str(args.get("actor", "") or "").strip(),
            severity=str(args.get("severity", "") or "").strip(),
            date_from=str(args.get("from", "") or "").strip(),
            date_to=str(args.get("to", "") or "").strip(),
            page=int_arg(args, "page", 1, 100000),
            per_page=int_arg(args, "per_page", DEFAULT_PER_PAGE, MAX_PER_PAGE),
        )

    def to_args(self) -> dict[str, str]:
        pairs = {
            "q": self.query, "kind": self.kind, "device": self.device,
            "site": self.site, "actor": self.actor,
            "severity": self.severity, "from": self.date_from,
            "to": self.date_to,
        }
        return {key: value for key, value in pairs.items() if value}


def filter_events(
    events: Sequence[Mapping[str, Any]],
    filters: ChronicleFilter,
    *,
    sites_by_device: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    sites = {k.casefold(): v for k, v in (sites_by_device or {}).items()}
    needle = filters.query.casefold()
    found: list[dict[str, Any]] = []
    for event in events:
        occurred = str(event.get("occurred_at") or "")
        if filters.kind and str(event.get("kind")) != filters.kind:
            continue
        if filters.device and (
            str(event.get("hostname") or "").casefold()
            != filters.device.casefold()
        ):
            continue
        if filters.site:
            hostname = str(event.get("hostname") or "").casefold()
            if sites.get(hostname, "unknown") != filters.site:
                continue
        if filters.actor and str(event.get("actor") or "") != filters.actor:
            continue
        if filters.severity and str(event.get("severity")) != filters.severity:
            continue
        if filters.date_from and occurred and occurred < filters.date_from:
            continue
        if filters.date_to and occurred and occurred > filters.date_to + "￿":
            continue
        if needle:
            haystack = " ".join((
                str(event.get("title") or ""),
                str(event.get("detail") or ""),
                str(event.get("hostname") or ""),
                str(event.get("network") or ""),
                str(event.get("actor") or ""),
            )).casefold()
            if needle not in haystack:
                continue
        found.append(dict(event))
    return found


def summarize_kinds(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        kind = str(event.get("kind"))
        counts[kind] = counts.get(kind, 0) + 1
    return counts
