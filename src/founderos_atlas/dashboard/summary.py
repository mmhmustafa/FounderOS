"""Deterministic executive summary computed from existing Atlas artifacts.

The dashboard is an operational summary, not a monitoring system: it reads
the artifacts previous Atlas runs produced (snapshot, viewer, brief, change
report, configurations) and summarizes them. Missing artifacts degrade
gracefully — an empty workspace still renders a valid dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any

from founderos_atlas.history import HistoryRepository


STATUS_HEALTHY = "Healthy"
STATUS_WARNING = "Warning"
STATUS_CRITICAL = "Critical"
STATUS_UNKNOWN = "Unknown"


@dataclass(frozen=True)
class DashboardAction:
    label: str
    href: str | None

    @property
    def available(self) -> bool:
        return self.href is not None


@dataclass(frozen=True)
class DashboardSummary:
    last_discovery: str
    status: str
    status_detail: str
    device_count: int | None
    relationship_count: int | None
    discovery_success: str
    configurations_collected: int
    change_count: int | None
    recent_changes: tuple[str, ...]
    recent_activity: tuple[str, ...]
    recent_discoveries: tuple[str, ...]
    configuration_changes: tuple[str, ...]
    operational_changes: tuple[str, ...]
    incident_investigation: tuple[str, ...]
    actions: tuple[DashboardAction, ...]
    # Enterprise intelligence (PR-034); None/empty when no report exists.
    health_score: int | None = None
    health_trend: str | None = None
    health_confidence: str | None = None
    top_risks: tuple[str, ...] = ()
    top_recommendations: tuple[str, ...] = ()
    priority_queue: tuple[str, ...] = ()
    improvements: tuple[str, ...] = ()
    regressions: tuple[str, ...] = ()
    # Root cause analysis (PR-035); shown when confidence is high enough.
    root_cause_headline: str | None = None
    root_cause_band: str | None = None
    root_cause_percent: int | None = None
    root_cause_next_step: str | None = None
    # Latest change prediction (PR-036B), when one has been run.
    prediction_change: str | None = None
    prediction_risk: str | None = None
    prediction_confidence: str | None = None
    prediction_action: str | None = None
    prediction_blast: str | None = None

    @property
    def has_confident_root_cause(self) -> bool:
        return self.root_cause_band in ("high", "very-high")


def build_dashboard_summary(
    *,
    snapshot_path: str | Path = "topology_snapshot.json",
    topology_path: str | Path = "atlas_topology.html",
    brief_path: str | Path = "morning_brief.md",
    change_report_json: str | Path = "change_report.json",
    change_report_md: str | Path = "change_report.md",
    configs_dir: str | Path = "configs",
    history_root: str | Path = Path(".atlas") / "history",
    timeline_path: str | Path = "timeline.md",
    config_change_report: str | Path = "config_change_report.json",
    config_change_report_md: str | Path = "config_change_report.md",
    state_change_report: str | Path = "state_change_report.json",
    state_change_report_md: str | Path = "state_change_report.md",
    incident_report: str | Path = "incident_report.json",
    incident_report_md: str | Path = "incident_report.md",
    intelligence_report: str | Path = "intelligence_report.json",
    intelligence_report_md: str | Path = "intelligence_report.md",
    root_cause_report: str | Path = "root_cause_report.json",
    root_cause_report_md: str | Path = "root_cause_report.md",
    prediction_report: str | Path = "prediction_report.json",
    link_base: str | Path = ".",
) -> DashboardSummary:
    snapshot = _load_json(snapshot_path)
    change_report = _load_json(change_report_json)
    brief_exists = Path(brief_path).is_file()
    topology_exists = Path(topology_path).is_file()
    configurations = _count_configurations(Path(configs_dir))

    device_count = relationship_count = None
    failed_hosts: tuple[str, ...] = ()
    snapshot_warnings = 0
    last_discovery = "never"
    if snapshot is not None:
        device_count = int(snapshot.get("device_count") or 0)
        relationship_count = _logical_relationship_count(snapshot)
        metadata = snapshot.get("metadata") or {}
        failed_hosts = tuple(str(host) for host in metadata.get("failed_hosts") or ())
        snapshot_warnings = len(snapshot.get("warnings") or ())
        last_discovery = str(snapshot.get("created_at") or "unrecorded")

    history = HistoryRepository(history_root).load()
    if history.latest is not None:
        last_discovery = _format_timestamp(history.latest.completed_at)
    recent_discoveries = tuple(
        f"{_format_timestamp(record.started_at)} — {record.device_count} device(s) — "
        f"{record.network_status} — {record.duration_seconds:.1f}s"
        for record in history.records[:5]
    )

    change_count = None
    severity_counts: dict[str, int] = {}
    recent_changes: tuple[str, ...] = ()
    if change_report is not None:
        change_count = int(change_report.get("change_count") or 0)
        severity_counts = dict(change_report.get("severity_counts") or {})
        recent_changes = tuple(
            f"[{entry.get('severity', 'info')}] {entry.get('description', '')}"
            for entry in (change_report.get("changes") or ())[:5]
        )

    configuration_changes = _configuration_changes(_load_json(config_change_report))
    operational = _load_json(state_change_report)
    operational_changes = _operational_changes(operational)
    incident_investigation = _incident_investigation(_load_json(incident_report))
    intelligence = _intelligence_summary(_load_json(intelligence_report))
    root_cause = _root_cause_summary(_load_json(root_cause_report))
    prediction = _prediction_summary(_load_json(prediction_report))

    status, status_detail = _network_status(
        snapshot, change_count, severity_counts, snapshot_warnings, failed_hosts,
        operational,
    )
    discovery_success = _discovery_success(device_count, failed_hosts)
    recent_activity = _recent_activity(
        device_count,
        relationship_count,
        failed_hosts,
        brief_exists,
        change_count,
        configurations,
    )

    base = Path(link_base)
    actions = (
        DashboardAction("Open Topology", _href(Path(topology_path), base)),
        DashboardAction("Open Morning Brief", _href(Path(brief_path), base)),
        DashboardAction("Open Change Report", _href(Path(change_report_md), base)),
        DashboardAction("Open Configurations", _href(Path(configs_dir), base, directory=True)),
        DashboardAction("Open Snapshot", _href(Path(snapshot_path), base)),
        DashboardAction("Open History", _href(Path(history_root), base, directory=True)),
        DashboardAction("Open Timeline", _href(Path(timeline_path), base)),
        DashboardAction("Open Config Changes", _href(Path(config_change_report_md), base)),
        DashboardAction("Open Operational Changes", _href(Path(state_change_report_md), base)),
        DashboardAction("Open Incident Report", _href(Path(incident_report_md), base)),
        DashboardAction("Open Intelligence Report", _href(Path(intelligence_report_md), base)),
        DashboardAction("Open Root Cause Analysis", _href(Path(root_cause_report_md), base)),
    )
    return DashboardSummary(
        last_discovery=last_discovery,
        status=status,
        status_detail=status_detail,
        device_count=device_count,
        relationship_count=relationship_count,
        discovery_success=discovery_success,
        configurations_collected=configurations,
        change_count=change_count,
        recent_changes=recent_changes,
        recent_activity=recent_activity,
        recent_discoveries=recent_discoveries,
        configuration_changes=configuration_changes,
        operational_changes=operational_changes,
        incident_investigation=incident_investigation,
        actions=actions,
        **intelligence,
        **root_cause,
        **prediction,
    )


@dataclass(frozen=True)
class NetworkSummary:
    """One network's (discovery scope's) latest state in the global view."""

    scope_id: str
    label: str
    summary: DashboardSummary


@dataclass(frozen=True)
class GlobalDashboardSummary:
    """All networks combined: the latest successful state of every scope.

    This is pure aggregation — each network's numbers come from its own
    latest artifacts. Networks are never compared against each other, so a
    device absent from one network can never look "removed" from another.
    """

    network_count: int
    device_count: int
    relationship_count: int
    configurations_collected: int
    status: str
    status_detail: str
    networks: tuple[NetworkSummary, ...]


_STATUS_SEVERITY = {
    STATUS_CRITICAL: 3,
    STATUS_WARNING: 2,
    STATUS_HEALTHY: 1,
    STATUS_UNKNOWN: 0,
}


def aggregate_dashboard_summaries(
    networks: tuple[NetworkSummary, ...] | list[NetworkSummary],
) -> GlobalDashboardSummary:
    """Combine per-network summaries into one All Networks view."""

    resolved = tuple(networks)
    device_count = sum(net.summary.device_count or 0 for net in resolved)
    relationship_count = sum(net.summary.relationship_count or 0 for net in resolved)
    configurations = sum(net.summary.configurations_collected for net in resolved)
    status = STATUS_UNKNOWN
    for net in resolved:
        if _STATUS_SEVERITY.get(net.summary.status, 0) > _STATUS_SEVERITY.get(status, 0):
            status = net.summary.status
    if not resolved:
        detail = "No discovery has run yet in any network."
    elif status == STATUS_UNKNOWN:
        detail = "No network has discovery data yet."
    else:
        attention = tuple(
            net.label for net in resolved if net.summary.status == status
        )
        if status == STATUS_HEALTHY:
            detail = f"All {len(resolved)} network(s) healthy."
        else:
            detail = f"{status}: {', '.join(attention)}."
    return GlobalDashboardSummary(
        network_count=len(resolved),
        device_count=device_count,
        relationship_count=relationship_count,
        configurations_collected=configurations,
        status=status,
        status_detail=detail,
        networks=resolved,
    )


def _network_status(
    snapshot: dict[str, Any] | None,
    change_count: int | None,
    severity_counts: dict[str, int],
    snapshot_warnings: int,
    failed_hosts: tuple[str, ...],
    operational: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if snapshot is None:
        return STATUS_UNKNOWN, "No discovery has run yet. Run: founderos atlas discover"
    operational = operational or {}
    # Current health reflects unresolved (active) issues only — a recovery
    # event is history, not a reason to stay in Warning.
    op_active = int(operational.get("active_issue_count") or 0)
    op_health = str(operational.get("current_health") or "Healthy")
    interfaces_down = int(operational.get("interfaces_down") or 0)
    topology_high = int(severity_counts.get("high") or 0)
    if topology_high or op_health == STATUS_CRITICAL:
        reasons = []
        if topology_high:
            reasons.append(f"{topology_high} high-severity topology change(s)")
        if op_health == STATUS_CRITICAL:
            reasons.append(f"{interfaces_down} interface(s) down")
        return STATUS_CRITICAL, "; ".join(reasons) + " require attention."
    concerns: list[str] = []
    if change_count:
        concerns.append(f"{change_count} topology change(s) detected")
    if op_active:
        detail = f"{op_active} active operational issue(s)"
        if interfaces_down:
            detail += f" ({interfaces_down} interface(s) down)"
        concerns.append(detail)
    if failed_hosts:
        concerns.append(f"{len(failed_hosts)} host(s) failed discovery")
    if snapshot_warnings:
        concerns.append(f"{snapshot_warnings} reconciliation warning(s)")
    if concerns:
        return STATUS_WARNING, "; ".join(concerns) + "."
    return STATUS_HEALTHY, "No warnings or active issues detected."


def _discovery_success(device_count: int | None, failed_hosts: tuple[str, ...]) -> str:
    if device_count is None:
        return "—"
    attempted = device_count + len(failed_hosts)
    if attempted == 0:
        return "—"
    return f"{round(100 * device_count / attempted)}%"


def _recent_activity(
    device_count: int | None,
    relationship_count: int | None,
    failed_hosts: tuple[str, ...],
    brief_exists: bool,
    change_count: int | None,
    configurations: int,
) -> tuple[str, ...]:
    activity: list[str] = []
    if device_count is not None:
        activity.append(
            f"Topology discovered: {device_count} device(s), "
            f"{relationship_count or 0} relationship(s)."
        )
        if failed_hosts:
            activity.append(f"Discovery failed for {len(failed_hosts)} host(s).")
    if brief_exists:
        activity.append("Morning Brief generated.")
    if change_count is not None:
        activity.append(
            f"Change report: {change_count} change(s) detected."
            if change_count
            else "Change report: no changes detected."
        )
    if configurations:
        activity.append(f"Configurations collected for {configurations} device(s).")
    if not activity:
        activity.append("No discovery has run yet. Run: founderos atlas discover")
    return tuple(activity)


def _logical_relationship_count(snapshot: dict[str, Any]) -> int:
    hostname_by_id = {
        str(device.get("device_id")): str(device.get("hostname"))
        for device in snapshot.get("devices") or ()
    }
    links: set[tuple[str, str]] = set()
    for edge in snapshot.get("edges") or ():
        local = hostname_by_id.get(
            str(edge.get("local_device_id")), str(edge.get("local_device_id"))
        )
        remote = str(edge.get("remote_hostname"))
        endpoints = sorted((local.casefold(), remote.casefold()))
        links.add((endpoints[0], endpoints[1]))
    return len(links)


def _count_configurations(configs_dir: Path) -> int:
    if not configs_dir.is_dir():
        return 0
    return sum(
        1
        for entry in configs_dir.iterdir()
        if entry.is_dir() and (entry / "running_config.txt").is_file()
    )


def _configuration_changes(report: dict[str, Any] | None) -> tuple[str, ...]:
    if report is None:
        return ()
    counts = report.get("severity_counts") or {}
    devices = 1 if int(report.get("change_count") or 0) else 0
    return (
        f"Devices changed: {devices}",
        f"High severity: {counts.get('high', 0)}",
        f"Medium severity: {counts.get('medium', 0)}",
        f"Low severity: {counts.get('low', 0)}",
    )


def _operational_changes(report: dict[str, Any] | None) -> tuple[str, ...]:
    if report is None:
        return ()
    health = str(report.get("current_health") or report.get("status") or "Healthy")
    return (
        f"Current health: {health}",
        f"Active issues: {report.get('active_issue_count', 0)}",
        f"Interfaces currently down: {report.get('interfaces_down', 0)}",
        f"Recoveries: {report.get('recovery_count', 0)}",
        f"Historical events: {report.get('change_count', 0)}",
    )


def _intelligence_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    """DashboardSummary fields from an intelligence report, or empties."""

    if report is None:
        return {}
    health = report.get("health") or {}
    priorities = [p for p in report.get("priorities") or () if isinstance(p, dict)]
    recommendations = [
        r for r in report.get("recommendations") or () if isinstance(r, dict)
    ]
    improvements = []
    regressions = []
    if report.get("biggest_improvement"):
        improvements.append(str(report["biggest_improvement"]))
    if report.get("biggest_regression"):
        regressions.append(str(report["biggest_regression"]))
    return {
        "health_score": (
            int(health["score"]) if isinstance(health.get("score"), (int, float)) else None
        ),
        "health_trend": str(report.get("trend") or "baseline"),
        "health_confidence": str(health.get("confidence") or "unknown"),
        "top_risks": tuple(
            f"{p.get('title')} — severity {p.get('severity')}, "
            f"risk {p.get('risk')}, urgency {p.get('urgency')}"
            for p in priorities[:5]
        ),
        "top_recommendations": tuple(
            f"{r.get('title')}: {r.get('next_step')}" for r in recommendations[:5]
        ),
        "priority_queue": tuple(str(p.get("title")) for p in priorities[:5]),
        "improvements": tuple(improvements),
        "regressions": tuple(regressions),
    }


def _root_cause_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    """The most likely root cause for the dashboard, or empties."""

    if report is None:
        return {}
    most = report.get("most_important")
    if not isinstance(most, dict):
        return {}
    primary = most.get("primary") or {}
    if not primary.get("statement"):
        return {}
    return {
        "root_cause_headline": str(primary["statement"]),
        "root_cause_band": str(primary.get("band") or "low"),
        "root_cause_percent": (
            int(primary["confidence_percent"])
            if isinstance(primary.get("confidence_percent"), (int, float))
            else None
        ),
        "root_cause_next_step": str(primary.get("next_step") or ""),
    }


def _prediction_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    """The latest change prediction for the dashboard panel, or empties."""

    if report is None:
        return {}
    change = report.get("change_request") or {}
    risk = report.get("risk") or {}
    confidence = report.get("confidence") or {}
    advice = report.get("advice") or {}
    blast = report.get("blast_radius") or {}
    if not change.get("change_type"):
        return {}
    subject = " ".join(
        part
        for part in (
            str(change.get("target_device") or ""),
            str(change.get("target_object") or ""),
        )
        if part
    )
    return {
        "prediction_change": f"{change['change_type']}: {subject}",
        "prediction_risk": str(risk.get("level") or "unknown"),
        "prediction_confidence": (
            f"{confidence.get('band', 'unknown')} ({confidence.get('percent', '?')}%)"
        ),
        "prediction_action": str(advice.get("action") or ""),
        "prediction_blast": str(blast.get("summary") or ""),
    }


def _incident_investigation(report: dict[str, Any] | None) -> tuple[str, ...]:
    if report is None:
        return ()
    return (
        f"Title: {report.get('title', 'unknown')}",
        f"Generated: {_format_timestamp(str(report.get('generated_at', 'unrecorded')))}",
        f"Confidence: {str(report.get('confidence', 'unknown')).title()}",
    )


def _format_timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d-%b-%Y %H:%M")
    except ValueError:
        return value


def _load_json(path: str | Path) -> dict[str, Any] | None:
    resolved = Path(path)
    if not resolved.is_file():
        return None
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _href(target: Path, base: Path, *, directory: bool = False) -> str | None:
    exists = target.is_dir() if directory else target.is_file()
    if not exists:
        return None
    try:
        return os.path.relpath(target, base).replace(os.sep, "/")
    except ValueError:
        return target.resolve().as_uri()
