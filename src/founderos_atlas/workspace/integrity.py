"""Workspace corruption detection.

Scans the known Atlas metadata files (JSON and JSONL) and reports,
per file: ok, missing (a state, not an error), or corrupt — with a
human explanation and the recovery step (restore from a metadata
backup, or delete the file to rebuild derived state). The scan never
repairs silently: recovery is an explicit, audited operator action.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Root-level workspace files Atlas owns. JSONL files are validated
# line by line; JSON files must parse whole.
KNOWN_JSON_FILES = (
    "profiles.json",
    "credential_sets.json",
    "credential_memory.json",
    "preferences.json",
    "discovery_drafts.json",
    "sites.json",
    "site-overrides.json",
    "identity-resolutions.json",
    "evidence-resolution-decisions.json",
    "policy-exceptions.json",
    "policy-trend.json",
    "policy-governance.json",
    "policy-posture.json",
    "schedules.json",
    "annotations.json",
    "incidents.json",
    "users.json",
    "sessions.json",
    "workspace-schema.json",
)
KNOWN_JSONL_FILES = (
    "audit.jsonl",
    "site-overrides.audit.jsonl",
    "identity-resolutions.audit.jsonl",
    "evidence-resolution-decisions.audit.jsonl",
    "notifications.jsonl",
    "notification-outbox.jsonl",
    "telemetry.jsonl",
)


@dataclass(frozen=True)
class FileStatus:
    name: str
    state: str          # ok | missing | corrupt
    detail: str = ""


def _check_json(path: Path) -> FileStatus:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "schedules.json":
            from founderos_atlas.scheduling import validate_schedule_catalog

            validate_schedule_catalog(value)
        return FileStatus(name=path.name, state="ok")
    except (KeyError, OSError, TypeError, ValueError) as error:
        return FileStatus(
            name=path.name, state="corrupt",
            detail=f"{type(error).__name__}: the file is not valid Atlas metadata. "
                   "Restore it from a metadata backup, or remove it to "
                   "start that record fresh.",
        )


def _check_jsonl(path: Path) -> FileStatus:
    bad_lines = 0
    total = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            total += 1
            try:
                json.loads(line)
            except ValueError:
                bad_lines += 1
    except OSError as error:
        return FileStatus(
            name=path.name, state="corrupt",
            detail=f"{type(error).__name__}: the file could not be read.",
        )
    if bad_lines:
        return FileStatus(
            name=path.name, state="corrupt",
            detail=f"{bad_lines} of {total} lines do not parse. Readers "
                   "skip bad lines, so the rest of the record remains "
                   "usable; restore from a backup to recover the lost lines.",
        )
    return FileStatus(name=path.name, state="ok")


def verify_workspace(workspace_root: str | Path) -> list[FileStatus]:
    root = Path(workspace_root)
    results: list[FileStatus] = []
    for name in KNOWN_JSON_FILES:
        path = root / name
        results.append(
            _check_json(path) if path.is_file()
            else FileStatus(name=name, state="missing")
        )
    for name in KNOWN_JSONL_FILES:
        path = root / name
        results.append(
            _check_jsonl(path) if path.is_file()
            else FileStatus(name=name, state="missing")
        )
    return results
