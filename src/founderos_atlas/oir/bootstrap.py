"""Registry bootstrap: capability-owned registration (PR-164.1, Part 4).

Each Atlas capability owns its intent registrations in its OWN package
(``founderos_atlas.<capability>.intents``); this module only lists WHO
registers and in WHAT ORDER. Adding a capability to Atlas means adding
its ``intents`` module here — never editing a central catalog file.

Bootstrap order is part of the platform contract: refinement and
fallback ties break toward the earlier registration, so the order
below is deliberate and stable. Direct routing precedence does NOT
depend on this order — it comes from each intent's declared
``routing_priority``.

Registrar contract: a module listed here exposes ``CAPABILITY`` (its
display name) and ``register(registry)`` which only registers
:class:`IntentDefinition` data. Registrars must not route, must not
build registries of their own, and must not trigger further
registration — recursion is detected and refused.
"""

from __future__ import annotations

import importlib
import threading

from .registry import IntentRegistry, RegistryValidationError


CAPABILITY_REGISTRARS: tuple[str, ...] = (
    "founderos_atlas.health.intents",
    "founderos_atlas.routing.intents",
    "founderos_atlas.policy.intents",
    "founderos_atlas.path_intelligence.intents",
    "founderos_atlas.change.intents",
    "founderos_atlas.search.intents",
    "founderos_atlas.discovery.intents",
    "founderos_atlas.compass.intents",
    "founderos_atlas.prediction.intents",
    "founderos_atlas.incidents.intents",
    "founderos_atlas.enterprise.intents",
    "founderos_atlas.identity.intents",
    "founderos_atlas.telemetry.intents",
    "founderos_atlas.audit.intents",
    "founderos_atlas.oir.registrations",
)

# PER-THREAD re-entrancy guard: recursion (a registrar triggering
# bootstrap) is a bug in the SAME thread's call stack; two different
# threads building concurrently is legitimate (each gets its own
# registry) and must never be mistaken for a cycle.
_building = threading.local()


def build_default_registry() -> IntentRegistry:
    """Run every capability registrar, in order, into a fresh registry.

    Returns the registry OPEN (unfrozen): the caller — normally
    :func:`founderos_atlas.oir.service.default_router` — freezes it,
    which is when validation runs. Tests may register extra intents on
    the result before freezing.
    """

    if getattr(_building, "active", False):
        raise RegistryValidationError([
            "circular registration detected: a capability registrar "
            "triggered registry bootstrap while bootstrap was already "
            "running — registrars must only declare intents"
        ])
    _building.active = True
    try:
        registry = IntentRegistry()
        for module_path in CAPABILITY_REGISTRARS:
            module = importlib.import_module(module_path)
            module.register(registry)
        return registry
    finally:
        _building.active = False
