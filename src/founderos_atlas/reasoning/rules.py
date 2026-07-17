"""CORTEX rule framework — enumerable, versioned, testable rules (§5).

Today rules are ``if`` statements inside engines: they cannot be listed, tested
in isolation, or explained as "rule X fired." Here a rule is a pure function of
evidence. It may not fetch, may not render, and — critically — may not compute
a final score. It *declares named factors* (from :mod:`calculus`) and the
engine prices them, which is the single change that makes "High" mean one
thing everywhere.

No DSL, no config language, no dynamic dispatch (risk R4): a rule is a plain
Python object. The registry just makes them enumerable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .calculus import ConfidenceFactor
from .evidence import Evidence, EvidenceGap
from .result import (
    Recommendation,
    RejectedConclusion,
    ReasoningStep,
    SEVERITY_MEDIUM,
)


@dataclass(frozen=True)
class RuleOutcome:
    """What a rule concluded — before the engine prices confidence and packages
    a :class:`ReasoningResult`.

    A rule declares ``factors`` (named, via the calculus constructors) but never
    the final score. ``base_confidence`` is the rule's starting point; the
    engine applies ``clamp(base + Σ factors)``. ``has_evidence=False`` forces
    the result to band ``unknown`` no matter what — the structural guarantee
    that a no-evidence conclusion cannot look confident.
    """

    conclusion: str
    conclusion_kind: str
    base_confidence: float
    factors: tuple[ConfidenceFactor, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    steps: tuple[ReasoningStep, ...] = ()
    gaps: tuple[EvidenceGap, ...] = ()
    recommendations: tuple[Recommendation, ...] = ()
    rejected: tuple[RejectedConclusion, ...] = ()
    conflicting: tuple[str, ...] = ()
    severity: str = SEVERITY_MEDIUM
    has_evidence: bool = True
    confidence_basis: str = ""


@runtime_checkable
class Rule(Protocol):
    """A pure function of evidence. Registered, so Atlas can answer "what rules
    exist?" and test each one alone."""

    @property
    def rule_id(self) -> str: ...

    @property
    def family(self) -> str: ...

    @property
    def question_kinds(self) -> tuple[str, ...]: ...

    def applies(self, evidence: tuple[Evidence, ...]) -> bool:
        """Whether this rule has anything to say about this evidence."""
        ...

    def evaluate(
        self, evidence: tuple[Evidence, ...], gaps: tuple[EvidenceGap, ...]
    ) -> RuleOutcome:
        """The conclusion, as declared factors — never a final score."""
        ...


# -- rule families (open vocabulary) -----------------------------------------

FAMILY_HEALTH = "health"
FAMILY_RISK = "risk"
FAMILY_COMPLIANCE = "compliance"
FAMILY_PREDICTION = "prediction"
FAMILY_INCIDENT = "incident"
FAMILY_TOPOLOGY = "topology"
FAMILY_RELATIONSHIP = "relationship"
FAMILY_CONFIGURATION = "configuration"


class RuleRegistry:
    """The enumerable, deterministically-ordered set of rules Atlas knows.

    Order is insertion order (deterministic), and lookups preserve it, so two
    runs over the same rules produce the same ranking. A rule id is unique;
    re-registering one replaces it (a pack reload is not an error)."""

    def __init__(self) -> None:
        self._rules: dict[str, Rule] = {}

    def register(self, rule: Rule) -> None:
        self._rules[rule.rule_id] = rule

    def register_all(self, rules) -> None:
        for rule in rules:
            self.register(rule)

    def get(self, rule_id: str) -> Rule | None:
        return self._rules.get(rule_id)

    def all(self) -> tuple[Rule, ...]:
        return tuple(self._rules.values())

    def for_question(
        self, kind: str, *, family: str | None = None, focus: str | None = None
    ) -> tuple[Rule, ...]:
        """Rules that answer a question kind, optionally narrowed to one family
        or pinned to a single rule id (``focus`` — how a targeted check selects
        exactly its own rule)."""

        if focus is not None:
            rule = self._rules.get(focus)
            return (rule,) if rule is not None else ()
        matches = []
        for rule in self._rules.values():
            if kind not in rule.question_kinds:
                continue
            if family is not None and rule.family != family:
                continue
            matches.append(rule)
        return tuple(matches)

    def families(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for rule in self._rules.values():
            seen.setdefault(rule.family, None)
        return tuple(seen)

    def __len__(self) -> int:
        return len(self._rules)
