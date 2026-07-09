"""Deterministic JSON and Markdown rendering for incident reports."""

from __future__ import annotations

import json

from .models import IncidentReport


def render_incident_report_json(report: IncidentReport) -> str:
    if not isinstance(report, IncidentReport):
        raise TypeError("report must be an IncidentReport")
    return json.dumps(
        report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"


def render_incident_report_markdown(report: IncidentReport) -> str:
    if not isinstance(report, IncidentReport):
        raise TypeError("report must be an IncidentReport")

    def bullet_list(values: tuple[str, ...], empty: str) -> list[str]:
        return [f"- {value}" for value in values] if values else [f"- {empty}"]

    lines = [
        "# Atlas Incident Investigation",
        "",
        f"- Incident ID: `{report.incident_id}`",
        f"- Title: {report.title}",
        f"- Generated at: {report.generated_at}",
        f"- Confidence: {report.confidence.title()}",
        "",
        "## Description",
        "",
        report.description,
        "",
        "## Affected Devices",
        "",
        *bullet_list(report.affected_devices, "No devices matched the incident description."),
        "",
        "## Topology Context",
        "",
        *bullet_list(report.topology_context, "No topology snapshot is available."),
        "",
        "## Possible Related Changes",
        "",
        *bullet_list(report.possible_related_changes, "No related changes were found in available reports."),
        "",
        "## Configuration Context",
        "",
        *bullet_list(report.configuration_context, "No configuration evidence is available."),
        "",
        "## Evidence",
        "",
        *(
            [f"- {item.statement} _(source: {item.source})_" for item in report.evidence]
            or ["- No evidence was available."]
        ),
        "",
        "## Investigation Steps",
        "",
        *(f"{index}. {step}" for index, step in enumerate(report.investigation_steps, start=1)),
        "",
        "## Recommendations",
        "",
        *bullet_list(report.recommendations, "No recommendations."),
        "",
        "## Limitations",
        "",
        *bullet_list(report.limitations, "None."),
        "",
    ]
    return "\n".join(lines)
