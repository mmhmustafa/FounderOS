"""Independent App Package Manifest structural and semantic contract tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "runtime" / "contracts" / "app" / "app.schema.yaml"
EXAMPLE_PATH = SCHEMA_PATH.parent / "examples" / "discovery-app.yaml"


def load_yaml(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def semantic_errors(manifest: dict[str, object]) -> list[str]:
    """Validate logical identifier uniqueness not expressible by uniqueItems."""

    errors: list[str] = []
    for field in (
        "workflows",
        "agents",
        "artifacts",
        "prompts",
        "evaluations",
        "policies",
        "fixtures",
        "documentation",
        "dependencies",
    ):
        ids = [item["id"] for item in manifest[field]]
        if len(ids) != len(set(ids)):
            errors.append(f"{field} contains duplicate identifiers")
    return errors


class AppManifestSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_yaml(SCHEMA_PATH)
        cls.example = load_yaml(EXAMPLE_PATH)
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def assert_invalid(self, manifest: dict[str, object]) -> None:
        self.assertTrue(list(self.validator.iter_errors(manifest)) or semantic_errors(manifest))

    def test_discovery_app_example_is_valid(self) -> None:
        self.validator.validate(self.example)
        self.assertEqual(semantic_errors(self.example), [])

    def test_missing_each_required_field_is_invalid(self) -> None:
        for field in self.schema["required"]:
            with self.subTest(field=field):
                manifest = deepcopy(self.example)
                del manifest[field]
                self.assertTrue(list(self.validator.iter_errors(manifest)))

    def test_empty_id_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["id"] = ""
        self.assert_invalid(manifest)

    def test_invalid_semantic_version_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["version"] = "1.0"
        self.assert_invalid(manifest)

    def test_invalid_maturity_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["maturity"] = "production"
        self.assert_invalid(manifest)

    def test_missing_workflow_references_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["workflows"] = []
        self.assert_invalid(manifest)

    def test_duplicate_workflow_identifiers_are_invalid(self) -> None:
        manifest = deepcopy(self.example)
        duplicate = deepcopy(manifest["workflows"][0])
        duplicate["version"] = "1.1.0"
        duplicate["manifest_ref"] = "workflows/discovery-workflow-v1.1.yaml"
        manifest["workflows"].append(duplicate)
        self.assertEqual(list(self.validator.iter_errors(manifest)), [])
        self.assertIn("duplicate identifiers", semantic_errors(manifest)[0])

    def test_invalid_runtime_compatibility_string_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["compatible_runtime"] = "latest"
        self.assert_invalid(manifest)

    def test_empty_agents_list_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["agents"] = []
        self.assert_invalid(manifest)

    def test_invalid_dependency_format_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["dependencies"] = [
            {"id": "invalid dependency", "version_range": "latest", "optional": False}
        ]
        self.assert_invalid(manifest)

    def test_execution_and_runtime_authority_fields_are_invalid(self) -> None:
        for field in ("execute", "provider", "tools", "memory", "runtime_state"):
            with self.subTest(field=field):
                manifest = deepcopy(self.example)
                manifest[field] = {}
                self.assert_invalid(manifest)

    def test_semantic_validation_is_deterministic(self) -> None:
        manifest = deepcopy(self.example)
        manifest["workflows"].append(deepcopy(manifest["workflows"][0]))
        self.assertEqual(semantic_errors(manifest), semantic_errors(manifest))


if __name__ == "__main__":
    unittest.main()
