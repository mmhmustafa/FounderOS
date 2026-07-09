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
    incident_investigation: tuple[str, ...]
    actions: tuple[DashboardAction, ...]


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
    incident_report: str | Path = "incident_report.json",
    incident_report_md: str | Path = "incident_report.md",
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
    incident_investigation = _incident_investigation(_load_json(incident_report))

    status, status_detail = _network_status(
        snapshot, change_count, severity_counts, snapshot_warnings, failed_hosts
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
        DashboardAction("Open Incident Report", _href(Path(incident_report_md), base)),
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
        incident_investigation=incident_investigation,
        actions=actions,
    )


def _network_status(
    snapshot: dict[str, Any] | None,
    change_count: int | None,
    severity_counts: dict[str, int],
    snapshot_warnings: int,
    failed_hosts: tuple[str, ...],
) -> tuple[str, str]:
    if snapshot is None:
        return STATUS_UNKNOWN, "No discovery has run yet. Run: founderos atlas discover"
    high = int(severity_counts.get("high") or 0)
    if high:
        return STATUS_CRITICAL, f"{high} high-severity change(s) require attention."
    concerns: list[str] = []
    if change_count:
        concerns.append(f"{change_count} change(s) detected")
    if failed_hosts:
        concerns.append(f"{len(failed_hosts)} host(s) failed discovery")
    if snapshot_warnings:
        concerns.append(f"{snapshot_warnings} reconciliation warning(s)")
    if concerns:
        return STATUS_WARNING, "; ".join(concerns) + "."
    return STATUS_HEALTHY, "No warnings or changes detected."


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
