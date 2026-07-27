"""The Operational Intent Router's registry (PR-164, INTENT).

Atlas has exactly ONE workflow orchestration engine: this registry.
Every module that wants Atlas to route operators into its workflow
registers an :class:`IntentDefinition` here — the intent's name, the
evidence it needs, the workflows that serve it, the recommendations and
follow-up questions it offers, and the honest limitations it carries.

Governance (Part 12): future modules MUST NOT implement their own
routing logic, MUST NOT duplicate intent detection, and MUST NOT modify
Advisor. They register an intent; every consumer — Advisor today, APIs
and automation tomorrow — reads the same catalog.

Everything here is data, not behaviour: detection stays deterministic
because a definition can only declare phrases and keywords, never code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

    ``engine`` names the existing Advisor evidence engine that produces
    the answer (health/path/changes/search/discovery/compass/prediction/
    continue/investigation/enterprise/unknown) — OIR routes, it never
    invents a second answering path. ``domain`` selects the answer
    layout family. ``refine_keywords`` are the deterministic secondary
    signals that pick this intent WITHIN its engine family; the first
    registered definition of a family is its base intent.
    """

    name: str
    key: str
    description: str
    engine: str
    domain: str
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
        return {
            "name": self.name,
            "key": self.key,
            "description": self.description,
            "engine": self.engine,
            "domain": self.domain,
            "required_evidence": list(self.required_evidence),
            "workflows": [item.to_dict() for item in self.workflows],
            "recommendations": [
                item.to_dict() for item in self.recommendations
            ],
            "followups": [item.to_dict() for item in self.followups],
            "confidence_rule": self.confidence_rule,
            "limitations": list(self.limitations),
        }


class IntentRegistry:
    """Ordered registry of intent definitions.

    Registration order is meaningful and deterministic: within an engine
    family, the FIRST registered definition is the family's base intent,
    and refinement ties break toward the earlier registration.
    """

    def __init__(self) -> None:
        self._definitions: list[IntentDefinition] = []
        self._by_key: dict[str, IntentDefinition] = {}

    def register(self, definition: IntentDefinition) -> IntentDefinition:
        if definition.key in self._by_key:
            raise ValueError(
                f"intent key {definition.key!r} is already registered — "
                "one catalog, no duplicates"
            )
        self._definitions.append(definition)
        self._by_key[definition.key] = definition
        return definition

    def definitions(self) -> tuple[IntentDefinition, ...]:
        return tuple(self._definitions)

    def get(self, key: str) -> IntentDefinition | None:
        return self._by_key.get(key)

    def family(self, engine: str) -> tuple[IntentDefinition, ...]:
        """Every definition answered by one engine, registration order."""

        return tuple(
            item for item in self._definitions if item.engine == engine
        )
