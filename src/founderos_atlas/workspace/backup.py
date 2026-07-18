"""The workspace backup contract: an explicit, reviewed manifest.

A backup is built from a NAMED list of files with a stated
classification each — never from "every JSON under the directory".
An unknown future file is excluded until someone consciously adds it
here with a classification, so a new secret store can never leak into
backups by default.

Classifications:

- ``operational-metadata`` — profiles, sites, overrides, policy
  records, incidents, notifications, audit trails, preferences,
  drafts. References and metadata only; no secret values by design.
- ``sensitive-included`` — records deliberately included although an
  attacker would value them: ``users.json`` carries scrypt password
  hashes (needed to restore accounts; hashes are built to resist
  offline attack, and the backup consumer must still protect the
  archive).

Always excluded:

- **secrets**: ``credentials.enc.json`` (the sealed credential store)
  and any other credential material — a backup must never contain a
  secret store, encrypted or not; the OS keyring is likewise never
  touched.
- **session material**: ``sessions.json`` — restoring it would
  resurrect revoked access.
- **temporary files**: ``.*.writing`` / ``*.restoring`` staging files.
- **raw evidence**: lives under the output tree and is intentionally a
  separate, explicit export (evidence bundles), never bundled into a
  metadata backup.
- **migration backups**: point-in-time duplicates; included only when
  deliberately requested.

Every archive carries ``backup-manifest.json``: schema version, file
names, sizes, SHA-256 hashes, classifications, creation time, and the
application version — machine-verifiable at restore time.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKUP_SCHEMA_VERSION = "1.0.0"
MANIFEST_NAME = "backup-manifest.json"
NOTICE_NAME = "BACKUP-NOTICE.txt"

OPERATIONAL_METADATA = "operational-metadata"
SENSITIVE_INCLUDED = "sensitive-included"

# The reviewed manifest: name -> classification. THIS is the backup.
INCLUDED_FILES: dict[str, str] = {
    "profiles.json": OPERATIONAL_METADATA,
    "credential_sets.json": OPERATIONAL_METADATA,   # references, no secrets
    "credential_memory.json": OPERATIONAL_METADATA,
    "preferences.json": OPERATIONAL_METADATA,
    "discovery_drafts.json": OPERATIONAL_METADATA,
    "sites.json": OPERATIONAL_METADATA,
    "site-overrides.json": OPERATIONAL_METADATA,
    "site-overrides.audit.jsonl": OPERATIONAL_METADATA,
    "identity-resolutions.json": OPERATIONAL_METADATA,
    "identity-resolutions.audit.jsonl": OPERATIONAL_METADATA,
    "policy-exceptions.json": OPERATIONAL_METADATA,
    "policy-trend.json": OPERATIONAL_METADATA,
    "annotations.json": OPERATIONAL_METADATA,
    "incidents.json": OPERATIONAL_METADATA,
    "notifications.jsonl": OPERATIONAL_METADATA,
    "audit.jsonl": OPERATIONAL_METADATA,
    "users.json": SENSITIVE_INCLUDED,               # scrypt hashes
    "workspace-schema.json": OPERATIONAL_METADATA,
}

EXCLUDED_SECRETS = ("credentials.enc.json",)
EXCLUDED_SESSIONS = ("sessions.json",)
EXCLUDED_REASONS = {
    "secrets": "a backup must never contain a credential store",
    "sessions": "restoring session tokens would resurrect revoked access",
    "temporary": "in-flight staging files are not state",
    "raw-evidence": "evidence is a separate, explicit export",
    "migration-backups": "point-in-time duplicates, on request only",
    "unknown": "files not in the reviewed manifest are excluded by default",
}


def build_manifest(
    workspace_root: str | Path, *, application_version: str | None = None,
) -> dict[str, Any]:
    from founderos_atlas.release import DISPLAY_VERSION

    root = Path(workspace_root)
    files = []
    for name, classification in sorted(INCLUDED_FILES.items()):
        path = root / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        files.append({
            "name": name,
            "classification": classification,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return {
        "backup_schema_version": BACKUP_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "application_version": application_version or DISPLAY_VERSION,
        "files": files,
        "excluded": {
            "secrets": list(EXCLUDED_SECRETS),
            "sessions": list(EXCLUDED_SESSIONS),
            "reasons": EXCLUDED_REASONS,
        },
    }


def build_backup(
    workspace_root: str | Path, *, application_version: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """The backup archive bytes and its manifest."""

    root = Path(workspace_root)
    manifest = build_manifest(
        root, application_version=application_version
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in manifest["files"]:
            archive.write(root / entry["name"], entry["name"])
        archive.writestr(
            MANIFEST_NAME,
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        archive.writestr(NOTICE_NAME, (
            "Atlas metadata backup.\n"
            "Included: the reviewed operational metadata named in "
            "backup-manifest.json (users.json carries password HASHES — "
            "protect this archive accordingly).\n"
            "Never included: credential stores (encrypted or otherwise), "
            "OS-keyring secrets, session tokens, temporary files, raw "
            "network evidence.\n"
        ))
    return buffer.getvalue(), manifest
