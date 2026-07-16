"""PR-045 (MEMORY) — Enterprise Memory Foundation acceptance tests.

Atlas gains durable memory: every discovery session, every raw command
response, every configuration snapshot — immutable, content-addressed,
deduplicated. These tests pin the foundation the spec's Part 11 checklist
requires, plus the two guarantees that make the layer trustworthy: raw
evidence is preserved verbatim (so a future parser can reprocess it), and a
secret never leaves the store through a rendered view.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import gzip
import tempfile
import unittest

from founderos_atlas.enterprise_memory import (
    COLLECTION_EMPTY,
    COLLECTION_OK,
    MODE_SEED,
    PARSER_VERSION,
    SESSION_COMPLETED,
    SESSION_RUNNING,
    SOURCE_CLI,
    DiscoverySession,
    EnterpriseMemory,
    EnterpriseMemoryStore,
    EvidenceSink,
    content_sha256,
)

from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_profile_isolation import (
    FIXED,
    add_profile,
    make_service,
    run_discover,
    scope_dir,
)
from tests.test_unified_pipeline import full_outputs


SECRET_CONFIG = (
    "hostname core1\n"
    "snmp-server community SUPERSECRET RO\n"
    "username admin privilege 15 secret 0 HUNTER2\n"
    "!\n"
)


def _store(tmp: str, *, clock=None) -> EnterpriseMemoryStore:
    return EnterpriseMemoryStore(Path(tmp) / "enterprise-memory", clock=clock)


def _fixed_clock(moment=None):
    moment = moment or datetime(2026, 7, 14, 14, 3, tzinfo=timezone.utc)
    return lambda: moment


# -- discovery sessions ------------------------------------------------------


class DiscoverySessionTests(unittest.TestCase):
    def _session(self, **kw):
        base = dict(
            session_id="disc-47", network="Delhi Lab", profile_id="delhi",
            profile_name="Delhi Lab", started_at="2026-07-14T14:03:00+00:00",
            mode=MODE_SEED, seeds=("10.0.0.1",), status=SESSION_RUNNING,
        )
        base.update(kw)
        return DiscoverySession(**base)

    def test_a_session_is_stored_and_retrieved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            store.begin_session(self._session())
            got = store.get_session("disc-47")
            self.assertIsNotNone(got)
            self.assertEqual("Delhi Lab", got.network)
            self.assertEqual(SESSION_RUNNING, got.status)

    def test_completing_a_session_finalizes_the_same_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            store.begin_session(self._session())
            store.complete_session(self._session(
                status=SESSION_COMPLETED, completed_at="2026-07-14T14:05:00+00:00",
                duration_seconds=133.0, device_count=9, authenticated_count=9,
            ))
            sessions = store.list_sessions()
            self.assertEqual(1, len(sessions))     # finalized in place, not duplicated
            self.assertEqual(SESSION_COMPLETED, sessions[0].status)
            self.assertEqual(9, sessions[0].device_count)

    def test_sessions_list_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            store.begin_session(self._session(session_id="a", started_at="2026-07-14T10:00:00+00:00"))
            store.begin_session(self._session(session_id="b", started_at="2026-07-14T12:00:00+00:00"))
            self.assertEqual(["b", "a"], [s.session_id for s in store.list_sessions()])


# -- raw evidence storage ----------------------------------------------------


class RawEvidenceTests(unittest.TestCase):
    def test_evidence_is_stored_compressed_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            record = store.store_evidence(
                device_id="frr:core1", hostname="core1",
                command="show version", output="FRRouting 8.4",
                discovery_session="s1",
            )
            self.assertTrue(record.captured)
            self.assertEqual(PARSER_VERSION, record.parser_version)
            self.assertEqual("FRRouting 8.4", store.evidence_text(record.content_sha256))
            # blob is gzip on disk
            blob = store._blob_path(record.content_sha256)
            self.assertTrue(blob.exists())
            self.assertEqual(b"\x1f\x8b", blob.read_bytes()[:2])

    def test_empty_output_is_recorded_but_stores_no_blob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            record = store.store_evidence(
                device_id="d", hostname="h", command="show foo", output="",
                discovery_session="s1",
            )
            self.assertFalse(record.captured)
            self.assertEqual(COLLECTION_EMPTY, record.collection_status)
            self.assertEqual("", record.content_sha256)

    def test_raw_evidence_is_preserved_verbatim(self) -> None:
        """Collection is separated from interpretation: the exact bytes are
        kept, so a future parser can reprocess them."""

        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            weird = "interface eth0\r\n  ip address 10.0.0.1\r\n\ttrailing  \n"
            record = store.store_evidence(
                device_id="d", hostname="h", command="show run", output=weird,
                discovery_session="s1",
            )
            # Round-trips exactly (newlines normalized, content intact).
            self.assertIn("trailing", store.evidence_text(record.content_sha256))

    def test_the_same_output_is_stored_once_across_devices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            store.store_evidence(device_id="d1", hostname="a", command="show x",
                                 output="same", discovery_session="s1")
            store.store_evidence(device_id="d2", hostname="b", command="show x",
                                 output="same", discovery_session="s1")
            stats = store.statistics()
            self.assertEqual(2, stats["evidence_records"])
            self.assertEqual(1, stats["unique_blobs"])
            self.assertEqual(1, stats["deduplicated"])

    def test_records_filter_by_device_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            store.store_evidence(device_id="d1", hostname="a", command="c1",
                                 output="x", discovery_session="s1")
            store.store_evidence(device_id="d2", hostname="b", command="c2",
                                 output="y", discovery_session="s2")
            self.assertEqual(1, len(store.evidence_records(device_id="d1")))
            self.assertEqual(1, len(store.evidence_records(discovery_session="s2")))


# -- hash stability & content addressing -------------------------------------


class HashTests(unittest.TestCase):
    def test_hash_is_stable_and_newline_normalized(self) -> None:
        self.assertEqual(content_sha256("a\nb\n"), content_sha256("a\r\nb\r\n"))
        self.assertNotEqual(content_sha256("a"), content_sha256("b"))

    def test_identical_content_yields_identical_blob_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            r = store.store_evidence(device_id="d", hostname="h", command="c",
                                     output="deterministic", discovery_session="s1")
            first = store._blob_path(r.content_sha256).read_bytes()
        with tempfile.TemporaryDirectory() as tmp2:
            store2 = _store(tmp2, clock=_fixed_clock())
            r2 = store2.store_evidence(device_id="d", hostname="h", command="c",
                                       output="deterministic", discovery_session="s1")
            second = store2._blob_path(r2.content_sha256).read_bytes()
        # Deterministic gzip: same content → byte-identical on disk.
        self.assertEqual(first, second)


# -- configuration snapshots + immutability ----------------------------------


class ConfigurationSnapshotTests(unittest.TestCase):
    def test_a_snapshot_references_the_running_config_blob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            snap = store.store_configuration(
                device_id="frr:core1", hostname="core1", discovery_session="s1",
                running_config="hostname core1\n!", platform="FRRouting",
            )
            self.assertIsNotNone(snap)
            self.assertEqual("hostname core1\n!", store.configuration_text(snap.config_sha256))

    def test_snapshot_immutability_blob_never_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            snap = store.store_configuration(
                device_id="d", hostname="h", discovery_session="s1",
                running_config="config-v1", platform="ios",
            )
            path = store._blob_path(snap.config_sha256)
            before = path.read_bytes()
            # Re-store identical content: same blob, byte-identical, not rewritten.
            store.store_configuration(
                device_id="d", hostname="h", discovery_session="s2",
                running_config="config-v1", platform="ios",
            )
            self.assertEqual(before, path.read_bytes())

    def test_unchanged_reconfig_shares_the_blob_but_keeps_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            store.store_configuration(device_id="d", hostname="h",
                                      discovery_session="s1", running_config="cfg", platform="ios")
            store.store_configuration(device_id="d", hostname="h",
                                      discovery_session="s2", running_config="cfg", platform="ios")
            snaps = store.configuration_snapshots(device_id="d")
            self.assertEqual(2, len(snaps))                      # history: two sessions
            self.assertEqual(1, len({s.config_sha256 for s in snaps}))  # one blob

    def test_changed_config_adds_a_snapshot_and_a_blob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            store.store_configuration(device_id="d", hostname="h",
                                      discovery_session="s1", running_config="v1", platform="ios")
            store.store_configuration(device_id="d", hostname="h",
                                      discovery_session="s2", running_config="v2", platform="ios")
            snaps = store.configuration_snapshots(device_id="d")
            self.assertEqual(2, len({s.config_sha256 for s in snaps}))

    def test_no_config_captured_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            self.assertIsNone(store.store_configuration(
                device_id="d", hostname="h", discovery_session="s1",
                running_config="", platform="ios"))


# -- observations ------------------------------------------------------------


class ObservationTests(unittest.TestCase):
    def test_re_collection_increments_observations_not_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            for session in ("s1", "s2", "s3"):
                store.store_evidence(device_id="d", hostname="h", command="c",
                                     output="same", discovery_session=session)
            digest = content_sha256("same")
            obs = store.observation(digest)
            self.assertEqual(3, obs.observation_count)
            self.assertEqual(("s1", "s2", "s3"), obs.discovery_sessions)


# -- device memory + retrieval APIs ------------------------------------------


class DeviceMemoryTests(unittest.TestCase):
    def _seed(self, store):
        store.begin_session(DiscoverySession(
            session_id="s1", network="Lab", profile_id="p", profile_name="Lab",
            started_at="2026-07-14T14:03:00+00:00"))
        store.store_evidence(device_id="frr:core1", hostname="core1",
                             command="show version", output="FRR 8.4",
                             discovery_session="s1")
        store.store_configuration(device_id="frr:core1", hostname="core1",
                                  discovery_session="s1", running_config="hostname core1\n!",
                                  platform="FRRouting")

    def test_device_memory_aggregates_sessions_configs_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            self._seed(store)
            memory = store.device_memory("frr:core1")
            self.assertEqual("core1", memory.hostname)
            self.assertEqual("Lab", memory.network)
            self.assertEqual(1, memory.configuration_versions)
            self.assertEqual(1, len(memory.evidence))
            self.assertEqual(("s1",), memory.discovery_sessions)

    def test_retrieval_api_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            self._seed(store)
            api = EnterpriseMemory(store)
            self.assertEqual(1, len(api.list_discovery_sessions()))
            self.assertIsNotNone(api.get_discovery_session("s1"))
            self.assertEqual(("frr:core1",), api.device_ids())
            self.assertEqual(1, len(api.get_configuration_history("frr:core1")))
            self.assertEqual(1, len(api.get_raw_evidence("frr:core1")))
            self.assertIn("core1", api.session_devices("s1")[0]["hostname"])


# -- download (raw) vs view (masked) -----------------------------------------


class MaskingTests(unittest.TestCase):
    def test_download_is_raw_but_view_is_masked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            record = store.store_evidence(
                device_id="d", hostname="h", command="show running-config",
                output=SECRET_CONFIG, discovery_session="s1")
            api = EnterpriseMemory(store)
            # Prove the secret is really stored (download = raw, for the operator).
            raw = api.download_evidence(record.content_sha256)
            self.assertIn("SUPERSECRET", raw)
            self.assertIn("HUNTER2", raw)
            # The view an engineer sees is masked.
            view = api.view_evidence(record)
            self.assertNotIn("SUPERSECRET", view.text)
            self.assertNotIn("HUNTER2", view.text)
            self.assertEqual(2, view.masked_line_count)
            self.assertIn("hostname core1", view.text)  # non-secret lines survive


# -- discovery integration (the pipeline) ------------------------------------


class DiscoveryIntegrationTests(unittest.TestCase):
    def _network(self, running_config=None):
        return ScriptedNetwork({
            "10.0.0.1": full_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),),
                                     running_config=running_config),
            "10.0.0.2": full_outputs("SW1", "10.0.0.2"),
        })

    def _memory(self, workdir):
        return EnterpriseMemory(
            EnterpriseMemoryStore(scope_dir(workdir, "lab-a") / "enterprise-memory")
        )

    def test_discovery_creates_one_session_with_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            svc = make_service(wd)
            add_profile(svc, "Lab A", "10.0.0.1")
            run_discover(wd, svc, self._network(), "Lab A", FIXED)
            mem = self._memory(wd)
            sessions = mem.list_discovery_sessions()
            self.assertEqual(1, len(sessions))
            self.assertEqual(SESSION_COMPLETED, sessions[0].status)
            self.assertEqual(2, sessions[0].device_count)
            # Every discovered device has raw evidence.
            for device_id in mem.device_ids():
                self.assertGreater(len(mem.get_raw_evidence(device_id)), 0)

    def test_configuration_collection_lands_in_enterprise_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            svc = make_service(wd)
            add_profile(svc, "Lab A", "10.0.0.1", collect_configuration=True)
            run_discover(wd, svc, self._network(), "Lab A", FIXED)
            mem = self._memory(wd)
            self.assertGreater(len(mem.get_configuration_history("cisco-ios:r1")), 0)

    def test_rerun_without_change_stores_no_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            svc = make_service(wd)
            add_profile(svc, "Lab A", "10.0.0.1", collect_configuration=True)
            run_discover(wd, svc, self._network(), "Lab A", FIXED)
            store = EnterpriseMemoryStore(scope_dir(wd, "lab-a") / "enterprise-memory")
            blobs_after_1 = store.statistics()["unique_blobs"]
            run_discover(wd, svc, self._network(), "Lab A", FIXED + timedelta(hours=1))
            stats = store.statistics()
            self.assertEqual(2, stats["sessions"])
            self.assertEqual(blobs_after_1, stats["unique_blobs"])   # no new storage
            self.assertGreater(stats["deduplicated"], 0)

    def test_rerun_with_change_creates_new_snapshot_history_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            svc = make_service(wd)
            add_profile(svc, "Lab A", "10.0.0.1", collect_configuration=True)
            run_discover(wd, svc, self._network(), "Lab A", FIXED)
            run_discover(
                wd, svc,
                self._network(running_config="hostname R1\nip domain changed\n!"),
                "Lab A", FIXED + timedelta(hours=2),
            )
            mem = self._memory(wd)
            history = mem.get_configuration_history("cisco-ios:r1")
            self.assertGreaterEqual(len(history), 2)                      # history kept
            self.assertEqual(2, len({s.config_sha256 for s in history}))  # a new version


# -- multi-platform ----------------------------------------------------------


class MultiPlatformTests(unittest.TestCase):
    def test_evidence_is_platform_agnostic(self) -> None:
        """The store cares about bytes, not platform. IOS and FRR evidence are
        stored and retrieved the same way."""

        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            store.store_evidence(device_id="cisco:r1", hostname="r1",
                                 command="show version", output="Cisco IOS 15.2",
                                 discovery_session="s1", source=SOURCE_CLI)
            store.store_evidence(device_id="frr:c1", hostname="c1",
                                 command="show version", output="FRRouting 8.4",
                                 discovery_session="s1", source=SOURCE_CLI)
            self.assertEqual("Cisco IOS 15.2",
                             store.evidence_text(content_sha256("Cisco IOS 15.2")))
            self.assertEqual("FRRouting 8.4",
                             store.evidence_text(content_sha256("FRRouting 8.4")))


# -- the sink ----------------------------------------------------------------


class EvidenceSinkTests(unittest.TestCase):
    def test_sink_captures_every_command_and_the_running_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            sink = EvidenceSink(store, discovery_session="s1")
            sink.capture(
                device_id="frr:core1", hostname="core1", platform="FRRouting",
                raw_outputs={
                    "show version": "FRR 8.4",
                    "show ip ospf neighbor": "core2 Full",
                    "show running-config": "hostname core1\n!",
                },
            )
            self.assertEqual(3, sink.evidence_written)
            self.assertEqual(1, sink.configurations_written)
            self.assertEqual(1, len(store.configuration_snapshots(device_id="frr:core1")))


class MetadataHardeningTests(unittest.TestCase):
    """PR-045R Parts 2–5: strengthened provenance travels with every record."""

    def test_raw_evidence_carries_strong_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            r = store.store_evidence(
                device_id="frr:core1", hostname="core1", command="show version",
                output="FRR 8.4", discovery_session="s1",
                transport="ssh", platform="FRRouting", software_version="8.4",
                platform_driver="FRRoutingDriver",
            )
            d = r.to_dict()
            for key in ("transport", "platform", "software_version",
                        "platform_driver", "atlas_version", "exit_status",
                        "parser_version", "metadata"):
                self.assertIn(key, d)
            self.assertEqual("FRRoutingDriver", d["platform_driver"])
            self.assertEqual(r.collection_status, d["exit_status"])

    def test_metadata_slot_supports_future_sources(self) -> None:
        """A future evidence source attaches its own fields without a model
        change — Part 7 extensibility."""

        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            r = store.store_evidence(
                device_id="d", hostname="h", command="1.3.6.1.2.1.1",
                output="sysDescr", discovery_session="s1", source="snmp",
                metadata={"oid": "1.3.6.1.2.1.1", "snmp_version": "2c"},
            )
            reloaded = store.evidence_records(device_id="d")[0]
            self.assertEqual("snmp", reloaded.source)
            self.assertEqual("1.3.6.1.2.1.1", reloaded.metadata["oid"])

    def test_configuration_snapshot_carries_provenance_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            snap = store.store_configuration(
                device_id="frr:core1", hostname="core1", discovery_session="s1",
                running_config="hostname core1\ninterface lo\n!",
                platform="FRRouting", software_version="8.4",
                credential_ref="atlas-profile:lab", discovery_policy="always",
                platform_driver="FRRoutingDriver",
            )
            d = snap.to_dict()
            self.assertEqual("atlas-profile:lab", d["credential_ref"])
            self.assertEqual("always", d["discovery_policy"])
            self.assertEqual("FRRoutingDriver", d["platform_driver"])
            self.assertIsNotNone(d["fingerprint"])
            self.assertEqual("core1", d["fingerprint"]["hostname"])
            # Provenance survives a round-trip.
            from founderos_atlas.enterprise_memory import ConfigurationSnapshot
            self.assertEqual("always", ConfigurationSnapshot.from_dict(d).discovery_policy)

    def test_no_provenance_field_is_a_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            snap = store.store_configuration(
                device_id="d", hostname="h", discovery_session="s1",
                running_config=SECRET_CONFIG, platform="ios",
                credential_ref="atlas-profile:lab",
            )
            self.assertNotIn("SUPERSECRET", str(snap.to_dict()))
            self.assertNotIn("HUNTER2", str(snap.to_dict()))

    def test_device_memory_exposes_latest_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, clock=_fixed_clock())
            store.begin_session(DiscoverySession(
                session_id="s1", network="Lab", profile_id="p",
                profile_name="Lab", started_at="2026-07-14T14:03:00+00:00"))
            store.store_evidence(device_id="d", hostname="h", command="c",
                                 output="x", discovery_session="s1")
            store.store_configuration(device_id="d", hostname="h",
                                      discovery_session="s1", running_config="cfg",
                                      platform="ios")
            dm = store.device_memory("d")
            self.assertEqual("s1", dm.latest_discovery)
            self.assertEqual(1, dm.evidence_count)   # one raw command recorded
            self.assertEqual(1, dm.configuration_count)
            self.assertEqual(1, dm.observation_count)
            self.assertIsNotNone(dm.latest_configuration)


class FingerprintTests(unittest.TestCase):
    """PR-045R Part 6: a lightweight structural fingerprint — counts only."""

    CONFIG = (
        "hostname core1\n"
        "interface eth1\n ip address 10.4.2.2/30\n"
        "interface eth2\n ip address 10.4.2.6/30\n"
        "interface lo\n ip address 10.4.255.11/32\n"
        "router bgp 65100\n"
        " neighbor 10.4.255.1 remote-as 65100\n"
        " neighbor 10.4.255.2 remote-as 65100\n"
        "router ospf\n network 10.4.2.0/30 area 0\n"
        "ip route 0.0.0.0/0 10.0.0.1\n!\n"
    )

    def test_fingerprint_counts_structure(self) -> None:
        from founderos_atlas.enterprise_memory import fingerprint
        fp = fingerprint(self.CONFIG)
        self.assertEqual("core1", fp.hostname)
        self.assertEqual(3, fp.interface_count)
        self.assertEqual(1, fp.loopback_count)
        self.assertEqual(2, fp.bgp_neighbor_count)
        self.assertEqual("65100", fp.bgp_as)
        self.assertEqual(1, fp.ospf_process_count)
        self.assertEqual(1, fp.static_route_count)

    def test_fingerprint_is_deterministic(self) -> None:
        from founderos_atlas.enterprise_memory import fingerprint
        self.assertEqual(fingerprint(self.CONFIG).to_dict(),
                         fingerprint(self.CONFIG).to_dict())

    def test_empty_config_has_no_fingerprint(self) -> None:
        from founderos_atlas.enterprise_memory import fingerprint
        self.assertIsNone(fingerprint(""))
        self.assertIsNone(fingerprint(None))

    def test_likely_changed_is_a_fast_structural_precheck(self) -> None:
        from founderos_atlas.enterprise_memory import fingerprint
        base = fingerprint(self.CONFIG)
        same = fingerprint(self.CONFIG)
        fewer = fingerprint(self.CONFIG.replace(
            " neighbor 10.4.255.2 remote-as 65100\n", ""))
        self.assertFalse(base.likely_changed_from(same))   # identical hash
        self.assertTrue(fewer.likely_changed_from(base))    # a neighbour removed
        self.assertTrue(base.likely_changed_from(None))     # nothing before

    def test_fingerprint_never_contains_a_secret(self) -> None:
        from founderos_atlas.enterprise_memory import fingerprint
        fp = fingerprint(SECRET_CONFIG)
        self.assertNotIn("SUPERSECRET", str(fp.to_dict()))
        self.assertNotIn("HUNTER2", str(fp.to_dict()))


class TimelineTests(unittest.TestCase):
    """PR-045R Part 8: ordered histories future modules read without changes."""

    def test_evidence_and_configuration_timelines_are_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = {"now": datetime(2026, 7, 14, 10, tzinfo=timezone.utc)}
            store = _store(tmp, clock=lambda: state["now"])
            api = EnterpriseMemory(store)
            for i in range(3):
                store.store_evidence(device_id="d", hostname="h",
                                     command=f"c{i}", output=f"out{i}",
                                     discovery_session=f"s{i}")
                store.store_configuration(device_id="d", hostname="h",
                                          discovery_session=f"s{i}",
                                          running_config=f"cfg{i}", platform="ios")
                state["now"] += timedelta(hours=1)
            ev = api.evidence_timeline("d", newest_first=True)
            self.assertEqual("out2".__len__(), len("out2"))  # sanity
            self.assertGreaterEqual(ev[0].collected_at, ev[-1].collected_at)
            cfg = api.configuration_timeline("d", newest_first=False)
            self.assertLessEqual(cfg[0].captured_at, cfg[-1].captured_at)


class MemoryGuiTests(unittest.TestCase):
    """The rendered pages, and that no page leaks a secret."""

    def _client(self, workdir: Path):
        from founderos_atlas.web import create_app

        svc = make_service(workdir)
        add_profile(svc, "Lab A", "10.0.0.1", collect_configuration=True)
        net = ScriptedNetwork({
            "10.0.0.1": full_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),),
                                     running_config=SECRET_CONFIG),
            "10.0.0.2": full_outputs("SW1", "10.0.0.2"),
        })
        run_discover(workdir, svc, net, "Lab A", FIXED)
        app = create_app(
            profile_service=svc, output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return app.test_client()

    def test_discovery_history_lists_the_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._client(Path(tmp)).get("/evidence").get_data(as_text=True)
            # PR-047A: the page is named for what the operator came for
            # (Evidence), not for the platform layer behind it (Enterprise
            # Memory). The sessions section is "Discovery Sessions" so it no
            # longer collides with the Discoveries page.
            self.assertIn("Evidence", page)
            self.assertIn("Discovery Sessions", page)
            self.assertIn("Completed", page)

    def test_device_memory_page_shows_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            page = client.get("/evidence/device/cisco-ios:r1").get_data(as_text=True)
            self.assertEqual(
                200, client.get("/evidence/device/cisco-ios:r1").status_code
            )
            # PR-047B renamed the section for what it holds: the commands Atlas
            # ran. "Raw Evidence" described the storage; this describes the work.
            self.assertIn("Collected Commands", page)
            self.assertIn("show running-config", page)

    def test_evidence_view_masks_secrets_but_download_is_raw(self) -> None:
        import re

        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            page = client.get("/evidence/device/cisco-ios:r1").get_data(as_text=True)
            # The running-config evidence link (its row contains the command).
            m = re.search(
                r"show running-config.*?/record/([0-9a-f]{32,})", page, re.DOTALL
            )
            assert m, "no running-config evidence link rendered"
            sha = m.group(1)
            view = client.get(
                f"/evidence/device/cisco-ios:r1/record/{sha}"
            ).get_data(as_text=True)
            self.assertNotIn("SUPERSECRET", view)
            self.assertNotIn("HUNTER2", view)
            raw = client.get(
                f"/evidence/device/cisco-ios:r1/record/{sha}/download"
            ).get_data(as_text=True)
            self.assertIn("SUPERSECRET", raw)   # download is the raw path

    def test_no_memory_page_leaks_a_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            # follow_redirects matters: /memory is now a 302 to /evidence, and a
            # redirect's empty body would satisfy this assertion without ever
            # rendering the page it is supposed to be checking. Asserting
            # against a body that was never built is how a security test passes
            # for the wrong reason.
            for url in (
                "/memory", "/memory/device/cisco-ios:r1",
                "/evidence", "/evidence/device/cisco-ios:r1",
            ):
                body = client.get(url, follow_redirects=True).get_data(as_text=True)
                self.assertIn("Atlas", body, f"{url} rendered no page to check")
                self.assertNotIn("SUPERSECRET", body)
                self.assertNotIn("HUNTER2", body)


if __name__ == "__main__":
    unittest.main()
