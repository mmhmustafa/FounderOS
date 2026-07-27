"""Present an Advisor answer the way a senior engineer would explain it.

Presentation ONLY (PR-163). This module never computes new conclusions:
it reorganizes what the engine already said — the stored ``to_dict()``
response — into the hierarchy an operator reads naturally: the direct
answer first, then the executive summary, the findings, what was
checked, the reasoning, the evidence, and the limitations. Every rule
here is a deterministic reading of the engine's OWN words; when those
words do not clearly support a verdict, the verdict is neutral rather
than invented.

The functions are tolerant of older stored conversations (missing keys
never raise) because the GUI renders persisted dicts, not live objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# The final answer (verdict)
#
# Markers are matched against the engine's own summary text, casefolded,
# after the negated forms are removed so "no active issues" never reads
# as a problem. High-precision only: a phrase that could describe either
# state stays out of both lists, and the verdict falls back to neutral.
# ---------------------------------------------------------------------------

TONE_OK = "ok"
TONE_ATTENTION = "attention"
TONE_UNKNOWN = "unknown"
TONE_INFO = "info"

_NEGATED_FORMS = (
    "no active issue",
    "0 active issue",
    "no unresolved",
    "no failed",
    "no conflict",
    "not degraded",
    "no warning",
)

_ATTENTION_MARKERS = (
    "active issue",
    "degraded",
    "critical",
    "failed",
    "cannot reach",
    "could not reach",
    "unreachable",
    "unstable",
    "conflict",
    "interfaces down",
)

_OK_MARKERS = (
    "healthy",
    "can reach",
    "no active issues",
    "completed successfully",
    "no changes",
)

_HEADLINES = {
    TONE_OK: "All clear in what Atlas checked.",
    TONE_ATTENTION: "Atlas found concerns that need attention.",
    TONE_UNKNOWN: "Atlas cannot determine this confidently.",
    TONE_INFO: "Here is what the evidence shows.",
}

_ICONS = {
    TONE_OK: "✓",         # check mark
    TONE_ATTENTION: "⚠",  # warning sign
    TONE_UNKNOWN: "?",
    TONE_INFO: "•",       # bullet
}

# Confidence is a 4-value scale; the meter says so honestly — four
# segments, not five stars implying precision the engine never claimed.
_CONFIDENCE_METER = {"High": 4, "Medium": 2, "Low": 1, "Unknown": 0}
_CONFIDENCE_CSS = {
    "High": "pass",
    "Medium": "warning",
    "Low": "failed",
    "Unknown": "unknown",
}

# Why each recommendation is offered — worded per intent, so the button
# explains its own relevance instead of appearing by fiat.
_WHY_BY_INTENT = {
    "health": "This answer summarizes health evidence; the workflow shows "
              "the same evidence in full.",
    "changes": "This answer is grounded in the recorded change history.",
    "discovery": "This answer reports on discovery runs; the workflow "
                 "manages them.",
    "path": "This answer traced a path; the workflow holds the full "
            "investigation.",
    "prediction": "This answer cites a prediction; the workflow shows its "
                  "impact analysis.",
    "compass": "This answer reads from maintenance plans; the workflow "
               "manages them.",
    "continue": "This is the most recent unfinished work Atlas found.",
    "search": "This answer came from the evidence index; the workflow "
              "opens the matching records.",
    "enterprise": "This answer summarizes the enterprise graph; the "
                  "workflow shows it whole.",
    "investigation": "This answer references an investigation; the "
                     "workflow reopens it.",
}
_WHY_DEFAULT = "The workflow this answer's evidence comes from."

_MAX_SUMMARY_BULLETS = 6


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _verdict(summary: str, confidence: str) -> dict[str, str]:
    if confidence == "Unknown":
        tone = TONE_UNKNOWN
    else:
        text = summary.casefold()
        for form in _NEGATED_FORMS:
            text = text.replace(form, "")
        if any(marker in text for marker in _ATTENTION_MARKERS):
            tone = TONE_ATTENTION
        elif any(marker in summary.casefold() for marker in _OK_MARKERS):
            tone = TONE_OK
        else:
            tone = TONE_INFO
    return {"tone": tone, "icon": _ICONS[tone], "headline": _HEADLINES[tone]}


def _summary_bullets(summary: str) -> list[str]:
    """The engine's summary, split into scannable sentences (max 6)."""

    parts = [part.strip() for part in summary.split(". ") if part.strip()]
    bullets = []
    for part in parts:
        bullets.append(part if part.endswith(".") else part + ".")
    if len(bullets) > _MAX_SUMMARY_BULLETS:
        kept = bullets[: _MAX_SUMMARY_BULLETS - 1]
        kept.append(
            f"…and {len(bullets) - (_MAX_SUMMARY_BULLETS - 1)} further "
            "detail(s) in the findings below."
        )
        return kept
    return bullets


