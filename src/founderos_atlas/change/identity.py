"""Change annotation identity (PR-178.2A).

A change's annotation identity is THE OBSERVATION POINT THAT REPORTED
IT plus THE EXACT DIFFERENCE IT REPORTED:

    change:v2:<scope_id>:<content-hash>

``scope_id`` is the stable profile/scope identifier (never the display
label — renaming "Hyderabad" to "Hyderabad Production" keeps the id and
therefore every annotation). The content hash uses exactly the original
fingerprint basis, so the durability property is unchanged: the same
delta rediscovered later keeps its acknowledgement, owner, suppression
and note.

Before PR-178.2A the subject was the content hash alone
(``change:<hash>``), which made the identical delta in two independent
networks ONE annotatable record — acknowledging it in Hyderabad silently
acknowledged it in Secunderabad (measured; see the architecture review).
Those unscoped subjects survive as READ-ONLY legacy records:
``resolve_annotation`` is the one canonical implementation of the
precedence rule (scoped record wins; legacy record is a display
fallback that is never written through), and the v3 workspace migration
converges unambiguous legacy records onto their scoped key.

This module is pure functions over plain data — no I/O, no Flask.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any


# The v1 basis, verbatim. Deliberately EXCLUDES the scope (that is the
# v2 prefix's job), the network display label, run ids and timestamps —
# identity must survive rediscovery and renames, and must never depend
# on presentation.
_CONTENT_KEYS = (
    "kind", "category", "device", "field", "before", "after", "description",
)

_V1_PREFIX = "change:"
_V2_PREFIX = "change:v2:"


def content_hash(row: Mapping[str, Any]) -> str:
    """The 20-hex content digest both subject versions share."""

    basis = "|".join(str(row.get(key) or "") for key in _CONTENT_KEYS)
    return sha256(basis.encode("utf-8")).hexdigest()[:20]


def subject_v1(row: Mapping[str, Any]) -> str:
    """The pre-isolation, scope-blind subject (legacy; read-only)."""

    return _V1_PREFIX + content_hash(row)


def subject_v2_for_hash(scope_id: str, digest: str) -> str:
    """The scoped subject for an already-computed content hash."""

    scope = str(scope_id or "").strip()
    if not scope:
        raise ValueError("a v2 change subject requires a stable scope_id")
    return f"{_V2_PREFIX}{scope}:{digest}"


def subject_v2(row: Mapping[str, Any], scope_id: str) -> str:
    """The canonical scoped subject for one change row."""

    return subject_v2_for_hash(scope_id, content_hash(row))


def parse_v2(subject: str) -> tuple[str, str] | None:
    """``(scope_id, content_hash)`` for a v2 subject, else None.

    The ONE place that knows the subject layout. Neither component may
    be empty; scope ids are slugs and hashes are hex, so the single
    remaining colon is unambiguous.
    """

    text = str(subject or "")
    if not text.startswith(_V2_PREFIX):
        return None
    remainder = text[len(_V2_PREFIX):]
    scope, separator, digest = remainder.rpartition(":")
    if not separator or not scope or not digest:
        return None
    return scope, digest


def scope_of(subject: str) -> str | None:
    """The owning scope of a v2 subject; None for legacy/foreign ids."""

    parsed = parse_v2(subject)
    return parsed[0] if parsed else None


def legacy_subject_of(subject: str) -> str | None:
    """The v1 twin of a v2 subject — the key its pre-isolation record
    would live under. None when ``subject`` is not a v2 subject."""

    parsed = parse_v2(subject)
    return _V1_PREFIX + parsed[1] if parsed else None


def resolve_annotation(
    records: Mapping[str, Mapping[str, Any]] | None,
    subject_v2: str,
    subject_v1: str | None,
) -> Mapping[str, Any] | None:
    """The canonical read precedence, implemented exactly once.

    1. The scoped v2 record wins.
    2. Absent that, the unscoped v1 record serves as a READ-ONLY legacy
       fallback, so pre-isolation operator state never disappears.
    3. Writing through the fallback is forbidden by construction: this
       function only reads, and every write path uses the v2 subject.
    """

    if not records:
        return None
    found = records.get(subject_v2)
    if found is not None:
        return found
    if subject_v1:
        return records.get(subject_v1)
    return None
