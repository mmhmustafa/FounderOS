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


class _ScriptedTransport:
    """A driver-aware scripted device: answers what it knows, refuses the
    rest in its own platform's words. Satisfies DeviceTransport."""

    def __init__(self, outputs: dict, refusal: str) -> None:
        self.outputs = dict(outputs)
        self.refusal = refusal
        self.sent: list[str] = []
        self.disconnected = False

    def connect(self) -> None:  # pragma: no cover - trivial
        return None

    def disconnect(self) -> None:
        self.disconnected = True

    def execute(self, command: str) -> str:
        self.sent.append(command)
        return self.outputs.get(command, self.refusal)

    def execute_many(self, commands):
        return {command: self.execute(command) for command in commands}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.disconnect()
        return False


def _registered_transport(outputs: dict, refusal: str) -> _ScriptedTransport:
    from founderos_atlas.transport import DeviceTransport

    if not issubclass(_ScriptedTransport, DeviceTransport):
        DeviceTransport.register(_ScriptedTransport)
    return _ScriptedTransport(outputs, refusal)


class DriverAwareCollectionTests(unittest.TestCase):
    """T3–T9 + the §2 beta-blocker checkpoint: driver-owned collection."""

    def _discover(self, fixture_module):
        registry = default_registry()
        outputs = fixture_module.normal()
        transport = _registered_transport(
            outputs, getattr(fixture_module, "UNSUPPORTED", "unknown command.")
        )
        probe = None
        driver = None
        for probe_command in registry.probe_commands():
            probe = outputs.get(probe_command)
            if probe is None:
                continue
            driver = registry.detect(probe)
            if driver is not None:
                break
        assert driver is not None
        discovery = driver.discover(
            transport, management_ip_hint="10.0.0.99", probe_output=probe
        )
        return discovery.result

    def test_junos_refusal_never_becomes_a_configuration(self) -> None:
        # T4 — the exact External Beta Readiness blocker, re-run: a Junos
        # device answers every Cisco-shaped command with its own refusal.
        from tests.platform_fixtures import junos as fx

        from founderos_atlas.config import collect_configuration

        result = self._discover(fx)
        transport = _registered_transport({}, fx.UNSUPPORTED)
        artifact = collect_configuration(transport, result)
        self.assertFalse(artifact.collected)
        self.assertEqual("unsupported", artifact.status)
        self.assertEqual("", artifact.running_config)
        self.assertNotIn("unknown command", artifact.running_config)
        # The driver's own command was what Atlas asked, not Cisco's.
        self.assertIn("show configuration | display set", transport.sent)
        self.assertNotIn("show running-config", transport.sent)
        # And storage refuses it outright.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_configuration_artifacts(artifact, Path(tmp) / "j")

    def test_junos_valid_configuration_uses_the_driver_command(self) -> None:
        # T3 — the happy path collects via the driver's declared command.
        from tests.platform_fixtures import junos as fx

        from founderos_atlas.config import collect_configuration

        result = self._discover(fx)
        transport = _registered_transport(
            {"show configuration | display set": fx.SHOW_CONFIG_SET},
            fx.UNSUPPORTED,
        )
        artifact = collect_configuration(transport, result)
        self.assertTrue(artifact.collected)
        self.assertEqual(
            "show configuration | display set", artifact.command_used
        )
        self.assertIn("set system host-name", artifact.running_config)
        # Junos session preparation ran; Cisco enrichment noise did not.
        self.assertIn("set cli screen-length 0", transport.sent)
        self.assertNotIn("show startup-config", transport.sent)

    def test_panos_refusal_never_becomes_a_configuration(self) -> None:
        # T5 — PAN-OS: TIER_DEEP is escalated, session_setup runs, and the
        # refusal stays a refusal.
        from tests.platform_fixtures import panos as fx

        from founderos_atlas.config import collect_configuration

        result = self._discover(fx)
        transport = _registered_transport({}, fx.UNKNOWN)
        artifact = collect_configuration(transport, result)
        self.assertFalse(artifact.collected)
        self.assertEqual("", artifact.running_config)
        self.assertIn("show config running", transport.sent)
        self.assertIn("set cli pager off", transport.sent)

    def test_panos_valid_configuration_collects(self) -> None:
        from tests.platform_fixtures import panos as fx

        from founderos_atlas.config import collect_configuration

        result = self._discover(fx)
        transport = _registered_transport(
            {"show config running": fx.SHOW_CONFIG_RUNNING}, fx.UNKNOWN
        )
        artifact = collect_configuration(transport, result)
        self.assertTrue(artifact.collected)
        self.assertEqual("show config running", artifact.command_used)

    def test_wlc_refusal_never_becomes_a_configuration(self) -> None:
        # T9 — Cisco WLC.
        from tests.platform_fixtures import cisco_wlc as fx

        from founderos_atlas.config import collect_configuration

        result = self._discover(fx)
        transport = _registered_transport({}, fx.UNKNOWN)
        artifact = collect_configuration(transport, result)
        self.assertFalse(artifact.collected)
        self.assertIn("show run-config commands", transport.sent)

    def test_fortios_is_contained_no_command_sent(self) -> None:
        # T6 — FortiOS: no permitted pager-off path exists, so collection
        # is not attempted, and the artifact says exactly that.
        from tests.platform_fixtures import fortios as fx

        from founderos_atlas.config import collect_configuration

        result = self._discover(fx)
        transport = _registered_transport({}, fx.UNKNOWN)
        artifact = collect_configuration(transport, result)
        self.assertFalse(artifact.collected)
        self.assertEqual("unsupported", artifact.status)
        self.assertIn("pagination", artifact.detail)
        self.assertEqual([], transport.sent)

    def test_aruba_cx_is_contained_no_command_sent(self) -> None:
        from tests.platform_fixtures import aruba_cx as fx

        from founderos_atlas.config import collect_configuration

        result = self._discover(fx)
        transport = _registered_transport({}, fx.UNKNOWN)
        artifact = collect_configuration(transport, result)
        self.assertFalse(artifact.collected)
        self.assertIn("pagination", artifact.detail)
        self.assertEqual([], transport.sent)

    def test_f5_declares_no_configuration_command(self) -> None:
        # T7 — unsupported by declaration; nothing is sent, and the
        # precollection decision needs no transport at all.
        from founderos_atlas.config.collector import precollection_outcome

        driver = default_registry().driver_for("f5-bigip")
        from tests.test_multihop_discovery import device_outputs  # noqa: F401

        class _Device:
            device_id = "f5:lb-1"
            hostname = "lb-1"
            vendor = "f5"
            platform = "BIG-IP"
            os_name = "TMOS"
            os_version = "17.1"
            management_ip = "10.0.0.50"

        artifact = precollection_outcome(driver, _Device())
        self.assertIsNotNone(artifact)
        self.assertEqual("unsupported", artifact.status)
        self.assertIn("declares no configuration collection command",
                      artifact.detail)

    def test_citrix_and_a10_declare_no_configuration_command(self) -> None:
        # T8 — same declaration semantics for the other ADC drivers.
        from founderos_atlas.config.collector import precollection_outcome

        class _Device:
            device_id = "adc:lb-2"
            hostname = "lb-2"
            vendor = "citrix"
            platform = "ADC"
            os_name = "NS"
            os_version = "14.1"
            management_ip = "10.0.0.51"

        for platform_id in ("citrix-adc", "a10-acos"):
            with self.subTest(platform=platform_id):
                driver = default_registry().driver_for(platform_id)
                artifact = precollection_outcome(driver, _Device())
                self.assertIsNotNone(artifact)
                self.assertEqual("unsupported", artifact.status)

    def test_unrecognised_reply_fails_closed_end_to_end(self) -> None:
        # T18 at the collector: a device that answers something that is
        # neither a config nor a recognised refusal.
        from tests.platform_fixtures import junos as fx

        from founderos_atlas.config import collect_configuration

        result = self._discover(fx)
        transport = _registered_transport({}, "SYSTEM READY\nOK\nDONE\n")
        artifact = collect_configuration(transport, result)
        self.assertFalse(artifact.collected)
        self.assertEqual("unrecognised", artifact.status)
        self.assertEqual("", artifact.running_config)
        self.assertIn("SYSTEM READY", artifact.raw_reply)


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


