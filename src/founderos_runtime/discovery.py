"""Deterministic local Discovery Workflow v1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .content import InMemoryContentStore
from .ids import new_id, reference, utc_now
from .lifecycle import (
    ApprovalLifecycleService,
    ArtifactLifecycleService,
    DecisionLifecycleService,
    EvaluationLifecycleService,
)
from .lifecycle_planner import Planner
from .execution_context import ExecutionContextBuilder
from .project_state import ProjectStateService, replay_project_events
from .repositories import RuntimeRepositories
from .runs import AgentRunService, WorkflowRunService
from .state_machine import StateMachine, TransitionCommand


SERVICE_ACTOR = {"type": "service", "id": "discovery-v1", "display_name": "Discovery Workflow v1"}
SCORE_FIELDS = (
    "pain_score", "frequency_score", "budget_score", "ai_advantage_score",
    "mvp_feasibility_score", "founder_fit_score",
)


@dataclass(frozen=True)
class DiscoveryPreparation:
    project_id: str
    workflow_run_id: str
    agent_run_id: str
    artifact_id: str
    evaluation_id: str
    approval_id: str
    content: dict[str, Any]


@dataclass(frozen=True)
class DiscoveryCompletion:
    transition: dict[str, Any]
    decision: dict[str, Any]
    project: dict[str, Any]


def score_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and rank candidates using an unweighted six-score sum."""

    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Discovery requires at least one opportunity candidate")
    scored: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for index, raw in enumerate(candidates):
        if not isinstance(raw, dict):
            raise ValueError(f"Candidate {index} must be an object")
        allowed = {"problem", "target_user", *SCORE_FIELDS, "total_score", "assumptions", "risks"}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Candidate {index} has unknown fields: {', '.join(sorted(unknown))}")
        problem, target_user = raw.get("problem"), raw.get("target_user")
        if not isinstance(problem, str) or not problem.strip():
            raise ValueError(f"Candidate {index} requires a non-empty problem")
        if not isinstance(target_user, str) or not target_user.strip():
            raise ValueError(f"Candidate {index} requires a non-empty target_user")
        identity = (problem.strip(), target_user.strip())
        if identity in identities:
            raise ValueError("Opportunity candidates must be unique by problem and target_user")
        identities.add(identity)
        values: dict[str, int] = {}
        for field in SCORE_FIELDS:
            value = raw.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10:
                raise ValueError(f"Candidate {index}.{field} must be an integer from 0 to 10")
            values[field] = value
        total = sum(values.values())
        supplied_total = raw.get("total_score")
        if supplied_total is not None and supplied_total != total:
            raise ValueError(f"Candidate {index}.total_score must equal the deterministic score {total}")
        assumptions = raw.get("assumptions", [])
        risks = raw.get("risks", [])
        if not isinstance(assumptions, list) or not all(isinstance(item, str) for item in assumptions):
            raise ValueError(f"Candidate {index}.assumptions must be an array of strings")
        if not isinstance(risks, list) or not all(isinstance(item, str) for item in risks):
            raise ValueError(f"Candidate {index}.risks must be an array of strings")
        scored.append({
            "problem": problem.strip(), "target_user": target_user.strip(), **values,
            "total_score": total, "assumptions": list(assumptions), "risks": list(risks),
        })
    return sorted(scored, key=lambda item: (-item["total_score"], item["problem"], item["target_user"]))


