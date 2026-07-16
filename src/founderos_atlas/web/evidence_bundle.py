"""Evidence bundles (PR-047B, PROOF, Part 8).

An operator who needs to hand evidence to someone else -- a colleague, an
auditor, a vendor TAC case -- should not have to click Download once per
command. This builds a zip of what Enterprise Memory already holds.

**Masked by default.** A bundle is the easiest artefact in Atlas to forward to
someone, so the default must be the safe one: every output goes through the
same ``view_*`` masking path the GUI uses, and a manifest records that it was
masked. A raw bundle is a separate, explicit choice, is labelled as raw inside
the bundle itself, and is audited -- the operator can always get the exact
bytes, but never by accident.

Nothing here reads the network or changes storage; a bundle is a re-packaging
of records that already exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import posixpath
import re
import zipfile
from typing import Any, Callable, Iterable

from founderos_atlas.enterprise_memory import EnterpriseMemory
from founderos_atlas.enterprise_memory.models import RawEvidenceRecord


# A bundle's entry names come from device ids and command strings -- both
# operator-influenced, both containing characters a filesystem would rather not
# see ("frr:core1", "show ip route"). Zip entries are also a classic path
# traversal surface ("../../etc/passwd"), so names are built from an allowlist
# rather than by escaping what we happen to think of.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(value: str, *, fallback: str = "unnamed") -> str:
    """A filesystem- and zip-safe name for one device or command.

    Allowlist, not denylist: everything outside ``[A-Za-z0-9._-]`` becomes a
    hyphen, so a device id of ``../../etc/passwd`` cannot escape the bundle --
    it becomes ``etc-passwd``. Leading dots are stripped so no entry is hidden
    or relative.
    """

    text = _UNSAFE.sub("-", str(value or "")).strip("-._")
    return text or fallback


@dataclass(frozen=True)
class BundleFile:
    """One file inside a bundle."""

    path: str
    text: str


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_metadata(record: RawEvidenceRecord) -> dict[str, Any]:
    data = record.to_dict()
    # The content hash addresses the blob and is safe to carry; it is provenance
    # for whoever receives the bundle, not an identifier the operator navigates.
    return {
        key: data.get(key)
        for key in (
            "device_id", "hostname", "command", "source", "collected_at",
            "collection_status", "parser_version", "discovery_session",
            "content_sha256", "byte_size", "transport", "platform",
            "software_version", "platform_driver", "detail", "atlas_version",
        )
    }


def build_device_bundle(
    memory: EnterpriseMemory,
    device_id: str,
    *,
    raw: bool = False,
    session_id: str | None = None,
    clock: Callable[[], str] | None = None,
) -> bytes | None:
    """One device's evidence as a zip. Returns None when there is none."""

    records = memory.get_raw_evidence(device_id)
    if session_id:
        records = tuple(r for r in records if r.discovery_session == session_id)
    if not records:
        return None
    files, metadata = _device_files(memory, device_id, records, raw=raw)
    manifest = _manifest(
        kind="device", subject=device_id, records=records, raw=raw, clock=clock,
    )
    manifest.update(metadata)
    files.append(BundleFile("evidence-metadata.json", _json(manifest)))
    return _zip(files)


def build_session_bundle(
    memory: EnterpriseMemory,
    session_id: str,
    *,
    raw: bool = False,
    clock: Callable[[], str] | None = None,
) -> bytes | None:
    """One discovery session's evidence as a zip, one directory per device."""

    session = memory.get_discovery_session(session_id)
    all_records = [
        r for device_id in memory.device_ids()
        for r in memory.get_raw_evidence(device_id)
        if r.discovery_session == session_id
    ]
    if not all_records:
        return None

    files: list[BundleFile] = []
    by_device: dict[str, list[RawEvidenceRecord]] = {}
    for record in all_records:
        by_device.setdefault(record.device_id, []).append(record)

    used_directories: set[str] = set()
    for device_id, records in sorted(by_device.items()):
        directory = safe_name(records[0].hostname or device_id, fallback="device")
        # Two canonical devices can share a hostname (that is precisely what
        # duplicate detection exists to surface). Two directories must not
        # collide and silently interleave one device's evidence with another's.
        if directory in used_directories:
            directory = f"{directory}-{safe_name(device_id, fallback='device')}"
        used_directories.add(directory)
        device_files, metadata = _device_files(
            memory, device_id, tuple(records), raw=raw
        )
        device_files.append(
            BundleFile("evidence-metadata.json", _json(metadata))
        )
        for item in device_files:
            files.append(BundleFile(posixpath.join(directory, item.path), item.text))

    summary = _manifest(
        kind="session", subject=session_id, records=tuple(all_records), raw=raw,
        clock=clock,
    )
    if session is not None:
        summary["session"] = session.to_dict()
    summary["devices"] = sorted(by_device)
    files.append(BundleFile("session-summary.json", _json(summary)))
    return _zip(files)


def _device_files(
    memory: EnterpriseMemory,
    device_id: str,
    records: Iterable[RawEvidenceRecord],
    *,
    raw: bool,
) -> tuple[list[BundleFile], dict[str, Any]]:
    """This device's output files, and the metadata describing them.

    The caller writes the metadata: a device bundle merges it into the
    top-level manifest, a session bundle writes one per device directory.
    """

    files: list[BundleFile] = []
    metadata: list[dict[str, Any]] = []
    used: set[str] = set()

    for record in records:
        entry = _record_metadata(record)
        if not record.content_sha256:
            # A command that returned nothing has no file -- but it still
            # appears in the metadata. Omitting it entirely would let a reader
            # conclude Atlas never ran it.
            entry["output_file"] = None
            metadata.append(entry)
            continue

        text = (
            memory.download_evidence(record.content_sha256)
            if raw
            else memory.view_evidence(record).text
        )
        if text is None:
            entry["output_file"] = None
            metadata.append(entry)
            continue

        name = safe_name(record.command, fallback="command")
        candidate = f"{name}.txt"
        # Two commands can normalize to one name ("show run" / "show-run").
        # Disambiguate by content address rather than dropping one silently.
        if candidate in used:
            candidate = f"{name}-{record.content_sha256[:8]}.txt"
        used.add(candidate)
        entry["output_file"] = candidate
        entry["masked"] = not raw
        metadata.append(entry)
        files.append(BundleFile(candidate, text))

    return files, {
        "device_id": device_id,
        "masked": not raw,
        "records": metadata,
    }


def _manifest(
    *,
    kind: str,
    subject: str,
    records: tuple[RawEvidenceRecord, ...],
    raw: bool,
    clock: Callable[[], str] | None,
) -> dict[str, Any]:
    now = (clock or _timestamp)()
    return {
        "bundle_kind": kind,
        "subject": subject,
        "generated_at": now,
        "record_count": len(records),
        "masked": not raw,
        # Said plainly, inside the artefact, because the artefact outlives the
        # click that produced it and travels away from the operator who knows.
        "disclosure": (
            "RAW EXPORT -- outputs are unmasked and may contain secrets."
            if raw else
            "Outputs are masked: any line containing a secret is redacted."
        ),
    }


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


def _zip(files: Iterable[BundleFile]) -> bytes:
    buffer = io.BytesIO()
    # Deterministic: a fixed member timestamp so the same evidence bundles to
    # the same bytes. Two exports of unchanged evidence should be comparable,
    # and Atlas's outputs are reproducible everywhere else (PR-045's
    # _deterministic_gzip made the same choice for the blob store).
    fixed = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(files, key=lambda f: f.path):
            info = zipfile.ZipInfo(filename=item.path, date_time=fixed)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, item.text)
    return buffer.getvalue()
