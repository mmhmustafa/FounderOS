"""The ONE runtime/dev dependency partition rule (PR-A0).

Every compliance consumer — the runtime manifest, the SBOM, and the later
notices generator and licence gate — reads THIS module. The architecture
review found three divergent readings of ``constraints.txt`` and ruled that
a fourth is not a fix; this is the single reading.

The rule
--------
``constraints.txt`` is the ENVIRONMENT LOCK: it pins versions for the whole
development environment, runtime and dev together (80 pins against a true
runtime closure of ~52). It is deliberately NOT the definition of what Atlas
ships. Runtime membership is derived from the project's own declarations:

    runtime roots = [project.dependencies]
                  + optional-dependencies for the RUNTIME extras
                    (credentials, ssh, web)
    dev roots     = optional-dependencies for the DEV extras (dev)

and the transitive closure is expanded through package metadata with
environment markers evaluated EXPLICITLY per target platform — never the
markers of whatever interpreter happens to run the generator.

Determinism contract
--------------------
The output is a pure function of (pyproject.toml, constraints.txt, the
installed metadata of PINNED packages). Three properties enforce it:

- Expansion is LOCKED-ONLY: a dependency is expanded transitively only when
  ``constraints.txt`` pins it. A dependency the lock does not pin (for
  example keyring's linux-only SecretStorage/jeepney) is recorded as an
  unexpanded leaf with ``expansion: "not-locked"`` — the same record on
  every generation host, whether or not the package happens to be installed
  there. This is also a finding surface: the lock's own gaps become visible
  instead of platform-dependent.
- Ambient contamination is impossible by construction: resolution WALKS
  FROM THE ROOTS. A package that is merely installed (the review measured
  eleven, including an LGPL cairosvg Atlas never imports) is unreachable
  and cannot enter any closure.
- A pinned, reached package whose installed version differs from its pin —
  or which is not installed at all — fails generation LOUDLY. A quietly
  different environment must never produce a quietly different manifest.

Licence-evidence model (PR-A0 structural, not classification)
-------------------------------------------------------------
Evidence collection records FACTS for the later gate: the declared metadata
expression, every licence-evidence file WITH ITS ATTRIBUTION PATH, bundled
component SBOMs (cryptography's Rust SBOM), and factual observations
(pyserial ships no licence file; isoduration's metadata says UNKNOWN while
an ISC text is bundled). One rule is load-bearing: a licence file installed
at the site-packages ROOT is NEVER package evidence — netmiko and
ntc_templates both install a root-level ``LICENSE`` that overwrite each
other, so a root path can prove nothing about who it belongs to.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from importlib import metadata as importlib_metadata
from pathlib import Path

from packaging.markers import Marker
from packaging.requirements import InvalidRequirement, Requirement

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
LOCK = ROOT / "constraints.txt"

# The distribution model, per the PR-A architecture review (§5, §18):
# Atlas ships the base dependencies plus these extras. ``dev`` never ships.
RUNTIME_EXTRAS = ("credentials", "ssh", "web")
DEV_EXTRAS = ("dev",)

# Target platforms, per the review: the Windows beta distribution and the
# Linux CI runner are mandatory; Darwin costs nothing extra to model and is
# preserved. Alphabetical everywhere for deterministic output.
TARGET_PLATFORMS = ("darwin", "linux", "win32")

# Markers are evaluated against FIXED environments — never the generator's
# own interpreter. python_version is the project floor (requires-python
# >=3.11): evaluating at the floor keeps backport-shaped conditionals
# (tomli, exceptiongroup, importlib-metadata for older pythons) out of
# every closure deterministically.
_PYTHON_VERSION = "3.11"
_COMMON_ENV = {
    "implementation_name": "cpython",
    "implementation_version": _PYTHON_VERSION + ".0",
    "platform_python_implementation": "CPython",
    "platform_release": "",
    "platform_version": "",
    "python_full_version": _PYTHON_VERSION + ".0",
    "python_version": _PYTHON_VERSION,
}
MARKER_ENVIRONMENTS = {
    "darwin": {
        **_COMMON_ENV,
        "os_name": "posix", "platform_machine": "arm64",
        "platform_system": "Darwin", "sys_platform": "darwin",
    },
    "linux": {
        **_COMMON_ENV,
        "os_name": "posix", "platform_machine": "x86_64",
        "platform_system": "Linux", "sys_platform": "linux",
    },
    "win32": {
        **_COMMON_ENV,
        "os_name": "nt", "platform_machine": "AMD64",
        "platform_system": "Windows", "sys_platform": "win32",
    },
}

_LICENSE_FILE = re.compile(
    r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS|COPYRIGHT)", re.IGNORECASE
)


def normalize(name: str) -> str:
    """PEP 503 name normalization — the one spelling every artifact uses.

    PyYAML -> pyyaml, ruamel.yaml -> ruamel-yaml, jaraco.classes ->
    jaraco-classes, boolean.py -> boolean-py.
    """

    return re.sub(r"[-_.]+", "-", name).lower()


def read_pins(lock_path: Path | None = None) -> dict[str, tuple[str, str]]:
    """``constraints.txt`` as {normalized: (raw name, version)}.

    Every line must be a fully locked ``name==version`` (the same contract
    generate_sbom.py has always enforced).
    """

    pins: dict[str, tuple[str, str]] = {}
    path = lock_path or LOCK
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", value)
        if match is None:
            raise SystemExit(f"constraints.txt is not fully locked: {value}")
        name, version = match.groups()
        pins[normalize(name)] = (name, version)
    return pins


def read_roots(pyproject_path: Path | None = None) -> tuple[list[str], list[str]]:
    """(runtime root requirements, dev root requirements) from pyproject.

    Sorted by normalized requirement name so declaration order in
    pyproject.toml can never change any generated artifact.
    """

    path = pyproject_path or PYPROJECT
    project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
    runtime = list(project.get("dependencies", ()))
    optional = project.get("optional-dependencies", {})
    for extra in RUNTIME_EXTRAS:
        runtime.extend(optional.get(extra, ()))
    dev: list[str] = []
    for extra in DEV_EXTRAS:
        dev.extend(optional.get(extra, ()))

    def _key(req: str) -> str:
        return normalize(Requirement(req).name)

    return sorted(runtime, key=_key), sorted(dev, key=_key)


@dataclass
class Member:
    """One package's membership in one closure."""

    normalized: str
    name: str                       # raw (lock spelling when pinned)
    version: str | None             # the pin, or None when not locked
    pinned: bool
    direct: bool = False            # a declared root
    expansion: str = "locked"       # "locked" | "not-locked"
    platforms: set[str] = field(default_factory=set)
    required_by: set[str] = field(default_factory=set)


