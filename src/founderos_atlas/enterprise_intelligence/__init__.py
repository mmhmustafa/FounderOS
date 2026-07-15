"""Enterprise Intelligence Engine (PR-034).

Atlas stops reporting raw events and starts answering the questions a
network manager actually asks: *What matters? What changed? Should I care?
What should I do first?* The engine consumes the deterministic artifacts
every discovery already produces — topology, operational state,
configuration changes, discovery history, incidents, provenance — and
computes:

- a calculated, fully explained **health score** (every point accounted
  for by a named factor with evidence);
- **findings** with severity, risk, confidence, and urgency;
- a **priority queue** ("top things you should care about") ranked by
  urgency, severity, blast radius, recurrence, and confidence;
- **recommendations** with likely cause and a concrete next step;
- **trends** across discoveries (health trajectory, configuration churn,
  recurring instability, topology stability);
- Morning Brief v2 and dashboard payloads.

Everything is deterministic and rule-based — no AI, no randomness, no
wall-clock reads outside the injected timestamps. The JSON report is
designed so a future AI layer can consume summary, evidence, risk,
confidence, and recommendations without any recomputation.
"""

from .engine import (
    IntelligenceEvidence,
    build_intelligence,
    is_auth_failure,
    load_evidence,
)
from .health import score_health
from .models import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    TREND_DECLINING,
    TREND_IMPROVING,
    TREND_STABLE,
    EnterpriseIntelligence,
    Finding,
    HealthScore,
    Recommendation,
    ScoreFactor,
    TrendSignal,
)
from .priority import prioritize
from .recommendations import recommend
from .risk import detect_findings
from .summary import (
    intelligence_brief_section,
    render_intelligence_json,
    render_intelligence_markdown,
)
from .trend import detect_trends

__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "EnterpriseIntelligence",
    "Finding",
    "HealthScore",
    "IntelligenceEvidence",
    "Recommendation",
    "is_auth_failure",
    "ScoreFactor",
    "TREND_DECLINING",
    "TREND_IMPROVING",
    "TREND_STABLE",
    "TrendSignal",
    "build_intelligence",
    "detect_findings",
    "detect_trends",
    "intelligence_brief_section",
    "load_evidence",
    "prioritize",
    "recommend",
    "render_intelligence_json",
    "render_intelligence_markdown",
    "score_health",
]
