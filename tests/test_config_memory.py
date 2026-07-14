"""PR-044 (MEMORY) — Configuration Intelligence acceptance tests.

Discovery tells Atlas what exists today; Configuration Memory tells Atlas
what existed yesterday. These tests pin the Part 12 checklist: snapshot
creation, duplicate suppression, version history, hash stability, timeline,
text diff, semantic diff, normalization, structured extraction,
multi-platform support, and discovery integration — plus the standing
guarantee that no secret ever leaves the blob store.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.config_memory import (
    ConfigMemoryStore,
    POLICY_ALWAYS,
    POLICY_DISABLED,
    POLICY_DISCOVERY_ONLY,
    POLICY_MANUAL,
    POLICY_SCHEDULED,
    RECORD_NEW_DEVICE,
    RECORD_NEW_VERSION,
    RECORD_UNCHANGED,
    TimelineEvent,
    config_sha256,
    config_version_id,
    config_view,
    decide_collection,
    device_timeline,
    enterprise_timeline,
    extract_facts,
    group_by_day,
    normalize_policy,
    semantic_diff_text,
    text_diff,
)
from founderos_atlas.web.timefmt import (
    _abbreviate,
    day_key_for,
    format_relative,
    format_timestamp,
    resolve_timezone,
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


IOS_V1 = """hostname core1
!
vrf definition GUEST
!
interface GigabitEthernet0/1
 description LINK-TO-dist1
 ip address 10.0.0.1 255.255.255.252
 standby 1 priority 110
!
interface GigabitEthernet0/2
 description SPARE
 shutdown
!
router bgp 65001
 bgp router-id 10.255.0.1
 neighbor 10.0.0.2 remote-as 65002
!
router ospf 1
 network 10.0.0.0 0.0.0.255 area 0
!
vlan 10
ip access-list extended GUEST-IN
route-map SET-LP permit 10
ip route 0.0.0.0 0.0.0.0 10.0.0.2
ntp server 10.1.1.1
logging host 10.1.1.2
aaa new-model
snmp-server community SUPERSECRET RO
username admin privilege 15 secret 0 HUNTER2
"""

# v2: BGP neighbour added, interface shut, VLAN added, HSRP priority, desc.
IOS_V2 = """hostname core1
!
vrf definition GUEST
!
interface GigabitEthernet0/1
 description LINK-TO-dist1-UPLINK
 ip address 10.0.0.1 255.255.255.252
 standby 1 priority 120
 shutdown
!
interface GigabitEthernet0/2
 description SPARE
 shutdown
!
router bgp 65001
 bgp router-id 10.255.0.1
 neighbor 10.0.0.2 remote-as 65002
 neighbor 10.0.0.6 remote-as 65003
!
router ospf 1
 network 10.0.0.0 0.0.0.255 area 0
 network 10.9.0.0 0.0.0.255 area 9
!
vlan 10
vlan 20
ip access-list extended GUEST-IN
route-map SET-LP permit 10
ip route 0.0.0.0 0.0.0.0 10.0.0.2
ntp server 10.1.1.1
logging host 10.1.1.2
aaa new-model
snmp-server community SUPERSECRET RO
username admin privilege 15 secret 0 HUNTER2
"""

FRR_CONFIG = """frr version 8.4.2
hostname delhi-r1
!
interface eth1
 description LINK-TO-delhi-r2
 ip address 192.0.2.65/30
!
router bgp 65010
 bgp router-id 192.0.2.50
 neighbor 192.0.2.66 remote-as 65020
!
router ospf
 network 192.0.2.64/30 area 0