class StorageHonestyTests(unittest.TestCase):
    """PR-181 Step 6 — a snapshot exists only for verified configuration."""

    def _sink(self, tmp):
        from founderos_atlas.enterprise_memory.sink import EvidenceSink
        from founderos_atlas.enterprise_memory.store import EnterpriseMemoryStore

        store = EnterpriseMemoryStore(Path(tmp))
        return store, EvidenceSink(store, discovery_session="sess-1")

    def test_a_refusal_never_becomes_a_snapshot_but_stays_evidence(self) -> None:
        import tempfile

        from tests.platform_fixtures import junos as fx

        with tempfile.TemporaryDirectory() as tmp:
            store, sink = self._sink(tmp)
            driver = default_registry().driver_for("junos")
            sink.capture(
                device_id="junos:edge-1", hostname="edge-1",
                raw_outputs={
                    "show configuration | display set": fx.UNSUPPORTED,
                },
                platform="MX204", platform_driver="JunosDriver",
                configuration_commands=tuple(driver.configuration_commands()),
                configuration_check=driver.is_configuration,
            )
            self.assertEqual(0, sink.configurations_written)
            self.assertEqual([], list(store.configuration_snapshots()))
            # The forensic record survives, honestly labelled.
            records = store.evidence_records(device_id="junos:edge-1")
            self.assertEqual(1, len(records))
            self.assertEqual("unavailable", records[0].collection_status)

    def test_a_verified_configuration_snapshot_carries_provenance(self) -> None:
        import tempfile

        from tests.platform_fixtures import junos as fx

        with tempfile.TemporaryDirectory() as tmp:
            store, sink = self._sink(tmp)
            driver = default_registry().driver_for("junos")
            sink.capture(
                device_id="junos:edge-1", hostname="edge-1",
                raw_outputs={
                    "show configuration | display set": fx.SHOW_CONFIG_SET,
                },
                platform="MX204", platform_driver="JunosDriver",
                configuration_commands=tuple(driver.configuration_commands()),
                configuration_check=driver.is_configuration,
            )
            self.assertEqual(1, sink.configurations_written)
            snapshot = store.configuration_snapshots()[0]
            self.assertEqual("collected", snapshot.collection_status)
            self.assertEqual(
                "show configuration | display set", snapshot.command
            )
            self.assertIn("pr181:", snapshot.verified_by or "")

    def test_driverless_capture_still_requires_positive_proof(self) -> None:
        # Legacy callers get the fallback spelling set AND the shared
        # structural check — never "non-empty means configuration".
        import tempfile

        from tests.platform_fixtures import junos as fx

        with tempfile.TemporaryDirectory() as tmp:
            store, sink = self._sink(tmp)
            sink.capture(
                device_id="r1", hostname="r1",
                raw_outputs={
                    "show running-config": fx.UNSUPPORTED,  # refusal text
                },
            )
            self.assertEqual(0, sink.configurations_written)
            sink.capture(
                device_id="r1", hostname="r1",
                raw_outputs={"show running-config": FRR_RUNNING_CONFIG},
            )
            self.assertEqual(1, sink.configurations_written)

    def test_failed_attempt_provenance_survives_restart(self) -> None:
        # T15 — reopen the store from disk; the honest record is intact.
        import tempfile

        from tests.platform_fixtures import junos as fx

        from founderos_atlas.enterprise_memory.store import EnterpriseMemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            store, sink = self._sink(tmp)
            driver = default_registry().driver_for("junos")
            sink.capture(
                device_id="junos:edge-1", hostname="edge-1",
                raw_outputs={
                    "show configuration | display set": fx.UNSUPPORTED,
                },
                configuration_commands=tuple(driver.configuration_commands()),
                configuration_check=driver.is_configuration,
            )
            reopened = EnterpriseMemoryStore(Path(tmp))
            records = reopened.evidence_records(device_id="junos:edge-1")
            self.assertEqual(1, len(records))
            self.assertEqual("unavailable", records[0].collection_status)
            self.assertEqual(
                "show configuration | display set", records[0].command
            )
            self.assertEqual([], list(reopened.configuration_snapshots()))


