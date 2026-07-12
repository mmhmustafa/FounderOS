"""MISSION view-model assembly: orchestration, never business logic.

MISSION is the operational workspace — the answer to "what are you
trying to do?" rather than "which module do you need?". Everything here
READS artifacts the existing engines already produced (enterprise graph
contributions, discovery history, compass plans, prediction and
investigation reports, change summaries) and shapes them for one calm
page. No engine logic lives here; the engines remain authoritative.

Today's Recommendations are deterministic: each one exists only because
specific evidence exists (a stale contribution, a failed discovery, an
unanalysed plan, a low-confidence prediction, an active operational
issue) and each cites that evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


STALE_AFTER_HOURS = 24


def describe_age(observed_at: str | None, now: str) -> str | None:
    """Human wording for evidence age — deterministic from timestamps."""

    if not observed_at:
        return None
    try:
        observed = datetime.fromisoformat(observed_at)
        reference = datetime.fromisoformat(now)
    except ValueError:
        return None
    hours = int((reference - observed).total_seconds() // 3600)
    if hours < 1:
        return "under an hour old"
    if hours < 48:
        return f"{hours} hour(s) old"
    return f"{hours // 24} day(s) old"


def build_recommendations(
    *,
    contributions: list[dict],
    draft_plan_count: int,
    discovery_failures: list[dict],
    predictions: list[dict],
    active_issues: list[dict],
    has_any_data: bool,
    now: str,
) -> list[dict[str, Any]]:
    """Today's Recommendations — every entry cites its evidence.

    Deterministic order: missing data, then failures, then staleness,
    then unreviewed plans, then operational issues, then low-confidence
    predictions.
    """

    recommendations: list[dict[str, Any]] = []
    if not has_any_data:
        recommendations.append(
            {
                "text": "No discovery has run yet — Atlas has no evidence "
                "to reason about.",
                "action": "Run Discovery",
                "href": "/discovery",
                "evidence": "no topology snapshot exists in any scope",
            }
        )
        return recommendations
    for failure in discovery_failures:
        recommendations.append(
            {
                "text": (
                    f"The last discovery of {failure['network']} could not "
                    f"reach {failure['count']} host(s) — review credentials "
                    "and reachability."
                ),
                "action": "Open History",
                "href": f"/history?scope={failure['scope_id']}",
                "evidence": (
                    f"discovery run {failure['run_id']} recorded "
                    f"{failure['count']} failure(s)"
                ),
            }
        )
    for contribution in contributions:
        if contribution.get("fresh") is False:
            age = describe_age(contribution.get("observed_at"), now)
            recommendations.append(
                {
                    "text": (
                        f"{contribution['profile_name']}'s discovery evidence "
                        f"is {age or 'stale'} — run discovery to refresh the "
                        "enterprise graph."
                    ),
                    "action": "Run Discovery",
                    "href": "/discovery",
                    "evidence": (
                        f"last observed {contribution.get('observed_at') or 'never'}"
                    ),
                }
            )
    if draft_plan_count:
        recommendations.append(
            {
                "text": (
                    f"{draft_plan_count} maintenance plan(s) have not been "
                    "analysed yet — Compass can recommend a safer order."
                ),
                "action": "Open Compass",
                "href": "/compass",
                "evidence": f"{draft_plan_count} plan(s) in draft status",
            }
        )
    for issue in active_issues:
        recommendations.append(
            {
                "text": (
                    f"{issue['network']} has {issue['count']} active "
                    "operational issue(s) — investigate before they bite."
                ),
                "action": "Review Changes",
                "href": f"/changes?scope={issue['scope_id']}",
                "evidence": (
                    f"state change report: {issue['count']} active issue(s)"
                ),
            }
        )
    for prediction in predictions:
        band = str(prediction.get("confidence_band") or "").casefold()
        if band in ("medium", "low"):
            recommendations.append(
                {
                    "text": (
                        f"The latest prediction for {prediction['subject']} "
                        f"has {band} confidence — review its evidence before "
                        "acting on it."
                    ),
                    "action": "Review Prediction",
                    "href": prediction["href"],
                    "evidence": (
                        f"prediction confidence {prediction.get('confidence_percent')}%"
                    ),
                }
            )
    return recommendations


def merge_recent(
    collections: list[list[dict]], *, key: str = "generated_at", limit: int = 6
) -> list[dict]:
    """Newest-first merge of already-shaped activity rows."""

    merged = [item for collection in collections for item in collection]
    merged.sort(key=lambda item: str(item.get(key) or ""), reverse=True)
    return merged[:limit]


def shape_investigations(
    entries: list[dict], *, scope_id: str, network: str, limit: int = 3
) -> list[dict]:
    """Path-investigation history rows shaped for the MISSION card."""

    shaped: list[dict] = []
    for entry in entries[:limit]:
        if not isinstance(entry, dict):
            continue
        shaped.append(
            {
                "title": f"{entry.get('source')} → {entry.get('destination')}",
                "status": str(entry.get("status") or "unknown"),
                "network": network,
                "generated_at": entry.get("generated_at"),
                "href": f"/paths?scope={scope_id}",
            }
        )
    return shaped


def shape_prediction(
    report: dict | None, *, scope_id: str, network: str
) -> dict | None:
    """One latest-prediction row for the MISSION card, or None."""

    if not isinstance(report, dict):
        return None
    request = report.get("change_request") or {}
    risk = (report.get("risk") or {}).get("level") or "unknown"
    confidence = report.get("confidence") or {}
    subject = (
        f"{request.get('target_device') or '?'} "
        f"{request.get('target_object') or ''}"
    ).strip()
    return {
        "subject": f"{request.get('change_type') or '?'} {subject}".strip(),
        "risk": risk,
        "network": network,
        "generated_at": report.get("generated_at"),
        "confidence_band": confidence.get("band"),
        "confidence_percent": confidence.get("percent"),
        "href": f"/predict?scope={scope_id}",
    }
