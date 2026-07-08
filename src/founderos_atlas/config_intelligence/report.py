"""Deterministic JSON and Markdown rendering for configuration change reports."""

from __future__ import annotations

import json

from .models import SEVERITY_ORDER, ConfigChangeReport


def render_config_report_json(report: ConfigChangeReport) -> str:
    if not isinstance(report, ConfigChangeReport):
        raise TypeError("report must be a ConfigChangeReport")
    return json.dumps(
        report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"


def render_config_report_markdown(report: ConfigChangeReport) -> str:
    if not isinstance(report, ConfigChangeReport):
        raise TypeError("report must be a ConfigChangeReport")
    counts = report.severity_counts
    lines = [
        "# Atlas Configuration Change Report",
        "",
        f"- Device: {report.hostname}",
        f"- Previous: `{report.previous_ref}`",
        f"- Current: `{report.current_ref}`",
        f"- Changes detected: {report.change_count}",
        "- Secrets: masked",
        "",
        "## Severity Summary",
        "",
        "| Severity | Count |",
        "|---|---|",
    ]
    lines.extend(f"| {severity.title()} | {counts[severity]} |" for severity in SEVERITY_ORDER)
    lines.extend(("", "## Changes", ""))
    if not report.changes:
        lines.append("No configuration changes detected between the two configurations.")
    for change in report.changes:
        lines.extend(
            (
                f"### [{change.severity.title()}] {change.raw_diff_reference}",
                "",
                f"- Category: {change.category}",
                f"- {change.summary}",
                f"- Recommendation: {change.recommendation}",
            )
        )
        if change.added_lines:
            lines.extend(("", "```diff"))
            lines.extend(f"+ {line}" for line in change.added_lines)
            if change.removed_lines:
                lines.extend(f"- {line}" for line in change.removed_lines)
            lines.append("```")
        elif change.removed_lines:
            lines.extend(("", "```diff"))
            lines.extend(f"- {line}" for line in change.removed_lines)
            lines.append("```")
        lines.append("")
    return "\n".join(lines)
