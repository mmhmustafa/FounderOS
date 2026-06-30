"""Authoritative in-memory Project aggregate operations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .events import build_event
from .ids import new_id, utc_now
from .errors import ConflictError
from .repositories import RuntimeRepositories


def replay_project_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive the Project state/revision summary from one gap-free event stream."""

    summary: dict[str, Any] | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event["sequence"] != expected_sequence:
            raise ConflictError(
                f"Event stream integrity error: expected sequence {expected_sequence}, got {event['sequence']}"
            )
        if event["event_type"] == "project.created":
            if summary is not None:
                raise ConflictError("Event stream contains duplicate project.created events")
            summary = {
                "current_state": event["payload"]["current_state"],
                "revision": event["payload"]["revision"],
                "last_aggregate_event_sequence": event["sequence"],
            }
        elif summary is None:
            raise ConflictError("Event stream must begin with project.created")
        elif event["event_type"] == "transition.applied":
            if event["payload"]["from_state"] != summary["current_state"]:
                raise ConflictError("Applied transition does not match replayed state")
            summary["current_state"] = event["payload"]["to_state"]
            summary["revision"] = event["payload"]["resulting_project_revision"]
            summary["last_aggregate_event_sequence"] = event["sequence"]
        elif event["event_type"] == "project.updated":
            summary["revision"] = event["payload"]["revision"]
            summary["last_aggregate_event_sequence"] = event["sequence"]
    if summary is None:
        raise ConflictError("Cannot replay an empty Project event stream")
    return summary


class ProjectStateService:
    """Create and update Projects without permitting direct state transitions."""

    def __init__(self, repositories: RuntimeRepositories) -> None:
        self.repositories = repositories
        self._create_correlations: dict[str, str] = {}

    def create_project(
        self,
        *,
        name: str,
        founder_id: str,
        founder_name: str,
        domain: str,
        actor: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        with self.repositories.lock:
            existing_id = self._create_correlations.get(correlation_id)
            if existing_id:
                return self.repositories.projects.get(existing_id)

            now = utc_now()
            project = {
                "id": new_id("project"),
                "revision": 1,
                "status": "active",
                "name": name,
                "founder": {"actor_id": founder_id, "display_name": founder_name},
                "domain": domain,
                "current_state": "NO_PROJECT",
                "completed_artifact_refs": [],
                "pending_artifact_types": [],
                "decision_refs": [],
                "risks": [],
                "next_action": "Begin founder setup",
                "last_event_sequence": 1,
                "created_at": now,
                "updated_at": now,
                "metadata": {"correlation_id": correlation_id},
            }
            project = self.repositories.contracts.validate("project", project)
            event = build_event(
                self.repositories,
                project_id=project["id"],
                event_type="project.created",
                actor=actor,
                subject_ref={"kind": "project", "id": project["id"], "revision": 1},
                correlation_id=correlation_id,
                payload={"name": name, "current_state": "NO_PROJECT", "revision": 1},
            )
            event = self.repositories.contracts.validate("event", event)

            project_snapshot = self.repositories.projects._snapshot()
            event_snapshot = self.repositories.events._snapshot()
            try:
                self.repositories.projects._insert_validated(project)
                self.repositories.events._append_validated(event)
                self._create_correlations[correlation_id] = project["id"]
            except Exception:
                self.repositories.projects._restore(project_snapshot)
                self.repositories.events._restore(event_snapshot)
                raise
            return deepcopy(project)

    def get(self, project_id: str) -> dict[str, Any]:
        return self.repositories.projects.get(project_id)

    def update_details(
        self,
        project_id: str,
        *,
        expected_revision: int,
        actor: dict[str, Any],
        correlation_id: str,
        next_action: str | None = None,
        risks: list[str] | None = None,
    ) -> dict[str, Any]:
        with self.repositories.lock:
            current = self.repositories.projects.get(project_id)
            updated = deepcopy(current)
            updated["revision"] = current["revision"] + 1
            updated["updated_at"] = utc_now()
            if next_action is not None:
                updated["next_action"] = next_action
            if risks is not None:
                updated["risks"] = list(risks)
            event = build_event(
                self.repositories,
                project_id=project_id,
                event_type="project.updated",
                actor=actor,
                subject_ref={"kind": "project", "id": project_id, "revision": updated["revision"]},
                correlation_id=correlation_id,
                payload={"revision": updated["revision"], "next_action": updated["next_action"]},
            )
            updated["last_event_sequence"] = event["sequence"]
            validated = self.repositories.contracts.validate("project", updated)
            event = self.repositories.contracts.validate("event", event)
            project_snapshot = self.repositories.projects._snapshot()
            event_snapshot = self.repositories.events._snapshot()
            try:
                self.repositories.projects._replace_validated(validated, expected_revision=expected_revision)
                self.repositories.events._append_validated(event)
            except Exception:
                self.repositories.projects._restore(project_snapshot)
                self.repositories.events._restore(event_snapshot)
                raise
            return deepcopy(validated)
