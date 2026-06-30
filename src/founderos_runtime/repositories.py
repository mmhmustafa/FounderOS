"""Thread-safe in-memory repositories for contract records."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Iterable

from .contracts import ContractRegistry
from .errors import (
    ConflictError,
    DuplicateRecordError,
    RecordNotFoundError,
    ReferenceIntegrityError,
    StateMutationError,
)

_KIND_PREFIXES = {
    "agent": "agt_",
    "artifact": "art_",
    "workflow": "wfl_",
    "state": "sta_",
    "decision": "dec_",
    "project": "prj_",
    "workflow_run": "wfr_",
    "agent_run": "agr_",
    "transition": "trn_",
    "evaluation": "evl_",
    "approval": "apr_",
    "event": "evt_",
}


class InMemoryRepository:
    """Validate records at the boundary and return defensive copies."""

    def __init__(self, kind: str, contracts: ContractRegistry, lock: RLock, *, immutable: bool = False) -> None:
        self.kind = kind
        self.contracts = contracts
        self.lock = lock
        self.immutable = immutable
        self._records: dict[str, dict[str, Any]] = {}

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        validated = self.contracts.validate(self.kind, record)
        with self.lock:
            self._insert_validated(validated)
            return deepcopy(validated)

    def _insert_validated(self, record: dict[str, Any]) -> None:
        record_id = record["id"]
        if record_id in self._records:
            raise DuplicateRecordError(f"{self.kind} already exists: {record_id}")
        self._records[record_id] = deepcopy(record)

    def get(self, record_id: str) -> dict[str, Any]:
        with self.lock:
            try:
                return deepcopy(self._records[record_id])
            except KeyError as error:
                raise RecordNotFoundError(f"{self.kind} not found: {record_id}") from error

    def all(self) -> list[dict[str, Any]]:
        with self.lock:
            return [deepcopy(record) for record in self._records.values()]

    def replace(self, record: dict[str, Any], *, expected_revision: int | None = None) -> dict[str, Any]:
        validated = self.contracts.validate(self.kind, record)
        with self.lock:
            self._replace_validated(validated, expected_revision=expected_revision)
            return deepcopy(validated)

    def _replace_validated(self, record: dict[str, Any], *, expected_revision: int | None = None) -> None:
        if self.immutable:
            raise ConflictError(f"{self.kind} records are immutable")
        record_id = record["id"]
        if record_id not in self._records:
            raise RecordNotFoundError(f"{self.kind} not found: {record_id}")
        current = self._records[record_id]
        if expected_revision is not None and current.get("revision") != expected_revision:
            raise ConflictError(
                f"{self.kind} revision conflict for {record_id}: "
                f"expected {expected_revision}, stored {current.get('revision')}"
            )
        if "revision" in current and record.get("revision") != current["revision"] + 1:
            raise ConflictError(f"{self.kind} replacement must increment revision exactly once")
        self._records[record_id] = deepcopy(record)

    def _snapshot(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self._records)

    def _restore(self, snapshot: dict[str, dict[str, Any]]) -> None:
        self._records = deepcopy(snapshot)


class ProjectRepository(InMemoryRepository):
    """Project repository that rejects direct state mutation."""

    def replace(
        self,
        record: dict[str, Any],
        *,
        expected_revision: int | None = None,
        allow_state_change: bool = False,
    ) -> dict[str, Any]:
        validated = self.contracts.validate(self.kind, record)
        with self.lock:
            current = self.get(record["id"])
            if not allow_state_change and current["current_state"] != validated["current_state"]:
                raise StateMutationError("Project.current_state may only be changed by the State Machine")
            self._replace_validated(validated, expected_revision=expected_revision)
            return deepcopy(validated)


class EventRepository(InMemoryRepository):
    """Append-only, gap-free event streams ordered independently per project."""

    def __init__(self, contracts: ContractRegistry, lock: RLock) -> None:
        super().__init__("event", contracts, lock, immutable=True)
        self._streams: dict[str, list[str]] = defaultdict(list)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        validated = self.contracts.validate("event", event)
        with self.lock:
            self._append_validated(validated)
            return deepcopy(validated)

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.append(record)

    def _append_validated(self, event: dict[str, Any]) -> None:
        project_id = event["project_ref"]["id"]
        expected = len(self._streams[project_id]) + 1
        if event["sequence"] != expected:
            raise ConflictError(
                f"event sequence conflict for {project_id}: expected {expected}, got {event['sequence']}"
            )
        self._insert_validated(event)
        self._streams[project_id].append(event["id"])

    def next_sequence(self, project_id: str) -> int:
        with self.lock:
            return len(self._streams[project_id]) + 1

    def for_project(self, project_id: str) -> list[dict[str, Any]]:
        with self.lock:
            return [deepcopy(self._records[event_id]) for event_id in self._streams[project_id]]

    def _snapshot(self) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
        return deepcopy(self._records), deepcopy(dict(self._streams))

    def _restore(self, snapshot: tuple[dict[str, dict[str, Any]], dict[str, list[str]]]) -> None:
        records, streams = snapshot
        self._records = deepcopy(records)
        self._streams = defaultdict(list, deepcopy(streams))


@dataclass
class RuntimeRepositories:
    """Repository composition root sharing one in-memory transaction lock."""

    contracts: ContractRegistry
    lock: RLock = field(default_factory=RLock)
    projects: ProjectRepository = field(init=False)
    artifacts: InMemoryRepository = field(init=False)
    decisions: InMemoryRepository = field(init=False)
    workflow_runs: InMemoryRepository = field(init=False)
    agent_runs: InMemoryRepository = field(init=False)
    events: EventRepository = field(init=False)
    approvals: InMemoryRepository = field(init=False)
    evaluations: InMemoryRepository = field(init=False)
    transitions: InMemoryRepository = field(init=False)
    agents: InMemoryRepository = field(init=False)
    workflows: InMemoryRepository = field(init=False)

    def __post_init__(self) -> None:
        self.projects = ProjectRepository("project", self.contracts, self.lock)
        self.artifacts = InMemoryRepository("artifact", self.contracts, self.lock)
        self.decisions = InMemoryRepository("decision", self.contracts, self.lock)
        self.workflow_runs = InMemoryRepository("workflow_run", self.contracts, self.lock)
        self.agent_runs = InMemoryRepository("agent_run", self.contracts, self.lock)
        self.events = EventRepository(self.contracts, self.lock)
        self.approvals = InMemoryRepository("approval", self.contracts, self.lock)
        self.evaluations = InMemoryRepository("evaluation", self.contracts, self.lock, immutable=True)
        self.transitions = InMemoryRepository("transition", self.contracts, self.lock, immutable=True)
        self.agents = InMemoryRepository("agent", self.contracts, self.lock, immutable=True)
        self.workflows = InMemoryRepository("workflow", self.contracts, self.lock, immutable=True)

    def repository_for_kind(self, kind: str) -> InMemoryRepository:
        repositories = {
            "agent": self.agents,
            "artifact": self.artifacts,
            "workflow": self.workflows,
            "decision": self.decisions,
            "project": self.projects,
            "workflow_run": self.workflow_runs,
            "agent_run": self.agent_runs,
            "transition": self.transitions,
            "evaluation": self.evaluations,
            "approval": self.approvals,
            "event": self.events,
        }
        try:
            return repositories[kind]
        except KeyError as error:
            raise ReferenceIntegrityError(f"Unsupported reference kind: {kind}") from error

    def resolve_reference(self, ref: dict[str, Any], *, project_id: str | None = None) -> dict[str, Any]:
        kind = ref.get("kind")
        record_id = ref.get("id", "")
        expected_prefix = _KIND_PREFIXES.get(kind)
        if expected_prefix is None or not record_id.startswith(expected_prefix):
            raise ReferenceIntegrityError(f"Reference kind/ID prefix mismatch: {kind}/{record_id}")
        target = self.repository_for_kind(kind).get(record_id)
        if "version" in ref and target.get("version") != ref["version"]:
            raise ReferenceIntegrityError(f"Reference version mismatch for {record_id}")
        if "revision" in ref and target.get("revision") != ref["revision"]:
            raise ReferenceIntegrityError(f"Reference revision mismatch for {record_id}")
        owner_id = target.get("project_ref", {}).get("id")
        if project_id and owner_id and owner_id != project_id:
            raise ReferenceIntegrityError(f"Cross-project reference rejected: {record_id}")
        if project_id and kind == "project" and target["id"] != project_id:
            raise ReferenceIntegrityError(f"Wrong project reference: {record_id}")
        return target

    def resolve_all(self, refs: Iterable[dict[str, Any]], *, project_id: str) -> list[dict[str, Any]]:
        return [self.resolve_reference(ref, project_id=project_id) for ref in refs]
