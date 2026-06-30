"""Hardened local-file persistence for the FounderOS CLI."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
from datetime import UTC, datetime
from typing import Any, Callable, Iterator

from .content import InMemoryContentStore
from .contracts import ContractRegistry
from .errors import ConflictError, PersistenceLockError, RecordNotFoundError, RecoveryError
from .project_state import replay_project_events
from .repositories import RuntimeRepositories


_RECORD_KINDS = (
    "agent", "workflow", "project", "workflow_run", "agent_run", "artifact",
    "decision", "evaluation", "approval", "transition",
)


def _migrate_v0_to_v1(snapshot: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(snapshot)
    migrated["format_version"] = 1
    migrated.setdefault("store_revision", 0)
    return migrated


def _migrate_v1_to_v2(snapshot: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(snapshot)
    migrated["format_version"] = 2
    migrated.setdefault("commands", {})
    return migrated


MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    0: _migrate_v0_to_v1,
    1: _migrate_v1_to_v2,
}


@dataclass(frozen=True)
class LocalRuntime:
    repositories: RuntimeRepositories
    content: InMemoryContentStore
    store_revision: int = 0
    commands: dict[str, dict[str, Any]] | None = None


@dataclass(frozen=True)
class PersistenceHealth:
    status: str
    primary_valid: bool
    backup_available: bool
    backup_valid: bool
    locked: bool
    format_version: int | None
    store_revision: int | None
    issues: tuple[str, ...]
    recovery_recommended: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "primary_valid": self.primary_valid,
            "backup_available": self.backup_available,
            "backup_valid": self.backup_valid,
            "locked": self.locked,
            "format_version": self.format_version,
            "store_revision": self.store_revision,
            "issues": list(self.issues),
            "recovery_recommended": self.recovery_recommended,
        }


class LocalProjectStore:
    """Persist one validated Project with optimistic single-writer protection."""

    FORMAT_VERSION = 2

    def __init__(self, root: str | Path = ".founderos", *, failure_injector: Callable[[str], None] | None = None) -> None:
        self.root = Path(root)
        self.state_path = self.root / "project-state.json"
        self.events_path = self.root / "events.jsonl"
        self.artifacts_path = self.root / "artifacts"
        self.backup_path = self.root / "backup"
        self.lock_path = self.root / ".write.lock"
        self.failure_injector = failure_injector

    @property
    def exists(self) -> bool:
        return self.state_path.is_file()

    def empty_runtime(self) -> LocalRuntime:
        repositories = RuntimeRepositories(ContractRegistry())
        return LocalRuntime(repositories, InMemoryContentStore(repositories.lock), 0, {})

    def load(self) -> LocalRuntime:
        if not self.exists:
            raise RecordNotFoundError(f"No FounderOS project exists at {self.root}")
        snapshot = self._migrate_snapshot(self._read_json(self.state_path))
        runtime = self._hydrate(snapshot)
        commands = snapshot.get("commands", {})
        if not isinstance(commands, dict):
            raise ConflictError("Persisted command journal must be a JSON object")
        return LocalRuntime(runtime.repositories, runtime.content, snapshot["store_revision"], commands)

    def save(self, runtime: LocalRuntime) -> None:
        projects = runtime.repositories.projects.all()
        if len(projects) != 1:
            raise ConflictError("Local CLI persistence requires exactly one Project")
        self.root.mkdir(parents=True, exist_ok=True)
        with self.writer_lock():
            current_revision = self._current_store_revision()
            if current_revision != runtime.store_revision:
                raise ConflictError(
                    f"Stale local persistence write: expected store revision {runtime.store_revision}, "
                    f"stored {current_revision}"
                )
            if self.exists:
                self._create_backup()
            self._phase("after_backup")
            next_revision = current_revision + 1
            records = {
                kind: runtime.repositories.repository_for_kind(kind).all() for kind in _RECORD_KINDS
            }
            events = runtime.repositories.events.for_project(projects[0]["id"])
            event_text = "".join(
                json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events
            )
            self.artifacts_path.mkdir(parents=True, exist_ok=True)
            expected_files: set[Path] = set()
            for artifact in runtime.repositories.artifacts.all():
                path = self.artifacts_path / f"{artifact['id']}.json"
                expected_files.add(path)
                self._write_json_atomic(path, runtime.content.get(artifact["content_uri"]))
            self._phase("after_artifacts")
            self._write_text_atomic(self.events_path, event_text)
            self._phase("after_events")
            self._phase("before_state")
            self._write_json_atomic(
                self.state_path,
                {
                    "format_version": self.FORMAT_VERSION,
                    "store_revision": next_revision,
                    "commands": runtime.commands or {},
                    "records": records,
                },
            )
            self._phase("after_state")
            for path in self.artifacts_path.glob("*.json"):
                if path not in expected_files:
                    path.unlink()

    @contextmanager
    def writer_lock(self) -> Iterator[None]:
        """Acquire an exclusive lock file or fail immediately."""

        self.root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise PersistenceLockError(
                f"FounderOS persistence is locked by another writer: {self.lock_path}"
            ) from error
        try:
            metadata = json.dumps({"pid": os.getpid(), "created_at": datetime.now(UTC).isoformat()}) + "\n"
            os.write(descriptor, metadata.encode("utf-8"))
            os.close(descriptor)
            descriptor = -1
            yield
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            self.lock_path.unlink(missing_ok=True)

    def health(self) -> PersistenceHealth:
        issues: list[str] = []
        locked = self.lock_path.exists()
        primary_valid = False
        format_version: int | None = None
        store_revision: int | None = None
        try:
            runtime = self.load()
            primary_valid = True
            store_revision = runtime.store_revision
            format_version = self.FORMAT_VERSION
        except Exception as error:
            issues.append(f"primary: {error}")
            try:
                raw = self._read_json(self.state_path)
                value = raw.get("format_version", 0)
                format_version = value if isinstance(value, int) else None
            except Exception:
                pass
        backup_available = (self.backup_path / "project-state.json").is_file()
        backup_valid = False
        if backup_available:
            try:
                LocalProjectStore(self.backup_path).load()
                backup_valid = True
            except Exception as error:
                issues.append(f"backup: {error}")
        if locked:
            issues.append(f"writer lock present: {self.lock_path}")
        recovery_recommended = not primary_valid and backup_valid
        status = "healthy" if primary_valid and not locked else "recoverable" if recovery_recommended else "unhealthy"
        return PersistenceHealth(
            status, primary_valid, backup_available, backup_valid, locked,
            format_version, store_revision, tuple(issues), recovery_recommended,
        )

    def recover(self) -> PersistenceHealth:
        """Restore the last validated pre-write backup and revalidate it."""

        backup_store = LocalProjectStore(self.backup_path)
        if not backup_store.exists:
            raise RecoveryError("No local persistence backup is available")
        try:
            backup_store.load()
        except Exception as error:
            raise RecoveryError(f"Local persistence backup is invalid: {error}") from error
        with self.writer_lock():
            self._copy_file_atomic(backup_store.state_path, self.state_path)
            self._copy_file_atomic(backup_store.events_path, self.events_path)
            if self.artifacts_path.exists():
                shutil.rmtree(self.artifacts_path)
            if backup_store.artifacts_path.exists():
                shutil.copytree(backup_store.artifacts_path, self.artifacts_path)
            else:
                self.artifacts_path.mkdir(parents=True, exist_ok=True)
        result = self.health()
        if not result.primary_valid:
            raise RecoveryError("Backup restore completed but validation still failed")
        return result

    def inspect_lock(self) -> dict[str, Any] | None:
        """Return lock metadata and liveness without modifying the lock."""

        if not self.lock_path.is_file():
            return None
        metadata = self._read_json(self.lock_path)
        pid = metadata.get("pid")
        created_at = metadata.get("created_at")
        if not isinstance(pid, int) or not isinstance(created_at, str):
            raise ConflictError("Writer lock metadata is invalid")
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ConflictError("Writer lock timestamp is invalid") from error
        age_seconds = max(0.0, (datetime.now(UTC) - created).total_seconds())
        return {"pid": pid, "created_at": created_at, "age_seconds": age_seconds, "owner_alive": self._pid_alive(pid)}

    def clear_stale_lock(self, *, expected_pid: int, minimum_age_seconds: float = 300.0) -> None:
        """Remove only an old lock whose exact recorded process is no longer alive."""

        info = self.inspect_lock()
        if info is None:
            raise PersistenceLockError("No writer lock exists")
        if info["pid"] != expected_pid:
            raise PersistenceLockError("Writer lock PID changed; refusing removal")
        if info["owner_alive"]:
            raise PersistenceLockError("Writer process is still alive; refusing removal")
        if info["age_seconds"] < minimum_age_seconds:
            raise PersistenceLockError("Writer lock is too recent; refusing removal")
        self.lock_path.unlink()

    def _hydrate(self, snapshot: dict[str, Any]) -> LocalRuntime:
        runtime = self.empty_runtime()
        records = snapshot.get("records")
        if not isinstance(records, dict):
            raise ConflictError("Local persistence records must be a JSON object")
        for kind in _RECORD_KINDS:
            items = records.get(kind, [])
            if not isinstance(items, list):
                raise ConflictError(f"Local persistence record collection must be an array: {kind}")
        runtime.repositories.import_records(records)
        if not self.events_path.is_file():
            raise RecordNotFoundError(f"Required local persistence file is missing: {self.events_path}")
        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(self.events_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ConflictError(f"Invalid Event JSON on line {line_number}") from error
            events.append(event)
        runtime.repositories.import_events(events)
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

    def _migrate_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        version = snapshot.get("format_version", 0)
        if not isinstance(version, int) or version < 0:
            raise ConflictError("Invalid local persistence format version")
        if version > self.FORMAT_VERSION:
            raise ConflictError(
                f"Unsupported future local persistence format {version}; runtime supports {self.FORMAT_VERSION}"
            )
        migrated = dict(snapshot)
        while version < self.FORMAT_VERSION:
            migration = MIGRATIONS.get(version)
            if migration is None:
                raise ConflictError(f"No migration exists from local persistence format {version}")
            migrated = migration(migrated)
            next_version = migrated.get("format_version")
            if not isinstance(next_version, int) or next_version <= version:
                raise ConflictError(f"Invalid migration result from local persistence format {version}")
            version = next_version
        revision = migrated.get("store_revision", 0)
        if not isinstance(revision, int) or revision < 0:
            raise ConflictError("Invalid local persistence store revision")
        migrated["store_revision"] = revision
        commands = migrated.get("commands", {})
        if not isinstance(commands, dict):
            raise ConflictError("Invalid persisted command journal")
        migrated["commands"] = commands
        return migrated

    def _current_store_revision(self) -> int:
        if not self.exists:
            return 0
        snapshot = self._migrate_snapshot(self._read_json(self.state_path))
        return snapshot["store_revision"]

    def _create_backup(self) -> None:
        """Create a validated copy of the last committed primary state."""

        self.load()
        temporary = self.root / "backup.tmp"
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)
        shutil.copy2(self.state_path, temporary / self.state_path.name)
        shutil.copy2(self.events_path, temporary / self.events_path.name)
        if self.artifacts_path.exists():
            shutil.copytree(self.artifacts_path, temporary / "artifacts")
        if self.backup_path.exists():
            shutil.rmtree(self.backup_path)
        temporary.replace(self.backup_path)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise RecordNotFoundError(f"Required local persistence file is missing: {path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConflictError(f"Invalid JSON persistence file: {path}") from error
        if not isinstance(value, dict):
            raise ConflictError(f"Expected a JSON object in {path}")
        return value

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
        LocalProjectStore._write_text_atomic(path, json.dumps(value, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def _write_text_atomic(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(value, encoding="utf-8", newline="\n")
        temporary.replace(path)

    @staticmethod
    def _copy_file_atomic(source: Path, destination: Path) -> None:
        if not source.is_file():
            raise RecoveryError(f"Backup file is missing: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".recovery.tmp")
        shutil.copy2(source, temporary)
        temporary.replace(destination)

    def _phase(self, phase: str) -> None:
        if self.failure_injector is not None:
            self.failure_injector(phase)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (OSError, PermissionError):
            return False
