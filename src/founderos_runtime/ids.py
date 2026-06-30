"""Canonical IDs and timestamps using only the Python standard library."""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_PREFIXES = {
    "agent": "agt",
    "artifact": "art",
    "workflow": "wfl",
    "state": "sta",
    "decision": "dec",
    "project": "prj",
    "workflow_run": "wfr",
    "agent_run": "agr",
    "transition": "trn",
    "evaluation": "evl",
    "approval": "apr",
    "event": "evt",
}


def _encode_ulid(value: int) -> str:
    characters = ["0"] * 26
    for index in range(25, -1, -1):
        characters[index] = _ALPHABET[value & 31]
        value >>= 5
    return "".join(characters)


def new_id(kind: str) -> str:
    """Create a canonical type-prefixed ULID for a supported entity kind."""

    try:
        prefix = _PREFIXES[kind]
    except KeyError as error:
        raise ValueError(f"Unsupported entity kind: {kind}") from error
    timestamp_ms = int(time.time() * 1000)
    value = (timestamp_ms << 80) | secrets.randbits(80)
    return f"{prefix}_{_encode_ulid(value)}"


def utc_now() -> str:
    """Return an RFC 3339 UTC timestamp normalized to a trailing Z."""

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def reference(kind: str, record: dict, *, include_version: bool = False, include_revision: bool = False) -> dict:
    """Build a typed reference from a canonical record."""

    result = {"kind": kind, "id": record["id"]}
    if include_version and "version" in record:
        result["version"] = record["version"]
    if include_revision and "revision" in record:
        result["revision"] = record["revision"]
    return result
