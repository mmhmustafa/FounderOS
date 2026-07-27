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
    # PR-164 Part 6: the natural-language honest sentence, verbatim.
    TONE_UNKNOWN: "Atlas doesn't currently have enough evidence to "
                  "answer this.",
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
_MAX_FOLLOWUPS = 6

# PR-164: domain-aware layout titles. The hierarchy is identical for
# every domain — only the summary heading speaks the operator's domain,
# because a routing question deserves a routing heading.
_DOMAIN_TITLES = {
    "health": "Health summary",
    "routing": "Routing summary",
    "connectivity": "Connectivity summary",
    "configuration": "Configuration summary",
    "policy": "Policy summary",
    "identity": "Identity summary",
    "timeline": "Change summary",
    "inventory": "Inventory summary",
    "discovery": "Discovery summary",
    "maintenance": "Maintenance summary",
    "incident": "Investigation summary",
    "evidence": "Evidence summary",
    "performance": "Performance summary",
    "security": "Security summary",
}
_DEFAULT_TITLE = "Executive summary"

# PR-164: operational-check naming. Each engine step is shown under the
# operational check it performed; the raw step stays attached so the
# name never replaces the truth. Matched by substring on the engine's
# OWN step wording; an unmatched step keeps its raw text as the label —
# nothing is invented.
_CHECK_NAMES = (
    ("enterprise knowledge graph", "Enterprise Graph"),
    ("discovery completeness", "Discovery Coverage & Freshness"),
    ("reading the enterprise graph", "Enterprise Graph"),
    ("change report", "Change Report"),
    ("discovery history", "Discovery History"),
    ("searching the enterprise", "Evidence Index"),
    ("connectivity investigation", "Connectivity Classification"),
    ("path investigation", "Path Walk (hop by hop)"),
    ("discovery failures", "Discovery Failure Check"),
    ("change prediction", "Impact Classification"),
    ("prediction for", "Impact Prediction"),
    ("resolving interface", "Interface Resolution"),
    ("maintenance plans", "Maintenance Plans"),
    ("recent investigation", "Investigation History"),
    ("classifying the question", "Intent Classification"),
)


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


def _checked(steps: list) -> list[dict[str, str]]:
    """Each engine step under its operational-check name (PR-164).

    Matching reads the engine's own wording; a step no name claims
    keeps its raw text as the label — the naming layer never invents
    a check that was not performed."""

    checked = []
    for step in steps:
        raw = _clean_text(step)
        folded = raw.casefold()
        label = next(
            (name for marker, name in _CHECK_NAMES if marker in folded),
            raw,
        )
        checked.append({"label": label, "step": raw})
    return checked


def _actions(
    response: Mapping[str, Any], oi: Mapping[str, Any]
) -> list[dict[str, Any]]:
    intent = _clean_text(response.get("intent"))
    why = _WHY_BY_INTENT.get(intent, _WHY_DEFAULT)
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(label: str, href: str, item_why: str, primary: bool) -> None:
        # Dedupe by href AND label: the engine's primary action and an
        # intent workflow often name the same destination with different
        # query strings ("/predict?scope=all" vs "/predict") — one
        # "Open Predict" button is the truth, two are noise.
        if not label or not href:
            return
        keys = {href.split("?")[0], label.casefold()}
        if keys & seen:
            return
        seen.update(keys)
        actions.append({"label": label, "href": href,
                        "why": item_why, "primary": primary})

    next_action = response.get("next_action") or {}
    add(_clean_text(next_action.get("label")),
        _clean_text(next_action.get("href")), why, True)
    # The intent's declared workflows and recommendations — each with
    # the WHY it registered (PR-164: context-aware recommendations).
    for item in list(oi.get("workflows") or ()) + list(
        oi.get("recommendations") or ()
    ):
        add(_clean_text((item or {}).get("label")),
            _clean_text((item or {}).get("href")),
            _clean_text((item or {}).get("why"))
            or "A workflow registered for this operational intent.",
            False)
    for item in response.get("followups") or ():
        add(_clean_text((item or {}).get("label")),
            _clean_text((item or {}).get("href")),
            "A related workflow for this answer's evidence.", False)
    return actions


def _merged_followups(
    response: Mapping[str, Any], oi: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The engine's follow-up questions plus the intent's seeds — the
    engine's own (answer-specific) first, deduplicated, capped."""

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(response.get("followups") or ()) + list(
        oi.get("followups") or ()
    ):
        question = _clean_text((item or {}).get("question"))
        label = _clean_text((item or {}).get("label")) or question
        if not question:
            continue
        key = question.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append({"label": label, "question": question})
        if len(merged) >= _MAX_FOLLOWUPS:
            break
    return merged


def _merged_limitations(
    response: Mapping[str, Any], oi: Mapping[str, Any]
) -> list[str]:
    """The answer's own unknowns plus the INTENT's declared standing
    limitations (e.g. "no application-performance telemetry"), stated
    rather than silently omitted. Deduplicated, order preserved."""

    merged: list[str] = []
    seen: set[str] = set()
    for item in list(response.get("unknowns") or ()) + list(
        oi.get("limitations") or ()
    ):
        text = _clean_text(item)
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            merged.append(text)
    return merged


def _intent_display(oi: Mapping[str, Any]) -> dict[str, Any] | None:
    name = _clean_text(oi.get("name"))
    if not name:
        return None
    return {
        "name": name,
        "confidence": _clean_text(oi.get("routing_confidence")) or "Unknown",
        "why": [_clean_text(item) for item in oi.get("why") or () if item],
        "escalated": bool(oi.get("escalated")),
    }


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
    oi = response.get("operational_intent") or {}
    if not isinstance(oi, Mapping):
        oi = {}
    return {
        "verdict": _verdict(summary, confidence),
        "summary_title": _DOMAIN_TITLES.get(
            _clean_text(oi.get("domain")), _DEFAULT_TITLE
        ),
        "summary_bullets": _summary_bullets(summary),
        "findings": list(response.get("evidence") or ()),
        "checked": _checked(list(response.get("steps") or ())),
        "reasoning": _reasoning(response),
        "intent": _intent_display(oi),
        "confidence": {
            "level": confidence,
            "meter": _CONFIDENCE_METER.get(confidence, 0),
            "css": _CONFIDENCE_CSS.get(confidence, "unknown"),
        },
        "freshness": dict(freshness) if freshness else None,
        "limitations": _merged_limitations(response, oi),
        "actions": _actions(response, oi),
        "followup_questions": _merged_followups(response, oi),
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
