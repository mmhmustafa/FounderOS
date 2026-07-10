"""Memory of which credential reference last worked for each device.

Only references, hostnames, and timestamps are stored — never secrets. The
memory lets the resolver prefer a previously successful credential for a
stable device identity, cutting failed attempts (and lockout risk) on
subsequent runs. Persistence is best-effort: a missing or corrupt file
simply means no memory.
"""

from __future__ import annotations

import json
from pathlib import Path

from founderos_atlas.workspace.repository import default_workspace_root


CREDENTIAL_MEMORY_FILENAME = "credential_memory.json"


class CredentialSuccessMemory:
    """host -> {credential_ref, username, hostname, last_used}; refs only."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        root = (
            Path(workspace_root) if workspace_root is not None else default_workspace_root()
        )
        self._path = root / CREDENTIAL_MEMORY_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def recall(self, host: str) -> dict | None:
        entry = self._load().get(str(host).strip())
        return dict(entry) if isinstance(entry, dict) else None

    def hostname_for(self, host: str) -> str | None:
        entry = self.recall(host)
        return entry.get("hostname") if entry else None

    def record_success(
        self,
        host: str,
        *,
        credential_ref: str,
        username: str,
        hostname: str | None = None,
        when: str | None = None,
    ) -> None:
        data = self._load()
        entry = {
            "credential_ref": credential_ref,
            "username": username,
            "last_used": when,
        }
        if hostname:
            entry["hostname"] = hostname
        data[str(host).strip()] = entry
        self._write(data)

    def _load(self) -> dict:
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        devices = data.get("devices") if isinstance(data, dict) else None
        return dict(devices) if isinstance(devices, dict) else {}

    def _write(self, devices: dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {"schema_version": "1.0.0", "devices": devices},
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            # Memory is an optimization; never fail a discovery over it.
            pass
