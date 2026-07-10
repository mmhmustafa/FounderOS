"""Persistent storage for credential sets — metadata only, never secrets.

Credential sets live beside the profile store
(``<workspace_root>/credential_sets.json``). Every entry carries only a
``credential_ref`` into the secure credential provider.
"""

from __future__ import annotations

import json
from pathlib import Path

from founderos_atlas.workspace.exceptions import WorkspaceCorruptedError
from founderos_atlas.workspace.repository import default_workspace_root

from .models import CREDENTIAL_SETS_SCHEMA_VERSION, CredentialSet


CREDENTIAL_SETS_FILENAME = "credential_sets.json"


class CredentialSetRepository:
    """Load and persist credential sets, keyed by ``set_id``."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self._root = (
            Path(workspace_root) if workspace_root is not None else default_workspace_root()
        )

    @property
    def path(self) -> Path:
        return self._root / CREDENTIAL_SETS_FILENAME

    def load(self) -> dict[str, CredentialSet]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The credential set file {self.path} could not be read: {error}"
            ) from error
        entries = raw.get("credential_sets") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            raise WorkspaceCorruptedError(
                f"The credential set file {self.path} does not contain a set list."
            )
        sets: dict[str, CredentialSet] = {}
        for entry in entries:
            credential_set = CredentialSet.from_dict(entry)
            sets[credential_set.set_id] = credential_set
        return sets

    def list(self) -> tuple[CredentialSet, ...]:
        return tuple(
            sorted(self.load().values(), key=lambda item: item.name.casefold())
        )

    def get(self, set_id: str) -> CredentialSet | None:
        return self.load().get(set_id)

    def save(self, credential_set: CredentialSet) -> None:
        sets = self.load()
        sets[credential_set.set_id] = credential_set
        self._write(sets)

    def delete(self, set_id: str) -> CredentialSet | None:
        sets = self.load()
        removed = sets.pop(set_id, None)
        if removed is not None:
            self._write(sets)
        return removed

    def _write(self, sets: dict[str, CredentialSet]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        ordered = sorted(sets.values(), key=lambda item: item.name.casefold())
        document = {
            "schema_version": CREDENTIAL_SETS_SCHEMA_VERSION,
            "credential_sets": [item.to_dict() for item in ordered],
        }
        self.path.write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
