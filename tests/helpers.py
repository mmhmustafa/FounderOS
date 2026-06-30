"""Contract-valid record factories for runtime acceptance tests."""

from __future__ import annotations

from typing import Any

from founderos_runtime import (
    AgentRunService,
    ContractRegistry,
    ProjectStateService,
    RuntimeRepositories,
    StateMachine,
    TransitionCommand,
    WorkflowRunService,
    new_id,
    utc_now,
)
from founderos_runtime.ids import reference

HUMAN = {"type": "human", "id": "founder-1", "display_name": "Founder"}
SERVICE = {"type": "service", "id": "runtime", "display_name": "FounderOS Runtime"}


class RuntimeFixture:
    def __init__(self) -> None:
        self.contracts = ContractRegistry()
        self.repositories = RuntimeRepositories(self.contracts)
        self.projects = ProjectStateService(self.repositories)
        self.workflows = WorkflowRunService(self.repositories)
        self.agents = AgentRunService(self.repositories)
        self.machine = StateMachine(self.repositories)
        self.project = self.projects.create_project(
            name="Test Project",
            founder_id="founder-1",
            founder_name="Founder",
            domain="Testing",
            actor=HUMAN,
            correlation_id="create-project",
        )

    @property
    def project_ref(self) -> dict[str, Any]:
        return {"kind": "project", "id": self.project["id"]}

    def refresh_project(self) -> dict[str, Any]:
        self.project = self.projects.get(self.project["id"])
        return self.project

    def create_workflow_definition(
        self,
        *,
        entry_state: str = "NO_PROJECT",
        exit_states: list[str] | None = None,
        max_attempts: int = 2,
    ) -> dict[str, Any]:
        now = utc_now()
        workflow = {
            "id": new_id("workflow"),
            "version": "1.0.0",
            "status": "active",
            "name": "Test Workflow",
            "purpose": "Exercise runtime contracts",
            "entry_state": entry_state,
            "exit_states": exit_states or ["FOUNDER_SETUP"],
            "required_artifact_types": [],
            "produced_artifact_types": [],
            "agent_refs": [],
            "steps": [
                {
                    "step_id": "collect_input",
                    "sequence": 1,
                    "name": "Collect input",
                    "action_type": "collect_input",
                    "on_failure": "fail",
                }
            ],
            "quality_gate_ids": [],
            "success_criteria": [],
            "failure_policy": {"max_attempts": max_attempts, "terminal_behavior": "fail"},
            "next_workflow_refs": [],
            "created_at": now,
            "updated_at": now,
        }
        return self.repositories.workflows.create(workflow)

    def create_agent_definition(self) -> dict[str, Any]:
        now = utc_now()
        agent = {
            "id": new_id("agent"),
            "version": "1.0.0",
            "status": "active",
            "name": "Test Agent",
            "role": "Contract Tester",
            "seniority": "not_applicable",
            "purpose": "Exercise AgentRun contracts",
            "responsibilities": ["Return structured output"],
            "accepted_artifact_types": [],
            "produced_artifact_types": [],
            "tool_ids": [],
            "constraints": ["No external calls"],
            "quality_gate_ids": [],
            "handoff_agent_refs": [],
            "failure_modes": [],
            "escalation_rules": [],
            "created_at": now,
            "updated_at": now,
        }
        return self.repositories.agents.create(agent)

    def create_workflow_run(
        self,
        *,
        workflow: dict[str, Any] | None = None,
        max_attempts: int = 2,
    ) -> dict[str, Any]:
        workflow = workflow or self.create_workflow_definition(
            entry_state=self.project["current_state"], max_attempts=max_attempts
        )
        return self.workflows.create(
            project_ref=self.project_ref,
            workflow_ref=reference("workflow", workflow, include_version=True),
            entry_state=self.project["current_state"],
            requested_exit_state=workflow["exit_states"][0],
        )

    def create_artifact(self, artifact_type: str, *, status: str = "approved") -> dict[str, Any]:
        agent = self.create_agent_definition()
        now = utc_now()
        artifact = {
            "id": new_id("artifact"),
            "version": "1.0.0",
            "revision": 1,
            "project_ref": self.project_ref,
            "name": artifact_type.replace("_", " ").title(),
            "artifact_type": artifact_type,
            "status": status,
            "owner_ref": reference("agent", agent, include_version=True),
            "content_uri": f"memory://{artifact_type}/1.0.0",
            "content_digest": "sha256:" + "0" * 64,
            "input_artifact_refs": [],
            "output_consumer_refs": [],
            "confidence_score": 0.9,
            "assumptions": [],
            "risks": [],
            "open_questions": [],
            "decision_refs": [],
            "evaluation_refs": [],
            "approval_refs": [],
            "created_at": now,
            "updated_at": now,
        }
        return self.repositories.artifacts.create(artifact)

    def create_approval(self, subject_ref: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        approval = {
            "id": new_id("approval"),
            "revision": 1,
            "project_ref": self.project_ref,
            "subject_ref": subject_ref,
            "approval_type": "transition",
            "status": "approved",
            "requested_by": SERVICE,
            "required_approver_type": "founder",
            "decided_by": HUMAN,
            "rationale": "Approved for test",
            "requested_at": now,
            "decided_at": now,
        }
        return self.repositories.approvals.create(approval)

    def create_evaluation(self, target_ref: dict[str, Any], *, outcome: str = "pass") -> dict[str, Any]:
        now = utc_now()
        evaluation = {
            "id": new_id("evaluation"),
            "project_ref": self.project_ref,
            "target_ref": target_ref,
            "evaluation_type": "quality_gate",
            "status": "completed",
            "evaluator": SERVICE,
            "criteria": [
                {
                    "criterion_id": "contract_quality",
                    "description": "Contract quality gate",
                    "passed": outcome == "pass",
                    "score": 0.9 if outcome == "pass" else 0.2,
                }
            ],
            "outcome": outcome,
            "confidence_score": 0.9 if outcome == "pass" else 0.2,
            "created_at": now,
            "completed_at": now,
        }
        return self.repositories.evaluations.create(evaluation)

    def create_decision(self, approval: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        decision = {
            "id": new_id("decision"),
            "version": "1.0.0",
            "revision": 1,
            "project_ref": self.project_ref,
            "title": "Test decision",
            "status": "approved",
            "state_code": self.project["current_state"],
            "context": "A test choice is required",
            "options_considered": ["Proceed", "Stop"],
            "selected_option": "Proceed",
            "rationale": "Contract test",
            "confidence_score": 0.9,
            "risks": [],
            "reversibility": "easy",
            "owner": HUMAN,
            "related_artifact_refs": [],
            "approval_ref": reference("approval", approval, include_revision=True),
            "created_at": now,
            "updated_at": now,
        }
        return self.repositories.decisions.create(decision)

    def move_to_founder_setup(self, *, correlation_id: str = "to-founder-setup") -> dict[str, Any]:
        workflow_run = self.create_workflow_run()
        outcome = self.machine.transition(
            TransitionCommand(
                project_id=self.project["id"],
                from_state="NO_PROJECT",
                to_state="FOUNDER_SETUP",
                expected_project_revision=self.project["revision"],
                trigger="begin_setup",
                actor=HUMAN,
                correlation_id=correlation_id,
                workflow_run_ref=reference("workflow_run", workflow_run, include_revision=True),
            )
        )
        self.refresh_project()
        return outcome
