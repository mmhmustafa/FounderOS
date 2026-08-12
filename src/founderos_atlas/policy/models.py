"""Policy model — the reusable, data-driven definition (PR-047 Part 1).

Atlas does not hard-code compliance; it *evaluates policies*. A policy is data:
what to look for, what evidence proves it, how severe a violation is, and how to
fix it. Compliance is then just one pack of these; Security, CIS, STIG, PCI,
customer packs (Part 6) are more data over the same engine.

Every policy result is a projection of the CORTEX :class:`ReasoningResult` — the
policy layer chooses the question and renders the answer, but the conclusion,
confidence, evidence, and reasoning are the engine's, unchanged (Part 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from founderos_atlas.reasoning import (
    CONCLUSION_FAIL,
    CONCLUSION_PASS,
    CONCLUSION_UNKNOWN,
    CONCLUSION_WARNING,
    ReasoningResult,
)
from founderos_atlas.reasoning.result import SEVERITIES

from .matcher import PolicyCheck
from .applicability import (
    INTENT_REQUIRED,
    POLICY_INTENTS,
    ApplicabilityDecision,
    PolicyApplicability,
)


# -- categories (Part 5; open — a new category needs no redesign) ------------

CATEGORY_CONFIGURATION = "configuration"
CATEGORY_ROUTING = "routing"
CATEGORY_SECURITY = "security"
CATEGORY_IDENTITY = "identity"
CATEGORY_MANAGEMENT = "management"
CATEGORY_OPERATIONAL = "operational"
CATEGORY_SERVICES = "services"
CATEGORY_INVENTORY = "inventory"

CATEGORIES = (
    CATEGORY_CONFIGURATION,
    CATEGORY_ROUTING,
    CATEGORY_SECURITY,
    CATEGORY_IDENTITY,
    CATEGORY_MANAGEMENT,
    CATEGORY_OPERATIONAL,
    CATEGORY_SERVICES,
    CATEGORY_INVENTORY,
)


# -- status (Part 4; the four dispositions, mapped to conclusion kinds) ------

STATUS_PASSED = CONCLUSION_PASS
STATUS_FAILED = CONCLUSION_FAIL
STATUS_WARNING = CONCLUSION_WARNING
STATUS_UNKNOWN = CONCLUSION_UNKNOWN

STATUS_LABELS = {
    STATUS_PASSED: "Passed",
    STATUS_FAILED: "Failed",
    STATUS_WARNING: "Warning",
    STATUS_UNKNOWN: "Unknown",
}


@dataclass(frozen=True)
class Policy:
    """One enterprise policy. Data-driven: the ``check`` is a declarative spec,
    never code. ``base_confidence`` is the calculus starting point the engine
    prices factors onto; the policy never computes a final score itself."""

    policy_id: str
    name: str
    description: str
    category: str
    severity: str
    check: PolicyCheck
    evidence_required: tuple[str, ...]
    reasoning_strategy: str
    expected_state: str
    recommendation: str
    remediation: str
    tags: tuple[str, ...] = ()
    version: str = "1.0"
    author: str = "Atlas Starter Pack"
    base_confidence: float = 0.70
    intent: str = INTENT_REQUIRED
    applicability: PolicyApplicability = field(
        default_factory=PolicyApplicability
    )

    def __post_init__(self) -> None:
        for name in (
            "policy_id", "name", "category", "severity", "expected_state",
            "recommendation", "remediation",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.intent not in POLICY_INTENTS:
            raise ValueError(
                "intent must be one of " + ", ".join(POLICY_INTENTS)
            )
        if not isinstance(self.applicability, PolicyApplicability):
            raise ValueError("applicability must be a PolicyApplicability")
        if self.severity not in SEVERITIES:
            raise ValueError(
                "severity must be one of " + ", ".join(SEVERITIES)
            )
        if not 0 <= self.base_confidence <= 1:
            raise ValueError("base_confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "severity": self.severity,
            "check": self.check.to_dict(),
            "evidence_required": list(self.evidence_required),
            "reasoning_strategy": self.reasoning_strategy,
            "expected_state": self.expected_state,
            "recommendation": self.recommendation,
            "remediation": self.remediation,
            "tags": list(self.tags),
            "version": self.version,
            "author": self.author,
            "base_confidence": self.base_confidence,
            "intent": self.intent,
            "applicability": self.applicability.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Policy":
        return cls(
            policy_id=str(value["policy_id"]),
            name=str(value["name"]),
            description=str(value.get("description") or ""),
            category=str(value.get("category") or CATEGORY_CONFIGURATION),
            severity=str(value["severity"]),
            check=PolicyCheck.from_dict(value["check"]),
            evidence_required=tuple(value.get("evidence_required") or ()),
            reasoning_strategy=str(value.get("reasoning_strategy") or ""),
            expected_state=str(value.get("expected_state") or ""),
            recommendation=str(value.get("recommendation") or ""),
            remediation=str(value.get("remediation") or ""),
            tags=tuple(value.get("tags") or ()),
            version=str(value.get("version") or "1.0"),
            author=str(value.get("author") or ""),
            base_confidence=float(value.get("base_confidence") or 0.70),
            intent=str(value.get("intent") or INTENT_REQUIRED),
            applicability=PolicyApplicability.from_dict(
                value.get("applicability")
            ),
        )


@dataclass(frozen=True)
class PolicyPack:
    """A named, versioned set of policies. Installing a future pack (Cisco
    Enterprise, PCI-DSS, a customer's own) is exactly this object with different
    policies — no engine change (Part 6)."""

    pack_id: str
    name: str
    description: str
    version: str
    author: str
    policies: tuple[Policy, ...]

    def __post_init__(self) -> None:
        for name in ("pack_id", "name", "version", "author"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.policies, tuple):
            raise ValueError("policies must be a tuple")
        identifiers = [policy.policy_id for policy in self.policies]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("policy ids must be unique within a pack")

    def categories(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for policy in self.policies:
            seen.setdefault(policy.category, None)
        return tuple(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "policy_count": len(self.policies),
            "categories": list(self.categories()),
            "policies": [p.to_dict() for p in self.policies],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PolicyPack":
        return cls(
            pack_id=str(value["pack_id"]),
            name=str(value["name"]),
            description=str(value.get("description") or ""),
            version=str(value["version"]),
            author=str(value["author"]),
            policies=tuple(
                Policy.from_dict(item)
                for item in value.get("policies") or ()
            ),
        )


@dataclass(frozen=True)
class PolicyEvaluation:
    """One policy evaluated against one device — a :class:`ReasoningResult`
    plus policy ergonomics (status, the masked config snippet). The reasoning
    content *is* the engine's result; nothing is recomputed here."""

    policy: Policy
    device_id: str
    hostname: str
    network: str
    result: ReasoningResult
    config_snippet: tuple[str, ...] = ()
    applicability: ApplicabilityDecision = field(
        default_factory=lambda: ApplicabilityDecision(
            True,
            "Applicable to every device; no targeting selector is configured.",
        )
    )
    device_context: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return self.result.conclusion_kind

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status.title())

    @property
    def passed(self) -> bool:
        return self.status == STATUS_PASSED

    @property
    def applicable(self) -> bool:
        """Whether this policy really applied to this device (PR-172, R1).

        Two independent gates, both already decided upstream and merely
        read here: the targeting selector (``PolicyApplicability``) and
        the check's own antecedent (a device with no ``router bgp`` is
        not judged by a BGP rule). Aggregations that answer "is X
        compliant?" must exclude non-applicable evaluations from the
        judged counts — not applicable is a third outcome, never a pass.
        """

        return bool(
            getattr(self.result, "applicable", True)
            and self.applicability.applicable
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.to_dict(),
            "device_id": self.device_id,
            "hostname": self.hostname,
            "network": self.network,
            "status": self.status,
            "status_label": self.status_label,
            "applicable": self.applicable,
            "config_snippet": list(self.config_snippet),
            "applicability": self.applicability.to_dict(),
            "device_context": dict(self.device_context),
            "result": self.result.to_dict(),
        }


