"""CORTEX scoring calculus — the one confidence primitive (REASONING_ENGINE §6).

Atlas already scored confidence eight different ways (root_cause, prediction,
correlation, federation, knowledge, health, risk, identity). Read the formulas
rather than the modules and every one is the same shape::

    score = clamp(base + Σ (named, signed, documented factor), FLOOR, CAP)
    band  = f(score)

This module is that shape, extracted once. It invents nothing: the arithmetic,
the 0.05/0.95 bounds, and the band thresholds are lifted verbatim from
``root_cause/confidence.py`` (the most complete of the eight), so a
characterisation test can prove the primitive reproduces that engine
byte-for-byte before anything is migrated onto it.

Two commitments that make ``High`` mean one thing everywhere:

1. **A rule declares factors; the calculus prices them.** A rule may say "this
   is a direct observation" — it may not decide a direct observation is worth
   +0.15. The weight lives here, once, as contract.
2. **Confidence depends on evidence, never on severity or desirability.** A
   critical finding is not more certain for being critical. ``Severity`` and
   ``Confidence`` are computed from different inputs and never touch.

The 0.95 cap is deliberate and load-bearing: evidence-based reasoning never
claims certainty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# -- bounds (promoted from root_cause/confidence.py:24-25) -------------------

CONFIDENCE_FLOOR = 0.05
CONFIDENCE_CAP = 0.95


# -- bands (promoted from root_cause/confidence.py:19-22, plus ``unknown``) --

BAND_VERY_HIGH = "very-high"
BAND_HIGH = "high"
BAND_MEDIUM = "medium"
BAND_LOW = "low"
BAND_UNKNOWN = "unknown"

# The ordered bands, strongest first — for presentation and comparison.
BANDS = (BAND_VERY_HIGH, BAND_HIGH, BAND_MEDIUM, BAND_LOW, BAND_UNKNOWN)


# -- the standard factor vocabulary (REASONING_ENGINE §6) --------------------
#
# The abstraction over the eight engines' ad-hoc factors. These weights are the
# contract that replaces today's *coincidental* agreement (two engines happen
# to weight a contradiction at -0.15; nothing stopped a third choosing -0.30).
# A rule references a factor by name; it never sees the number.

FACTOR_DIRECT_OBSERVATION = "direct-observation"     # Atlas saw it on the device
FACTOR_CORROBORATION = "corroboration"               # an independent source agrees
FACTOR_CONTRADICTION = "contradiction"               # sources disagree
FACTOR_STALENESS = "staleness"                        # older than the freshness window
FACTOR_MISSING_EVIDENCE = "missing-evidence"          # a gap that bears on the claim
FACTOR_NOT_MODELLED = "not-modelled"                  # a layer Atlas does not represent

# Signed, documented weights. One table, the whole product.
FACTOR_WEIGHTS: dict[str, float] = {
    FACTOR_DIRECT_OBSERVATION: 0.15,
    FACTOR_CORROBORATION: 0.08,     # per corroborating source, diminishing (see below)
    FACTOR_CONTRADICTION: -0.15,
    FACTOR_STALENESS: -0.10,
    FACTOR_MISSING_EVIDENCE: -0.10,
    FACTOR_NOT_MODELLED: -0.10,
}

# Corroboration diminishes: the 4th agreeing source is not worth as much as the
# 1st. Capped exactly as ``root_cause`` caps ``min(supporting, 3)``.
CORROBORATION_CAP = 3


@dataclass(frozen=True)
class ConfidenceFactor:
    """One named, signed, explained contribution to a score.

    ``points`` is the actual signed contribution (already multiplied out, e.g.
    two corroborating sources -> +0.16). ``why`` is human-readable and
    ``evidence_ids`` link the factor to the exact evidence that justified it —
    so ``confidence.factors[]`` answers "why this score?" with no recomputation.
    """

    name: str
    points: float
    why: str
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "points": round(self.points, 4),
            "why": self.why,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ConfidenceFactor":
        return cls(
            name=str(value["name"]),
            points=float(value.get("points") or 0.0),
            why=str(value.get("why") or ""),
            evidence_ids=tuple(value.get("evidence_ids") or ()),
        )


@dataclass(frozen=True)
class Confidence:
    """A score *and* its band, always together (fixes Advisor's lossy ``str``).

    Bands are *derived*, never stored independently — ``band()`` is the one
    truth. ``basis`` is a short prose summary of what drove the score, for the
    common case where a reader wants the gist without walking ``factors``.
    """

    score: float
    band: str
    factors: tuple[ConfidenceFactor, ...] = ()
    basis: str = ""

    @property
    def percent(self) -> int:
        """The score as a whole-number percent, for display (e.g. 85)."""

        return int(round(self.score * 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "percent": self.percent,
            "band": self.band,
            "factors": [f.to_dict() for f in self.factors],
            "basis": self.basis,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Confidence":
        return cls(
            score=float(value.get("score") or 0.0),
            band=str(value.get("band") or BAND_UNKNOWN),
            factors=tuple(
                ConfidenceFactor.from_dict(f) for f in value.get("factors") or ()
            ),
            basis=str(value.get("basis") or ""),
        )

    @classmethod
    def unknown(cls, basis: str = "no evidence available") -> "Confidence":
        """The honest zero: no evidence, so no claim. Band is ``unknown``, not
        ``low`` — absence of evidence is a different state from weak evidence."""

        return cls(score=CONFIDENCE_FLOOR, band=BAND_UNKNOWN, factors=(), basis=basis)


def clamp(value: float) -> float:
    """Bound a raw score to [FLOOR, CAP] and round, exactly as every engine
    does. Rounding matches ``root_cause`` (4 dp) so the two agree bit-for-bit."""

    return max(CONFIDENCE_FLOOR, min(CONFIDENCE_CAP, round(value, 4)))


def band(score: float, *, has_evidence: bool = True) -> str:
    """The single band function. ``has_evidence=False`` yields ``unknown``
    regardless of score — an absent-evidence result must never present as a
    confident one."""

    if not has_evidence:
        return BAND_UNKNOWN
    if score >= 0.90:
        return BAND_VERY_HIGH
    if score >= 0.72:
        return BAND_HIGH
    if score >= 0.50:
        return BAND_MEDIUM
    return BAND_LOW


def score_of(base: float, factors: tuple[ConfidenceFactor, ...]) -> float:
    """``clamp(base + Σ factor.points)`` — the whole calculus, in one line."""

    return clamp(base + sum(f.points for f in factors))


def assess(
    base: float,
    factors: tuple[ConfidenceFactor, ...] | list[ConfidenceFactor],
    *,
    has_evidence: bool = True,
    basis: str = "",
) -> Confidence:
    """Build a full :class:`Confidence` from a base and declared factors.

    This is the engine's entry point (§2.3 step "factors -> clamp(base + Σ)").
    Rules never call it; only the engine does, which is what keeps a rule from
    biasing its own score.
    """

    factors = tuple(factors)
    if not has_evidence:
        return Confidence.unknown(basis or "no evidence available")
    score = score_of(base, factors)
    return Confidence(score=score, band=band(score), factors=factors, basis=basis)


# -- factor constructors (name -> priced ConfidenceFactor) -------------------
#
# The only sanctioned way to make a factor: the caller supplies the *reason*
# and the *evidence*, the weight comes from FACTOR_WEIGHTS. A caller cannot
# smuggle in a custom weight.


def direct_observation(why: str, evidence_ids: tuple[str, ...] = ()) -> ConfidenceFactor:
    return ConfidenceFactor(
        FACTOR_DIRECT_OBSERVATION, FACTOR_WEIGHTS[FACTOR_DIRECT_OBSERVATION], why, evidence_ids
    )


def corroboration(
    sources: int, why: str, evidence_ids: tuple[str, ...] = ()
) -> ConfidenceFactor:
    """``sources`` independent agreeing sources, diminishing and capped, exactly
    as ``root_cause`` caps ``min(supporting, 3)``."""

    counted = max(0, min(sources, CORROBORATION_CAP))
    return ConfidenceFactor(
        FACTOR_CORROBORATION,
        FACTOR_WEIGHTS[FACTOR_CORROBORATION] * counted,
        why,
        evidence_ids,
    )


def contradiction(count: int, why: str, evidence_ids: tuple[str, ...] = ()) -> ConfidenceFactor:
    return ConfidenceFactor(
        FACTOR_CONTRADICTION,
        FACTOR_WEIGHTS[FACTOR_CONTRADICTION] * max(0, count),
        why,
        evidence_ids,
    )


def staleness(why: str, evidence_ids: tuple[str, ...] = ()) -> ConfidenceFactor:
    return ConfidenceFactor(
        FACTOR_STALENESS, FACTOR_WEIGHTS[FACTOR_STALENESS], why, evidence_ids
    )


def missing_evidence(why: str, evidence_ids: tuple[str, ...] = ()) -> ConfidenceFactor:
    return ConfidenceFactor(
        FACTOR_MISSING_EVIDENCE, FACTOR_WEIGHTS[FACTOR_MISSING_EVIDENCE], why, evidence_ids
    )


def not_modelled(why: str, evidence_ids: tuple[str, ...] = ()) -> ConfidenceFactor:
    return ConfidenceFactor(
        FACTOR_NOT_MODELLED, FACTOR_WEIGHTS[FACTOR_NOT_MODELLED], why, evidence_ids
    )
