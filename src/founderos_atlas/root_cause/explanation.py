"""Explanation engine: human-readable reasoning that cites its evidence.

The reasoning chain follows the causal graph from the primary cause to its
effects — each sentence names the evidence id it rests on, so a user can
inspect exactly why Atlas reached the conclusion. Also home to the JSON /
markdown / brief / incident renderers of the root-cause report.
"""

from __future__ import annotations

import json

from .graph import CausalGraph
from .models import EvidenceItem, Hypothesis, RootCauseReport


def build_reasoning(
    hypothesis: Hypothesis,
    anchor: EvidenceItem,
    evidence_by_id: dict[str, EvidenceItem],
    graph: CausalGraph,
) -> tuple[str, ...]:
    """Ordered causal sentences, each referencing its evidence id."""

    lines: list[str] = []
    # Start the chain at the earliest cause: the first supporting evidence
    # with the lowest causal rank, else the anchor itself.
    roots = [
        evidence_by_id[evidence_id]
        for evidence_id in hypothesis.supporting
        if evidence_id in evidence_by_id
    ]
    root = min(
        roots or [anchor],
        key=lambda item: (item.causal_rank, item.evidence_id),
    )
    for evidence_id in graph.chain_from(root.evidence_id):
        item = evidence_by_id.get(evidence_id)
        if item is None:
            continue
        lines.append(f"{item.description} [{item.evidence_id}]")
    if not lines:
        lines.append(f"{anchor.description} [{anchor.evidence_id}]")
    if hypothesis.contradicting:
        lines.append(
            "Weighed against: "
            + ", ".join(
                evidence_by_id[eid].description
                for eid in hypothesis.contradicting
                if eid in evidence_by_id
            )
        )
    lines.append(
        f"Conclusion: {hypothesis.statement} "
        f"(confidence {hypothesis.band}, {hypothesis.confidence_percent}%)"
    )
    return tuple(lines)


# -- renderers ---------------------------------------------------------------


def render_root_cause_json(report: RootCauseReport) -> str:
    return (
        json.dumps(
            report.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def render_root_cause_markdown(report: RootCauseReport) -> str:
    lines = [
        "# Atlas Root Cause Analysis",
        "",
        f"- Generated: {report.generated_at}",
        f"- Problems analyzed: {len(report.analyses)}",
        f"- Note: {report.ordering_note}",
        "",
    ]
    if not report.analyses:
        lines.append("Nothing needed a root-cause explanation this run.")
        return "\n".join(lines) + "\n"
    lines.extend(("## Event Timeline", ""))
    for event in report.timeline:
        lines.append(
            f"- {event.at} · {event.category}: {event.description}"
        )
    for analysis in report.analyses:
        primary = analysis.primary
        lines.extend(
            (
                "",
                f"## {analysis.problem}",
                "",
                f"**Likely root cause** ({primary.band} confidence, "
                f"{primary.confidence_percent}%):",
                "",
                primary.statement,
                "",
                "### Reasoning",
                "",
            )
        )
        lines.extend(f"{index}. {line}" for index, line in enumerate(analysis.reasoning, 1))
        lines.extend(("", f"**Suggested next step:** {primary.next_step}", ""))
        if analysis.alternatives:
            lines.append("### Alternatives Considered")
            lines.append("")
            for alternative in analysis.alternatives:
                lines.append(
                    f"- {alternative.statement} ({alternative.band}, "
                    f"{alternative.confidence_percent}%)"
                )
    return "\n".join(lines) + "\n"


def root_cause_brief_section(report: RootCauseReport) -> str:
    """Morning Brief: the most important root cause, when one exists."""

    most = report.most_important
    if most is None:
        return ""
    primary = most.primary
    lines = [
        "",
        "### Most Important Root Cause",
        "",
        f"**{most.problem}** — {primary.statement}",
        f"- Confidence: {primary.band.title()} ({primary.confidence_percent}%)",
        f"- Next step: {primary.next_step}",
        "- Evidence: "
        + (", ".join(primary.supporting) if primary.supporting else "see report"),
    ]
    return "\n".join(lines) + "\n"


def root_cause_incident_section(report_data: dict) -> str:
    """Markdown appended to incident reports (works on the stored JSON)."""

    most = report_data.get("most_important")
    if not isinstance(most, dict):
        return ""
    primary = most.get("primary") or {}
    lines = [
        "",
        "## Root Cause Analysis",
        "",
        f"**Likely cause** ({primary.get('band')} confidence, "
        f"{primary.get('confidence_percent')}%): {primary.get('statement')}",
        "",
        "### Supporting Evidence",
        "",
    ]
    for evidence_id in primary.get("supporting") or ():
        lines.append(f"- {evidence_id}")
    reasoning = most.get("reasoning") or ()
    if reasoning:
        lines.extend(("", "### Timeline / Reasoning", ""))
        lines.extend(f"{index}. {line}" for index, line in enumerate(reasoning, 1))
    lines.extend(
        ("", f"**Recommended next step:** {primary.get('next_step')}", "")
    )
    return "\n".join(lines)
