"""How Atlas *presents* confidence (PR-047A FOCUS, decision 4).

The reasoning layer computes confidence for every conclusion, and it is right to.
The product should not therefore print it on every row. On the live lab, 108 of
108 policy results scored "high, 85%" — a number identical on every line carries
no information while taxing attention on every line.

So this module answers one question: **does this confidence change what the
reader should do?**

- **Very high / high** — Atlas is confident and its reasoning is deterministic.
  Saying so adds nothing; the conclusion already speaks. Show **nothing**.
- **Medium / low** — the reader should weigh the conclusion differently. Say so.
- **Unknown** — Atlas could not judge. This is the most important thing on the
  row, because it means *act on your own knowledge, not on this*.
- **Conflicting** — sources disagree. Always surface.

This is presentation only. Nothing here changes a score, a band, or a
conclusion — the reasoning kernel is untouched, and the full confidence
breakdown (score, band, factors) remains available wherever a reader opens a
result's detail. We are choosing what to put in front of them, not what to keep.
"""

from __future__ import annotations

from typing import Any


# Bands the reader needs to act on. Anything stronger is left unsaid.
_NOTEWORTHY = {
    "unknown": {
        "label": "Unknown",
        "tone": "unknown",
        "why": "Atlas could not judge this from the evidence it has.",
    },
    "low": {
        "label": "Low confidence",
        "tone": "failed",
        "why": "Weak evidence — treat this as a lead, not a finding.",
    },
    "medium": {
        "label": "Medium confidence",
        "tone": "warning",
        "why": "Partial evidence — worth checking before acting.",
    },
}


def confidence_display(
    confidence: dict[str, Any] | None, *, conflicting: bool = False
) -> dict[str, Any] | None:
    """How to show this confidence in a list, or ``None`` to show nothing.

    ``confidence`` is a ``Confidence.to_dict()``. ``conflicting`` is True when
    the result carries conflicting evidence, which always deserves saying
    regardless of score.

    Returns ``{label, tone, why, percent, band}`` or ``None``. ``None`` is the
    common, healthy case: a strong deterministic conclusion that should be read
    as a plain fact.
    """

    if not confidence:
        return None

    band = str(confidence.get("band") or "")

    if conflicting:
        return {
            "label": "Conflicting evidence",
            "tone": "warning",
            "why": "Independent sources disagree — read the evidence before acting.",
            "percent": confidence.get("percent"),
            "band": band,
        }

    noteworthy = _NOTEWORTHY.get(band)
    if noteworthy is None:
        # very-high / high: confident and deterministic. Say nothing.
        return None

    return {
        "label": noteworthy["label"],
        "tone": noteworthy["tone"],
        "why": confidence.get("basis") or noteworthy["why"],
        # An "Unknown" has no meaningful score to quote — quoting the floor
        # (5%) would imply a measurement where there was none.
        "percent": None if band == "unknown" else confidence.get("percent"),
        "band": band,
    }


def confidence_detail(confidence: dict[str, Any] | None) -> str:
    """The one-line full disclosure, for a result's expanded detail — where a
    reader has explicitly asked for the reasoning and every number is welcome."""

    if not confidence:
        return "—"
    band = confidence.get("band") or "unknown"
    if band == "unknown":
        basis = confidence.get("basis") or "no evidence available"
        return f"Unknown — {basis}"
    percent = confidence.get("percent")
    basis = confidence.get("basis")
    text = f"{band} ({percent}%)" if percent is not None else str(band)
    return f"{text} — {basis}" if basis else text
