"""Deterministic in-memory execution of a Planner ExecutionPlan."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
import re
from typing import Any

from founderos_runtime.authorization import AuthorizationDecision, AuthorizationEngine
from founderos_runtime.evaluation import (
    EvaluationRequest,
    EvaluationResult,
    EvaluationRubric,
    EvaluationRule,
    EvaluationRunner,
    RuleType,
    Severity,
)
from founderos_runtime.planner import Planner, PlannerWorkflowNotFoundError
from founderos_runtime.planner.execution_plan import ExecutionPlan, ExecutionStep
from founderos_runtime.provider import MockProvider, ProviderRequest, ProviderStatus
from founderos_runtime.provider import thaw as provider_thaw
from founderos_runtime.validation import PlanValidator, ValidationReport
from founderos_runtime.workspace import Workspace

from .exceptions import JourneyEmptyPlanError, JourneyInvalidPlanError, JourneyWorkflowNotFoundError
from .journey_result import JourneyResult, JourneyStatus


JOURNEY_RUNNER_VERSION = "1.0.0"
_SKIPPED_TYPES = {"approval", "transition_request", "activity_request"}
_LOCAL_TYPES = {"human_input", "artifact_creation"}
RubricResolver = Callable[[Mapping[str, Any]], EvaluationRubric | None]
ArtifactBuilder = Callable[[ExecutionStep, Mapping[str, Any]], Mapping[str, Any]]


class JourneyRunner:
    """Execute one fixed plan in memory without persistence or Kernel mutation."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        provider: MockProvider | None = None,
        evaluation_runner: EvaluationRunner | None = None,
        planner: Planner | None = None,
        validator: PlanValidator | None = None,
        authorization_engine: AuthorizationEngine | None = None,
        rubric_resolver: RubricResolver | None = None,
        artifact_builders: Mapping[str, ArtifactBuilder] | None = None,
    ) -> None:
        if not isinstance(workspace, Workspace):
            raise TypeError("JourneyRunner requires a Workspace")
        self._workspace = workspace
        self._provider = provider or MockProvider()
        self._evaluation_runner = evaluation_runner or EvaluationRunner()
        self._planner = planner or Planner(workspace)
        self._validator = validator or PlanValidator(workspace)
        self._authorization_engine = authorization_engine or AuthorizationEngine()
        self._rubric_resolver = rubric_resolver
        self._artifact_builders = dict(artifact_builders or {})
        if not isinstance(self._provider, MockProvider):
            raise TypeError("JourneyRunner provider must be a MockProvider")
        if not isinstance(self._evaluation_runner, EvaluationRunner):
            raise TypeError("evaluation_runner must be an EvaluationRunner")
        if not isinstance(self._planner, Planner):
            raise TypeError("planner must be a Workspace Planner")
        if not isinstance(self._validator, PlanValidator):
            raise TypeError("validator must be a PlanValidator")
        if not isinstance(self._authorization_engine, AuthorizationEngine):
            raise TypeError("authorization_engine must be an AuthorizationEngine")
        if self._rubric_resolver is not None and not callable(self._rubric_resolver):
            raise TypeError("rubric_resolver must be callable")
        if any(
            not isinstance(step_id, str) or not step_id or not callable(builder)
            for step_id, builder in self._artifact_builders.items()
        ):
            raise TypeError("artifact_builders must map non-empty step ids to callables")

    def run(
        self,
        workflow_id: str,
        *,
        input_artifacts: Mapping[str, Any] | None = None,
    ) -> JourneyResult:
        try:
            plan = self._planner.plan(workflow_id)
        except PlannerWorkflowNotFoundError as error:
            raise JourneyWorkflowNotFoundError(str(error)) from error
        if not plan.steps:
            raise JourneyEmptyPlanError(f"workflow {workflow_id!r} produced an empty plan")

        validation = self._validator.validate(plan)
        if not validation.valid:
            return self._preflight_failure(plan, "plan_validation_failed", validation, None)
        authorization = self._authorization_engine.authorize(plan, validation)
        if not authorization.allowed:
            return self._preflight_failure(
                plan, "plan_authorization_denied", validation, authorization
            )
        preflight = {
            "validation": validation.to_dict(),
            "authorization": authorization.to_dict(),
        }

        completed: list[str] = []
        skipped: list[str] = []
        evaluations: list[EvaluationResult] = []
        supplied_artifacts = dict(input_artifacts or {})
        required_ids = {item.id for item in plan.required_artifacts}
        unknown_inputs = sorted(set(supplied_artifacts) - required_ids)
        if unknown_inputs:
            raise JourneyInvalidPlanError(
                f"input artifact {unknown_inputs[0]!r} is not required by the plan"
            )
        artifacts: dict[str, Any] = {
            item.id: {"artifact_id": item.id, "source": "required_input"}
            for item in plan.required_artifacts
        }
        artifacts.update(supplied_artifacts)
        generated: set[str] = set()
        log: list[dict[str, Any]] = []

        for position, step in enumerate(plan.steps):
            self._require_inputs(step, artifacts)
            if step.type == "agent_task":
                self._run_agent(plan, step, position, artifacts, generated, log)
                completed.append(step.id)
            elif step.type == "evaluation":
                result = self._run_evaluation(plan, step, position, artifacts, log)
                evaluations.append(result)
                completed.append(step.id)
                if self._critical_failure(result):
                    log.append({"index": len(log), "step_id": step.id, "event": "journey_stopped"})
                    return self._result(
                        plan, JourneyStatus.FAILED, completed, skipped, evaluations,
                        artifacts, generated, log, "critical_evaluation_failure", preflight,
                    )
            elif step.type in _SKIPPED_TYPES:
                skipped.append(step.id)
                log.append(
                    {
                        "index": len(log),
                        "step_id": step.id,
                        "event": "step_skipped",
                        "reason": f"{step.type}_execution_out_of_scope",
                    }
                )
            elif step.type in _LOCAL_TYPES:
                if step.type == "artifact_creation" and step.id in self._artifact_builders:
                    self._run_artifact_builder(step, artifacts, generated, log)
                else:
                    for artifact_id in step.produced_artifacts:
                        artifacts[artifact_id] = {
                            "artifact_id": artifact_id,
                            "source": step.type,
                            "step_id": step.id,
                        }
                        generated.add(artifact_id)
                    log.append(
                        {"index": len(log), "step_id": step.id, "event": "step_completed"}
                    )
                completed.append(step.id)
            else:
                raise JourneyInvalidPlanError(
                    f"step {step.id!r} has unsupported type {step.type!r}"
                )

        return self._result(
            plan, JourneyStatus.SUCCEEDED, completed, skipped, evaluations,
            artifacts, generated, log, None, preflight,
        )

    def _run_artifact_builder(
        self,
        step: ExecutionStep,
        artifacts: dict[str, Any],
        generated: set[str],
        log: list[dict[str, Any]],
    ) -> None:
        builder = self._artifact_builders[step.id]
        inputs = {
            artifact_id: deepcopy(artifacts[artifact_id])
            for artifact_id in step.required_artifacts
        }
        output = builder(step, inputs)
        if not isinstance(output, Mapping):
            raise JourneyInvalidPlanError(
                f"artifact builder for step {step.id!r} must return a mapping"
            )
        expected = set(step.produced_artifacts)
        actual = set(output)
        if actual != expected:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            detail = (
                f"missing output {missing[0]!r}" if missing
                else f"unexpected output {unexpected[0]!r}"
            )
            raise JourneyInvalidPlanError(
                f"artifact builder for step {step.id!r} returned {detail}"
            )
        for artifact_id in sorted(expected):
            artifacts[artifact_id] = deepcopy(output[artifact_id])
            generated.add(artifact_id)
        log.append(
            {
                "index": len(log),
                "step_id": step.id,
                "event": "artifact_created",
                "produced_artifacts": sorted(expected),
            }
        )

    def summary(self) -> dict[str, Any]:
        planner_summary = self._planner.summary()
        return {
            "journey_runner_version": JOURNEY_RUNNER_VERSION,
            "provider": {
                "name": self._provider.provider_name,
                "version": self._provider.provider_version,
            },
            "available_workflows": list(planner_summary["available_workflows"]),
            "deterministic": True,
            "in_memory_only": True,
            "workspace_read_only": True,
            "preflight_validation": True,
            "preflight_authorization": True,
        }

    def _run_agent(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
        position: int,
        artifacts: dict[str, Any],
        generated: set[str],
        log: list[dict[str, Any]],
    ) -> None:
        if step.required_agent is None:
            raise JourneyInvalidPlanError(f"agent task {step.id!r} has no required agent")
        request_id = f"journey.{plan.workflow_id}.{step.id}"
        request = ProviderRequest(
            request_id=request_id,
            operation="journey.agent_task",
            input={
                "workflow_id": plan.workflow_id,
                "step_id": step.id,
                "agent": {
                    "id": step.required_agent.id,
                    "version": step.required_agent.version,
                    "role": step.required_agent.role,
                },
                "artifacts": {key: artifacts[key] for key in step.required_artifacts},
            },
            metadata={"plan_step_index": position},
            correlation_id=f"journey.{plan.workflow_id}",
            idempotency_key=request_id,
        )
        response = self._provider.generate(request)
        if response.status is not ProviderStatus.SUCCESS:
            code = response.error.code if response.error is not None else "unknown"
            raise JourneyInvalidPlanError(f"provider failed for step {step.id!r}: {code}")
        output = provider_thaw(response.output)
        for artifact_id in step.produced_artifacts:
            artifacts[artifact_id] = output
            generated.add(artifact_id)
        log.append(
            {
                "index": len(log),
                "step_id": step.id,
                "event": "provider_completed",
                "request_id": request.request_id,
                "provider": response.provider_name,
                "produced_artifacts": list(step.produced_artifacts),
            }
        )

    def _run_evaluation(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
        position: int,
        artifacts: Mapping[str, Any],
        log: list[dict[str, Any]],
    ) -> EvaluationResult:
        subject_id = self._evaluation_subject(plan, step)
        declaration = self._evaluation_declaration(plan, step, subject_id)
        rubric = self._rubric_resolver(declaration) if self._rubric_resolver else None
        if rubric is not None:
            request = rubric.request(
                f"evaluation.{plan.workflow_id}.{step.id}",
                artifacts[subject_id],
                metadata={
                    "workflow_id": plan.workflow_id,
                    "step_id": step.id,
                    "subject_artifact": subject_id,
                    "plan_step_index": position,
                },
            )
            result = rubric.runner().run(request)
            log.append(
                {
                    "index": len(log),
                    "step_id": step.id,
                    "event": "evaluation_completed",
                    "request_id": request.request_id,
                    "passed": result.passed,
                    "score": result.score,
                    "rubric_id": rubric.id,
                    "rubric_version": rubric.version,
                }
            )
            return result
        rule_id = "journey." + re.sub(r"[^a-z0-9._-]", "_", step.id.lower())
        request = EvaluationRequest(
            request_id=f"evaluation.{plan.workflow_id}.{step.id}",
            artifact=artifacts[subject_id],
            rules=(
                EvaluationRule(
                    id=rule_id,
                    name="Required journey evaluation subject",
                    description="Required evaluation subjects must contain a generated value.",
                    severity=Severity.CRITICAL,
                    type=RuleType.SCHEMA,
                    parameters={"schema": {"not": {"type": "null"}}},
                ),
            ),
            metadata={
                "workflow_id": plan.workflow_id,
                "step_id": step.id,
                "subject_artifact": subject_id,
                "plan_step_index": position,
            },
        )
        result = self._evaluation_runner.run(request)
        log.append(
            {
                "index": len(log),
                "step_id": step.id,
                "event": "evaluation_completed",
                "request_id": request.request_id,
                "passed": result.passed,
                "score": result.score,
            }
        )
        return result

    @staticmethod
    def _evaluation_declaration(
        plan: ExecutionPlan,
        step: ExecutionStep,
        subject_id: str,
    ) -> Mapping[str, Any]:
        candidates = [
            declaration
            for declaration in plan.evaluations
            if declaration.get("subject_artifact") == subject_id
        ]
        if step.id.startswith("evaluation."):
            declaration_id = step.id.removeprefix("evaluation.")
            exact = [item for item in candidates if item.get("id") == declaration_id]
            if exact:
                return exact[0]
        if len(candidates) != 1:
            raise JourneyInvalidPlanError(
                f"evaluation step {step.id!r} does not resolve exactly one declaration"
            )
        return candidates[0]

    @staticmethod
    def _evaluation_subject(plan: ExecutionPlan, step: ExecutionStep) -> str:
        candidates = list(step.required_artifacts)
        if step.id.startswith("evaluation."):
            declaration_id = step.id.removeprefix("evaluation.")
            for declaration in plan.evaluations:
                if declaration.get("id") == declaration_id:
                    candidates.insert(0, declaration["subject_artifact"])
        if not candidates:
            raise JourneyInvalidPlanError(f"evaluation step {step.id!r} has no subject artifact")
        return candidates[0]

    @staticmethod
    def _require_inputs(step: ExecutionStep, artifacts: Mapping[str, Any]) -> None:
        missing = sorted(set(step.required_artifacts) - set(artifacts))
        if missing:
            raise JourneyInvalidPlanError(
                f"step {step.id!r} requires unavailable artifact {missing[0]!r}"
            )

    @staticmethod
    def _critical_failure(result: EvaluationResult) -> bool:
        return any(
            not finding.passed and finding.severity is Severity.CRITICAL
            for finding in result.findings
        )

    @staticmethod
    def _result(
        plan: ExecutionPlan,
        status: JourneyStatus,
        completed: list[str],
        skipped: list[str],
        evaluations: list[EvaluationResult],
        artifacts: Mapping[str, Any],
        generated: set[str],
        log: list[Mapping[str, Any]],
        stopped_reason: str | None,
        preflight: Mapping[str, Any],
    ) -> JourneyResult:
        return JourneyResult(
            workflow_id=plan.workflow_id,
            status=status,
            completed_steps=tuple(completed),
            skipped_steps=tuple(skipped),
            evaluation_results=tuple(evaluations),
            generated_artifacts={key: artifacts[key] for key in sorted(generated)},
            execution_log=tuple(log),
            metadata={
                "journey_runner_version": JOURNEY_RUNNER_VERSION,
                "planner_version": plan.metadata["planner_version"],
                "workflow_version": plan.metadata["workflow_version"],
                "stopped_reason": stopped_reason,
                "persistence": False,
                "state_mutation": False,
                **preflight,
            },
        )

    @staticmethod
    def _preflight_failure(
        plan: ExecutionPlan,
        stopped_reason: str,
        validation: ValidationReport,
        authorization: AuthorizationDecision | None,
    ) -> JourneyResult:
        event = "validation_failed" if authorization is None else "authorization_denied"
        return JourneyResult(
            workflow_id=plan.workflow_id,
            status=JourneyStatus.FAILED,
            completed_steps=(),
            skipped_steps=tuple(step.id for step in plan.steps),
            evaluation_results=(),
            generated_artifacts={},
            execution_log=(
                {"index": 0, "step_id": None, "event": event, "reason": stopped_reason},
            ),
            metadata={
                "journey_runner_version": JOURNEY_RUNNER_VERSION,
                "planner_version": plan.metadata["planner_version"],
                "workflow_version": plan.metadata["workflow_version"],
                "stopped_reason": stopped_reason,
                "persistence": False,
                "state_mutation": False,
                "validation": validation.to_dict(),
                "authorization": authorization.to_dict() if authorization is not None else None,
            },
        )
