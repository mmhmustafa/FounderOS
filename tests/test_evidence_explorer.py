"""PR-047B (PROOF) — the Evidence Explorer.

The Evidence page reported on the storage engine: unique blobs, deduplicated
observations, stored bytes. True, and not one of them a question a network
engineer asks. These tests pin the page that replaced it:

- the summary counts collection, not storage;
- an **empty** response is never a failure and a **failed** one is never
  collected -- the two mistakes that would make Atlas cry wolf or hide a fault;
- a rendered page never contains a secret, a download always does;
- a bundle cannot be named out of its own directory;
- "used by" is traced by content address, never guessed, and says so honestly
  when it cannot answer;
- every pre-PROOF /memory URL still lands on the page that replaced it.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

from founderos_atlas.enterprise_memory import (
    EnterpriseMemory,
    EnterpriseMemoryStore,
)
from founderos_atlas.enterprise_memory.models import (
    COLLECTION_EMPTY,
    DiscoverySession,
    COLLECTION_ERROR,
    COLLECTION_OK,
    COLLECTION_UNAVAILABLE,
)
from founderos_atlas.web import evidence_bundle as bundle
from founderos_atlas.web import evidence_view as ev


FIXED = datetime(2026, 7, 15, 12, 30, 0, tzinfo=timezone.utc)

SECRET_CONFIG = """hostname core1
username atlas password 0 SUPERSECRET
enable secret 5 HUNTER2
interface Loopback0
 ip address 10.0.0.1 255.255.255.255
