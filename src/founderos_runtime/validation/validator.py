"""Deterministic read-only validation of Workspace ExecutionPlans."""

from __future__ import annotations

from typing import Any

from founderos_runtime.planner.execution_plan import ExecutionPlan
from founderos_runtime.workspace import Workspace, WorkspaceItemNotFoundError

from .exceptions import PlanValidationError
from .report import ValidationFinding, ValidationReport, report
from .rules import artifact_graph, cyclic_nodes, duplicate_values, error


PLAN_VALIDATOR_VERSION = "1.0.0"


class PlanValidator:
    def __init__(self, workspace: Workspace) -> None:
        if not isinstance(workspace, Workspace):
            raise TypeError("PlanValidator requires a Workspace")
        self._workspace = workspace

    def validate(self, plan: ExecutionPlan) -> ValidationReport:
        if not isinstance(plan, ExecutionPlan):
            raise PlanValidationError("validate requires an ExecutionPlan")
        findings: list[ValidationFinding] = []
        workflow = self._workflow(plan, findings)
        self._duplicates(plan, findings)
        self._agents(plan, findings)
        self._artifacts(plan, findings)
        self._dependencies(plan, findings)
        self._evaluations(plan, findings)
        self._approvals(plan, findings)
        if workflow is not None and plan.metadata.get("workflow_version") != workflow.get("version"):
            findings.append(
                error(
                    "workflow.version_mismatch",
                    "plan workflow version does not match Workspace definition",
                    plan.workflow_id,
                )
            )
        return report(
            findings,
            {
                "validator_version": PLAN_VALIDATOR_VERSION,
                "workflow_id": plan.workflow_id,
                "step_count": len(plan.steps),
                "workspace_runtime_version": self._workspace.runtime_version,
            },
        )

    def summary(self) -> dict[str, Any]:
        return {
            "validator_version": PLAN_VALIDATOR_VERSION,
            "workspace_root": str(self._workspace.project_root),
            "deterministic": True,
            "read_only": True,
        }

    def _workflow(
        self, plan: ExecutionPlan, findings: list[ValidationFinding]
    ) -> dict[str, Any] | None:
        try:
            return self._workspace.get_workflow(plan.workflow_id)
        except WorkspaceItemNotFoundError:
            findings.append(
                error("workflow.missing", "plan Workflow does not exist in Workspace", plan.workflow_id)
            )
            return None

    @staticmethod
    def _duplicates(plan: ExecutionPlan, findings: list[ValidationFinding]) -> None:
        groups = {
            "step": (step.id for step in plan.steps),
            "agent": (agent.id for agent in plan.required_agents),
            "required_artifact": (item.id for item in plan.required_artifacts),
            "produced_artifact": (item.id for item in plan.produced_artifacts),
            "evaluation": (str(item.get("id", "")) for item in plan.evaluations),
        }
        for kind, values in groups.items():
            for identifier in duplicate_values(values):
                findings.append(
                    error("id.duplicate", f"duplicate {kind} id {identifier!r}", identifier)
                )

    def _agents(self, plan: ExecutionPlan, findings: list[ValidationFinding]) -> None:
        declared = {(item.id, item.version) for item in plan.required_agents}
        for reference in plan.required_agents:
            try:
                agent = self._workspace.get_agent(reference.id)
            except WorkspaceItemNotFoundError:
                findings.append(error("agent.missing", "required Agent does not exist", reference.id))
                continue
            if agent.get("version") != reference.version:
                findings.append(error("agent.version_mismatch", "Agent version differs", reference.id))
        for step in plan.steps:
            if step.required_agent is not None and (
                step.required_agent.id, step.required_agent.version
            ) not in declared:
                findings.append(
                    error(
                        "agent.undeclared",
                        "step Agent is not present in required_agents",
                        step.id,
                    )
                )

    @staticmethod
    def _artifacts(plan: ExecutionPlan, findings: list[ValidationFinding]) -> None:
        required = {item.id for item in plan.required_artifacts}
        produced = {item.id for item in plan.produced_artifacts}
        declared = required | produced
        producers: dict[str, list[str]] = {}
        for step in plan.steps:
            for artifact_id in step.required_artifacts:
                if artifact_id not in declared:
                    findings.append(
                        error("artifact.missing", "step input Artifact is undeclared", f"{step.id}:{artifact_id}")
                    )
            for artifact_id in step.produced_artifacts:
                if artifact_id not in produced:
                    findings.append(
                        error("artifact.undeclared_output", "step output Artifact is undeclared", f"{step.id}:{artifact_id}")
                    )
                producers.setdefault(artifact_id, []).append(step.id)
        for artifact_id in sorted(produced):
            count = len(producers.get(artifact_id, []))
            if count == 0:
                findings.append(error("artifact.no_producer", "produced Artifact has no producer", artifact_id))
            elif count > 1:
                findings.append(error("artifact.multiple_producers", "Artifact has multiple producers", artifact_id))

    @staticmethod
    def _dependencies(plan: ExecutionPlan, findings: list[ValidationFinding]) -> None:
        _, dependencies = artifact_graph(plan)
        cycle = cyclic_nodes(dependencies)
        if cycle:
            findings.append(
                error("dependency.circular", f"circular dependency: {', '.join(cycle)}", plan.workflow_id)
            )
            return
        positions = {step.id: index for index, step in enumerate(plan.steps)}
        for consumer in sorted(dependencies):
            for producer in sorted(dependencies[consumer]):
                if producer in positions and consumer in positions and positions[producer] >= positions[consumer]:
                    findings.append(
                        error(
                            "dependency.order_invalid",
                            f"producer {producer!r} must precede consumer {consumer!r}",
                            consumer,
                        )
                    )

    @staticmethod
    def _approvals(plan: ExecutionPlan, findings: list[ValidationFinding]) -> None:
        declared = {
            str(item["id"]): item
            for item in plan.approvals
            if isinstance(item.get("id"), str) and item.get("id")
        }
        approval_steps = [step for step in plan.steps if step.type == "approval"]
        for identifier, declaration in sorted(declared.items()):
            subject = declaration.get("subject_ref")
            matching = [
                step
                for step in approval_steps
                if subject in step.required_artifacts or step.id == f"approval.{identifier}"
            ]
            if declaration.get("required") and not matching:
                findings.append(
                    error("approval.checkpoint_missing", "required Approval has no checkpoint", identifier)
                )
        if plan.transition_request is not None:
            for reference in plan.transition_request.get("approval_refs", ()):
                if reference not in declared:
                    findings.append(
                        error(
                            "approval.reference_missing",
                            "transition references an undeclared Approval",
                            str(reference),
                        )
                    )
    @staticmethod
    def _evaluations(plan: ExecutionPlan, findings: list[ValidationFinding]) -> None:
        evaluation_steps = [step for step in plan.steps if step.type == "evaluation"]
        declared_artifacts = {
            item.id for item in plan.required_artifacts + plan.produced_artifacts
        }
        for declaration in plan.evaluations:
            identifier = declaration.get("id")
            subject = declaration.get("subject_artifact")
            if not isinstance(identifier, str) or not identifier:
                findings.append(error("evaluation.invalid", "Evaluation id is missing", plan.workflow_id))
                continue
            if subject not in declared_artifacts:
                findings.append(error("evaluation.subject_missing", "Evaluation subject is undeclared", identifier))
            matching = [
                step
                for step in evaluation_steps
                if subject in step.required_artifacts or step.id == f"evaluation.{identifier}"
            ]
            if declaration.get("required") and not matching:
                findings.append(
                    error("evaluation.checkpoint_missing", "required Evaluation has no checkpoint", identifier)
                )

