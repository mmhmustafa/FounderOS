"""Generate a deterministic CycloneDX 1.6 inventory from the lock file."""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "constraints.txt"
DESTINATION = ROOT / "sbom.cdx.json"


def main() -> int:
    components = []
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", value)
        if match is None:
            raise SystemExit(f"constraints.txt is not fully locked: {value}")
        name, version = match.groups()
        normalized = name.casefold().replace("_", "-")
        components.append({
            "type": "library",
            "name": normalized,
            "version": version,
            "purl": f"pkg:pypi/{normalized}@{version}",
        })
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"component": {
            "type": "application", "name": "founderos-runtime",
            "version": _application_version(),
        }},
        "components": sorted(components, key=lambda item: item["name"]),
    }
    DESTINATION.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {DESTINATION} ({len(components)} components)")
    return 0


def _application_version() -> str:
    from founderos_atlas.release import VERSION
    return VERSION


if __name__ == "__main__":
    raise SystemExit(main())
