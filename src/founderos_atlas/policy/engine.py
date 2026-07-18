"""Policy evaluation pipeline (PR-047 Part 3).

Every policy follows the identical path::

    Enterprise Memory → Evidence Provider → Reasoning Engine → Policy Result

The :class:`PolicyEngine` is a thin orchestrator: it wires the CORTEX engine to
the Memory-backed evidence provider, compiles each policy to a rule, and asks
the engine one focused question per (device, policy). It computes no
confidence, invents no rule, and reaches past the engine to nothing — exactly
the "module is a presentation layer over the engine" contract (§8).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from founderos_atlas.enterprise_memory import EnterpriseMemory
from founderos_atlas.release import VERSION
from founderos_atlas.reasoning import (
    QUESTION_COMPLY,
    ReasoningEngine,
    ReasoningQuestion,
    RuleRegistry,
)
from founderos_atlas.reasoning.providers import MemoryEvidenceProvider

from .matcher import evaluate_check
from .models import Policy, PolicyEvaluation, PolicyPack, PolicyReport
from .packs import default_pack
from .rule import PolicyRule


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PolicyEngine:
    """Evaluates a policy pack against the devices in one scope's memory."""

    def __init__(
        self,
        pack: PolicyPack | None = None,
        *,
        clock: Callable[[], str] | None = None,
        atlas_version: str = VERSION,
    ) -> None:
        self._pack = pack or default_pack()
        self._clock = clock or _utc_now_iso
        self._atlas_version = atlas_version

    @property
    def pack(self) -> PolicyPack:
        return self._pack

    def _build_engine(self, memory: EnterpriseMemory) -> ReasoningEngine:
        registry = RuleRegistry()
        registry.register_all(PolicyRule(policy) for policy in self._pack.policies)
        provider = MemoryEvidenceProvider(memory)
        return ReasoningEngine(
            registry,
            (provider,),
            clock=self._clock,
            rule_set_version=f"{self._pack.pack_id}@{self._pack.version}",
            atlas_version=self._atlas_version,
        )

    def evaluate(
        self,
        memory: EnterpriseMemory,
        *,
        scope_label: str = "",
        as_of: str | None = None,
    ) -> PolicyReport:
        """Evaluate every policy against every device in ``memory``."""

        engine = self._build_engine(memory)
        generated_at = self._clock()
        evaluations: list[PolicyEvaluation] = []

        for device_id in memory.device_ids():
            device = memory.get_device_memory(device_id)
            hostname = device.hostname if device else device_id
            network = device.network if device else scope_label
            for policy in self._pack.policies:
                question = ReasoningQuestion(
                    kind=QUESTION_COMPLY,
                    subject=device_id,
                    scope=scope_label,
                    focus=policy.policy_id,
                    as_of=as_of,
                    consumer="policy",
                )
                result = engine.evaluate(question)
                evaluations.append(
                    PolicyEvaluation(
                        policy=policy,
                        device_id=device_id,
                        hostname=hostname,
                        network=network,
                        result=result,
                        config_snippet=self._snippet(policy, result),
                    )
                )

        evaluations.sort(key=_evaluation_sort_key)
        return PolicyReport(
            pack=self._pack,
            scope_label=scope_label,
            generated_at=generated_at,
            evaluations=tuple(evaluations),
        )

    def evaluate_scopes(
        self,
        memories,
        *,
        scope_label: str = "",
        as_of: str | None = None,
    ) -> PolicyReport:
        """Evaluate the pack across several scopes and merge into one report —
        the "All Networks" view. ``memories`` is an iterable of
        ``(label, EnterpriseMemory)`` pairs. Devices from different networks are
        listed side by side and never compared."""

        generated_at = self._clock()
        evaluations: list[PolicyEvaluation] = []
        for label, memory in memories:
            report = self.evaluate(memory, scope_label=label, as_of=as_of)
            evaluations.extend(report.evaluations)
        evaluations.sort(key=_evaluation_sort_key)
        return PolicyReport(
            pack=self._pack,
            scope_label=scope_label,
            generated_at=generated_at,
            evaluations=tuple(evaluations),
        )

    def evaluate_device(
        self,
        memory: EnterpriseMemory,
        device_id: str,
        policy: Policy,
        *,
        scope_label: str = "",
        as_of: str | None = None,
    ) -> PolicyEvaluation:
        """Evaluate a single policy against a single device — for detail views
        and targeted tests."""

        engine = self._build_engine(memory)
        device = memory.get_device_memory(device_id)
        hostname = device.hostname if device else device_id
        network = device.network if device else scope_label
        question = ReasoningQuestion(
            kind=QUESTION_COMPLY,
            subject=device_id,
            scope=scope_label,
            focus=policy.policy_id,
            as_of=as_of,
            consumer="policy",
        )
        result = engine.evaluate(question)
        return PolicyEvaluation(
            policy=policy,
            device_id=device_id,
            hostname=hostname,
            network=network,
            result=result,
            config_snippet=self._snippet(policy, result),
        )

    # -- helpers -----------------------------------------------------------

    def _snippet(self, policy: Policy, result) -> tuple[str, ...]:
        """The masked configuration lines behind the verdict (Part 9 "Config
        Snippet"). Derived from the evidence the engine actually used, so it can
        never disagree with the conclusion."""

        item = next(
            (e for e in result.evidence_used if e.kind == policy.check.evidence),
            None,
        )
        if item is None:
            return ()
        report = evaluate_check(policy.check, item.text)
        return tuple(f"L{hit.line}: {hit.text}" for hit in report.hits[:12])


def _evaluation_sort_key(evaluation: PolicyEvaluation):
    """Failed and warning results first (by severity), then by device, then
    policy — the order the Policy page wants: problems at the top."""

    from founderos_atlas.reasoning import severity_rank
    from .models import STATUS_FAILED, STATUS_UNKNOWN, STATUS_WARNING

    status_rank = {
        STATUS_FAILED: 0,
        STATUS_WARNING: 1,
        STATUS_UNKNOWN: 2,
    }.get(evaluation.status, 3)
    return (
        status_rank,
        severity_rank(evaluation.result.severity),
        evaluation.hostname.casefold(),
        evaluation.policy.policy_id,
    )
