"""Network timeline: a day-grouped Markdown story of discovery history.

Reuses change intelligence between consecutive stored snapshots, so each
timeline entry can say what actually changed — not just that a discovery
happened.
"""

from __future__ import annotations

from datetime import date
import json

from founderos_atlas.change import ChangeDetector

from .models import CONFIG_COLLECTED, CONFIG_PARTIAL, DiscoveryRecord
from .repository import HistoryIndex, HistoryRepository


_MAX_CHANGE_LINES = 5


def generate_timeline(
    repository: HistoryRepository, index: HistoryIndex | None = None
) -> str:
    resolved = index if index is not None else repository.load()
    lines = ["# Network Timeline", ""]
    if not resolved.records:
        lines.extend(
            ("No discoveries recorded yet. Run: founderos atlas discover", "")
        )
        return "\n".join(lines)

    current_day = None
    records = resolved.records  # newest first
    for position, record in enumerate(records):
        day = _day_label(record.started_at)
        if day != current_day:
            current_day = day
            lines.extend((f"## {day}", ""))
        previous = records[position + 1] if position + 1 < len(records) else None
        lines.extend(_entry_lines(repository, record, previous))
    if resolved.issues:
        lines.extend(("## Issues", ""))
        lines.extend(f"- {issue}" for issue in resolved.issues)
        lines.append("")
    return "\n".join(lines)


def _entry_lines(
    repository: HistoryRepository,
    record: DiscoveryRecord,
    previous: DiscoveryRecord | None,
) -> list[str]:
    time_label = record.started_at[11:16] or record.started_at
    lines = [f"### {time_label} — Discovery completed", ""]
    device_line = f"- Devices: {record.device_count}"
    if previous is not None:
        delta = record.device_count - previous.device_count
        if delta:
            device_line += f" ({'+' if delta > 0 else ''}{delta} since previous discovery)"
    lines.append(device_line)
    lines.append(f"- Relationships: {record.relationship_count}")
    lines.append(f"- Status: {record.network_status}")
    if record.configuration_status in (CONFIG_COLLECTED, CONFIG_PARTIAL):
        lines.append(
            f"- Configuration collected for {record.configured_device_count} device(s)"
        )
    if record.failures:
        lines.append(f"- Discovery failed for {len(record.failures)} host(s)")
    change_lines = _change_lines(repository, record, previous)
    if change_lines:
        lines.append("- Changes since previous discovery:")
        lines.extend(f"  - {entry}" for entry in change_lines)
    lines.append("")
    return lines


def _change_lines(
    repository: HistoryRepository,
    record: DiscoveryRecord,
    previous: DiscoveryRecord | None,
) -> list[str]:
    if previous is None:
        return []
    previous_snapshot = _load_snapshot(repository, previous.record_id)
    current_snapshot = _load_snapshot(repository, record.record_id)
    if previous_snapshot is None or current_snapshot is None:
        return []
    try:
        report = ChangeDetector().compare(previous_snapshot, current_snapshot)
    except (TypeError, ValueError):
        return []
    return [
        f"[{change.severity}] {change.description}"
        for change in report.changes[:_MAX_CHANGE_LINES]
    ]


def _load_snapshot(repository: HistoryRepository, record_id: str) -> dict | None:
    path = repository.snapshot_path(record_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _day_label(started_at: str) -> str:
    try:
        return date.fromisoformat(started_at[:10]).strftime("%d-%b-%Y")
    except ValueError:
        return started_at[:10] or "unknown date"
