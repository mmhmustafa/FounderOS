"""Atlas Operational Intent Router (OIR) — codename INTENT (PR-164).

Atlas's single workflow-orchestration platform service. It understands
the operator's GOAL — deterministically, from their own words and known
enterprise entities — and routes them into the workflow that serves it,
with the routing confidence and the WHY attached to every decision.

Consumers today: the Advisor (its ``classify``/``route`` delegate
here). Governance: any future module that wants routing registers an
:class:`IntentDefinition` in the catalog — it must NOT implement its
own detection, and must NOT modify Advisor.
"""

from .analytics import ANALYTICS_FILENAME, IntentAnalytics
from .catalog import (
    DEFAULT_REGISTRY,
    ENGINE_CHANGES,
    ENGINE_COMPASS,
    ENGINE_CONTINUE,
    ENGINE_DISCOVERY,
    ENGINE_ENTERPRISE,
    ENGINE_HEALTH,
    ENGINE_INVESTIGATION,
    ENGINE_PATH,
    ENGINE_PREDICTION,
    ENGINE_RULES,
    ENGINE_SEARCH,
    ENGINE_UNKNOWN,
    build_default_registry,
    engine_rule_match,
)
from .detection import (
    ROUTE_CONFIDENCE_HIGH,
    ROUTE_CONFIDENCE_MEDIUM,
    ROUTE_CONFIDENCE_UNKNOWN,
    IntentRoute,
    detect,
)
from .registry import (
    FollowUpSeed,
    IntentDefinition,
    IntentRegistry,
    Workflow,
)

__all__ = [
    "ANALYTICS_FILENAME",
    "DEFAULT_REGISTRY",
    "ENGINE_CHANGES",
    "ENGINE_COMPASS",
    "ENGINE_CONTINUE",
    "ENGINE_DISCOVERY",
    "ENGINE_ENTERPRISE",
    "ENGINE_HEALTH",
    "ENGINE_INVESTIGATION",
    "ENGINE_PATH",
    "ENGINE_PREDICTION",
    "ENGINE_RULES",
    "ENGINE_SEARCH",
    "ENGINE_UNKNOWN",
    "FollowUpSeed",
    "IntentAnalytics",
    "IntentDefinition",
    "IntentRegistry",
    "IntentRoute",
    "ROUTE_CONFIDENCE_HIGH",
    "ROUTE_CONFIDENCE_MEDIUM",
    "ROUTE_CONFIDENCE_UNKNOWN",
    "Workflow",
    "build_default_registry",
    "detect",
    "engine_rule_match",
]
