"""PR-A0 — the deterministic compliance foundation.

One partition rule, one tracked runtime manifest, one converged SBOM.
These tests pin the properties the PR-A architecture review proved were
missing: determinism, ambient-contamination impossibility, platform-aware
marker evaluation, and a licence-evidence model in which the site-packages
root LICENSE collision is structurally impossible.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _core():
    spec = importlib.util.spec_from_file_location(
        "compliance_core", ROOT / "scripts" / "compliance_core.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("compliance_core", module)
    spec.loader.exec_module(module)
    return module


def _manifest_module():
    core = _core()  # noqa: F841 - ensures sys.modules entry for the import
    spec = importlib.util.spec_from_file_location(
        "runtime_manifest", ROOT / "scripts" / "runtime_manifest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PartitionRuleTests(unittest.TestCase):
    """The ONE runtime/dev membership rule."""

    @classmethod
    def setUpClass(cls):
        cls.core = _core()
        cls.partition = cls.core.compute_partition()

    def test_roots_come_from_project_declarations(self) -> None:
        runtime_roots, dev_roots = self.core.read_roots()
        project = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]
        declared = set(project["dependencies"])
        for extra in self.core.RUNTIME_EXTRAS:
            declared |= set(project["optional-dependencies"][extra])
        self.assertEqual(declared, set(runtime_roots))
        self.assertEqual(
            set(project["optional-dependencies"]["dev"]), set(dev_roots)
        )

    def test_ambient_only_packages_cannot_enter_any_closure(self) -> None:
        # These are installed in the development venv but reachable from
        # neither root set (the review's stray-venv hazard, including an
        # LGPL cairosvg Atlas never imports). Resolution walks from the
        # roots, so they are unreachable by construction.
        for stray in ("cairosvg", "pillow", "build", "tinycss2"):
            self.assertNotIn(stray, self.partition.runtime)
            self.assertNotIn(stray, self.partition.development)
            self.assertNotIn(stray, self.partition.unassigned)

    def test_dev_only_packages_do_not_become_runtime(self) -> None:
        for dev in ("pytest", "pip-audit", "certifi", "requests", "pip"):
            self.assertNotIn(dev, self.partition.runtime)
        self.assertIn("pytest", self.partition.development)
        self.assertIn("certifi", self.partition.development)

    def test_windows_marker_evaluation(self) -> None:
        runtime = self.partition.runtime
        self.assertIn("win32", runtime["pywin32-ctypes"].platforms)
        self.assertNotIn("linux", runtime["pywin32-ctypes"].platforms)
        self.assertIn("win32", runtime["colorama"].platforms)
        self.assertEqual({"win32"}, runtime["colorama"].platforms)

    def test_linux_marker_evaluation(self) -> None:
        runtime = self.partition.runtime
        self.assertEqual({"linux"}, runtime["secretstorage"].platforms)
        self.assertEqual({"linux"}, runtime["jeepney"].platforms)
        # And the lock gap is recorded honestly, not papered over:
        self.assertFalse(runtime["secretstorage"].pinned)
        self.assertEqual("not-locked", runtime["secretstorage"].expansion)

    def test_normalized_naming_is_deterministic(self) -> None:
        normalize = self.core.normalize
        self.assertEqual("pyyaml", normalize("PyYAML"))
        self.assertEqual("ruamel-yaml", normalize("ruamel.yaml"))
        self.assertEqual("jaraco-classes", normalize("jaraco.classes"))
        self.assertEqual("boolean-py", normalize("boolean.py"))
        self.assertEqual(normalize("Flask"), normalize("flask"))

    def test_root_declaration_order_cannot_change_output(self) -> None:
        runtime_roots, _ = self.core.read_roots()
        pins = self.core.read_pins()
        forward = self.core.resolve_closure(runtime_roots, pins, "win32")
        backward = self.core.resolve_closure(
            list(reversed(runtime_roots)), pins, "win32"
        )
        self.assertEqual(
            {k: sorted(m.required_by) for k, m in forward.items()},
            {k: sorted(m.required_by) for k, m in backward.items()},
        )

    def test_missing_installed_package_fails_loudly(self) -> None:
        core = self.core
        pins = {"flask": ("Flask", "999.0")}  # version skew vs installed
        with self.assertRaises(SystemExit) as caught:
            core.resolve_closure(["Flask==999.0"], pins, "win32")
        self.assertIn("does not match constraints.txt", str(caught.exception))


class RuntimeManifestTests(unittest.TestCase):
    """The tracked artifact and its determinism."""

    @classmethod
    def setUpClass(cls):
        cls.module = _manifest_module()
        cls.tracked = ROOT / "compliance" / "runtime-manifest.json"

    def test_generation_is_deterministic(self) -> None:
        first = json.dumps(self.module.build_manifest(), sort_keys=True)
        second = json.dumps(self.module.build_manifest(), sort_keys=True)
        self.assertEqual(first, second)

    def test_tracked_manifest_is_current(self) -> None:
        # The test-level form of the CI diff-check: regenerating must
        # reproduce the tracked file exactly. A stale manifest fails here
        # and in CI.
        regenerated = json.dumps(
            self.module.build_manifest(), indent=2, sort_keys=True
        ) + "\n"
        tracked_bytes = self.tracked.read_bytes()
        self.assertNotIn(b"\r", tracked_bytes, "manifest must be LF-only")
        self.assertEqual(regenerated, tracked_bytes.decode("utf-8"))

    def test_manifest_counts_are_consistent(self) -> None:
        payload = json.loads(self.tracked.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["counts"]["runtime_total"], len(payload["runtime"])
        )
        self.assertEqual(
            payload["counts"]["development_only"],
            len(payload["development_only"]),
        )
        for platform, count in payload["counts"][
            "runtime_by_platform"
        ].items():
            measured = sum(
                1 for entry in payload["runtime"]
                if platform in entry["platforms"]
            )
            self.assertEqual(count, measured, platform)

    def test_ci_checks_both_generated_artifacts(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("scripts/runtime_manifest.py", workflow)
        self.assertIn(
            "git diff --exit-code -- sbom.cdx.json "
            "compliance/runtime-manifest.json",
            workflow,
        )


class LicenceEvidenceModelTests(unittest.TestCase):
    """Structural evidence facts — the collision fix and the hard cases."""

    @classmethod
    def setUpClass(cls):
        cls.core = _core()
        payload = json.loads(
            (ROOT / "compliance" / "runtime-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        cls.by_name = {e["normalized"]: e for e in payload["runtime"]}

    def test_root_license_collision_is_impossible(self) -> None:
        # netmiko and ntc_templates both install a root-level LICENSE that
        # overwrite each other. Neither may claim it as evidence.
        for package in ("netmiko", "ntc-templates"):
            evidence = self.by_name[package]["license_evidence"]
            self.assertIn("LICENSE", evidence["rejected_root_paths"])
            for path in (
                evidence["evidence_files"] + evidence["nested_evidence_files"]
            ):
                self.assertNotEqual(
                    "LICENSE", path,
                    f"{package} must not claim the shared root LICENSE",
                )

    def test_nested_evidence_is_representable(self) -> None:
        netmiko = self.by_name["netmiko"]["license_evidence"]
        self.assertIn(
            "netmiko/_telnetlib/LICENSE", netmiko["nested_evidence_files"]
        )
        werkzeug = self.by_name["werkzeug"]["license_evidence"]
        self.assertIn(
            "werkzeug/debug/shared/ICON_LICENSE.md",
            werkzeug["nested_evidence_files"],
        )

    def test_static_component_sboms_are_representable(self) -> None:
        crypto = self.by_name["cryptography"]["license_evidence"]
        self.assertIn(
            "cryptography-49.0.0.dist-info/sboms/"
            "cryptography-rust.cyclonedx.json",
            crypto["component_sboms"],
        )

    def test_doubly_nested_licence_paths_survive(self) -> None:
        pynacl = self.by_name["pynacl"]["license_evidence"]
        self.assertIn(
            "pynacl-1.6.2.dist-info/licenses/licenses/LICENSE.libsodium.txt",
            pynacl["evidence_files"],
        )

    def test_baseline_exceptions_are_recorded_not_fatal(self) -> None:
        # pyserial: declared licence, zero shipped text. isoduration:
        # metadata UNKNOWN, ISC text bundled. A0 records the facts; the
        # policy decision belongs to the A2 gate.
        pyserial = self.by_name["pyserial"]["license_evidence"]
        self.assertIn("no-license-file-shipped", pyserial["observations"])
        isoduration = self.by_name["isoduration"]["license_evidence"]
        self.assertIn(
            "metadata-license-unknown", isoduration["observations"]
        )
        self.assertIn(
            "bundled-license-text-present", isoduration["observations"]
        )


class SbomConvergenceTests(unittest.TestCase):
    """The SBOM consumes the same partition rule."""

    @classmethod
    def setUpClass(cls):
        cls.core = _core()
        cls.sbom = json.loads(
            (ROOT / "sbom.cdx.json").read_text(encoding="utf-8")
        )
        cls.manifest = json.loads(
            (ROOT / "compliance" / "runtime-manifest.json").read_text(
                encoding="utf-8"
            )
        )

    def _sbom_scope(self, component) -> str:
        return next(
            p["value"] for p in component["properties"]
            if p["name"] == "founderos:scope"
        )

    def test_sbom_and_manifest_agree_on_runtime_membership(self) -> None:
        sbom_runtime = {
            c["name"] for c in self.sbom["components"]
            if self._sbom_scope(c) == "runtime"
        }
        manifest_runtime_pinned = {
            e["normalized"] for e in self.manifest["runtime"] if e["pinned"]
        }
        self.assertEqual(manifest_runtime_pinned, sbom_runtime)

    def test_sbom_uses_normalized_names(self) -> None:
        names = [c["name"] for c in self.sbom["components"]]
        for name in names:
            self.assertEqual(self.core.normalize(name), name)
        self.assertIn("boolean-py", names)
        self.assertIn("ruamel-yaml", names)

    def test_every_component_declares_its_licence_string(self) -> None:
        for component in self.sbom["components"]:
            self.assertTrue(
                component.get("licenses"),
                f"{component['name']} has no declared licence entry",
            )

    def test_sbom_is_current_and_lf(self) -> None:
        raw = (ROOT / "sbom.cdx.json").read_bytes()
        self.assertNotIn(b"\r", raw)


class FoundationScopeGuards(unittest.TestCase):
    """A0 changes the foundation and nothing else."""

    def test_license_content_unchanged(self) -> None:
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("LICENSE NOT YET SELECTED"))

    def test_jsonschema_extra_still_format(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"jsonschema[format]>=4.23,<5"', pyproject)

    def test_rfc3987_still_pinned(self) -> None:
        lock = (ROOT / "constraints.txt").read_text(encoding="utf-8")
        self.assertIn("rfc3987==1.3.8", lock)

    def test_setuptools_floor_is_77(self) -> None:
        pyproject = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        requires = pyproject["build-system"]["requires"]
        self.assertIn("setuptools>=77", requires)


class SdistCompositionTests(unittest.TestCase):
    """The sdist is an allow-list, and lab data cannot enter it."""

    def test_sdist_contains_no_private_material_and_no_tests(self) -> None:
        import tarfile
        import tempfile

        from setuptools import build_meta

        with tempfile.TemporaryDirectory() as tmp:
            import contextlib
            import io
            import os

            cwd = os.getcwd()
            try:
                os.chdir(ROOT)
                with contextlib.redirect_stdout(io.StringIO()):
                    name = build_meta.build_sdist(tmp)
            finally:
                os.chdir(cwd)
            with tarfile.open(Path(tmp) / name) as archive:
                members = archive.getnames()

        banned_segments = (
            "/.atlas/", "/configs/", "/enterprise-memory/",
            "/deliverables/", "/_zip/", "/tests/", "/.git/",
        )
        offenders = [
            m for m in members
            if m.endswith(".zip")
            or any(seg in f"/{m}/" for seg in banned_segments)
        ]
        self.assertEqual([], offenders)
        self.assertTrue(
            any("compliance/runtime-manifest.json" in m for m in members),
            "the runtime manifest must travel with the sdist",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
