"""Read-only structured runtime diagnostics and audit inspection."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from .content import InMemoryContentStore
from .local_store import LocalProjectStore
from .project_state import replay_project_events
from .repositories import RuntimeRepositories


REDACTED = "[REDACTED]"
SENSITIVE_KEYS = frozenset({
    "content", "founder_profile", "startup_context", "background", "known_problem_area",
    "rationale", "selected_option", "constraints", "open_questions",
})


def redact(value: Any, *, include_sensitive: bool = False) -> Any:
    """Recursively redact known sensitive fields from diagnostic output."""

    if include_sensitive:
        return deepcopy(value)
    if isinstance(value, dict):
        return {
            key: REDACTED if key in SENSITIVE_KEYS else redact(item, include_sensitive=False)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, include_sensitive=False) for item in value]
    return deepcopy(value)


def command_correlation(correlation_id: str) -> str:
    parts = correlation_id.split(":")
    return ":".join(parts[:3]) if len(parts) >= 3 and parts[0] == "cli" else correlation_id


class RuntimeDiagnostics:
    """Build disposable summaries without mutating repositories or persistence."""

    def __init__(
        self, repositories: RuntimeRepositories, content: InMemoryContentStore,
        store: LocalProjectStore | None = None,
    ) -> None:
        self.repositories = repositories
        self.content = content
        self.store = store

    def project(self, project_id: str) -> dict[str, Any]:
        project = self.repositories.projects.get(project_id)
        return {
            "id": project["id"], "name": project["name"], "status": project["status"],
            "current_state": project["current_state"], "revision": project["revision"],
            "completed_artifact_refs": project["completed_artifact_refs"],
            "pending_artifact_types": project["pending_artifact_types"], "next_action": project["next_action"],
        }

    def events(self, project_id: str) -> list[dict[str, Any]]:
        return [
            {
                "sequence": event["sequence"], "event_id": event["id"], "event_type": event["event_type"],
                "correlation_id": event["correlation_id"],
                "command_correlation_id": command_correlation(event["correlation_id"]),
                "actor": event["actor"], "subject_ref": event["subject_ref"],
                "occurred_at": event["occurred_at"], "payload": redact(event["payload"]),
            }
            for event in self.repositories.events.for_project(project_id)
        ]

    def runs(self, project_id: str) -> dict[str, Any]:
        event_index = self._subject_correlations(project_id)
        workflows = [record for record in self.repositories.workflow_runs.all() if record["project_ref"]["id"] == project_id]
        agents = [record for record in self.repositories.agent_runs.all() if record["project_ref"]["id"] == project_id]
        return {
            "workflow_runs": [self._run_summary("workflow_run", record, event_index) for record in workflows],
            "agent_runs": [self._run_summary("agent_run", record, event_index) for record in agents],
        }

    def approvals(self, project_id: str, *, include_sensitive: bool = False) -> list[dict[str, Any]]:
        return [
            redact({
                "id": item["id"], "status": item["status"], "approval_type": item["approval_type"],
                "subject_ref": item["subject_ref"], "requested_by": item["requested_by"],
                "decided_by": item.get("decided_by"), "rationale": item.get("rationale"),
                "requested_at": item["requested_at"], "decided_at": item.get("decided_at"),
                "command_correlation_id": command_correlation(item.get("metadata", {}).get("correlation_id", "")),
            }, include_sensitive=include_sensitive)
            for item in self.repositories.approvals.all() if item["project_ref"]["id"] == project_id
        ]

    def evaluations(self, project_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": item["id"], "target_ref": item["target_ref"], "type": item["evaluation_type"],
                "status": item["status"], "outcome": item["outcome"],
                "confidence_score": item.get("confidence_score"), "completed_at": item["completed_at"],
                "command_correlation_id": command_correlation(item.get("metadata", {}).get("correlation_id", "")),
            }
            for item in self.repositories.evaluations.all() if item["project_ref"]["id"] == project_id
        ]

    def transitions(self, project_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in self.repositories.transitions.all():
            if item["project_ref"]["id"] != project_id:
                continue
            approval_refs = item.get("approval_refs", [])
            artifact_refs: list[dict[str, Any]] = []
            for approval_ref in approval_refs:
                approval = self.repositories.approvals.get(approval_ref["id"])
                if approval["subject_ref"]["kind"] == "artifact":
                    artifact_refs.append(approval["subject_ref"])
            results.append({
                "id": item["id"], "status": item["status"], "from_state": item["from_state"],
                "to_state": item["to_state"], "trigger": item["trigger"],
                "command_correlation_id": command_correlation(item.get("metadata", {}).get("correlation_id", "")),
                "workflow_run_ref": item.get("workflow_run_ref"), "approval_refs": approval_refs,
                "artifact_refs": artifact_refs, "rejection_code": item.get("rejection_code"),
                "requested_at": item["requested_at"], "decided_at": item["decided_at"],
            })
        return results

    def audit(self, project_id: str, *, include_sensitive: bool = False) -> dict[str, Any]:
        events = self.events(project_id)
        transitions = self.transitions(project_id)
        artifacts = []
        for item in self.repositories.artifacts.all():
            if item["project_ref"]["id"] != project_id:
                continue
            summary: dict[str, Any] = {
                "id": item["id"], "artifact_type": item["artifact_type"], "status": item["status"],
                "version": item["version"], "content_digest": item["content_digest"],
                "approval_refs": item.get("approval_refs", []), "evaluation_refs": item.get("evaluation_refs", []),
                "produced_by_run_ref": item.get("produced_by_run_ref"),
                "input_artifact_refs": item.get("input_artifact_refs", []),
                "command_correlation_id": command_correlation(item.get("metadata", {}).get("correlation_id", "")),
            }
            if include_sensitive:
                summary["content"] = self.content.get(item["content_uri"])
            artifacts.append(redact(summary, include_sensitive=include_sensitive))
        replayed = replay_project_events(self.repositories.events.for_project(project_id))
        project = self.repositories.projects.get(project_id)
        consistency = {
            "event_sequences_gap_free": [event["sequence"] for event in events] == list(range(1, len(events) + 1)),
            "project_matches_event_replay": (
                replayed["current_state"], replayed["revision"]
            ) == (project["current_state"], project["revision"]),
            "transition_events_resolve": self._transition_events_resolve(project_id),
        }
        commands = self._command_summaries(events)
        return {
            "project": self.project(project_id), "persistence": self.store.health().to_dict() if self.store else None,
            "commands": commands, "timeline": events, "runs": self.runs(project_id),
            "approvals": self.approvals(project_id, include_sensitive=include_sensitive), "evaluations": self.evaluations(project_id),
            "transitions": transitions, "artifacts": artifacts, "consistency": consistency,
        }

    def _subject_correlations(self, project_id: str) -> dict[tuple[str, str], set[str]]:
        index: dict[tuple[str, str], set[str]] = {}
        for event in self.repositories.events.for_project(project_id):
            key = (event["subject_ref"]["kind"], event["subject_ref"]["id"])
            index.setdefault(key, set()).add(command_correlation(event["correlation_id"]))
        return index

    @staticmethod
    def _run_summary(kind: str, record: dict[str, Any], index: dict[tuple[str, str], set[str]]) -> dict[str, Any]:
        return {
            "id": record["id"], "status": record["status"], "revision": record["revision"],
            "attempt": record["attempt"], "command_correlation_ids": sorted(index.get((kind, record["id"]), set())),
            "record_correlation_id": command_correlation(record.get("metadata", {}).get("correlation_id", "")),
            "created_at": record["created_at"], "started_at": record.get("started_at"),
            "completed_at": record.get("completed_at"),
        }

    @staticmethod
    def _command_summaries(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            grouped.setdefault(event["command_correlation_id"], []).append(event)
        summaries = []
        for correlation, group in grouped.items():
            first, last = group[0], group[-1]
            duration_ms = max(0.0, (datetime.fromisoformat(last["occurred_at"].replace("Z", "+00:00")) - datetime.fromisoformat(first["occurred_at"].replace("Z", "+00:00"))).total_seconds() * 1000)
            summaries.append({
                "command_correlation_id": correlation, "first_sequence": first["sequence"],
                "last_sequence": last["sequence"], "event_count": len(group),
                "event_types": [event["event_type"] for event in group], "duration_ms": duration_ms,
            })
        return summaries

    def _transition_events_resolve(self, project_id: str) -> bool:
        transition_ids = {item["id"] for item in self.repositories.transitions.all() if item["project_ref"]["id"] == project_id}
        return all(
            event["subject_ref"]["id"] in transition_ids
            for event in self.repositories.events.for_project(project_id)
            if event["event_type"].startswith("transition.")
        )
