"""CORTEX reasoning engine — evaluate → score → explain (§2.3).

The engine is the only thing that turns evidence into a scored, explained
:class:`ReasoningResult`. Four properties fall out of its lifecycle and are
worth naming, because each is a guarantee the review asked for:

1. **Evidence gathering is a separate step.** Rules never fetch. A new
   evidence source is a new provider, not an engine change (§10).
2. **What was *unavailable* is a first-class return value.** Gaps flow through
   to the result; "unknown stays unknown" is structural.
3. **Rejected candidates are recorded during ranking**, not reconstructed
   after — the only honest way to answer "why not X?" (Part 7).
4. **Scoring is called by the engine, never by a rule.** A rule declares
   factors; the engine prices them. This is what makes "High" mean one thing.

Determinism: the engine holds an injected ``clock`` (no wall-clock in the
reasoning path), and rule order is the registry's insertion order, so the same
inputs always produce the same result.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256

from founderos_atlas.release import VERSION

from .calculus import assess
from .evidence import Evidence, EvidenceGap
from .provider import EvidenceProvider
from .result import (
    CONCLUSION_UNKNOWN,
    ReasoningQuestion,
    ReasoningResult,
    RejectedConclusion,
    ResultProvenance,
    severity_rank,
)
from .rules import Rule, RuleOutcome, RuleRegistry

ENGINE_VERSION = "cortex-0.1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReasoningEngine:
    """Reasons a :class:`ReasoningQuestion` into a :class:`ReasoningResult`
    using registered rules and injected evidence providers."""

    def __init__(
        self,
        registry: RuleRegistry,
        providers: tuple[EvidenceProvider, ...] | list[EvidenceProvider],
        *,
        clock: Callable[[], str] | None = None,
        rule_set_version: str = "unversioned",
        atlas_version: str = VERSION,
        engine_version: str = ENGINE_VERSION,
    ) -> None:
        self._registry = registry
        self._providers = tuple(providers)
        self._clock = clock or _utc_now_iso
        self._rule_set_version = rule_set_version
        self._atlas_version = atlas_version
        self._engine_version = engine_version

    # -- evidence gathering (step 1; rules never do this) ------------------

    def _gather(
        self, subject: str, as_of: str | None, kinds: tuple[str, ...]
    ) -> tuple[tuple[Evidence, ...], tuple[EvidenceGap, ...]]:
        evidence: list[Evidence] = []
        gaps: list[EvidenceGap] = []
        for provider in self._providers:
            evidence.extend(provider.gather(subject, as_of=as_of, kinds=kinds))
            gaps.extend(provider.describe_gaps(subject, as_of=as_of, kinds=kinds))
        return tuple(evidence), tuple(gaps)

    # -- evaluation --------------------------------------------------------

    def evaluate(self, question: ReasoningQuestion) -> ReasoningResult:
        generated_at = self._clock()
        as_of = question.as_of or generated_at

        evidence, gaps = self._gather(question.subject, question.as_of, ())

        rules = self._registry.for_question(
            question.kind,
            family=question.parameters.get("family"),
            focus=question.focus,
        )

        # Run every candidate rule that has something to say. A focused rule is
        # always run (a targeted check must return a verdict even when the
        # evidence it needs is absent — that verdict is "unknown").
        outcomes: list[tuple[Rule, RuleOutcome]] = []
        for rule in rules:
            if question.focus is not None or rule.applies(evidence):
                outcomes.append((rule, rule.evaluate(evidence, gaps)))

        if not outcomes:
            return self._empty_result(question, generated_at, as_of, evidence, gaps)

        ranked = sorted(outcomes, key=lambda item: self._rank_key(item[1]))
        winner_rule, winner = ranked[0]

        # Losing candidates become recorded rejections (Part 7), in addition to
        # any the winning rule itself declared.
        rejected = list(winner.rejected)
        for _rule, outcome in ranked[1:]:
            rejected.append(
                RejectedConclusion(
                    statement=outcome.conclusion,
                    why_not=(
                        f"a stronger conclusion applied "
                        f"({winner.severity}, {winner.conclusion_kind})"
                    ),
                    evidence_against=outcome.evidence_ids,
                )
            )

        return self._build_result(
            question,
            winner_rule,
            winner,
            generated_at=generated_at,
            as_of=as_of,
            evidence=evidence,
            gaps=gaps,
            rejected=tuple(rejected),
        )

    # -- ranking -----------------------------------------------------------

    @staticmethod
    def _rank_key(outcome: RuleOutcome):
        """Severity first, then confidence base, then conclusion text — a total,
        deterministic order (Remaining question §14.2: severity ranks first)."""

        return (
            severity_rank(outcome.severity),
            -outcome.base_confidence,
            outcome.conclusion,
        )

    # -- result construction ----------------------------------------------

    def _build_result(
        self,
        question: ReasoningQuestion,
        rule: Rule,
        outcome: RuleOutcome,
        *,
        generated_at: str,
        as_of: str,
        evidence: tuple[Evidence, ...],
        gaps: tuple[EvidenceGap, ...],
        rejected: tuple[RejectedConclusion, ...],
    ) -> ReasoningResult:
        # The structural guarantee (§7): no evidence -> band unknown, always.
        used = tuple(e for e in evidence if e.id in set(outcome.evidence_ids))
        has_evidence = outcome.has_evidence and bool(used)
        confidence = assess(
            outcome.base_confidence,
            outcome.factors,
            has_evidence=has_evidence,
            basis=outcome.confidence_basis,
        )
        # Only the gaps the winning rule flagged, plus provider-level gaps.
        result_gaps = tuple(dict.fromkeys(outcome.gaps + gaps))
        return ReasoningResult(
            result_id=self._result_id(question, rule.rule_id, generated_at),
            question=question,
            conclusion=outcome.conclusion,
            conclusion_kind=outcome.conclusion_kind,
            confidence=confidence,
            severity=outcome.severity,
            subject=question.subject,
            generated_at=generated_at,
            as_of=as_of,
            evidence_used=used,
            evidence_missing=result_gaps,
            evidence_conflicting=outcome.conflicting,
            reasoning_path=outcome.steps,
            alternatives_rejected=rejected,
            recommendations=outcome.recommendations,
            consumer=question.consumer,
            provenance=self._provenance(),
        )

    def _empty_result(
        self,
        question: ReasoningQuestion,
        generated_at: str,
        as_of: str,
        evidence: tuple[Evidence, ...],
        gaps: tuple[EvidenceGap, ...],
    ) -> ReasoningResult:
        """No rule applied — an honest "unknown", never a fabricated verdict."""

        from .calculus import Confidence
        from .result import SEVERITY_INFO

        return ReasoningResult(
            result_id=self._result_id(question, "none", generated_at),
            question=question,
            conclusion="No rule could reach a conclusion from the available evidence.",
            conclusion_kind=CONCLUSION_UNKNOWN,
            confidence=Confidence.unknown("no applicable rule"),
            severity=SEVERITY_INFO,
            subject=question.subject,
            generated_at=generated_at,
            as_of=as_of,
            evidence_used=(),
            evidence_missing=gaps,
            reasoning_path=(),
            alternatives_rejected=(),
            recommendations=(),
            consumer=question.consumer,
            provenance=self._provenance(),
        )

    def _provenance(self) -> ResultProvenance:
        return ResultProvenance(
            rule_set_version=self._rule_set_version,
            engine_version=self._engine_version,
            atlas_version=self._atlas_version,
        )

    @staticmethod
    def _result_id(question: ReasoningQuestion, rule_id: str, generated_at: str) -> str:
        digest = sha256(
            "|".join(
                [question.kind, question.subject, rule_id, question.as_of or "", generated_at]
            ).encode("utf-8")
        ).hexdigest()
        return f"result:{digest[:16]}"
