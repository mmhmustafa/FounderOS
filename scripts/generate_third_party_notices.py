"""Generate THIRD-PARTY-NOTICES.txt deterministically from the compliance model.

PR-A2a. Source of truth, in strict order:

    compliance/runtime-manifest.json     (the A0 partition — the ONLY closure)
    compliance/license-policy.json       (reviewed conclusions and elections)
    recorded licence evidence            (dist-info + in-package paths from the
                                          manifest; never a site-packages root)
    bundled component SBOMs              (every dist-info/sboms/*.json)
    compliance/vendored-assets.json      (non-pip assets, recorded evidence)

NEVER: pip freeze, the ambient venv, constraints.txt alone, or a
site-packages-root LICENSE file — the measured netmiko/ntc_templates root
collision makes root paths structurally unattributable, and the manifest
already rejects them.

Determinism: LF everywhere, PEP 503-sorted sections, no timestamps, no
host paths, no generator version strings. CI regenerates this file and
fails on any diff, exactly like the runtime manifest and the SBOM.

Text handling: a shipped evidence file whose normalized bytes equal a
canonical text in compliance/licenses/ is referenced to the appendix
instead of inlined twice; every other shipped text is inlined verbatim.
Components whose distributions ship only a short notice (scp,
ntc_templates) or no text at all (pyserial) get the canonical full text
by reference, and the notice says the generator supplied it.

This file records third-party attribution only. It grants no rights in
Atlas and contains no Atlas-owned licence terms (Stage A2b is separate).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import importlib.metadata as importlib_metadata

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compliance_core as core  # noqa: E402

ROOT = core.ROOT
OUTPUT = ROOT / "THIRD-PARTY-NOTICES.txt"
POLICY_PATH = ROOT / "compliance" / "license-policy.json"
VENDORED_PATH = ROOT / "compliance" / "vendored-assets.json"
MANIFEST_PATH = ROOT / "compliance" / "runtime-manifest.json"

RULE = "=" * 72
THIN = "-" * 72


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize(raw: bytes) -> str:
    """Decode deterministically (UTF-8, then Latin-1) and normalize to LF."""

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n"


class NoticeBuilder:
    def __init__(self) -> None:
        self.policy = _load(POLICY_PATH)
        self.vendored = _load(VENDORED_PATH)
        self.manifest = _load(MANIFEST_PATH)
        self.members = {e["normalized"]: e for e in self.manifest["runtime"]}
        self.reviewed = {r["name"]: r for r in self.policy["reviewed_components"]}
        self.exceptions = {
            e["component"]: e for e in self.policy["evidence_exceptions"]
        }
        self.nested = {
            (r["within"], r["component"]): r
            for r in self.policy["nested_resolutions"]
        }
        # canonical key -> normalized text (loaded once; appendix + dedupe)
        self.canonical: dict[str, str] = {}
        for key, rel in sorted(self.policy["canonical_texts"].items()):
            self.canonical[key] = _normalize((ROOT / rel).read_bytes())
        self.lines: list[str] = []

    # ------------------------------------------------------------------

    def emit(self, text: str = "") -> None:
        self.lines.append(text)

    def _evidence_bytes(self, name: str, rel: str) -> bytes:
        member = self.members[name]
        try:
            dist = importlib_metadata.distribution(name)
        except importlib_metadata.PackageNotFoundError:
            raise core.EnvironmentMismatch(
                f"{name} is not installed; the notices generator needs the"
                " locked environment. Remedy: .venv/Scripts/python.exe -m pip"
                " install -c constraints.txt -e .[dev,ssh,credentials,web]"
            )
        expected = member.get("version")
        if expected and dist.version != expected:
            raise core.EnvironmentMismatch(
                f"{name}: installed {dist.version} but the manifest pins"
                f" {expected}; regenerate the manifest or align the"
                " environment before generating notices"
            )
        path = Path(str(dist.locate_file(rel)))
        if not path.is_file():
            raise core.EnvironmentMismatch(
                f"{name}: recorded evidence file missing on disk: {rel}"
            )
        return path.read_bytes()

    def _emit_text_or_reference(self, name: str, rel: str) -> None:
        text = _normalize(self._evidence_bytes(name, rel))
        for key, canonical in self.canonical.items():
            if text == canonical:
                self.emit(f"    Licence text: identical to the canonical"
                          f" {key} text in the appendix.")
                return
        self.emit(f"    -- {rel} --")
        for line in text.splitlines():
            self.emit(f"    {line}")

    def _election_for(self, expression: str, name: str, within: str | None):
        for election in self.policy["elections"]:
            if election["expression"] != expression:
                continue
            for component in election["components"]:
                if component["name"] == name and component.get("within") == within:
                    return election
        return None

    # ------------------------------------------------------------------

    def header(self) -> None:
        self.emit(RULE)
        self.emit("THIRD-PARTY NOTICES — FounderOS Atlas")
        self.emit(RULE)
        self.emit()
        self.emit("GENERATED FILE — DO NOT EDIT BY HAND.")
        self.emit("Regenerate: python scripts/generate_third_party_notices.py")
        self.emit()
        self.emit("Scope: the current runtime dependency closure as recorded in")
        self.emit("compliance/runtime-manifest.json (the single partition rule),")
        self.emit("plus vendored frontend assets recorded in")
        self.emit("compliance/vendored-assets.json. Reviewed conclusions, licence")
        self.emit("elections and evidence exceptions come from")
        self.emit("compliance/license-policy.json. Development-only tooling is not")
        self.emit("distributed and is deliberately not listed.")
        self.emit()
        self.emit("Where a licence expression offers a choice (OR), the elected")
        self.emit("licence is stated and the ORIGINAL expression is preserved.")
        self.emit("Where an expression is conjunctive (AND), every obligation is")
        self.emit("carried. Where a distribution ships no usable licence text, the")
        self.emit("canonical text is supplied and the notice says so.")
        self.emit()
        self.emit("This file records third-party attribution only. It grants no")
        self.emit("rights in Atlas itself, and it contains no Atlas-owned licence")
        self.emit("terms.")
        self.emit()

    def python_distributions(self) -> None:
        self.emit(RULE)
        self.emit("SECTION 1 — PYTHON DISTRIBUTIONS (runtime closure)")
        self.emit(RULE)
        components = self.policy["components"]
        for name in sorted(self.members):
            member = self.members[name]
            if member.get("expansion") == "not-locked":
                continue
            treatment = components[name]
            evidence = member.get("license_evidence") or {}
            self.emit()
            self.emit(THIN)
            self.emit(f"{name} {member.get('version')}")
            self.emit(THIN)
            concluded = treatment["concluded"]
            declared = (
                evidence.get("declared_expression")
                or evidence.get("declared_license")
                or (evidence.get("declared_classifiers") or [""])[0]
            )
            self.emit(f"Licence: {concluded}")
            if declared and declared != concluded:
                self.emit(f"Declared by the distribution as: {declared}")
            election = self._election_for(concluded, name, None)
            if election is not None:
                self.emit(
                    f"Election [{election['id']}]: {election['elected']}"
                    f" (original expression preserved above)"
                )
            exception = self.exceptions.get(name)
            if exception is not None:
                self.emit(f"Evidence note [{exception['id']}]:"
                          f" {exception['observation']} —"
                          f" {exception['resolution']}.")
                attribution = exception.get("attribution")
                if attribution:
                    self.emit(f"Attribution: {attribution}")
            if name in self.reviewed:
                self._reviewed_block(self.reviewed[name])
            files = list(evidence.get("evidence_files") or [])
            if files:
                self.emit("Licence text as shipped:")
                for rel in files:
                    self._emit_text_or_reference(name, rel)
            elif exception is not None:
                key = concluded if concluded in self.canonical else None
                if key:
                    self.emit(
                        f"Licence text: the distribution ships none; the"
                        f" canonical {key} text in the appendix is supplied"
                        " by this generator."
                    )
            self._nested_blocks(name, evidence)

    def _reviewed_block(self, record: dict) -> None:
        attribution = record.get("attribution")
        if attribution:
            self.emit(f"Attribution: {attribution}")
        self.emit(f"Weak-copyleft treatment ({record['family']}):")
        self.emit(f"    This distribution includes the {record['name']} library,")
        self.emit(f"    covered by {record['licence']}. The complete licence text")
        self.emit("    is in the appendix. Complete corresponding source for the")
        self.emit(f"    exact distributed version is provided at:")
        self.emit(f"        {record['source_archive']}")
        self.emit(f"        sha256 {record['source_sha256']}")
        self.emit(f"    Source provenance: {record['source_provenance']}")
        self.emit(f"    Upstream: {record['upstream']}")
        note = record.get("note")
        if note:
            self.emit(f"    Note: {note}")

    def _nested_blocks(self, name: str, evidence: dict) -> None:
        nested_files = list(evidence.get("nested_evidence_files") or [])
        interesting = [
            rel for rel in nested_files
            if "templates/" not in rel  # ntc textfsm data files are not licences
        ]
        for rel in interesting:
            self.emit(f"Nested component evidence ({rel}):")
            self._emit_text_or_reference(name, rel)
        # Nested resolutions declared for this member but carried in dist-info
        # paths (libsodium) or prose (silk icons) rather than package paths.
        for (within, component), record in sorted(self.nested.items()):
            if within != name:
                continue
            self.emit(f"Nested component: {component} — {record['resolution']}")
            self.emit(f"    Kind: {record['kind']}")
            self.emit(f"    Evidence: {record['evidence']}")
            text_rel = record.get("licence_text")
            if text_rel:
                key = next(
                    (
                        k for k, rel in self.policy["canonical_texts"].items()
                        if rel == text_rel
                    ),
                    None,
                )
                if key:
                    self.emit(f"    Licence text: canonical {key} text in the"
                              " appendix.")
        self._sbom_blocks(name, evidence)

    def _sbom_blocks(self, name: str, evidence: dict) -> None:
        sboms = list(evidence.get("component_sboms") or [])
        if not sboms:
            return
        rows: list[tuple[str, str, str]] = []
        for rel in sorted(sboms):
            sbom = json.loads(_normalize(self._evidence_bytes(name, rel)))
            for component in sbom.get("components", []):
                expressions = sorted(
                    {
                        licence.get("expression")
                        or (licence.get("license") or {}).get("id")
                        or (licence.get("license") or {}).get("name")
                        or ""
                        for licence in component.get("licenses", [])
                    }
                )
                rows.append(
                    (
                        component.get("name") or "?",
                        component.get("version") or "?",
                        " / ".join(e for e in expressions if e),
                    )
                )
        self.emit(
            "Statically linked / bundled components (from the distribution's"
            " own SBOMs — every SBOM file is read):"
        )
        for cname, cversion, expression in sorted(rows):
            record = self.nested.get((name, cname))
            if not expression and record is not None:
                self.emit(
                    f"    {cname} {cversion} — no licence declared in the SBOM;"
                    f" resolved as {record['resolution']}"
                    f" [{record['id']}]"
                )
                continue
            election = self._election_for(expression, cname, name)
            if election is not None:
                self.emit(
                    f"    {cname} {cversion} — {expression}"
                    f" [elected: {election['elected']} per {election['id']}]"
                )
            else:
                self.emit(f"    {cname} {cversion} — {expression}")
        self.emit(
            "    Elected and conjunctive licence texts (MIT, Apache-2.0,"
            " BSD-3-Clause, Unicode-3.0, LLVM-exception) are in the appendix."
        )

    def vendored_assets(self) -> None:
        self.emit()
        self.emit(RULE)
        self.emit("SECTION 2 — VENDORED FRONTEND ASSETS")
        self.emit(RULE)
        for component in self.vendored["components"]:
            self.emit()
            self.emit(THIN)
            version = component["version"] or "version not determinable"
            self.emit(f"{component['name']} ({version})")
            self.emit(THIN)
            if component["version"] is None:
                self.emit(f"Version note: {component['version_evidence']}")
            self.emit(f"Licence: {component['licence']}")
            self.emit(f"Attribution: {component['attribution']}")
            self.emit(f"Upstream: {component['upstream']}")
            note = component.get("evidence_note")
            if note:
                self.emit(f"Evidence note: {note}")
            self.emit("Files:")
            for rel in component["files"]:
                self.emit(f"    {rel}")
            self.emit("Licence text as shipped:")
            for rel in component["licence_evidence"]:
                text = _normalize((ROOT / rel).read_bytes())
                self.emit(f"    -- {rel} --")
                for line in text.splitlines():
                    self.emit(f"    {line}")

    def not_locked(self) -> None:
        leaves = self.policy["not_locked_leaves"]
        if not leaves:
            return
        self.emit()
        self.emit(RULE)
        self.emit("SECTION 3 — NOT-LOCKED PLATFORM LEAVES (no evidence held)")
        self.emit(RULE)
        self.emit()
        self.emit("The A0 partition records the following packages as reachable on")
        self.emit("some platform but unpinned in constraints.txt. They are not")
        self.emit("installed here, no licence evidence exists for them, and they are")
        self.emit("not part of any verified distribution set. They must be pinned")
        self.emit("and reviewed before any distribution that would ship them:")
        self.emit()
        for name in sorted(leaves):
            self.emit(f"    {name}")

    def packaging_placeholder(self) -> None:
        self.emit()
        self.emit(RULE)
        self.emit("SECTION 4 — PACKAGING-TIME COMPONENTS (NOT POPULATED)")
        self.emit(RULE)
        self.emit()
        self.emit("Nothing in this section ships today. A future packaged")
        self.emit("distribution (PR-B) adds components that are not part of the")
        self.emit("current runtime closure and MUST populate this section before")
        self.emit("any package is produced:")
        self.emit()
        self.emit("    CPython interpreter — PSF License Version 2")
        self.emit("    PyInstaller bootloader/runtime — per its own licence")
        self.emit("    native runtime libraries introduced by packaging")
        self.emit()
        self.emit("See prb_distribution_contract in compliance/license-policy.json.")

    def appendix(self) -> None:
        self.emit()
        self.emit(RULE)
        self.emit("APPENDIX — CANONICAL LICENCE TEXTS")
        self.emit(RULE)
        for key in sorted(self.canonical):
            self.emit()
            self.emit(THIN)
            self.emit(f"CANONICAL TEXT: {key}")
            self.emit(f"({self.policy['canonical_texts'][key]})")
            self.emit(THIN)
            for line in self.canonical[key].splitlines():
                self.emit(line)

    def build(self) -> str:
        self.header()
        self.python_distributions()
        self.vendored_assets()
        self.not_locked()
        self.packaging_placeholder()
        self.appendix()
        return "\n".join(self.lines).rstrip("\n") + "\n"


def main() -> int:
    text = NoticeBuilder().build()
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(f"Wrote {OUTPUT} ({len(text.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
