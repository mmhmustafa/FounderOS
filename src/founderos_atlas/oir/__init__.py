"""Atlas Operational Intent Router (OIR) — codename INTENT (PR-164),
hardened as a platform service by PR-164.1 (FOUNDATION).

Atlas's single workflow-orchestration platform service. It understands
the operator's GOAL — deterministically, from their own words and known
enterprise entities — and routes them into the workflow that serves it,
with the routing confidence and the WHY attached to every decision.

Public interface: :class:`OperationalIntentRouter` (and
:func:`default_router` for the process-wide instance). Consumers —
Advisor today; REST APIs, CLI, automation, mobile, future AI — depend
on that surface, never on internal modules.

Lifecycle: capability registrars (see ``bootstrap``) register
:class:`IntentDefinition` data at startup; the registry validates and
FREEZES; runtime only resolves. Registration after freeze fails
loudly. OIR resolves INTENT; the execution engines perform the work.
"""

from .analytics import (
    ANALYTICS_FILENAME,
    ANALYTICS_SCHEMA_VERSION,
    IntentAnalytics,
)
from .bootstrap import CAPABILITY_REGISTRARS, build_default_registry
from .catalog import (
    ENGINE_CHANGES,
    ENGINE_COMPASS,
    ENGINE_CONTINUE,
    ENGINE_DISCOVERY,
    ENGINE_ENTERPRISE,
    ENGINE_HEALTH,
    ENGINE_INVESTIGATION,
    ENGINE_PATH,
    ENGINE_PREDICTION,
    ENGINE_SEARCH,
    ENGINE_UNKNOWN,
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
    RegistryFrozenError,
    RegistryValidationError,
    Workflow,
)
from .service import OperationalIntentRouter, default_router
from .vocabulary import (
    EVIDENCE_KINDS,
    KNOWN_WORKFLOW_AREAS,
    KNOWN_WORKFLOW_PATHS,
    workflow_path,
)

# DEFAULT_REGISTRY and ENGINE_RULES are deliberately NOT in __all__:
# they are lazy registry-derived views (see __getattr__ below), and
# advertising them would make `import *` build and freeze the whole
# catalog as an import side effect. Reachable by explicit name.
__all__ = [
    "ANALYTICS_FILENAME",
    "ANALYTICS_SCHEMA_VERSION",
    "CAPABILITY_REGISTRARS",
    "ENGINE_CHANGES",
    "ENGINE_COMPASS",
    "ENGINE_CONTINUE",
    "ENGINE_DISCOVERY",
    "ENGINE_ENTERPRISE",
    "ENGINE_HEALTH",
    "ENGINE_INVESTIGATION",
    "ENGINE_PATH",
    "ENGINE_PREDICTION",
    "ENGINE_SEARCH",
    "ENGINE_UNKNOWN",
    "EVIDENCE_KINDS",
    "FollowUpSeed",
    "IntentAnalytics",
    "IntentDefinition",
    "IntentRegistry",
    "IntentRoute",
    "KNOWN_WORKFLOW_AREAS",
    "KNOWN_WORKFLOW_PATHS",
    "OperationalIntentRouter",
    "ROUTE_CONFIDENCE_HIGH",
    "ROUTE_CONFIDENCE_MEDIUM",
    "ROUTE_CONFIDENCE_UNKNOWN",
    "RegistryFrozenError",
    "RegistryValidationError",
    "Workflow",
    "build_default_registry",
    "default_router",
    "detect",
    "engine_rule_match",
    "workflow_path",
]


def __getattr__(name: str):
    # Registry-derived compatibility attributes stay lazy (PEP 562):
    # touching them builds and freezes the default catalog. Cached
    # after first access.
    if name in ("DEFAULT_REGISTRY", "ENGINE_RULES"):
        from . import catalog

        value = getattr(catalog, name)
        globals()[name] = value
        return value
    raise AttributeError(name)


def __dir__():
    return sorted(list(globals()) + ["DEFAULT_REGISTRY", "ENGINE_RULES"])