!
end
"""

RECORD_KW = dict(
    device_id="cisco-ios:core1",
    hostname="core1",
    network="Lab A",
    profile_id="lab-a",
)


def store_at(root: Path) -> ConfigMemoryStore:
    return ConfigMemoryStore(root / "config-memory")


# -- Parts 2/3: snapshots, content addressing, duplicate suppression --------------


class SnapshotAndDedupTests(unittest.TestCase):
    def test_hash_is_stable_and_content_addressed(self) -> None:
        self.assertEqual(config_sha256(IOS_V1), config_sha256(IOS_V1))
        self.assertNotEqual(config_sha256(IOS_V1), config_sha256(IOS_V2))
        digest = config_sha256(IOS_V1)
        self.assertEqual(f"atlas-config:{digest}", config_version_id(digest))
        with self.assertRaises(ValueError):
            config_version_id("not-a-digest")

    def test_first_record_creates_v1_with_full_snapshot_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = store_at(Path(tmp))
            outcome = store.record(
                IOS_V1, discovery_session="run-1",
                collected_at="2026-07-13T09:00:00+00:00",
                platform="IOSv", vendor="cisco", os_name="IOS",
                os_version="15.9", management_ip="10.0.0.1", **RECORD_KW,
            )
            self.assertEqual(RECORD_NEW_DEVICE, outcome.outcome)
            self.assertEqual(1, outcome.version)
            self.assertTrue(outcome.stored_blob)
            self.assertTrue(outcome.changed)
            snapshot = store.history("cisco-ios:core1").versions[0].snapshot
            # Part 2 metadata is complete…
            self.assertEqual("core1", snapshot.hostname)
            self.assertEqual("Lab A", snapshot.network)
            self.assertEqual("lab-a", snapshot.profile_id)
            self.assertEqual("IOSv", snapshot.platform)
            self.assertEqual("15.9", snapshot.os_version)
            self.assertEqual("run-1", snapshot.discovery_session)
            self.assertEqual(config_sha256(IOS_V1), snapshot.config_sha256)
            # …and carries NO configuration content.
            self.assertNotIn("SUPERSECRET", str(snapshot.to_dict()))
            self.assertNotIn("hostname core1", str(snapshot.to_dict()))

    def test_identical_configuration_is_observed_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = store_at(Path(tmp))
            store.record(IOS_V1, discovery_session="run-1",
                         collected_at="2026-07-13T09:00:00+00:00", **RECORD_KW)
            second = store.record(IOS_V1, discovery_session="run-2",
                                  collected_at="2026-07-13T12:00:00+00:00",
                                  **RECORD_KW)
            self.assertEqual(RECORD_UNCHANGED, second.outcome)
            self.assertEqual(1, second.version)      # still v1
            self.assertFalse(second.stored_blob)     # no duplicate storage
            self.assertFalse(second.changed)
            history = store.history("cisco-ios:core1")
            self.assertEqual(1, history.version_count)
            version = history.versions[0]
            self.assertEqual(2, version.observation_count)
            self.assertEqual("2026-07-13T09:00:00+00:00", version.first_seen)
            self.assertEqual("2026-07-13T12:00:00+00:00", version.last_seen)
            # Exactly one blob on disk.
            self.assertEqual(1, len(list(store.blobs_dir.glob("*.txt"))))

    def test_changed_configuration_creates_a_new_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = store_at(Path(tmp))
            store.record(IOS_V1, discovery_session="run-1",
                         collected_at="2026-07-13T09:00:00+00:00", **RECORD_KW)
            outcome = store.record(IOS_V2, discovery_session="run-2",
                                   collected_at="2026-07-14T09:42:00+00:00",
                                   **RECORD_KW)
            self.assertEqual(RECORD_NEW_VERSION, outcome.outcome)
            self.assertEqual(2, outcome.version)
            self.assertTrue(outcome.changed)
            self.assertEqual(config_sha256(IOS_V1), outcome.previous_sha256)
            self.assertEqual(2, store.history("cisco-ios:core1").version_count)

    def test_reverting_reuses_the_stored_blob_but_is_a_new_version(self) -> None:
        # A revert is chronologically a new change, but costs no storage.
        with tempfile.TemporaryDirectory() as tmp:
            store = store_at(Path(tmp))
            store.record(IOS_V1, discovery_session="r1",
                         collected_at="2026-07-13T09:00:00+00:00", **RECORD_KW)
            store.record(IOS_V2, discovery_session="r2",
                         collected_at="2026-07-14T09:00:00+00:00", **RECORD_KW)
            back = store.record(IOS_V1, discovery_session="r3",
                                collected_at="2026-07-15T09:00:00+00:00",
                                **RECORD_KW)
            self.assertEqual(RECORD_NEW_VERSION, back.outcome)
            self.assertEqual(3, back.version)
            self.assertFalse(back.stored_blob)   # content already known
            self.assertEqual(2, len(list(store.blobs_dir.glob("*.txt"))))

    def test_two_devices_with_identical_config_share_one_blob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = store_at(Path(tmp))
            store.record(IOS_V1, discovery_session="r1",
                         collected_at="2026-07-13T09:00:00+00:00", **RECORD_KW)
            store.record(
                IOS_V1, device_id="cisco-ios:core2", hostname="core2",
                network="Lab A", profile_id="lab-a", discovery_session="r1",
                collected_at="2026-07-13T09:00:00+00:00",
            )
            self.assertEqual(1, len(list(store.blobs_dir.glob("*.txt"))))
            self.assertEqual(2, len(store.device_ids()))

    def test_statistics_report_the_dedup_win(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = store_at(Path(tmp))
            for hour in (9, 10, 11):
                store.record(IOS_V1, discovery_session=f"r{hour}",
                             collected_at=f"2026-07-13T{hour}:00:00+00:00",
                             **RECORD_KW)
            stats = store.statistics()
            self.assertEqual(1, stats["devices"])
            self.assertEqual(1, stats["versions"])
            self.assertEqual(3, stats["observations"])
            self.assertEqual(1, stats["unique_configurations"])
            self.assertEqual(2, stats["deduplicated_observations"])

    def test_stored_text_round_trips_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = store_at(Path(tmp))
            store.record(IOS_V1, discovery_session="r1",
                         collected_at="2026-07-13T09:00:00+00:00", **RECORD_KW)
            self.assertEqual(IOS_V1, store.version_text("cisco-ios:core1", 1))
            self.assertIsNone(store.version_text("cisco-ios:core1", 99))
            self.assertIsNone(store.history("nope:device"))

    def test_empty_configuration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = store_at(Path(tmp))
            with self.assertRaises(ValueError):
                store.record("   ", discovery_session="r1",
                             collected_at="2026-07-13T09:00:00+00:00",
                             **RECORD_KW)


# -- Part 4: version history -------------------------------------------------------


class VersionHistoryTests(unittest.TestCase):
    def test_history_is_ordered_and_navigable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = store_at(Path(tmp))
            store.record(IOS_V1, discovery_session="r1",
                         collected_at="2026-07-13T09:00:00+00:00", **RECORD_KW)
            store.record(IOS_V2, discovery_session="r2",
                         collected_at="2026-07-14T09:00:00+00:00", **RECORD_KW)
            history = store.history("cisco-ios:core1")
            self.assertEqual(["v1", "v2"], [v.label for v in history.versions])
            self.assertEqual(2, history.latest.version)
            self.assertEqual(1, history.version(1).version)
            self.assertIsNone(history.version(7))
            self.assertEqual(2, history.total_observations)


# -- Part 5: text diff -------------------------------------------------------------


class TextDiffTests(unittest.TestCase):
    def test_added_and_removed_lines_are_reported(self) -> None:
        diff = text_diff(IOS_V1, IOS_V2)
        self.assertTrue(diff.changed)
        self.assertTrue(diff.added)
        self.assertTrue(diff.removed)
        added = [line.current_text for line in diff.lines if line.kind == "added"]
        self.assertTrue(any("neighbor 10.0.0.6 remote-as 65003" in t for t in added))
        self.assertTrue(any("vlan 20" in t for t in added))

    def test_identical_configurations_show_no_change(self) -> None:
        diff = text_diff(IOS_V1, IOS_V1)
        self.assertFalse(diff.changed)
        self.assertEqual(0, diff.added)
        self.assertEqual(0, diff.removed)
        self.assertTrue(all(line.kind == "equal" for line in diff.lines))

    def test_secrets_are_masked_in_every_rendered_line(self) -> None:
        diff = text_diff(IOS_V1, IOS_V2)
        rendered = " ".join(
            (line.previous_text or "") + (line.current_text or "")
            for line in diff.lines
        )
        self.assertNotIn("SUPERSECRET", rendered)
        self.assertNotIn("HUNTER2", rendered)
        self.assertIn("masked", rendered)

    def test_context_trimming_keeps_changes(self) -> None:
        full = text_diff(IOS_V1, IOS_V2)
        compact = text_diff(IOS_V1, IOS_V2, context_lines=1)
        self.assertLess(len(compact.lines), len(full.lines))
        self.assertEqual(full.added, compact.added)
        self.assertEqual(full.removed, compact.removed)


# -- Parts 6/8: structured extraction + semantic diff ------------------------------


class ExtractionTests(unittest.TestCase):
    def test_ios_configuration_normalizes_into_facts(self) -> None:
        facts = extract_facts(IOS_V1)
        self.assertEqual("core1", facts.hostname)
        self.assertEqual("10.255.0.1", facts.router_id)
        self.assertEqual("65001", facts.bgp_as)
        self.assertEqual(["10.0.0.2"], [n.neighbor for n in facts.bgp_neighbors])
        self.assertEqual("65002", facts.bgp_neighbors[0].remote_as)
        self.assertEqual(("0",), facts.ospf_areas)
        self.assertIn("10", facts.vlans)
        self.assertIn("GUEST", facts.vrfs)
        self.assertIn("GUEST-IN", facts.acls)
        self.assertIn("SET-LP", facts.route_maps)
        self.assertEqual(("10.1.1.1",), facts.ntp_servers)
        self.assertEqual(("10.1.1.2",), facts.logging_hosts)
        self.assertTrue(facts.snmp_configured)
        self.assertTrue(facts.aaa_configured)
        self.assertTrue(facts.static_routes)
        names = {i.name: i for i in facts.interfaces}
        self.assertEqual("LINK-TO-dist1", names["GigabitEthernet0/1"].description)
        self.assertEqual("10.0.0.1 255.255.255.252", names["GigabitEthernet0/1"].ip_address)
        self.assertFalse(names["GigabitEthernet0/1"].shutdown)
        self.assertTrue(names["GigabitEthernet0/2"].shutdown)
        self.assertEqual(
            [("GigabitEthernet0/1", "1", "110")],
            [(g.interface, g.group, g.priority) for g in facts.hsrp_groups],
        )

    def test_extraction_never_captures_secrets(self) -> None:
        rendered = str(extract_facts(IOS_V1).to_dict())
        self.assertNotIn("SUPERSECRET", rendered)
        self.assertNotIn("HUNTER2", rendered)
        # Existence is recorded; the secret value never is.
        self.assertTrue(extract_facts(IOS_V1).snmp_configured)

    def test_frr_configuration_is_supported_by_the_same_extractor(self) -> None:
        facts = extract_facts(FRR_CONFIG)
        self.assertEqual("delhi-r1", facts.hostname)
        self.assertEqual("65010", facts.bgp_as)
        self.assertEqual("192.0.2.50", facts.router_id)
        self.assertEqual(["192.0.2.66"], [n.neighbor for n in facts.bgp_neighbors])
        self.assertEqual(("0",), facts.ospf_areas)
        names = {i.name: i for i in facts.interfaces}
        self.assertEqual("192.0.2.65/30", names["eth1"].ip_address)
        self.assertEqual("LINK-TO-delhi-r2", names["eth1"].description)

    def test_absent_constructs_stay_absent(self) -> None:
        facts = extract_facts("hostname bare\n!\n")
        self.assertEqual("bare", facts.hostname)
        self.assertIsNone(facts.bgp_as)
        self.assertEqual((), facts.bgp_neighbors)
        self.assertEqual((), facts.vlans)
        self.assertFalse(facts.snmp_configured)
        self.assertFalse(facts.aaa_configured)

    def test_extraction_is_deterministic(self) -> None:
        self.assertEqual(
            extract_facts(IOS_V1).to_dict(), extract_facts(IOS_V1).to_dict()
        )


class SemanticDiffTests(unittest.TestCase):
    def kinds(self, events) -> set[str]:
        return {event.kind for event in events}

    def test_configuration_differences_become_structured_events(self) -> None:
        events = semantic_diff_text(IOS_V1, IOS_V2)
        kinds = self.kinds(events)
        self.assertIn("bgp-neighbor-added", kinds)
        self.assertIn("interface-shutdown", kinds)
        self.assertIn("vlan-added", kinds)
        self.assertIn("ospf-area-added", kinds)
        self.assertIn("hsrp-priority-changed", kinds)
        self.assertIn("interface-description-changed", kinds)
        added = next(e for e in events if e.kind == "bgp-neighbor-added")
        self.assertEqual("10.0.0.6", added.subject)
        self.assertEqual("high", added.severity)
        self.assertEqual("bgp", added.category)
        self.assertIn("65003", added.summary)

    def test_removal_is_the_mirror_of_addition(self) -> None:
        events = semantic_diff_text(IOS_V2, IOS_V1)
        kinds = self.kinds(events)
        self.assertIn("bgp-neighbor-removed", kinds)
        self.assertIn("vlan-removed", kinds)
        self.assertIn("ospf-area-removed", kinds)
        self.assertIn("interface-enabled", kinds)

    def test_no_change_yields_no_events(self) -> None:
        self.assertEqual((), semantic_diff_text(IOS_V1, IOS_V1))

    def test_events_are_severity_ordered_and_secret_free(self) -> None:
        events = semantic_diff_text(IOS_V1, IOS_V2)
        severities = [e.severity for e in events]
        rank = {"high": 2, "medium": 1, "low": 0}
        self.assertEqual(
            sorted(severities, key=lambda s: -rank[s]), severities
        )
        rendered = str([e.to_dict() for e in events])
        self.assertNotIn("SUPERSECRET", rendered)
        self.assertNotIn("HUNTER2", rendered)

    def test_semantics_survive_formatting_noise(self) -> None:
        # Meaning, not text: a device re-emitting byte counts / save
        # timestamps is not a configuration change.
        noisy = (
            "Building configuration...\n"
            "Current configuration : 1234 bytes\n"
            "! Last configuration change at 10:00:00 UTC Mon Jul 13 2026\n"
            + IOS_V1
        )
        self.assertEqual((), semantic_diff_text(IOS_V1, noisy))


# -- Part 7: timeline --------------------------------------------------------------


class TimelineTests(unittest.TestCase):
    def build(self, root: Path) -> ConfigMemoryStore:
        store = store_at(root)
        store.record(IOS_V1, discovery_session="r1",
                     collected_at="2026-07-13T09:00:00+00:00", **RECORD_KW)
        store.record(IOS_V2, discovery_session="r2",
                     collected_at="2026-07-14T09:42:00+00:00", **RECORD_KW)
        return store

    def test_device_timeline_reports_baseline_then_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self.build(Path(tmp))
            events = device_timeline(
                store.history("cisco-ios:core1"), config_text=store.config_text
            )
            self.assertEqual(2, len(events))
            newest, baseline = events
            self.assertEqual(2, newest.version)
            self.assertEqual(1, newest.previous_version)
            self.assertEqual("high", newest.highest_severity)
            self.assertGreater(newest.change_count, 0)
            self.assertIsNone(baseline.previous_version)
            self.assertIn("baseline", baseline.summary.casefold())

    def test_enterprise_timeline_excludes_baselines_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self.build(Path(tmp))
            events = enterprise_timeline(
                store.histories(), config_text=store.config_text
            )
            self.assertEqual(1, len(events))
            self.assertEqual(2, events[0].version)
            self.assertEqual("core1", events[0].hostname)

    def test_timeline_groups_by_day_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self.build(Path(tmp))
            days = group_by_day(
                device_timeline(
                    store.history("cisco-ios:core1"), config_text=store.config_text
                )
            )
            self.assertEqual(["2026-07-14", "2026-07-13"], [d["day"] for d in days])

    def test_missing_blob_degrades_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = self.build(Path(tmp))
            events = device_timeline(
                store.history("cisco-ios:core1"),
                config_text=lambda digest: None,   # blobs unavailable
                include_baseline=False,
            )
            self.assertEqual(1, len(events))
            self.assertIn("unavailable", events[0].summary)
            self.assertEqual(0, events[0].change_count)


# -- Part 1: collection policy -----------------------------------------------------


class CollectionPolicyTests(unittest.TestCase):
    NOW = "2026-07-14T09:00:00+00:00"

    def test_legacy_boolean_maps_to_always_or_disabled(self) -> None:
        self.assertEqual(POLICY_ALWAYS, normalize_policy(True))
        self.assertEqual(POLICY_DISABLED, normalize_policy(False))
        self.assertEqual(POLICY_DISABLED, normalize_policy(None))
        with self.assertRaises(ValueError):
            normalize_policy("sometimes")

    def test_always_and_disabled(self) -> None:
        self.assertTrue(decide_collection(POLICY_ALWAYS, now=self.NOW).collect)
        decision = decide_collection(POLICY_DISABLED, now=self.NOW)
        self.assertFalse(decision.collect)
        self.assertIn("disabled", decision.reason)

    def test_manual_requires_an_explicit_request(self) -> None:
        self.assertFalse(decide_collection(POLICY_MANUAL, now=self.NOW).collect)
        self.assertTrue(
            decide_collection(
                POLICY_MANUAL, now=self.NOW, manually_requested=True
            ).collect
        )

    def test_discovery_only_collects_with_discovery(self) -> None:
        self.assertTrue(
            decide_collection(
                POLICY_DISCOVERY_ONLY, now=self.NOW, is_discovery_run=True
            ).collect
        )
        self.assertFalse(
            decide_collection(
                POLICY_DISCOVERY_ONLY, now=self.NOW, is_discovery_run=False
            ).collect
        )

    def test_scheduled_respects_the_interval(self) -> None:
        first = decide_collection(POLICY_SCHEDULED, now=self.NOW)
        self.assertTrue(first.collect)          # never collected before
        due = decide_collection(
            POLICY_SCHEDULED, now=self.NOW,
            last_collected_at="2026-07-13T08:00:00+00:00", schedule_hours=24,
        )
        self.assertTrue(due.collect)
        not_due = decide_collection(
            POLICY_SCHEDULED, now=self.NOW,
            last_collected_at="2026-07-14T08:00:00+00:00", schedule_hours=24,
        )
        self.assertFalse(not_due.collect)
        self.assertIn("not due", not_due.reason)

    def test_editing_a_profile_preserves_policy_and_archived(self) -> None:
        # An edit must never silently un-archive a profile or reset how it
        # collects configuration.
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_profile(service, "Lab A", "10.0.0.1")
            service.update_profile("Lab A", collection_policy=POLICY_SCHEDULED,
                                   collection_schedule_hours=12)
            service.archive_profile("Lab A")
            # An unrelated edit…
            service.update_profile("Lab A", description="notes")
            profile = service.get_profile("Lab A")
            self.assertTrue(profile.archived)                       # preserved
            self.assertEqual(POLICY_SCHEDULED, profile.collection_policy)
            self.assertEqual(12, profile.collection_schedule_hours)
            self.assertEqual("notes", profile.description)

    def test_profile_policy_reaches_the_discovery_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_profile(service, "Lab A", "10.0.0.1")
            service.update_profile("Lab A", collection_policy=POLICY_ALWAYS)
            inputs = service.resolve_discovery_inputs("Lab A")
            self.assertEqual(POLICY_ALWAYS, inputs.collection_policy)

    def test_every_decision_states_a_reason(self) -> None:
        for policy in (POLICY_ALWAYS, POLICY_DISABLED, POLICY_MANUAL,
                       POLICY_DISCOVERY_ONLY, POLICY_SCHEDULED):
            decision = decide_collection(policy, now=self.NOW)
            self.assertTrue(decision.reason, policy)
            self.assertEqual(policy, decision.policy)


# -- Part 9: discovery integration -------------------------------------------------


def _network(description: str = "LINK-TO-SW1"):
    r1 = full_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),))
    r1["show running-config"] = (
        f"hostname R1\n!\ninterface GigabitEthernet0/1\n"
        f" description {description}\n ip address 10.0.0.1 255.255.255.0\n!\n"
        f"router bgp 65001\n neighbor 10.0.0.2 remote-as 65002\n!\n"
    )
    return ScriptedNetwork(
        {"10.0.0.1": r1, "10.0.0.2": full_outputs("SW1", "10.0.0.2")}
    )


def _secretive_network():
    """A device whose running-config carries credentials.

    Used by the page tests: proving the GUI does not leak a secret requires
    a device that has one to leak.
    """

    r1 = full_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),))
    r1["show running-config"] = (
        "hostname R1\n!\ninterface GigabitEthernet0/1\n"
        " description LINK-TO-SW1\n ip address 10.0.0.1 255.255.255.0\n!\n"
        "router bgp 65001\n neighbor 10.0.0.2 remote-as 65002\n!\n"
        "snmp-server community SUPERSECRET RO\n"
        "username admin privilege 15 secret 0 HUNTER2\n!\n"
    )
    return ScriptedNetwork(
        {"10.0.0.1": r1, "10.0.0.2": full_outputs("SW1", "10.0.0.2")}
    )


class DiscoveryIntegrationTests(unittest.TestCase):
    def test_discovery_remembers_configuration_without_extra_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1", collect_configuration=True)
            run_discover(workdir, service, _network(), "Lab A", FIXED)
            store = ConfigMemoryStore(scope_dir(workdir, "lab-a") / "config-memory")
            self.assertEqual(2, len(store.device_ids()))   # R1 + SW1
            history = next(
                h for h in store.histories() if h.hostname == "R1"
            )
            self.assertEqual(1, history.version_count)
            self.assertEqual("Lab A", history.network)
            self.assertIn("hostname R1", store.version_text(history.device_id, 1))

    def test_unchanged_rediscovery_adds_an_observation_not_a_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1", collect_configuration=True)
            run_discover(workdir, service, _network(), "Lab A", FIXED)
            run_discover(
                workdir, service, _network(), "Lab A", FIXED + timedelta(hours=3)
            )
            store = ConfigMemoryStore(scope_dir(workdir, "lab-a") / "config-memory")
            history = next(h for h in store.histories() if h.hostname == "R1")
            self.assertEqual(1, history.version_count)      # unchanged
            self.assertEqual(2, history.versions[0].observation_count)

    def test_changed_rediscovery_creates_v2_and_a_timeline_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1", collect_configuration=True)
            run_discover(workdir, service, _network(), "Lab A", FIXED)
            run_discover(
                workdir, service, _network("LINK-TO-SW1-NEW"), "Lab A",
                FIXED + timedelta(hours=6),
            )
            store = ConfigMemoryStore(scope_dir(workdir, "lab-a") / "config-memory")
            history = next(h for h in store.histories() if h.hostname == "R1")
            self.assertEqual(2, history.version_count)
            events = enterprise_timeline(
                store.histories(), config_text=store.config_text
            )
            self.assertTrue(events)
            self.assertEqual("R1", events[0].hostname)
            self.assertIn("description changed", events[0].summary)

    def test_disabled_collection_remembers_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1")  # collect_configuration=False
            run_discover(workdir, service, _network(), "Lab A", FIXED)
            store = ConfigMemoryStore(scope_dir(workdir, "lab-a") / "config-memory")
            self.assertEqual((), store.device_ids())


class ConfigViewerTests(unittest.TestCase):
    """Reading a remembered configuration is the point of remembering it.

    The GUI must be able to show one — and must never show a secret while
    doing it.
    """

    def test_viewer_renders_every_line_with_real_line_numbers(self) -> None:
        view = config_view(IOS_V1)
        self.assertEqual(len(IOS_V1.splitlines()), view.line_count)
        self.assertEqual(
            list(range(1, view.line_count + 1)),
            [line.number for line in view.lines],
        )

    def test_viewer_masks_secrets_and_says_how_many(self) -> None:
        view = config_view(IOS_V1)
        rendered = "\n".join(line.text for line in view.lines)
        self.assertNotIn("SUPERSECRET", rendered)
        self.assertNotIn("HUNTER2", rendered)
        self.assertEqual(2, view.masked_count)
        self.assertEqual(
            2, sum(1 for line in view.lines if line.masked)
        )

    def test_viewer_keeps_ordinary_configuration_readable(self) -> None:
        view = config_view(IOS_V1)
        rendered = "\n".join(line.text for line in view.lines)
        # Masking is per-line, not wholesale redaction.
        self.assertIn("hostname core1", rendered)
        self.assertIn("router bgp", rendered)

    def test_empty_configuration_views_as_nothing(self) -> None:
        view = config_view("")
        self.assertEqual(0, view.line_count)
        self.assertEqual(0, view.masked_count)


class FactsViewTests(unittest.TestCase):
    """``summary()`` answers "how many"; an operator asks "which ones"."""

    def test_view_carries_counts_and_the_detail_behind_them(self) -> None:
        facts = extract_facts(IOS_V1)
        view = facts.view()
        # Counts (what summary() gave) survive...
        self.assertEqual(view["interface_count"], len(facts.interfaces))
        self.assertEqual(view["bgp_neighbor_count"], len(facts.bgp_neighbors))
        # ...and the detail behind them is no longer discarded.
        self.assertEqual(len(facts.interfaces), len(view["interfaces"]))
        self.assertEqual(len(facts.bgp_neighbors), len(view["bgp_neighbors"]))
        self.assertIn("warnings", view)

    def test_view_never_carries_a_secret(self) -> None:
        rendered = repr(extract_facts(IOS_V1).view())
        self.assertNotIn("SUPERSECRET", rendered)
        self.assertNotIn("HUNTER2", rendered)


class DisplayTimezoneTests(unittest.TestCase):
    """Storage stays UTC; only the screen is converted."""

    def test_auto_resolves_to_system_local_and_utc_is_explicit(self) -> None:
        self.assertIsNone(resolve_timezone("auto"))
        self.assertIsNone(resolve_timezone(None))
        self.assertEqual(timezone.utc, resolve_timezone("UTC"))

    def test_unknown_zone_degrades_to_system_local_never_raises(self) -> None:
        self.assertIsNone(resolve_timezone("Not/AZone"))

    def test_timestamp_is_converted_and_always_names_its_zone(self) -> None:
        rendered = format_timestamp("2026-07-14T09:00:02+00:00", tz=timezone.utc)
        self.assertIn("09:00", rendered)
        self.assertIn("UTC", rendered)

    def test_naive_stored_timestamp_is_read_as_utc_not_guessed(self) -> None:
        aware = format_timestamp("2026-07-14T09:00:02+00:00", tz=timezone.utc)
        naive = format_timestamp("2026-07-14T09:00:02", tz=timezone.utc)
        self.assertEqual(aware, naive)

    def test_unparseable_value_is_shown_not_swallowed(self) -> None:
        self.assertEqual("not-a-time", format_timestamp("not-a-time"))
        self.assertEqual("never", format_timestamp(None))

    def test_relative_time_is_deterministic_given_now(self) -> None:
        now = datetime(2026, 7, 14, 9, 2, 2, tzinfo=timezone.utc)
        self.assertEqual(
            "2 minutes ago",
            format_relative("2026-07-14T09:00:02+00:00", now=now),
        )
        self.assertEqual(
            "just now", format_relative("2026-07-14T09:02:00+00:00", now=now)
        )

    def test_windows_long_zone_names_are_abbreviated(self) -> None:
        self.assertEqual("IST", _abbreviate("India Standard Time"))
        self.assertEqual("PST", _abbreviate("Pacific Standard Time"))
        # Initials of the spelled-out UTC would be wrong.
        self.assertEqual("UTC", _abbreviate("Coordinated Universal Time"))
        self.assertEqual("IST", _abbreviate("IST"))


class TimelineDayBoundaryTests(unittest.TestCase):
    """The day an operator groups changes by is *their* day.

    Timestamps are stored in UTC, so slicing the ISO prefix groups by the
    UTC day. For an operator at UTC+05:30 a change made at 02:00 on the 15th
    was recorded as 20:30 on the 14th — and would file under the wrong day.
    """

    def _event(self, occurred_at: str) -> TimelineEvent:
        return TimelineEvent(
            occurred_at=occurred_at,
            device_id="frr:core1",
            hostname="core1",
            network="lab",
            version=2,
            previous_version=1,
            summary="Interface eth1 description changed",
            change_count=1,
            discovery_session="s1",
        )

    def test_default_day_key_groups_by_the_utc_day(self) -> None:
        days = group_by_day((self._event("2026-07-14T20:30:00+00:00"),))
        self.assertEqual("2026-07-14", days[0]["day"])

    def test_operator_day_key_groups_by_the_operators_day(self) -> None:
        kolkata = resolve_timezone("Asia/Kolkata")
        if kolkata is None:  # pragma: no cover - platform lacks tzdata
            self.skipTest("IANA timezone data unavailable on this platform")
        days = group_by_day(
            (self._event("2026-07-14T20:30:00+00:00"),),
            day_of=day_key_for(kolkata),
        )
        # 20:30 UTC on the 14th is 02:00 on the 15th in Kolkata.
        self.assertEqual("2026-07-15", days[0]["day"])

    def test_grouping_preserves_events_and_counts(self) -> None:
        days = group_by_day(
            (
                self._event("2026-07-14T20:30:00+00:00"),
                self._event("2026-07-14T21:30:00+00:00"),
            ),
            day_of=day_key_for(timezone.utc),
        )
        self.assertEqual(1, len(days))
        self.assertEqual(2, days[0]["change_count"])


class ConfigurationPageTests(unittest.TestCase):
    """The rendered page, not the functions behind it.

    A green unit test proves ``config_view`` masks; it does not prove the
    *page* does. The route could call ``summary()``, the template could
    render an unmasked field — both were real defects. These tests assert on
    the HTML an operator actually receives.
    """

    def _client(self, workdir: Path):
        """A GUI over a discovered device whose configuration HAS secrets.

        The secrets are the point: a fixture without them would let a
        leaking page pass.
        """

        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1", collect_configuration=True)
        run_discover(workdir, service, _secretive_network(), "Lab A", FIXED)
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True, ATLAS_DISPLAY_TIMEZONE="UTC")
        self._device_id = next(
            h.device_id
            for h in ConfigMemoryStore(
                scope_dir(workdir, "lab-a") / "config-memory"
            ).histories()
            if h.hostname == "R1"
        )
        return app.test_client()

    def _device_page(self, client) -> str:
        response = client.get(f"/configuration/{self._device_id}")
        self.assertEqual(200, response.status_code)
        return response.get_data(as_text=True)

    def test_page_shows_the_configuration_not_only_counts_of_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._device_page(self._client(Path(tmp)))
            # A baseline device has no comparison — the configuration must
            # still be readable, which it previously was not.
            self.assertIn("Configuration — v1", page)
            self.assertIn("hostname", page)

    def test_page_renders_interface_detail_not_just_a_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._device_page(self._client(Path(tmp)))
            self.assertIn("Interfaces", page)
            # The address and description extraction already knew about.
            self.assertIn("GigabitEthernet0/1", page)

    def test_rendered_page_never_contains_a_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            page = self._device_page(client)
            # First prove the secret is really there to leak: the export
            # (the deliberate raw path) must show it. Without this the
            # assertions below could pass on a fixture that never had one.
            raw = client.get(
                f"/configuration/{self._device_id}/export/1"
            ).get_data(as_text=True)
            self.assertIn("SUPERSECRET", raw)
            self.assertIn("HUNTER2", raw)
            # The page renders the same configuration, masked.
            self.assertIn("Configuration — v1", page)
            self.assertNotIn("SUPERSECRET", page)
            self.assertNotIn("HUNTER2", page)

    def test_page_labels_the_timezone_it_renders_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._device_page(self._client(Path(tmp)))
            # A bare time is the ambiguity; the zone must be named.
            self.assertIn("UTC", page)

    def test_export_sends_one_charset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            response = client.get(f"/configuration/{self._device_id}/export/1")
            self.assertEqual(200, response.status_code)
            self.assertEqual(
                1, response.headers["Content-Type"].count("charset")
            )

    def test_settings_explains_storage_stays_utc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = self._client(Path(tmp)).get("/settings")
            page = response.get_data(as_text=True)
            self.assertEqual(200, response.status_code)
            self.assertIn("UTC", page)
            self.assertIn("ATLAS_DISPLAY_TIMEZONE", page)


if __name__ == "__main__":
    unittest.main()
