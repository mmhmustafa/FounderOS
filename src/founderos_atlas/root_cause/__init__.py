"""Evidence-based Root Cause Analysis engine (PR-035).

Atlas explains *why* — deterministically. Evidence from configuration,
operational state, topology, discovery, history, and incidents is
normalized into timestamped, causally-ranked items; a causal graph links
related observations (never unrelated ones); rule-based hypotheses are
generated with supporting AND contradicting evidence; confidence is a
documented calculation banded very-high/high/medium/low and capped below
100%; and every conclusion is rendered as an inspectable reasoning chain
that references its evidence.

No AI, no LLM, no guessing: the same evidence always yields the same
explanation, byte for byte.
"""

from .confidence import BAND_HIGH, BAND_LOW, BAND_MEDIUM, BAND_VERY_HIGH
from .engine import analyze, analyze_record
from .evidence import build_evidence
from .explanation import (
    render_root_cause_json,
    render_root_cause_markdown,
    root_cause_brief_section,
    root_cause_incident_section,
)
from .models import (
    EvidenceItem,
    Hypothesis,
    RootCauseAnalysis,
    RootCauseReport,
    TimelineEvent,
)
from .timeline import build_timeline

__all__ = [
    "BAND_HIGH",
    "BAND_LOW",
    "BAND_MEDIUM",
    "BAND_VERY_HIGH",
    "EvidenceItem",
    "Hypothesis",
    "RootCauseAnalysis",
    "RootCauseReport",
    "TimelineEvent",
    "analyze",
    "analyze_record",
    "build_evidence",
    "build_timeline",
    "render_root_cause_json",
    "render_root_cause_markdown",
    "root_cause_brief_section",
    "root_cause_incident_section",
]