class EnvironmentMismatch(SystemExit):
    """The installed environment does not match the lock — refuse to guess."""


def _installed_version(normalized_name: str) -> str | None:
    try:
        return importlib_metadata.version(normalized_name)
    except importlib_metadata.PackageNotFoundError:
        return None


def _requires_dist(normalized_name: str) -> list[str]:
    md = importlib_metadata.metadata(normalized_name)
    return list(md.get_all("Requires-Dist") or ())


def _marker_allows(
    marker: Marker | None, env: dict[str, str], extras: frozenset[str]
) -> bool:
    if marker is None:
        return True
    if not extras:
        return marker.evaluate({**env, "extra": ""})
    return any(marker.evaluate({**env, "extra": extra}) for extra in extras)


def resolve_closure(
    root_requirements: list[str],
    pins: dict[str, tuple[str, str]],
    platform: str,
) -> dict[str, Member]:
    """The closure of one root set on one target platform.

    Walks from the declared roots only; expands only lock-pinned packages;
    fails loudly on any pinned, reached package whose installed metadata is
    missing or version-skewed.
    """

    env = MARKER_ENVIRONMENTS[platform]
    members: dict[str, Member] = {}
    # normalized -> extras already expanded for
    expanded: dict[str, frozenset[str]] = {}
    # A requirement's marker is evaluated ONCE, at enqueue time, in the
    # extras context of whoever required it (a dependency guarded by
    # ``extra == 'format'`` is admitted by its parent's extras and must
    # not be re-judged later with an empty context). Enqueued items are
    # therefore already marker-approved.
    queue: list[tuple[Requirement, str | None]] = []
    for raw in root_requirements:
        root = Requirement(raw)
        if _marker_allows(root.marker, env, frozenset()):
            queue.append((root, None))

    problems: list[str] = []
    while queue:
        requirement, parent = queue.pop()
        key = normalize(requirement.name)
        pinned = key in pins
        raw_name, version = pins.get(key, (requirement.name, None))
        member = members.get(key)
        if member is None:
            member = Member(
                normalized=key, name=raw_name, version=version, pinned=pinned,
                expansion="locked" if pinned else "not-locked",
            )
            members[key] = member
        member.platforms.add(platform)
        if parent is None:
            member.direct = True
        else:
            member.required_by.add(parent)

        if not pinned:
            # The lock does not cover this dependency: record the leaf and
            # do NOT expand — expansion here would depend on what happens
            # to be installed on the generation host.
            continue

        extras = frozenset(requirement.extras)
        already = expanded.get(key)
        if already is not None and extras <= already:
            continue
        expanded[key] = (already or frozenset()) | extras

        installed = _installed_version(key)
        if installed is None:
            problems.append(
                f"{raw_name}=={version} is pinned and reachable but not "
                "installed"
            )
            continue
        if installed != version:
            problems.append(
                f"{raw_name}: installed {installed} != pinned {version}"
            )
            continue
        for spec in _requires_dist(key):
            try:
                dependency = Requirement(spec)
            except InvalidRequirement:
                continue
            if not _marker_allows(dependency.marker, env, extras):
                continue
            queue.append((dependency, key))

    if problems:
        raise EnvironmentMismatch(
            "the installed environment does not match constraints.txt — "
            "run: pip install -c constraints.txt -e .[dev,ssh,credentials,web]\n  "
            + "\n  ".join(sorted(problems))
        )
    return members


