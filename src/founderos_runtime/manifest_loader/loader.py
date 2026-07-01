"""Read and validate declarative FounderOS YAML manifests without execution."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .exceptions import (
    ManifestFileNotFoundError,
    ManifestReadError,
    ManifestSchemaError,
    ManifestYamlError,
)
from .validators import validate_manifest, validate_schema


SCHEMA_PATHS = {
    "agent": Path("agent") / "agent.schema.yaml",
    "workflow": Path("workflow") / "workflow.schema.yaml",
    "app": Path("app") / "app.schema.yaml",
}


def _default_contract_directory() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "runtime" / "contracts"
        if candidate.is_dir():
            return candidate
    raise ManifestSchemaError(
        "runtime/contracts",
        "<schema>",
        "contract directory was not found; provide contract_directory explicitly",
    )


def _yaml_reason(error: yaml.YAMLError) -> str:
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None) or "malformed YAML"
    if mark is None:
        return str(problem)
    return f"{problem} at line {mark.line + 1}, column {mark.column + 1}"


def _read_yaml(path: Path, *, schema: bool = False) -> object:
    error_type = ManifestSchemaError if schema else ManifestYamlError
    field = "<schema>" if schema else "<root>"
    try:
        is_file = path.is_file()
    except OSError as error:
        raise ManifestReadError(path, field, f"file could not be inspected: {error.strerror or error}") from error
    if not is_file:
        if schema:
            raise ManifestSchemaError(path, field, "schema file was not found")
        raise ManifestFileNotFoundError(path, field, "manifest file was not found")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except yaml.YAMLError as error:
        raise error_type(path, field, _yaml_reason(error)) from error
    except UnicodeError as error:
        raise error_type(path, field, "file is not valid UTF-8") from error
    except OSError as error:
        raise ManifestReadError(path, field, f"file could not be read: {error.strerror or error}") from error


class ManifestLoader:
    """Stateless loader for Agent, Workflow, and App YAML manifests."""

    def __init__(self, contract_directory: str | Path | None = None) -> None:
        self.contract_directory = (
            Path(contract_directory) if contract_directory is not None else _default_contract_directory()
        )

    def load_agent_manifest(self, path: str | Path) -> dict[str, Any]:
        return self._load("agent", path)

    def load_workflow_manifest(self, path: str | Path) -> dict[str, Any]:
        return self._load("workflow", path)

    def load_app_manifest(self, path: str | Path) -> dict[str, Any]:
        return self._load("app", path)

    def _load(self, kind: str, path: str | Path) -> dict[str, Any]:
        manifest_path = Path(path)
        schema_path = self.contract_directory / SCHEMA_PATHS[kind]
        schema = validate_schema(_read_yaml(schema_path, schema=True), schema_path)
        manifest = _read_yaml(manifest_path)
        validated = validate_manifest(kind, manifest, schema, manifest_path)
        return deepcopy(validated)


def load_agent_manifest(path: str | Path) -> dict[str, Any]:
    return ManifestLoader().load_agent_manifest(path)


def load_workflow_manifest(path: str | Path) -> dict[str, Any]:
    return ManifestLoader().load_workflow_manifest(path)


def load_app_manifest(path: str | Path) -> dict[str, Any]:
    return ManifestLoader().load_app_manifest(path)
