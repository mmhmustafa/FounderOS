"""Deterministic structural and semantic manifest validation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from .exceptions import ManifestSchemaError, ManifestValidationError


def _field_path(parts: object) -> str:
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += ("." if path else "") + str(part)
    return path or "<root>"


def _join_field(base: str, child: str) -> str:
    if base == "<root>":
        return child
    return f"{base}.{child}"


def _validation_detail(error: ValidationError) -> tuple[str, str]:
    field = _field_path(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, Mapping):
        missing = sorted(set(error.validator_value) - set(error.instance))
        if missing:
            return _join_field(field, missing[0]), "required field is missing"
    if error.validator == "additionalProperties" and isinstance(error.instance, Mapping):
        allowed = set(error.schema.get("properties", {}))
        extras = sorted(set(error.instance) - allowed)
        if extras:
            return _join_field(field, extras[0]), "unknown field is not allowed"
    return field, error.message


def validate_schema(schema: object, schema_path: Path) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise ManifestSchemaError(schema_path, "<schema>", "schema root must be a mapping")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        field = _field_path(error.absolute_path)
        raise ManifestSchemaError(schema_path, field, error.message) from error
    return schema


def validate_manifest(
    kind: str,
    manifest: object,
    schema: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(manifest),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            str(error.validator),
            error.message,
        ),
    )
    if errors:
        field, reason = _validation_detail(errors[0])
        raise ManifestValidationError(manifest_path, field, reason) from errors[0]
    if not isinstance(manifest, dict):
        raise ManifestValidationError(manifest_path, "<root>", "manifest root must be a mapping")

    semantic_errors = _semantic_errors(kind, manifest)
    if semantic_errors:
        field, reason = sorted(semantic_errors)[0]
        raise ManifestValidationError(manifest_path, field, reason)
    return manifest


def _duplicate_identifier_errors(manifest: dict[str, Any], fields: tuple[str, ...]) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    for field in fields:
        seen: set[str] = set()
        for index, item in enumerate(manifest[field]):
            identifier = item["id"]
            if identifier in seen:
                errors.append((f"{field}[{index}].id", f"duplicate identifier {identifier!r}"))
            seen.add(identifier)
    return errors


def _workflow_semantic_errors(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    errors = _duplicate_identifier_errors(
        manifest,
        ("required_artifacts", "produced_artifacts", "steps", "evaluations", "approvals"),
    )
    required_agents = {(agent["id"], agent["version"]) for agent in manifest["required_agents"]}
    required_artifacts = {artifact["id"] for artifact in manifest["required_artifacts"]}
    produced_artifacts = {artifact["id"] for artifact in manifest["produced_artifacts"]}
    all_artifacts = required_artifacts | produced_artifacts
    approvals = {approval["id"]: approval for approval in manifest["approvals"]}

    overlap = sorted(required_artifacts & produced_artifacts)
    if overlap:
        errors.append(("produced_artifacts", f"artifact identifier {overlap[0]!r} is also required"))

    for index, step in enumerate(manifest["steps"]):
        agent = step["required_agent"]
        if agent is not None and (agent["id"], agent["version"]) not in required_agents:
            errors.append((f"steps[{index}].required_agent", "Agent is not declared in required_agents"))
        for artifact in step["input_artifacts"]:
            if artifact not in all_artifacts:
                errors.append((f"steps[{index}].input_artifacts", f"undeclared Artifact {artifact!r}"))
        for artifact in step["output_artifacts"]:
            if artifact not in produced_artifacts:
                errors.append((f"steps[{index}].output_artifacts", f"undeclared produced Artifact {artifact!r}"))

    transition = manifest["transition_intent"]
    if transition is not None:
        if transition["from_state"] != manifest["entry_state"]:
            errors.append(("transition_intent.from_state", "must match entry_state"))
        if transition["to_state"] != manifest["exit_state"]:
            errors.append(("transition_intent.to_state", "must match exit_state"))
        for index, approval_ref in enumerate(transition["approval_refs"]):
            approval = approvals.get(approval_ref)
            if approval is None or not approval["required"]:
                errors.append(
                    (f"transition_intent.approval_refs[{index}]", "must reference a required Approval")
                )
    return errors


def _app_semantic_errors(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    return _duplicate_identifier_errors(
        manifest,
        (
            "workflows",
            "agents",
            "artifacts",
            "prompts",
            "evaluations",
            "policies",
            "fixtures",
            "documentation",
            "dependencies",
        ),
    )


def _semantic_errors(kind: str, manifest: dict[str, Any]) -> list[tuple[str, str]]:
    if kind == "workflow":
        return _workflow_semantic_errors(manifest)
    if kind == "app":
        return _app_semantic_errors(manifest)
    return []
