"""Pure deterministic Evaluation runner."""

from __future__ import annotations

from collections.abc import Mapping

from .contracts import EvaluationRequest, EvaluationResult, Severity, thaw
from .exceptions import EvaluationConfigurationError, EvaluationRequestError
from .rules import CustomRule, content_finding, evaluate_rule, expected_schema_finding


class EvaluationRunner:
    """Evaluate one immutable request without I/O, persistence, or runtime mutation."""

    def __init__(
        self,
        *,
        minimum_score: float = 1.0,
        custom_rules: Mapping[str, CustomRule] | None = None,
    ) -> None:
        if (
            not isinstance(minimum_score, int | float)
            or isinstance(minimum_score, bool)
            or not 0 <= float(minimum_score) <= 1
        ):
            raise EvaluationConfigurationError("minimum_score must be between 0 and 1")
        handlers = dict(custom_rules or {})
        for name, handler in handlers.items():
            if not isinstance(name, str) or not name or not callable(handler):
                raise EvaluationConfigurationError(
                    "custom_rules must map non-empty names to callable handlers"
                )
        self._minimum_score = float(minimum_score)
        self._custom_rules = handlers

    def run(self, request: EvaluationRequest) -> EvaluationResult:
        if not isinstance(request, EvaluationRequest):
            raise EvaluationRequestError("run requires an EvaluationRequest")
        findings = [content_finding(request.artifact)]
        if request.expected_schema is not None:
            findings.append(expected_schema_finding(request.artifact, request.expected_schema))
        for rule in sorted(request.rules, key=lambda item: item.id):
            findings.append(evaluate_rule(rule, request.artifact, self._custom_rules))

        passed_count = sum(finding.passed for finding in findings)
        score = round(passed_count / len(findings), 6)
        blocking_failure = any(
            not finding.passed and finding.severity in (Severity.ERROR, Severity.CRITICAL)
            for finding in findings
        )
        passed = score >= self._minimum_score and not blocking_failure
        return EvaluationResult(
            request_id=request.request_id,
            passed=passed,
            score=score,
            findings=tuple(findings),
            metadata={
                "minimum_score": self._minimum_score,
                "total_findings": len(findings),
                "passed_findings": passed_count,
                "request_metadata": thaw(request.metadata),
            },
        )
