"""Independent Agent Manifest schema validation tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "runtime" / "contracts" / "agent" / "agent.schema.yaml"
EXAMPLE_PATH = SCHEMA_PATH.parent / "examples" / "product-manager.yaml"


def load_yaml(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class AgentManifestSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_yaml(SCHEMA_PATH)
        cls.example = load_yaml(EXAMPLE_PATH)
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def assert_invalid(self, manifest: dict[str, object]) -> None:
        self.assertTrue(list(self.validator.iter_errors(manifest)))

    def test_product_manager_example_is_valid(self) -> None:
        self.validator.validate(self.example)

    def test_missing_each_required_field_is_invalid(self) -> None:
        for field in self.schema["required"]:
            with self.subTest(field=field):
                manifest = deepcopy(self.example)
                del manifest[field]
                self.assert_invalid(manifest)

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

    def test_unknown_tool_category_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["allowed_tool_categories"] = ["database_admin"]
        self.assert_invalid(manifest)

    def test_missing_capabilities_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        del manifest["capabilities"]
        self.assert_invalid(manifest)

    def test_validation_errors_are_deterministic(self) -> None:
        manifest = deepcopy(self.example)
        manifest["version"] = "latest"
        first = [(list(error.path), error.validator) for error in self.validator.iter_errors(manifest)]
        second = [(list(error.path), error.validator) for error in self.validator.iter_errors(manifest)]
        self.assertEqual(first, second)

    def test_prohibited_runtime_and_prompt_fields_are_invalid(self) -> None:
        for field in ("prompt", "secrets", "runtime_state", "conversation_history", "model_config"):
            with self.subTest(field=field):
                manifest = deepcopy(self.example)
                manifest[field] = {}
                self.assert_invalid(manifest)

        manifest = deepcopy(self.example)
        manifest["provider_preferences"]["model"] = "provider-specific-model"
        self.assert_invalid(manifest)


if __name__ == "__main__":
    unittest.main()
