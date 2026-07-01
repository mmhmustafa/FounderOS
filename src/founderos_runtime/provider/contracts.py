"""Immutable structured contracts for deterministic Provider generation."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .exceptions import ProviderRequestError


_OPERATION = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _validate_json_value(value: Any, field_name: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProviderRequestError(f"{field_name} mapping keys must be strings")
            _validate_json_value(item, field_name)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, field_name)
        return
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise ProviderRequestError(f"{field_name} must contain only JSON-compatible values")


def _json_copy(value: Any, field_name: str) -> Any:
    _validate_json_value(value, field_name)
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise ProviderRequestError(f"{field_name} must contain only JSON-compatible values") from error


def validate_operation(operation: object) -> str:
    if not isinstance(operation, str) or not _OPERATION.fullmatch(operation):
        raise ProviderRequestError("operation must be a lowercase namespaced token")
    return operation


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """Return a JSON-compatible defensive copy of a frozen contract value."""

    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return deepcopy(value)


def canonical_json(value: Any) -> str:
    return json.dumps(thaw(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


class ProviderStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


@dataclass(frozen=True)
class ProviderError:
    code: str
    message: str
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code or not _OPERATION.fullmatch(self.code):
            raise ProviderRequestError("ProviderError.code must be a non-empty stable code")
        if not self.message:
            raise ProviderRequestError("ProviderError.message must not be empty")
        if not isinstance(self.retryable, bool):
            raise ProviderRequestError("ProviderError.retryable must be a boolean")
        details = _json_copy(self.details, "ProviderError.details")
        if not isinstance(details, dict):
            raise ProviderRequestError("ProviderError.details must be a mapping")
        object.__setattr__(self, "details", _freeze(details))


@dataclass(frozen=True)
class ProviderRequest:
    request_id: str
    operation: str
    input: Mapping[str, Any]
    expected_output_schema: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ProviderRequestError("request_id must be a non-empty string")
        if len(self.request_id) > 200:
            raise ProviderRequestError("request_id must be at most 200 characters")
        validate_operation(self.operation)
        input_value = _json_copy(self.input, "input")
        if not isinstance(input_value, dict):
            raise ProviderRequestError("input must be a mapping")
        metadata = _json_copy(self.metadata, "metadata")
        if not isinstance(metadata, dict):
            raise ProviderRequestError("metadata must be a mapping")
        schema = None
        if self.expected_output_schema is not None:
            schema = _json_copy(self.expected_output_schema, "expected_output_schema")
            if not isinstance(schema, dict):
                raise ProviderRequestError("expected_output_schema must be a mapping")
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as error:
                raise ProviderRequestError(f"expected_output_schema is invalid: {error.message}") from error
        for field_name, value in (
            ("correlation_id", self.correlation_id),
            ("idempotency_key", self.idempotency_key),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ProviderRequestError(f"{field_name} must be null or a non-empty string")
        object.__setattr__(self, "input", _freeze(input_value))
        object.__setattr__(self, "metadata", _freeze(metadata))
        object.__setattr__(self, "expected_output_schema", _freeze(schema) if schema is not None else None)

    @property
    def fingerprint(self) -> str:
        payload = {
            "operation": self.operation,
            "input": thaw(self.input),
            "expected_output_schema": thaw(self.expected_output_schema),
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProviderResponse:
    request_id: str
    status: ProviderStatus
    output: Any
    error: ProviderError | None
    metadata: Mapping[str, Any]
    provider_name: str
    provider_version: str

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ProviderRequestError("ProviderResponse.request_id must not be empty")
        if not isinstance(self.status, ProviderStatus):
            raise ProviderRequestError("ProviderResponse.status must be a ProviderStatus")
        if self.status is ProviderStatus.SUCCESS and self.error is not None:
            raise ProviderRequestError("successful ProviderResponse must not contain an error")
        if self.status is ProviderStatus.ERROR and self.error is None:
            raise ProviderRequestError("error ProviderResponse must contain ProviderError")
        if not self.provider_name:
            raise ProviderRequestError("provider_name must not be empty")
        if not _SEMVER.fullmatch(self.provider_version):
            raise ProviderRequestError("provider_version must use Semantic Versioning")
        output = _json_copy(self.output, "ProviderResponse.output")
        metadata = _json_copy(self.metadata, "ProviderResponse.metadata")
        if not isinstance(metadata, dict):
            raise ProviderRequestError("ProviderResponse.metadata must be a mapping")
        object.__setattr__(self, "output", _freeze(output))
        object.__setattr__(self, "metadata", _freeze(metadata))