"""


def _build_memory(tmp: Path) -> EnterpriseMemory:
    """One device, one session, one configuration that really has secrets in it.

    The live FRR lab's configurations contain no password lines at all, so the
    lab cannot prove the masking guard. This fixture can.

    The history directory matters: "All Networks" aggregates only scopes that
    ``has_data()``, which means a snapshot or a history entry. A real discovery
    writes both that and the memory; a fixture that wrote only the memory would
    build a store no page ever reads, and every assertion below would be made
    against an empty page.
    """

    (tmp / ".atlas" / "history" / "2026-07-15_12-30-00").mkdir(parents=True, exist_ok=True)
    store = EnterpriseMemoryStore(tmp / "enterprise-memory", clock=lambda: FIXED)
    store.begin_session(DiscoverySession(
        session_id="s1", network="Delhi Lab", profile_id="lab",
        profile_name="Lab", started_at=FIXED.isoformat(),
        device_count=1, authenticated_count=1,
    ))
    store.store_evidence(
        device_id="frr:core1", hostname="core1",
        command="show running-config", output=SECRET_CONFIG,
        collection_status=COLLECTION_OK, discovery_session="s1", source="cli",
        platform="FRRouting",
    )
    store.store_evidence(
        device_id="frr:core1", hostname="core1",
        command="show lldp neighbors", output="",
        collection_status=COLLECTION_EMPTY, discovery_session="s1", source="cli",
        platform="FRRouting",
    )
    store.store_configuration(
        device_id="frr:core1", hostname="core1", discovery_session="s1",
        running_config=SECRET_CONFIG, platform="FRRouting",
    )
    return EnterpriseMemory(store)


def _bundle_text(data: bytes) -> str:
    """Every byte a bundle would hand someone, decompressed.

    A zip is DEFLATE-compressed, so `assertNotIn(b"SUPERSECRET", data)` against
    the raw archive passes whether or not the secret is in it -- a guard that
    cannot fail. Read every member, plus the entry names, and search THAT.
    """

    archive = zipfile.ZipFile(io.BytesIO(data))
    parts = list(archive.namelist())
    for name in archive.namelist():
        parts.append(archive.read(name).decode("utf-8", "replace"))
    return "\n".join(parts)


def _record(**overrides):
    row = {
        "device_id": "frr:core1", "hostname": "core1",
        "command": "show version", "source": "cli",
        "collected_at": "2026-07-15T12:30:00+00:00",
        "collection_status": COLLECTION_OK,
        "parser_version": "2026.07", "discovery_session": "s1",
        "content_sha256": "a" * 64, "byte_size": 420, "transport": "ssh",
        "platform": "FRRouting", "software_version": "8.4_git",
    }
    row.update(overrides)
    return row


class StatusMeaningTests(unittest.TestCase):
    """The distinction the whole page rests on."""

    def test_an_empty_response_is_not_a_failure(self) -> None:
        # The live lab's nine FRR devices all return nothing for
        # `show lldp neighbors`. Calling that a failure would report nine
        # faults in a network with none -- the exact defect PR-043 removed
        # from Mission.
        self.assertFalse(ev.is_failure(COLLECTION_EMPTY))
        self.assertEqual("Empty", ev.status_display(COLLECTION_EMPTY).label)
        self.assertIn("not a failure", ev.status_display(COLLECTION_EMPTY).meaning)

    def test_an_unsupported_command_is_not_a_failure(self) -> None:
        self.assertFalse(ev.is_failure(COLLECTION_UNAVAILABLE))
        self.assertEqual("Unsupported", ev.status_display(COLLECTION_UNAVAILABLE).label)

    def test_a_failure_is_a_failure(self) -> None:
        self.assertTrue(ev.is_failure(COLLECTION_ERROR))
        self.assertEqual("Failed", ev.status_display(COLLECTION_ERROR).label)

    def test_a_failure_is_never_reported_as_collected(self) -> None:
        # The inverse mistake, and the worse one: it would hide a real gap
        # behind a number that says everything is fine.
        for status in (COLLECTION_ERROR, COLLECTION_EMPTY, COLLECTION_UNAVAILABLE):
            self.assertFalse(ev.is_collected(status), status)
        self.assertTrue(ev.is_collected(COLLECTION_OK))

    def test_an_unrecognised_status_is_unknown_not_guessed(self) -> None:
        display = ev.status_display("something-new")
        self.assertEqual("Unknown", display.label)
        self.assertEqual("Unknown", ev.status_display(None).label)


class CollectionSummaryTests(unittest.TestCase):
    def test_the_summary_counts_what_was_collected(self) -> None:
        records = (
            [_record(command=f"cmd{i}") for i in range(54)]
            + [_record(command="show lldp neighbors", collection_status=COLLECTION_EMPTY,
                       content_sha256="") for _ in range(9)]
        )
        session = {
            "network": "Delhi Lab", "session_id": "s1", "started_at": "2026-07-15",
            "device_count": 9, "authenticated_count": 9, "warning_count": 0,
        }
        summary = ev.collection_summary(session, records)
        self.assertEqual(63, summary.commands_attempted)
        self.assertEqual(54, summary.commands_collected)
        self.assertEqual(9, summary.empty_responses)
        self.assertEqual(0, summary.failed_collections)
        self.assertEqual(9, summary.devices_reached)
        self.assertEqual(9, summary.devices_authenticated)

    def test_empty_responses_do_not_reduce_completeness(self) -> None:
        """A healthy lab that simply does not run LLDP reaches 100%.

        If an empty response counted against completeness, this page would nag
        forever about a network with nothing wrong with it.
        """

        self.assertEqual(100, ev.completeness_percent(63, failed=0, unsupported=0))

    def test_failures_and_unsupported_commands_do_reduce_completeness(self) -> None:
        self.assertEqual(90, ev.completeness_percent(10, failed=1, unsupported=0))
        self.assertEqual(90, ev.completeness_percent(10, failed=0, unsupported=1))
        self.assertEqual(80, ev.completeness_percent(10, failed=1, unsupported=1))

    def test_completeness_of_nothing_is_unknown_not_a_number(self) -> None:
        # Neither 0% (a lie about failure) nor 100% (a lie about success).
        self.assertIsNone(ev.completeness_percent(0, failed=0, unsupported=0))
        self.assertIsNone(ev.collection_summary({}, []).completeness_percent)


class DeviceGroupingTests(unittest.TestCase):
    def test_each_canonical_device_appears_exactly_once(self) -> None:
        records = [
            _record(device_id="frr:core1", command="show version"),
            _record(device_id="frr:core1", command="show interface"),
            _record(device_id="frr:edge1", hostname="edge1", command="show version"),
        ]
        rows = ev.device_rows(records)
        self.assertEqual(2, len(rows))
        self.assertEqual(["core1", "edge1"], [r["hostname"] for r in rows])
        self.assertEqual(2, rows[0]["commands_attempted"])

    def test_a_device_row_separates_empty_from_failed(self) -> None:
        records = [
            _record(command="show version"),
            _record(command="show lldp neighbors", collection_status=COLLECTION_EMPTY),
            _record(command="show broken", collection_status=COLLECTION_ERROR),
        ]
        row = ev.device_rows(records)[0]
        self.assertEqual(3, row["commands_attempted"])
        self.assertEqual(1, row["commands_collected"])
        self.assertEqual(1, row["empty_responses"])
        self.assertEqual(1, row["failed_collections"])

    def test_a_device_with_no_configuration_says_so(self) -> None:
        row = ev.device_rows([_record()])[0]
        self.assertFalse(row["has_configuration"])
        self.assertEqual("Not collected", row["configuration_status"])


class UsedByTests(unittest.TestCase):
    """Part 6: never invent a relationship between evidence and a conclusion."""

    def test_evidence_with_no_usage_tracking_says_so_honestly(self) -> None:
        usage = ev.used_by(_record(command="show version"))
        self.assertFalse(usage.tracked)
        self.assertEqual(0, len(usage.findings))
        self.assertIn("not available yet", usage.message)

    def test_a_policy_finding_is_reported_only_when_it_cites_this_evidence(self) -> None:
        record = _record(command="show running-config", content_sha256="c" * 64)
        mine = {
            "device_id": "frr:core1",
            "policy": {"name": "Hostname Configured"},
            "status_label": "Passed",
            "result": {"evidence_used": [{"payload": {"config_sha256": "c" * 64}}]},
        }
        # Same device, same policy shape -- but it used a DIFFERENT snapshot.
        # Matching on device alone would wrongly claim this one.
        other = {
            "device_id": "frr:core1",
            "policy": {"name": "From An Older Snapshot"},
            "status_label": "Failed",
            "result": {"evidence_used": [{"payload": {"config_sha256": "d" * 64}}]},
        }
        usage = ev.used_by(record, policy_evaluations=[mine, other])
        self.assertTrue(usage.tracked)
        titles = [f.title for f in usage.findings]
        self.assertIn("Hostname Configured", titles)
        self.assertNotIn("From An Older Snapshot", titles)

    def test_another_devices_finding_is_never_claimed(self) -> None:
        record = _record(command="show running-config", content_sha256="c" * 64)
        theirs = {
            "device_id": "frr:edge1",
            "policy": {"name": "Someone Else's Policy"},
            "status_label": "Passed",
            "result": {"evidence_used": [{"payload": {"config_sha256": "c" * 64}}]},
        }
        usage = ev.used_by(record, policy_evaluations=[theirs])
        self.assertNotIn(
            "Someone Else's Policy", [f.title for f in usage.findings]
        )

    def test_traceability_is_limited_to_evidence_atlas_can_actually_follow(self) -> None:
        self.assertTrue(ev.is_traceable(_record(command="show running-config")))
        self.assertFalse(ev.is_traceable(_record(command="show ip route")))
        # ...and a config record with no stored output cannot be traced either.
        self.assertFalse(
            ev.is_traceable(_record(command="show running-config", content_sha256=""))
        )


class NormalizedFactsTests(unittest.TestCase):
    def test_facts_come_from_what_atlas_already_stored(self) -> None:
        facts = ev.normalized_facts(_record())
        labels = {f["label"]: f["value"] for f in facts}
        self.assertEqual("core1", labels["Hostname"])
        self.assertEqual("FRRouting", labels["Platform"])
        self.assertEqual("8.4_git", labels["Software version"])

    def test_a_fingerprint_count_of_zero_is_shown_a_missing_key_is_not(self) -> None:
        facts = ev.normalized_facts(
            _record(command="show running-config"),
            snapshot={"fingerprint": {"acl_count": 0, "interface_count": 6}},
        )
        labels = {f["label"]: f["value"] for f in facts}
        self.assertEqual("0", labels["Access lists"])     # zero is a fact
        self.assertEqual("6", labels["Interfaces"])
        self.assertNotIn("VLANs", labels)                 # absent is silence

    def test_no_facts_is_an_empty_tuple_not_an_invention(self) -> None:
        facts = ev.normalized_facts(
            {"command": "show version", "content_sha256": "a" * 64}
        )
        self.assertEqual((), facts)


class BundleSafetyTests(unittest.TestCase):
    def test_a_name_cannot_escape_the_bundle(self) -> None:
        self.assertEqual("etc-passwd", bundle.safe_name("../../etc/passwd"))
        self.assertEqual("etc-shadow", bundle.safe_name("/etc/shadow"))
        self.assertEqual("frr-core1", bundle.safe_name("frr:core1"))
        self.assertEqual("show-ip-route", bundle.safe_name("show ip route"))
        self.assertEqual("unnamed", bundle.safe_name(""))
        self.assertEqual("unnamed", bundle.safe_name("../.."))

    def test_no_bundle_entry_is_absolute_or_relative(self) -> None:
        for hostile in ("../../etc/passwd", "/etc/shadow", "..\\..\\win.ini"):
            name = bundle.safe_name(hostile)
            self.assertFalse(name.startswith(("/", ".", "\\")))
            self.assertNotIn("..", name)


class MemoryBackedTests(unittest.TestCase):
    """Against a real store, with a configuration that really has secrets in it."""

    def _memory(self, tmp: Path) -> EnterpriseMemory:
        return _build_memory(tmp)

    def test_a_default_bundle_masks_every_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = self._memory(Path(tmp))
            data = bundle.build_device_bundle(memory, "frr:core1")
            whole = _bundle_text(data)
            # Not one secret anywhere in the archive -- including the metadata
            # and the entry names, not only the output files.
            self.assertNotIn("SUPERSECRET", whole)
            self.assertNotIn("HUNTER2", whole)
            archive = zipfile.ZipFile(io.BytesIO(data))
            config = archive.read("show-running-config.txt").decode()
            self.assertIn("masked", config)
            self.assertIn("hostname core1", config)  # non-secrets survive

    def test_a_raw_bundle_carries_the_bytes_and_says_that_it_does(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = self._memory(Path(tmp))
            archive = zipfile.ZipFile(io.BytesIO(
                bundle.build_device_bundle(memory, "frr:core1", raw=True)
            ))
            self.assertIn("SUPERSECRET", archive.read("show-running-config.txt").decode())
            manifest = archive.read("evidence-metadata.json").decode()
            self.assertIn('"masked": false', manifest)
            self.assertIn("RAW EXPORT", manifest)

    def test_an_empty_command_has_no_file_but_keeps_its_record(self) -> None:
        """Omitting it entirely would let a reader conclude Atlas never ran it."""

        with tempfile.TemporaryDirectory() as tmp:
            import json

            memory = self._memory(Path(tmp))
            archive = zipfile.ZipFile(io.BytesIO(
                bundle.build_device_bundle(memory, "frr:core1")
            ))
            self.assertNotIn("show-lldp-neighbors.txt", archive.namelist())
            meta = json.loads(archive.read("evidence-metadata.json"))
            lldp = next(r for r in meta["records"] if "lldp" in r["command"])
            self.assertIsNone(lldp["output_file"])
            self.assertEqual(COLLECTION_EMPTY, lldp["collection_status"])

    def test_a_session_bundle_has_one_directory_per_device(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = self._memory(Path(tmp))
            data = bundle.build_session_bundle(memory, "s1")
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
            self.assertIn("session-summary.json", names)
            self.assertIn("core1/show-running-config.txt", names)
            self.assertIn("core1/evidence-metadata.json", names)
            self.assertNotIn("SUPERSECRET", _bundle_text(data))

    def test_the_same_evidence_bundles_to_the_same_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = self._memory(Path(tmp))
            self.assertEqual(
                bundle.build_session_bundle(memory, "s1"),
                bundle.build_session_bundle(memory, "s1"),
            )

    def test_a_bundle_of_nothing_is_none_not_an_empty_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = self._memory(Path(tmp))
            self.assertIsNone(bundle.build_device_bundle(memory, "frr:nobody"))
            self.assertIsNone(bundle.build_session_bundle(memory, "no-such-session"))


class ExplorerPageTests(unittest.TestCase):
    """The rendered Explorer, over a store that really has a secret in it."""

    def _client(self, tmp: Path):
        from founderos_atlas.web import create_app

        _build_memory(tmp)
        app = create_app(
            output_dir=tmp,
            history_root=tmp / ".atlas" / "history",
            workspace_root=tmp / "workspace",
        )
        app.config.update(TESTING=True, ATLAS_DISPLAY_TIMEZONE="UTC")
        return app.test_client()

    def test_the_summary_reports_collection_not_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._client(Path(tmp)).get("/evidence").get_data(as_text=True)
            body = page.split("<main", 1)[1]
            for label in (
                "Devices reached", "Configurations collected", "Commands attempted",
                "Collected successfully", "Empty responses", "Failed collections",
                "Collection completeness",
            ):
                self.assertIn(label, body, f"{label} missing from the summary")

    def test_storage_internals_survive_but_only_under_system_details(self) -> None:
        """Part 12: kept for administrators, not deleted -- and not in the way."""

        with tempfile.TemporaryDirectory() as tmp:
            body = self._client(Path(tmp)).get("/evidence").get_data(as_text=True)
            self.assertIn("Enterprise Memory — System Details", body)
            self.assertIn("Unique blobs stored", body)
            # The storage numbers must sit inside the collapsed drawer, not
            # above it where they used to define the page.
            head, _, drawer = body.partition("<details>")
            self.assertIn("Unique blobs stored", drawer)
            self.assertNotIn("Unique blobs stored", head)

    def test_an_empty_response_renders_as_empty_and_never_as_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._client(Path(tmp)).get(
                "/evidence/device/frr:core1"
            ).get_data(as_text=True)
            block = page.split("show lldp neighbors", 1)[1][:400]
            self.assertIn("Empty", block)
            self.assertNotIn("Failed", block)
            self.assertNotIn("badge-bad", block)

    def test_a_record_page_masks_output_and_offers_the_raw_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            page = client.get("/evidence/device/frr:core1").get_data(as_text=True)
            sha = re.search(
                r"show running-config.*?/record/([0-9a-f]{64})", page, re.DOTALL
            ).group(1)
            view = client.get(
                f"/evidence/device/frr:core1/record/{sha}"
            ).get_data(as_text=True)
            self.assertNotIn("SUPERSECRET", view)
            self.assertNotIn("HUNTER2", view)
            self.assertIn("hostname core1", view)          # non-secrets survive
            self.assertIn("Copy Output", view)
            self.assertIn(f"/record/{sha}/download", view)

            raw = client.get(
                f"/evidence/device/frr:core1/record/{sha}/download"
            ).get_data(as_text=True)
            self.assertIn("SUPERSECRET", raw)   # download is the raw path

    def test_a_config_record_names_the_policies_that_used_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            page = client.get("/evidence/device/frr:core1").get_data(as_text=True)
            sha = re.search(
                r"show running-config.*?/record/([0-9a-f]{64})", page, re.DOTALL
            ).group(1)
            view = client.get(
                f"/evidence/device/frr:core1/record/{sha}"
            ).get_data(as_text=True)
            self.assertIn("Used By Atlas", view)
            # The starter pack's Hostname policy reads this exact snapshot.
            self.assertIn("Hostname Configured", view)

    def test_device_rows_offer_the_universal_device_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._client(Path(tmp)).get("/evidence").get_data(as_text=True)
            self.assertIn("device-actions", page)

    def test_filters_narrow_the_table_but_never_the_summary(self) -> None:
        """A filtered view that also re-scored completeness would let an
        operator narrow to one device and read its number as the network's."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            page = client.get(
                "/evidence?session=s1&command=show+running-config"
            ).get_data(as_text=True)
            self.assertIn("Showing 1 of 2 evidence records", page)
            # ...and the summary still describes the whole session: 2 commands.
            body = page.split("Commands attempted", 1)[1][:80]
            self.assertIn("2", body)

    def test_a_filter_that_matches_nothing_says_so_and_offers_a_way_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._client(Path(tmp)).get(
                "/evidence?session=s1&q=nonexistent-device"
            ).get_data(as_text=True)
            self.assertIn("No evidence matches these filters", page)

    def test_a_nonsense_page_number_is_a_typo_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            self.assertEqual(
                200, client.get("/evidence/device/frr:core1?page=banana").status_code
            )
            self.assertEqual(
                200, client.get("/evidence/device/frr:core1?page=9999").status_code
            )

    def test_a_listing_page_never_reads_a_blob(self) -> None:
        """Part 11: the tables are built from the records index alone.

        Proven by sabotage: if a listing needed output it would call
        view_evidence, and this replaces it with a recorder. The point is not
        that it succeeds -- it is that it never asks.
        """

        from founderos_atlas.enterprise_memory.retrieval import EnterpriseMemory

        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            original = EnterpriseMemory.view_evidence
            calls: list[int] = []

            def spy(self, record):
                calls.append(1)
                return original(self, record)

            EnterpriseMemory.view_evidence = spy
            try:
                self.assertEqual(200, client.get("/evidence").status_code)
                self.assertEqual(
                    200, client.get("/evidence/device/frr:core1").status_code
                )
                self.assertEqual([], calls, "a listing page read evidence output")
                # ...and opening one item does read exactly that item.
                page = client.get("/evidence/device/frr:core1").get_data(as_text=True)
                sha = re.search(r"/record/([0-9a-f]{64})", page).group(1)
                calls.clear()
                client.get(f"/evidence/device/frr:core1/record/{sha}")
                self.assertEqual(1, len(calls), "opening a record read no output")
            finally:
                EnterpriseMemory.view_evidence = original

    def test_bundles_download_and_carry_no_secret_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            response = client.get("/evidence/device/frr:core1/bundle")
            self.assertEqual(200, response.status_code)
            self.assertIn("evidence-device-frr-core1.zip",
                          response.headers["Content-Disposition"])
            self.assertNotIn("SUPERSECRET", _bundle_text(response.data))

            session = client.get("/evidence/session/s1/bundle")
            self.assertEqual(200, session.status_code)
            self.assertNotIn("SUPERSECRET", _bundle_text(session.data))

            # A raw export is available, and is labelled raw in its own filename.
            raw = client.get("/evidence/device/frr:core1/bundle?raw=1")
            self.assertIn("SUPERSECRET", _bundle_text(raw.data))
            self.assertIn("-raw.zip", raw.headers["Content-Disposition"])

    def test_no_page_leaks_a_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            for url in ("/evidence", "/evidence?session=s1",
                        "/evidence/device/frr:core1"):
                body = client.get(url, follow_redirects=True).get_data(as_text=True)
                self.assertIn("Atlas", body, f"{url} rendered no page to check")
                self.assertNotIn("SUPERSECRET", body)
                self.assertNotIn("HUNTER2", body)


