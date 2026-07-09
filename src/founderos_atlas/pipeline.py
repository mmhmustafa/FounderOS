"""Unified discovery intelligence pipeline.

After live discovery, Atlas automatically loads the previous baseline from
history, compares topology and configurations, and aggregates the results.
This module holds the pure composition steps; prompting, transports, and
file delivery remain in the CLI layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .change import ChangeDetector, ChangeReport
from .config import safe_artifact_name
from .config_intelligence import (
    ConfigChangeReport,
    SEVERITY_ORDER as CONFIG_SEVERITY_ORDER,
    compare_configurations,
    render_config_report_markdown,
)
from .history import DiscoveryRecord, HistoryRepository
from .topology import TopologySnapshot


@dataclass(frozen=True)
class Baseline:
    """The previous discovery Atlas will compare against, if one exists."""

    record: DiscoveryRecord | None
    snapshot: TopologySnapshot | None
    issues: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.snapshot is not None


def load_previous_baseline(history_root: str | Path) -> Baseline:
    """Latest history record plus its reconstructed, integrity-checked snapshot."""

    repository = HistoryRepository(history_root)
    record = repository.latest()
    if record is None:
        return Baseline(record=None, snapshot=None)
    snapshot_path = repository.snapshot_path(record.record_id)
    if not snapshot_path.is_file():
        return Baseline(
            record=record,
            snapshot=None,
            issues=(f"Baseline record {record.record_id} holds no topology snapshot.",),
        )
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot = TopologySnapshot.from_dict(data)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return Baseline(
            record=record,
            snapshot=None,
            issues=(
                f"Baseline snapshot in {record.record_id} could not be loaded: {error}",
            ),
        )
    return Baseline(record=record, snapshot=snapshot)


def run_topology_intelligence(
    baseline: Baseline, current: TopologySnapshot
) -> ChangeReport | None:
    """Automatic change intelligence when a previous topology exists."""

    if not baseline.available:
        return None
    return ChangeDetector().compare(baseline.snapshot, current)


def run_configuration_intelligence(
    history_root: str | Path,
    baseline: Baseline,
    collected: Mapping[str, str | Path],
) -> tuple[ConfigChangeReport, ...]:
    """Automatic per-device config intelligence against the baseline record.

    ``collected`` maps hostname -> this run's artifact directory. Devices
    without a baseline configuration are skipped: no previous evidence means
    no comparison, never an invented one.
    """

    if baseline.record is None:
        return ()
    repository = HistoryRepository(history_root)
    record_dir = repository.record_directory(baseline.record.record_id)
    reports: list[ConfigChangeReport] = []
    for hostname in sorted(collected, key=str.casefold):
        previous_file = (
            record_dir / "configs" / safe_artifact_name(hostname) / "running_config.txt"
        )
        current_file = Path(collected[hostname]) / "running_config.txt"
        if not previous_file.is_file() or not current_file.is_file():
            continue
        try:
            previous_text = previous_file.read_text(encoding="utf-8")
            current_text = current_file.read_text(encoding="utf-8")
        except OSError:
            continue
        reports.append(
            compare_configurations(
                previous_text,
                current_text,
                hostname=hostname,
                previous_ref=baseline.record.record_id,
                current_ref="current-discovery",
            )
        )
    return tuple(reports)


def aggregate_config_reports(
    reports: tuple[ConfigChangeReport, ...]
) -> tuple[dict[str, Any], str]:
    """One JSON document and one Markdown document across all compared devices."""

    severity_counts = {severity: 0 for severity in CONFIG_SEVERITY_ORDER}
    for report in reports:
        for severity, count in report.severity_counts.items():
            severity_counts[severity] += count
    data = {
        "generated_by": "founderos atlas discover",
        "device_count": len(reports),
        "devices_changed": sum(1 for report in reports if report.change_count),
        "change_count": sum(report.change_count for report in reports),
        "severity_counts": severity_counts,
        "reports": [report.to_dict() for report in reports],
        "secrets_masked": True,
    }
    if not reports:
        markdown = (
            "# Atlas Configuration Change Report\n\n"
            "No baseline configurations were available for comparison.\n"
        )
    else:
        sections = [
            "# Atlas Configuration Change Report",
            "",
            f"- Devices compared: {len(reports)}",
            f"- Devices changed: {data['devices_changed']}",
            f"- Changes detected: {data['change_count']}",
            "- Secrets: masked",
            "",
        ]
        for report in reports:
            sections.append(f"---\n")
            sections.append(render_config_report_markdown(report))
        markdown = "\n".join(sections)
    return data, markdown
