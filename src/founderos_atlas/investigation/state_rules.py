"""State rules — health as DATA, judged by the CORTEX engine (PR-173).

Before this module, Atlas's notion of "healthy" lived in two inline
Python expressions (``_session_is_established`` for BGP, a bare
``startswith("full")`` for OSPF) — precisely the subject-specific-
validator antipattern PR-172 rejected for configuration. Here a health
rule is a declarative :class:`StateRuleDefinition` over a **closed
operator vocabulary**, and :class:`StateRule` is the second adapter of
CORTEX's evidence-agnostic ``Rule`` protocol (``PolicyRule`` being the
first). Both adapters feed the identical engine, so state verdicts
inherit the confidence calculus, the result schema, provenance, the
four dispositions, the no-evidence-⇒-unknown guarantee and PR-172's
``applicable`` flag — with no new scoring machinery.

The adapter judges STRUCTURED observations carried in
``Evidence.payload`` — never text, never a regex over serialized
records. State comparison folds case and reads only the value before
any ``/`` — ``Full/DR`` and ``Full/BDR`` are the same adjacency state
wearing its role suffix, which is identity information, not health.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from founderos_atlas.reasoning import (
    CONCLUSION_FAIL,
    CONCLUSION_PASS,
    CONCLUSION_UNKNOWN,
    FAMILY_HEALTH,
    QUESTION_ASSESS,
    Evidence,
    EvidenceGap,
    Recommendation,
    ReasoningStep,
    RejectedConclusion,
    RuleOutcome,
    direct_observation,
)
from founderos_atlas.reasoning.evidence import GAP_NOT_COLLECTED
from founderos_atlas.reasoning.result import SEVERITY_HIGH, SEVERITY_INFO

from .state import (
    STATE_KIND_BGP_SESSIONS,
    STATE_KIND_INTERFACE_STATUS,
    STATE_KIND_OSPF_ADJACENCIES,
)


# Provenance for every state verdict — the state analogue of a policy
# pack's ``pack_id@version``.
STATE_RULES_VERSION = "atlas-state-rules@1.0"

# -- the closed operator vocabulary ------------------------------------------
#
# Few and boring, exactly like the policy matcher's: adding a rule is
# data; adding an operator is a rare, reviewed change HERE. This is the
# boundary that keeps per-protocol health functions from returning.

OP_ALL_IN_STATES = "all_in_states"      # every observation in an expected state
OP_NONE_IN_STATES = "none_in_states"    # no observation in a forbidden state
OP_MIN_COUNT = "min_count"              # at least N observations exist
OP_RATIO_AT_LEAST = "ratio_at_least"    # expected-state share >= threshold

STATE_OPERATORS = (
    OP_ALL_IN_STATES,
    OP_NONE_IN_STATES,
    OP_MIN_COUNT,
    OP_RATIO_AT_LEAST,
)


def canonical_state(value: Any) -> str:
    """Fold case; strip a role suffix. ``Full/DR`` -> ``full``."""

    return str(value or "").casefold().split("/")[0].strip()


@dataclass(frozen=True)
class StateCheck:
    """The declarative body of a state rule. Pure data."""

    kind: str                              # observation kind judged
    operator: str
    expected_states: tuple[str, ...] = ()
    threshold: float | None = None         # min_count / ratio_at_least
    state_field: str = "state"
    # Observations in these states are EXCLUDED from judgement, by
    # name — "admin-down" is configured intent, not a failure.
    ignore_states: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.operator not in STATE_OPERATORS:
            raise ValueError(
                "operator must be one of " + ", ".join(STATE_OPERATORS)
            )
        if self.operator in (OP_MIN_COUNT, OP_RATIO_AT_LEAST):
            if self.threshold is None:
                raise ValueError(f"{self.operator} requires a threshold")
        elif not self.expected_states:
            raise ValueError(f"{self.operator} requires expected_states")


@dataclass(frozen=True)
class StateRuleDefinition:
    """One health rule, fully declared — the state twin of ``Policy``."""

    rule_id: str
    name: str
    description: str
    subject: str                           # subject registry key
    check: StateCheck
    severity: str
    expected_state: str                    # operator sentence: what healthy IS
    recommendation: str
    remediation: str
    base_confidence: float = 0.75

    def __post_init__(self) -> None:
        for field_name in ("rule_id", "name", "subject", "expected_state"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not 0 <= self.base_confidence <= 1:
            raise ValueError("base_confidence must be between 0 and 1")


# -- the installed rules (data; grows per subject, never per vendor) ----------

STATE_RULES: tuple[StateRuleDefinition, ...] = (
    StateRuleDefinition(
        rule_id="STATE-BGP-001",
        name="BGP sessions established",
        description="Every observed BGP session should be in the "
                    "Established state.",
        subject="bgp",
        check=StateCheck(
            kind=STATE_KIND_BGP_SESSIONS,
            operator=OP_ALL_IN_STATES,
            # "estab" and "up" are vendor spellings of the same healthy
            # state — the vocabulary the deleted inline predicate held,
            # preserved HERE as data.
            expected_states=("established", "estab", "up"),
        ),
        severity=SEVERITY_HIGH,
        expected_state="Every observed BGP session is Established.",
        recommendation="Investigate sessions that are not Established — "
                       "a configured peer that cannot reach Established "
                       "is a broken peering, not a cosmetic detail.",
        remediation="Check reachability to the peer address, the "
                    "remote-as, and filters on both ends.",
    ),
    StateRuleDefinition(
        rule_id="STATE-OSPF-001",
        name="OSPF adjacencies full",
        description="Every observed OSPF adjacency should be in the "
                    "Full state (role suffixes like /DR are identity, "
                    "not health).",
        subject="ospf",
        check=StateCheck(
            kind=STATE_KIND_OSPF_ADJACENCIES,
            operator=OP_ALL_IN_STATES,
            expected_states=("full",),
        ),
        severity=SEVERITY_HIGH,
        expected_state="Every observed OSPF adjacency is Full.",
        recommendation="Investigate adjacencies stuck below Full — "
                       "Init/ExStart usually mean MTU, authentication "
                       "or area mismatches.",
        remediation="Compare interface MTU, hello/dead timers, area ids "
                    "and authentication on both neighbours.",
    ),
    StateRuleDefinition(
        rule_id="STATE-IFACE-001",
        name="Enabled interfaces up",
        description="Every enabled interface should be operationally "
                    "up; administratively-down interfaces are "
                    "intentionally down and are excluded by name.",
        subject="interfaces",
        check=StateCheck(
            kind=STATE_KIND_INTERFACE_STATUS,
            operator=OP_ALL_IN_STATES,
            expected_states=("up",),
            ignore_states=("admin-down",),
        ),
        severity=SEVERITY_HIGH,
        expected_state="Every enabled interface is up/up.",
        recommendation="Investigate enabled interfaces reporting down — "
                       "a link nobody shut down should be carrying "
                       "traffic.",
        remediation="Check the physical link, the far end, and error "
                    "counters on the interface.",
    ),
)

_RULES_BY_ID = {item.rule_id: item for item in STATE_RULES}


def rules_for_kind(kind: str) -> tuple[StateRuleDefinition, ...]:
    return tuple(
        item for item in STATE_RULES if item.check.kind == str(kind or "")
    )


def rules_for_subject(subject: str) -> tuple[StateRuleDefinition, ...]:
    return tuple(
        item for item in STATE_RULES if item.subject == str(subject or "")
    )


def state_rule(rule_id: str) -> StateRuleDefinition | None:
    return _RULES_BY_ID.get(str(rule_id or ""))


# -- the CORTEX adapter -------------------------------------------------------


def _item_label(item: dict[str, Any]) -> str:
    """One observation, named the way an operator would name it."""

    if item.get("peer_address"):
        return f"peer {item['peer_address']}"
    if item.get("neighbor_router_id"):
        label = f"neighbour {item['neighbor_router_id']}"
        if item.get("local_interface"):
            label += f" on {item['local_interface']}"
        return label
    if item.get("name"):
        return str(item["name"])
    return "observation"


class StateRule:
    """Adapts one :class:`StateRuleDefinition` to the CORTEX ``Rule``
    protocol — the state twin of ``PolicyRule``."""

    def __init__(self, definition: StateRuleDefinition) -> None:
        self._definition = definition

    # -- Rule protocol -----------------------------------------------------

    @property
    def rule_id(self) -> str:
        return self._definition.rule_id

    @property
    def family(self) -> str:
        return FAMILY_HEALTH

    @property
    def question_kinds(self) -> tuple[str, ...]:
        return (QUESTION_ASSESS,)

    @property
    def definition(self) -> StateRuleDefinition:
        return self._definition

    def applies(self, evidence: tuple[Evidence, ...]) -> bool:
        return any(
            e.kind == self._definition.check.kind for e in evidence
        )

    def evaluate(
        self, evidence: tuple[Evidence, ...], gaps: tuple[EvidenceGap, ...]
    ) -> RuleOutcome:
        definition = self._definition
        check = definition.check
        item = next(
            (e for e in evidence if e.kind == check.kind), None
        )

        # No evidence of the required kind -> honest unknown, never a
        # guess (identical to PolicyRule's discipline).
        if item is None:
            return self._unknown_outcome(gaps)

        observations = tuple(
            row for row in (item.payload.get("items") or ())
            if isinstance(row, dict)
        )
        if not observations:
            # The device holds NO observations of this kind: it does
            # not run the subject. Not applicable — never healthy,
            # never failing (PR-172 R1 on the state axis).
            return self._not_applicable_outcome(item)

        ignored = tuple(
            row for row in observations
            if canonical_state(row.get(check.state_field))
            in check.ignore_states
        )
        judged = tuple(
            row for row in observations if row not in ignored
        )
        if not judged:
            # Everything present is intentionally excluded (e.g. every
            # interface is admin-down) — nothing to judge.
            return self._not_applicable_outcome(
                item,
                detail=f"all {len(observations)} observation(s) are in "
                       "states this rule excludes by name "
                       f"({', '.join(check.ignore_states)})",
            )

        offenders = self._offenders(check, judged)
        matched, detail = self._judge(check, judged, offenders)
        if matched:
            return self._pass_outcome(item, judged, ignored, detail)
        return self._fail_outcome(item, judged, offenders, detail)

    # -- judgement (pure functions of observations) ------------------------

    @staticmethod
    def _offenders(check: StateCheck, judged) -> tuple[dict, ...]:
        expected = tuple(canonical_state(s) for s in check.expected_states)
        if check.operator == OP_NONE_IN_STATES:
            return tuple(
                row for row in judged
                if canonical_state(row.get(check.state_field)) in expected
            )
        return tuple(
            row for row in judged
            if canonical_state(row.get(check.state_field)) not in expected
        )

    @staticmethod
    def _judge(check: StateCheck, judged, offenders) -> tuple[bool, str]:
        total = len(judged)
        if check.operator == OP_ALL_IN_STATES:
            ok = not offenders
            return ok, (
                f"all {total} observation(s) are in an expected state"
                if ok else
                f"{len(offenders)} of {total} observation(s) are not in "
                f"an expected state ({', '.join(check.expected_states)})"
            )
        if check.operator == OP_NONE_IN_STATES:
            ok = not offenders
            return ok, (
                f"no observation is in a forbidden state"
                if ok else
                f"{len(offenders)} of {total} observation(s) are in a "
                f"forbidden state ({', '.join(check.expected_states)})"
            )
        if check.operator == OP_MIN_COUNT:
            ok = total >= int(check.threshold or 0)
            return ok, (
                f"{total} observation(s) present "
                f"(minimum {int(check.threshold or 0)})"
            )
        # OP_RATIO_AT_LEAST
        in_state = total - len(offenders)
        ratio = (in_state / total) if total else 0.0
        ok = ratio >= float(check.threshold or 0.0)
        return ok, (
            f"{in_state} of {total} observation(s) in an expected state "
            f"({ratio:.0%}; required {float(check.threshold or 0):.0%})"
        )

    # -- outcome builders (mirroring PolicyRule) ---------------------------

    def _steps(self, item, verdict: str, detail: str,
               offenders=()) -> tuple[ReasoningStep, ...]:
        definition = self._definition
        steps = [ReasoningStep(
            rule_id=definition.rule_id,
            statement=(
                f"Applied operator '{definition.check.operator}' over "
                f"{definition.check.kind}: rule {verdict} ({detail})."
            ),
            evidence_ids=(item.id,),
        )]
        for row in offenders[:8]:
            steps.append(ReasoningStep(
                rule_id=definition.rule_id,
                statement=(
                    f"{_item_label(row)}: state "
                    f"{row.get(definition.check.state_field) or 'unknown'}"
                ),
            ))
        return tuple(steps)

    def _factors(self, item):
        return (direct_observation(
            "evaluated against observations collected from the device "
            f"({', '.join(item.payload.get('source_commands') or ()) or 'discovery'})",
            (item.id,),
        ),)

    _BASIS = "direct operational observations from the last discovery"

    def _pass_outcome(self, item, judged, ignored, detail) -> RuleOutcome:
        definition = self._definition
        note = (
            f" ({len(ignored)} excluded by name)" if ignored else ""
        )
        return RuleOutcome(
            conclusion=f"{definition.name}: healthy — {detail}{note}.",
            conclusion_kind=CONCLUSION_PASS,
            base_confidence=definition.base_confidence,
            factors=self._factors(item),
            evidence_ids=(item.id,),
            steps=self._steps(item, "satisfied", detail),
            recommendations=(),
            rejected=(RejectedConclusion(
                statement=f"{definition.name}: degraded",
                why_not="rejected — every judged observation is in an "
                        "expected state",
                evidence_against=(item.id,),
            ),),
            severity=SEVERITY_INFO,
            has_evidence=True,
            confidence_basis=self._BASIS,
        )

    def _fail_outcome(self, item, judged, offenders, detail) -> RuleOutcome:
        definition = self._definition
        recommendation = Recommendation(
            action=definition.remediation or definition.recommendation,
            rationale=(
                f"{definition.expected_state} Observed: {detail}."
            ).strip(),
            severity=definition.severity,
        )
        return RuleOutcome(
            conclusion=f"{definition.name}: degraded — {detail}.",
            conclusion_kind=CONCLUSION_FAIL,
            base_confidence=definition.base_confidence,
            factors=self._factors(item),
            evidence_ids=(item.id,),
            steps=self._steps(item, "violated", detail, offenders),
            recommendations=(recommendation,),
            rejected=(RejectedConclusion(
                statement=f"{definition.name}: healthy",
                why_not=f"rejected — {detail}",
                evidence_against=(item.id,),
            ),),
            severity=definition.severity,
            has_evidence=True,
            confidence_basis=self._BASIS,
        )

    def _not_applicable_outcome(self, item, detail: str = "") -> RuleOutcome:
        definition = self._definition
        detail = detail or (
            "the device reports no observations of this kind — it does "
            "not run this subject"
        )
        return RuleOutcome(
            conclusion=f"{definition.name}: not applicable — {detail}.",
            conclusion_kind=CONCLUSION_PASS,
            base_confidence=definition.base_confidence,
            factors=self._factors(item),
            evidence_ids=(item.id,),
            steps=(ReasoningStep(
                rule_id=definition.rule_id,
                statement=(
                    f"{definition.name} does not apply: {detail}."
                ),
                evidence_ids=(item.id,),
            ),),
            recommendations=(),
            rejected=(),
            severity=SEVERITY_INFO,
            has_evidence=True,
            confidence_basis=self._BASIS,
            applicable=False,
        )

    def _unknown_outcome(self, gaps) -> RuleOutcome:
        definition = self._definition
        required = definition.check.kind
        relevant = tuple(
            gap for gap in gaps if gap.kind == required
        ) or (EvidenceGap(
            kind=required,
            subject="",
            why=GAP_NOT_COLLECTED,
            detail=f"no {required} observations were collected for "
                   "this device",
        ),)
        return RuleOutcome(
            conclusion=(
                f"{definition.name}: unknown — required observations "
                f"({required}) are not available."
            ),
            conclusion_kind=CONCLUSION_UNKNOWN,
            base_confidence=definition.base_confidence,
            factors=(),
            evidence_ids=(),
            steps=(ReasoningStep(
                rule_id=definition.rule_id,
                statement=(
                    f"Cannot evaluate {definition.name}: the required "
                    f"observations ({required}) were not collected. "
                    "Atlas reports Unknown rather than guessing."
                ),
            ),),
            gaps=relevant,
            recommendations=(),
            rejected=(),
            severity=SEVERITY_INFO,
            has_evidence=False,
            confidence_basis="no observations available to judge this rule",
        )


__all__ = [
    "OP_ALL_IN_STATES",
    "OP_MIN_COUNT",
    "OP_NONE_IN_STATES",
    "OP_RATIO_AT_LEAST",
    "STATE_OPERATORS",
    "STATE_RULES",
    "STATE_RULES_VERSION",
    "StateCheck",
    "StateRule",
    "StateRuleDefinition",
    "canonical_state",
    "rules_for_kind",
    "rules_for_subject",
    "state_rule",
]
