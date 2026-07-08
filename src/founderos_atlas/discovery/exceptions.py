"""Typed Atlas discovery failures."""

from __future__ import annotations

import re


_PREVIEW_LIMIT = 300
_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|secret|community|passphrase|key)\b\s+\S+"
)
_CONTROL_CHARS = re.compile(r"[^\x20-\x7e\n\t]")


def sanitize_output_preview(text: str, limit: int = _PREVIEW_LIMIT) -> str:
    """Return a short, secret-free preview of raw device output."""

    if not isinstance(text, str) or not text.strip():
        return "<empty output>"
    redacted = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)} <redacted>", text)
    printable = _CONTROL_CHARS.sub("", redacted).strip()
    if len(printable) <= limit:
        return printable
    return printable[: limit - 3] + "..."


class AtlasDiscoveryError(Exception):
    """Base failure for deterministic Atlas discovery."""


class MissingCommandOutputError(AtlasDiscoveryError):
    """A required fixture command output was absent or empty."""


class UnsupportedAdapterError(AtlasDiscoveryError):
    """The supplied adapter does not implement the Atlas adapter contract."""


class DiscoveryParseError(AtlasDiscoveryError):
    """Raw command text could not be normalized into required facts.

    Optionally carries structured diagnostics (adapter, command, field, and a
    sanitized output preview) so real-device parse failures are actionable.
    """

    def __init__(
        self,
        message: str,
        *,
        adapter: str | None = None,
        command: str | None = None,
        field: str | None = None,
        raw_output: str | None = None,
    ) -> None:
        self.adapter = adapter
        self.command = command
        self.field = field
        self.output_preview = (
            sanitize_output_preview(raw_output) if raw_output is not None else None
        )
        parts = [message]
        if adapter:
            parts.append(f"adapter: {adapter}")
        if command:
            parts.append(f"command: {command}")
        if field:
            parts.append(f"missing field: {field}")
        if self.output_preview is not None:
            parts.append(f"output preview: {self.output_preview}")
        if adapter or command or field:
            parts.append(
                "The device output may not match this parser yet. Capture the "
                "full command output and extend the adapter to support it."
            )
        super().__init__(" | ".join(parts))
