"""Reusable Artifact, Evaluation, and Approval lifecycle services."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .events import build_event
from .ids import new_id, reference, utc_now
from .repositories import RuntimeRepositories


class _LifecycleService:
    def __init__(self, repositories: RuntimeRepositories) -> None:
        self.repositories = repositories

    def _event(self, *, project_id: str, event_type: str, actor: dict[str, Any], subject_ref: dict[str, Any], correlation_id: str, payload: dict[str, Any]) -> None:
        event = build_event(
            self.repositories, project_id=project_id, event_type=event_type, actor=actor,
            subject_ref=subject_ref, correlation_id=correlation_id, payload=payload,
        )
        self.repositories.events.append(event)


class ArtifactLifecycleService(_LifecycleService):
    def create(self, record: dict[str, Any], *, actor: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        record = deepcopy(record)
        record["metadata"] = {**record.get("metadata", {}), "correlation_id": correlation_id}
        artifact = self.repositories.artifacts.create(record)
        self._event(
            project_id=artifact["project_ref"]["id"], event_type="artifact.created", actor=actor,
            subject_ref=reference("artifact", artifact, include_version=True), correlation_id=correlation_id,
            payload={"artifact_type": artifact["artifact_type"], "status": artifact["status"]},
        )
        return artifact

    def approve_with_references(
        self, artifact_id: str, *, approval_ref: dict[str, Any], evaluation_refs: list[dict[str, Any]],
        actor: dict[str, Any], correlation_id: str,
    ) -> dict[str, Any]:
        artifact = self.repositories.artifacts.get(artifact_id)
        updated = deepcopy(artifact)
        updated.update({
            "revision": artifact["revision"] + 1, "status": "approved", "updated_at": utc_now(),
            "approval_refs": [approval_ref], "evaluation_refs": list(evaluation_refs),
        })
        updated = self.repositories.artifacts.replace(updated, expected_revision=artifact["revision"])
        self._event(
            project_id=artifact["project_ref"]["id"], event_type="artifact.approved", actor=actor,
            subject_ref=reference("artifact", updated, include_version=True), correlation_id=correlation_id,
            payload={"status": "approved"},
        )
        return updated


class EvaluationLifecycleService(_LifecycleService):
    def create(self, record: dict[str, Any], *, actor: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        record = deepcopy(record)
        record["metadata"] = {**record.get("metadata", {}), "correlation_id": correlation_id}
        evaluation = self.repositories.evaluations.create(record)
        self._event(
            project_id=evaluation["project_ref"]["id"], event_type="evaluation.completed", actor=actor,
            subject_ref=reference("evaluation", evaluation), correlation_id=correlation_id,
            payload={"outcome": evaluation["outcome"]},
        )
        return evaluation


class ApprovalLifecycleService(_LifecycleService):
    def request(self, record: dict[str, Any], *, actor: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        record = deepcopy(record)
        record["metadata"] = {**record.get("metadata", {}), "correlation_id": correlation_id}
        approval = self.repositories.approvals.create(record)
        self._event(
            project_id=approval["project_ref"]["id"], event_type="approval.requested", actor=actor,
            subject_ref=reference("approval", approval), correlation_id=correlation_id,
            payload={"status": approval["status"]},
        )
        return approval

    def approve(self, approval_id: str, *, actor: dict[str, Any], rationale: str, correlation_id: str) -> dict[str, Any]:
        if actor.get("type") != "human":
            raise ValueError("Approval must be decided by a human")
        approval = self.repositories.approvals.get(approval_id)
        if approval["status"] == "approved":
            return approval
        if approval["status"] != "pending":
            raise ValueError(f"Approval is {approval['status']}")
        updated = deepcopy(approval)
        updated.update({
            "revision": approval["revision"] + 1, "status": "approved", "decided_by": actor,
            "rationale": rationale, "decided_at": utc_now(),
        })
        updated = self.repositories.approvals.replace(updated, expected_revision=approval["revision"])
        self._event(
            project_id=approval["project_ref"]["id"], event_type="approval.decided", actor=actor,
            subject_ref=reference("approval", updated, include_revision=True), correlation_id=correlation_id,
            payload={"status": "approved"},
        )
        return updated


class DecisionLifecycleService(_LifecycleService):
    def create(self, record: dict[str, Any], *, actor: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        record = deepcopy(record)
        record["metadata"] = {**record.get("metadata", {}), "correlation_id": correlation_id}
        decision = self.repositories.decisions.create(record)
        self._event(
            project_id=decision["project_ref"]["id"], event_type="decision.approved", actor=actor,
            subject_ref=reference("decision", decision, include_version=True), correlation_id=correlation_id,
            payload={"status": decision["status"], "title": decision["title"]},
        )
        return decision
