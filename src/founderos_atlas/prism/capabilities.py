"""PRISM AI capability registry (PR-165, Parts 6 and 12).

AI is never "on". Capabilities register individually and each is
enabled by an administrator one at a time, so a customer can run
executive summaries without ever enabling a conversational surface.

Every capability declares what it needs and — the important half —
what Atlas does when it is unavailable. ``fallback`` is a plain
sentence describing the DETERMINISTIC behaviour that remains, because
the platform contract is that no Atlas capability depends on AI: with
AI off, the fallback IS the product, not a degraded mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .prompts import (
    PROMPT_EXECUTIVE_SUMMARY,
    PROMPT_INCIDENT_SUMMARY,
    PROMPT_PLAIN_ENGLISH,
    PROMPT_QUESTION_REWRITE,
    PROMPT_REPORT,
    PROMPT_TRANSLATION,
)


CAPABILITY_PLAIN_ENGLISH = "plain-english"
CAPABILITY_EXECUTIVE_SUMMARY = "executive-summary"
CAPABILITY_INCIDENT_SUMMARY = "incident-summary"
CAPABILITY_REPORT = "report-generation"
CAPABILITY_QUESTION_REWRITE = "question-rewrite"
CAPABILITY_TRANSLATION = "translation"
CAPABILITY_CONVERSATION = "conversation"


@dataclass(frozen=True)
class AICapability:
    """One optional AI enhancement."""

    key: str
    label: str
    description: str
    prompt: str
    fallback: str
    owner: str = "Atlas Platform"
    min_context_tokens: int = 2048
    max_output_tokens: int = 800
    requires_cloud_disclosure: bool = True
    available: bool = True     # a capability may ship not-yet-available
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "prompt": self.prompt,
            "fallback": self.fallback,
            "owner": self.owner,
            "min_context_tokens": self.min_context_tokens,
            "available": self.available,
            "notes": self.notes,
        }


class CapabilityRegistry:
    """Registered capabilities, in registration order."""

    def __init__(self) -> None:
        self._by_key: dict[str, AICapability] = {}

    def register(self, capability: AICapability) -> AICapability:
        if capability.key in self._by_key:
            raise ValueError(
                f"AI capability {capability.key!r} is already registered"
            )
        self._by_key[capability.key] = capability
        return capability

    def get(self, key: str) -> AICapability | None:
        return self._by_key.get(key)

    def all(self) -> tuple[AICapability, ...]:
        return tuple(self._by_key.values())

    def keys(self) -> tuple[str, ...]:
        return tuple(self._by_key)


def build_default_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(AICapability(
        key=CAPABILITY_PLAIN_ENGLISH, label="Plain English explanation",
        description="Restates an Atlas answer in non-specialist language.",
        prompt=PROMPT_PLAIN_ENGLISH,
        fallback="Atlas shows its own deterministic answer with evidence, "
                 "confidence and limitations — exactly as it does today.",
        owner="Advisor",
    ))
    registry.register(AICapability(
        key=CAPABILITY_EXECUTIVE_SUMMARY, label="Executive summary",
        description="Summarizes several findings for a management "
                    "audience.",
        prompt=PROMPT_EXECUTIVE_SUMMARY,
        fallback="Atlas shows the per-dimension health summary and the "
                 "evidence behind it.",
        owner="Advisor", max_output_tokens=600,
    ))
    registry.register(AICapability(
        key=CAPABILITY_INCIDENT_SUMMARY, label="Incident summary",
        description="Narrates an incident timeline Atlas has built.",
        prompt=PROMPT_INCIDENT_SUMMARY,
        fallback="Atlas shows the incident timeline and its evidence "
                 "entries in order.",
        owner="Incidents",
    ))
    registry.register(AICapability(
        key=CAPABILITY_REPORT, label="Report narrative",
        description="Turns structured report data into prose.",
        prompt=PROMPT_REPORT,
        fallback="Atlas exports the report with its tables and figures, "
                 "without narrative prose.",
        owner="Reporting", max_output_tokens=1200,
    ))
    registry.register(AICapability(
        key=CAPABILITY_QUESTION_REWRITE, label="Question rewriting",
        description="Rewrites an operator question into the vocabulary "
                    "the deterministic router understands. The rewritten "
                    "question is then routed by the OIR exactly as a "
                    "typed one — AI never selects the workflow.",
        prompt=PROMPT_QUESTION_REWRITE,
        fallback="The Operational Intent Router classifies the question "
                 "as typed, and says so honestly when nothing matches.",
        owner="Advisor", max_output_tokens=120,
    ))
    registry.register(AICapability(
        key=CAPABILITY_TRANSLATION, label="Translation",
        description="Translates an Atlas answer into another language.",
        prompt=PROMPT_TRANSLATION,
        fallback="Atlas presents answers in English.",
        owner="Atlas Platform",
    ))
    registry.register(AICapability(
        key=CAPABILITY_CONVERSATION, label="Conversation",
        description="Multi-turn conversational assistance over Atlas "
                    "answers.",
        prompt=PROMPT_PLAIN_ENGLISH,
        fallback="Advisor answers one evidence-backed question at a "
                 "time, with its stored conversation history.",
        owner="Advisor", available=False,
        notes="Registered for governance visibility; no consumer ships "
              "in PR-165, so enabling it changes nothing yet.",
    ))
    return registry


DEFAULT_CAPABILITY_REGISTRY = build_default_capability_registry()
