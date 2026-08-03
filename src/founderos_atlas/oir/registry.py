"""The Operational Intent Router's registry (PR-164 INTENT, hardened
by PR-164.1 FOUNDATION).

Atlas has exactly ONE workflow orchestration engine: this registry.
Every capability that wants Atlas to route operators into its workflow
registers an :class:`IntentDefinition` — the intent's name, its DIRECT
ROUTING PHRASES and priority, the refinement and fallback signals, the
evidence it needs, the workflows that serve it, the recommendations and
follow-up questions it offers, and the honest limitations it carries.
One declarative source of truth; the routing engine derives ALL of its
behaviour from it (no static tables anywhere else).

Lifecycle (PR-164.1):

    Startup -> Module Registration -> Validation -> Freeze -> Runtime

``freeze()`` validates every registration (duplicates, phrase clashes,
priority conflicts, unknown workflow references, unknown evidence
kinds, missing engine defaults), derives the routing table, and locks
the registry. After freeze, ``register()`` fails loudly — the catalog
is immutable at runtime, which is what makes routing deterministic and
auditable.

Governance: future capabilities MUST NOT implement their own routing
logic, MUST NOT duplicate intent detection, and MUST NOT modify
Advisor. They register an intent; every consumer — Advisor today, APIs
and automation tomorrow — reads the same catalog. Everything here is
data, not behaviour: a definition can only declare phrases and
keywords, never code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


class RegistryFrozenError(RuntimeError):
    """Registration attempted after the registry was frozen."""


class RegistryValidationError(ValueError):
    """One or more registrations failed startup validation."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__(
            "intent registry validation failed:\n- " + "\n- ".join(problems)
        )


@dataclass(frozen=True)
class Workflow:
    """One Atlas workflow that serves an intent, with its reason."""

    label: str
    href: str
    why: str

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "href": self.href, "why": self.why}


@dataclass(frozen=True)
class FollowUpSeed:
    """A follow-up question an intent suggests (resubmitted to Advisor)."""

    label: str
    question: str

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "question": self.question}


@dataclass(frozen=True)
class IntentDefinition:
    """One operational intent, fully declared.

    ``engine`` names the existing execution engine that produces the
    answer (health/path/changes/search/discovery/compass/prediction/
    continue/investigation/enterprise/unknown) — OIR RESOLVES intent,
    engines EXECUTE; it never invents a second answering path.

    ``routing_phrases`` are the intent's direct routing phrases and
    ``routing_priority`` orders them against every other intent's
    (lower fires first; first match wins). An intent with phrases must
    declare a priority, and priorities must be unique — that keeps the
    derived table exactly as deterministic as the fixed table it
    replaced. ``default_for_engine`` marks the ONE intent per engine
    that a bare engine match falls back to when no finer signal exists.

    ``capability`` names the owning Atlas capability (diagnostics and
    accountability). ``refine_keywords``/``refine_entities`` pick this
    intent WITHIN its engine family; ``fallback_keywords`` may rescue a
    question no routing phrase claimed, at Medium confidence.
    """

    name: str
    key: str
    description: str
    engine: str
    domain: str
    # PR-171: WHAT KIND of answer this intent wants — validate, assess,
    # locate, explain, compare or forecast. The engine says WHERE the
    # answer comes from; the objective says WHAT SHAPE it takes, and
    # dispatch reads both. Every pre-existing intent takes the default,
    # so (engine, objective) dispatch reproduces the old engine-only
    # dispatch exactly. Before this field existed the resolved intent
    # was never consulted at execution time at all — Atlas recognised
    # "OSPF" in a configuration question and then answered with the
    # enterprise summary, because dispatch saw only engine="health".
    objective: str = "assess"
    capability: str = "Atlas Platform"
    routing_phrases: tuple[str, ...] = ()
    routing_priority: int = 0
    default_for_engine: bool = False
    examples: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    workflows: tuple[Workflow, ...] = ()
    recommendations: tuple[Workflow, ...] = ()
    followups: tuple[FollowUpSeed, ...] = ()
    refine_keywords: tuple[str, ...] = ()
    refine_entities: tuple[str, ...] = ()  # e.g. ("site",): a named
    #   known entity of this kind selects the intent within its family
    fallback_keywords: tuple[str, ...] = ()
    confidence_rule: str = ""
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        # COMPLETE: the registry version hashes this dict, so every
        # field that can change routing or presentation must appear —
        # omitting one would let behaviour change under an unchanged
        # version.
        return {
            "name": self.name,
            "key": self.key,
            "description": self.description,
            "engine": self.engine,
            "domain": self.domain,
            "objective": self.objective,
            "capability": self.capability,
            "routing_phrases": list(self.routing_phrases),
            "routing_priority": self.routing_priority,
            "default_for_engine": self.default_for_engine,
            "examples": list(self.examples),
            "required_evidence": list(self.required_evidence),
            "workflows": [item.to_dict() for item in self.workflows],
            "recommendations": [
                item.to_dict() for item in self.recommendations
            ],
            "followups": [item.to_dict() for item in self.followups],
            "refine_keywords": list(self.refine_keywords),
            "refine_entities": list(self.refine_entities),
            "fallback_keywords": list(self.fallback_keywords),
            "confidence_rule": self.confidence_rule,
            "limitations": list(self.limitations),
        }


