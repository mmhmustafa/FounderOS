"""The single-process instance lock.

Atlas's supported concurrency model is **one process per workspace**:
every repository serializes writers with in-process locks and atomic
replaces, discovery jobs are in-process threads, and the rate limiter
is in-memory. Those guarantees hold only inside one process — so Atlas
ENFORCES the model instead of documenting a hope.

At startup the application takes an OS-level exclusive lock on
``<workspace>/.atlas-instance.lock`` and holds it for the process
lifetime. A second process pointed at the same workspace (a second
``gunicorn`` worker, a second service instance, a stray dev server)
fails to acquire it and refuses to start with instructions, instead of
silently corrupting shared files. Within one process the lock is
re-entrant — building several app objects over one workspace (tests,
embedding) is one process and therefore safe.

The lock is advisory-exclusive via ``msvcrt.locking`` on Windows and
``fcntl.flock`` on POSIX; both release automatically if the process
dies, so a crash never leaves a stale lock behind.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

INSTANCE_LOCK_FILENAME = ".atlas-instance.lock"

_HELD: dict[str, "InstanceLock"] = {}
_HELD_GUARD = RLock()


def _lock_path_for(workspace_root: Path) -> Path:
    """The lock file for a workspace, kept OUTSIDE the workspace.

    The OS holds the lock handle open for the process lifetime; keeping
    the file inside the workspace would pin the directory (breaking
    workspace deletion and backups on Windows). The path is derived
    deterministically from the resolved workspace path, so every process
    contends on the same file for the same workspace.
    """

    import hashlib
    import tempfile

    digest = hashlib.sha256(
        str(workspace_root.resolve()).casefold().encode("utf-8")
    ).hexdigest()[:24]
    directory = Path(tempfile.gettempdir()) / "atlas-instance-locks"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{digest}.lock"


class WorkspaceInUseError(RuntimeError):
    """Another process already owns this workspace."""


class InstanceLock:
    def __init__(self, path: Path, handle: int) -> None:
        self.path = path
        self._handle = handle

    @property
    def held(self) -> bool:
        return self._handle is not None

    def release(self) -> None:  # pragma: no cover - process-lifetime lock
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(self._handle, 0, os.SEEK_SET)
                msvcrt.locking(self._handle, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle, fcntl.LOCK_UN)
        finally:
            os.close(self._handle)
            self._handle = None
            with _HELD_GUARD:
                _HELD.pop(str(self.path), None)


def acquire_instance_lock(workspace_root: str | Path) -> InstanceLock:
    """The workspace's exclusive instance lock (re-entrant per process).

    Raises :class:`WorkspaceInUseError` when another process holds it.
    """

    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    path = _lock_path_for(root)
    key = str(path)
    with _HELD_GUARD:
        existing = _HELD.get(key)
        if existing is not None and existing.held:
            return existing

        handle = os.open(path, os.O_CREAT | os.O_RDWR)
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(handle, 0, os.SEEK_SET)
                msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(handle)
            raise WorkspaceInUseError(
                f"Another Atlas process already serves the workspace "
                f"{root}. Atlas's supported model is ONE process per "
                "workspace (threads are fine; multiple WSGI workers are "
                "not). Stop the other instance, or point this one at a "
                "different workspace. If you are deploying with gunicorn, "
                "use exactly --workers 1."
            ) from error

        # Diagnostics only — the lock, not this text, is the control.
        try:
            os.lseek(handle, 8, os.SEEK_SET)
            os.write(handle, (
                f"pid={os.getpid()} "
                f"started={datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
            ).encode("utf-8"))
        except OSError:  # pragma: no cover - diagnostics are best-effort
            pass

        lock = InstanceLock(path, handle)
        _HELD[key] = lock
        return lock


def instance_lock_held(workspace_root: str | Path) -> bool:
    """Whether THIS process holds the workspace's instance lock."""

    path = _lock_path_for(Path(workspace_root))
    with _HELD_GUARD:
        lock = _HELD.get(str(path))
        return lock is not None and lock.held