class DiscoveryWorkflowService:
    """Execute deterministic Discovery using existing runtime boundaries."""

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
        self.decisions = DecisionLifecycleService(repositories)

    def discover(
        self, project_id: str, candidates: list[dict[str, Any]], *, actor: dict[str, Any], correlation_id: str,
    ) -> DiscoveryPreparation:
        project = self.projects.get(project_id)
        if project["current_state"] != "FOUNDER_BRIEF_COMPLETE":
            raise ValueError("Discovery requires a Project in FOUNDER_BRIEF_COMPLETE")
        founder_brief = self._approved_artifact(project_id, "founder_brief")
        if not founder_brief.get("approval_refs"):
            raise ValueError("Discovery requires an approved Founder Brief with human Approval")
        plan = self.planner.plan(self.contexts.build(project_id))
        if plan.recommended_workflow != "Discovery Workflow":
            raise ValueError("Planner does not recommend Discovery Workflow")
        agent, workflow = self._ensure_definitions()
        workflow_run = self.workflow_runs.create(
            project_ref=reference("project", project),
            workflow_ref=reference("workflow", workflow, include_version=True),
            entry_state="FOUNDER_BRIEF_COMPLETE", requested_exit_state="DISCOVERY_RUNNING",
            input_artifact_refs=[reference("artifact", founder_brief, include_version=True)],
            correlation_id=correlation_id,
        )
        workflow_run = self.workflow_runs.set_status(
            workflow_run["id"], "running", expected_revision=workflow_run["revision"],
            actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:workflow-start",
        )
        start_transition = self.machine.transition(TransitionCommand(
            project_id=project_id, from_state="FOUNDER_BRIEF_COMPLETE", to_state="DISCOVERY_RUNNING",
            expected_project_revision=project["revision"], trigger="start_discovery", actor=actor,
            correlation_id=f"{correlation_id}:start-transition",
            workflow_run_ref=reference("workflow_run", workflow_run),
            approval_refs=tuple(founder_brief["approval_refs"]),
        ))
        if start_transition["status"] != "applied":
            raise ValueError(f"Discovery start transition rejected: {start_transition.get('rejection_code')}")
        agent_run = self.agent_runs.create(
            project_ref=reference("project", self.projects.get(project_id)),
            workflow_run_ref=reference("workflow_run", workflow_run),
            agent_ref=reference("agent", agent, include_version=True),
            input_refs=[reference("artifact", founder_brief, include_version=True)],
            correlation_id=correlation_id,
        )
        agent_run = self.agent_runs.set_status(
            agent_run["id"], "running", expected_revision=agent_run["revision"],
            actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:agent-start",
        )
        ranked = score_candidates(candidates)
        content = self.repositories.contracts.validate("opportunity_report_content", {
            "schema_version": "1.0.0",
            "founder_brief_ref": reference("artifact", founder_brief, include_version=True),
            "candidates": ranked, "recommended_candidate_index": 0,
            "scoring_method": "unweighted_sum_v1",
        })
        artifact_id = new_id("artifact")
        uri = f"memory://projects/{project_id}/artifacts/{artifact_id}/1.0.0"
        _, digest = self.content.put(uri, content)
        now = utc_now()
        artifact = self.artifacts.create({
            "id": artifact_id, "version": "1.0.0", "revision": 1,
            "project_ref": reference("project", self.projects.get(project_id)),
            "name": "Opportunity Report", "artifact_type": "opportunity_report", "status": "under_review",
            "owner_ref": reference("agent", agent, include_version=True),
            "produced_by_run_ref": reference("agent_run", agent_run), "content_uri": uri, "content_digest": digest,
            "input_artifact_refs": [reference("artifact", founder_brief, include_version=True)],
            "output_consumer_refs": [], "confidence_score": min(1.0, ranked[0]["total_score"] / 60),
            "assumptions": sorted({value for item in ranked for value in item["assumptions"]}),
            "risks": sorted({value for item in ranked for value in item["risks"]}),
            "open_questions": [], "decision_refs": [], "evaluation_refs": [], "approval_refs": [],
            "created_at": now, "updated_at": now,
        }, actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:artifact")
        evaluation = self.evaluations.create({
            "id": new_id("evaluation"), "project_ref": reference("project", self.projects.get(project_id)),
            "target_ref": reference("artifact", artifact, include_version=True), "evaluation_type": "quality_gate",
            "status": "completed", "evaluator": SERVICE_ACTOR,
            "criteria": [
                {"criterion_id": "opportunity_report_schema", "description": "Report matches its structured contract", "passed": True, "score": 1.0},
                {"criterion_id": "deterministic_scoring", "description": "All totals equal the six component score sum", "passed": True, "score": 1.0}
            ],
            "outcome": "pass", "confidence_score": 1.0,
            "summary": "Opportunity Report is structurally valid and deterministically ranked",
            "created_at": now, "completed_at": now,
        }, actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:evaluation")
        approval = self.approvals.request({
            "id": new_id("approval"), "revision": 1,
            "project_ref": reference("project", self.projects.get(project_id)),
            "subject_ref": reference("artifact", artifact, include_version=True),
            "approval_type": "artifact", "status": "pending", "requested_by": SERVICE_ACTOR,
            "required_approver_type": "founder", "requested_at": now,
        }, actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:approval")
        agent_run = self.agent_runs.set_status(
            agent_run["id"], "succeeded", expected_revision=agent_run["revision"],
            actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:agent-complete",
        )
        return DiscoveryPreparation(
            project_id, workflow_run["id"], agent_run["id"], artifact["id"],
            evaluation["id"], approval["id"], content,
        )

    def approve_opportunity(
        self, preparation: DiscoveryPreparation, *, actor: dict[str, Any], rationale: str, correlation_id: str,
    ) -> DiscoveryCompletion:
        if actor.get("type") != "human":
            raise ValueError("Opportunity selection requires human approval")
        project = self.projects.get(preparation.project_id)
        if project["current_state"] != "DISCOVERY_RUNNING":
            raise ValueError("Opportunity approval requires DISCOVERY_RUNNING")
        approval = self.approvals.approve(
            preparation.approval_id, actor=actor, rationale=rationale,
            correlation_id=f"{correlation_id}:approval-decision",
        )
        artifact = self.artifacts.approve_with_references(
            preparation.artifact_id,
            approval_ref=reference("approval", approval, include_revision=True),
            evaluation_refs=[reference("evaluation", self.repositories.evaluations.get(preparation.evaluation_id))],
            actor=actor, correlation_id=f"{correlation_id}:artifact-approval",
        )
        selected = preparation.content["candidates"][preparation.content["recommended_candidate_index"]]
        now = utc_now()
        options = [f"{item['problem']} — {item['target_user']}" for item in preparation.content["candidates"]]
        decision = self.decisions.create({
            "id": new_id("decision"), "version": "1.0.0", "revision": 1,
            "project_ref": reference("project", project), "title": "Select Discovery opportunity",
            "status": "approved", "state_code": "DISCOVERY_RUNNING",
            "context": "Select the highest-ranked deterministic Discovery v1 opportunity",
            "options_considered": options, "selected_option": options[0], "rationale": rationale,
            "confidence_score": min(1.0, selected["total_score"] / 60), "risks": selected["risks"],
            "reversibility": "moderate", "owner": actor,
            "related_artifact_refs": [reference("artifact", artifact, include_version=True)],
            "approval_ref": reference("approval", approval, include_revision=True),
            "created_at": now, "updated_at": now,
        }, actor=actor, correlation_id=f"{correlation_id}:decision")
        workflow_run = self.repositories.workflow_runs.get(preparation.workflow_run_id)
        workflow_run = self.workflow_runs.set_status(
            workflow_run["id"], "succeeded", expected_revision=workflow_run["revision"],
            actor=SERVICE_ACTOR, correlation_id=f"{correlation_id}:workflow-complete",
        )
        transition = self.machine.transition(TransitionCommand(
            project_id=preparation.project_id, from_state="DISCOVERY_RUNNING", to_state="OPPORTUNITY_SELECTED",
            expected_project_revision=project["revision"], trigger="approve_opportunity", actor=actor,
            correlation_id=correlation_id, workflow_run_ref=reference("workflow_run", workflow_run),
            artifact_refs=(reference("artifact", artifact, include_version=True),),
            evaluation_refs=(reference("evaluation", self.repositories.evaluations.get(preparation.evaluation_id)),),
            decision_refs=(reference("decision", decision, include_version=True),),
            approval_refs=(reference("approval", approval, include_revision=True),),
        ))
        return DiscoveryCompletion(transition, decision, self.projects.get(preparation.project_id))

    def _approved_artifact(self, project_id: str, artifact_type: str) -> dict[str, Any]:
        matches = [
            item for item in self.repositories.artifacts.all()
            if item["project_ref"]["id"] == project_id and item["artifact_type"] == artifact_type and item["status"] == "approved"
        ]
        if not matches:
            raise ValueError(f"Required approved artifact is missing: {artifact_type}")
        return matches[-1]

    def _ensure_definitions(self) -> tuple[dict[str, Any], dict[str, Any]]:
        agents = [item for item in self.repositories.agents.all() if item["name"] == "Opportunity Scoring Agent" and item["status"] == "active"]
        if agents:
            agent = agents[0]
        else:
            now = utc_now()
            agent = self.repositories.agents.create({
                "id": new_id("agent"), "version": "1.0.0", "status": "active",
                "name": "Opportunity Scoring Agent", "role": "Opportunity Scoring Agent",
                "seniority": "not_applicable", "purpose": "Deterministically score founder-provided opportunities",
                "responsibilities": ["Validate candidates", "Compute scores", "Rank opportunities"],
                "accepted_artifact_types": ["founder_brief"], "produced_artifact_types": ["opportunity_report"],
                "tool_ids": [], "constraints": ["No LLM, web, or external API calls"],
                "quality_gate_ids": ["opportunity_report_schema", "deterministic_scoring"],
                "handoff_agent_refs": [], "failure_modes": [], "escalation_rules": [],
                "created_at": now, "updated_at": now,
            })
        workflows = [item for item in self.repositories.workflows.all() if item["name"] == "Discovery Workflow" and item["status"] == "active"]
        if workflows:
            return agent, workflows[0]
        now = utc_now()
        workflow = self.repositories.workflows.create({
            "id": new_id("workflow"), "version": "1.0.0", "status": "active",
            "name": "Discovery Workflow", "purpose": "Rank static founder-provided opportunity candidates",
            "entry_state": "FOUNDER_BRIEF_COMPLETE", "exit_states": ["DISCOVERY_RUNNING", "OPPORTUNITY_SELECTED"],
            "required_artifact_types": ["founder_brief"], "produced_artifact_types": ["opportunity_report"],
            "agent_refs": [reference("agent", agent, include_version=True)],
            "steps": [
                {"step_id": "collect_candidates", "sequence": 1, "name": "Collect candidates", "action_type": "collect_input", "on_failure": "request_human"},
                {"step_id": "score_candidates", "sequence": 2, "name": "Score candidates", "action_type": "invoke_agent", "agent_ref": reference("agent", agent, include_version=True), "required_artifact_types": ["founder_brief"], "produced_artifact_types": ["opportunity_report"], "on_failure": "fail"},
                {"step_id": "evaluate_report", "sequence": 3, "name": "Evaluate report", "action_type": "evaluate", "required_artifact_types": ["opportunity_report"], "on_failure": "fail"},
                {"step_id": "approve_opportunity", "sequence": 4, "name": "Approve opportunity", "action_type": "request_approval", "required_artifact_types": ["opportunity_report"], "on_failure": "request_human"},
                {"step_id": "select_opportunity", "sequence": 5, "name": "Select opportunity", "action_type": "record_decision", "required_artifact_types": ["opportunity_report"], "on_failure": "fail"},
                {"step_id": "complete_discovery", "sequence": 6, "name": "Complete Discovery", "action_type": "request_transition", "on_failure": "pause"}
            ],
            "quality_gate_ids": ["opportunity_report_schema", "deterministic_scoring"],
            "success_criteria": ["Opportunity Report approved", "Opportunity selection Decision recorded"],
            "failure_policy": {"max_attempts": 1, "terminal_behavior": "request_human", "recovery_action": "Correct candidate data and start a new Discovery run"},
            "next_workflow_refs": [], "created_at": now, "updated_at": now,
        })
        return agent, workflow

    def resume(self, project_id: str) -> dict[str, Any]:
        project = self.projects.get(project_id)
        replayed = replay_project_events(self.repositories.events.for_project(project_id))
        if (project["current_state"], project["revision"]) != (replayed["current_state"], replayed["revision"]):
            raise ValueError("Discovery resume replay does not match Project state")
        return {"project": project, "replayed_state": replayed, "plan": self.planner.plan(self.contexts.build(project_id))}
