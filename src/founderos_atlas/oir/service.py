"""The OIR's stable public service interface (PR-164.1, Part 6).

Consumers — Advisor today; REST APIs, CLI, automation, mobile, or a
future AI layer tomorrow — depend on :class:`OperationalIntentRouter`
and nothing else. Internal modules (registry, detection, bootstrap,
validation) may evolve; this surface stays stable.

Execution model (Part 7): OIR performs INTENT RESOLUTION — what is the
operator trying to accomplish. The route names an execution engine;
EXECUTION — how Atlas performs the work — belongs to the engines
(today: the Advisor engine's handlers). OIR never executes anything.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Iterable

from .bootstrap import CAPABILITY_REGISTRARS, build_default_registry
from .detection import IntentRoute, detect
from .registry import IntentDefinition, IntentRegistry
from .vocabulary import workflow_path


class OperationalIntentRouter:
    """The one router. Constructing it completes the lifecycle:
    registration (if no registry is supplied), validation, freeze."""

    def __init__(self, registry: IntentRegistry | None = None) -> None:
        started = time.perf_counter()
        self._registry = registry or build_default_registry()
        if not self._registry.frozen:
            self._registry.freeze()  # validates; raises listing problems
        self._startup_ms = int((time.perf_counter() - started) * 1000)

    # -- resolution ------------------------------------------------------

    def route(
        self, question: str, *, sites: Iterable[str] = ()
    ) -> IntentRoute:
        """Resolve one question to an operational intent. Resolution
        only — execution stays with the engines."""

        return detect(question, registry=self._registry, sites=sites)

    # -- catalog reads ---------------------------------------------------

    @property
    def registry(self) -> IntentRegistry:
        return self._registry

    def intents(self) -> tuple[IntentDefinition, ...]:
        return self._registry.definitions()

    def intent(self, key: str) -> IntentDefinition | None:
        return self._registry.get(key)

    # -- diagnostics (Part 8) --------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """Administrative snapshot of the frozen registry — everything
        a debugging session needs, JSON-safe."""

        definitions = self._registry.definitions()
        capabilities: dict[str, list[str]] = {}
        workflows: set[str] = set()
        for definition in definitions:
            capabilities.setdefault(definition.capability, []).append(
                definition.key
            )
            for workflow in definition.workflows + definition.recommendations:
                workflows.add(workflow_path(workflow.href))
        return {
            "registry_version": self._registry.version,
            "frozen": self._registry.frozen,
            "validation": "passed",  # a frozen registry passed by definition
            "intent_count": len(definitions),
            "capabilities": {
                name: sorted(keys)
                for name, keys in sorted(capabilities.items())
            },
            "registrars": list(CAPABILITY_REGISTRARS),
            "routing_table": [
                {
                    "priority": definition.routing_priority,
                    "intent": definition.name,
                    "key": definition.key,
                    "engine": definition.engine,
                    "phrases": list(phrases),
                }
                for definition, phrases in self._registry.routing_table()
            ],
            "engine_defaults": {
                definition.engine: definition.key
                for definition in definitions
                if definition.default_for_engine
            },
            "workflows_referenced": sorted(workflows),
            "startup_ms": self._startup_ms,
        }


_default_router: OperationalIntentRouter | None = None
_default_router_lock = threading.Lock()


def default_router() -> OperationalIntentRouter:
    """The process-wide router over the default capability catalog.
    Built once (registration → validation → freeze), then immutable.

    Thread-safe by double-checked locking: the first build spans 15
    registrar imports, and on a threaded server several first requests
    can race here — every caller must get the SAME frozen router, and
    none may wander into the bootstrap's re-entrancy guard."""

    global _default_router
    if _default_router is None:
        with _default_router_lock:
            if _default_router is None:
                _default_router = OperationalIntentRouter()
    return _default_router
