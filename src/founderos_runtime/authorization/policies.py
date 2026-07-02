"""Deterministic plan capability and risk policy definitions."""

from __future__ import annotations

from founderos_runtime.planner.execution_plan import ExecutionPlan


POLICY_ORDER = (
    "deny_missing_validation",
    "deny_unknown_capability",
    "require_approval_for_high_risk",
    "allow_safe_plan",
)

STEP_CAPABILITIES = {
    "human_input": "input.reference",
    "agent_task": "provider.mock.invoke",
    "evaluation": "evaluation.run",
    "approval": "approval.request",
    "activity_request": "activity.request",
    "artifact_creation": "artifact.in_memory.create",
    "transition_request": "state.transition.request",
}

KNOWN_CAPABILITIES = frozenset(STEP_CAPABILITIES.values())
HIGH_RISK_CAPABILITIES = frozenset({"activity.request", "state.transition.request"})


def requested_capabilities(plan: ExecutionPlan) -> tuple[str, ...]:
    capabilities = {
        STEP_CAPABILITIES.get(step.type, f"step.{step.type}")
        for step in plan.steps
    }
    declared = plan.metadata.get("required_capabilities")
    if declared is not None:
        if not isinstance(declared, tuple | list):
            capabilities.add("<invalid>")
        else:
            capabilities.update(str(item) for item in declared)
    return tuple(sorted(capabilities))


def declared_approval_ids(plan: ExecutionPlan) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(item["id"])
            for item in plan.approvals
            if item.get("required") and isinstance(item.get("id"), str)
        )
    )


def transition_approval_ids(plan: ExecutionPlan) -> tuple[str, ...]:
    if plan.transition_request is None:
        return ()
    values = plan.transition_request.get("approval_refs", ())
    return tuple(sorted(str(item) for item in values))

