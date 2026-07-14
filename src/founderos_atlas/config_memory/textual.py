"""Side-by-side text difference for configuration versions (PR-044, Part 5).

Line-level added / removed / unchanged, suitable for a side-by-side view.
Built on Python's deterministic ``difflib`` so the same pair of versions
always renders the same diff.

**Every emitted line is masked** through the existing
``config_intelligence.mask_line`` before it leaves this module, so a diff
view can never surface a password, key, or community string — the same
guarantee the change-intelligence reports already make.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from founderos_atlas.config_intelligence import is_dynamic_metadata, mask_line


LINE_EQUAL = "equal"
LINE_ADDED = "added"
LINE_REMOVED = "removed"


@dataclass(frozen=True)
class DiffLine:
    """One rendered line of a side-by-side comparison (already masked)."""

    kind: str                     # equal | added | removed
    previous_number: int | None
    current_number: int | None
    previous_text: str | None
    current_text: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "previous_number": self.previous_number,
            "current_number": self.current_number,
            "previous_text": self.previous_text,
            "current_text": self.current_text,
        }


@dataclass(frozen=True)
class TextDiff:
    """A full side-by-side comparison plus honest counts."""

    lines: tuple[DiffLine, ...]
    added: int
    removed: int

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "removed": self.removed,
            "changed": self.changed,
            "lines": [line.to_dict() for line in self.lines],
        }


@dataclass(frozen=True)
class ConfigLine:
    """One rendered line of a configuration (already masked)."""

    number: int
    text: str
    masked: bool

    def to_dict(self) -> dict[str, Any]:
        return {"number": self.number, "text": self.text, "masked": self.masked}


@dataclass(frozen=True)
class ConfigView:
    """A whole configuration, rendered safely for the screen."""

    lines: tuple[ConfigLine, ...]
    masked_count: int

    @property
    def line_count(self) -> int:
        return len(self.lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lines": [line.to_dict() for line in self.lines],
            "line_count": self.line_count,
            "masked_count": self.masked_count,
        }


def config_view(text: str) -> ConfigView:
    """A configuration prepared for display — **every line masked**.

    Reading a remembered configuration is the point of remembering it, so
    the GUI must be able to show one. It shows this: the operator's own
    line numbers, with any line carrying a password, key, or community
    string replaced. Export remains the one path that serves raw text.

    Line numbers are the real ones — dynamic metadata is kept here (unlike
    the diff, which filters it) because this view claims to be the
    configuration, not a summary of what changed in it.
    """

    lines: list[ConfigLine] = []
    masked_count = 0
    for index, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.rstrip()
        rendered = mask_line(stripped)
        was_masked = rendered != stripped
        if was_masked:
            masked_count += 1
        lines.append(ConfigLine(number=index, text=rendered, masked=was_masked))
    return ConfigView(lines=tuple(lines), masked_count=masked_count)


def _prepare(text: str, *, ignore_dynamic: bool) -> list[str]:
    lines = [raw.rstrip() for raw in text.splitlines()]
    if ignore_dynamic:
        # Device-generated noise (byte counts, save timestamps) is not a
        # configuration change — the same rule the section diff applies.
        lines = [line for line in lines if not is_dynamic_metadata(line)]
    return lines


def text_diff(
    previous_config: str,
    current_config: str,
    *,
    ignore_dynamic_metadata: bool = True,
    context_lines: int | None = None,
) -> TextDiff:
    """Deterministic, masked, side-by-side line diff of two versions.

    ``context_lines`` (when set) keeps only that many unchanged lines
    around each change — useful for a compact view of a large config.
    """

    if not isinstance(previous_config, str) or not isinstance(current_config, str):
        raise TypeError("configurations must be text")

    before = _prepare(previous_config, ignore_dynamic=ignore_dynamic_metadata)
    after = _prepare(current_config, ignore_dynamic=ignore_dynamic_metadata)

    lines: list[DiffLine] = []
    added = removed = 0
    matcher = SequenceMatcher(a=before, b=after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                text = before[i1 + offset]
                lines.append(
                    DiffLine(
                        kind=LINE_EQUAL,
                        previous_number=i1 + offset + 1,
                        current_number=j1 + offset + 1,
                        previous_text=mask_line(text),
                        current_text=mask_line(text),
                    )
                )
            continue
        if tag in ("replace", "delete"):
            for offset in range(i2 - i1):
                removed += 1
                lines.append(
                    DiffLine(
                        kind=LINE_REMOVED,
                        previous_number=i1 + offset + 1,
                        current_number=None,
                        previous_text=mask_line(before[i1 + offset]),
                        current_text=None,
                    )
                )
        if tag in ("replace", "insert"):
            for offset in range(j2 - j1):
                added += 1
                lines.append(
                    DiffLine(
                        kind=LINE_ADDED,
                        previous_number=None,
                        current_number=j1 + offset + 1,
                        previous_text=None,
                        current_text=mask_line(after[j1 + offset]),
                    )
                )

    rendered = tuple(lines)
    if context_lines is not None:
        rendered = _trim_context(rendered, context_lines)
    return TextDiff(lines=rendered, added=added, removed=removed)


def _trim_context(lines: tuple[DiffLine, ...], context: int) -> tuple[DiffLine, ...]:
    """Keep changed lines plus ``context`` unchanged lines around each."""

    keep: set[int] = set()
    for index, line in enumerate(lines):
        if line.kind == LINE_EQUAL:
            continue
        low = max(0, index - context)
        high = min(len(lines), index + context + 1)
        keep.update(range(low, high))
    return tuple(lines[index] for index in sorted(keep))
