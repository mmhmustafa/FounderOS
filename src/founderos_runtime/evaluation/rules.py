"""Built-in and custom deterministic Evaluation rule behavior."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .contracts import EvaluationFinding, EvaluationRule, RuleType, thaw
from .exceptions import EvaluationConfigurationError, EvaluationExecutionError


CustomRule = Callable[[Any, Mapping[str, Any]], bool | tuple[bool, str]]
_MISSING = object()


def _resolve(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, tuple | list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def _require_keys(rule: EvaluationRule, required: set[str], allowed: set[str] | None = None) -> None:
    keys = set(rule.parameters)
    missing = sorted(required - keys)
    if missing:
        raise EvaluationConfigurationError(
            f"rule {rule.id!r} requires parameter {missing[0]!r}"
        )
    allowed_keys = allowed if allowed is not None else required
    unknown = sorted(keys - allowed_keys)
    if unknown:
        raise EvaluationConfigurationError(
            f"rule {rule.id!r} has unknown parameter {unknown[0]!r}"
        )


def validate_rule_configuration(rule: EvaluationRule) -> None:
    if rule.type is RuleType.REQUIRED_FIELD:
        _require_keys(rule, {"field"})
        _validate_field(rule)
    elif rule.type is RuleType.MINIMUM_LENGTH:
        _require_keys(rule, {"field", "minimum"})
        _validate_field(rule)
        minimum = rule.parameters["minimum"]
        if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
            raise EvaluationConfigurationError(
                f"rule {rule.id!r} minimum must be a non-negative integer"
            )
    elif rule.type is RuleType.REGEX:
        _require_keys(rule, {"field", "pattern"})
        _validate_field(rule)
        pattern = rule.parameters["pattern"]
        if not isinstance(pattern, str):
            raise EvaluationConfigurationError(f"rule {rule.id!r} pattern must be a string")
        try:
            re.compile(pattern)
        except re.error as error:
            raise EvaluationConfigurationError(
                f"rule {rule.id!r} pattern is invalid: {error.msg}"
            ) from error
    elif rule.type is RuleType.SCHEMA:
        _require_keys(rule, {"schema"}, {"schema", "field"})
        if "field" in rule.parameters:
            _validate_field(rule)
        schema = thaw(rule.parameters["schema"])
        if not isinstance(schema, dict):
            raise EvaluationConfigurationError(f"rule {rule.id!r} schema must be a mapping")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            raise EvaluationConfigurationError(
                f"rule {rule.id!r} schema is invalid: {error.message}"
            ) from error
    elif rule.type is RuleType.CUSTOM:
        _require_keys(rule, {"handler"}, set(rule.parameters))
        handler = rule.parameters["handler"]
        if not isinstance(handler, str) or not handler:
            raise EvaluationConfigurationError(f"rule {rule.id!r} handler must be non-empty")


def _validate_field(rule: EvaluationRule) -> None:
    field = rule.parameters["field"]
    if not isinstance(field, str) or not field or any(not part for part in field.split(".")):
        raise EvaluationConfigurationError(f"rule {rule.id!r} field must be a dotted path")


def evaluate_rule(
    rule: EvaluationRule,
    artifact: Any,
    custom_rules: Mapping[str, CustomRule],
) -> EvaluationFinding:
    validate_rule_configuration(rule)
    if rule.type is RuleType.REQUIRED_FIELD:
        field = rule.parameters["field"]
        passed = _resolve(artifact, field) is not _MISSING
        message = f"required field {field!r} is present" if passed else f"required field {field!r} is missing"
    elif rule.type is RuleType.MINIMUM_LENGTH:
        field = rule.parameters["field"]
        minimum = rule.parameters["minimum"]
        value = _resolve(artifact, field)
        actual = len(value) if isinstance(value, str | tuple | list | Mapping) else None
        passed = actual is not None and actual >= minimum
        message = (
            f"field {field!r} length {actual} meets minimum {minimum}"
            if passed
            else f"field {field!r} must have minimum length {minimum}"
        )
    elif rule.type is RuleType.REGEX:
        field = rule.parameters["field"]
        pattern = rule.parameters["pattern"]
        value = _resolve(artifact, field)
        passed = isinstance(value, str) and re.search(pattern, value) is not None
        message = (
            f"field {field!r} matches pattern"
            if passed
            else f"field {field!r} does not match pattern"
        )
    elif rule.type is RuleType.SCHEMA:
        subject = artifact
        if "field" in rule.parameters:
            subject = _resolve(artifact, rule.parameters["field"])
        errors = _schema_errors(subject, thaw(rule.parameters["schema"]))
        passed = not errors
        message = "schema validation passed" if passed else f"schema validation failed at {errors[0][0]}: {errors[0][1]}"
    else:
        handler_name = rule.parameters["handler"]
        handler = custom_rules.get(handler_name)
        if handler is None:
            raise EvaluationConfigurationError(
                f"rule {rule.id!r} references unknown custom handler {handler_name!r}"
            )
        parameters = {key: thaw(value) for key, value in rule.parameters.items() if key != "handler"}
        try:
            outcome = handler(thaw(artifact), parameters)
        except Exception as error:
            raise EvaluationExecutionError(
                f"custom rule {rule.id!r} handler {handler_name!r} failed: {type(error).__name__}"
            ) from error
        if isinstance(outcome, bool):
            passed = outcome
            message = "custom rule passed" if passed else "custom rule failed"
        elif (
            isinstance(outcome, tuple)
            and len(outcome) == 2
            and isinstance(outcome[0], bool)
            and isinstance(outcome[1], str)
            and outcome[1]
        ):
            passed, message = outcome
        else:
            raise EvaluationExecutionError(
                f"custom rule {rule.id!r} must return bool or (bool, non-empty message)"
            )
    return EvaluationFinding(
        rule_id=rule.id,
        severity=rule.severity,
        message=message,
        passed=passed,
    )


def _schema_errors(subject: Any, schema: dict[str, Any]) -> list[tuple[str, str]]:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(thaw(subject)),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
    )
    return [
        (".".join(str(part) for part in error.absolute_path) or "<root>", error.message)
        for error in errors
    ]


def expected_schema_finding(artifact: Any, schema: Mapping[str, Any]) -> EvaluationFinding:
    errors = _schema_errors(artifact, thaw(schema))
    return EvaluationFinding(
        rule_id="schema.expected",
        severity="error",
        message=(
            "expected schema validation passed"
            if not errors
            else f"expected schema validation failed at {errors[0][0]}: {errors[0][1]}"
        ),
        passed=not errors,
    )


def content_finding(artifact: Any) -> EvaluationFinding:
    empty = (
        artifact is None
        or (isinstance(artifact, str) and not artifact.strip())
        or (isinstance(artifact, Mapping | tuple | list) and len(artifact) == 0)
    )
    return EvaluationFinding(
        rule_id="content.not_empty",
        severity="error",
        message="artifact content is not empty" if not empty else "artifact content is empty",
        passed=not empty,
    )
