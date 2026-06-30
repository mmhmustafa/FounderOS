"""Guarded, atomic in-memory FounderOS state transitions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .errors import RecordNotFoundError, ReferenceIntegrityError
from .events import build_event
from .ids import new_id, utc_now
from .repositories import RuntimeRepositories


@dataclass(frozen=True)
class RouteRequirement:
    artifact_types: tuple[str, ...] = ()
    workflow_statuses: frozenset[str] = frozenset()
    evaluation: bool = False
    decision: bool = False
    approval: bool = False


ROUTES: dict[tuple[str, str], RouteRequirement] = {
    ("NO_PROJECT", "FOUNDER_SETUP"): RouteRequirement(workflow_statuses=frozenset({"queued", "running"})),
    ("FOUNDER_SETUP", "FOUNDER_BRIEF_COMPLETE"): RouteRequirement(
        artifact_types=("founder_brief",), workflow_statuses=frozenset({"succeeded"}), evaluation=True, approval=True
    ),
    ("FOUNDER_BRIEF_COMPLETE", "DISCOVERY_RUNNING"): RouteRequirement(
        workflow_statuses=frozenset({"running"}), approval=True
    ),
    ("DISCOVERY_RUNNING", "OPPORTUNITY_SELECTED"): RouteRequirement(
        artifact_types=("opportunity_report",), workflow_statuses=frozenset({"succeeded"}), decision=True, approval=True
    ),
    ("OPPORTUNITY_SELECTED", "VALIDATION_RUNNING"): RouteRequirement(
        workflow_statuses=frozenset({"running"}), approval=True
    ),
    ("VALIDATION_RUNNING", "VALIDATION_PASSED"): RouteRequirement(
        artifact_types=("validation_report",), workflow_statuses=frozenset({"succeeded"}), evaluation=True, approval=True
    ),
    ("VALIDATION_RUNNING", "DISCOVERY_RUNNING"): RouteRequirement(decision=True, approval=True),
    ("VALIDATION_PASSED", "PRODUCT_DESIGN_RUNNING"): RouteRequirement(
        workflow_statuses=frozenset({"running"}), approval=True
    ),
    ("PRODUCT_DESIGN_RUNNING", "PRD_COMPLETE"): RouteRequirement(
        artifact_types=("prd",), workflow_statuses=frozenset({"succeeded"}), decision=True, approval=True
    ),
    ("PRD_COMPLETE", "ARCHITECTURE_RUNNING"): RouteRequirement(
        workflow_statuses=frozenset({"running"}), approval=True
    ),
    ("ARCHITECTURE_RUNNING", "ARCHITECTURE_COMPLETE"): RouteRequirement(
        artifact_types=("architecture", "database_design", "api_specification", "security_model"),
        workflow_statuses=frozenset({"succeeded"}),
        approval=True,
    ),
    ("ARCHITECTURE_COMPLETE", "AI_DESIGN_RUNNING"): RouteRequirement(
        workflow_statuses=frozenset({"running"}), approval=True
    ),
    ("AI_DESIGN_RUNNING", "AI_ARCHITECTURE_COMPLETE"): RouteRequirement(
        artifact_types=("ai_architecture", "evaluation_plan"),
        workflow_statuses=frozenset({"succeeded"}),
        approval=True,
    ),
    ("AI_ARCHITECTURE_COMPLETE", "DEVELOPMENT_PLANNING"): RouteRequirement(
        workflow_statuses=frozenset({"running"}), approval=True
    ),
    ("DEVELOPMENT_PLANNING", "SPRINT_READY"): RouteRequirement(
        artifact_types=("sprint_plan", "implementation_backlog"),
        workflow_statuses=frozenset({"succeeded"}),
        approval=True,
    ),
    ("SPRINT_READY", "MVP_BUILDING"): RouteRequirement(approval=True),
    ("MVP_BUILDING", "QA_RUNNING"): RouteRequirement(workflow_statuses=frozenset({"running"}), approval=True),
    ("QA_RUNNING", "READY_FOR_BETA"): RouteRequirement(
        workflow_statuses=frozenset({"succeeded"}), evaluation=True, approval=True
    ),
    ("READY_FOR_BETA", "LAUNCH_RUNNING"): RouteRequirement(
        artifact_types=("beta_launch_plan", "gtm_plan", "sales_playbook", "support_plan"), approval=True
    ),
    ("LAUNCH_RUNNING", "CUSTOMERS_ACQUIRED"): RouteRequirement(
        artifact_types=("customer_evidence",), decision=True, approval=True
    ),
    ("CUSTOMERS_ACQUIRED", "CEO_REVIEW"): RouteRequirement(
        workflow_statuses=frozenset({"running"}), approval=True
    ),
    ("CEO_REVIEW", "SCALING"): RouteRequirement(
        artifact_types=("ceo_review",), workflow_statuses=frozenset({"succeeded"}), decision=True, approval=True
    ),
}

KNOWN_STATES = frozenset({state for route in ROUTES for state in route})


@dataclass(frozen=True)
class TransitionCommand:
    project_id: str
    from_state: str
    to_state: str
    expected_project_revision: int
    trigger: str
    actor: dict[str, Any]
    correlation_id: str
    workflow_run_ref: dict[str, Any] | None = None
    artifact_refs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    evaluation_refs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    decision_refs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    approval_refs: tuple[dict[str, Any], ...] = field(default_factory=tuple)


class StateMachine:
    """Evaluate guards and persist applied/rejected outcomes."""

    def __init__(self, repositories: RuntimeRepositories) -> None:
        self.repositories = repositories
        self._correlations: dict[tuple[str, str], str] = {}

    @staticmethod
    def allowed_transitions(state: str) -> tuple[str, ...]:
        """Return deterministic allowed targets without mutating runtime state."""

        return tuple(sorted(to_state for from_state, to_state in ROUTES if from_state == state))

    @staticmethod
    def route_requirement(from_state: str, to_state: str) -> RouteRequirement | None:
        """Expose the canonical route requirement for read-only planning."""

        return ROUTES.get((from_state, to_state))

    def transition(self, command: TransitionCommand) -> dict[str, Any]:
        key = (command.project_id, command.correlation_id)
        with self.repositories.lock:
            existing_id = self._correlations.get(key)
            if existing_id:
                return self.repositories.transitions.get(existing_id)

            project = self.repositories.projects.get(command.project_id)
            transition_id = new_id("transition")
            requested_at = utc_now()
            guard_results: list[dict[str, Any]] = []

            failure = self._guard(
                guard_results,
                "project_active",
                project["status"] == "active",
                "Project must be active",
            )
            if failure:
                return self._reject(command, transition_id, requested_at, guard_results, "PROJECT_NOT_ACTIVE", "Activate the project")

            failure = self._guard(
                guard_results,
                "project_revision_matches",
                project["revision"] == command.expected_project_revision,
                f"Expected revision {command.expected_project_revision}; stored {project['revision']}",
            )
            if failure:
                return self._reject(command, transition_id, requested_at, guard_results, "STALE_REVISION", "Reload the project and retry")

            failure = self._guard(
                guard_results,
                "state_matches",
                project["current_state"] == command.from_state,
                f"Project state is {project['current_state']}",
            )
            if failure:
                return self._reject(command, transition_id, requested_at, guard_results, "INVALID_TRANSITION", "Resolve actions from the current state")

            requirement = ROUTES.get((command.from_state, command.to_state))
            failure = self._guard(
                guard_results,
                "transition_allowed",
                requirement is not None,
                f"Route {command.from_state} -> {command.to_state}",
            )
            if failure:
                return self._reject(command, transition_id, requested_at, guard_results, "INVALID_TRANSITION", "Choose an allowed next state")
            assert requirement is not None

            if requirement.workflow_statuses:
                workflow, evidence, message = self._resolve_workflow(command, requirement)
                failure = self._guard(guard_results, "workflow_succeeded", workflow is not None, message, evidence)
                if failure:
                    return self._reject(command, transition_id, requested_at, guard_results, "GUARD_FAILED", "Provide a WorkflowRun in the required status")

            if requirement.artifact_types:
                passed, evidence, message = self._check_artifacts(command, requirement)
                failure = self._guard(guard_results, "artifact_status", passed, message, evidence)
                if failure:
                    return self._reject(command, transition_id, requested_at, guard_results, "GUARD_FAILED", "Provide all required approved artifacts")

            if requirement.evaluation:
                passed, evidence, message = self._check_evaluations(command)
                failure = self._guard(guard_results, "evaluation_passed", passed, message, evidence)
                if failure:
                    return self._reject(command, transition_id, requested_at, guard_results, "GUARD_FAILED", "Rework evidence and create a passing evaluation")

            if requirement.decision:
                passed, evidence, message = self._check_decisions(command)
                failure = self._guard(guard_results, "decision_recorded", passed, message, evidence)
                if failure:
                    return self._reject(command, transition_id, requested_at, guard_results, "GUARD_FAILED", "Record an approved decision")

            if requirement.approval:
                passed, evidence, message = self._check_approvals(command)
                failure = self._guard(guard_results, "approval_granted", passed, message, evidence)
                if failure:
                    return self._reject(command, transition_id, requested_at, guard_results, "APPROVAL_MISSING", "Obtain current authorized human approval")

            return self._apply(command, transition_id, requested_at, guard_results, project)

    def _guard(
        self,
        results: list[dict[str, Any]],
        guard_id: str,
        passed: bool,
        message: str,
        evidence_refs: list[dict[str, Any]] | None = None,
    ) -> bool:
        result: dict[str, Any] = {
            "guard_id": guard_id,
            "passed": passed,
            "message": message,
            "evaluated_at": utc_now(),
        }
        if evidence_refs:
            result["evidence_refs"] = evidence_refs
        results.append(result)
        return not passed

    def _resolve_workflow(
        self, command: TransitionCommand, requirement: RouteRequirement
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
        if command.workflow_run_ref is None:
            return None, [], "WorkflowRun reference is missing"
        try:
            workflow = self.repositories.resolve_reference(command.workflow_run_ref, project_id=command.project_id)
        except (RecordNotFoundError, ReferenceIntegrityError) as error:
            return None, [], str(error)
        passed = workflow["status"] in requirement.workflow_statuses
        return (workflow if passed else None), [command.workflow_run_ref], f"WorkflowRun status is {workflow['status']}"

    def _check_artifacts(
        self, command: TransitionCommand, requirement: RouteRequirement
    ) -> tuple[bool, list[dict[str, Any]], str]:
        try:
            artifacts = self.repositories.resolve_all(command.artifact_refs, project_id=command.project_id)
        except (RecordNotFoundError, ReferenceIntegrityError) as error:
            return False, list(command.artifact_refs), str(error)
        approved_types = {record["artifact_type"] for record in artifacts if record["status"] == "approved"}
        missing = set(requirement.artifact_types) - approved_types
        return not missing, list(command.artifact_refs), f"Missing approved artifact types: {', '.join(sorted(missing))}" if missing else "Required artifacts are approved"

    def _check_evaluations(self, command: TransitionCommand) -> tuple[bool, list[dict[str, Any]], str]:
        try:
            evaluations = self.repositories.resolve_all(command.evaluation_refs, project_id=command.project_id)
        except (RecordNotFoundError, ReferenceIntegrityError) as error:
            return False, list(command.evaluation_refs), str(error)
        passed = bool(evaluations) and all(
            record["status"] == "completed"
            and record["outcome"] == "pass"
            and record.get("confidence_score", 1.0) >= 0.70
            for record in evaluations
        )
        return passed, list(command.evaluation_refs), "All evaluations passed" if passed else "A passing evaluation with confidence >= 0.70 is required"

    def _check_decisions(self, command: TransitionCommand) -> tuple[bool, list[dict[str, Any]], str]:
        try:
            decisions = self.repositories.resolve_all(command.decision_refs, project_id=command.project_id)
        except (RecordNotFoundError, ReferenceIntegrityError) as error:
            return False, list(command.decision_refs), str(error)
        passed = bool(decisions) and all(record["status"] == "approved" for record in decisions)
        return passed, list(command.decision_refs), "Approved decision recorded" if passed else "An approved decision is required"

    def _check_approvals(self, command: TransitionCommand) -> tuple[bool, list[dict[str, Any]], str]:
        try:
            approvals = self.repositories.resolve_all(command.approval_refs, project_id=command.project_id)
        except (RecordNotFoundError, ReferenceIntegrityError) as error:
            return False, list(command.approval_refs), str(error)
        now = datetime.now(UTC)
        passed = bool(approvals)
        for record in approvals:
            expires_at = record.get("expires_at")
            current = not expires_at or datetime.fromisoformat(expires_at.replace("Z", "+00:00")) > now
            human = record.get("decided_by", {}).get("type") == "human"
            passed = passed and record["status"] == "approved" and current and human
        return passed, list(command.approval_refs), "Authorized human approval granted" if passed else "Current authorized human approval is required"

    def _base_transition(
        self,
        command: TransitionCommand,
        transition_id: str,
        requested_at: str,
        guard_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": transition_id,
            "project_ref": {"kind": "project", "id": command.project_id},
            "from_state": command.from_state,
            "to_state": command.to_state,
            "trigger": command.trigger,
            "requested_by": command.actor,
            "expected_project_revision": command.expected_project_revision,
            "guard_results": guard_results,
            "approval_refs": list(command.approval_refs),
            "requested_at": requested_at,
            "decided_at": utc_now(),
            "metadata": {"correlation_id": command.correlation_id},
        }
        if command.workflow_run_ref:
            record["workflow_run_ref"] = command.workflow_run_ref
        return record

    def _reject(
        self,
        command: TransitionCommand,
        transition_id: str,
        requested_at: str,
        guard_results: list[dict[str, Any]],
        code: str,
        recovery_action: str,
    ) -> dict[str, Any]:
        record = self._base_transition(command, transition_id, requested_at, guard_results)
        record.update({"status": "rejected", "rejection_code": code, "recovery_action": recovery_action})
        record = self.repositories.contracts.validate("transition", record)
        event = build_event(
            self.repositories,
            project_id=command.project_id,
            event_type="transition.rejected",
            actor=command.actor,
            subject_ref={"kind": "transition", "id": transition_id},
            correlation_id=command.correlation_id,
            payload={"from_state": command.from_state, "to_state": command.to_state, "rejection_code": code},
        )
        event = self.repositories.contracts.validate("event", event)
        transition_snapshot = self.repositories.transitions._snapshot()
        event_snapshot = self.repositories.events._snapshot()
        try:
            self.repositories.transitions._insert_validated(record)
            self.repositories.events._append_validated(event)
            self._correlations[(command.project_id, command.correlation_id)] = transition_id
        except Exception:
            self.repositories.transitions._restore(transition_snapshot)
            self.repositories.events._restore(event_snapshot)
            raise
        return deepcopy(record)

    def _apply(
        self,
        command: TransitionCommand,
        transition_id: str,
        requested_at: str,
        guard_results: list[dict[str, Any]],
        project: dict[str, Any],
    ) -> dict[str, Any]:
        resulting_revision = project["revision"] + 1
        record = self._base_transition(command, transition_id, requested_at, guard_results)
        record.update({"status": "applied", "resulting_project_revision": resulting_revision})
        record = self.repositories.contracts.validate("transition", record)
        event = build_event(
            self.repositories,
            project_id=command.project_id,
            event_type="transition.applied",
            actor=command.actor,
            subject_ref={"kind": "transition", "id": transition_id},
            correlation_id=command.correlation_id,
            payload={
                "from_state": command.from_state,
                "to_state": command.to_state,
                "resulting_project_revision": resulting_revision,
            },
        )
        event = self.repositories.contracts.validate("event", event)
        updated_project = deepcopy(project)
        updated_project.update(
            {
                "current_state": command.to_state,
                "revision": resulting_revision,
                "last_event_sequence": event["sequence"],
                "updated_at": utc_now(),
                "next_action": f"Continue from {command.to_state}",
            }
        )
        completed_refs = list(updated_project["completed_artifact_refs"])
        known_refs = {(item["kind"], item["id"], item.get("version")) for item in completed_refs}
        for artifact_ref in command.artifact_refs:
            key = (artifact_ref["kind"], artifact_ref["id"], artifact_ref.get("version"))
            if key not in known_refs:
                completed_refs.append(artifact_ref)
                known_refs.add(key)
        updated_project["completed_artifact_refs"] = completed_refs
        if command.artifact_refs:
            artifact_types = {
                self.repositories.resolve_reference(ref, project_id=command.project_id)["artifact_type"]
                for ref in command.artifact_refs
            }
            updated_project["pending_artifact_types"] = [
                item for item in updated_project["pending_artifact_types"] if item not in artifact_types
            ]
        updated_project = self.repositories.contracts.validate("project", updated_project)

        project_snapshot = self.repositories.projects._snapshot()
        transition_snapshot = self.repositories.transitions._snapshot()
        event_snapshot = self.repositories.events._snapshot()
        try:
            self.repositories.transitions._insert_validated(record)
            self.repositories.events._append_validated(event)
            self.repositories.projects._replace_validated(
                updated_project, expected_revision=command.expected_project_revision
            )
            self._correlations[(command.project_id, command.correlation_id)] = transition_id
        except Exception:
            self.repositories.projects._restore(project_snapshot)
            self.repositories.transitions._restore(transition_snapshot)
            self.repositories.events._restore(event_snapshot)
            raise
        return deepcopy(record)
