"""PR-010 deterministic Plan Validation and Authorization tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from founderos_runtime.authorization import AuthorizationEngine
from founderos_runtime.journey import JourneyRunner, JourneyStatus
from founderos_runtime.planner import Planner
from founderos_runtime.planner.execution_plan import (
    ArtifactReference,
    DefinitionReference,
    ExecutionPlan,
    ExecutionStep,
    thaw as plan_thaw,
)
from founderos_runtime.provider import MockProvider
from founderos_runtime.validation import PlanValidator
from founderos_runtime.workspace import Workspace


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "runtime" / "contracts"
WORKFLOW_ID = "wfl_01ARZ3NDEKTSV4RRFFQ69G5FAW"
PRODUCT_MANAGER_ID = "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"
MARKET_RESEARCH_ID = "agt_01ARZ3NDEKTSV4RRFFQ69G5FAX"


def read_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class StaticPlanner(Planner):
    def __init__(self, workspace: Workspace, plan: ExecutionPlan) -> None:
        super().__init__(workspace)
        self._static_plan = plan

    def plan(self, workflow_id: str) -> ExecutionPlan:
        return self._static_plan


class PlanValidationAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.workflow = read_yaml(
            CONTRACTS / "workflow" / "examples" / "discovery-workflow.yaml"
        )
        self.product_manager = read_yaml(
            CONTRACTS / "agent" / "examples" / "product-manager.yaml"
        )
        self.market_research = deepcopy(self.product_manager)
        self.market_research.update(
            {
                "id": MARKET_RESEARCH_ID,
                "name": "Market Research Agent",
                "role": "Market Research Agent",
            }
        )
        self.workspace = Workspace(
            self.root.resolve(),
            "0.1.0",
            {},
            {WORKFLOW_ID: self.workflow},
            {
                PRODUCT_MANAGER_ID: self.product_manager,
                MARKET_RESEARCH_ID: self.market_research,
            },
        )
        self.plan = Planner(self.workspace).plan(WORKFLOW_ID)
        self.validator = PlanValidator(self.workspace)
        self.engine = AuthorizationEngine()

    def metadata(self, **updates: object) -> dict[str, object]:
        value = plan_thaw(self.plan.metadata)
        value.update(updates)
        return value

    def test_valid_plan(self) -> None:
        report = self.validator.validate(self.plan)
        self.assertTrue(report.valid)
        self.assertEqual(report.errors, ())

    def test_missing_workflow(self) -> None:
        workspace = Workspace(self.root.resolve(), "0.1.0", {}, {}, {})
        report = PlanValidator(workspace).validate(self.plan)
        self.assertFalse(report.valid)
        self.assertIn("workflow.missing", {item.code for item in report.errors})

    def test_missing_agent(self) -> None:
        missing = DefinitionReference("agt_01ARZ3NDEKTSV4RRFFQ69G5FZZ", "1.0.0", "Missing")
        steps = tuple(
            replace(step, required_agent=missing)
            if step.id == "score_opportunities"
            else step
            for step in self.plan.steps
        )
        plan = replace(self.plan, required_agents=(missing,), steps=steps)
        report = self.validator.validate(plan)
        self.assertIn("agent.missing", {item.code for item in report.errors})

    def test_missing_artifact(self) -> None:
        plan = replace(self.plan, required_artifacts=())
        report = self.validator.validate(plan)
        self.assertIn("artifact.missing", {item.code for item in report.errors})

    def test_duplicate_ids(self) -> None:
        plan = replace(self.plan, steps=(self.plan.steps[0],) + self.plan.steps)
        report = self.validator.validate(plan)
        self.assertIn("id.duplicate", {item.code for item in report.errors})

    def test_circular_dependency(self) -> None:
        step_a = ExecutionStep("produce_a", "artifact_creation", "A", None, ("b",), ("a",), False, False)
        step_b = ExecutionStep("produce_b", "artifact_creation", "B", None, ("a",), ("b",), False, False)
        plan = replace(
            self.plan,
            steps=(step_a, step_b),
            required_agents=(),
            required_artifacts=(),
            produced_artifacts=(
                ArtifactReference("a", "a", "schemas/a.json"),
                ArtifactReference("b", "b", "schemas/b.json"),
            ),
            evaluations=(),
            approvals=(),
            transition_request=None,
        )
        report = self.validator.validate(plan)
        self.assertIn("dependency.circular", {item.code for item in report.errors})

    def test_invalid_execution_order(self) -> None:
        steps = list(self.plan.steps)
        producer = next(i for i, step in enumerate(steps) if step.id == "score_opportunities")
        consumer = next(i for i, step in enumerate(steps) if step.id == "evaluate_opportunity_report")
        steps[producer], steps[consumer] = steps[consumer], steps[producer]
        report = self.validator.validate(replace(self.plan, steps=tuple(steps)))
        self.assertIn("dependency.order_invalid", {item.code for item in report.errors})

    def test_safe_plan_allowed(self) -> None:
        safe = replace(
            self.plan,
            steps=tuple(
                step for step in self.plan.steps
                if step.type not in {"approval", "transition_request"}
            ),
            approvals=(),
            transition_request=None,
        )
        validation = self.validator.validate(safe)
        decision = self.engine.authorize(safe, validation)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.required_approvals, ())

    def test_unknown_capability_denied(self) -> None:
        plan = replace(self.plan, metadata=self.metadata(required_capabilities=["unknown.fly"]))
        decision = self.engine.authorize(plan, self.validator.validate(plan))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "UNKNOWN_CAPABILITY")

    def test_high_risk_requires_approval(self) -> None:
        decision = self.engine.authorize(self.plan, self.validator.validate(self.plan))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.required_approvals, ("opportunity_selection_approval",))
        self.assertEqual(
            next(x for x in decision.policy_results if x.policy == "require_approval_for_high_risk").outcome,
            "require",
        )

    def test_missing_validation_denied(self) -> None:
        decision = self.engine.authorize(self.plan, None)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "MISSING_OR_INVALID_VALIDATION")

    def test_deterministic_policy_decisions(self) -> None:
        validation = self.validator.validate(self.plan)
        self.assertEqual(
            self.engine.authorize(self.plan, validation),
            self.engine.authorize(self.plan, validation),
        )

    def test_validation_failure_stops_journey(self) -> None:
        invalid = replace(self.plan, steps=(self.plan.steps[0],) + self.plan.steps)
        provider = MockProvider()
        with patch.object(provider, "generate", wraps=provider.generate) as generate:
            result = JourneyRunner(
                self.workspace,
                provider=provider,
                planner=StaticPlanner(self.workspace, invalid),
            ).run(WORKFLOW_ID)
        self.assertEqual(result.status, JourneyStatus.FAILED)
        self.assertEqual(result.metadata["stopped_reason"], "plan_validation_failed")
        self.assertEqual(generate.call_count, 0)

    def test_authorization_denial_stops_journey(self) -> None:
        denied = replace(
            self.plan,
            metadata=self.metadata(required_capabilities=["unknown.fly"]),
        )
        provider = MockProvider()
        with patch.object(provider, "generate", wraps=provider.generate) as generate:
            result = JourneyRunner(
                self.workspace,
                provider=provider,
                planner=StaticPlanner(self.workspace, denied),
            ).run(WORKFLOW_ID)
        self.assertEqual(result.status, JourneyStatus.FAILED)
        self.assertEqual(result.metadata["stopped_reason"], "plan_authorization_denied")
        self.assertEqual(generate.call_count, 0)

    def test_successful_validation_continues(self) -> None:
        result = JourneyRunner(self.workspace).run(WORKFLOW_ID)
        self.assertEqual(result.status, JourneyStatus.SUCCEEDED)
        self.assertTrue(result.metadata["validation"]["valid"])
        self.assertTrue(result.metadata["authorization"]["allowed"])


if __name__ == "__main__":
    unittest.main()

