"""Generate a deterministic CycloneDX 1.6 inventory from the lock file.

PR-A0: the SBOM and the runtime manifest now share ONE partition rule
(scripts/compliance_core.py). The SBOM remains the ENVIRONMENT inventory —
every constraints.txt pin appears — but each component now carries the
partition's verdict (CycloneDX ``scope`` plus explicit properties) and the
factual declared-licence string from the pinned distribution's own
metadata. Classification (GREEN/AMBER/RED) is deliberately absent: that is
Stage A2's licence gate, and pretending it exists here would be a second,
divergent reading.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import compliance_core as core  # noqa: E402

DESTINATION = ROOT / "sbom.cdx.json"


def main() -> int:
    pins = core.read_pins()
    partition = core.compute_partition()

    components = []
    for key in sorted(pins):
        name, version = pins[key]
        runtime_member = partition.runtime.get(key)
        if runtime_member is not None:
            scope = "required"
            founderos_scope = "runtime"
            platforms = sorted(runtime_member.platforms)
        elif key in partition.development:
            scope = "excluded"
            founderos_scope = "development"
            platforms = sorted(partition.development[key].platforms)
        else:
            scope = "excluded"
            founderos_scope = "unassigned"
            platforms = []
        component = {
            "type": "library",
            "name": key,
            "version": version,
            "purl": f"pkg:pypi/{key}@{version}",
            "scope": scope,
            "properties": [
                {"name": "founderos:scope", "value": founderos_scope},
                {
                    "name": "founderos:platforms",
                    "value": ",".join(platforms),
                },
            ],
        }
        declared = core.declared_license_label(key)
        if declared:
            # Factual: the distribution's own declared licence string.
            # Arbitrary declared strings ("Dual License", "UNKNOWN") are
            # not valid SPDX expressions, so the named-licence form is
            # used throughout rather than sometimes-expression.
            component["licenses"] = [{"license": {"name": declared}}]
        components.append(component)

    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"component": {
            "type": "application", "name": "founderos-runtime",
            "version": _application_version(),
        }},
        "components": components,
    }
    with DESTINATION.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"Wrote {DESTINATION} ({len(components)} components)")
    return 0


def _application_version() -> str:
    from founderos_atlas.release import VERSION
    return VERSION


if __name__ == "__main__":
    raise SystemExit(main())
