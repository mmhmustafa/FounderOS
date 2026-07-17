"""CORTEX — the Atlas Enterprise Reasoning Framework (PR-046 design, PR-047 kernel).

A small shared kernel every module reasons *through*, so Atlas has one
definition of confidence, one result schema, and one explanation contract.
This package is the extraction the architecture (``docs/architecture/
REASONING_ENGINE.md``) proposed; PR-047 builds the minimal kernel and proves it
by carrying the greenfield Policy engine (the Phase-5 acceptance gate).

Public surface, in dependency order:

- :mod:`calculus`  — the one confidence primitive ``clamp(base + Σ factors)``
- :mod:`evidence`  — ``Evidence`` / ``EvidenceGap`` (the missing shared type)
- :mod:`result`    — ``ReasoningResult`` / ``ReasoningQuestion`` (one schema)
- :mod:`provider`  — the source-agnostic ``EvidenceProvider`` port
- :mod:`rules`     — ``Rule`` / ``RuleOutcome`` / ``RuleRegistry``
- :mod:`engine`    — ``ReasoningEngine.evaluate(question) -> ReasoningResult``
"""

from __future__ import annotations

from .calculus import (
    BAND_HIGH,
    BAND_LOW,
    BAND_MEDIUM,
    BAND_UNKNOWN,
    BAND_VERY_HIGH,
    BANDS,
    CONFIDENCE_CAP,
    CONFIDENCE_FLOOR,
    Confidence,
    ConfidenceFactor,
    assess,
    band,
    clamp,
    corroboration,
    direct_observation,
    contradiction,
    missing_evidence,
    not_modelled,
    score_of,
    staleness,
)
from .engine import ENGINE_VERSION, ReasoningEngine
from .evidence import (
    GAP_NOT_COLLECTED,
    GAP_NOT_MODELLED,
    GAP_UNREACHABLE,
    GAP_UNSUPPORTED,
    STRENGTH_ABSENT,
    STRENGTH_CIRCUMSTANTIAL,
    STRENGTH_CORROBORATING,
    STRENGTH_DIRECT,
    Evidence,
    EvidenceGap,
    EvidenceProvenance,
)
from .provider import EvidenceProvider
from .result import (
    CONCLUSION_FAIL,
    CONCLUSION_PASS,
    CONCLUSION_UNKNOWN,
    CONCLUSION_WARNING,
    QUESTION_ASSESS,
    QUESTION_COMPLY,
    QUESTION_DIAGNOSE,
    QUESTION_PREDICT,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    Recommendation,
    ReasoningQuestion,
    ReasoningResult,
    ReasoningStep,
    RejectedConclusion,
    ResultProvenance,
    severity_rank,
)
from .rules import (
    FAMILY_COMPLIANCE,
    FAMILY_CONFIGURATION,
    FAMILY_HEALTH,
    FAMILY_INCIDENT,
    FAMILY_PREDICTION,
    FAMILY_RELATIONSHIP,
    FAMILY_RISK,
    FAMILY_TOPOLOGY,
    Rule,
    RuleOutcome,
    RuleRegistry,
)

__all__ = [
    # calculus
    "Confidence", "ConfidenceFactor", "assess", "band", "clamp", "score_of",
    "direct_observation", "corroboration", "contradiction", "staleness",
    "missing_evidence", "not_modelled",
    "CONFIDENCE_FLOOR", "CONFIDENCE_CAP",
    "BAND_VERY_HIGH", "BAND_HIGH", "BAND_MEDIUM", "BAND_LOW", "BAND_UNKNOWN", "BANDS",
    # evidence
    "Evidence", "EvidenceGap", "EvidenceProvenance",
    "STRENGTH_DIRECT", "STRENGTH_CORROBORATING", "STRENGTH_CIRCUMSTANTIAL",
    "STRENGTH_ABSENT",
    "GAP_NOT_COLLECTED", "GAP_UNREACHABLE", "GAP_UNSUPPORTED", "GAP_NOT_MODELLED",
    # result
    "ReasoningResult", "ReasoningQuestion", "ReasoningStep", "RejectedConclusion",
    "Recommendation", "ResultProvenance", "severity_rank",
    "QUESTION_DIAGNOSE", "QUESTION_ASSESS", "QUESTION_PREDICT", "QUESTION_COMPLY",
    "CONCLUSION_PASS", "CONCLUSION_FAIL", "CONCLUSION_WARNING", "CONCLUSION_UNKNOWN",
    "SEVERITY_INFO", "SEVERITY_LOW", "SEVERITY_MEDIUM", "SEVERITY_HIGH",
    "SEVERITY_CRITICAL",
    # provider
    "EvidenceProvider",
    # rules
    "Rule", "RuleOutcome", "RuleRegistry",
    "FAMILY_HEALTH", "FAMILY_RISK", "FAMILY_COMPLIANCE", "FAMILY_PREDICTION",
    "FAMILY_INCIDENT", "FAMILY_TOPOLOGY", "FAMILY_RELATIONSHIP",
    "FAMILY_CONFIGURATION",
    # engine
    "ReasoningEngine", "ENGINE_VERSION",
]
