"""One fail-closed policy for every user-controlled redirect target."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote, urlsplit


_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")


def safe_redirect_target(target: object, fallback: str = "/") -> str:
    """Return an application-relative target or the trusted fallback.

    Query strings and fragments are preserved.  Absolute/protocol-relative
    URLs, encoded path bypasses, backslashes, controls and malformed percent
    escapes fail closed.  The fallback is code-owned and must itself be an
    application path.
    """

    candidate = str(target or "")
    if not _valid(candidate):
        return fallback if _valid(fallback) else "/"
    return candidate


def _valid(candidate: str) -> bool:
    if (
        not candidate
        or candidate != candidate.strip()
        or not candidate.startswith("/")
        or candidate.startswith("//")
    ):
        return False
    if _BAD_PERCENT.search(candidate) or _has_forbidden_character(candidate):
        return False
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return False
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return False

    # Decode repeatedly because %252f%252fevil becomes //evil after two
    # browser/proxy decoding layers.  Only the path is considered: an encoded
    # URL in a legitimate search query is data, not a navigation authority.
    path = parsed.path
    for _ in range(3):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    if not path.startswith("/") or path.startswith("//"):
        return False
    if _has_forbidden_character(path):
        return False
    try:
        decoded_parsed = urlsplit(path)
    except ValueError:
        return False
    return not decoded_parsed.scheme and not decoded_parsed.netloc


def _has_forbidden_character(value: str) -> bool:
    return "\\" in value or any(
        unicodedata.category(character).startswith("C") for character in value
    )
