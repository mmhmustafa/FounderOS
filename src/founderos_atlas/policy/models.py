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

from .matcher import PolicyCheck


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

    @property
    def status(self) -> str:
        return self.result.conclusion_kind

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status.title())

    @property
    def passed(self) -> bool:
        return self.status == STATUS_PASSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.to_dict(),
            "device_id": self.device_id,
            "hostname": self.hostname,
            "network": self.network,
            "status": self.status,
            "status_label": self.status_label,
            "config_snippet": list(self.config_snippet),
            "result": self.result.to_dict(),
        }


@dataclass(frozen=True)
class PolicyReport:
    """The whole evaluation, aggregated for the Policy page (Part 9).

    ``score`` is the compliance score: passed / (passed + failed + warning),
    over the results where a verdict was actually reached. ``unknown`` results
    are excluded from the denominator — a policy Atlas could not judge must not
    silently count as a pass *or* a fail (never guess).
    """

    pack: PolicyPack
    scope_label: str
    generated_at: str
    evaluations: tuple[PolicyEvaluation, ...]

    def _count(self, status: str) -> int:
        return sum(1 for e in self.evaluations if e.status == status)

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
        return self._count(STATUS_UNKNOWN)

    @property
    def total(self) -> int:
        return len(self.evaluations)

    @property
    def judged(self) -> int:
        """Evaluations where a real verdict was reached (excludes unknown)."""

        return self.passed + self.failed + self.warnings

    @property
    def score(self) -> int:
        """Compliance score as a whole-number percent over judged evaluations."""

        if self.judged == 0:
            return 0
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
            "total": self.total,
            "judged": self.judged,
            "device_count": len(self.devices()),
            "evaluations": [e.to_dict() for e in self.evaluations],
        }
