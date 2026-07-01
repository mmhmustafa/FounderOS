"""Immutable contracts for deterministic quality Evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import json
import math
import re
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .exceptions import EvaluationRequestError


_RULE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def _validate_json(value: Any, field_name: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise EvaluationRequestError(f"{field_name} mapping keys must be strings")
            _validate_json(item, field_name)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, field_name)
        return
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise EvaluationRequestError(f"{field_name} must contain only JSON-compatible values")


def _json_copy(value: Any, field_name: str) -> Any:
    _validate_json(value, field_name)
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (TypeError, ValueError) as error:
        raise EvaluationRequestError(
            f"{field_name} must contain only JSON-compatible values"
        ) from error


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """Return a defensive JSON-compatible copy of frozen Evaluation data."""

    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return deepcopy(value)


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RuleType(str, Enum):
    REQUIRED_FIELD = "required_field"
    SCHEMA = "schema"
    MINIMUM_LENGTH = "minimum_length"
    REGEX = "regex"
    CUSTOM = "custom"


def _enum_value(value: Any, enum_type: type[Enum], field_name: str) -> Enum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        allowed = ", ".join(item.value for item in enum_type)
        raise EvaluationRequestError(f"{field_name} must be one of: {allowed}") from error


@dataclass(frozen=True)
class EvaluationRule:
    id: str
    name: str
    description: str
    severity: Severity | str
    type: RuleType | str
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _RULE_ID.fullmatch(self.id):
            raise EvaluationRequestError("EvaluationRule.id must be a stable lowercase token")
        if not isinstance(self.name, str) or not self.name.strip():
            raise EvaluationRequestError("EvaluationRule.name must not be empty")
        if not isinstance(self.description, str) or not self.description.strip():
            raise EvaluationRequestError("EvaluationRule.description must not be empty")
        severity = _enum_value(self.severity, Severity, "EvaluationRule.severity")
        rule_type = _enum_value(self.type, RuleType, "EvaluationRule.type")
        parameters = _json_copy(self.parameters, "EvaluationRule.parameters")
        if not isinstance(parameters, dict):
            raise EvaluationRequestError("EvaluationRule.parameters must be a mapping")
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "type", rule_type)
        object.__setattr__(self, "parameters", _freeze(parameters))


@dataclass(frozen=True)
class EvaluationRequest:
    request_id: str
    artifact: Any
    expected_schema: Mapping[str, Any] | None = None
    rules: tuple[EvaluationRule, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise EvaluationRequestError("request_id must be a non-empty string")
        artifact = _json_copy(self.artifact, "artifact")
        metadata = _json_copy(self.metadata, "metadata")
        if not isinstance(metadata, dict):
            raise EvaluationRequestError("metadata must be a mapping")
        if not isinstance(self.rules, tuple) or not all(
            isinstance(rule, EvaluationRule) for rule in self.rules
        ):
            raise EvaluationRequestError("rules must be a tuple of EvaluationRule objects")
        rule_ids = [rule.id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise EvaluationRequestError("rules must have unique ids")
        schema = None
        if self.expected_schema is not None:
            schema = _json_copy(self.expected_schema, "expected_schema")
            if not isinstance(schema, dict):
                raise EvaluationRequestError("expected_schema must be a mapping")
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as error:
                raise EvaluationRequestError(f"expected_schema is invalid: {error.message}") from error
        object.__setattr__(self, "artifact", _freeze(artifact))
        object.__setattr__(self, "metadata", _freeze(metadata))
        object.__setattr__(self, "expected_schema", _freeze(schema) if schema is not None else None)


@dataclass(frozen=True)
class EvaluationFinding:
    rule_id: str
    severity: Severity | str
    message: str
    passed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not _RULE_ID.fullmatch(self.rule_id):
            raise EvaluationRequestError("EvaluationFinding.rule_id must be a stable lowercase token")
        severity = _enum_value(self.severity, Severity, "EvaluationFinding.severity")
        if not isinstance(self.message, str) or not self.message.strip():
            raise EvaluationRequestError("EvaluationFinding.message must not be empty")
        if not isinstance(self.passed, bool):
            raise EvaluationRequestError("EvaluationFinding.passed must be a boolean")
        object.__setattr__(self, "severity", severity)


@dataclass(frozen=True)
class EvaluationResult:
    request_id: str
    passed: bool
    score: float
    findings: tuple[EvaluationFinding, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise EvaluationRequestError("EvaluationResult.request_id must not be empty")
        if not isinstance(self.passed, bool):
            raise EvaluationRequestError("EvaluationResult.passed must be a boolean")
        if not isinstance(self.score, int | float) or isinstance(self.score, bool):
            raise EvaluationRequestError("EvaluationResult.score must be numeric")
        if not 0 <= float(self.score) <= 1:
            raise EvaluationRequestError("EvaluationResult.score must be between 0 and 1")
        if not isinstance(self.findings, tuple) or not all(
            isinstance(finding, EvaluationFinding) for finding in self.findings
        ):
            raise EvaluationRequestError("findings must be a tuple of EvaluationFinding objects")
        metadata = _json_copy(self.metadata, "EvaluationResult.metadata")
        if not isinstance(metadata, dict):
            raise EvaluationRequestError("EvaluationResult.metadata must be a mapping")
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(self, "metadata", _freeze(metadata))
