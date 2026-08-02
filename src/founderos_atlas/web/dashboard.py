"""Operational summaries: context that supports an answer (PR-169).

Atlas pages that carry a dashboard follow one rule:

    Answer first. Context second. Evidence third.

A dashboard exists to tell an operator, in about three seconds,
whether the estate is in a state they should care about — and then to
get out of the way of whatever they actually came to do. Six equal
cards competing with an investigation is not context, it is a second
page stacked on top of the first.

This module turns the status cards a page already builds into that
compact form:

    readiness      one status word, reused from Atlas's OWN health
                   determination — never recomputed here
    chips          one short label/value per dimension, for scanning
    observations   the supporting ✓ / ⚠ lines, in operator words

**Nothing here decides anything.** Every state is read from the
assessment the health model produced; the only arithmetic is turning a
numerator and denominator Atlas already recorded into a percentage.
When a dimension has no state, this says so rather than guessing —
"not assessed" is a real answer.

It is deliberately page-agnostic: it takes plain card dicts and returns
plain data, so the next page to adopt the standard imports it rather
than reinventing it.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


# Atlas health states -> the operator status words of the Atlas
# Experience Language (PR-168 §4). A RELABELLING of a determination the
# health model already made; the mapping adds no judgement of its own.
#
# "stale" is a Warning rather than "not enough evidence": Atlas can
# still see the estate, it is just seeing an older version of it, and
# that is a developing operational risk the operator should act on.
READINESS = {
    "healthy": ("Healthy", "ok"),
    "degraded": ("Warning", "warning"),
    "stale": ("Warning", "warning"),
    "critical": ("Attention required", "attention"),
    "unavailable": ("Not enough evidence", "unknown"),
    "unknown": ("Not enough evidence", "unknown"),
}
_DEFAULT_READINESS = ("Not enough evidence", "unknown")

# Which mark leads a supporting observation, as an ATLAS ICON NAME —
# the shared SVG set, never emoji, which the icon-system test enforces
# on every primary page. A dimension Atlas could not assess gets a
# neutral dot, not a tick, which would read as "checked and fine".
_MARKS = {
    "ok": "check", "warning": "warning", "attention": "warning",
    "unknown": "dot",
}

_GOOD_STATES = frozenset({"healthy"})
_UNASSESSED_STATES = frozenset({"unknown", "unavailable", None, ""})


def _text(value: Any) -> str:
    return str(value or "").strip()


def readiness_for(state: Any) -> tuple[str, str]:
    """``(status word, tone)`` for one Atlas health state."""

    return READINESS.get(_text(state).casefold(), _DEFAULT_READINESS)


def percentage(numerator: Any, denominator: Any) -> str:
    """``"53%"`` from a ratio Atlas already recorded, or ``""``.

    Arithmetic on the health model's own numbers — it introduces no
    fact that was not already there. A zero or missing denominator
    yields nothing rather than a divide-by-zero or a fake 0%.
    """

    try:
        top, bottom = int(numerator), int(denominator)
    except (TypeError, ValueError):
        return ""
    if bottom <= 0:
        return ""
    return f"{round(100 * top / bottom)}%"


def summarise(
    cards: Iterable[Mapping[str, Any]], *, updated: str = "",
) -> dict[str, Any]:
    """One operational summary from a page's status cards.

    ``cards`` are the dicts a page already builds: ``title``, ``state``
    (an Atlas health state or ``None``), ``chip`` (a short scannable
    value), ``detail`` (Atlas's own sentence) and ``href``. The first
    card is taken as the overall assessment, which is how every Atlas
    page orders them today.
    """

    rows = [dict(card) for card in cards or ()]
    if not rows:
        return {
            "available": False, "status": _DEFAULT_READINESS[0],
            "tone": _DEFAULT_READINESS[1], "detail": "",
            "show_detail": False, "chips": [], "observations": [],
            "updated": _text(updated), "concerns": 0,
            "unlisted_concern": False,
        }

    overall = rows[0]
    status, tone = readiness_for(overall.get("state"))

    chips: list[dict[str, Any]] = []
    observations: list[dict[str, str]] = []
    for card in rows:
        # The overall card is the READINESS WORD above; repeating it as
        # a chip said the same fact twice, and said it in the health
        # model's vocabulary ("Health · Stale") beside the operator's
        # ("Warning"). One fact, one place, one vocabulary.
        if card is overall:
            continue

        state = _text(card.get("state")).casefold()
        card_status, card_tone = readiness_for(state)
        assessed = state not in _UNASSESSED_STATES and bool(state)
        # NB: not `tone` — that name holds the OVERALL tone, and
        # shadowing it here made the unlisted-concern check read the
        # last chip's tone instead of the estate's.
        chip_tone = card_tone if assessed else "none"
        chips.append({
            "label": _text(card.get("title")),
            "value": _text(card.get("chip")) or "—",
            "state": state,
            "tone": chip_tone,
            # State must reach the operator through more than colour.
            # ``mark`` is a SHAPE (the icon set) and ``status`` is the
            # word — the chip renders the icon and carries the word in
            # its accessible name. A border colour alone left a
            # colour-blind operator, a high-contrast display and a
            # screen reader with no state at all.
            "mark": _MARKS.get(chip_tone, "") if assessed else "",
            "status": card_status if assessed else "",
            "href": _text(card.get("href")),
            # The title attribute keeps Atlas's own sentence reachable
            # on a chip that shows three characters.
            "detail": _text(card.get("detail")),
        })

        if assessed:
            mark_tone = "ok" if state in _GOOD_STATES else card_tone
        else:
            mark_tone = "unknown"
        observations.append({
            "mark": _MARKS.get(mark_tone, "dot"),
            "tone": mark_tone,
            "label": _text(card.get("title")),
            "text": _text(card.get("detail")) or (
                "Atlas has not assessed this." if not assessed else ""
            ),
        })

    # How many dimensions are not clean — lets a collapsed summary say
    # "2 need attention" without the operator opening it.
    concerns = sum(
        1 for item in observations
        if item["tone"] in ("warning", "attention")
    )
    detail = _text(overall.get("detail"))

    # The readiness word is the health model's worst-of over EVERY
    # dimension it assesses — including ones this page gives no card
    # (reachability, evidence coverage, configuration drift). Counting
    # only the cards let the header say "Warning" directly above
    # "nothing flagged", which reads as a bug in Atlas and hides the
    # dimension actually at fault. When that happens, say so: the
    # overall detail names the cause and the page must point at it.
    unlisted = bool(concerns == 0 and tone in ("warning", "attention"))

    # The overall detail is composed from the failing dimension's own
    # summary — prefixed with that dimension's label — so on a carded
    # dimension it repeats the observation a few lines below it. An
    # exact-match check missed that prefix, so compare by containment.
    covered = any(
        item["text"] and item["text"] in detail
        for item in observations
    )
    show_detail = bool(detail) and (unlisted or not covered)

    return {
        "available": True,
        "status": status,
        "tone": tone,
        "detail": detail,
        "show_detail": show_detail,
        "chips": chips,
        "observations": observations,
        "updated": _text(updated) or _text(overall.get("updated")),
        "concerns": concerns,
        "unlisted_concern": unlisted,
    }