@dataclass(frozen=True)
class PolicyReport:
    """The whole evaluation, aggregated for the Policy page (Part 9).

    ``score`` is the compliance score: passed / (passed + failed + warning),
    over the results where a verdict was actually reached. ``unknown`` results
    are excluded from the denominator — a policy Atlas could not judge must not
    silently count as a pass *or* a fail (never guess).

    **PR-174.2 — not applicable is excluded too.** A rule that did not
    apply to a device (its antecedent is absent, or a targeting selector
    excluded it) used to be counted as a PASS, because the engine gives
    the not-applicable outcome ``conclusion_kind = pass``. That inflated
    the headline compliance number with devices nothing was checked on:
    a fleet where one BGP speaker is broken and 81 devices never ran BGP
    scored ~99%. Absence of a subject is not compliance, so it now has
    its own count and appears in neither the numerator nor the
    denominator. ``PolicyEvaluation.applicable`` (PR-172) is the
    authority; ``status`` alone cannot distinguish the two.
    """

    pack: PolicyPack
    scope_label: str
    generated_at: str
    evaluations: tuple[PolicyEvaluation, ...]

    def _count(self, status: str) -> int:
        return sum(
            1 for e in self.evaluations
            if e.status == status and e.applicable
        )

    @property
    def passed(self) -> int:
        return self._count(STATUS_PASSED)

    @property
    def failed(self) -> int:
        return self._count(STATUS_FAILED)

    @property
    def warnings(self) -> int:
        return self._count(STATUS_WARNING)

    @property
    def unknown(self) -> int:
        # Absent evidence outranks applicability: Atlas could not even
        # establish whether the rule applies, so it stays unknown.
        return sum(
            1 for e in self.evaluations if e.status == STATUS_UNKNOWN
        )

    @property
    def not_applicable(self) -> int:
        """Evaluations the rule did not apply to — never a pass."""

        return sum(
            1 for e in self.evaluations
            if e.status != STATUS_UNKNOWN and not e.applicable
        )

    @property
    def total(self) -> int:
        return len(self.evaluations)

    @property
    def judged(self) -> int:
        """Evaluations where a real verdict was reached (excludes unknown
        and not-applicable)."""

        return self.passed + self.failed + self.warnings

    @property
    def score(self) -> int | None:
        """Compliance score as a whole-number percent over judged evaluations.

        ``None`` when nothing was judged (PR-178): a score of 0 asserts
        "everything judged failed", which is a measurement; an absence
        of judgeable evaluations is not. Mirrors ``posture_score`` so
        the engine and the page can never disagree about what an
        unjudged scope reads as.
        """

        if self.judged == 0:
            return None
        return int(round(100 * self.passed / self.judged))

    def devices(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for e in self.evaluations:
            seen.setdefault(e.hostname, None)
        return tuple(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack": {
                "pack_id": self.pack.pack_id,
                "name": self.pack.name,
                "version": self.pack.version,
                "author": self.pack.author,
                "policy_count": len(self.pack.policies),
            },
            "scope_label": self.scope_label,
            "generated_at": self.generated_at,
            "score": self.score,
            "passed": self.passed,
            "failed": self.failed,
            "warnings": self.warnings,
            "unknown": self.unknown,
            "not_applicable": self.not_applicable,
            "total": self.total,
            "judged": self.judged,
            "device_count": len(self.devices()),
            "evaluations": [e.to_dict() for e in self.evaluations],
        }
