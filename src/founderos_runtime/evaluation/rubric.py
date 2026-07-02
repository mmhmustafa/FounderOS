"""Immutable executable view of a validated Evaluation Rubric manifest."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .contracts import EvaluationRequest, EvaluationRule
from .runner import EvaluationRunner
from .rules import CustomRule, validate_rule_configuration


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return deepcopy(value)


@dataclass(frozen=True)
class EvaluationRubric:
    id: str
    name: str
    version: str
    description: str
    status: str
    maturity: str
    applies_to: Mapping[str, Any]
    rules: tuple[EvaluationRule, ...]
    scoring: Mapping[str, Any]
    pass_threshold: float
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "applies_to", _freeze(self.applies_to))
        object.__setattr__(self, "scoring", _freeze(self.scoring))
        object.__setattr__(self, "metadata", _freeze(self.metadata))
        object.__setattr__(self, "pass_threshold", float(self.pass_threshold))

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any]) -> "EvaluationRubric":
        rules = tuple(
            EvaluationRule(
                id=item["id"],
                name=item["name"],
                description=item["description"],
                severity=item["severity"],
                type=item["type"],
                parameters=item["parameters"],
            )
            for item in manifest["rules"]
        )
        for rule in rules:
            validate_rule_configuration(rule)
        return cls(
            id=manifest["id"],
            name=manifest["name"],
            version=manifest["version"],
            description=manifest["description"],
            status=manifest["status"],
            maturity=manifest["maturity"],
            applies_to=manifest["applies_to"],
            rules=rules,
            scoring=manifest["scoring"],
            pass_threshold=manifest["pass_threshold"],
            metadata=manifest["metadata"],
        )

    def runner(
        self, *, custom_rules: Mapping[str, CustomRule] | None = None
    ) -> EvaluationRunner:
        return EvaluationRunner(
            minimum_score=self.pass_threshold,
            custom_rules=custom_rules,
        )

    def request(
        self,
        request_id: str,
        artifact: Any,
        *,
        expected_schema: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvaluationRequest:
        return EvaluationRequest(
            request_id=request_id,
            artifact=artifact,
            expected_schema=expected_schema,
            rules=self.rules,
            metadata={
                "rubric_id": self.id,
                "rubric_version": self.version,
                **dict(metadata or {}),
            },
        )

