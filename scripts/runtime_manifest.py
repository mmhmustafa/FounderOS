"""Generate the deterministic runtime manifest (PR-A0).

``compliance/runtime-manifest.json`` is the ONE authoritative answer to
"what does Atlas actually ship at runtime" — the artifact the architecture
review found missing when it proved constraints.txt is an environment lock,
not a runtime manifest. The SBOM, and later the third-party notices and the
licence gate, all derive from the same partition rule this generator uses
(scripts/compliance_core.py).

Deterministic by construction: resolved from the project's declared roots
with markers evaluated per target platform, pinned by constraints.txt,
sorted by normalized name, written with LF endings. CI regenerates it and
fails on any diff, exactly like sbom.cdx.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import compliance_core as core  # noqa: E402

DESTINATION = ROOT / "compliance" / "runtime-manifest.json"


def _member_payload(member: core.Member, scope: str) -> dict:
    payload: dict = {
        "name": member.name,
        "normalized": member.normalized,
        "version": member.version,
        "pinned": member.pinned,
        "scope": scope,
        "direct": member.direct,
        "expansion": member.expansion,
        "platforms": sorted(member.platforms),
        "required_by": sorted(member.required_by),
    }
    if member.pinned:
        # Structural licence-evidence FACTS (PR-A0). Classification and
        # notice generation are Stage A2's; nothing here is a legal
        # decision. Evidence is only collectable for installed packages —
        # which every pinned, reached package is (generation fails loudly
        # otherwise).
        payload["license_evidence"] = core.license_evidence(member.normalized)
    else:
        payload["license_evidence"] = None
    return payload


def build_manifest() -> dict:
    partition = core.compute_partition()
    runtime = [
        _member_payload(partition.runtime[key], "runtime")
        for key in sorted(partition.runtime)
    ]
    development = [
        _member_payload(partition.development[key], "development")
        for key in sorted(partition.development)
    ]
    unassigned = [
        {"name": name, "normalized": key, "version": version}
        for key, (name, version) in sorted(partition.unassigned.items())
    ]
    return {
        "schema_version": "1.0",
        "generated_by": "scripts/runtime_manifest.py",
        "application": {
            "name": "founderos-runtime",
            "version": _application_version(),
        },
        "partition_rule": {
            "description": (
                "runtime = [project.dependencies] + runtime extras; "
                "dev = dev extras; expansion is locked-only "
                "(constraints.txt); markers evaluated per target platform "
                "at the python floor"
            ),
            "runtime_extras": list(core.RUNTIME_EXTRAS),
            "dev_extras": list(core.DEV_EXTRAS),
            "python_version_floor": core.MARKER_ENVIRONMENTS["linux"][
                "python_version"
            ],
            "target_platforms": list(core.TARGET_PLATFORMS),
        },
        "counts": {
            "runtime_total": len(runtime),
            "runtime_by_platform": {
                platform: sum(
                    1 for entry in runtime if platform in entry["platforms"]
                )
                for platform in core.TARGET_PLATFORMS
            },
            "development_only": len(development),
            "unassigned_pins": len(unassigned),
        },
        "runtime": runtime,
        "development_only": development,
        "unassigned_pins": unassigned,
    }


def _application_version() -> str:
    from founderos_atlas.release import VERSION

    return VERSION


def main() -> int:
    payload = build_manifest()
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    # LF explicitly: this file's bytes are diff-checked in CI; the platform
    # the generator happens to run on must not be able to change them.
    with DESTINATION.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        f"Wrote {DESTINATION} "
        f"({payload['counts']['runtime_total']} runtime, "
        f"{payload['counts']['development_only']} dev-only, "
        f"{payload['counts']['unassigned_pins']} unassigned)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
