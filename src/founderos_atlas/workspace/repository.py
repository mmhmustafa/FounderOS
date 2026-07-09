"""Persistent storage for saved discovery profiles.

Profiles are kept as a single JSON document in the Atlas workspace
directory (``~/.atlas/workspace/profiles.json`` by default). Only profile
metadata and credential references are stored here — never a password.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .exceptions import DuplicateProfileError, ProfileNotFoundError, WorkspaceCorruptedError
from .models import DiscoveryProfile, normalize_name


PROFILES_FILENAME = "profiles.json"


def atlas_home() -> Path:
    """Root of the Atlas application-data directory (overridable for tests)."""

    override = os.environ.get("ATLAS_HOME")
    return Path(override) if override else Path.home() / ".atlas"


def default_workspace_root() -> Path:
    return atlas_home() / "workspace"


class ProfileRepository:
    """Load and persist discovery profiles; keyed by normalized name."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self._root = Path(workspace_root) if workspace_root is not None else default_workspace_root()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def profiles_path(self) -> Path:
        return self._root / PROFILES_FILENAME

    def load(self) -> dict[str, DiscoveryProfile]:
        path = self.profiles_path
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise WorkspaceCorruptedError(
                f"The Atlas workspace file {path} could not be read: {error}"
            ) from error
        entries = raw.get("profiles") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            raise WorkspaceCorruptedError(
                f"The Atlas workspace file {path} does not contain a profile list."
            )
        profiles: dict[str, DiscoveryProfile] = {}
        for entry in entries:
            profile = DiscoveryProfile.from_dict(entry)
            profiles[profile.normalized_name] = profile
        return profiles

    def list(self) -> tuple[DiscoveryProfile, ...]:
        profiles = self.load()
        return tuple(
            sorted(profiles.values(), key=lambda profile: profile.name.casefold())
        )

    def get(self, name: str) -> DiscoveryProfile:
        profiles = self.load()
        profile = profiles.get(normalize_name(name))
        if profile is None:
            raise ProfileNotFoundError(f"No saved profile named {name!r}.")
        return profile

    def exists(self, name: str) -> bool:
        return normalize_name(name) in self.load()

    def add(self, profile: DiscoveryProfile) -> None:
        profiles = self.load()
        if profile.normalized_name in profiles:
            raise DuplicateProfileError(
                f"A profile named {profile.name!r} already exists."
            )
        profiles[profile.normalized_name] = profile
        self._write(profiles)

    def save(self, profile: DiscoveryProfile) -> None:
        """Insert or replace a profile (used for updates)."""

        profiles = self.load()
        profiles[profile.normalized_name] = profile
        self._write(profiles)

    def delete(self, name: str) -> DiscoveryProfile:
        profiles = self.load()
        key = normalize_name(name)
        if key not in profiles:
            raise ProfileNotFoundError(f"No saved profile named {name!r}.")
        removed = profiles.pop(key)
        self._write(profiles)
        return removed

    def _write(self, profiles: dict[str, DiscoveryProfile]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        ordered = sorted(profiles.values(), key=lambda profile: profile.name.casefold())
        document = {
            "schema_version": "1.0.0",
            "profiles": [profile.to_dict() for profile in ordered],
        }
        self.profiles_path.write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
