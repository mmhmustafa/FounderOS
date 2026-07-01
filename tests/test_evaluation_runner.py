"""Deterministic Evaluation contracts, built-in rules, custom rules, and scoring tests."""

from __future__ import annotations

import unittest

from founderos_runtime.evaluation import (
    EvaluationConfigurationError,
    EvaluationRequest,
    EvaluationRule,
    EvaluationRunner,
    RuleType,
    Severity,
)


def rule(
    identifier: str,
    rule_type: RuleType | str,
    parameters: dict[str, object],
    *,
    severity: Severity | str = Severity.ERROR,
) -> EvaluationRule:
    return EvaluationRule(
        id=identifier,
        name=identifier.replace(".", " ").title(),
        description=f"Evaluate {identifier}",
        severity=severity,
        type=rule_type,
        parameters=parameters,
    )


class EvaluationRunnerTests(unittest.TestCase):
    def test_successful_evaluation(self) -> None:
        request = EvaluationRequest(
            request_id="eval-success",
            artifact={"summary": "Evidence-backed opportunity"},
            rules=(rule("summary.required", "required_field", {"field": "summary"}),),
        )
        result = EvaluationRunner().run(request)
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)
        self.assertTrue(all(finding.passed for finding in result.findings))

    def test_missing_required_field(self) -> None:
        request = EvaluationRequest(
            request_id="eval-missing",
            artifact={"title": "Opportunity"},
            rules=(rule("summary.required", "required_field", {"field": "summary"}),),
        )
        result = EvaluationRunner().run(request)
        self.assertFalse(result.passed)
        finding = next(item for item in result.findings if item.rule_id == "summary.required")
        self.assertFalse(finding.passed)
        self.assertIn("missing", finding.message)

    def test_empty_artifact(self) -> None:
        result = EvaluationRunner().run(
            EvaluationRequest(request_id="eval-empty", artifact={}, rules=())
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.findings[0].rule_id, "content.not_empty")

    def test_schema_mismatch(self) -> None:
        result = EvaluationRunner().run(
            EvaluationRequest(
                request_id="eval-schema",
                artifact={"score": "high"},
                expected_schema={
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "required": ["score"],
                    "properties": {"score": {"type": "integer"}},
                },
                rules=(),
            )
        )
        self.assertFalse(result.passed)
        finding = next(item for item in result.findings if item.rule_id == "schema.expected")
        self.assertIn("score", finding.message)

    def test_minimum_length_rule(self) -> None:
        request = EvaluationRequest(
            request_id="eval-length",
            artifact={"summary": "short"},
            rules=(
                rule(
                    "summary.length",
                    "minimum_length",
                    {"field": "summary", "minimum": 10},
                ),
            ),
        )
        result = EvaluationRunner().run(request)
        self.assertFalse(result.passed)
        self.assertIn("minimum length 10", result.findings[1].message)

    def test_regex_rule(self) -> None:
        request = EvaluationRequest(
            request_id="eval-regex",
            artifact={"slug": "Invalid Slug"},
            rules=(
                rule(
                    "slug.format",
                    "regex",
                    {"field": "slug", "pattern": "^[a-z][a-z0-9-]+$"},
                    severity="warning",
                ),
            ),
        )
        result = EvaluationRunner(minimum_score=0.5).run(request)
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 0.5)
        self.assertFalse(result.findings[1].passed)

    def test_custom_rule(self) -> None:
        def has_two_assumptions(artifact: object, parameters: object) -> tuple[bool, str]:
            assumptions = artifact["assumptions"]  # type: ignore[index]
            passed = len(assumptions) >= 2
            return passed, "at least two assumptions supplied" if passed else "too few assumptions"

        request = EvaluationRequest(
            request_id="eval-custom",
            artifact={"assumptions": ["A", "B"]},
            rules=(
                rule(
                    "assumptions.count",
                    "custom",
                    {"handler": "has_two_assumptions"},
                ),
            ),
        )
        result = EvaluationRunner(
            custom_rules={"has_two_assumptions": has_two_assumptions}
        ).run(request)
        self.assertTrue(result.passed)
        self.assertEqual(result.findings[1].message, "at least two assumptions supplied")

    def test_score_and_finding_order_are_deterministic(self) -> None:
        first_rule = rule("z.required", "required_field", {"field": "z"}, severity="warning")
        second_rule = rule("a.required", "required_field", {"field": "a"})
        first = EvaluationRunner(minimum_score=0).run(
            EvaluationRequest(
                request_id="eval-order",
                artifact={"a": 1},
                rules=(first_rule, second_rule),
            )
        )
        second = EvaluationRunner(minimum_score=0).run(
            EvaluationRequest(
                request_id="eval-order",
                artifact={"a": 1},
                rules=(second_rule, first_rule),
            )
        )
        self.assertEqual(first, second)
        self.assertEqual(first.score, 0.666667)
        self.assertEqual([item.rule_id for item in first.findings], ["content.not_empty", "a.required", "z.required"])

    def test_multiple_findings(self) -> None:
        request = EvaluationRequest(
            request_id="eval-multiple",
            artifact={"title": "x"},
            rules=(
                rule("summary.required", "required_field", {"field": "summary"}),
                rule("title.length", "minimum_length", {"field": "title", "minimum": 5}),
            ),
        )
        result = EvaluationRunner().run(request)
        self.assertEqual(len(result.findings), 3)
        self.assertEqual(sum(not item.passed for item in result.findings), 2)

    def test_critical_failure_blocks_even_with_zero_threshold(self) -> None:
        request = EvaluationRequest(
            request_id="eval-critical",
            artifact={"risk": "unknown"},
            rules=(
                rule(
                    "security.review",
                    "required_field",
                    {"field": "security_review"},
                    severity="critical",
                ),
            ),
        )
        result = EvaluationRunner(minimum_score=0).run(request)
        self.assertFalse(result.passed)
        self.assertEqual(result.findings[1].severity, Severity.CRITICAL)

    def test_invalid_rule_configuration(self) -> None:
        invalid = rule(
            "summary.length",
            "minimum_length",
            {"field": "summary", "minimum": -1},
        )
        request = EvaluationRequest(
            request_id="eval-invalid",
            artifact={"summary": "value"},
            rules=(invalid,),
        )
        with self.assertRaises(EvaluationConfigurationError) as raised:
            EvaluationRunner().run(request)
        self.assertIn("non-negative integer", str(raised.exception))

    def test_empty_rule_list(self) -> None:
        result = EvaluationRunner().run(
            EvaluationRequest(
                request_id="eval-no-rules",
                artifact={"content": "present"},
                rules=(),
                metadata={"correlation_id": "command-1"},
            )
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.metadata["request_metadata"]["correlation_id"], "command-1")


if __name__ == "__main__":
    unittest.main()
