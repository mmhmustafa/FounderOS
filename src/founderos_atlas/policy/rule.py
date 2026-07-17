"""PolicyRule — a data-driven policy, compiled into a CORTEX rule (Part 3).

This is the whole of the "zero new scoring code" claim: a policy carries no
arithmetic. It declares *what compliant looks like*; this adapter turns that
into a :class:`Rule` that declares evidence-based *factors*, and the CORTEX
engine prices them with the one calculus. Every policy — SSH, hostname, BGP
router-id — flows through the identical pipeline (Part 3).

Explainability is structural (Part 7): a failed policy always carries the
evidence it used, the exact configuration lines (masked), the operator that
fired, and a remediation with a rationale. A verdict with no evidence is forced
to band ``unknown`` by the engine — silence is impossible.
"""

from __future__ import annotations

from founderos_atlas.reasoning import (
    CONCLUSION_FAIL,
    CONCLUSION_PASS,
    CONCLUSION_UNKNOWN,
    FAMILY_COMPLIANCE,
    QUESTION_COMPLY,
    SEVERITY_INFO,
    Evidence,
    EvidenceGap,
    Recommendation,
    ReasoningStep,
    RejectedConclusion,
    RuleOutcome,
    direct_observation,
)
from founderos_atlas.reasoning.evidence import GAP_NOT_COLLECTED

from .matcher import MatchReport, evaluate_check
from .models import Policy


class PolicyRule:
    """Adapts one :class:`Policy` to the CORTEX :class:`Rule` protocol."""

    def __init__(self, policy: Policy) -> None:
        self._policy = policy

    # -- Rule protocol -----------------------------------------------------

    @property
    def rule_id(self) -> str:
        return self._policy.policy_id

    @property
    def family(self) -> str:
        return FAMILY_COMPLIANCE

    @property
    def question_kinds(self) -> tuple[str, ...]:
        return (QUESTION_COMPLY,)

    @property
    def policy(self) -> Policy:
        return self._policy

    def applies(self, evidence: tuple[Evidence, ...]) -> bool:
        return any(e.kind == self._policy.check.evidence for e in evidence)

    def evaluate(
        self, evidence: tuple[Evidence, ...], gaps: tuple[EvidenceGap, ...]
    ) -> RuleOutcome:
        policy = self._policy
        item = self._evidence_for(evidence)

        # No evidence of the required kind -> honest "unknown", never a guess.
        if item is None:
            return self._unknown_outcome(gaps)

        report = evaluate_check(policy.check, item.text)
        factors = (
            direct_observation(
                "evaluated against the device's directly-collected running configuration",
                (item.id,),
            ),
        )
        basis = "a direct configuration observation, freshly collected"

        if not report.applicable:
            return self._not_applicable_outcome(item, report, factors, basis)
        if report.matched:
            return self._pass_outcome(item, report, factors, basis)
        return self._fail_outcome(item, report, factors, basis)

    # -- outcome builders --------------------------------------------------

    def _pass_outcome(self, item, report, factors, basis) -> RuleOutcome:
        policy = self._policy
        steps = self._steps(policy, report, verdict="satisfied")
        rejected = (
            RejectedConclusion(
                statement=f"{policy.name}: device is non-compliant",
                why_not="rejected — the required configuration is present (see reasoning)",
                evidence_against=(item.id,),
            ),
        )
        return RuleOutcome(
            conclusion=f"{policy.name}: compliant — {report.detail}.",
            conclusion_kind=CONCLUSION_PASS,
            base_confidence=policy.base_confidence,
            factors=factors,
            evidence_ids=(item.id,),
            steps=steps,
            recommendations=(),
            rejected=rejected,
            severity=SEVERITY_INFO,
            has_evidence=True,
            confidence_basis=basis,
        )

    def _fail_outcome(self, item, report, factors, basis) -> RuleOutcome:
        policy = self._policy
        steps = self._steps(policy, report, verdict="violated")
        recommendation = Recommendation(
            action=policy.remediation or policy.recommendation,
            rationale=(
                f"{policy.expected_state} "
                f"Observed: {report.detail}."
            ).strip(),
            severity=policy.severity,
        )
        rejected = (
            RejectedConclusion(
                statement=f"{policy.name}: device is compliant",
                why_not=f"rejected — {report.detail}",
                evidence_against=(item.id,),
            ),
        )
        return RuleOutcome(
            conclusion=f"{policy.name}: non-compliant — {report.detail}.",
            conclusion_kind=CONCLUSION_FAIL,
            base_confidence=policy.base_confidence,
            factors=factors,
            evidence_ids=(item.id,),
            steps=steps,
            recommendations=(recommendation,),
            rejected=rejected,
            severity=policy.severity,
            has_evidence=True,
            confidence_basis=basis,
        )

    def _not_applicable_outcome(self, item, report, factors, basis) -> RuleOutcome:
        policy = self._policy
        steps = (
            ReasoningStep(
                rule_id=policy.policy_id,
                statement=(
                    f"{policy.name} does not apply to this device: {report.detail}."
                ),
                evidence_ids=(item.id,),
            ),
        )
        return RuleOutcome(
            conclusion=f"{policy.name}: not applicable — {report.detail}.",
            conclusion_kind=CONCLUSION_PASS,
            base_confidence=policy.base_confidence,
            factors=factors,
            evidence_ids=(item.id,),
            steps=steps,
            recommendations=(),
            rejected=(),
            severity=SEVERITY_INFO,
            has_evidence=True,
            confidence_basis=basis,
        )

    def _unknown_outcome(self, gaps: tuple[EvidenceGap, ...]) -> RuleOutcome:
        policy = self._policy
        required = policy.check.evidence
        relevant = tuple(g for g in gaps if g.kind == required) or (
            EvidenceGap(
                kind=required,
                subject="",
                why=GAP_NOT_COLLECTED,
                detail=f"no {required} evidence was collected for this device",
            ),
        )
        step = ReasoningStep(
            rule_id=policy.policy_id,
            statement=(
                f"Cannot evaluate {policy.name}: the required evidence "
                f"({required}) was not collected. Atlas reports Unknown rather "
                f"than guessing a verdict."
            ),
        )
        return RuleOutcome(
            conclusion=(
                f"{policy.name}: unknown — required evidence ({required}) "
                f"is not available."
            ),
            conclusion_kind=CONCLUSION_UNKNOWN,
            base_confidence=policy.base_confidence,
            factors=(),
            evidence_ids=(),
            steps=(step,),
            gaps=relevant,
            recommendations=(),
            rejected=(),
            severity=SEVERITY_INFO,
            has_evidence=False,
            confidence_basis="no evidence available to judge this policy",
        )

    # -- helpers -----------------------------------------------------------

    def _evidence_for(self, evidence: tuple[Evidence, ...]) -> Evidence | None:
        for item in evidence:
            if item.kind == self._policy.check.evidence:
                return item
        return None

    def _steps(self, policy: Policy, report: MatchReport, *, verdict: str) -> tuple[ReasoningStep, ...]:
        steps = [
            ReasoningStep(
                rule_id=policy.policy_id,
                statement=(
                    f"Applied operator '{report.operator}' over "
                    f"{policy.check.evidence}: policy {verdict} ({report.detail})."
                ),
            )
        ]
        for hit in report.hits[:8]:
            steps.append(
                ReasoningStep(
                    rule_id=policy.policy_id,
                    statement=f"L{hit.line}: {hit.text}",
                )
            )
        return tuple(steps)
