"""Prediction confidence: documented arithmetic, banded, never 100%.

    confidence = 0.50 base
               + 0.15 topology evidence present
               + 0.10 discovery fresh (not stale)
               + 0.10 configuration captured for the target device
               + 0.05 historical observations available
               + 0.05 change type has a registered evaluator
               - 0.10 x unknown dependency layers (services/apps not modeled)
               - 0.15 x contradicting evidence
    clamped to [0.05, 0.95]

Bands reuse the root-cause vocabulary (very-high / high / medium / low) so
every Atlas engine speaks the same confidence language.
"""

from __future__ import annotations

from founderos_atlas.root_cause.confidence import band as confidence_band

from .models import ConfidenceAssessment, ConfidenceFactor


CONFIDENCE_FLOOR = 0.05
CONFIDENCE_CAP = 0.95


def assess_confidence(
    *,
    topology_available: bool,
    fresh: bool,
    configuration_captured: bool,
    history_available: bool,
    evaluator_registered: bool,
    unknown_layers: int = 0,
    contradictions: int = 0,
) -> ConfidenceAssessment:
    factors = [ConfidenceFactor("base", 0.50, "evidence-based prediction baseline")]

    def add(name: str, points: float, detail: str, condition: bool) -> None:
        if condition:
            factors.append(ConfidenceFactor(name, points, detail))

    add("topology-evidence", 0.15, "current topology snapshot available", topology_available)
    add("fresh-discovery", 0.10, "discovery evidence is fresh", fresh)
    add(
        "configuration-captured", 0.10,
        "the target device's configuration is captured", configuration_captured,
    )
    add("historical-observations", 0.05, "history records available", history_available)
    add(
        "modeled-change-type", 0.05,
        "this change type has a registered evaluator", evaluator_registered,
    )
    if unknown_layers:
        factors.append(
            ConfidenceFactor(
                "unknown-dependency-layers",
                -0.10 * unknown_layers,
                f"{unknown_layers} dependency layer(s) not yet modeled "
                "(services, applications, ...)",
            )
        )
    if contradictions:
        factors.append(
            ConfidenceFactor(
                "contradicting-evidence",
                -0.15 * contradictions,
                f"{contradictions} contradicting observation(s)",
            )
        )
    score = max(
        CONFIDENCE_FLOOR,
        min(CONFIDENCE_CAP, round(sum(factor.points for factor in factors), 4)),
    )
    return ConfidenceAssessment(
        score=score, band=confidence_band(score), factors=tuple(factors)
    )
