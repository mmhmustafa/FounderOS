"""Transactional metadata restore: validate → stage → snapshot → commit.

Nothing live changes until EVERY archive member has been fully
validated (names, sizes, compression ratios, JSON/JSONL structure,
schema compatibility, manifest hashes). Validated files are staged
beside the workspace, the current state is snapshotted, and the commit
replaces files one atomic rename at a time — any failure rolls every
already-committed file back from the snapshot, so a restore either
happens completely or not at all.

Sessions are never restorable (revoked access must stay revoked), and
no external credential store is read or written.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from .backup import INCLUDED_FILES, MANIFEST_NAME, NOTICE_NAME

MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_MEMBER_BYTES = 24 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 128 * 1024 * 1024
MAX_MEMBERS = 64
MAX_COMPRESSION_RATIO = 200          # zip-bomb guard

SNAPSHOT_DIRNAME = "pre-restore-snapshots"


class RestoreError(ValueError):
    """A restore refused safely — nothing live was modified (or, when
    raised during commit, everything was rolled back)."""


@dataclass
class RestoreResult:
    restored: list[str] = field(default_factory=list)
    snapshot_dir: str | None = None
    verified: bool = False


def _validate_member_name(name: str, seen: set[str]) -> None:
    if name in (MANIFEST_NAME, NOTICE_NAME):
        return
    if "/" in name or "\\" in name or name.startswith(".") or ".." in name:
        raise RestoreError(
            f"The archive member {name!r} is not a plain workspace "
            "filename — path traversal is refused."
        )
    if name in seen:
        raise RestoreError(f"The archive lists {name!r} twice.")
    if name not in INCLUDED_FILES:
        raise RestoreError(
            f"The archive contains {name!r}, which is not restorable "
            "Atlas metadata. Sessions, credential stores, and unknown "
            "files are never restored."
        )


def _validate_structure(name: str, data: bytes) -> None:
    text = data.decode("utf-8")     # UnicodeDecodeError => corrupt
    if name.endswith(".jsonl"):
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip():
                json.loads(line)
        return
    json.loads(text)


def _validate_schema(members: dict[str, bytes]) -> None:
    from .migrations import CURRENT_SCHEMA_VERSION

    raw = members.get("workspace-schema.json")
    if raw is None:
        return          # legacy backups predate the marker: migratable
    version = int(json.loads(raw.decode("utf-8")).get("version", 0))
    if version > CURRENT_SCHEMA_VERSION:
        raise RestoreError(
            f"The backup carries workspace schema v{version}, newer than "
            f"this application understands (v{CURRENT_SCHEMA_VERSION}). "
            "Restore it on a matching or newer Atlas version."
        )


def _verify_manifest(members: dict[str, bytes]) -> None:
    raw = members.get(MANIFEST_NAME)
    if raw is None:
        return          # manifests appeared with the backup contract
    manifest = json.loads(raw.decode("utf-8"))
    for entry in manifest.get("files") or ():
        name = str(entry.get("name"))
        if name not in members:
            raise RestoreError(
                f"The manifest names {name!r} but the archive lacks it."
            )
        digest = sha256(members[name]).hexdigest()
        if digest != entry.get("sha256"):
            raise RestoreError(
                f"The archive member {name!r} does not match its "
                "manifest hash — the backup is damaged or altered."
            )


def perform_restore(
    workspace_root: str | Path,
    archive_bytes: bytes,
    *,
    commit_hook=None,
) -> RestoreResult:
    """Restore an Atlas metadata backup transactionally.

    ``commit_hook(name)`` is called before each file is committed —
    tests inject failures there to prove the rollback.
    """

    root = Path(workspace_root)
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise RestoreError(
            "The upload exceeds the restore size limit "
            f"({MAX_ARCHIVE_BYTES // (1024 * 1024)} MB)."
        )

    # ---- phase 1: open and validate every member, touching nothing ----
    try:
        archive = zipfile.ZipFile(__import__("io").BytesIO(archive_bytes))
    except zipfile.BadZipFile as error:
        raise RestoreError("The upload is not a readable ZIP archive.") from error

    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > MAX_MEMBERS:
        raise RestoreError(
            f"The archive lists {len(infos)} members; the limit is "
            f"{MAX_MEMBERS}."
        )
    seen: set[str] = set()
    total_uncompressed = 0
    for info in infos:
        _validate_member_name(info.filename, seen)
        seen.add(info.filename)
        total_uncompressed += info.file_size
        if info.file_size > MAX_MEMBER_BYTES:
            raise RestoreError(
                f"The member {info.filename!r} declares "
                f"{info.file_size} bytes, over the per-file limit."
            )
        compressed = max(info.compress_size, 1)
        if info.file_size / compressed > MAX_COMPRESSION_RATIO:
            raise RestoreError(
                f"The member {info.filename!r} has an implausible "
                "compression ratio — refusing a possible decompression "
                "bomb."
            )
    if total_uncompressed > MAX_TOTAL_UNCOMPRESSED:
        raise RestoreError(
            "The archive would decompress beyond the total size limit."
        )

    members: dict[str, bytes] = {}
    for info in infos:
        data = archive.read(info)   # sizes already bounded above
        if len(data) != info.file_size:
            raise RestoreError(
                f"The member {info.filename!r} lied about its size."
            )
        members[info.filename] = data

    restorable = {
        name: data for name, data in members.items()
        if name not in (MANIFEST_NAME, NOTICE_NAME)
    }
    if not restorable:
        raise RestoreError(
            "The archive contains no restorable Atlas metadata."
        )
    for name, data in restorable.items():
        try:
            _validate_structure(name, data)
        except (ValueError, UnicodeDecodeError) as error:
            raise RestoreError(
                f"The member {name!r} does not parse as valid "
                f"{'JSONL' if name.endswith('.jsonl') else 'JSON'} — "
                "nothing was restored."
            ) from error
    _validate_schema(members)
    _verify_manifest(members)

    # ---- phase 2: stage everything beside the workspace ---------------
    root.mkdir(parents=True, exist_ok=True)
    stage = root / f".restore-stage-{uuid4().hex}"
    stage.mkdir()
    result = RestoreResult()
    try:
        for name, data in restorable.items():
            (stage / name).write_bytes(data)

        # ---- phase 3: pre-restore recovery snapshot -------------------
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot = root / SNAPSHOT_DIRNAME / f"{stamp}-{uuid4().hex[:6]}"
        snapshot.mkdir(parents=True)
        for name in restorable:
            live = root / name
            if live.is_file():
                shutil.copy2(live, snapshot / name)
        result.snapshot_dir = str(snapshot)

        # ---- phase 4: atomic-per-file commit with full rollback -------
        committed: list[str] = []
        try:
            for name in sorted(restorable):
                if commit_hook is not None:
                    commit_hook(name)
                (stage / name).replace(root / name)
                committed.append(name)
        except Exception as error:
            for name in committed:
                saved = snapshot / name
                if saved.is_file():
                    shutil.copy2(saved, root / name)
                else:
                    (root / name).unlink(missing_ok=True)
            raise RestoreError(
                "The restore failed while committing and was fully "
                "rolled back — the workspace is unchanged. "
                f"(Snapshot retained at {snapshot.name}.)"
            ) from error
        result.restored = committed

        # ---- phase 5: verify what was just written --------------------
        from .integrity import verify_workspace

        corrupt = [
            status.name for status in verify_workspace(root)
            if status.state == "corrupt" and status.name in restorable
        ]
        if corrupt:      # defense in depth; phase-1 validation parses first
            raise RestoreError(
                "Post-restore integrity found problems in: "
                + ", ".join(corrupt)
            )
        result.verified = True
        return result
    finally:
        shutil.rmtree(stage, ignore_errors=True)
