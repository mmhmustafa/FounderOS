"""PR-A2a — the third-party compliance surface.

The licence policy, the SPDX-aware gate, the deterministic notices
generator, the LGPL/MPL corresponding-source material, and the guards
proving A2a did NOT implement A2b: the Atlas-owned LICENSE is untouched,
no evaluation grant exists, no proprietary metadata landed. These tests
pin the properties the PR-A2 architecture review proved were required —
elections recorded separately from preserved original expressions, AND
never flattened to OR, nested SBOMs all read, root-level licence paths
never attributed, and notices driven by the runtime manifest rather than
the ambient virtual environment.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "compliance" / "license-policy.json"
VENDORED_PATH = ROOT / "compliance" / "vendored-assets.json"
MANIFEST_PATH = ROOT / "compliance" / "runtime-manifest.json"
NOTICES_PATH = ROOT / "THIRD-PARTY-NOTICES.txt"


def _load_script(name: str):
    if "compliance_core" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "compliance_core", ROOT / "scripts" / "compliance_core.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["compliance_core"] = module
        spec.loader.exec_module(module)
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


def _gate():
    return _load_script("check_licenses")


def _generator():
    return _load_script("generate_third_party_notices")


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


class PolicyDocumentTests(unittest.TestCase):
    """The machine-readable policy is complete and internally coherent."""

    @classmethod
    def setUpClass(cls):
        cls.policy = _policy()
        cls.manifest = _manifest()
        cls.members = {e["normalized"]: e for e in cls.manifest["runtime"]}

    def test_every_runtime_member_has_policy_treatment(self) -> None:
        self.assertEqual(
            set(self.members), set(self.policy["components"])
        )

    def test_every_locked_member_has_concluded_licence(self) -> None:
        for name, member in self.members.items():
            treatment = self.policy["components"][name]
            if member.get("expansion") == "not-locked":
                self.assertIsNone(treatment["concluded"], name)
            else:
                self.assertTrue(treatment["concluded"], name)

    def test_forbidden_families_cover_gpl_and_agpl(self) -> None:
        forbidden = set(self.policy["spdx"]["forbidden_runtime_families"])
        for required in (
            "GPL-2.0-only", "GPL-3.0-only", "GPL-3.0-or-later",
            "AGPL-3.0-only", "AGPL-3.0-or-later",
        ):
            self.assertIn(required, forbidden)

    def test_allowed_reviewed_forbidden_are_disjoint(self) -> None:
        spdx = self.policy["spdx"]
        allowed = set(spdx["allowed_families"])
        reviewed = set(spdx["reviewed_weak_copyleft"])
        forbidden = set(spdx["forbidden_runtime_families"])
        self.assertFalse(allowed & reviewed)
        self.assertFalse(allowed & forbidden)
        self.assertFalse(reviewed & forbidden)

    def test_not_locked_leaves_match_manifest(self) -> None:
        manifest_leaves = {
            n for n, m in self.members.items()
            if m.get("expansion") == "not-locked"
        }
        self.assertEqual(manifest_leaves, set(self.policy["not_locked_leaves"]))

    def test_canonical_texts_exist_and_are_lf(self) -> None:
        for key, rel in self.policy["canonical_texts"].items():
            path = ROOT / rel
            self.assertTrue(path.is_file(), rel)
            self.assertNotIn(b"\r", path.read_bytes(), rel)


class SpdxSemanticsTests(unittest.TestCase):
    """OR is a recorded choice; AND preserves every obligation."""

    @classmethod
    def setUpClass(cls):
        cls.gate = _gate()

    def _check(self):
        return self.gate.PolicyCheck()

    def test_unelected_disjunction_fails(self) -> None:
        check = self._check()
        check.evaluate(
            "Apache-2.0 OR GPL-2.0-only", "synthetic",
            election_key=("no-such-component", None),
        )
        self.assertTrue(
            any("no recorded election" in p for p in check.problems)
        )

    def test_elected_disjunction_passes(self) -> None:
        check = self._check()
        check.evaluate(
            "Apache-2.0 OR GPL-2.0-only", "self_cell",
            election_key=("self_cell", "cryptography"),
        )
        self.assertEqual([], check.problems)

    def test_and_with_forbidden_arm_fails_despite_allowed_arm(self) -> None:
        check = self._check()
        check.evaluate("MIT AND GPL-2.0-only", "synthetic")
        self.assertTrue(
            any("forbidden licence GPL-2.0-only" in p for p in check.problems)
        )

    def test_election_records_original_expression_separately(self) -> None:
        policy = _policy()
        for election in policy["elections"]:
            self.assertNotEqual(
                election["expression"], election["elected"], election["id"]
            )
            self.assertTrue(election["components"], election["id"])
            self.assertTrue(election["rationale"], election["id"])

    def test_invalid_election_is_rejected(self) -> None:
        check = self._check()
        self.assertFalse(
            check.election_satisfies("GPL-2.0-only", "MIT OR Apache-2.0")
        )
        self.assertFalse(
            check.election_satisfies("BSD-2-Clause", "MIT OR Apache-2.0")
        )

    def test_conjunctive_arm_cannot_be_elected_away(self) -> None:
        check = self._check()
        self.assertFalse(
            check.election_satisfies(
                "MIT", "(MIT OR Apache-2.0) AND Unicode-3.0"
            )
        )
        self.assertTrue(
            check.election_satisfies(
                "MIT AND Unicode-3.0", "(MIT OR Apache-2.0) AND Unicode-3.0"
            )
        )

    def test_unknown_symbol_is_unresolved_not_pass(self) -> None:
        check = self._check()
        check.evaluate("W3C-19980720", "synthetic")
        self.assertTrue(any("unresolved" in p for p in check.problems))

    def test_llvm_exception_is_carried_and_allowed(self) -> None:
        check = self._check()
        check.evaluate("Apache-2.0 WITH LLVM-exception", "synthetic")
        self.assertEqual([], check.problems)
        check.evaluate("Apache-2.0 WITH Classpath-exception-2.0", "synthetic")
        self.assertTrue(
            any("not on the allowed_exceptions list" in p
                for p in check.problems)
        )


class GateBaselineTests(unittest.TestCase):
    """The gate is green on the real closure and driven by the manifest."""

    @classmethod
    def setUpClass(cls):
        cls.gate = _gate()
        cls.check = cls.gate.PolicyCheck()
        cls.problems = cls.check.run()

    def test_gate_passes_on_the_real_closure(self) -> None:
        self.assertEqual([], self.problems)

    def test_zero_gpl_and_zero_agpl_in_runtime(self) -> None:
        # The concluded expressions were all evaluated by the gate run above
        # with zero problems, so no forbidden family is REQUIRED anywhere.
        # Belt: no locked member's concluded expression even mentions AGPL,
        # and any GPL mention is inside a recorded, elected disjunction.
        policy = _policy()
        for name, treatment in policy["components"].items():
            concluded = treatment.get("concluded") or ""
            self.assertNotIn("AGPL", concluded, name)
            if "GPL-" in concluded.replace("LGPL-", ""):
                self.assertIn(" OR ", concluded, name)

    def test_gate_is_manifest_driven_not_venv_driven(self) -> None:
        manifest_names = {
            e["normalized"] for e in _manifest()["runtime"]
        }
        self.assertEqual(manifest_names, set(self.check.members))
        # Installed-but-ambient packages never enter the gate's universe.
        for ambient in ("pillow", "cairosvg", "build", "pytest", "pip-audit"):
            self.assertNotIn(ambient, self.check.members)

    def test_dev_only_certifi_stays_out_of_runtime_and_notices(self) -> None:
        self.assertNotIn("certifi", self.check.members)
        notices = NOTICES_PATH.read_text(encoding="utf-8")
        self.assertNotIn("\ncertifi", notices)


class GateFailureModeTests(unittest.TestCase):
    """Every mandated failure mode actually fails."""

    def setUp(self):
        self.gate = _gate()
        self.check = self.gate.PolicyCheck()

    def test_forbidden_runtime_licence_fails(self) -> None:
        self.check.policy["components"]["attrs"] = {
            "concluded": "GPL-3.0-or-later", "basis": ["synthetic"],
        }
        self.check.check_members()
        self.assertTrue(
            any("forbidden licence GPL-3.0-or-later" in p
                for p in self.check.problems)
        )

    def test_agpl_runtime_licence_fails(self) -> None:
        self.check.policy["components"]["attrs"] = {
            "concluded": "AGPL-3.0-only", "basis": ["synthetic"],
        }
        self.check.check_members()
        self.assertTrue(
            any("forbidden licence AGPL-3.0-only" in p
                for p in self.check.problems)
        )

    def test_member_without_policy_treatment_fails(self) -> None:
        del self.check.policy["components"]["attrs"]
        self.check.check_membership()
        self.assertTrue(
            any("attrs has no policy treatment" in p
                for p in self.check.problems)
        )

    def test_member_without_evidence_fails(self) -> None:
        member = copy.deepcopy(self.check.members["attrs"])
        member["license_evidence"]["evidence_files"] = []
        member["license_evidence"]["nested_evidence_files"] = []
        self.check.members["attrs"] = member
        self.check.check_members()
        self.assertTrue(
            any("attrs: no licence evidence" in p
                for p in self.check.problems)
        )

    def test_missing_source_archive_fails(self) -> None:
        for record in self.check.policy["reviewed_components"]:
            if record["name"] == "paramiko":
                record["source_archive"] = (
                    "compliance/third-party-source/does-not-exist.tar.gz"
                )
        self.check.check_reviewed()
        self.assertTrue(
            any("corresponding source archive missing" in p
                for p in self.check.problems)
        )

    def test_source_archive_hash_mismatch_fails(self) -> None:
        for record in self.check.policy["reviewed_components"]:
            if record["name"] == "scp":
                record["source_sha256"] = "0" * 64
        self.check.check_reviewed()
        self.assertTrue(
            any("sha256 mismatch" in p for p in self.check.problems)
        )

    def test_reviewed_version_bump_fails(self) -> None:
        member = copy.deepcopy(self.check.members["paramiko"])
        member["version"] = "5.0.0"
        self.check.members["paramiko"] = member
        self.check.check_reviewed()
        self.assertTrue(
            any("version pin 4.0.0 does not match manifest 5.0.0" in p
                for p in self.check.problems)
        )

    def test_paramiko_policy_and_security_exception_pin_together(self) -> None:
        for record in self.check.policy["reviewed_components"]:
            if record["name"] == "paramiko":
                record["version"] = "4.1.0"
        self.check.reviewed_by_name = {
            r["name"]: r for r in self.check.policy["reviewed_components"]
        }
        self.check.members["paramiko"] = dict(
            self.check.members["paramiko"], version="4.1.0"
        )
        self.check.check_reviewed()
        self.assertTrue(
            any("the two gates must move together" in p
                for p in self.check.problems)
        )

    def test_stale_pyserial_exception_fails(self) -> None:
        member = copy.deepcopy(self.check.members["pyserial"])
        member["license_evidence"]["observations"] = []
        self.check.members["pyserial"] = member
        self.check.check_exception_evidence()
        self.assertTrue(
            any("EXC-PYSERIAL is stale" in p for p in self.check.problems)
        )

    def test_stale_isoduration_exception_fails(self) -> None:
        member = copy.deepcopy(self.check.members["isoduration"])
        member["license_evidence"]["observations"] = ["bundled-license-text-present"]
        self.check.members["isoduration"] = member
        self.check.check_exception_evidence()
        self.assertTrue(
            any("EXC-ISODURATION is stale" in p for p in self.check.problems)
        )

    def test_resolved_rfc3987_syntax_discrepancy_fails_as_stale(self) -> None:
        member = copy.deepcopy(self.check.members["rfc3987-syntax"])
        member["license_evidence"]["declared_classifiers"] = [
            "OSI Approved :: MIT License"
        ]
        self.check.members["rfc3987-syntax"] = member
        self.check.check_exception_evidence()
        self.assertTrue(
            any("EXC-RFC3987-SYNTAX is stale" in p
                for p in self.check.problems)
        )

    def test_missing_nested_sbom_fails(self) -> None:
        member = copy.deepcopy(self.check.members["cryptography"])
        member["license_evidence"]["component_sboms"] = [
            "cryptography-49.0.0.dist-info/sboms/gone.json"
        ]
        self.check.members["cryptography"] = member
        self.check.check_nested()
        self.assertTrue(
            any("recorded evidence file missing" in p
                for p in self.check.problems)
        )

    def test_missing_openssl_resolution_fails(self) -> None:
        self.check.policy["nested_resolutions"] = [
            r for r in self.check.policy["nested_resolutions"]
            if r["id"] != "NEST-OPENSSL"
        ]
        self.check.check_nested()
        self.assertTrue(
            any("openssl" in p and "no nested_resolutions record" in p
                for p in self.check.problems)
        )

    def test_unlisted_vendored_file_fails(self) -> None:
        self.check.vendored["components"] = [
            c for c in self.check.vendored["components"]
            if c["name"] != "Cytoscape.js"
        ]
        self.check.check_vendored()
        self.assertTrue(
            any("cytoscape.min.js has no evidence entry" in p
                for p in self.check.problems)
        )

    def test_missing_canonical_text_fails(self) -> None:
        self.check.policy["canonical_texts"]["MIT"] = (
            "compliance/licenses/absent.txt"
        )
        self.check.check_canonical_texts()
        self.assertTrue(
            any("canonical text MIT missing" in p
                for p in self.check.problems)
        )


class AmberMaterialTests(unittest.TestCase):
    """LGPL/MPL treatment: exact versions, texts, corresponding source."""

    @classmethod
    def setUpClass(cls):
        cls.policy = _policy()
        cls.reviewed = {r["name"]: r for r in cls.policy["reviewed_components"]}
        cls.members = {
            e["normalized"]: e for e in _manifest()["runtime"]
        }

    def test_reviewed_set_is_exactly_the_amber_three(self) -> None:
        self.assertEqual(
            {"paramiko", "scp", "fqdn"}, set(self.reviewed)
        )

    def test_paramiko_licence_and_version_pinned(self) -> None:
        record = self.reviewed["paramiko"]
        self.assertEqual("4.0.0", record["version"])
        self.assertEqual("LGPL-2.1-only", record["licence"])
        self.assertEqual("4.0.0", self.members["paramiko"]["version"])

    def test_scp_licence_and_version_pinned(self) -> None:
        record = self.reviewed["scp"]
        self.assertEqual("0.15.0", record["version"])
        self.assertEqual("LGPL-2.1-or-later", record["licence"])

    def test_fqdn_licence_and_version_pinned(self) -> None:
        record = self.reviewed["fqdn"]
        self.assertEqual("1.5.1", record["version"])
        self.assertEqual("MPL-2.0", record["licence"])

    def test_source_archives_present_and_hash_pinned(self) -> None:
        for name, record in self.reviewed.items():
            archive = ROOT / record["source_archive"]
            self.assertTrue(archive.is_file(), name)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(record["source_sha256"], digest, name)

    def test_archives_contain_the_exact_distributed_versions(self) -> None:
        expected_roots = {
            "paramiko": "paramiko-4.0.0/",
            "scp": "scp-0.15.0/",
            "fqdn": "fqdn-1.5.1/",
        }
        expected_member = {
            "paramiko": "paramiko-4.0.0/paramiko/client.py",
            "scp": "scp-0.15.0/scp.py",
            "fqdn": "fqdn-1.5.1/fqdn/__init__.py",
        }
        for name, record in self.reviewed.items():
            with tarfile.open(ROOT / record["source_archive"]) as tar:
                names = tar.getnames()
            self.assertTrue(
                all(n.startswith(expected_roots[name].rstrip("/"))
                    for n in names),
                name,
            )
            self.assertIn(expected_member[name], names, name)

    def test_full_lgpl_and_mpl_texts_are_stored(self) -> None:
        lgpl = (ROOT / "compliance/licenses/LGPL-2.1.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("GNU LESSER GENERAL PUBLIC LICENSE", lgpl)
        self.assertGreater(len(lgpl), 25000)  # the full text, not a notice
        mpl = (ROOT / "compliance/licenses/MPL-2.0.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("Mozilla Public License Version 2.0", mpl)
        self.assertIn("3.2. Distribution of Executable Form", mpl)

    def test_netmiko_still_requires_scp_at_import_time(self) -> None:
        # Measured, not assumed: the reason scp cannot be dropped.
        import netmiko  # noqa: F401

        self.assertIn("scp", sys.modules)

    def test_atlas_source_does_not_import_or_vendor_scp(self) -> None:
        pattern = re.compile(r"^\s*(import scp\b|from scp\b)", re.MULTILINE)
        offenders = []
        for path in (ROOT / "src").rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                offenders.append(str(path))
        self.assertEqual([], offenders)

    def test_archive_format_is_tar_gz_never_zip(self) -> None:
        # MANIFEST.in globally excludes *.zip; a .zip source archive would
        # silently vanish from the sdist (PR-A2 amendment F).
        stored = list((ROOT / "compliance/third-party-source").iterdir())
        self.assertTrue(stored)
        for path in stored:
            self.assertTrue(path.name.endswith(".tar.gz"), path.name)


class NestedGraphTests(unittest.TestCase):
    """One distribution is not one obligation: SBOMs, nested texts, assets."""

    @classmethod
    def setUpClass(cls):
        cls.members = {e["normalized"]: e for e in _manifest()["runtime"]}
        cls.notices = NOTICES_PATH.read_text(encoding="utf-8")

    def test_cryptography_lists_both_sboms(self) -> None:
        sboms = self.members["cryptography"]["license_evidence"][
            "component_sboms"
        ]
        self.assertEqual(2, len(sboms))

    def test_openssl_static_linkage_represented(self) -> None:
        self.assertIn(
            "openssl 4.0.1 — no licence declared in the SBOM;"
            " resolved as Apache-2.0 [NEST-OPENSSL]",
            self.notices,
        )

    def test_cryptography_rust_crates_represented(self) -> None:
        self.assertIn(
            "self_cell 1.2.2 — Apache-2.0 OR GPL-2.0-only"
            " [elected: Apache-2.0 per ELECT-SELF-CELL]",
            self.notices,
        )
        self.assertIn("asn1 0.24.1 — BSD-3-Clause", self.notices)

    def test_rpds_py_rust_crates_represented(self) -> None:
        self.assertIn("archery 1.2.2 — MIT", self.notices)
        self.assertIn("rpds 1.2.1 — MIT", self.notices)

    def test_unicode_conjunction_carried(self) -> None:
        self.assertIn(
            "unicode-ident 1.0.24 — (MIT OR Apache-2.0) AND Unicode-3.0"
            " [elected: MIT AND Unicode-3.0 per ELECT-UNICODE-IDENT-INNER]",
            self.notices,
        )
        self.assertIn("CANONICAL TEXT: Unicode-3.0", self.notices)

    def test_libsodium_represented(self) -> None:
        self.assertIn("libsodium", self.notices)
        self.assertIn("LICENSE.libsodium.txt", self.notices)

    def test_telnetlib_psf_obligation_live_today(self) -> None:
        self.assertIn("netmiko/_telnetlib/LICENSE", self.notices)
        self.assertIn("PSF-2.0", self.notices)

    def test_silk_icons_election_and_attribution(self) -> None:
        self.assertIn("Silk icon set 1.3", self.notices)
        self.assertIn("CC-BY-3.0", self.notices)

    def test_root_level_licence_paths_never_attributed(self) -> None:
        # The netmiko/ntc_templates collision: root paths are recorded as
        # rejected in the manifest and the generator never renders one.
        for name in ("netmiko", "ntc-templates"):
            evidence = self.members[name]["license_evidence"]
            self.assertTrue(evidence["rejected_root_paths"], name)
            for rel in evidence["evidence_files"]:
                self.assertIn("/", rel, name)
        self.assertNotIn("\n    -- LICENSE --\n", self.notices)


class NoticesDeterminismTests(unittest.TestCase):
    """Byte-stable generation, manifest-driven universe, tracked freshness."""

    @classmethod
    def setUpClass(cls):
        cls.generator = _generator()
        cls.tracked = NOTICES_PATH.read_bytes()

    def test_double_generation_is_byte_identical(self) -> None:
        first = self.generator.NoticeBuilder().build().encode("utf-8")
        second = self.generator.NoticeBuilder().build().encode("utf-8")
        self.assertEqual(first, second)

    def test_tracked_notices_match_regeneration(self) -> None:
        # The CI interlock in one assert: a stale tracked file fails here.
        regenerated = self.generator.NoticeBuilder().build().encode("utf-8")
        self.assertEqual(self.tracked, regenerated)

    def test_no_cr_bytes_and_lf_ending(self) -> None:
        self.assertNotIn(b"\r", self.tracked)
        self.assertTrue(self.tracked.endswith(b"\n"))

    def test_generator_uses_no_clock(self) -> None:
        source = (ROOT / "scripts" / "generate_third_party_notices.py").read_text(
            encoding="utf-8"
        )
        for banned in ("datetime", "time.time", "strftime", "now()"):
            self.assertNotIn(banned, source)

    def test_notices_universe_is_exactly_the_locked_closure(self) -> None:
        members = {e["normalized"]: e for e in _manifest()["runtime"]}
        locked = {
            n for n, m in members.items()
            if m.get("expansion") != "not-locked"
        }
        text = self.tracked.decode("utf-8")
        section = text.split("SECTION 1")[1].split("SECTION 2")[0]
        listed = set(
            re.findall(r"^([a-z0-9-]+) \S+$", section, re.MULTILINE)
        )
        self.assertEqual(locked, listed)

    def test_ambient_distributions_never_enter_notices(self) -> None:
        text = self.tracked.decode("utf-8")
        for ambient in ("pillow", "Pillow", "cairosvg", "CairoSVG",
                        "pip-audit", "pytest "):
            self.assertNotIn(f"\n{ambient} ", text)

    def test_not_locked_leaves_are_declared_not_omitted(self) -> None:
        text = self.tracked.decode("utf-8")
        self.assertIn("SECTION 3 — NOT-LOCKED PLATFORM LEAVES", text)
        for leaf in ("secretstorage", "jeepney", "typing-extensions"):
            self.assertIn(leaf, text)

    def test_packaging_placeholder_present_and_unpopulated(self) -> None:
        text = self.tracked.decode("utf-8")
        self.assertIn("SECTION 4 — PACKAGING-TIME COMPONENTS (NOT POPULATED)",
                      text)
        self.assertIn("CPython interpreter — PSF License Version 2", text)
        self.assertIn("PyInstaller bootloader", text)
        self.assertIn("Nothing in this section ships today", text)


class VendoredAssetTests(unittest.TestCase):
    """Frontend assets are evidence-recorded, versioned honestly."""

    @classmethod
    def setUpClass(cls):
        cls.vendored = json.loads(VENDORED_PATH.read_text(encoding="utf-8"))
        cls.notices = NOTICES_PATH.read_text(encoding="utf-8")

    def test_every_vendor_file_is_recorded(self) -> None:
        recorded = {
            rel
            for component in self.vendored["components"]
            for rel in component["files"]
        } | set(self.vendored["evidence_files"])
        for directory in self.vendored["directories"]:
            for path in (ROOT / directory).rglob("*"):
                if path.is_file():
                    rel = path.relative_to(ROOT).as_posix()
                    self.assertIn(rel, recorded, rel)

    def test_cytoscape_version_recoverable_and_recorded(self) -> None:
        self.assertIn("Cytoscape.js (3.29.2)", self.notices)

    def test_xterm_versions_declared_unrecoverable_not_invented(self) -> None:
        self.assertIn("xterm.js (version not determinable)", self.notices)
        self.assertIn("xterm-addon-fit (version not determinable)",
                      self.notices)

    def test_no_font_files_ship(self) -> None:
        for suffix in ("*.woff", "*.woff2", "*.ttf", "*.otf", "*.eot"):
            self.assertEqual(
                [], list((ROOT / "src").rglob(suffix)), suffix
            )


class SdistComplianceTests(unittest.TestCase):
    """The compliance surface travels; nothing private leaks."""

    @classmethod
    def setUpClass(cls):
        import setuptools.build_meta as backend

        cls.tmpdir = tempfile.mkdtemp(prefix="a2a-sdist-")
        name = backend.build_sdist(cls.tmpdir)
        with tarfile.open(Path(cls.tmpdir) / name) as tar:
            cls.names = [
                n.split("/", 1)[1] for n in tar.getnames() if "/" in n
            ]
            member = tar.getmember(
                name.removesuffix(".tar.gz") + "/THIRD-PARTY-NOTICES.txt"
            )
            cls.notices_size = member.size

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_notices_travel_non_empty(self) -> None:
        self.assertIn("THIRD-PARTY-NOTICES.txt", self.names)
        self.assertGreater(self.notices_size, 100000)

    def test_policy_and_licences_travel(self) -> None:
        self.assertIn("compliance/license-policy.json", self.names)
        self.assertIn("compliance/vendored-assets.json", self.names)
        self.assertEqual(
            7,
            sum(1 for n in self.names
                if n.startswith("compliance/licenses/")),
        )

    def test_source_archives_travel_as_tar_gz(self) -> None:
        archives = [
            n for n in self.names
            if n.startswith("compliance/third-party-source/")
        ]
        self.assertEqual(3, len(archives))
        for archive in archives:
            self.assertTrue(archive.endswith(".tar.gz"), archive)

    def test_no_zip_no_tests_no_private_data(self) -> None:
        for name in self.names:
            self.assertFalse(name.endswith(".zip"), name)
            for banned in ("tests/", ".atlas/", "configs/",
                           "enterprise-memory/", "deliverables/", "_zip/"):
                self.assertFalse(name.startswith(banned), name)


class A2bNonPrejudgmentTests(unittest.TestCase):
    """A2a did not implement A2b. Hard gate."""

    def test_license_file_unchanged(self) -> None:
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("LICENSE NOT YET SELECTED"))
        self.assertNotIn("Effective date", text)
        self.assertNotIn("Mohammed Mustafa Hussain", text)

    def test_no_proprietary_pep639_metadata(self) -> None:
        project = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]
        self.assertNotIn("license", project)
        self.assertNotIn("license-files", project)
        self.assertNotIn("authors", project)

    def test_no_licenseref_anywhere_in_metadata(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("LicenseRef-", pyproject)

    def test_compliance_surface_grants_no_atlas_rights(self) -> None:
        notices = NOTICES_PATH.read_text(encoding="utf-8")
        self.assertIn("It grants no", notices)
        self.assertIn("rights in Atlas itself", notices)
        # Assertion-shaped, not substring-shaped (the PR-A2 review's lesson):
        # word-bounded patterns, and the policy's a2b_requirements section is
        # excluded because NAMING "effective date" as an outstanding A2b
        # requirement is the opposite of supplying one.
        # Third-party licence TEXTS may legitimately contain such phrases —
        # MPL-2.0 itself defines "Effective Date" — so the full ban applies
        # to the Atlas-authored surfaces (policy minus the a2b_requirements
        # record, the vendored-asset evidence, and the notices' generator-
        # authored header), never to inlined third-party texts.
        policy = _policy()
        del policy["a2b_requirements"]
        header = notices.split("SECTION 1")[0]
        surfaces = {
            "license-policy.json (minus a2b_requirements)": json.dumps(policy),
            "vendored-assets.json": VENDORED_PATH.read_text(encoding="utf-8"),
            "THIRD-PARTY-NOTICES.txt header": header,
        }
        banned = (
            r"evaluation grant", r"governing law", r"arbitration",
            r"non-disclosure", r"\bNDA\b", r"effective date",
            r"telemetry", r"activation", r"licen[cs]e key",
        )
        for label, text in surfaces.items():
            for pattern in banned:
                self.assertIsNone(
                    re.search(pattern, text, re.IGNORECASE),
                    f"{label}: {pattern}",
                )

    def test_policy_records_a2b_as_outstanding(self) -> None:
        policy = _policy()
        requirements = policy["a2b_requirements"]
        self.assertIn("NOT IMPLEMENTED", requirements["status"])
        ids = {r["id"] for r in requirements["requirements"]}
        self.assertIn("A2B-REQ-1", ids)
        text = json.dumps(requirements)
        self.assertIn("reverse engineering", text)
        self.assertIn("modification", text)

    def test_prb_contract_established(self) -> None:
        policy = _policy()
        contract = policy["prb_distribution_contract"]
        self.assertIn("NOT STARTED", contract["status"])
        ids = {r["id"] for r in contract["requirements"]}
        self.assertEqual(
            {"PRB-REQ-1", "PRB-REQ-2", "PRB-REQ-3", "PRB-REQ-4"}, ids
        )
        replaceability = next(
            r for r in contract["requirements"] if r["id"] == "PRB-REQ-1"
        )
        self.assertIn("replaceable", replaceability["requirement"])
        self.assertIn("verification", replaceability)


class RepositoryConsistencyTests(unittest.TestCase):
    """README/strategy statements agree with the A2a truth."""

    def test_readme_states_a2a_truth_without_overclaiming(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("THIRD-PARTY-NOTICES.txt", readme)
        self.assertIn("not authorized", readme)
        for overclaim in ("commercially released", "production ready",
                          "generally available"):
            self.assertNotIn(overclaim, readme)

    def test_strategy_doc_marked_non_authoritative(self) -> None:
        strategy = (ROOT / "docs/strategy/PRODUCT_REVIEW_ZERO.md").read_text(
            encoding="utf-8"
        )
        marker = strategy.index("Historical / non-authoritative")
        open_core = strategy.index("Permissive (Apache-2.0)")
        self.assertLess(marker, open_core)

    def test_ui_open_source_buttons_are_not_licensing_statements(self) -> None:
        # Known false-positive surface for naive substring checks: the
        # inbox "Open source" button opens the source of an item. It must
        # keep existing (the consistency checks above are scoped and never
        # read templates).
        inbox = (ROOT / "src/founderos_atlas/web/templates/inbox.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("Open source", inbox)

    def test_source_zips_removed_from_head(self) -> None:
        git = shutil.which("git")
        if git is None:
            self.skipTest("git unavailable")
        result = subprocess.run(
            [git, "ls-files", "*.zip"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        self.assertEqual("", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
