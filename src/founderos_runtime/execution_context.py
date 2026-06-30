"""Immutable read model used by the Runtime Planner."""

from __future__ import annotations

from dataclasses import dataclass

from .repositories import RuntimeRepositories


@dataclass(frozen=True, order=True)
class AvailableAgent:
    id: str
    name: str
    role: str
    version: str


@dataclass(frozen=True, order=True)
class AvailableWorkflow:
    id: str
    name: str
    entry_state: str
    exit_states: tuple[str, ...]
    version: str


@dataclass(frozen=True, order=True)
class DecisionSummary:
    id: str
    title: str
    status: str


@dataclass(frozen=True, order=True)
class EventSummary:
    sequence: int
    id: str
    event_type: str


@dataclass(frozen=True)
class ExecutionContext:
    project_id: str
    current_state: str
    completed_artifacts: tuple[str, ...]
    pending_artifacts: tuple[str, ...]
    available_agents: tuple[AvailableAgent, ...]
    available_workflows: tuple[AvailableWorkflow, ...]
    decisions: tuple[DecisionSummary, ...]
    risks: tuple[str, ...]
    events: tuple[EventSummary, ...]
    next_action: str


class ExecutionContextBuilder:
    """Build a deterministic context from defensive repository reads."""

    def __init__(self, repositories: RuntimeRepositories) -> None:
        self.repositories = repositories

    def build(self, project_id: str) -> ExecutionContext:
        project = self.repositories.projects.get(project_id)
        artifacts = [
            artifact
            for artifact in self.repositories.artifacts.all()
            if artifact["project_ref"]["id"] == project_id and artifact["status"] == "approved"
        ]
        decisions = [
            decision
            for decision in self.repositories.decisions.all()
            if decision["project_ref"]["id"] == project_id
        ]
        agents = [agent for agent in self.repositories.agents.all() if agent["status"] == "active"]
        workflows = [workflow for workflow in self.repositories.workflows.all() if workflow["status"] == "active"]
        events = self.repositories.events.for_project(project_id)

        return ExecutionContext(
            project_id=project_id,
            current_state=project["current_state"],
            completed_artifacts=tuple(sorted({artifact["artifact_type"] for artifact in artifacts})),
            pending_artifacts=tuple(sorted(set(project["pending_artifact_types"]))),
            available_agents=tuple(
                sorted(
                    AvailableAgent(agent["id"], agent["name"], agent["role"], agent["version"])
                    for agent in agents
                )
            ),
            available_workflows=tuple(
                sorted(
                    AvailableWorkflow(
                        workflow["id"],
                        workflow["name"],
                        workflow["entry_state"],
                        tuple(workflow["exit_states"]),
                        workflow["version"],
                    )
                    for workflow in workflows
                )
            ),
            decisions=tuple(
                sorted(DecisionSummary(decision["id"], decision["title"], decision["status"]) for decision in decisions)
            ),
            risks=tuple(project["risks"]),
            events=tuple(EventSummary(event["sequence"], event["id"], event["event_type"]) for event in events),
            next_action=project["next_action"],
        )
