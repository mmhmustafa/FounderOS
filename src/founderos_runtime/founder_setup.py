"""First executable Founder Setup vertical slice."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .content import InMemoryContentStore
from .errors import ApprovalRequiredError, VerticalSliceError
from .execution_context import ExecutionContextBuilder
from .ids import new_id, reference, utc_now
from .lifecycle import ApprovalLifecycleService, ArtifactLifecycleService, EvaluationLifecycleService
from .planner import ExecutionPlan, Planner
from .project_state import ProjectStateService, replay_project_events
from .repositories import RuntimeRepositories
from .runs import AgentRunService, WorkflowRunService
from .state_machine import StateMachine, TransitionCommand

SERVICE_ACTOR = {"type": "service", "id": "founder-setup", "display_name": "Founder Setup Service"}


@dataclass(frozen=True)
class FounderSetupSession:
    project_id: str
    workflow_run_id: str
    workflow_id: str
    agent_id: str
    plan: ExecutionPlan


@dataclass(frozen=True)
class FounderBriefPreparation:
    project_id: str
    workflow_run_id: str
    agent_run_id: str
    artifact_id: str
    evaluation_id: str
    approval_id: str
    content: dict[str, Any]


@dataclass(frozen=True)
class FounderSetupCompletion:
    transition: dict[str, Any]
    project: dict[str, Any]


class FounderSetupService:
    """Coordinate existing runtime boundaries without hiding their records."""

    def __init__(self, repositories: RuntimeRepositories, content_store: InMemoryContentStore | None = None) -> None:
        self.repositories = repositories
        self.content = content_store or InMemoryContentStore(repositories.lock)
        self.projects = ProjectStateService(repositories)
        self.machine = StateMachine(repositories)
        self.planner = Planner(self.machine)
        self.contexts = ExecutionContextBuilder(repositories)
        self.workflow_runs = WorkflowRunService(repositories)
        self.agent_runs = AgentRunService(repositories)
        self.artifacts = ArtifactLifecycleService(repositories)
        self.evaluations = EvaluationLifecycleService(repositories)
        self.approvals = ApprovalLifecycleService(repositories)

    def create_project(self, **kwargs: Any) -> dict[str, Any]:
        return self.projects.create_project(**kwargs)

    def plan(self, project_id: str) -> ExecutionPlan:
        return self.planner.plan(self.contexts.build(project_id))

    def start(self, project_id: str, *, actor: dict[str, Any], correlation_id: str) -> FounderSetupSession:
        project = self.projects.get(project_id)
        plan = self.plan(project_id)
        if plan.recommended_workflow != "Founder Setup Workflow":
            raise VerticalSliceError(f"Founder Setup is not recommended from {project['current_state']}")
        agent, workflow = self._ensure_definitions()
        if project["current_state"] == "NO_PROJECT":
            run = self.workflow_runs.create(
                project_ref=reference("project", project),
                workflow_ref=reference("workflow", workflow, include_version=True),
                entry_state="NO_PROJECT",
                requested_exit_state="FOUNDER_SETUP",
            )
            transition = self.machine.transition(TransitionCommand(
                project_id=project_id, from_state="NO_PROJECT", to_state="FOUNDER_SETUP",
                expected_project_revision=project["revision"], trigger="begin_founder_setup", actor=actor,
                correlation_id=f"{correlation_id}:transition", workflow_run_ref=reference("workflow_run", run),
            ))
            if transition["status"] != "applied":
                raise VerticalSliceError(f"Founder Setup start rejected: {transition.get('rejection_code')}")
        else:
            candidates = [r for r in self.repositories.workflow_runs.all() if r["project_ref"]["id"] == project_id and r["status"] in {"queued", "running"}]
            if not candidates:
                run = self.workflow_runs.create(
                    project_ref=reference("project", project), workflow_ref=reference("workflow", workflow, include_version=True),
                    entry_state="FOUNDER_SETUP", requested_exit_state="FOUNDER_BRIEF_COMPLETE")
            else:
                run = candidates[-1]
        if run["status"] == "queued":
            run = self.workflow_runs.set_status(run["id"], "running", expected_revision=run["revision"], actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:workflow")
        return FounderSetupSession(project_id, run["id"], workflow["id"], agent["id"], plan)

    def produce_founder_brief(
        self, session: FounderSetupSession, *, founder_profile: dict[str, Any], startup_context: dict[str, Any],
        assumptions: list[str] | None = None, risks: list[str] | None = None,
        open_questions: list[str] | None = None, correlation_id: str,
    ) -> FounderBriefPreparation:
        project = self.projects.get(session.project_id)
        if project["current_state"] != "FOUNDER_SETUP":
            raise VerticalSliceError("Founder Brief production requires FOUNDER_SETUP")
        workflow_run = self.repositories.workflow_runs.get(session.workflow_run_id)
        agent = self.repositories.agents.get(session.agent_id)
        agent_run = self.agent_runs.create(
            project_ref=reference("project", project), workflow_run_ref=reference("workflow_run", workflow_run),
            agent_ref=reference("agent", agent, include_version=True))
        agent_run = self.agent_runs.set_status(agent_run["id"], "running", expected_revision=1, actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:agent-start")
        content = {
            "schema_version": "1.0.0", "founder_profile": deepcopy(founder_profile),
            "startup_context": deepcopy(startup_context), "assumptions": list(assumptions or []),
            "risks": list(risks or []), "open_questions": list(open_questions or []),
            "next_recommended_workflow": "Discovery Workflow",
        }
        content = self.repositories.contracts.validate("founder_brief_content", content)
        artifact_id = new_id("artifact")
        uri = f"memory://projects/{session.project_id}/artifacts/{artifact_id}/1.0.0"
        _, digest = self.content.put(uri, content)
        now = utc_now()
        artifact = self.artifacts.create({
            "id": artifact_id, "version": "1.0.0", "revision": 1,
            "project_ref": reference("project", project), "name": "Founder Brief", "artifact_type": "founder_brief",
            "status": "under_review", "owner_ref": reference("agent", agent, include_version=True),
            "produced_by_run_ref": reference("agent_run", agent_run), "content_uri": uri, "content_digest": digest,
            "input_artifact_refs": [], "output_consumer_refs": [], "confidence_score": 1.0,
            "assumptions": content["assumptions"], "risks": content["risks"], "open_questions": content["open_questions"],
            "decision_refs": [], "evaluation_refs": [], "approval_refs": [], "created_at": now, "updated_at": now,
        }, actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:artifact")
        evaluation = self.evaluations.create({
            "id": new_id("evaluation"), "project_ref": reference("project", project),
            "target_ref": reference("artifact", artifact, include_version=True), "evaluation_type": "schema", "status": "completed",
            "evaluator": SERVICE_ACTOR, "criteria": [{"criterion_id": "founder_brief_schema", "description": "Founder Brief content matches its contract", "passed": True, "score": 1.0}],
            "outcome": "pass", "confidence_score": 1.0, "summary": "Machine-valid structured Founder Brief", "created_at": now, "completed_at": now,
        }, actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:evaluation")
        approval = self.approvals.request({
            "id": new_id("approval"), "revision": 1, "project_ref": reference("project", project),
            "subject_ref": reference("artifact", artifact, include_version=True), "approval_type": "artifact", "status": "pending",
            "requested_by": SERVICE_ACTOR, "required_approver_type": "founder", "requested_at": now,
        }, actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:approval")
        agent_run = self.agent_runs.set_status(agent_run["id"], "succeeded", expected_revision=agent_run["revision"], actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:agent-complete")
        return FounderBriefPreparation(session.project_id, session.workflow_run_id, agent_run["id"], artifact["id"], evaluation["id"], approval["id"], content)

    def approve_founder_brief(self, preparation: FounderBriefPreparation, *, actor: dict[str, Any], rationale: str, correlation_id: str) -> dict[str, Any]:
        if actor.get("type") != "human":
            raise VerticalSliceError("Founder Brief approval must be decided by a human")
        with self.repositories.lock:
            approval = self.repositories.approvals.get(preparation.approval_id)
            if approval["status"] == "approved":
                return approval
            if approval["status"] != "pending":
                raise VerticalSliceError(f"Approval is {approval['status']}")
            updated = self.approvals.approve(
                approval["id"], actor=actor, rationale=rationale,
                correlation_id=f"{correlation_id}:decision",
            )
            self.artifacts.approve_with_references(
                preparation.artifact_id,
                approval_ref=reference("approval", updated, include_revision=True),
                evaluation_refs=[reference("evaluation", self.repositories.evaluations.get(preparation.evaluation_id))],
                actor=actor, correlation_id=f"{correlation_id}:artifact",
            )
            return updated

    def complete(self, preparation: FounderBriefPreparation, *, actor: dict[str, Any], correlation_id: str, expected_project_revision: int | None = None) -> FounderSetupCompletion:
        prior = [t for t in self.repositories.transitions.all() if t["project_ref"]["id"] == preparation.project_id and t.get("metadata", {}).get("correlation_id") == correlation_id]
        if prior:
            return FounderSetupCompletion(prior[0], self.projects.get(preparation.project_id))
        approval = self.repositories.approvals.get(preparation.approval_id)
        if approval["status"] != "approved" or approval.get("decided_by", {}).get("type") != "human":
            raise ApprovalRequiredError("Human Founder Brief approval is required")
        workflow_run = self.repositories.workflow_runs.get(preparation.workflow_run_id)
        if workflow_run["status"] == "running":
            workflow_run = self.workflow_runs.set_status(workflow_run["id"], "succeeded", expected_revision=workflow_run["revision"], actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:workflow")
        project = self.projects.get(preparation.project_id)
        transition = self.machine.transition(TransitionCommand(
            project_id=project["id"], from_state="FOUNDER_SETUP", to_state="FOUNDER_BRIEF_COMPLETE",
            expected_project_revision=project["revision"] if expected_project_revision is None else expected_project_revision,
            trigger="founder_brief_approved", actor=actor, correlation_id=correlation_id,
            workflow_run_ref=reference("workflow_run", workflow_run),
            artifact_refs=(reference("artifact", self.repositories.artifacts.get(preparation.artifact_id), include_version=True),),
            evaluation_refs=(reference("evaluation", self.repositories.evaluations.get(preparation.evaluation_id)),),
            approval_refs=(reference("approval", approval, include_revision=True),),
        ))
        return FounderSetupCompletion(transition, self.projects.get(preparation.project_id))

    def resume(self, project_id: str) -> dict[str, Any]:
        project = self.projects.get(project_id); events = self.repositories.events.for_project(project_id)
        replayed = replay_project_events(events)
        if (replayed["current_state"], replayed["revision"]) != (project["current_state"], project["revision"]):
            raise VerticalSliceError("Replayed aggregate does not match stored Project")
        briefs = []
        for artifact in self.repositories.artifacts.all():
            if artifact["project_ref"]["id"] == project_id and artifact["artifact_type"] == "founder_brief":
                briefs.append({"artifact": artifact, "content": self.content.get(artifact["content_uri"])})
        return {"project": project, "replayed_state": replayed, "plan": self.plan(project_id), "founder_briefs": briefs}

    def _ensure_definitions(self) -> tuple[dict[str, Any], dict[str, Any]]:
        agents = [a for a in self.repositories.agents.all() if a["name"] == "Founder Interview Agent" and a["status"] == "active"]
        if agents: agent = agents[0]
        else:
            now = utc_now(); agent = self.repositories.agents.create({
                "id": new_id("agent"), "version": "1.0.0", "status": "active", "name": "Founder Interview Agent", "role": "Founder Interviewer",
                "seniority": "not_applicable", "purpose": "Assemble founder-supplied data into a structured Founder Brief",
                "responsibilities": ["Validate founder input", "Produce a Founder Brief"], "accepted_artifact_types": [], "produced_artifact_types": ["founder_brief"],
                "tool_ids": [], "constraints": ["No AI or external calls"], "quality_gate_ids": ["founder_brief_schema"], "handoff_agent_refs": [], "failure_modes": [], "escalation_rules": [], "created_at": now, "updated_at": now})
        workflows = [w for w in self.repositories.workflows.all() if w["name"] == "Founder Setup Workflow" and w["status"] == "active"]
        if workflows: return agent, workflows[0]
        now = utc_now(); workflow = self.repositories.workflows.create({
            "id": new_id("workflow"), "version": "1.0.0", "status": "active", "name": "Founder Setup Workflow", "purpose": "Create and approve the first Founder Brief",
            "entry_state": "NO_PROJECT", "exit_states": ["FOUNDER_SETUP", "FOUNDER_BRIEF_COMPLETE"], "required_artifact_types": [], "produced_artifact_types": ["founder_brief"],
            "agent_refs": [reference("agent", agent, include_version=True)], "steps": [
                {"step_id": "collect_founder_input", "sequence": 1, "name": "Collect founder input", "action_type": "collect_input", "on_failure": "request_human"},
                {"step_id": "produce_founder_brief", "sequence": 2, "name": "Produce Founder Brief", "action_type": "invoke_agent", "agent_ref": reference("agent", agent, include_version=True), "produced_artifact_types": ["founder_brief"], "on_failure": "fail"},
                {"step_id": "evaluate_founder_brief", "sequence": 3, "name": "Evaluate Founder Brief", "action_type": "evaluate", "required_artifact_types": ["founder_brief"], "on_failure": "fail"},
                {"step_id": "approve_founder_brief", "sequence": 4, "name": "Approve Founder Brief", "action_type": "request_approval", "required_artifact_types": ["founder_brief"], "on_failure": "request_human"},
                {"step_id": "complete_founder_setup", "sequence": 5, "name": "Complete Founder Setup", "action_type": "request_transition", "on_failure": "pause"}],
            "quality_gate_ids": ["founder_brief_schema"], "success_criteria": ["Founder Brief is approved by a human"],
            "failure_policy": {"max_attempts": 1, "terminal_behavior": "request_human", "recovery_action": "Correct founder input and start a new run"},
            "next_workflow_refs": [], "created_at": now, "updated_at": now})
        return agent, workflow
