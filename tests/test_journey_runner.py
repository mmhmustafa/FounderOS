"""Deterministic in-memory Journey Runner orchestration tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from founderos_runtime.journey import (
    JourneyEmptyPlanError,
    JourneyRunner,
    JourneyStatus,
    JourneyWorkflowNotFoundError,
    thaw,
)
from founderos_runtime.provider import MockProvider, ProviderResponse
from founderos_runtime.provider import thaw as provider_thaw
from founderos_runtime.workspace import Workspace


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "runtime" / "contracts"
WORKFLOW_ID = "wfl_01ARZ3NDEKTSV4RRFFQ69G5FAW"
PRODUCT_MANAGER_ID = "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"
MARKET_RESEARCH_ID = "agt_01ARZ3NDEKTSV4RRFFQ69G5FAX"


def read_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class NullOutputMockProvider(MockProvider):
    """Test-only Mock Provider variant preserving all local Provider metadata."""

    def generate(self, request):  # type: ignore[no-untyped-def]
        response = super().generate(request)
        return ProviderResponse(
            request_id=response.request_id,
            status=response.status,
            output=None,
            error=response.error,
            metadata=provider_thaw(response.metadata),
            provider_name=response.provider_name,
            provider_version=response.provider_version,
        )


class JourneyRunnerTests(unittest.TestCase):
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

    def workspace(self, workflow: dict[str, object] | None = None) -> Workspace:
        selected = workflow if workflow is not None else self.workflow
        return Workspace(
            self.root.resolve(),
            "0.1.0",
            {},
            {selected["id"]: selected},
            {
                PRODUCT_MANAGER_ID: self.product_manager,
                MARKET_RESEARCH_ID: self.market_research,
            },
        )

    def test_successful_discovery_journey(self) -> None:
        result = JourneyRunner(self.workspace()).run(WORKFLOW_ID)
        self.assertEqual(result.status, JourneyStatus.SUCCEEDED)
        self.assertIn("score_opportunities", result.completed_steps)
        self.assertIn("evaluate_opportunity_report", result.completed_steps)
        self.assertIn("approve_opportunity", result.skipped_steps)
        self.assertIn("request_opportunity_selected", result.skipped_steps)
        self.assertIsNone(result.metadata["stopped_reason"])

    def test_provider_invocation(self) -> None:
        provider = MockProvider()
        with patch.object(provider, "generate", wraps=provider.generate) as generate:
            JourneyRunner(self.workspace(), provider=provider).run(WORKFLOW_ID)
        self.assertEqual(generate.call_count, 1)
        request = generate.call_args.args[0]
        self.assertEqual(request.operation, "journey.agent_task")
        self.assertEqual(request.input["step_id"], "score_opportunities")

    def test_evaluation_success(self) -> None:
        result = JourneyRunner(self.workspace()).run(WORKFLOW_ID)
        self.assertEqual(len(result.evaluation_results), 1)
        self.assertTrue(result.evaluation_results[0].passed)
        self.assertTrue(all(finding.passed for finding in result.evaluation_results[0].findings))

    def test_critical_evaluation_failure_stops_execution(self) -> None:
        result = JourneyRunner(
            self.workspace(), provider=NullOutputMockProvider()
        ).run(WORKFLOW_ID)
        self.assertEqual(result.status, JourneyStatus.FAILED)
        self.assertEqual(result.metadata["stopped_reason"], "critical_evaluation_failure")
        self.assertNotIn("approve_opportunity", result.skipped_steps)
        self.assertTrue(
            any(
                not finding.passed and finding.severity.value == "critical"
                for finding in result.evaluation_results[0].findings
            )
        )

    def test_unknown_workflow(self) -> None:
        with self.assertRaises(JourneyWorkflowNotFoundError):
            JourneyRunner(self.workspace()).run("wfl_01ARZ3NDEKTSV4RRFFQ69G5FZZ")

    def test_empty_plan(self) -> None:
        workflow = deepcopy(self.workflow)
        workflow.update(
            {
                "workflow_type": "utility",
                "required_agents": [],
                "required_artifacts": [],
                "produced_artifacts": [],
                "steps": [],
                "evaluations": [],
                "approvals": [],
                "transition_intent": None,
            }
        )
        with self.assertRaises(JourneyEmptyPlanError):
            JourneyRunner(self.workspace(workflow)).run(WORKFLOW_ID)

    def test_deterministic_execution_and_workspace_non_mutation(self) -> None:
        workspace = self.workspace()
        before = workspace.get_workflow(WORKFLOW_ID)
        runner = JourneyRunner(workspace)
        first = runner.run(WORKFLOW_ID)
        second = runner.run(WORKFLOW_ID)
        self.assertEqual(first, second)
        self.assertEqual(before, workspace.get_workflow(WORKFLOW_ID))

    def test_summary_generation(self) -> None:
        summary = JourneyRunner(self.workspace()).summary()
        self.assertEqual(summary["journey_runner_version"], "1.0.0")
        self.assertEqual(summary["provider"]["name"], "founderos.mock")
        self.assertEqual(summary["available_workflows"], [WORKFLOW_ID])
        self.assertTrue(summary["in_memory_only"])

    def test_multiple_agent_steps(self) -> None:
        workflow = deepcopy(self.workflow)
        workflow["produced_artifacts"].append(
            {
                "id": "opportunity_summary",
                "artifact_type": "opportunity_summary",
                "schema_ref": "schemas/opportunity-summary.schema.json",
            }
        )
        workflow["steps"].insert(
            2,
            {
                "id": "summarize_opportunity",
                "name": "Summarize Opportunity",
                "type": "agent_task",
                "required_agent": {
                    "id": PRODUCT_MANAGER_ID,
                    "version": "1.0.0",
                    "role": "Product Manager",
                },
                "input_artifacts": ["opportunity_report"],
                "output_artifacts": ["opportunity_summary"],
                "activity_type": None,
                "requires_approval": False,
                "on_success": "continue",
                "on_failure": "fail",
            },
        )
        provider = MockProvider()
        with patch.object(provider, "generate", wraps=provider.generate) as generate:
            result = JourneyRunner(self.workspace(workflow), provider=provider).run(WORKFLOW_ID)
        self.assertEqual(generate.call_count, 2)
        self.assertIn("summarize_opportunity", result.completed_steps)
        self.assertIn("opportunity_summary", result.generated_artifacts)

    def test_generated_artifacts_are_available_and_immutable(self) -> None:
        result = JourneyRunner(self.workspace()).run(WORKFLOW_ID)
        self.assertIn("opportunity_report", result.generated_artifacts)
        artifact = thaw(result.generated_artifacts["opportunity_report"])
        self.assertEqual(artifact["operation"], "journey.agent_task")
        with self.assertRaises(TypeError):
            result.generated_artifacts["new"] = {}  # type: ignore[index]
        self.assertEqual(
            result.to_dict()["generated_artifacts"]["opportunity_report"], artifact
        )


if __name__ == "__main__":
    unittest.main()

