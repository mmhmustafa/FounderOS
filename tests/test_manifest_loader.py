"""Manifest Loader API, failure, determinism, and regression tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from founderos_runtime.manifest_loader import (
    ManifestFileNotFoundError,
    ManifestLoader,
    ManifestSchemaError,
    ManifestValidationError,
    ManifestYamlError,
    load_agent_manifest,
    load_app_manifest,
    load_workflow_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "runtime" / "contracts"
AGENT = CONTRACTS / "agent" / "examples" / "product-manager.yaml"
WORKFLOW = CONTRACTS / "workflow" / "examples" / "discovery-workflow.yaml"
APP = CONTRACTS / "app" / "examples" / "discovery-app.yaml"


def read_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class ManifestLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.temp = Path(self.temporary_directory.name)

    def write_manifest(self, name: str, data: object) -> Path:
        path = self.temp / name
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def test_valid_agent_workflow_and_app_manifests_load(self) -> None:
        cases = (
            (load_agent_manifest, AGENT, "Product Manager"),
            (load_workflow_manifest, WORKFLOW, "Discovery Workflow"),
            (load_app_manifest, APP, "FounderOS Discovery"),
        )
        for load, path, name in cases:
            with self.subTest(path=path.name):
                self.assertEqual(load(path)["name"], name)

    def test_missing_manifest_raises_contextual_error(self) -> None:
        path = self.temp / "missing.yaml"
        with self.assertRaises(ManifestFileNotFoundError) as raised:
            load_agent_manifest(path)
        self.assertEqual(raised.exception.file, str(path))
        self.assertEqual(raised.exception.field, "<root>")
        self.assertEqual(raised.exception.reason, "manifest file was not found")

    def test_malformed_yaml_reports_stable_location(self) -> None:
        path = self.temp / "malformed.yaml"
        path.write_text("id: [unterminated\n", encoding="utf-8")
        with self.assertRaises(ManifestYamlError) as raised:
            load_agent_manifest(path)
        self.assertEqual(raised.exception.file, str(path))
        self.assertEqual(raised.exception.field, "<root>")
        self.assertIn("line 2, column 1", raised.exception.reason)

    def test_invalid_utf8_is_reported_as_typed_yaml_error(self) -> None:
        path = self.temp / "invalid-encoding.yaml"
        path.write_bytes(b"name: \xff")
        with self.assertRaises(ManifestYamlError) as raised:
            load_agent_manifest(path)
        self.assertEqual(raised.exception.file, str(path))
        self.assertEqual(raised.exception.reason, "file is not valid UTF-8")

    def test_invalid_schema_raises_schema_error(self) -> None:
        schema_path = self.temp / "agent" / "agent.schema.yaml"
        schema_path.parent.mkdir(parents=True)
        schema_path.write_text("$schema: https://json-schema.org/draft/2020-12/schema\ntype: impossible\n", encoding="utf-8")
        loader = ManifestLoader(contract_directory=self.temp)
        with self.assertRaises(ManifestSchemaError) as raised:
            loader.load_agent_manifest(AGENT)
        self.assertEqual(raised.exception.file, str(schema_path))
        self.assertTrue(raised.exception.field.startswith("type"))
        self.assertIn("not valid", raised.exception.reason)

    def test_schema_validation_failure_identifies_field_and_reason(self) -> None:
        manifest = read_yaml(AGENT)
        manifest["version"] = "latest"
        path = self.write_manifest("invalid-agent.yaml", manifest)
        with self.assertRaises(ManifestValidationError) as raised:
            load_agent_manifest(path)
        self.assertEqual(raised.exception.file, str(path))
        self.assertEqual(raised.exception.field, "version")
        self.assertIn("does not match", raised.exception.reason)

    def test_unknown_field_is_rejected_with_exact_field(self) -> None:
        manifest = read_yaml(APP)
        manifest["execute"] = True
        path = self.write_manifest("unknown-field.yaml", manifest)
        with self.assertRaises(ManifestValidationError) as raised:
            load_app_manifest(path)
        self.assertEqual(raised.exception.field, "execute")
        self.assertEqual(raised.exception.reason, "unknown field is not allowed")

    def test_missing_required_field_is_rejected_with_exact_field(self) -> None:
        manifest = read_yaml(WORKFLOW)
        del manifest["steps"]
        path = self.write_manifest("missing-field.yaml", manifest)
        with self.assertRaises(ManifestValidationError) as raised:
            load_workflow_manifest(path)
        self.assertEqual(raised.exception.field, "steps")
        self.assertEqual(raised.exception.reason, "required field is missing")

    def test_error_string_contains_file_field_and_reason(self) -> None:
        path = self.temp / "absent.yaml"
        with self.assertRaises(ManifestFileNotFoundError) as raised:
            load_app_manifest(path)
        message = str(raised.exception)
        self.assertIn(str(path), message)
        self.assertIn("<root>", message)
        self.assertIn("manifest file was not found", message)

    def test_workflow_semantic_regression_rejects_undeclared_agent(self) -> None:
        manifest = read_yaml(WORKFLOW)
        manifest["steps"][1]["required_agent"] = {
            "id": "agt_01ARZ3NDEKTSV4RRFFQ69G5FAY",
            "version": "1.0.0",
            "role": "Undeclared Agent",
        }
        path = self.write_manifest("undeclared-agent.yaml", manifest)
        with self.assertRaises(ManifestValidationError) as raised:
            load_workflow_manifest(path)
        self.assertEqual(raised.exception.field, "steps[1].required_agent")
        self.assertEqual(raised.exception.reason, "Agent is not declared in required_agents")

    def test_app_semantic_regression_rejects_duplicate_workflow_id(self) -> None:
        manifest = read_yaml(APP)
        duplicate = deepcopy(manifest["workflows"][0])
        duplicate["version"] = "1.1.0"
        duplicate["manifest_ref"] = "workflows/discovery-v1.1.yaml"
        manifest["workflows"].append(duplicate)
        path = self.write_manifest("duplicate-workflow.yaml", manifest)
        with self.assertRaises(ManifestValidationError) as raised:
            load_app_manifest(path)
        self.assertEqual(raised.exception.field, "workflows[1].id")
        self.assertIn("duplicate identifier", raised.exception.reason)

    def test_repeated_loads_are_fresh_and_not_cached(self) -> None:
        loader = ManifestLoader()
        first = loader.load_agent_manifest(AGENT)
        first["name"] = "Mutated caller copy"
        second = loader.load_agent_manifest(AGENT)
        self.assertEqual(second["name"], "Product Manager")
        self.assertIsNot(first, second)

    def test_validation_error_selection_is_deterministic(self) -> None:
        manifest = read_yaml(AGENT)
        manifest["version"] = "latest"
        manifest["maturity"] = "production"
        path = self.write_manifest("multiple-errors.yaml", manifest)

        observed = []
        for _ in range(2):
            with self.assertRaises(ManifestValidationError) as raised:
                load_agent_manifest(path)
            observed.append((raised.exception.field, raised.exception.reason, str(raised.exception)))
        self.assertEqual(observed[0], observed[1])


if __name__ == "__main__":
    unittest.main()