class RouteCompatibilityTests(unittest.TestCase):
    """Renaming a route is not worth breaking a bookmark."""

    def _client(self, tmp: Path):
        from founderos_atlas.web import create_app

        _build_memory(tmp)
        app = create_app(
            output_dir=tmp, history_root=tmp / ".atlas" / "history",
            workspace_root=tmp / "workspace",
        )
        app.config.update(TESTING=True, ATLAS_DISPLAY_TIMEZONE="UTC")
        return app.test_client()

    def test_every_old_evidence_url_still_arrives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            page = client.get("/evidence/device/frr:core1").get_data(as_text=True)
            sha = re.search(r"/record/([0-9a-f]{64})", page).group(1)
            for old, new in (
                ("/memory", "/evidence"),
                ("/memory/session/s1", "/evidence"),
                ("/memory/device/frr:core1", "/evidence/device/frr:core1"),
                (f"/memory/device/frr:core1/evidence/{sha}",
                 f"/evidence/device/frr:core1/record/{sha}"),
            ):
                response = client.get(old)
                self.assertEqual(302, response.status_code, old)
                self.assertIn(new, response.headers["Location"], old)
                self.assertEqual(
                    200, client.get(old, follow_redirects=True).status_code,
                    f"{old} redirects nowhere",
                )

    def test_the_old_download_url_still_serves_the_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            page = client.get("/evidence/device/frr:core1").get_data(as_text=True)
            sha = re.search(
                r"show running-config.*?/record/([0-9a-f]{64})", page, re.DOTALL
            ).group(1)
            raw = client.get(
                f"/memory/device/frr:core1/evidence/{sha}/download",
                follow_redirects=True,
            )
            self.assertEqual(200, raw.status_code)
            self.assertIn(b"SUPERSECRET", raw.data)


if __name__ == "__main__":
    unittest.main()
