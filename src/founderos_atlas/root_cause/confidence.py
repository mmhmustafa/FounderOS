"""Confidence calculation. Documented arithmetic, banded, never 100%.

    confidence = base(rule)
               + 0.08 x min(supporting evidence, 3)
               - 0.15 x contradicting evidence
               + 0.15 when the exact interface appears in the causal evidence
               + 0.05 when history shows the same behavior recurring
               - 0.10 when the evidence is stale
    clamped to [0.05, 0.95]

Bands: >= 0.90 very-high · >= 0.72 high · >= 0.50 medium · < 0.50 low.
The 0.95 cap is deliberate: evidence-based reasoning never claims
certainty.
"""

from __future__ import annotations


BAND_VERY_HIGH = "very-high"
BAND_HIGH = "high"
BAND_MEDIUM = "medium"
BAND_LOW = "low"

CONFIDENCE_FLOOR = 0.05
CONFIDENCE_CAP = 0.95


def calculate(
    base: float,
    *,
    supporting: int = 0,
    contradicting: int = 0,
    interface_match: bool = False,
    recurring: bool = False,
    stale: bool = False,
) -> float:
    score = (
        base
        + 0.08 * min(supporting, 3)
        - 0.15 * contradicting
        + (0.15 if interface_match else 0.0)
        + (0.05 if recurring else 0.0)
        - (0.10 if stale else 0.0)
    )
    return max(CONFIDENCE_FLOOR, min(CONFIDENCE_CAP, round(score, 4)))


def band(confidence: float) -> str:
    if confidence >= 0.90:
        return BAND_VERY_HIGH
    if confidence >= 0.72:
        return BAND_HIGH
    if confidence >= 0.50:
        return BAND_MEDIUM
    return BAND_LOW
