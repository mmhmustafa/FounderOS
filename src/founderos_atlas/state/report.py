"""Deterministic JSON and Markdown rendering for operational state reports."""

from __future__ import annotations

import json

from .models import SEVERITY_ORDER, StateChangeReport


def render_state_report_json(report: StateChangeReport) -> str:
    if not isinstance(report, StateChangeReport):
        raise TypeError("report must be a StateChangeReport")
    return json.dumps(
        report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"


def render_state_report_markdown(report: StateChangeReport) -> str:
    if not isinstance(report, StateChangeReport):
        raise TypeError("report must be a StateChangeReport")
    counts = report.severity_counts
    lines = [
        "# Atlas Operational Change Report",
        "",
        f"- Previous: `{report.previous_ref}`",
        f"- Current: `{report.current_ref}`",
        f"- Current health: {report.current_health}",
        f"- Active issues: {report.active_issue_count}",
        f"- Recoveries: {len(report.recoveries)}",
        f"- Interfaces currently down: {report.interfaces_down}",
        f"- Historical events: {report.change_count}",
        "",
        "## Severity Summary",
        "",
        "| Severity | Count |",
        "|---|---|",
    ]
    lines.extend(f"| {severity.title()} | {counts[severity]} |" for severity in SEVERITY_ORDER)

    lines.extend(("", "## Active Issues", ""))
    if not report.active_issues:
        lines.append("No active operational issues — the current state is healthy.")
    for change in report.active_issues:
        lines.append(
            f"- [{change.severity.upper()}] {change.hostname} {change.interface}: "
            f"{change.description} — {change.recommendation}"
        )

    lines.extend(("", "## Events (history)", ""))
    if not report.changes:
        lines.append("No operational changes detected between the two snapshots.")
    for change in report.changes:
        lines.extend(
            (
                f"### [{change.event.upper()}] {change.hostname} {change.interface}",
                "",
                f"- {change.description}",
            )
        )
        if change.previous_value is not None and change.current_value is not None:
            lines.append(
                f"- {change.field}: {change.previous_value} → {change.current_value}"
            )
        lines.extend((f"- Recommendation: {change.recommendation}", ""))
    return "\n".join(lines)
