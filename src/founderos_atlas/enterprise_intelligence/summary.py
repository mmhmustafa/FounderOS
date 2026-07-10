"""Renderers: intelligence JSON artifact, markdown report, brief section.

The JSON artifact is the machine contract (dashboards, GUI, tests, and a
future AI layer). The markdown mirrors it for humans. The brief section is
appended to the Morning Brief — v2: the brief opens with what matters, not
with raw events.
"""

from __future__ import annotations

import json

from .models import EnterpriseIntelligence


def render_intelligence_json(intelligence: EnterpriseIntelligence) -> str:
    return (
        json.dumps(
            intelligence.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def render_intelligence_markdown(intelligence: EnterpriseIntelligence) -> str:
    lines = [
        "# Atlas Enterprise Intelligence",
        "",
        f"- Generated: {intelligence.generated_at}",
        f"- Enterprise Health: {intelligence.health.score}/100",
        f"- Trend: {intelligence.trend.title()} ({intelligence.trend_detail})",
        f"- Confidence: {intelligence.health.confidence.title()}",
        "",
        "## Health Factors",
        "",
        "| Factor | Points | Detail |",
        "|---|---|---|",
    ]
    if intelligence.health.factors:
        lines.extend(
            f"| {factor.name} | {factor.points:+d} | {factor.detail} |"
            for factor in intelligence.health.factors
        )
    else:
        lines.append("| (none) | +0 | no deductions or credits this run |")
    lines.extend(("", "## Top Priorities", ""))
    if intelligence.priorities:
        for index, finding in enumerate(intelligence.priorities, start=1):
            lines.append(
                f"{index}. **{finding.title}** — severity {finding.severity}, "
                f"risk {finding.risk}, confidence {finding.confidence}, "
                f"urgency {finding.urgency}"
            )
            lines.append(f"   - {finding.summary}")
    else:
        lines.append("Nothing needs your attention right now.")
    lines.extend(("", "## Recommendations", ""))
    if intelligence.recommendations:
        for recommendation in intelligence.recommendations:
            lines.extend(
                (
                    f"### {recommendation.title}",
                    "",
                    f"- Impact: {recommendation.impact}",
                    f"- Likely cause: {recommendation.likely_cause}",
                    f"- Suggested next step: {recommendation.next_step}",
                    "",
                )
            )
    else:
        lines.append("No recommendations — keep discovering regularly.")
    lines.extend(("", "## Trends", ""))
    for signal in intelligence.trends:
        lines.append(f"- {signal.name}: {signal.direction} — {signal.detail}")
    if intelligence.changes_summary:
        lines.extend(("", "## Changes Since The Previous Discovery", ""))
        lines.extend(f"- {entry}" for entry in intelligence.changes_summary)
    if intelligence.biggest_improvement or intelligence.biggest_regression:
        lines.append("")
        if intelligence.biggest_improvement:
            lines.append(f"- Biggest improvement: {intelligence.biggest_improvement}")
        if intelligence.biggest_regression:
            lines.append(f"- Biggest regression: {intelligence.biggest_regression}")
    return "\n".join(lines) + "\n"


def intelligence_brief_section(intelligence: EnterpriseIntelligence) -> str:
    """Morning Brief v2: the intelligence section appended to the brief."""

    lines = [
        "",
        "## Enterprise Intelligence",
        "",
        f"- Enterprise Health: **{intelligence.health.score}/100**",
        f"- Trend: {intelligence.trend.title()} — {intelligence.trend_detail}",
        f"- Confidence: {intelligence.health.confidence.title()}",
        "",
        "### Top Risks",
        "",
    ]
    if intelligence.priorities:
        lines.extend(
            f"{index}. {finding.title} (severity {finding.severity}, "
            f"risk {finding.risk}, urgency {finding.urgency})"
            for index, finding in enumerate(intelligence.priorities, start=1)
        )
    else:
        lines.append("Nothing needs your attention right now.")
    lines.extend(("", "### Top Recommendations", ""))
    if intelligence.recommendations:
        for recommendation in intelligence.recommendations[:3]:
            lines.append(f"- **{recommendation.title}** — {recommendation.next_step}")
    else:
        lines.append("- No recommendations — keep discovering regularly.")
    lines.extend(("", "### Changes Since Yesterday", ""))
    lines.extend(f"- {entry}" for entry in intelligence.changes_summary)
    if intelligence.biggest_improvement:
        lines.extend(("", f"- Biggest improvement: {intelligence.biggest_improvement}"))
    if intelligence.biggest_regression:
        lines.append(f"- Biggest regression: {intelligence.biggest_regression}")
    if intelligence.suggested_investigation:
        lines.extend(
            (
                "",
                "### Suggested Investigation",
                "",
                intelligence.suggested_investigation,
            )
        )
    return "\n".join(lines) + "\n"
