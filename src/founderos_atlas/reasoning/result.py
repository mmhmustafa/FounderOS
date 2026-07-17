"""CORTEX result schema — one shape every module reasons into (§4).

Today four result types (AdvisorResponse, PathInvestigation, prediction,
root_cause) express the same five concepts under different field names, and no
two agree. :class:`ReasoningResult` is the single schema. Its design notes,
each earning its place from the review:

- **Confidence is always score *and* band** (fixes Advisor's lossy ``str``).
- **``alternatives_rejected`` is mandatory** (may be empty, never absent) —
  Part 7's "why not another conclusion?" is otherwise unanswerable.
- **``evidence_conflicting`` is separate from ``evidence_missing``** — conflict
  and absence are different epistemic states.
- **``as_of`` vs ``generated_at``** — reasoning over Memory is time-travel;
  without ``as_of``, "what did we conclude about yesterday?" is inexpressible.
- **``provenance``** answers "which rules/version concluded this?".
- **``consumer``** is a *label*, never a behaviour switch — the engine must
  produce the identical result regardless. If it ever changes a conclusion,
  the framework has failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .calculus import Confidence
from .evidence import Evidence, EvidenceGap


# -- question kinds ----------------------------------------------------------

QUESTION_DIAGNOSE = "diagnose"     # "why is X the way it is?"
QUESTION_ASSESS = "assess"         # "what is the state of X?" (health)
QUESTION_PREDICT = "predict"       # "what if X?" (as_of = hypothetical)
QUESTION_COMPLY = "comply"         # "does X meet policy?"


# -- conclusion kinds (open; policy uses the four compliance dispositions) ---

CONCLUSION_PASS = "pass"
CONCLUSION_FAIL = "fail"
CONCLUSION_WARNING = "warning"
CONCLUSION_UNKNOWN = "unknown"


# -- severity (distinct from confidence; never feeds the score) --------------

SEVERITY_INFO = "info"
SEVERITY_LOW = "low"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"
SEVERITY_CRITICAL = "critical"

# Strongest first — for ranking.
SEVERITIES = (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_INFO,
)
_SEVERITY_RANK = {name: i for i, name in enumerate(SEVERITIES)}


def severity_rank(severity: str) -> int:
    """A sort key: lower is more severe (critical -> 0)."""

    return _SEVERITY_RANK.get(severity, len(SEVERITIES))


@dataclass(frozen=True)
class ReasoningQuestion:
    """What a module asks the engine. The module chooses the question; it may
    not compute the answer.

    ``focus`` pins the reasoning to a single rule (a policy id, say), so the
    same engine serves both open diagnosis (rank every matching rule) and a
    targeted check (evaluate exactly one). ``as_of`` makes historical reasoning
    over Enterprise Memory expressible.
    """

    kind: str
    subject: str                      # the thing being reasoned about
    scope: str = ""                   # network / profile scope id
    focus: str | None = None          # a specific rule id, when targeted
    as_of: str | None = None          # reason as of this instant (None = now)
    consumer: str = ""                # audit label only — never changes the result
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "scope": self.scope,
            "focus": self.focus,
            "as_of": self.as_of,
            "consumer": self.consumer,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class ReasoningStep:
    """One step of the reasoning path — how the engine got from evidence to
    conclusion. Carries the ``rule_id`` so "which rules?" is answerable."""

    rule_id: str
    statement: str
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "statement": self.statement,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class RejectedConclusion:
    """A conclusion the engine considered and rejected, with why. Recorded
    *during* ranking, never reconstructed after — the only honest way to
    answer "why not X?"."""

    statement: str
    why_not: str
    evidence_against: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "why_not": self.why_not,
            "evidence_against": list(self.evidence_against),
        }


@dataclass(frozen=True)
class Recommendation:
    """A remediation. A recommendation without a ``rationale`` is invalid —
    explainability enforced by the type, not by reviewer discipline."""

    action: str
    rationale: str
    severity: str = SEVERITY_MEDIUM
    deep_link: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "rationale": self.rationale,
            "severity": self.severity,
            "deep_link": self.deep_link,
        }


@dataclass(frozen=True)
class ResultProvenance:
    """Which rules/version produced this conclusion — the conclusion-level
    analogue of PR-045R's evidence provenance (§1.5.5)."""

    rule_set_version: str
    engine_version: str
    atlas_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_set_version": self.rule_set_version,
            "engine_version": self.engine_version,
            "atlas_version": self.atlas_version,
        }


@dataclass(frozen=True)
class ReasoningResult:
    """The one result shape. Every module renders this; none computes it.

    ``evidence_used`` and ``evidence_missing`` together make silence
    impossible: a result with empty ``evidence_used`` cannot carry a band above
    ``unknown`` (enforced in the engine), so a confident-looking answer always
    has evidence behind it.
    """

    result_id: str
    question: ReasoningQuestion
    conclusion: str
    conclusion_kind: str
    confidence: Confidence
    severity: str
    subject: str
    generated_at: str
    as_of: str
    evidence_used: tuple[Evidence, ...] = ()
    evidence_missing: tuple[EvidenceGap, ...] = ()
    evidence_conflicting: tuple[str, ...] = ()
    reasoning_path: tuple[ReasoningStep, ...] = ()
    alternatives_rejected: tuple[RejectedConclusion, ...] = ()
    recommendations: tuple[Recommendation, ...] = ()
    consumer: str = ""
    provenance: ResultProvenance | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "question": self.question.to_dict(),
            "conclusion": self.conclusion,
            "conclusion_kind": self.conclusion_kind,
            "confidence": self.confidence.to_dict(),
            "severity": self.severity,
            "subject": self.subject,
            "generated_at": self.generated_at,
            "as_of": self.as_of,
            "evidence_used": [e.to_dict() for e in self.evidence_used],
            "evidence_missing": [g.to_dict() for g in self.evidence_missing],
            "evidence_conflicting": list(self.evidence_conflicting),
            "reasoning_path": [s.to_dict() for s in self.reasoning_path],
            "alternatives_rejected": [r.to_dict() for r in self.alternatives_rejected],
            "recommendations": [r.to_dict() for r in self.recommendations],
            "consumer": self.consumer,
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }
