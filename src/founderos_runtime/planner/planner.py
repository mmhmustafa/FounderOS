"""Deterministic read-only planning over a validated Workspace."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from founderos_runtime.workspace import Workspace, WorkspaceItemNotFoundError

from .exceptions import (
    PlannerAgentNotFoundError,
    PlannerArtifactReferenceError,
    PlannerCircularDependencyError,
    PlannerInvalidWorkflowError,
    PlannerWorkflowNotFoundError,
)
from .execution_plan import (
    ArtifactReference,
    DefinitionReference,
    ExecutionPlan,
    ExecutionStep,
)


PLANNER_VERSION = "1.0.0"


class Planner:
    """Produce immutable ExecutionPlans without executing or mutating anything."""

    def __init__(self, workspace: Workspace) -> None:
        if not isinstance(workspace, Workspace):
            raise TypeError("Planner requires a Workspace")
        self._workspace = workspace

    def plan(self, workflow_id: str) -> ExecutionPlan:
        if not isinstance(workflow_id, str) or not workflow_id:
            raise PlannerInvalidWorkflowError("workflow_id must be a non-empty string")
        try:
            workflow = self._workspace.get_workflow(workflow_id)
        except WorkspaceItemNotFoundError as error:
            raise PlannerWorkflowNotFoundError(f"workflow id not found: {workflow_id!r}") from error

        self._validate_workflow_shape(workflow)
        required_agents = self._resolve_agents(workflow)
        required_artifacts = self._artifact_references(workflow["required_artifacts"])
        produced_artifacts = self._artifact_references(workflow["produced_artifacts"])
        normalized_steps = self._with_checkpoints(workflow)
        ordered_steps = self._order_steps(
            normalized_steps,
            {artifact.id for artifact in required_artifacts},
            {artifact.id for artifact in produced_artifacts},
        )
        evaluation_subjects = {item["subject_artifact"] for item in workflow["evaluations"]}
        approval_subjects = {
            item["subject_ref"]
            for item in workflow["approvals"]
            if item["subject_type"] == "artifact"
        }
        steps = tuple(
            self._execution_step(step, evaluation_subjects, approval_subjects)
            for step in ordered_steps
        )
        return ExecutionPlan(
            workflow_id=workflow["id"],
            steps=steps,
            required_agents=required_agents,
            required_artifacts=required_artifacts,
            produced_artifacts=produced_artifacts,
            evaluations=tuple(deepcopy(workflow["evaluations"])),
            approvals=tuple(deepcopy(workflow["approvals"])),
            transition_request=deepcopy(workflow["transition_intent"]),
            metadata={
                "planner_version": PLANNER_VERSION,
                "workflow_version": workflow["version"],
                "workflow_type": workflow["workflow_type"],
                "step_order": [step.id for step in steps],
                "source": "workspace",
            },
        )

    def summary(self) -> dict[str, Any]:
        workspace_summary = self._workspace.summary()
        return {
            "planner_version": PLANNER_VERSION,
            "workspace_root": workspace_summary["project_root"],
            "workflow_count": workspace_summary["counts"]["workflows"],
            "available_workflows": list(workspace_summary["workflows"]),
            "read_only": True,
        }

    @staticmethod
    def _validate_workflow_shape(workflow: dict[str, Any]) -> None:
        required = {
            "id",
            "version",
            "workflow_type",
            "required_agents",
            "required_artifacts",
            "produced_artifacts",
            "steps",
            "evaluations",
            "approvals",
            "transition_intent",
        }
        missing = sorted(required - set(workflow))
        if missing:
            raise PlannerInvalidWorkflowError(
                f"workflow {workflow.get('id', '<unknown>')!r} is missing field {missing[0]!r}"
            )
        step_ids = [step.get("id") for step in workflow["steps"]]
        if any(not isinstance(identifier, str) or not identifier for identifier in step_ids):
            raise PlannerInvalidWorkflowError("workflow step ids must be non-empty strings")
        if len(step_ids) != len(set(step_ids)):
            raise PlannerInvalidWorkflowError("workflow contains duplicate step ids")

    def _resolve_agents(self, workflow: dict[str, Any]) -> tuple[DefinitionReference, ...]:
        resolved: list[DefinitionReference] = []
        by_id: dict[str, DefinitionReference] = {}
        for reference in sorted(
            workflow["required_agents"], key=lambda item: (item["id"], item["version"])
        ):
            try:
                agent = self._workspace.get_agent(reference["id"])
            except WorkspaceItemNotFoundError as error:
                raise PlannerAgentNotFoundError(
                    f"workflow {workflow['id']!r} requires missing agent {reference['id']!r}"
                ) from error
            if agent["version"] != reference["version"]:
                raise PlannerAgentNotFoundError(
                    f"workflow {workflow['id']!r} requires agent {reference['id']!r} "
                    f"version {reference['version']}; found {agent['version']}"
                )
            item = DefinitionReference(
                id=reference["id"],
                version=reference["version"],
                role=reference.get("role"),
            )
            resolved.append(item)
            by_id[item.id] = item
        for step in workflow["steps"]:
            reference = step.get("required_agent")
            if reference is None:
                continue
            if reference["id"] not in by_id or by_id[reference["id"]].version != reference["version"]:
                raise PlannerAgentNotFoundError(
                    f"step {step['id']!r} references unavailable required agent "
                    f"{reference['id']!r} version {reference['version']}"
                )
        return tuple(resolved)

    @staticmethod
    def _artifact_references(items: list[dict[str, Any]]) -> tuple[ArtifactReference, ...]:
        return tuple(
            ArtifactReference(
                id=item["id"],
                artifact_type=item["artifact_type"],
                schema_ref=item["schema_ref"],
            )
            for item in sorted(items, key=lambda item: item["id"])
        )

    @staticmethod
    def _with_checkpoints(workflow: dict[str, Any]) -> list[dict[str, Any]]:
        steps = deepcopy(workflow["steps"])
        evaluation_covered = {
            artifact
            for step in steps
            if step["type"] == "evaluation"
            for artifact in step["input_artifacts"]
        }
        for evaluation in sorted(workflow["evaluations"], key=lambda item: item["id"]):
            subject = evaluation["subject_artifact"]
            if subject not in evaluation_covered:
                steps.append(
                    {
                        "id": f"evaluation.{evaluation['id']}",
                        "name": f"Evaluate {subject}",
                        "type": "evaluation",
                        "required_agent": None,
                        "input_artifacts": [subject],
                        "output_artifacts": [],
                        "requires_approval": False,
                    }
                )
        approval_covered = {
            artifact
            for step in steps
            if step["type"] == "approval"
            for artifact in step["input_artifacts"]
        }
        for approval in sorted(workflow["approvals"], key=lambda item: item["id"]):
            subject = approval["subject_ref"]
            if approval["subject_type"] == "artifact" and subject not in approval_covered:
                steps.append(
                    {
                        "id": f"approval.{approval['id']}",
                        "name": f"Approve {subject}",
                        "type": "approval",
                        "required_agent": None,
                        "input_artifacts": [subject],
                        "output_artifacts": [],
                        "requires_approval": True,
                    }
                )
        return steps

    @staticmethod
    def _order_steps(
        steps: list[dict[str, Any]],
        required_artifacts: set[str],
        declared_produced_artifacts: set[str],
    ) -> list[dict[str, Any]]:
        by_id = {step["id"]: step for step in steps}
        if len(by_id) != len(steps):
            raise PlannerInvalidWorkflowError("normalized workflow contains duplicate step ids")
        positions = {step["id"]: index for index, step in enumerate(steps)}
        producers: dict[str, str] = {}
        for step in steps:
            for artifact in step["output_artifacts"]:
                if artifact not in declared_produced_artifacts:
                    raise PlannerArtifactReferenceError(
                        f"step {step['id']!r} produces undeclared artifact {artifact!r}"
                    )
                if artifact in producers:
                    raise PlannerArtifactReferenceError(
                        f"artifact {artifact!r} has multiple producers: "
                        f"{producers[artifact]!r} and {step['id']!r}"
                    )
                producers[artifact] = step["id"]
        missing_producers = sorted(declared_produced_artifacts - set(producers))
        if missing_producers:
            raise PlannerArtifactReferenceError(
                f"declared produced artifact {missing_producers[0]!r} has no producing step"
            )

        dependencies: dict[str, set[str]] = {step["id"]: set() for step in steps}
        for step in steps:
            for artifact in step["input_artifacts"]:
                producer = producers.get(artifact)
                if producer is not None:
                    dependencies[step["id"]].add(producer)
                elif artifact not in required_artifacts:
                    raise PlannerArtifactReferenceError(
                        f"step {step['id']!r} requires missing artifact {artifact!r}"
                    )

        evaluation_steps = [step["id"] for step in steps if step["type"] == "evaluation"]
        approval_steps = [step["id"] for step in steps if step["type"] == "approval"]
        for step in steps:
            if step["type"] == "approval":
                dependencies[step["id"]].update(
                    identifier
                    for identifier in evaluation_steps
                    if positions[identifier] < positions[step["id"]]
                )
            if step["type"] == "transition_request":
                dependencies[step["id"]].update(evaluation_steps + approval_steps)

        ordered: list[dict[str, Any]] = []
        remaining = set(by_id)
        while remaining:
            ready = sorted(
                (identifier for identifier in remaining if not (dependencies[identifier] & remaining)),
                key=lambda identifier: (positions[identifier], identifier),
            )
            if not ready:
                cycle = sorted(remaining, key=lambda identifier: (positions[identifier], identifier))
                raise PlannerCircularDependencyError(
                    f"circular step dependency involving: {', '.join(cycle)}"
                )
            for identifier in ready:
                ordered.append(by_id[identifier])
                remaining.remove(identifier)
        return ordered

    @staticmethod
    def _execution_step(
        step: dict[str, Any],
        evaluation_subjects: set[str],
        approval_subjects: set[str],
    ) -> ExecutionStep:
        reference = step.get("required_agent")
        agent = (
            DefinitionReference(
                id=reference["id"],
                version=reference["version"],
                role=reference.get("role"),
            )
            if reference is not None
            else None
        )
        outputs = tuple(sorted(step["output_artifacts"]))
        inputs = tuple(sorted(step["input_artifacts"]))
        return ExecutionStep(
            id=step["id"],
            type=step["type"],
            description=step["name"],
            required_agent=agent,
            required_artifacts=inputs,
            produced_artifacts=outputs,
            requires_evaluation=(
                step["type"] == "evaluation" or bool(set(outputs) & evaluation_subjects)
            ),
            requires_approval=(
                bool(step.get("requires_approval"))
                or step["type"] == "approval"
                or bool(set(outputs) & approval_subjects)
            ),
        )
