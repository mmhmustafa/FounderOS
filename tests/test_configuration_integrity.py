"""PR-181 configuration-collection integrity: guard rails and pins.

Step 1 (guard rails) lands BEFORE any behaviour change and must stay green
through every later step:

- T19: platforms that successfully collect configuration today — FRRouting
  above all, 79% of the measured live estate — keep collecting after the
  collector becomes driver-aware.
- T16: every configuration Atlas has actually collected on this machine
  remains an accepted configuration. The live estate is the one corpus that
  can prove the repair does not fail closed on real data.
- Every CONFIGURATION CommandSpec is required=False: ProductionDriver raises
  AtlasDiscoveryError when a REQUIRED spec hits a transport fault, and that
  exception escapes the CLI collection loop's except clause — one flaky
  device must never end collection for the whole run.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from founderos_atlas.config import (
    NON_COLLECTED_STATUSES,
    STATUS_UNRECOGNISED,
    ConfigurationArtifact,
    collect_configuration,
    write_configuration_artifacts,
)
from founderos_atlas.platforms import capabilities as caps
from founderos_atlas.platforms.registry import default_registry

from tests.test_config_collection import config_outputs, make_collection


# A realistic FRRouting (vtysh) running configuration, shaped like the ones
# the live estate actually holds: hostname, interfaces, BGP, statics.
FRR_RUNNING_CONFIG = (
    "frr version 8.4.2\n"
    "frr defaults traditional\n"
    "hostname chennai-edge\n"
    "!\n"
    "interface eth0\n"
    " ip address 10.30.0.1/31\n"
    "!\n"
    "interface eth1\n"
    " ip address 10.30.0.3/31\n"
    "!\n"
    "router bgp 65040\n"
    " neighbor 10.30.0.0 remote-as 65041\n"
    " neighbor 10.30.0.2 remote-as 65042\n"
    "!\n"
    "ip route 0.0.0.0/0 10.30.0.0\n"
    "line vty\n"
    "!\n"
    "end\n"
)


def _live_estate_configs(limit: int | None = None) -> list[Path]:
    """Every running_config.txt this machine's estate holds (live + history).

    Empty on a machine without an estate — the corpus tests skip then.
    """

    repo = Path(__file__).resolve().parent.parent
    roots = (repo / ".atlas" / "profiles", repo / "configs")
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found.extend(sorted(root.rglob("running_config.txt")))
    return found[:limit] if limit else found


class ConfigurationCommandSpecContractTests(unittest.TestCase):
    """No CONFIGURATION capability may be marked required (PR-181 R7)."""

    def test_every_configuration_commandspec_is_optional(self) -> None:
        checked = 0
        for driver_cls in default_registry().drivers():
            driver = driver_cls()
            try:
                plan = driver.command_plan()
            except (NotImplementedError, AttributeError):
                continue  # legacy PlatformDriver — no CommandSpec plan
            for spec in plan:
                if spec.capability == caps.CONFIGURATION:
                    checked += 1
                    self.assertFalse(
                        spec.required,
                        f"{type(driver).__name__} marks CONFIGURATION required; "
                        "a transport fault on one device would abort the whole "
                        "collection run (production.py raises AtlasDiscoveryError "
                        "for required specs, which the CLI loop does not catch)",
                    )
        self.assertGreaterEqual(
            checked, 8, "expected at least the eight known CONFIGURATION specs"
        )


class ConfigurationDeclarationMatrixTests(unittest.TestCase):
    """T17 (declarations) — every advertised platform's configuration
    command source is explicit. No platform silently falls through."""

    EXPECTED = {
        "cisco-ios-xe": ("show running-config",),
        "cisco-ios": ("show running-config",),
        "cisco-nxos": ("show running-config",),
        "arista-eos": ("show running-config",),
        "junos": ("show configuration | display set", "show configuration"),
        "fortinet-fortios": ("show",),
        "paloalto-panos": ("show config running",),
        "aruba-cx": ("show running-config",),
        "cisco-wlc": ("show run-config commands",),
        # Deliberate declarations of NO configuration command: these
        # ProductionDrivers author a command plan and omit CONFIGURATION.
        "f5-bigip": (),
        "citrix-adc": (),
        "a10-acos": (),
        # PR-181 Step 4: the legacy platforms that used to depend on the
        # collector's hardcoded Cisco command now declare theirs.
        "frr": ("show running-config",),
        "atlaslab-firewall": ("show running-config",),
        "atlaslab-switch": ("show running-config",),
    }

    def test_every_registered_driver_declares_its_position(self) -> None:
        seen = {}
        for driver_cls in default_registry().drivers():
            driver = driver_cls()
            seen[driver.platform_id] = tuple(driver.configuration_commands())
        self.assertEqual(self.EXPECTED, seen)


class CollectionRegressionGuardTests(unittest.TestCase):
    """T19 — what collects today must still collect after the repair."""

    def test_frr_style_configuration_stays_collected(self) -> None:
        # FRRouting is 968 of the live estate's 1430 snapshots. Its vtysh
        # answers the legacy 'show running-config'; the driver declares no
        # CONFIGURATION spec. This pin fails if the repair ever turns that
        # into "unsupported by declaration".
        _, transport, result = make_collection(
            config_outputs(**{"show running-config": FRR_RUNNING_CONFIG})
        )
        artifact = collect_configuration(transport, result, include_optional=False)
        self.assertEqual("complete", artifact.status)
        self.assertEqual(FRR_RUNNING_CONFIG, artifact.running_config)

    def test_classic_ios_configuration_stays_collected(self) -> None:
        _, transport, result = make_collection(config_outputs())
        artifact = collect_configuration(transport, result, include_optional=False)
        self.assertEqual("complete", artifact.status)
        self.assertIn("hostname R1", artifact.running_config)


class LiveEstateCorpusTests(unittest.TestCase):
    """T16 — the repair must not fail closed on any real collected config.

    Runs only where an estate exists; on other machines the corpus is empty
    and the test skips rather than asserting on nothing.
    """

    def test_every_live_configuration_remains_collected(self) -> None:
        corpus = _live_estate_configs()
        if not corpus:
            self.skipTest("no live estate on this machine")
        rejected: list[str] = []
        for path in corpus:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if not text.strip():
                continue  # an empty file was never a collected configuration
            _, transport, result = make_collection(
                config_outputs(**{"show running-config": text})
            )
            artifact = collect_configuration(
                transport, result, include_optional=False
            )
            if artifact.status != "complete" or artifact.running_config != text:
                rejected.append(str(path))
        self.assertEqual(
            [], rejected,
            f"{len(rejected)} of {len(corpus)} real collected configurations "
            "would no longer be accepted",
        )


def _non_collected_artifact(status: str, **overrides) -> ConfigurationArtifact:
    fields = dict(
        device_id="junos:edge-1", hostname="edge-1", vendor="juniper",
        platform="MX204", os_name="Junos", os_version="21.4R3",
        management_ip="10.0.0.9", running_config="", status=status,
        collected_at="2026-08-15T00:00:00Z",
        command_used="show configuration | display set",
        raw_reply="           ^\nunknown command.\n",
        detail="the device rejected every configuration command form",
    )
    fields.update(overrides)
    return ConfigurationArtifact(**fields)


class LiveEstateClassifierCorpusTests(unittest.TestCase):
    """T16 (classifier form) — no real configuration fails the positive test.

    Every running_config.txt the estate holds must classify COLLECTED under
    the shared structural default — the fail-closed direction is a worse bug
    than the one PR-181 fixes.
    """

    def test_every_live_configuration_classifies_collected(self) -> None:
        from founderos_atlas.config.classify import classify_configuration_reply

        corpus = _live_estate_configs()
        if not corpus:
            self.skipTest("no live estate on this machine")
        rejected: list[str] = []
        for path in corpus:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if not text.strip():
                continue
            status, _detail = classify_configuration_reply(None, text)
            if status != "collected":
                rejected.append(f"{path} -> {status}")
        self.assertEqual(
            [], rejected,
            f"{len(rejected)} of {len(corpus)} real configurations "
            "fail the positive structural test",
        )


class HonestArtifactModelTests(unittest.TestCase):
    """PR-181 Step 2 — non-collected outcomes exist without pretending."""

    def test_every_non_collected_status_is_representable(self) -> None:
        for status in sorted(NON_COLLECTED_STATUSES):
            artifact = _non_collected_artifact(status)
            self.assertEqual(status, artifact.status)
            self.assertFalse(artifact.collected)
            self.assertEqual("", artifact.running_config)

    def test_unrecognised_is_a_distinct_honest_outcome(self) -> None:
        self.assertIn(STATUS_UNRECOGNISED, NON_COLLECTED_STATUSES)
        artifact = _non_collected_artifact(STATUS_UNRECOGNISED)
        self.assertEqual("unrecognised", artifact.status)

    def test_a_non_collected_artifact_rejects_configuration_content(self) -> None:
        with self.assertRaises(ValueError):
            _non_collected_artifact(
                "unsupported", running_config="hostname sneaky\n"
            )

    def test_a_collected_artifact_still_requires_content(self) -> None:
        with self.assertRaises(ValueError):
            _non_collected_artifact("complete")  # empty running_config

    def test_metadata_never_claims_content_it_does_not_hold(self) -> None:
        metadata = _non_collected_artifact("unsupported").to_metadata_dict()
        self.assertEqual("unsupported", metadata["collection_status"])
        self.assertIsNone(metadata["running_config_sha256"])
        self.assertEqual(0, metadata["running_config_lines"])
        # The raw device reply is forensic material, never metadata.
        self.assertNotIn("unknown command", str(metadata))

    def test_storage_refuses_a_non_collected_artifact(self) -> None:
        import tempfile

        artifact = _non_collected_artifact("unsupported")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_configuration_artifacts(artifact, Path(tmp) / "edge-1")
            self.assertEqual([], list(Path(tmp).rglob("running_config.txt")))


class HonestSummaryTests(unittest.TestCase):
    """T14 — the collection summary never counts a non-collection."""

    def test_configuration_history_counts_only_real_collections(self) -> None:
        from founderos_runtime.cli.commands import _configuration_history

        overall, configured, directories = _configuration_history((
            ("r1", "complete", r"C:\out\r1"),
            ("fw1", "partial", r"C:\out\fw1"),
            ("jn1", "unsupported", "the device rejected every command form"),
            ("jn2", "unrecognised", "reply could not be confirmed"),
            ("jn3", "denied", "the account lacks privilege"),
            ("jn4", "failed", "connection lost"),
        ))
        self.assertEqual(2, configured)
        self.assertEqual({"r1", "fw1"}, set(directories))
        self.assertEqual("partial", overall)

    def test_all_non_collected_is_not_reported_as_collected(self) -> None:
        from founderos_runtime.cli.commands import _configuration_history

        overall, configured, directories = _configuration_history((
            ("jn1", "unsupported", "refused"),
            ("jn2", "unrecognised", "unconfirmed"),
        ))
        self.assertEqual(0, configured)
        self.assertEqual({}, directories)
        self.assertNotIn(overall, ("collected", "partial"))

    def test_render_distinguishes_reasons_from_artifact_paths(self) -> None:
        # A reason line must never render with the artifact arrow: only
        # complete/partial entries point at a directory.
        import inspect

        from founderos_runtime.cli import render

        source = inspect.getsource(render.render_atlas_discover)
        self.assertIn('status in ("complete", "partial")', source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
