"""Fail when the runtime closure departs from the reviewed licence policy.

PR-A2a. The runtime closure is defined by compliance/runtime-manifest.json
(the A0 partition rule) — never pip freeze, never the ambient venv, never
constraints.txt alone. This gate checks that closure against
compliance/license-policy.json with real SPDX semantics:

- OR is a choice: it requires an explicitly recorded election, and the
  original expression is preserved rather than rewritten;
- AND preserves every conjunctive obligation;
- WITH carries the exception through;
- families are matched as parsed SPDX symbols, never substrings — the
  measured trap is ``Apache-2.0 OR GPL-2.0-only`` (a cryptography Rust
  crate), which a substring gate would wrongly fail and this gate passes
  only because the Apache-2.0 arm is elected on the record.

The gate also fails when reviewed weak-copyleft material goes stale: a
paramiko/scp/fqdn version bump, a missing or hash-skewed corresponding
source archive, a missing canonical licence text, or a recorded evidence
exception whose observed evidence state has changed.

Staleness of the generated artifacts themselves (manifest, SBOM, notices)
is CI's ``git diff --exit-code`` interlock, deliberately not duplicated
here.

Nothing in this file grants, limits, or interprets any right in Atlas
itself — Atlas-owned terms are Stage A2b and out of scope.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import importlib.metadata as importlib_metadata

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compliance_core as core  # noqa: E402

ROOT = core.ROOT
POLICY_PATH = ROOT / "compliance" / "license-policy.json"
VENDORED_PATH = ROOT / "compliance" / "vendored-assets.json"
MANIFEST_PATH = ROOT / "compliance" / "runtime-manifest.json"
SECURITY_EXCEPTIONS = ROOT / "security" / "vulnerability-exceptions.json"


def _licensing():
    try:
        from license_expression import get_spdx_licensing
    except ImportError as error:  # pragma: no cover - environment defect
        raise SystemExit(
            "license-expression is required to run the licence gate.\n"
            "Remedy: .venv/Scripts/python.exe -m pip install -c constraints.txt"
            " license-expression"
        ) from error
    return get_spdx_licensing()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PolicyCheck:
    """One run of the gate. Collects every problem before failing."""

    def __init__(self) -> None:
        self.licensing = _licensing()
        self.policy = load_json(POLICY_PATH)
        self.vendored = load_json(VENDORED_PATH)
        self.manifest = load_json(MANIFEST_PATH)
        self.problems: list[str] = []
        self.members = {e["normalized"]: e for e in self.manifest["runtime"]}
        spdx = self.policy["spdx"]
        self.allowed = set(spdx["allowed_families"])
        self.allowed_exceptions = set(spdx["allowed_exceptions"])
        self.reviewed_families = set(spdx["reviewed_weak_copyleft"])
        self.forbidden = set(spdx["forbidden_runtime_families"])
        self.reviewed_by_name = {
            r["name"]: r for r in self.policy["reviewed_components"]
        }

    def problem(self, text: str) -> None:
        self.problems.append(text)

    # ------------------------------------------------------------------
    # SPDX helpers
    # ------------------------------------------------------------------

    def parse(self, text: str, where: str):
        try:
            return self.licensing.parse(text, validate=True, strict=True)
        except Exception as error:
            self.problem(f"{where}: unparseable SPDX expression {text!r} ({error})")
            return None

    @staticmethod
    def _contains_or(parsed) -> bool:
        return " OR " in f" {parsed} ".replace("(", " ( ").replace(")", " ) ")

    def symbols(self, parsed):
        """Yield (licence_key, exception_key_or_None) for every symbol."""

        from license_expression import LicenseWithExceptionSymbol

        for symbol in parsed.symbols:
            if isinstance(symbol, LicenseWithExceptionSymbol):
                yield (
                    symbol.license_symbol.key,
                    symbol.exception_symbol.key,
                )
            else:
                yield (symbol.key, None)

    def election_satisfies(self, elected, expression) -> bool:
        """True when the elected expression is a valid choice of the original.

        Boolean absorption: choosing an arm of every OR yields an expression
        E with E AND original == E.
        """

        try:
            combined = self.licensing.parse(
                f"({elected}) AND ({expression})"
            ).simplify()
            return combined == self.licensing.parse(str(elected)).simplify()
        except Exception:
            return False

    def check_symbols(self, parsed, where: str, reviewed_name: str | None = None):
        """Every symbol of a non-disjunctive expression must be acceptable."""

        for licence_key, exception_key in self.symbols(parsed):
            if licence_key in self.forbidden:
                self.problem(
                    f"{where}: forbidden licence {licence_key} is required"
                    " (not an unelected disjunction arm)"
                )
            elif licence_key in self.reviewed_families:
                record = self.reviewed_by_name.get(reviewed_name or "")
                if record is None:
                    self.problem(
                        f"{where}: weak-copyleft {licence_key} has no"
                        " reviewed_components record"
                    )
            elif licence_key not in self.allowed:
                self.problem(
                    f"{where}: licence {licence_key} is neither allowed,"
                    " reviewed, nor forbidden — unresolved; add a reviewed"
                    " policy treatment"
                )
            if exception_key and exception_key not in self.allowed_exceptions:
                self.problem(
                    f"{where}: licence exception {exception_key} is not on the"
                    " allowed_exceptions list"
                )

    def evaluate(self, expression: str, where: str, *,
                 election_key: tuple[str, str | None] | None = None,
                 reviewed_name: str | None = None) -> None:
        """Evaluate one concluded/declared expression against the policy."""

        parsed = self.parse(expression, where)
        if parsed is None:
            return
        if self._contains_or(parsed):
            election = self._find_election(expression, election_key)
            if election is None:
                self.problem(
                    f"{where}: disjunction {expression!r} has no recorded"
                    " election in license-policy.json"
                )
                return
            elected = self.parse(election["elected"], f"{where} (elected)")
            if elected is None:
                return
            if not self.election_satisfies(election["elected"], expression):
                self.problem(
                    f"{where}: recorded election {election['elected']!r} is not"
                    f" a valid choice of {expression!r}"
                )
                return
            self.check_symbols(elected, f"{where} (elected arm)", reviewed_name)
        else:
            self.check_symbols(parsed, where, reviewed_name)

    def _find_election(self, expression: str,
                       election_key: tuple[str, str | None] | None):
        """Locate the election covering (component, within) for an expression."""

        target = self.licensing.parse(expression).simplify()
        for election in self.policy["elections"]:
            if self.licensing.parse(election["expression"]).simplify() != target:
                continue
            if election_key is None:
                return election
            name, within = election_key
            for component in election["components"]:
                if component["name"] == name and component.get("within") == within:
                    return election
        return None

    # ------------------------------------------------------------------
    # Individual gates
    # ------------------------------------------------------------------

    def check_membership(self) -> None:
        components = self.policy["components"]
        for name in self.members:
            if name not in components:
                self.problem(
                    f"runtime member {name} has no policy treatment in"
                    " license-policy.json"
                )
        for name in components:
            if name not in self.members:
                self.problem(
                    f"policy component {name} is no longer in the runtime"
                    " manifest — stale policy entry"
                )

    def check_members(self) -> None:
        components = self.policy["components"]
        exceptions_by_component = {
            e["component"]: e for e in self.policy["evidence_exceptions"]
        }
        for name, member in sorted(self.members.items()):
            treatment = components.get(name)
            if treatment is None:
                continue  # already reported
            if member.get("expansion") == "not-locked":
                if treatment.get("concluded") is not None:
                    self.problem(
                        f"{name}: not-locked leaf must not carry a concluded"
                        " licence (no evidence exists)"
                    )
                if name not in self.policy["not_locked_leaves"]:
                    self.problem(
                        f"{name}: not-locked leaf missing from"
                        " not_locked_leaves"
                    )
                continue
            concluded = treatment.get("concluded")
            if not concluded:
                self.problem(f"{name}: locked member has no concluded licence")
                continue
            evidence = member.get("license_evidence") or {}
            has_evidence = bool(
                evidence.get("evidence_files")
                or evidence.get("nested_evidence_files")
            )
            if not has_evidence and name not in exceptions_by_component:
                self.problem(
                    f"{name}: no licence evidence shipped and no recorded"
                    " evidence exception"
                )
            self.evaluate(
                concluded,
                f"component {name}",
                election_key=(name, None),
                reviewed_name=name,
            )

    def check_reviewed(self) -> None:
        for record in self.policy["reviewed_components"]:
            name = record["name"]
            member = self.members.get(name)
            where = f"reviewed component {name}"
            if member is None:
                self.problem(f"{where}: not in the runtime manifest")
                continue
            if member.get("version") != record["version"]:
                self.problem(
                    f"{where}: version pin {record['version']} does not match"
                    f" manifest {member.get('version')} — re-review the"
                    " treatment, licence text, and corresponding source"
                )
            archive = ROOT / record["source_archive"]
            if not archive.is_file():
                self.problem(f"{where}: corresponding source archive missing:"
                             f" {record['source_archive']}")
            else:
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                if digest != record["source_sha256"]:
                    self.problem(
                        f"{where}: source archive sha256 mismatch"
                        f" (recorded {record['source_sha256'][:12]}…,"
                        f" actual {digest[:12]}…)"
                    )
            text = ROOT / record["licence_text"]
            if not text.is_file():
                self.problem(f"{where}: canonical licence text missing:"
                             f" {record['licence_text']}")
        # The paramiko security exception and this policy must pin the same
        # version, so an upgrade fails both gates together (PR-A2 amendment H).
        paramiko = self.reviewed_by_name.get("paramiko")
        if paramiko is not None and SECURITY_EXCEPTIONS.is_file():
            security = load_json(SECURITY_EXCEPTIONS)
            for exception in security.get("exceptions", []):
                if exception.get("package") == "paramiko":
                    if exception.get("version") != paramiko["version"]:
                        self.problem(
                            "paramiko: license-policy.json pins"
                            f" {paramiko['version']} but"
                            " security/vulnerability-exceptions.json pins"
                            f" {exception.get('version')} — the two gates"
                            " must move together"
                        )

    def check_canonical_texts(self) -> None:
        for key, rel in self.policy["canonical_texts"].items():
            if not (ROOT / rel).is_file():
                self.problem(f"canonical text {key} missing: {rel}")

    def _locate(self, name: str, rel: str) -> Path | None:
        member = self.members.get(name) or {}
        try:
            dist = importlib_metadata.distribution(name)
        except importlib_metadata.PackageNotFoundError:
            self.problem(
                f"{name}: not installed — the gate needs the locked"
                " environment (pip install -c constraints.txt"
                " -e .[dev,ssh,credentials,web])"
            )
            return None
        installed = dist.version
        expected = member.get("version")
        if expected and installed != expected:
            self.problem(
                f"{name}: installed {installed} but manifest pins {expected}"
                " — environment mismatch"
            )
            return None
        path = Path(str(dist.locate_file(rel)))
        if not path.is_file():
            self.problem(f"{name}: recorded evidence file missing: {rel}")
            return None
        return path

    def check_nested(self) -> None:
        resolutions = {
            (r["within"], r["component"]): r
            for r in self.policy["nested_resolutions"]
        }
        for name, member in sorted(self.members.items()):
            evidence = member.get("license_evidence") or {}
            for rel in evidence.get("component_sboms") or []:
                path = self._locate(name, rel)
                if path is None:
                    continue
                sbom = load_json(path)
                for component in sbom.get("components", []):
                    cname = component.get("name") or "?"
                    cversion = component.get("version") or "?"
                    where = f"nested {name}:{cname}=={cversion}"
                    expressions = [
                        licence.get("expression")
                        or (licence.get("license") or {}).get("id")
                        or (licence.get("license") or {}).get("name")
                        for licence in component.get("licenses", [])
                    ]
                    expressions = [e for e in expressions if e]
                    if not expressions:
                        resolution = resolutions.get((name, cname))
                        if resolution is None:
                            self.problem(
                                f"{where}: no licence declared in the bundled"
                                " SBOM and no nested_resolutions record"
                            )
                            continue
                        self.evaluate(resolution["resolution"].split(" (")[0],
                                      f"{where} (resolved)")
                        continue
                    for expression in expressions:
                        self.evaluate(
                            expression,
                            where,
                            election_key=(cname, name),
                        )

    def check_exception_evidence(self) -> None:
        """A recorded exception whose observed evidence changed is stale."""

        def evidence(name: str) -> dict:
            member = self.members.get(name) or {}
            return member.get("license_evidence") or {}

        observations = evidence("pyserial").get("observations") or []
        if "no-license-file-shipped" not in observations:
            self.problem(
                "EXC-PYSERIAL is stale: pyserial now ships licence evidence —"
                " re-review and retire or rewrite the exception"
            )
        observations = evidence("isoduration").get("observations") or []
        for marker in ("metadata-license-unknown", "bundled-license-text-present"):
            if marker not in observations:
                self.problem(
                    f"EXC-ISODURATION is stale: observation {marker!r} no"
                    " longer holds — re-review the exception"
                )
        rfc = evidence("rfc3987-syntax")
        classifiers = " ".join(rfc.get("declared_classifiers") or [])
        if rfc.get("declared_expression") != "MIT" or "Apache" not in classifiers:
            self.problem(
                "EXC-RFC3987-SYNTAX is stale: the metadata discrepancy it"
                " records no longer exists — re-review the exception"
            )

    def check_vendored(self) -> None:
        listed: set[str] = set()
        for component in self.vendored["components"]:
            expression = component.get("licence")
            where = f"vendored {component['name']}"
            if not expression:
                self.problem(f"{where}: no licence recorded")
            else:
                self.evaluate(expression, where)
            for rel in component["files"]:
                listed.add(rel)
                if not (ROOT / rel).is_file():
                    self.problem(f"{where}: listed file missing: {rel}")
            for rel in component["licence_evidence"]:
                if not (ROOT / rel).is_file():
                    self.problem(f"{where}: evidence file missing: {rel}")
        evidence_files = set(self.vendored["evidence_files"])
        for rel in evidence_files:
            if not (ROOT / rel).is_file():
                self.problem(f"vendored evidence file missing: {rel}")
        for directory in self.vendored["directories"]:
            base = ROOT / directory
            if not base.is_dir():
                self.problem(f"vendored directory missing: {directory}")
                continue
            for path in sorted(base.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(ROOT).as_posix()
                if rel not in listed and rel not in evidence_files:
                    self.problem(
                        f"vendored file {rel} has no evidence entry in"
                        " compliance/vendored-assets.json"
                    )

    def check_not_locked(self) -> None:
        manifest_leaves = {
            name
            for name, member in self.members.items()
            if member.get("expansion") == "not-locked"
        }
        policy_leaves = set(self.policy["not_locked_leaves"])
        for name in sorted(manifest_leaves - policy_leaves):
            self.problem(f"not-locked leaf {name} missing from policy")
        for name in sorted(policy_leaves - manifest_leaves):
            self.problem(f"policy not-locked leaf {name} is stale")

    def run(self) -> list[str]:
        self.check_membership()
        self.check_members()
        self.check_reviewed()
        self.check_canonical_texts()
        self.check_nested()
        self.check_exception_evidence()
        self.check_vendored()
        self.check_not_locked()
        return self.problems


def main() -> int:
    check = PolicyCheck()
    problems = check.run()
    if problems:
        for problem in problems:
            print(f"LICENCE-GATE: {problem}", file=sys.stderr)
        print(f"licence gate FAILED: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    locked = sum(
        1 for m in check.members.values() if m.get("expansion") != "not-locked"
    )
    print(
        "licence gate passed:"
        f" {len(check.members)} runtime members ({locked} locked),"
        f" {len(check.policy['elections'])} recorded elections,"
        f" {len(check.policy['evidence_exceptions'])} evidence exceptions,"
        f" {len(check.policy['reviewed_components'])} reviewed weak-copyleft"
        " components"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
