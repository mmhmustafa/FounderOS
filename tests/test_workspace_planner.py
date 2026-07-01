"""Workspace Planner plan construction, checkpoints, dependencies, and errors."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from founderos_runtime.planner import (
    Planner,
    PlannerAgentNotFoundError,
    PlannerArtifactReferenceError,
    PlannerCircularDependencyError,
    PlannerInvalidWorkflowError,
    PlannerWorkflowNotFoundError,
)
from founderos_runtime.workspace import Workspace


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "runtime" / "contracts"
AGENT_EXAMPLE = CONTRACTS / "agent" / "examples" / "product-manager.yaml"
WORKFLOW_EXAMPLE = CONTRACTS / "workflow" / "examples" / "discovery-workflow.yaml"
APP_EXAMPLE = CONTRACTS / "app" / "examples" / "discovery-app.yaml"
WORKFLOW_ID = "wfl_01ARZ3NDEKTSV4RRFFQ69G5FAW"
PRODUCT_MANAGER_ID = "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"
MARKET_RESEARCH_ID = "agt_01ARZ3NDEKTSV4RRFFQ69G5FAX"


def read_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class WorkspacePlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.workflow = read_yaml(WORKFLOW_EXAMPLE)
        self.product_manager = read_yaml(AGENT_EXAMPLE)
        self.market_research = deepcopy(self.product_manager)
        self.market_research["id"] = MARKET_RESEARCH_ID
        self.market_research["name"] = "Market Research Agent"
        self.market_research["role"] = "Market Research Agent"

    def write(self, relative: str, value: object) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

    def valid_workspace(self) -> Workspace:
        self.write("apps/discovery-app.yaml", read_yaml(APP_EXAMPLE))
        self.write("workflows/discovery-workflow.yaml", self.workflow)
        self.write("agents/product-manager.yaml", self.product_manager)
        self.write("agents/market-research.yaml", self.market_research)
        return Workspace.load(self.root)

    def direct_workspace(
        self,
        workflow: dict[str, object],
        *,
        agents: dict[str, dict[str, object]] | None = None,
    ) -> Workspace:
        return Workspace(
            self.root.resolve(),
            "0.1.0",
            {},
            {workflow["id"]: workflow},
            agents
            if agents is not None
            else {
                PRODUCT_MANAGER_ID: self.product_manager,
                MARKET_RESEARCH_ID: self.market_research,
            },
        )

    def test_successful_plan_generation(self) -> None:
        plan = Planner(self.valid_workspace()).plan(WORKFLOW_ID)
        self.assertEqual(plan.workflow_id, WORKFLOW_ID)
        self.assertEqual(
            [agent.id for agent in plan.required_agents],
            [PRODUCT_MANAGER_ID, MARKET_RESEARCH_ID],
        )
        self.assertEqual([item.id for item in plan.required_artifacts], ["founder_brief"])
        self.assertEqual([item.id for item in plan.produced_artifacts], ["opportunity_report"])
        self.assertEqual(plan.transition_request["to_state"], "OPPORTUNITY_SELECTED")
        step_ids = [step.id for step in plan.steps]
        self.assertLess(step_ids.index("evaluate_opportunity_report"), step_ids.index("approve_opportunity"))
        self.assertLess(step_ids.index("approve_opportunity"), step_ids.index("request_opportunity_selected"))

    def test_missing_workflow(self) -> None:
        with self.assertRaises(PlannerWorkflowNotFoundError) as raised:
            Planner(self.valid_workspace()).plan("wfl_01ARZ3NDEKTSV4RRFFQ69G5FZZ")
        self.assertIn("workflow id not found", str(raised.exception))

    def test_missing_required_agent(self) -> None:
        workspace = self.direct_workspace(
            self.workflow,
            agents={PRODUCT_MANAGER_ID: self.product_manager},
        )
        with self.assertRaises(PlannerAgentNotFoundError) as raised:
            Planner(workspace).plan(WORKFLOW_ID)
        self.assertIn(MARKET_RESEARCH_ID, str(raised.exception))

    def test_missing_artifact_reference(self) -> None:
        workflow = deepcopy(self.workflow)
        workflow["steps"][0]["input_artifacts"] = ["unavailable_input"]
        with self.assertRaises(PlannerArtifactReferenceError) as raised:
            Planner(self.direct_workspace(workflow)).plan(WORKFLOW_ID)
        self.assertIn("unavailable_input", str(raised.exception))

    def test_circular_dependency_detection(self) -> None:
        workflow = deepcopy(self.workflow)
        workflow.update(
            {
                "workflow_type": "utility",
                "required_agents": [],
                "required_artifacts": [],
                "produced_artifacts": [
                    {"id": "artifact_a", "artifact_type": "artifact_a", "schema_ref": "schemas/a.json"},
                    {"id": "artifact_b", "artifact_type": "artifact_b", "schema_ref": "schemas/b.json"},
                ],
                "evaluations": [],
                "approvals": [],
                "transition_intent": None,
                "steps": [
                    {
                        "id": "produce_a",
                        "name": "Produce A",
                        "type": "artifact_creation",
                        "required_agent": None,
                        "input_artifacts": ["artifact_b"],
                        "output_artifacts": ["artifact_a"],
                        "requires_approval": False,
                    },
                    {
                        "id": "produce_b",
                        "name": "Produce B",
                        "type": "artifact_creation",
                        "required_agent": None,
                        "input_artifacts": ["artifact_a"],
                        "output_artifacts": ["artifact_b"],
                        "requires_approval": False,
                    },
                ],
            }
        )
        with self.assertRaises(PlannerCircularDependencyError) as raised:
            Planner(self.direct_workspace(workflow, agents={})).plan(WORKFLOW_ID)
        self.assertIn("produce_a", str(raised.exception))
        self.assertIn("produce_b", str(raised.exception))

    def test_evaluation_checkpoint_insertion(self) -> None:
        workflow = deepcopy(self.workflow)
        workflow["steps"] = [step for step in workflow["steps"] if step["type"] != "evaluation"]
        plan = Planner(self.direct_workspace(workflow)).plan(WORKFLOW_ID)
        checkpoint = next(step for step in plan.steps if step.id == "evaluation.opportunity_quality")
        self.assertEqual(checkpoint.type, "evaluation")
        self.assertTrue(checkpoint.requires_evaluation)

    def test_approval_checkpoint_insertion(self) -> None:
        workflow = deepcopy(self.workflow)
        workflow["steps"] = [step for step in workflow["steps"] if step["type"] != "approval"]
        plan = Planner(self.direct_workspace(workflow)).plan(WORKFLOW_ID)
        checkpoint = next(
            step for step in plan.steps if step.id == "approval.opportunity_selection_approval"
        )
        self.assertEqual(checkpoint.type, "approval")
        self.assertTrue(checkpoint.requires_approval)

    def test_execution_plan_is_deterministic_and_read_only(self) -> None:
        workspace = self.valid_workspace()
        planner = Planner(workspace)
        before = workspace.get_workflow(WORKFLOW_ID)
        first = planner.plan(WORKFLOW_ID)
        second = planner.plan(WORKFLOW_ID)
        self.assertEqual(first, second)
        self.assertEqual(before, workspace.get_workflow(WORKFLOW_ID))
        with self.assertRaises(TypeError):
            first.metadata["planner_version"] = "changed"  # type: ignore[index]

    def test_summary_generation(self) -> None:
        summary = Planner(self.valid_workspace()).summary()
        self.assertEqual(summary["planner_version"], "1.0.0")
        self.assertEqual(summary["workflow_count"], 1)
        self.assertEqual(summary["available_workflows"], [WORKFLOW_ID])
        self.assertTrue(summary["read_only"])

    def test_invalid_workflow_definition(self) -> None:
        workflow = deepcopy(self.workflow)
        workflow["steps"][1]["id"] = workflow["steps"][0]["id"]
        with self.assertRaises(PlannerInvalidWorkflowError) as raised:
            Planner(self.direct_workspace(workflow)).plan(WORKFLOW_ID)
        self.assertIn("duplicate step ids", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