def _reasoning(response: Mapping[str, Any]) -> str:
    """Deterministic explanation composed from what the engine recorded."""

    steps = list(response.get("steps") or ())
    evidence = list(response.get("evidence") or ())
    unknowns = list(response.get("unknowns") or ())
    basis = _clean_text(response.get("confidence_basis"))
    parts: list[str] = []
    if steps:
        parts.append(
            f"Atlas ran {len(steps)} check(s) against the existing engines"
        )
    if evidence:
        parts.append(
            f"grounded the answer in {len(evidence)} cited artifact(s)"
        )
    lead = " and ".join(parts)
    sentences: list[str] = []
    if lead:
        sentences.append(lead[0].upper() + lead[1:] + ".")
    if basis:
        text = basis if basis.endswith(".") else basis + "."
        sentences.append(text[0].upper() + text[1:])
    if unknowns:
        sentences.append(
            f"{len(unknowns)} limitation(s) are stated below rather than "
            "silently ignored."
        )
    return " ".join(sentences)


def _actions(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    intent = _clean_text(response.get("intent"))
    why = _WHY_BY_INTENT.get(intent, _WHY_DEFAULT)
    actions: list[dict[str, Any]] = []
    next_action = response.get("next_action") or {}
    label = _clean_text(next_action.get("label"))
    href = _clean_text(next_action.get("href"))
    if label and href:
        actions.append(
            {"label": label, "href": href, "why": why, "primary": True}
        )
    for item in response.get("followups") or ():
        item_href = _clean_text((item or {}).get("href"))
        item_label = _clean_text((item or {}).get("label"))
        if item_href and item_label:
            actions.append({
                "label": item_label,
                "href": item_href,
                "why": "A related workflow for this answer's evidence.",
                "primary": False,
            })
    return actions


def present_answer(
    response: Mapping[str, Any] | None,
    *,
    freshness: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The display structure for one stored Advisor answer.

    ``freshness`` is the CURRENT scope's discovery freshness computed by
    the caller (last discovery timestamp + stale flag). It is displayed
    beside — never blended into — the answer's own confidence: an old
    discovery makes evidence stale, it does not make the reasoning
    weaker, and the two must not be conflated.
    """

    if not response:
        return None
    summary = _clean_text(response.get("summary"))
    confidence = _clean_text(response.get("confidence")) or "Unknown"
    followup_questions = [
        item for item in (response.get("followups") or ())
        if _clean_text((item or {}).get("question"))
    ]
    return {
        "verdict": _verdict(summary, confidence),
        "summary_bullets": _summary_bullets(summary),
        "findings": list(response.get("evidence") or ()),
        "checked": list(response.get("steps") or ()),
        "reasoning": _reasoning(response),
        "confidence": {
            "level": confidence,
            "meter": _CONFIDENCE_METER.get(confidence, 0),
            "css": _CONFIDENCE_CSS.get(confidence, "unknown"),
        },
        "freshness": dict(freshness) if freshness else None,
        "limitations": list(response.get("unknowns") or ()),
        "actions": _actions(response),
        "followup_questions": followup_questions,
    }


# ---------------------------------------------------------------------------
# Conversation history grouping
# ---------------------------------------------------------------------------

def _parse_when(value: Any) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def group_conversations(
    entries: list[Mapping[str, Any]],
    *,
    now: str,
) -> list[dict[str, Any]]:
    """Stored conversations in display groups, keeping TRUE indices.

    Pinned first, then Today / Yesterday / Last week / Older. Every item
    carries its original stored index because rename/delete/export/pin
    all address conversations positionally — the display order must
    never change which entry a button acts on.
    """

    reference = _parse_when(now) or datetime.now(timezone.utc)
    groups: dict[str, list[dict[str, Any]]] = {
        "Pinned": [], "Today": [], "Yesterday": [], "Last week": [],
        "Older": [],
    }
    for index, entry in enumerate(entries):
        item = {"index": index, "entry": entry}
        if entry.get("pinned"):
            groups["Pinned"].append(item)
            continue
        asked = _parse_when(entry.get("asked_at"))
        if asked is None:
            groups["Older"].append(item)
            continue
        days = (reference.date() - asked.date()).days
        if days <= 0:
            groups["Today"].append(item)
        elif days == 1:
            groups["Yesterday"].append(item)
        elif days <= 7:
            groups["Last week"].append(item)
        else:
            groups["Older"].append(item)
    return [
        {"title": title, "items": items}
        for title, items in groups.items()
        if items
    ]
