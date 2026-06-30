"""Thin application facade used by the FounderOS CLI."""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from typing import Any
from uuid import uuid4

from .errors import ApprovalRequiredError, RecordNotFoundError, VerticalSliceError
from .execution_context import ExecutionContextBuilder
from .founder_setup import FounderBriefPreparation, FounderSetupService
from .local_store import LocalProjectStore, LocalRuntime


class FounderOSApplication:
    """Load, invoke existing runtime services, and persist command results."""

    def __init__(self, root: str | Path = ".founderos") -> None:
        self.store = LocalProjectStore(root)

    def new(self, *, name: str, founder_id: str, founder_name: str, domain: str, command_key: str | None = None) -> dict[str, Any]:
        if self.store.exists:
            runtime = self.store.load()
            replayed = self._replay_command(runtime, command_key, "new")
            if replayed is not None:
                return replayed
            raise VerticalSliceError(f"A FounderOS project already exists at {self.store.root}")
        runtime = self.store.empty_runtime()
        service = FounderSetupService(runtime.repositories, runtime.content)
        actor = self._human(founder_id, founder_name)
        project = service.create_project(
            name=name, founder_id=founder_id, founder_name=founder_name, domain=domain,
            actor=actor, correlation_id=self._correlation("new"),
        )
        result = {"project_id": project["id"], "state": project["current_state"], "next_action": project["next_action"]}
        self._record_command(runtime, command_key, "new", result)
        self.store.save(runtime)
        return result

    def status(self) -> dict[str, Any]:
        runtime, project = self._load_project()
        context = ExecutionContextBuilder(runtime.repositories).build(project["id"])
        plan = FounderSetupService(runtime.repositories, runtime.content).plan(project["id"])
        return {
            "project_id": project["id"], "name": project["name"], "state": project["current_state"],
            "completed_artifacts": list(context.completed_artifacts),
            "pending_artifacts": list(plan.missing_artifacts),
            "next_action": project["next_action"],
        }

    def plan(self) -> dict[str, Any]:
        runtime, project = self._load_project()
        return FounderSetupService(runtime.repositories, runtime.content).plan(project["id"]).to_dict()

    def founder_brief(self, content: dict[str, Any], *, command_key: str | None = None) -> dict[str, Any]:
        runtime, project = self._load_project()
        replayed = self._replay_command(runtime, command_key, "founder-brief")
        if replayed is not None:
            return replayed
        service = FounderSetupService(runtime.repositories, runtime.content)
        actor = self._project_actor(project)
        session = service.start(project["id"], actor=actor, correlation_id=self._correlation("founder-setup"))
        preparation = service.produce_founder_brief(
            session,
            founder_profile=self._object(content, "founder_profile"),
            startup_context=self._object(content, "startup_context"),
            assumptions=self._list(content, "assumptions"), risks=self._list(content, "risks"),
            open_questions=self._list(content, "open_questions"), correlation_id=self._correlation("founder-brief"),
        )
        artifact = runtime.repositories.artifacts.get(preparation.artifact_id)
        result = {
            "artifact_id": artifact["id"], "artifact_status": artifact["status"],
            "approval_id": preparation.approval_id, "project_state": service.projects.get(project["id"])["current_state"],
        }
        self._record_command(runtime, command_key, "founder-brief", result)
        self.store.save(runtime)
        return result

    def approve(self, *, rationale: str, founder_id: str | None = None, founder_name: str | None = None, command_key: str | None = None) -> dict[str, Any]:
        runtime, project = self._load_project()
        replayed = self._replay_command(runtime, command_key, "approve")
        if replayed is not None:
            return replayed
        service = FounderSetupService(runtime.repositories, runtime.content)
        preparation = self._pending_preparation(runtime, project["id"])
        actor = self._human(founder_id or project["founder"]["actor_id"], founder_name or project["founder"]["display_name"])
        approval = service.approve_founder_brief(
            preparation, actor=actor, rationale=rationale, correlation_id=self._correlation("approve"))
        completion = service.complete(
            preparation, actor=actor, correlation_id=self._correlation("complete"))
        if completion.transition["status"] != "applied":
            raise VerticalSliceError(
                f"Transition rejected: {completion.transition.get('rejection_code', 'unknown')}"
            )
        result = {
            "approval_id": approval["id"], "approval_status": approval["status"],
            "transition_id": completion.transition["id"], "transition_status": completion.transition["status"],
            "project_state": completion.project["current_state"],
        }
        self._record_command(runtime, command_key, "approve", result)
        self.store.save(runtime)
        return result

    def decisions(self) -> list[dict[str, Any]]:
        runtime, project = self._load_project()
        return [
            {"id": item["id"], "title": item["title"], "status": item["status"], "selected_option": item.get("selected_option")}
            for item in runtime.repositories.decisions.all() if item["project_ref"]["id"] == project["id"]
        ]

    def events(self) -> list[dict[str, Any]]:
        runtime, project = self._load_project()
        return [
            {"sequence": event["sequence"], "event_type": event["event_type"], "subject": event["subject_ref"], "occurred_at": event["occurred_at"]}
            for event in runtime.repositories.events.for_project(project["id"])
        ]

    def health(self) -> dict[str, Any]:
        return self.store.health().to_dict()

    def recover(self) -> dict[str, Any]:
        return self.store.recover().to_dict()

    @staticmethod
    def _replay_command(runtime: LocalRuntime, command_key: str | None, operation: str) -> dict[str, Any] | None:
        if command_key is None:
            return None
        entry = (runtime.commands or {}).get(command_key)
        if entry is None:
            return None
        if entry.get("operation") != operation:
            raise VerticalSliceError("Idempotency key was already used for a different command")
        result = entry.get("result")
        if not isinstance(result, dict):
            raise VerticalSliceError("Persisted idempotency result is invalid")
        return deepcopy(result)

    @staticmethod
    def _record_command(runtime: LocalRuntime, command_key: str | None, operation: str, result: dict[str, Any]) -> None:
        if command_key is None:
            return
        assert runtime.commands is not None
        runtime.commands[command_key] = {"operation": operation, "result": deepcopy(result)}

    def _load_project(self) -> tuple[LocalRuntime, dict[str, Any]]:
        runtime = self.store.load()
        projects = runtime.repositories.projects.all()
        if len(projects) != 1:
            raise RecordNotFoundError("Local FounderOS store does not contain exactly one Project")
        return runtime, projects[0]

    @staticmethod
    def _pending_preparation(runtime: LocalRuntime, project_id: str) -> FounderBriefPreparation:
        approvals = [
            item for item in runtime.repositories.approvals.all()
            if item["project_ref"]["id"] == project_id and item["status"] == "pending" and item["approval_type"] == "artifact"
        ]
        if not approvals:
            raise ApprovalRequiredError("No pending Founder Brief approval exists")
        approval = approvals[-1]
        artifact = runtime.repositories.artifacts.get(approval["subject_ref"]["id"])
        if artifact["artifact_type"] != "founder_brief":
            raise ApprovalRequiredError("Pending approval does not target a Founder Brief")
        evaluations = [item for item in runtime.repositories.evaluations.all() if item["target_ref"]["id"] == artifact["id"]]
        workflow_runs = [item for item in runtime.repositories.workflow_runs.all() if item["project_ref"]["id"] == project_id and item["status"] == "running"]
        if not evaluations or not workflow_runs or "produced_by_run_ref" not in artifact:
            raise ApprovalRequiredError("Founder Brief evidence is incomplete")
        return FounderBriefPreparation(
            project_id, workflow_runs[-1]["id"], artifact["produced_by_run_ref"]["id"], artifact["id"],
            evaluations[-1]["id"], approval["id"], runtime.content.get(artifact["content_uri"]),
        )

    @staticmethod
    def _project_actor(project: dict[str, Any]) -> dict[str, str]:
        return FounderOSApplication._human(project["founder"]["actor_id"], project["founder"]["display_name"])

    @staticmethod
    def _human(actor_id: str, display_name: str) -> dict[str, str]:
        return {"type": "human", "id": actor_id, "display_name": display_name}

    @staticmethod
    def _correlation(prefix: str) -> str:
        return f"cli:{prefix}:{uuid4().hex}"

    @staticmethod
    def _object(content: dict[str, Any], key: str) -> dict[str, Any]:
        value = content.get(key)
        if not isinstance(value, dict):
            raise VerticalSliceError(f"Founder Brief input requires object field: {key}")
        return value

    @staticmethod
    def _list(content: dict[str, Any], key: str) -> list[str]:
        value = content.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise VerticalSliceError(f"Founder Brief input field {key} must be an array of strings")
        return value
