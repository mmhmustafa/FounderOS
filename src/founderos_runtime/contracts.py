"""Load and enforce FounderOS JSON Schema contracts."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry, Resource

from .errors import ContractValidationError

SCHEMA_FILES = {
    "agent": "agent.schema.json",
    "artifact": "artifact.schema.json",
    "workflow": "workflow.schema.json",
    "state": "state.schema.json",
    "decision": "decision.schema.json",
    "project": "project.schema.json",
    "workflow_run": "workflow-run.schema.json",
    "agent_run": "agent-run.schema.json",
    "transition": "transition.schema.json",
    "evaluation": "evaluation.schema.json",
    "approval": "approval.schema.json",
    "event": "event.schema.json",
    "founder_brief_content": "founder-brief-content.schema.json",
}


def _default_contract_directory() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "runtime" / "contracts"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("Could not locate runtime/contracts; provide contract_directory explicitly")


class ContractRegistry:
    """Immutable registry of validated Draft 2020-12 schemas."""

    def __init__(self, contract_directory: str | Path | None = None) -> None:
        self.contract_directory = Path(contract_directory) if contract_directory else _default_contract_directory()
        self._schemas: dict[str, dict[str, Any]] = {}
        resources: list[tuple[str, Resource[Any]]] = []

        for path in sorted(self.contract_directory.glob("*.schema.json")):
            with path.open("r", encoding="utf-8") as handle:
                schema = json.load(handle)
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as error:
                raise ContractValidationError(f"Invalid schema {path.name}: {error.message}") from error
            self._schemas[path.name] = schema
            resources.append((schema["$id"], Resource.from_contents(schema)))

        missing = set(SCHEMA_FILES.values()) - set(self._schemas)
        if missing:
            raise ContractValidationError(f"Missing required schemas: {', '.join(sorted(missing))}")

        self._registry = Registry().with_resources(resources)
        self._validators = {
            kind: Draft202012Validator(
                self._schemas[filename],
                registry=self._registry,
                format_checker=FormatChecker(),
            )
            for kind, filename in SCHEMA_FILES.items()
        }

    @property
    def schema_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._schemas))

    def schema(self, kind: str) -> dict[str, Any]:
        try:
            return deepcopy(self._schemas[SCHEMA_FILES[kind]])
        except KeyError as error:
            raise ValueError(f"Unknown contract kind: {kind}") from error

    def validate(self, kind: str, record: dict[str, Any]) -> dict[str, Any]:
        """Validate without coercion or mutation and return a defensive copy."""

        try:
            validator = self._validators[kind]
        except KeyError as error:
            raise ValueError(f"Unknown contract kind: {kind}") from error
        errors = sorted(validator.iter_errors(record), key=lambda item: tuple(str(part) for part in item.absolute_path))
        if errors:
            error: ValidationError = errors[0]
            path = ".".join(str(part) for part in error.absolute_path) or "<root>"
            raise ContractValidationError(f"{kind} contract violation at {path}: {error.message}") from error
        return deepcopy(record)
