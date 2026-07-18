"""Secret-free persistence for Atlas administration preferences and drafts.

Passwords and tokens are structurally rejected.  Wizard drafts contain only
targeting and policy fields, making browser/server restart resumption safe
without expanding the credential-store boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .repository import default_workspace_root


FORBIDDEN_KEYS = frozenset({"password", "secret", "token", "private_key", "passphrase"})
PREFERENCES_FILENAME = "preferences.json"
DRAFTS_FILENAME = "discovery_drafts.json"


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.writing")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    unsafe = FORBIDDEN_KEYS.intersection(str(key).casefold() for key in value)
    if unsafe:
        raise ValueError("Secret fields are not permitted in administrative metadata.")
    return {str(key): item for key, item in value.items()}


@dataclass(frozen=True)
class WorkspacePreferences:
    timezone: str = "auto"
    theme: str = "system"
    density: str = "comfortable"
    retention_days: int = 365
    log_level: str = "INFO"
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "WorkspacePreferences":
        value = value or {}
        timezone_name = str(value.get("timezone") or "auto").strip()
        theme = str(value.get("theme") or "system").casefold()
        density = str(value.get("density") or "comfortable").casefold()
        log_level = str(value.get("log_level") or "INFO").upper()
        try:
            retention = int(value.get("retention_days", 365))
        except (TypeError, ValueError):
            retention = 365
        if theme not in {"system", "light", "dark"}:
            raise ValueError("Theme must be system, light, or dark.")
        if density not in {"comfortable", "compact"}:
            raise ValueError("Density must be comfortable or compact.")
        if log_level not in {"ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("Log level must be ERROR, WARNING, INFO, or DEBUG.")
        if not 1 <= retention <= 3650:
            raise ValueError("Retention must be between 1 and 3650 days.")
        return cls(
            timezone=timezone_name, theme=theme, density=density,
            retention_days=retention, log_level=log_level,
            updated_at=(str(value["updated_at"]) if value.get("updated_at") else None),
        )


class PreferencesConflictError(RuntimeError):
    """The caller saved over preferences someone changed meanwhile."""


class AdministrationRepository:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_workspace_root()

    @property
    def preferences_path(self) -> Path:
        return self.root / PREFERENCES_FILENAME

    @property
    def drafts_path(self) -> Path:
        return self.root / DRAFTS_FILENAME

    def preferences(self) -> WorkspacePreferences:
        if not self.preferences_path.is_file():
            return WorkspacePreferences()
        return WorkspacePreferences.from_dict(
            json.loads(self.preferences_path.read_text(encoding="utf-8"))
        )

    def save_preferences(
        self,
        value: Mapping[str, Any],
        *,
        expected_updated_at: str | None = None,
    ) -> WorkspacePreferences:
        current = self.preferences()
        if (
            expected_updated_at is not None
            and (current.updated_at or "") != expected_updated_at
        ):
            raise PreferencesConflictError(
                "The settings changed while you were editing "
                f"(saved {current.updated_at or 'never'}, you edited "
                f"{expected_updated_at or 'a fresh form'}). Nothing was "
                "overwritten — reload and reapply your change."
            )
        cleaned = _safe_fields(value)
        cleaned["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        preferences = WorkspacePreferences.from_dict(cleaned)
        _atomic_json(self.preferences_path, asdict(preferences))
        return preferences

    def reset_preferences(self) -> WorkspacePreferences:
        self.preferences_path.unlink(missing_ok=True)
        return WorkspacePreferences()

    def drafts(self) -> dict[str, dict[str, Any]]:
        if not self.drafts_path.is_file():
            return {}
        raw = json.loads(self.drafts_path.read_text(encoding="utf-8"))
        drafts = raw.get("drafts") if isinstance(raw, dict) else None
        return dict(drafts) if isinstance(drafts, dict) else {}

    def save_draft(self, draft_id: str | None, fields: Mapping[str, Any]) -> str:
        cleaned = _safe_fields(fields)
        identifier = (draft_id or f"draft-{uuid4().hex[:12]}").strip()
        cleaned["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        drafts = self.drafts()
        # updated_at has second precision; the monotonic sequence breaks
        # ties so "most recently saved" is always well-defined (the
        # resume picker sorts by it). Existing drafts without one are
        # older than any draft that has one.
        cleaned["sequence"] = 1 + max(
            (
                int(value.get("sequence") or 0)
                for value in drafts.values()
                if isinstance(value, dict)
            ),
            default=0,
        )
        drafts[identifier] = cleaned
        _atomic_json(self.drafts_path, {"schema_version": "1.0.0", "drafts": drafts})
        return identifier

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        value = self.drafts().get(draft_id)
        return dict(value) if isinstance(value, dict) else None

    def delete_draft(self, draft_id: str) -> bool:
        drafts = self.drafts()
        removed = drafts.pop(draft_id, None) is not None
        if removed:
            _atomic_json(self.drafts_path, {"schema_version": "1.0.0", "drafts": drafts})
        return removed
