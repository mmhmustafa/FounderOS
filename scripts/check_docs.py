"""Validate UTF-8 text and local links in active Markdown documentation."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git", ".venv", ".atlas", ".tmp-tests", "deliverables", "_zip",
    "historical", "handoffs", "reviews", "strategy",
}
TEXT_SUFFIXES = {".md", ".py", ".html", ".toml", ".txt", ".json", ".yml", ".yaml"}
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
MOJIBAKE = (
    chr(0xFFFD),
    chr(0xE2),  # typical UTF-8 punctuation decoded as Windows-1252
    chr(0xC2),  # typical UTF-8 spacing/symbol prefix decoded as Windows-1252
)


def main() -> int:
    failures: list[str] = []
    markdown: list[tuple[Path, str]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(ROOT)
        if path.resolve() == Path(__file__).resolve():
            continue
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except UnicodeError as error:
            failures.append(f"ENCODING {relative}: {error}")
            continue
        for marker in MOJIBAKE:
            if marker in text:
                failures.append(f"MOJIBAKE {relative}: {marker!r}")
        if path.suffix.casefold() == ".md":
            markdown.append((path, text))

    for path, text in markdown:
        for raw in LINK.findall(text):
            target = raw.strip().split(maxsplit=1)[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not local:
                continue
            destination = (path.parent / local).resolve()
            if not destination.exists():
                failures.append(
                    f"BROKEN LINK {path.relative_to(ROOT)} -> {target}"
                )
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Documentation check passed: {len(markdown)} Markdown files; UTF-8 clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