class SelectionSafetyTests(unittest.TestCase):
    """PR-181 Step 7 — selection can never pick the unverified."""

    def _store(self, tmp, clock=None):
        from founderos_atlas.enterprise_memory.store import EnterpriseMemoryStore

        return EnterpriseMemoryStore(Path(tmp), clock=clock)

    def test_valid_snapshot_is_not_displaced_by_later_invalid(self) -> None:
        # T11 — the displacement half of the beta blocker: a later non-OK
        # record must never displace the verified configuration.
        import tempfile

        from datetime import datetime, timedelta, timezone

        from founderos_atlas.enterprise_memory.retrieval import EnterpriseMemory
        from founderos_atlas.reasoning.providers import MemoryEvidenceProvider

        base = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)
        ticks = iter(range(600))

        def clock():
            return base + timedelta(seconds=next(ticks))

        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp, clock=clock)
            store.store_configuration(
                device_id="junos:edge-1", hostname="edge-1",
                discovery_session="s1",
                running_config="set system host-name edge-1\n",
                collection_status="collected",
                command="show configuration | display set",
                verified_by="pr181:test",
            )
            # A LATER attempt, explicitly not OK (defence in depth: the
            # sink no longer writes these, but selection must still refuse
            # one if it ever appears).
            store.store_configuration(
                device_id="junos:edge-1", hostname="edge-1",
                discovery_session="s2",
                running_config="           ^\nunknown command.\n",
                collection_status="unavailable",
            )
            memory = EnterpriseMemory(store)
            provider = MemoryEvidenceProvider(memory)
            evidence = provider.gather(
                "junos:edge-1", kinds=("running-config",)
            )
            self.assertEqual(1, len(evidence))
            self.assertIn("set system host-name", evidence[0].text)
            self.assertNotIn("unknown command", evidence[0].text)
            # T12: what Policy receives is the verified text, and the
            # device memory agrees.
            latest = store.device_memory("junos:edge-1").latest_configuration
            self.assertEqual("collected", latest.collection_status)

    def test_policy_is_told_when_a_newer_attempt_failed(self) -> None:
        # §9d — never silently stale: the superseded attempt reaches the
        # Policy evidence summary and payload.
        import tempfile

        from datetime import datetime, timedelta, timezone

        from founderos_atlas.enterprise_memory.retrieval import EnterpriseMemory
        from founderos_atlas.reasoning.providers import MemoryEvidenceProvider

        base = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
        ticks = iter(range(600))

        def clock():
            return base + timedelta(seconds=next(ticks))

        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp, clock=clock)
            store.store_configuration(
                device_id="junos:edge-1", hostname="edge-1",
                discovery_session="s1",
                running_config="set system host-name edge-1\n",
                collection_status="collected",
                command="show configuration | display set",
                verified_by="pr181:test",
            )
            store.store_evidence(
                device_id="junos:edge-1", hostname="edge-1",
                command="show configuration | display set",
                output="           ^\nunknown command.\n",
                collection_status="unavailable",
                discovery_session="s2",
            )
            provider = MemoryEvidenceProvider(EnterpriseMemory(store))
            evidence = provider.gather(
                "junos:edge-1", kinds=("running-config",)
            )
            self.assertEqual(1, len(evidence))
            self.assertIn("newer collection attempt", evidence[0].summary)
            self.assertIn("was not collected", evidence[0].summary)
            superseded = evidence[0].payload.get("superseded_attempt")
            self.assertIsNotNone(superseded)
            self.assertEqual("unavailable", superseded["collection_status"])

    def test_same_second_snapshots_order_identically_everywhere(self) -> None:
        # T28 — microsecond captured_at removes new ties; for forced ties
        # every selector must agree.
        import tempfile

        from datetime import datetime, timezone

        from founderos_atlas.enterprise_memory.retrieval import EnterpriseMemory
        from founderos_atlas.reasoning.providers import MemoryEvidenceProvider

        fixed = datetime(2026, 8, 15, 11, 0, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp, clock=lambda: fixed)
            for session, text in (
                ("s1", "hostname first\n"), ("s2", "hostname second\n"),
            ):
                store.store_configuration(
                    device_id="r1", hostname="r1",
                    discovery_session=session, running_config=text,
                    collection_status="collected", verified_by="pr181:test",
                )
            memory = EnterpriseMemory(store)
            provider = MemoryEvidenceProvider(memory)
            picked = provider._pick_snapshot("r1", None)
            latest = store.device_memory("r1").latest_configuration
            timeline = memory.collected_configuration_timeline(
                "r1", newest_first=True
            )
            self.assertEqual(picked.config_sha256, latest.config_sha256)
            self.assertEqual(picked.config_sha256, timeline[0].config_sha256)

    def test_new_writes_carry_microsecond_precision(self) -> None:
        import re
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            snap = store.store_configuration(
                device_id="r1", hostname="r1", discovery_session="s1",
                running_config="hostname r1\n",
                collection_status="collected", verified_by="pr181:test",
            )
            self.assertRegex(
                snap.captured_at, r"\d{2}:\d{2}:\d{2}\.\d{6}",
                "captured_at must carry microsecond precision",
            )

    def test_no_selector_reads_the_unfiltered_accessor(self) -> None:
        # T27 — the grep contract. The honest raw accessor exists for
        # forensics; everything that CHOOSES a configuration goes through
        # the collected accessor. This pins the complete caller list.
        src = Path(__file__).resolve().parent.parent / "src"
        allowed = {
            # the store itself: the collected accessor's body, DeviceMemory
            # construction (which filters inside latest_configuration), and
            # the statistics counters
            "founderos_atlas/enterprise_memory/store.py",
            # the forensic surfaces: full history is their explicit purpose
            "founderos_atlas/enterprise_memory/retrieval.py",
        }
        offenders = []
        for path in src.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if ".configuration_snapshots(" in text:
                rel = path.relative_to(src).as_posix()
                if rel not in allowed:
                    offenders.append(rel)
        self.assertEqual(
            [], offenders,
            "selectors must use collected_configuration_snapshots()",
        )

    def test_download_gate_refuses_ineligible_blobs(self) -> None:
        # T26 — the sha must resolve to an eligible snapshot for the
        # device; a blob existing is not enough.
        import tempfile

        from founderos_atlas.enterprise_memory.retrieval import EnterpriseMemory

        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            ok = store.store_configuration(
                device_id="r1", hostname="r1", discovery_session="s1",
                running_config="hostname r1\n",
                collection_status="collected", verified_by="pr181:test",
            )
            bad = store.store_configuration(
                device_id="r1", hostname="r1", discovery_session="s2",
                running_config="           ^\nunknown command.\n",
                collection_status="unavailable",
            )
            memory = EnterpriseMemory(store)
            self.assertIsNotNone(
                memory.collected_snapshot_for("r1", ok.config_sha256)
            )
            self.assertIsNone(
                memory.collected_snapshot_for("r1", bad.config_sha256)
            )
            self.assertIsNone(
                memory.collected_snapshot_for("other-device", ok.config_sha256)
            )


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
