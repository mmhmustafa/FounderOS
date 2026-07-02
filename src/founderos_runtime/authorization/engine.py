"""Pure deterministic authorization of validated ExecutionPlans."""

from __future__ import annotations

from typing import Any

from founderos_runtime.planner.execution_plan import ExecutionPlan
from founderos_runtime.validation import ValidationReport

from .decision import AuthorizationDecision, PolicyResult
from .exceptions import AuthorizationError
from .policies import (
    HIGH_RISK_CAPABILITIES,
    KNOWN_CAPABILITIES,
    POLICY_ORDER,
    declared_approval_ids,
    requested_capabilities,
    transition_approval_ids,
)


AUTHORIZATION_ENGINE_VERSION = "1.0.0"


class AuthorizationEngine:
    """Apply the fixed PR-010 plan policies with deny-overrides behavior."""

    def authorize(
        self,
        plan: ExecutionPlan,
        validation: ValidationReport | None,
    ) -> AuthorizationDecision:
        if not isinstance(plan, ExecutionPlan):
            raise AuthorizationError("authorize requires an ExecutionPlan")

        capabilities = requested_capabilities(plan)
        approvals = declared_approval_ids(plan)
        transition_approvals = transition_approval_ids(plan)
        results: list[PolicyResult] = []

        if validation is None or not isinstance(validation, ValidationReport) or not validation.valid:
            results.append(
                PolicyResult("deny_missing_validation", "deny", "valid ValidationReport required")
            )
            return self._decision(False, "MISSING_OR_INVALID_VALIDATION", (), results, plan, capabilities)
        results.append(PolicyResult("deny_missing_validation", "pass", "validation is valid"))

        unknown = tuple(sorted(set(capabilities) - KNOWN_CAPABILITIES))
        if unknown:
            results.append(
                PolicyResult(
                    "deny_unknown_capability",
                    "deny",
                    f"unknown capability: {unknown[0]}",
                )
            )
            return self._decision(False, "UNKNOWN_CAPABILITY", (), results, plan, capabilities)
        results.append(PolicyResult("deny_unknown_capability", "pass", "all capabilities known"))

        high_risk = tuple(sorted(set(capabilities) & HIGH_RISK_CAPABILITIES))
        required = tuple(sorted(set(approvals) | set(transition_approvals))) if high_risk else ()
        if high_risk and not required:
            results.append(
                PolicyResult(
                    "require_approval_for_high_risk",
                    "deny",
                    "high-risk capability has no declared Approval gate",
                )
            )
            return self._decision(False, "HIGH_RISK_APPROVAL_MISSING", (), results, plan, capabilities)
        results.append(
            PolicyResult(
                "require_approval_for_high_risk",
                "require" if high_risk else "pass",
                "Approval gate declared" if high_risk else "plan has no high-risk capability",
            )
        )
        results.append(PolicyResult("allow_safe_plan", "allow", "validated plan is allowed"))
        return self._decision(True, "ALLOW_SAFE_PLAN", required, results, plan, capabilities)

    def summary(self) -> dict[str, Any]:
        return {
            "authorization_engine_version": AUTHORIZATION_ENGINE_VERSION,
            "policies": list(POLICY_ORDER),
            "default_effect": "deny",
            "deterministic": True,
            "read_only": True,
        }

    @staticmethod
    def _decision(
        allowed: bool,
        reason: str,
        required_approvals: tuple[str, ...],
        results: list[PolicyResult],
        plan: ExecutionPlan,
        capabilities: tuple[str, ...],
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            allowed=allowed,
            reason=reason,
            required_approvals=required_approvals,
            policy_results=tuple(results),
            metadata={
                "authorization_engine_version": AUTHORIZATION_ENGINE_VERSION,
                "workflow_id": plan.workflow_id,
                "capabilities": list(capabilities),
                "policy_order": list(POLICY_ORDER),
                "human_approval_performed": False,
            },
        )

