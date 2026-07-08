"""Section-aware configuration diffing with secret masking.

Cisco-style configurations parse into top-level sections (an unindented
line plus its indented children); global one-liners are sections of one
line. Comparing section-by-section keeps every detected change attached to
the construct it belongs to, which is what makes classification meaningful.

Lines containing sensitive terms are masked here, at extraction time, so no
downstream model, report, or console output ever holds a secret value.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


SENSITIVE_TERMS = ("password", "secret", "key", "community", "token", "credential")
_SENSITIVE_PATTERN = re.compile(
    r"\b(" + "|".join(SENSITIVE_TERMS) + r")\b", re.IGNORECASE
)

SECTION_ADDED = "added"
SECTION_REMOVED = "removed"
SECTION_MODIFIED = "modified"


@dataclass(frozen=True)
class SectionDiff:
    """One changed configuration section; line content is already masked.

    ``classification_header`` keeps the first two tokens of the original
    header for category matching only — it is never emitted in reports.
    """

    header: str
    kind: str  # added | removed | modified
    added_lines: tuple[str, ...]
    removed_lines: tuple[str, ...]
    classification_header: str = ""


def mask_line(line: str) -> str:
    """Replace any line containing a sensitive term; over-masking is fine."""

    match = _SENSITIVE_PATTERN.search(line)
    if match is None:
        return line
    indent = line[: len(line) - len(line.lstrip())]
    return f"{indent}<masked: line contains '{match.group(1).lower()}'>"


def parse_sections(text: str) -> dict[str, tuple[str, ...]]:
    """Top-level line -> (header + indented children). Separators skipped."""

    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip() == "!":
            current = None
            continue
        if line.startswith((" ", "\t")):
            if current is not None:
                current.append(line)
            continue
        current = sections.setdefault(line, [line])
    return {header: tuple(lines) for header, lines in sections.items()}


def diff_sections(previous_text: str, current_text: str) -> tuple[SectionDiff, ...]:
    """Deterministic section-level differences, masked, sorted by header."""

    previous = parse_sections(previous_text)
    current = parse_sections(current_text)
    diffs: list[SectionDiff] = []
    for header in sorted(set(previous) | set(current), key=str.casefold):
        before = previous.get(header)
        after = current.get(header)
        if before == after:
            continue
        hint = " ".join(header.split()[:2]).casefold()
        if before is None:
            diffs.append(
                SectionDiff(
                    header=mask_line(header),
                    kind=SECTION_ADDED,
                    added_lines=_masked(after or ()),
                    removed_lines=(),
                    classification_header=hint,
                )
            )
        elif after is None:
            diffs.append(
                SectionDiff(
                    header=mask_line(header),
                    kind=SECTION_REMOVED,
                    added_lines=(),
                    removed_lines=_masked(before),
                    classification_header=hint,
                )
            )
        else:
            before_set = set(before)
            after_set = set(after)
            diffs.append(
                SectionDiff(
                    header=mask_line(header),
                    kind=SECTION_MODIFIED,
                    added_lines=_masked(
                        line for line in after if line not in before_set
                    ),
                    removed_lines=_masked(
                        line for line in before if line not in after_set
                    ),
                    classification_header=hint,
                )
            )
    return tuple(diffs)


def _masked(lines) -> tuple[str, ...]:
    return tuple(mask_line(line) for line in lines)
