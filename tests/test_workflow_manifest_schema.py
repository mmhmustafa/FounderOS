"""Independent Workflow Manifest structural and semantic contract tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "runtime" / "contracts" / "workflow" / "workflow.schema.yaml"
EXAMPLE_PATH = SCHEMA_PATH.parent / "examples" / "discovery-workflow.yaml"


def load_yaml(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def semantic_errors(manifest: dict[str, object]) -> list[str]:
    """Validate cross-field references JSON Schema cannot compare dynamically."""

    errors: list[str] = []
    required_agent_refs = {
        (agent["id"], agent["version"])
        for agent in manifest["required_agents"]
    }
    required_artifact_ids = {artifact["id"] for artifact in manifest["required_artifacts"]}
    produced_artifact_ids = {artifact["id"] for artifact in manifest["produced_artifacts"]}
    artifact_ids = required_artifact_ids | produced_artifact_ids
    approval_by_id = {approval["id"]: approval for approval in manifest["approvals"]}

    for step in manifest["steps"]:
        agent = step["required_agent"]
        if agent is not None and (agent["id"], agent["version"]) not in required_agent_refs:
            errors.append(f"step {step['id']} references an undeclared Agent")
        for artifact_id in step["input_artifacts"]:
            if artifact_id not in artifact_ids:
                errors.append(f"step {step['id']} references undeclared Artifact {artifact_id}")
        for artifact_id in step["output_artifacts"]:
            if artifact_id not in produced_artifact_ids:
                errors.append(f"step {step['id']} produces undeclared Artifact {artifact_id}")

    transition = manifest["transition_intent"]
    if transition is not None:
        if transition["from_state"] != manifest["entry_state"]:
            errors.append("transition from_state does not match entry_state")
        if transition["to_state"] != manifest["exit_state"]:
            errors.append("transition to_state does not match exit_state")
        for approval_ref in transition["approval_refs"]:
            approval = approval_by_id.get(approval_ref)
            if approval is None or not approval["required"]:
                errors.append(f"transition references missing or optional Approval {approval_ref}")

    for field in ("required_artifacts", "produced_artifacts", "steps", "evaluations", "approvals"):
        ids = [item["id"] for item in manifest[field]]
        if len(ids) != len(set(ids)):
            errors.append(f"{field} contains duplicate IDs")
    declared_artifact_ids = [
        artifact["id"]
        for artifact in manifest["required_artifacts"] + manifest["produced_artifacts"]
    ]
    if len(declared_artifact_ids) != len(set(declared_artifact_ids)):
        errors.append("Artifact IDs overlap across required and produced declarations")
    return errors


class WorkflowManifestSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_yaml(SCHEMA_PATH)
        cls.example = load_yaml(EXAMPLE_PATH)
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def assert_invalid(self, manifest: dict[str, object]) -> None:
        self.assertTrue(list(self.validator.iter_errors(manifest)) or semantic_errors(manifest))

    def test_discovery_workflow_example_is_valid(self) -> None:
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

    def test_invalid_workflow_type_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["workflow_type"] = "background_job"
        self.assert_invalid(manifest)

    def test_utility_workflow_with_transition_intent_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["workflow_type"] = "utility"
        manifest["exit_state"] = None
        self.assert_invalid(manifest)

    def test_lifecycle_workflow_without_transition_intent_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["transition_intent"] = None
        self.assert_invalid(manifest)

    def test_step_with_invalid_type_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["steps"][0]["type"] = "execute_directly"
        self.assert_invalid(manifest)

    def test_step_referencing_undeclared_required_agent_is_invalid(self) -> None:
        manifest = deepcopy(self.example)
        manifest["steps"][1]["required_agent"] = {
            "id": "agt_01ARZ3NDEKTSV4RRFFQ69G5FAY",
            "version": "1.0.0",
            "role": "Undeclared Agent",
        }
        self.assertEqual(list(self.validator.iter_errors(manifest)), [])
        self.assertIn("undeclared Agent", semantic_errors(manifest)[0])

    def test_validation_is_deterministic(self) -> None:
        manifest = deepcopy(self.example)
        manifest["steps"][1]["required_agent"] = {
            "id": "agt_01ARZ3NDEKTSV4RRFFQ69G5FAY",
            "version": "1.0.0",
            "role": "Undeclared Agent",
        }
        self.assertEqual(semantic_errors(manifest), semantic_errors(manifest))


if __name__ == "__main__":
    unittest.main()
