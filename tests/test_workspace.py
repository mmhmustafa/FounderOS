"""Read-only Workspace discovery, relationship, compatibility, and query tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from founderos_runtime.workspace import (
    Workspace,
    WorkspaceCompatibilityError,
    WorkspaceDependencyCycleError,
    WorkspaceDuplicateIdError,
    WorkspaceItemNotFoundError,
    WorkspaceMissingReferenceError,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "runtime" / "contracts"
AGENT_EXAMPLE = CONTRACTS / "agent" / "examples" / "product-manager.yaml"
WORKFLOW_EXAMPLE = CONTRACTS / "workflow" / "examples" / "discovery-workflow.yaml"
APP_EXAMPLE = CONTRACTS / "app" / "examples" / "discovery-app.yaml"


def read_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def write(self, relative_path: str, data: object) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def valid_manifests(self) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
        workflow = read_yaml(WORKFLOW_EXAMPLE)
        app = read_yaml(APP_EXAMPLE)
        product_manager = read_yaml(AGENT_EXAMPLE)
        market_research = deepcopy(product_manager)
        market_research["id"] = "agt_01ARZ3NDEKTSV4RRFFQ69G5FAX"
        market_research["name"] = "Market Research Agent"
        market_research["role"] = "Market Research Agent"
        return app, workflow, [product_manager, market_research]

    def create_valid_workspace(self) -> None:
        app, workflow, agents = self.valid_manifests()
        self.write("apps/discovery-app.yaml", app)
        self.write("workflows/discovery-workflow.yaml", workflow)
        self.write("agents/product-manager.yaml", agents[0])
        self.write("agents/market-research.yaml", agents[1])

    def test_empty_workspace(self) -> None:
        workspace = Workspace.load(self.root)
        self.assertEqual(workspace.apps(), ())
        self.assertEqual(workspace.workflows(), ())
        self.assertEqual(workspace.agents(), ())
        self.assertEqual(
            workspace.summary()["counts"],
            {"apps": 0, "workflows": 0, "agents": 0},
        )

    def test_single_app_loads_complete_relationship_graph(self) -> None:
        self.create_valid_workspace()
        workspace = Workspace.load(self.root)
        self.assertEqual(len(workspace.apps()), 1)
        self.assertEqual(len(workspace.workflows()), 1)
        self.assertEqual(len(workspace.agents()), 2)
        self.assertEqual(workspace.apps()[0]["id"], "founderos.discovery")

    def test_multiple_apps_are_ordered_deterministically(self) -> None:
        self.create_valid_workspace()
        second = read_yaml(APP_EXAMPLE)
        second["id"] = "founderos.architecture-review"
        second["name"] = "Architecture Review"
        self.write("apps/architecture-review.yaml", second)
        workspace = Workspace.load(self.root)
        self.assertEqual(
            [app["id"] for app in workspace.apps()],
            ["founderos.architecture-review", "founderos.discovery"],
        )

    def test_duplicate_agent_workflow_and_app_ids_are_rejected(self) -> None:
        cases = (
            ("agent", "agents/product-manager-copy.yaml", AGENT_EXAMPLE),
            ("workflow", "workflows/discovery-copy.yaml", WORKFLOW_EXAMPLE),
            ("app", "apps/discovery-copy.yaml", APP_EXAMPLE),
        )
        for kind, duplicate_path, source in cases:
            with self.subTest(kind=kind):
                with TemporaryDirectory() as directory:
                    original_root = self.root
                    self.root = Path(directory)
                    try:
                        self.create_valid_workspace()
                        self.write(duplicate_path, read_yaml(source))
                        with self.assertRaises(WorkspaceDuplicateIdError) as raised:
                            Workspace.load(self.root)
                        self.assertEqual(raised.exception.kind, kind)
                    finally:
                        self.root = original_root

    def test_missing_workflow_reference_is_rejected(self) -> None:
        app, _, agents = self.valid_manifests()
        self.write("apps/discovery-app.yaml", app)
        self.write("agents/product-manager.yaml", agents[0])
        self.write("agents/market-research.yaml", agents[1])
        with self.assertRaises(WorkspaceMissingReferenceError) as raised:
            Workspace.load(self.root)
        self.assertIn("missing workflow", str(raised.exception))

    def test_missing_agent_reference_is_rejected(self) -> None:
        app, workflow, agents = self.valid_manifests()
        self.write("apps/discovery-app.yaml", app)
        self.write("workflows/discovery-workflow.yaml", workflow)
        self.write("agents/product-manager.yaml", agents[0])
        with self.assertRaises(WorkspaceMissingReferenceError) as raised:
            Workspace.load(self.root)
        self.assertIn("missing agent", str(raised.exception))

    def test_incompatible_runtime_is_rejected(self) -> None:
        self.create_valid_workspace()
        with self.assertRaises(WorkspaceCompatibilityError) as raised:
            Workspace.load(self.root, runtime_version="1.0.0")
        self.assertIn("founderos.discovery", str(raised.exception))
        self.assertIn(">=0.1.0 <1.0.0", str(raised.exception))

    def test_queries_are_successful_and_defensive(self) -> None:
        self.create_valid_workspace()
        workspace = Workspace.load(self.root)
        app = workspace.get_app("founderos.discovery")
        workflow_id = "wfl_01ARZ3NDEKTSV4RRFFQ69G5FAW"
        agent_id = "agt_01ARZ3NDEKTSV4RRFFQ69G5FAV"
        self.assertEqual(workspace.get_workflow(workflow_id)["name"], "Discovery Workflow")
        self.assertEqual(workspace.get_agent(agent_id)["name"], "Product Manager")
        app["name"] = "Caller mutation"
        self.assertEqual(workspace.get_app("founderos.discovery")["name"], "FounderOS Discovery")
        with self.assertRaises(WorkspaceItemNotFoundError):
            workspace.get_app("founderos.missing")

    def test_summary_generation_is_deterministic(self) -> None:
        self.create_valid_workspace()
        workspace = Workspace.load(self.root)
        first = workspace.summary()
        second = workspace.summary()
        self.assertEqual(first, second)
        self.assertEqual(first["runtime_version"], "0.1.0")
        self.assertEqual(first["counts"], {"apps": 1, "workflows": 1, "agents": 2})
        self.assertEqual(first["apps"], ["founderos.discovery"])

    def test_circular_app_dependencies_are_rejected(self) -> None:
        self.create_valid_workspace()
        first = read_yaml(APP_EXAMPLE)
        second = deepcopy(first)
        second["id"] = "founderos.validation"
        second["name"] = "FounderOS Validation"
        first["dependencies"] = [
            {"id": "founderos.validation", "version_range": ">=1.0.0 <2.0.0", "optional": False}
        ]
        second["dependencies"] = [
            {"id": "founderos.discovery", "version_range": ">=1.0.0 <2.0.0", "optional": False}
        ]
        self.write("apps/discovery-app.yaml", first)
        self.write("apps/validation-app.yaml", second)
        with self.assertRaises(WorkspaceDependencyCycleError) as raised:
            Workspace.load(self.root)
        self.assertEqual(
            str(raised.exception),
            "circular app dependency: founderos.discovery -> founderos.validation -> founderos.discovery",
        )


if __name__ == "__main__":
    unittest.main()