@dataclass(frozen=True)
class Partition:
    """The one partition every compliance artifact derives from."""

    runtime: dict[str, Member]        # merged across platforms
    development: dict[str, Member]    # dev-closure members NOT in runtime
    unassigned: dict[str, tuple[str, str]]   # pinned, reachable from neither


def _merge(per_platform: list[dict[str, Member]]) -> dict[str, Member]:
    merged: dict[str, Member] = {}
    for closure in per_platform:
        for key, member in closure.items():
            existing = merged.get(key)
            if existing is None:
                merged[key] = Member(
                    normalized=member.normalized, name=member.name,
                    version=member.version, pinned=member.pinned,
                    direct=member.direct, expansion=member.expansion,
                    platforms=set(member.platforms),
                    required_by=set(member.required_by),
                )
            else:
                existing.platforms |= member.platforms
                existing.required_by |= member.required_by
                existing.direct = existing.direct or member.direct
    return merged


def compute_partition(
    pyproject_path: Path | None = None, lock_path: Path | None = None
) -> Partition:
    runtime_roots, dev_roots = read_roots(pyproject_path)
    pins = read_pins(lock_path)
    runtime = _merge([
        resolve_closure(runtime_roots, pins, platform)
        for platform in TARGET_PLATFORMS
    ])
    dev_all = _merge([
        resolve_closure(dev_roots, pins, platform)
        for platform in TARGET_PLATFORMS
    ])
    development = {
        key: member for key, member in dev_all.items() if key not in runtime
    }
    unassigned = {
        key: value for key, value in pins.items()
        if key not in runtime and key not in dev_all
    }
    return Partition(
        runtime=runtime, development=development, unassigned=unassigned
    )


# -- licence evidence (structural facts only; classification is A2's) --------


def license_evidence(normalized_name: str) -> dict:
    """Structural licence-evidence facts for one INSTALLED distribution.

    Attribution rules (the collision fix): a file counts as this package's
    evidence only when its path is under the package's own dist-info
    directory or under a top-level directory the package itself installs.
    A path at the site-packages ROOT (no directory) is recorded as rejected
    — it is shared mutable territory that netmiko and ntc_templates both
    write, so it can never prove attribution.
    """

    dist = importlib_metadata.distribution(normalized_name)
    md = dist.metadata
    declared_expression = md.get("License-Expression") or ""
    declared_license = " ".join(str(md.get("License") or "").split())
    classifiers = sorted(
        c.split("License ::", 1)[1].strip()
        for c in md.get_all("Classifier") or ()
        if c.startswith("License ::")
    )

    files = [str(f).replace("\\", "/") for f in (dist.files or ())]
    dist_info = next(
        (f.rsplit("/", 1)[0] for f in files if f.endswith(".dist-info/METADATA")),
        None,
    )
    top_level: set[str] = set()
    for f in files:
        if "/" not in f:
            continue
        head = f.split("/", 1)[0]
        if (
            head.endswith((".dist-info", ".data"))
            or head == "__pycache__"
            or head.startswith("..")
        ):
            continue
        top_level.add(head)

    dist_info_evidence: list[str] = []
    in_package_evidence: list[str] = []
    rejected_root_paths: list[str] = []
    component_sboms: list[str] = []
    for path in files:
        basename = path.rsplit("/", 1)[-1]
        if dist_info and path.startswith(dist_info + "/"):
            if "/sboms/" in path and path.endswith(".json"):
                component_sboms.append(path)
            elif _LICENSE_FILE.search(basename):
                dist_info_evidence.append(path)
            continue
        if _LICENSE_FILE.search(basename):
            if "/" not in path:
                # Site-packages root: shared, collision-prone, unattributable.
                rejected_root_paths.append(path)
            elif any(path.startswith(top + "/") for top in top_level):
                in_package_evidence.append(path)

    observations: list[str] = []
    if not dist_info_evidence and not in_package_evidence:
        observations.append("no-license-file-shipped")
    if declared_license.strip().upper() == "UNKNOWN":
        observations.append("metadata-license-unknown")
        if dist_info_evidence:
            observations.append("bundled-license-text-present")
    if rejected_root_paths:
        observations.append("root-level-evidence-ignored")
    if component_sboms:
        observations.append("bundled-component-sbom")
    if in_package_evidence:
        observations.append("nested-license-evidence")

    return {
        "declared_expression": declared_expression,
        "declared_license": declared_license,
        "declared_classifiers": classifiers,
        "evidence_files": sorted(dist_info_evidence),
        "nested_evidence_files": sorted(in_package_evidence),
        "component_sboms": sorted(component_sboms),
        "rejected_root_paths": sorted(rejected_root_paths),
        "observations": sorted(observations),
    }


def declared_license_label(normalized_name: str) -> str:
    """The single declared-licence string for SBOM annotation. Factual:
    metadata expression, else the License field, else the first licence
    classifier, else empty."""

    evidence = license_evidence(normalized_name)
    return (
        evidence["declared_expression"]
        or evidence["declared_license"]
        or (evidence["declared_classifiers"][0]
            if evidence["declared_classifiers"] else "")
    )
