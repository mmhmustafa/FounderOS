"""Per-user display preferences (PR: progressive disclosure).

The workspace preferences (`administration.py`) are deliberately
workspace-wide — retention, log level, timezone are operational policy.
The DISPLAY LEVEL is personal: how much detail one operator wants to
see. It therefore persists per owner (the authenticated username, or
``local-operator`` in local mode), in the workspace under
``user-preferences.json`` — the same atomic-replace + per-store lock
pattern every other workspace store uses, surviving browser and server
restarts without touching localStorage.

Display levels are a strict ladder of progressive disclosure:

- ``simple``   — conclusions, health, primary actions, important warnings
- ``detailed`` — plus operational evidence, secondary actions, filters
- ``expert``   — plus full protocol, provenance, diagnostics, advanced controls

The default is honest about history: a NEW workspace defaults everyone
to ``simple``; a workspace that predates this feature carries a
migration marker defaulting its users to ``expert`` so nobody's
controls disappear on upgrade. A corrupt or missing store silently
falls back to that same default — a broken preference file must never
break a page.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

USER_PREFERENCES_FILENAME = "user-preferences.json"
UX_DEFAULTS_FILENAME = "ux-defaults.json"

LEVEL_SIMPLE = "simple"
LEVEL_DETAILED = "detailed"
LEVEL_EXPERT = "expert"
DISPLAY_LEVELS = (LEVEL_SIMPLE, LEVEL_DETAILED, LEVEL_EXPERT)

_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


def _lock_for(path: Path) -> RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path), RLock())


class UserPreferenceStore:
    """Per-owner display preferences, isolated by username."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root)
        self.path = self.root / USER_PREFERENCES_FILENAME
        self._lock = _lock_for(self.path)

    # -- defaults ---------------------------------------------------------------

    def default_display_level(self) -> str:
        """``expert`` on workspaces that predate the feature (the upgrade
        marker written by migration v2), ``simple`` everywhere else."""

        marker = self.root / UX_DEFAULTS_FILENAME
        if marker.is_file():
            try:
                value = json.loads(marker.read_text(encoding="utf-8"))
                candidate = str(value.get("display_level_default") or "")
                if candidate in DISPLAY_LEVELS:
                    return candidate
            except (ValueError, TypeError, OSError):
                pass
        return LEVEL_SIMPLE

    # -- reading ----------------------------------------------------------------

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}   # corrupt store: fall back, never break a page
        users = raw.get("users") if isinstance(raw, Mapping) else None
        if not isinstance(users, Mapping):
            return {}
        return {
            str(owner).casefold(): dict(value)
            for owner, value in users.items()
            if isinstance(value, Mapping)
        }

    def display_level(self, owner: str) -> str:
        """The owner's persisted level, else the workspace default.

        Unknown or corrupt values fall back to the default — a bad byte
        in the store must never change what a page can render.
        """

        record = self._read().get(str(owner or "").casefold()) or {}
        candidate = str(record.get("display_level") or "")
        return (
            candidate if candidate in DISPLAY_LEVELS
            else self.default_display_level()
        )

    # -- writing ----------------------------------------------------------------

    def set_display_level(self, owner: str, level: str) -> str:
        cleaned = str(level or "").strip().casefold()
        if cleaned not in DISPLAY_LEVELS:
            raise ValueError(
                "Display level must be one of: " + ", ".join(DISPLAY_LEVELS)
            )
        key = str(owner or "").strip().casefold()
        if not key:
            raise ValueError("An owner is required for a display preference.")
        with self._lock:
            users = self._read()
            record = users.get(key) or {}
            record["display_level"] = cleaned
            users[key] = record
            self._write(users)
        return cleaned

    # -- generic namespaced UI preferences ------------------------------------

    #: Key prefixes a client may write through the UI-preference API.
    #: Anything else is refused — this store must never become a dumping
    #: ground, and security-sensitive state never rides through it.
    ALLOWED_UI_PREFIXES = ("topology:", "table:", "workflow:")
    MAX_UI_VALUE_BYTES = 4096

    def ui_value(self, owner: str, key: str, default: Any = None) -> Any:
        record = self._read().get(str(owner or "").casefold()) or {}
        values = record.get("ui")
        if not isinstance(values, Mapping):
            return default
        return values.get(str(key), default)

    def set_ui_value(self, owner: str, key: str, value: Any) -> None:
        cleaned_key = str(key or "").strip()
        if not any(
            cleaned_key.startswith(prefix)
            for prefix in self.ALLOWED_UI_PREFIXES
        ):
            raise ValueError(
                "UI preference keys must start with one of: "
                + ", ".join(self.ALLOWED_UI_PREFIXES)
            )
        encoded = json.dumps(value)
        if len(encoded.encode("utf-8")) > self.MAX_UI_VALUE_BYTES:
            raise ValueError("UI preference value is too large.")
        owner_key = str(owner or "").strip().casefold()
        if not owner_key:
            raise ValueError("An owner is required for a UI preference.")
        with self._lock:
            users = self._read()
            record = users.get(owner_key) or {}
            values = dict(record.get("ui") or {})
            values[cleaned_key] = value
            record["ui"] = values
            users[owner_key] = record
            self._write(users)

    def _write(self, users: Mapping[str, Mapping[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid4().hex}.writing"
        )
        try:
            temporary.write_text(
                json.dumps(
                    {"schema_version": "1.0.0", "users": dict(users)},
                    indent=2, sort_keys=True, ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