class IntentRegistry:
    """Ordered registry of intent definitions with a freeze lifecycle.

    Registration order is meaningful and deterministic: refinement and
    fallback ties break toward the earlier registration. The engine a
    bare match falls back to is the family's ``default_for_engine``
    intent — explicit, validated, never positional.
    """

    def __init__(self) -> None:
        self._definitions: list[IntentDefinition] = []
        self._by_key: dict[str, IntentDefinition] = {}
        self._frozen = False
        self._routing_table: tuple[
            tuple[IntentDefinition, tuple[str, ...]], ...
        ] = ()
        self._defaults: dict[str, IntentDefinition] = {}
        self._version = ""

    # -- registration (only while open) ---------------------------------

    def register(self, definition: IntentDefinition) -> IntentDefinition:
        if self._frozen:
            raise RegistryFrozenError(
                f"cannot register intent {definition.key!r}: the registry "
                "is frozen — intents register at startup, before "
                "freeze(), never at runtime"
            )
        if definition.key in self._by_key:
            raise RegistryValidationError([
                f"intent key {definition.key!r} is already registered — "
                "one catalog, no duplicates"
            ])
        self._definitions.append(definition)
        self._by_key[definition.key] = definition
        return definition

    # -- lifecycle -------------------------------------------------------

    def freeze(self) -> "IntentRegistry":
        """Validate every registration, derive the routing table, and
        lock the registry. Idempotent. Raises
        :class:`RegistryValidationError` listing EVERY problem found —
        fail fast, fail loud, fail completely."""

        if self._frozen:
            return self
        from .validation import validate_definitions

        problems = validate_definitions(self._definitions)
        if problems:
            raise RegistryValidationError(problems)
        # Version FIRST: serialization is the last thing that can fail,
        # and it must fail as a validation error before any derived
        # state is assigned — never a raw TypeError over a half-built
        # registry.
        digest = hashlib.sha256()
        for definition in self._definitions:
            try:
                digest.update(
                    json.dumps(
                        definition.to_dict(), sort_keys=True
                    ).encode()
                )
            except (TypeError, ValueError) as error:
                raise RegistryValidationError([
                    f"{definition.key!r}: declaration is not "
                    f"JSON-serialisable ({error}) — definitions are "
                    "plain data: strings, numbers, booleans"
                ]) from error
        self._version = digest.hexdigest()[:16]
        self._routing_table = tuple(
            (definition, definition.routing_phrases)
            for definition in sorted(
                (d for d in self._definitions if d.routing_phrases),
                key=lambda d: d.routing_priority,
            )
        )
        self._defaults = {
            d.engine: d for d in self._definitions if d.default_for_engine
        }
        self._frozen = True
        return self

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def version(self) -> str:
        """Deterministic content hash of every registration — two
        registries with identical declarations share a version."""

        return self._version

    def _require_frozen(self) -> None:
        if not self._frozen:
            raise RegistryFrozenError(
                "the registry must be frozen before routing — call "
                "freeze() after registration (lifecycle: register -> "
                "validate -> freeze -> route)"
            )

    # -- read side -------------------------------------------------------

    def definitions(self) -> tuple[IntentDefinition, ...]:
        return tuple(self._definitions)

    def get(self, key: str) -> IntentDefinition | None:
        return self._by_key.get(key)

    def family(self, engine: str) -> tuple[IntentDefinition, ...]:
        """Every definition answered by one engine, registration order."""

        return tuple(
            item for item in self._definitions if item.engine == engine
        )

    def default_for(self, engine: str) -> IntentDefinition | None:
        """The engine's declared default intent (frozen registries)."""

        self._require_frozen()
        return self._defaults.get(engine)

    def routing_table(
        self,
    ) -> tuple[tuple[IntentDefinition, tuple[str, ...]], ...]:
        """The derived direct-routing table, priority order — DATA
        derived from registrations, not a static table (PR-164.1)."""

        self._require_frozen()
        return self._routing_table
