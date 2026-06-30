"""Minimal WorkflowRun and AgentRun lifecycle services."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .events import build_event
from .ids import new_id, utc_now
from .repositories import InMemoryRepository, RuntimeRepositories

_WORKFLOW_ALLOWED = {
    "queued": {"running", "cancelled"},
    "running": {"waiting_for_input", "waiting_for_approval", "succeeded", "failed", "cancelled"},
    "waiting_for_input": {"running", "failed", "cancelled"},
    "waiting_for_approval": {"running", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}

_AGENT_ALLOWED = {
    "queued": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}


class _RunService:
    kind: str
    event_subject_kind: str
    allowed: dict[str, set[str]]
    event_types: dict[str, str]

    def __init__(self, repositories: RuntimeRepositories, repository: InMemoryRepository) -> None:
        self.repositories = repositories
        self.repository = repository

    def get(self, run_id: str) -> dict[str, Any]:
        return self.repository.get(run_id)

    def set_status(
        self,
        run_id: str,
        status: str,
        *,
        expected_revision: int,
        actor: dict[str, Any],
        correlation_id: str,
        failure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.repositories.lock:
            current = self.repository.get(run_id)
            if status not in self.allowed[current["status"]]:
                raise ValueError(f"Invalid {self.kind} lifecycle transition: {current['status']} -> {status}")
            now = utc_now()
            updated = deepcopy(current)
            updated["status"] = status
            updated["revision"] = current["revision"] + 1
            updated["updated_at"] = now
            if status == "running" and "started_at" not in updated:
                updated["started_at"] = now
            if status in {"succeeded", "failed", "cancelled"}:
                updated["completed_at"] = now
            if status == "failed":
                if failure is None:
                    raise ValueError("failure details are required when a run fails")
                updated["failure"] = failure
            validated = self.repositories.contracts.validate(self.kind, updated)

            event_type = self.event_types.get(status)
            if event_type is None:
                self.repository._replace_validated(validated, expected_revision=expected_revision)
                return deepcopy(validated)

            project_id = updated["project_ref"]["id"]
            event = build_event(
                self.repositories,
                project_id=project_id,
                event_type=event_type,
                actor=actor,
                subject_ref={"kind": self.event_subject_kind, "id": run_id, "revision": updated["revision"]},
                correlation_id=correlation_id,
                payload={"status": status, "revision": updated["revision"]},
            )
            event = self.repositories.contracts.validate("event", event)
            run_snapshot = self.repository._snapshot()
            event_snapshot = self.repositories.events._snapshot()
            try:
                self.repository._replace_validated(validated, expected_revision=expected_revision)
                self.repositories.events._append_validated(event)
            except Exception:
                self.repository._restore(run_snapshot)
                self.repositories.events._restore(event_snapshot)
                raise
            return deepcopy(validated)


class WorkflowRunService(_RunService):
    kind = "workflow_run"
    event_subject_kind = "workflow_run"
    allowed = _WORKFLOW_ALLOWED
    event_types = {"running": "workflow.started", "succeeded": "workflow.completed", "failed": "workflow.failed"}

    def __init__(self, repositories: RuntimeRepositories) -> None:
        super().__init__(repositories, repositories.workflow_runs)

    def create(
        self,
        *,
        project_ref: dict[str, Any],
        workflow_ref: dict[str, Any],
        entry_state: str,
        requested_exit_state: str | None = None,
        input_artifact_refs: list[dict[str, Any]] | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        project = self.repositories.resolve_reference(project_ref, project_id=project_ref["id"])
        self.repositories.resolve_reference(workflow_ref)
        if project["status"] != "active" or project["current_state"] != entry_state:
            raise ValueError("WorkflowRun entry state must match an active Project")
        now = utc_now()
        record: dict[str, Any] = {
            "id": new_id("workflow_run"),
            "revision": 1,
            "project_ref": project_ref,
            "workflow_ref": workflow_ref,
            "status": "queued",
            "entry_state": entry_state,
            "attempt": attempt,
            "input_artifact_refs": input_artifact_refs or [],
            "output_artifact_refs": [],
            "agent_run_refs": [],
            "evaluation_refs": [],
            "approval_refs": [],
            "created_at": now,
            "updated_at": now,
        }
        if requested_exit_state:
            record["requested_exit_state"] = requested_exit_state
        return self.repository.create(record)


class AgentRunService(_RunService):
    kind = "agent_run"
    event_subject_kind = "agent_run"
    allowed = _AGENT_ALLOWED
    event_types = {"running": "agent.started", "succeeded": "agent.completed", "failed": "agent.failed"}

    def __init__(self, repositories: RuntimeRepositories) -> None:
        super().__init__(repositories, repositories.agent_runs)

    def create(
        self,
        *,
        project_ref: dict[str, Any],
        workflow_run_ref: dict[str, Any],
        agent_ref: dict[str, Any],
        input_refs: list[dict[str, Any]] | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        self.repositories.resolve_reference(project_ref, project_id=project_ref["id"])
        workflow_run = self.repositories.resolve_reference(workflow_run_ref, project_id=project_ref["id"])
        self.repositories.resolve_reference(agent_ref)
        if workflow_run["status"] not in {"running", "waiting_for_input"}:
            raise ValueError("AgentRun requires an active WorkflowRun")
        now = utc_now()
        record = {
            "id": new_id("agent_run"),
            "revision": 1,
            "project_ref": project_ref,
            "workflow_run_ref": workflow_run_ref,
            "agent_ref": agent_ref,
            "status": "queued",
            "attempt": attempt,
            "input_refs": input_refs or [],
            "output_refs": [],
            "created_at": now,
            "updated_at": now,
        }
        return self.repository.create(record)

    def retry(self, failed_run_id: str) -> dict[str, Any]:
        failed = self.repository.get(failed_run_id)
        if failed["status"] != "failed" or not failed["failure"]["retryable"]:
            raise ValueError("Only retryable failed AgentRuns can be retried")
        return self.create(
            project_ref=failed["project_ref"],
            workflow_run_ref=failed["workflow_run_ref"],
            agent_ref=failed["agent_ref"],
            input_refs=failed["input_refs"],
            attempt=failed["attempt"] + 1,
        )

    def set_status(
        self,
        run_id: str,
        status: str,
        *,
        expected_revision: int,
        actor: dict[str, Any],
        correlation_id: str,
        failure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        updated = super().set_status(
            run_id,
            status,
            expected_revision=expected_revision,
            actor=actor,
            correlation_id=correlation_id,
            failure=failure,
        )
        if status != "failed":
            return updated

        workflow_run = self.repositories.resolve_reference(
            updated["workflow_run_ref"], project_id=updated["project_ref"]["id"]
        )
        workflow = self.repositories.resolve_reference(workflow_run["workflow_ref"])
        max_attempts = workflow["failure_policy"]["max_attempts"]
        if updated["attempt"] >= max_attempts and workflow_run["status"] not in {"failed", "cancelled", "succeeded"}:
            WorkflowRunService(self.repositories).set_status(
                workflow_run["id"],
                "failed",
                expected_revision=workflow_run["revision"],
                actor=actor,
                correlation_id=f"{correlation_id}:workflow",
                failure={
                    "code": "AGENT_RETRY_EXHAUSTED",
                    "message": "Agent retry policy exhausted",
                    "retryable": False,
                    "recovery_action": "Request a human recovery decision or start a new WorkflowRun",
                },
            )
        return updated
