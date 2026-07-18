"""Fail on every unapproved or expired dependency vulnerability."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
EXCEPTIONS = ROOT / "security" / "vulnerability-exceptions.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, help="Use saved pip-audit JSON")
    args = parser.parse_args()
    if args.input:
        report = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        command = [
            sys.executable, "-m", "pip_audit",
            "--requirement", str(ROOT / "constraints.txt"),
            "--no-deps", "--disable-pip", "--format", "json",
            "--cache-dir", str(ROOT / ".audit-cache"),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if not result.stdout.strip():
            sys.stderr.write(result.stderr)
            return 2
        report = json.loads(result.stdout)

    approved = _approved_exceptions()
    findings: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for dependency in report.get("dependencies", []):
        package = str(dependency.get("name") or "").casefold()
        version = str(dependency.get("version") or "")
        for vulnerability in dependency.get("vulns", []):
            key = (package, version, str(vulnerability.get("id") or ""))
            if key in seen:
                continue
            seen.add(key)
            exception = approved.get(key)
            if exception is None:
                findings.append(f"UNAPPROVED {package} {version} {key[2]}")
            elif date.fromisoformat(exception["expires"]) < date.today():
                findings.append(
                    f"EXPIRED {package} {version} {key[2]} "
                    f"({exception['expires']})"
                )
            else:
                print(
                    f"APPROVED UNTIL {exception['expires']}: "
                    f"{package} {version} {key[2]}"
                )
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print(f"Dependency audit passed: {len(seen)} finding(s), all approved and current.")
    return 0


def _approved_exceptions() -> dict[tuple[str, str, str], dict]:
    payload = json.loads(EXCEPTIONS.read_text(encoding="utf-8"))
    values: dict[tuple[str, str, str], dict] = {}
    for item in payload.get("exceptions", []):
        identifiers = [item["id"], *item.get("aliases", [])]
        for identifier in identifiers:
            values[(item["package"].casefold(), item["version"], identifier)] = item
    return values


if __name__ == "__main__":
    raise SystemExit(main())
