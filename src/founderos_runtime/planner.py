"""Deterministic, read-only orchestration planning for FounderOS."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .execution_context import ExecutionContext
from .planning_rules import PLANNING_RULES, PlanningRule
from .state_machine import KNOWN_STATES, RouteRequirement, StateMachine


class PlanningError(ValueError):
    """Execution planning cannot continue from the supplied context."""


@dataclass(frozen=True)
class ExecutionPlan:
    current_state: str
    recommended_workflow: str | None
    required_artifacts: tuple[str, ...]
    missing_artifacts: tuple[str, ...]
    recommended_agents: tuple[str, ...]
    allowed_transitions: tuple[str, ...]
    blocked_reason: str | None
    quality_gate_requirements: tuple[str, ...]
    next_state_candidate: str | None
    confidence_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArtifactPlanner:
    """Compare required artifact types with approved completed artifacts."""

    def required(self, rule: PlanningRule) -> tuple[str, ...]:
        return tuple(sorted(set(rule.required_artifacts)))

    def missing(self, context: ExecutionContext, rule: PlanningRule) -> tuple[str, ...]:
        completed = set(context.completed_artifacts)
        return tuple(artifact for artifact in self.required(rule) if artifact not in completed)


class AgentRouter:
    """Return stable agent-role recommendations without invoking agents or models."""

    def recommend(self, rule: PlanningRule) -> tuple[str, ...]:
        return tuple(sorted(set(rule.agent_roles)))


class WorkflowSelector:
    """Select a canonical workflow and explain why progress is blocked."""

    def __init__(self, state_machine: StateMachine) -> None:
        self.state_machine = state_machine

    def select(
        self,
        context: ExecutionContext,
        rule: PlanningRule,
        missing_artifacts: tuple[str, ...],
    ) -> tuple[str | None, tuple[str, ...], str | None]:
        allowed = self.state_machine.allowed_transitions(context.current_state)
        if rule.next_state is not None and rule.next_state not in allowed:
            raise PlanningError(
                f"Planner rule {context.current_state} -> {rule.next_state} is not allowed by the State Machine"
            )
        if rule.workflow is None:
            return None, allowed, "Project is in terminal state SCALING"
        if missing_artifacts:
            names = ", ".join(missing_artifacts)
            return rule.workflow, allowed, f"Missing required approved artifacts: {names}"
        return rule.workflow, allowed, None


class Planner:
    """Combine read-only context, artifacts, routing, agents, and state rules."""

    def __init__(self, state_machine: StateMachine) -> None:
        self.state_machine = state_machine
        self.artifacts = ArtifactPlanner()
        self.agents = AgentRouter()
        self.workflows = WorkflowSelector(state_machine)

    def plan(self, context: ExecutionContext) -> ExecutionPlan:
        if context.current_state not in KNOWN_STATES:
            raise PlanningError(f"Unknown project state: {context.current_state}")
        try:
            rule = PLANNING_RULES[context.current_state]
        except KeyError as error:
            raise PlanningError(f"No planning rule for state: {context.current_state}") from error

        required = self.artifacts.required(rule)
        missing = self.artifacts.missing(context, rule)
        workflow, allowed, blocked = self.workflows.select(context, rule, missing)
        route_requirement = (
            self.state_machine.route_requirement(context.current_state, rule.next_state)
            if rule.next_state is not None
            else None
        )
        quality_gates = self._quality_gates(route_requirement, required)
        return ExecutionPlan(
            current_state=context.current_state,
            recommended_workflow=workflow,
            required_artifacts=required,
            missing_artifacts=missing,
            recommended_agents=self.agents.recommend(rule),
            allowed_transitions=allowed,
            blocked_reason=blocked,
            quality_gate_requirements=quality_gates,
            next_state_candidate=rule.next_state,
            confidence_score=1.0,
        )

    @staticmethod
    def _quality_gates(
        requirement: RouteRequirement | None, required_artifacts: tuple[str, ...]
    ) -> tuple[str, ...]:
        if requirement is None:
            return ()
        gates = ["project_active", "project_revision_matches", "state_matches", "transition_allowed"]
        if requirement.workflow_statuses:
            statuses = ",".join(sorted(requirement.workflow_statuses))
            gates.append(f"workflow_status:{statuses}")
        if required_artifacts:
            gates.extend(f"approved_artifact:{artifact}" for artifact in required_artifacts)
        if requirement.evaluation:
            gates.append("evaluation_passed:confidence>=0.70")
        if requirement.decision:
            gates.append("decision_recorded:approved")
        if requirement.approval:
            gates.append("human_approval:approved_and_current")
        return tuple(gates)
