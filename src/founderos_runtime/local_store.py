"""Simple, validated local-file persistence for the FounderOS CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .content import InMemoryContentStore
from .contracts import ContractRegistry
from .errors import ConflictError, RecordNotFoundError
from .project_state import replay_project_events
from .repositories import RuntimeRepositories


_RECORD_KINDS = (
    "agent", "workflow", "project", "workflow_run", "agent_run", "artifact",
    "decision", "evaluation", "approval", "transition",
)


@dataclass(frozen=True)
class LocalRuntime:
    repositories: RuntimeRepositories
    content: InMemoryContentStore


class LocalProjectStore:
    """Persist one CLI project as JSON, JSONL Events, and JSON artifacts."""

    FORMAT_VERSION = 1

    def __init__(self, root: str | Path = ".founderos") -> None:
        self.root = Path(root)
        self.state_path = self.root / "project-state.json"
        self.events_path = self.root / "events.jsonl"
        self.artifacts_path = self.root / "artifacts"

    @property
    def exists(self) -> bool:
        return self.state_path.is_file()

    def empty_runtime(self) -> LocalRuntime:
        repositories = RuntimeRepositories(ContractRegistry())
        return LocalRuntime(repositories, InMemoryContentStore(repositories.lock))

    def load(self) -> LocalRuntime:
        if not self.exists:
            raise RecordNotFoundError(f"No FounderOS project exists at {self.root}")
        snapshot = self._read_json(self.state_path)
        if snapshot.get("format_version") != self.FORMAT_VERSION:
            raise ConflictError("Unsupported local FounderOS persistence format")
        runtime = self.empty_runtime()
        records = snapshot.get("records", {})
        for kind in _RECORD_KINDS:
            repository = runtime.repositories.repository_for_kind(kind)
            for record in records.get(kind, []):
                validated = runtime.repositories.contracts.validate(kind, record)
                repository._insert_validated(validated)
        if self.events_path.exists():
            for line_number, line in enumerate(self.events_path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ConflictError(f"Invalid Event JSON on line {line_number}") from error
                runtime.repositories.events.append(event)
        projects = runtime.repositories.projects.all()
        if len(projects) != 1:
            raise ConflictError("Local FounderOS persistence must contain exactly one Project")
        project = projects[0]
        replayed = replay_project_events(runtime.repositories.events.for_project(project["id"]))
        if (replayed["current_state"], replayed["revision"]) != (project["current_state"], project["revision"]):
            raise ConflictError("Persisted Project does not match deterministic Event replay")
        for artifact in runtime.repositories.artifacts.all():
            content_path = self.artifacts_path / f"{artifact['id']}.json"
            content = self._read_json(content_path)
            _, digest = runtime.content.put(artifact["content_uri"], content)
            if digest != artifact["content_digest"]:
                raise ConflictError(f"Artifact content digest mismatch: {artifact['id']}")
        return runtime

    def save(self, runtime: LocalRuntime) -> None:
        projects = runtime.repositories.projects.all()
        if len(projects) != 1:
            raise ConflictError("Local CLI persistence requires exactly one Project")
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_path.mkdir(parents=True, exist_ok=True)
        records: dict[str, list[dict[str, Any]]] = {}
        for kind in _RECORD_KINDS:
            records[kind] = runtime.repositories.repository_for_kind(kind).all()
        self._write_json_atomic(self.state_path, {"format_version": self.FORMAT_VERSION, "records": records})
        events = runtime.repositories.events.for_project(projects[0]["id"])
        event_text = "".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events)
        self._write_text_atomic(self.events_path, event_text)
        expected_files: set[Path] = set()
        for artifact in runtime.repositories.artifacts.all():
            path = self.artifacts_path / f"{artifact['id']}.json"
            expected_files.add(path)
            self._write_json_atomic(path, runtime.content.get(artifact["content_uri"]))
        for path in self.artifacts_path.glob("*.json"):
            if path not in expected_files:
                path.unlink()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise RecordNotFoundError(f"Required local persistence file is missing: {path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ConflictError(f"Invalid JSON persistence file: {path}") from error
        if not isinstance(value, dict):
            raise ConflictError(f"Expected a JSON object in {path}")
        return value

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
        LocalProjectStore._write_text_atomic(path, json.dumps(value, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def _write_text_atomic(path: Path, value: str) -> None:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(value, encoding="utf-8", newline="\n")
        temporary.replace(path)
