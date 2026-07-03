"""End-to-end deterministic Discovery vertical-slice acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
import urllib.request

from founderos_runtime.authorization import AuthorizationEngine
from founderos_runtime.demo import (
    DISCOVERY_WORKFLOW_ID,
    discovery_example_root,
    load_discovery_workspace,
    run_discovery_vertical_slice,
)
from founderos_runtime.evaluation import load_evaluation_rubric
from founderos_runtime.journey import JourneyStatus, thaw
from founderos_runtime.planner import Planner
from founderos_runtime.validation import PlanValidator

from tests.helpers import RuntimeFixture


class DiscoveryVerticalSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = discovery_example_root()

    def read_json(self, relative: str) -> object:
        with (self.root / relative).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_discovery_fixture_workspace_loads(self) -> None:
        workspace = load_discovery_workspace()
        summary = workspace.summary()
        self.assertEqual(summary["counts"], {"apps": 1, "workflows": 1, "agents": 2})
        self.assertEqual(summary["workflows"], [DISCOVERY_WORKFLOW_ID])

    def test_planner_creates_valid_execution_plan(self) -> None:
        workspace = load_discovery_workspace()
        plan = Planner(workspace).plan(DISCOVERY_WORKFLOW_ID)
        self.assertEqual(plan.workflow_id, DISCOVERY_WORKFLOW_ID)
        self.assertEqual([item.id for item in plan.produced_artifacts], ["opportunity_report"])
        self.assertEqual(plan.metadata["source"], "workspace")

    def test_plan_validation_passes(self) -> None:
        workspace = load_discovery_workspace()
        plan = Planner(workspace).plan(DISCOVERY_WORKFLOW_ID)
        report = PlanValidator(workspace).validate(plan)
        self.assertTrue(report.valid)
        self.assertEqual(report.errors, ())

    def test_authorization_allows_plan(self) -> None:
        workspace = load_discovery_workspace()
        plan = Planner(workspace).plan(DISCOVERY_WORKFLOW_ID)
        validation = PlanValidator(workspace).validate(plan)
        decision = AuthorizationEngine().authorize(plan, validation)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.required_approvals, ("opportunity_selection_approval",))

    def test_journey_runner_completes(self) -> None:
        result = run_discovery_vertical_slice()
        self.assertEqual(result.status, JourneyStatus.SUCCEEDED)
        self.assertIn("score_opportunities", result.completed_steps)
        self.assertIn("approve_opportunity", result.skipped_steps)

    def test_mock_provider_produces_expected_opportunity_report(self) -> None:
        result = run_discovery_vertical_slice()
        actual = thaw(result.generated_artifacts["opportunity_report"])
        expected = self.read_json("expected/opportunity-report.json")
        self.assertEqual(actual, expected)
        self.assertEqual(actual["source"], "founderos.mock.fixture")

    def test_evaluation_rubric_passes_valid_output(self) -> None:
        result = run_discovery_vertical_slice()
        evaluation = result.evaluation_results[0]
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.score, 1.0)
        self.assertEqual(
            evaluation.metadata["request_metadata"]["rubric_id"],
            "rub_01ARZ3NDEKTSV4RRFFQ69G5FAY",
        )
        rubric = load_evaluation_rubric(
            self.root / "rubrics" / "opportunity-report-rubric.yaml"
        )
        self.assertEqual(len(evaluation.findings), len(rubric.rules) + 1)

    def test_journey_result_includes_generated_artifacts(self) -> None:
        result = run_discovery_vertical_slice()
        self.assertEqual(tuple(result.generated_artifacts), ("opportunity_report",))
        self.assertEqual(
            result.execution_log[0]["event"],
            "provider_completed",
        )

    def test_journey_result_includes_evaluation_results(self) -> None:
        result = run_discovery_vertical_slice()
        self.assertEqual(len(result.evaluation_results), 1)
        self.assertEqual(
            result.execution_log[1]["rubric_id"],
            "rub_01ARZ3NDEKTSV4RRFFQ69G5FAY",
        )

    def test_running_twice_is_deterministic(self) -> None:
        first = run_discovery_vertical_slice()
        second = run_discovery_vertical_slice()
        self.assertEqual(first, second)

    def test_no_real_provider_or_network_access(self) -> None:
        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("network used")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")),
        ):
            result = run_discovery_vertical_slice()
        self.assertEqual(result.status, JourneyStatus.SUCCEEDED)

    def test_no_persistence_or_runtime_state_mutation(self) -> None:
        runtime = RuntimeFixture()
        repository_before = runtime.repositories.export_records()
        files_before = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }
        result = run_discovery_vertical_slice()
        files_after = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(result.status, JourneyStatus.SUCCEEDED)
        self.assertEqual(repository_before, runtime.repositories.export_records())
        self.assertEqual(files_before, files_after)


if __name__ == "__main__":
    unittest.main()

