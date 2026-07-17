"""The canonical Atlas health model.

One reusable definition of operational health, computed once and shown
identically on every page. See model.py for the states and dimensions,
assess.py for how each dimension is calculated from artifacts.
"""

from .model import (
    DIMENSION_DRIFT,
    DIMENSION_EVIDENCE,
    DIMENSION_FRESHNESS,
    DIMENSION_IDENTITY,
    DIMENSION_INCIDENTS,
    DIMENSION_POLICY,
    DIMENSION_REACHABILITY,
    HEALTH_DIMENSIONS,
    HEALTH_STATES,
    STATE_CRITICAL,
    STATE_DEGRADED,
    STATE_HEALTHY,
    STATE_STALE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    HealthAssessment,
    HealthDimension,
    aggregate_assessments,
    overall_state,
)
from .assess import assess_network_health

__all__ = [
    "DIMENSION_DRIFT",
    "DIMENSION_EVIDENCE",
    "DIMENSION_FRESHNESS",
    "DIMENSION_IDENTITY",
    "DIMENSION_INCIDENTS",
    "DIMENSION_POLICY",
    "DIMENSION_REACHABILITY",
    "HEALTH_DIMENSIONS",
    "HEALTH_STATES",
    "STATE_CRITICAL",
    "STATE_DEGRADED",
    "STATE_HEALTHY",
    "STATE_STALE",
    "STATE_UNAVAILABLE",
    "STATE_UNKNOWN",
    "HealthAssessment",
    "HealthDimension",
    "aggregate_assessments",
    "assess_network_health",
    "overall_state",
]
