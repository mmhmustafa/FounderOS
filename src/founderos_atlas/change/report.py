"""Deterministic JSON and Markdown rendering for Atlas change reports."""

from __future__ import annotations

import json

from .models import SEVERITY_ORDER, ChangeReport


def render_change_report_json(report: ChangeReport) -> str:
    if not isinstance(report, ChangeReport):
        raise TypeError("report must be a ChangeReport")
    return json.dumps(
        report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"


def render_change_report_markdown(report: ChangeReport) -> str:
    if not isinstance(report, ChangeReport):
        raise TypeError("report must be a ChangeReport")
    lines = [
        "# Atlas Change Report",
        "",
        f"- Previous snapshot: `{report.previous_snapshot_id}`",
        f"- Current snapshot: `{report.current_snapshot_id}`",
        f"- Changes detected: {report.change_count}",
        "",
        "## Severity Summary",
        "",
        "| Severity | Count |",
        "|---|---|",
    ]
    counts = report.severity_counts
    lines.extend(f"| {severity.title()} | {counts[severity]} |" for severity in SEVERITY_ORDER)
    lines.extend(("", "## Changes", ""))
    if not report.changes:
        lines.append("No changes detected between the two snapshots.")
    for change in report.changes:
        lines.extend(
            (
                f"### [{change.severity.title()}] {change.description}",
                "",
                f"- Category: {change.category}",
                f"- Subject: {change.subject}",
            )
        )
        if change.previous_value is not None:
            lines.append(f"- Previous: {change.previous_value}")
        if change.current_value is not None:
            lines.append(f"- Current: {change.current_value}")
        lines.extend((f"- Recommendation: {change.recommendation}", ""))
    if report.changes:
        lines.extend(("## Recommendations", ""))
        lines.extend(f"- {item}" for item in report.recommendations)
        lines.append("")
    return "\n".join(lines)
