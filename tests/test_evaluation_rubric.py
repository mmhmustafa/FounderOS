"""Evaluation Rubric schema, loading, execution, and isolation tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from founderos_runtime.evaluation import (
    EvaluationRubricLoader,
    EvaluationRule,
    load_evaluation_rubric,
)
from founderos_runtime.manifest_loader import (
    ManifestLoader,
    ManifestValidationError,
)
from founderos_runtime.provider import MockProvider

from tests.helpers import RuntimeFixture


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = (
    ROOT
    / "runtime"
    / "contracts"
    / "evaluation"
    / "examples"
    / "opportunity-report-rubric.yaml"
)


class EvaluationRubricTests(unittest.TestCase):
    def setUp(self) -> None:
        with EXAMPLE.open("r", encoding="utf-8") as handle:
            self.manifest = yaml.safe_load(handle)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def write_manifest(self, manifest: object) -> Path:
        path = Path(self.directory.name) / "rubric.yaml"
        path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        return path

    @staticmethod
    def valid_artifact() -> dict[str, object]:
        return {
            "candidates": [
                {
                    "problem": "Founders cannot compare evidence consistently.",
                    "target_user": "Technical B2B SaaS founders",
                }
            ],
            "selected_opportunity": {
                "problem": "Founders cannot compare evidence consistently.",
                "target_user": "Technical B2B SaaS founders",
            },
        }

    def test_valid_rubric_manifest(self) -> None:
        loaded = ManifestLoader().load_evaluation_rubric_manifest(EXAMPLE)
        self.assertEqual(loaded["id"], self.manifest["id"])
        self.assertEqual(loaded["scoring"]["method"], "passed_finding_ratio")

    def test_missing_required_field(self) -> None:
        manifest = deepcopy(self.manifest)
        del manifest["rules"]
        with self.assertRaises(ManifestValidationError) as raised:
            ManifestLoader().load_evaluation_rubric_manifest(self.write_manifest(manifest))
        self.assertEqual(raised.exception.field, "rules")

    def test_invalid_semantic_version(self) -> None:
        manifest = deepcopy(self.manifest)
        manifest["version"] = "1.0"
        with self.assertRaises(ManifestValidationError) as raised:
            ManifestLoader().load_evaluation_rubric_manifest(self.write_manifest(manifest))
        self.assertEqual(raised.exception.field, "version")

    def test_invalid_maturity(self) -> None:
        manifest = deepcopy(self.manifest)
        manifest["maturity"] = "production"
        with self.assertRaises(ManifestValidationError) as raised:
            ManifestLoader().load_evaluation_rubric_manifest(self.write_manifest(manifest))
        self.assertEqual(raised.exception.field, "maturity")

    def test_invalid_rule_type(self) -> None:
        manifest = deepcopy(self.manifest)
        manifest["rules"][0]["type"] = "model_judge"
        with self.assertRaises(ManifestValidationError) as raised:
            ManifestLoader().load_evaluation_rubric_manifest(self.write_manifest(manifest))
        self.assertEqual(raised.exception.field, "rules[0].type")

    def test_rubric_loads_into_evaluation_rules(self) -> None:
        rubric = EvaluationRubricLoader().load(EXAMPLE)
        self.assertTrue(rubric.rules)
        self.assertTrue(all(isinstance(rule, EvaluationRule) for rule in rubric.rules))
        self.assertEqual(rubric.pass_threshold, 1.0)

    def test_opportunity_report_rubric_evaluates_valid_artifact(self) -> None:
        rubric = load_evaluation_rubric(EXAMPLE)
        result = rubric.runner().run(
            rubric.request("evaluation.valid", self.valid_artifact())
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.metadata["request_metadata"]["rubric_id"], rubric.id)

    def test_opportunity_report_rubric_fails_invalid_artifact(self) -> None:
        rubric = load_evaluation_rubric(EXAMPLE)
        result = rubric.runner().run(
            rubric.request("evaluation.invalid", {"candidates": []})
        )
        self.assertFalse(result.passed)
        self.assertTrue(any(not finding.passed for finding in result.findings))

    def test_deterministic_scoring(self) -> None:
        rubric = load_evaluation_rubric(EXAMPLE)
        request = rubric.request("evaluation.repeat", self.valid_artifact())
        first = rubric.runner().run(request)
        second = rubric.runner().run(request)
        self.assertEqual(first, second)

    def test_no_provider_calls(self) -> None:
        rubric = load_evaluation_rubric(EXAMPLE)
        with patch.object(
            MockProvider,
            "generate",
            side_effect=AssertionError("Provider must not be called"),
        ):
            result = rubric.runner().run(
                rubric.request("evaluation.offline", self.valid_artifact())
            )
        self.assertTrue(result.passed)

    def test_no_runtime_mutation(self) -> None:
        runtime = RuntimeFixture()
        before = runtime.repositories.export_records()
        rubric = load_evaluation_rubric(EXAMPLE)
        rubric.runner().run(rubric.request("evaluation.read_only", self.valid_artifact()))
        self.assertEqual(before, runtime.repositories.export_records())


if __name__ == "__main__":
    unittest.main()

