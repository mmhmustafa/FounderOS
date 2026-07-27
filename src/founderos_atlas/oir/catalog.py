"""Engine identifiers and registry-derived compatibility views.

PR-164.1 (FOUNDATION): the static routing tables that used to live in
this module are GONE. Every intent now declares its own routing
phrases and priority at registration (capability-owned modules listed
in ``bootstrap.CAPABILITY_REGISTRARS``), and the routing engine
derives its behaviour from the frozen registry. This module keeps the
engine identifiers — the stable names of Atlas's EXECUTION engines —
and legacy-shaped views (``ENGINE_RULES``, ``engine_rule_match``)
now DERIVED from registrations, for diagnostics and compatibility.
"""

from __future__ import annotations

from .bootstrap import build_default_registry  # re-export (compat)

# DEFAULT_REGISTRY and ENGINE_RULES are deliberately NOT in __all__:
# they are lazy (PEP 562) registry-derived views, and advertising them
# would make `import *` (and __all__-driven introspection) build and
# freeze the whole catalog as an import side effect. They stay
# reachable by explicit name.
__all__ = [
    "ENGINE_HEALTH", "ENGINE_CHANGES", "ENGINE_DISCOVERY", "ENGINE_PATH",
    "ENGINE_PREDICTION", "ENGINE_COMPASS", "ENGINE_CONTINUE",
    "ENGINE_SEARCH", "ENGINE_ENTERPRISE", "ENGINE_INVESTIGATION",
    "ENGINE_UNKNOWN", "build_default_registry", "engine_rule_match",
]

ENGINE_HEALTH = "health"
ENGINE_CHANGES = "changes"
ENGINE_DISCOVERY = "discovery"
ENGINE_PATH = "path"
ENGINE_PREDICTION = "prediction"
ENGINE_COMPASS = "compass"
ENGINE_CONTINUE = "continue"
ENGINE_SEARCH = "search"
ENGINE_ENTERPRISE = "enterprise"
ENGINE_INVESTIGATION = "investigation"
ENGINE_UNKNOWN = "unknown"


def engine_rule_match(question: str) -> tuple[str, str] | None:
    """(engine, matched phrase) for the first direct-phrase hit, else
    None — the legacy shape, DERIVED from the frozen registry."""

    from .service import default_router

    folded = " ".join(str(question or "").casefold().split())
    if not folded:
        return None
    for definition, phrases in default_router().registry.routing_table():
        for phrase in phrases:
            if phrase in folded:
                return definition.engine, phrase
    return None


def __getattr__(name: str):
    # Lazy, registry-derived module attributes (PEP 562): building the
    # default registry imports every capability registrar, so it must
    # not happen at import time. Computed once, then cached into the
    # module globals so repeated access is free.
    if name == "DEFAULT_REGISTRY":
        from .service import default_router

        value = default_router().registry
    elif name == "ENGINE_RULES":
        from .service import default_router

        value = tuple(
            (definition.engine, phrases)
            for definition, phrases
            in default_router().registry.routing_table()
        )
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(globals()) + ["DEFAULT_REGISTRY", "ENGINE_RULES"])
