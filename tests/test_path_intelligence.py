"""Acceptance tests for PR-037 — Atlas Path Intelligence (FLOW).

The first vertical slice of end-to-end connectivity investigation:
deterministic path construction from discovered topology, hop-by-hop
validation against collected evidence, first-failure detection with a
cited WHY, honest ambiguity and unknowns, an investigation story, scope
history for replay, and the Path Intelligence GUI page.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.path_intelligence import (
    investigate_path,
    investigate_path_for_scope,
    load_investigation_history,
    render_investigation_json,
    render_investigation_markdown,
)

from tests.test_atlas_transport import PASSWORD
from tests.test_prediction_architecture import NOW, chain, topology
from tests.test_profile_isolation import (
    A2_DOWN_BRIEF,
    FIXED,
    add_profile,
    make_service,
    network_a,
    run_discover,
    scope_dir,
)


def set_interface_status(snapshot: dict, device: str, interface: str, status: str) -> dict:
    for entry in snapshot["devices"]:
        if entry["hostname"] == device:
            for item in entry["interfaces"]:
                if item["name"] == interface:
                    item["status"] = status
    return snapshot


def diamond() -> dict:
    """R1 -- (A|B) -- SW9: two equally short paths, deliberately ambiguous."""

    return topology(
        {
            "R1": ["Gi0/1", "Gi0/2"],
            "A": ["Gi0/1", "Gi0/2"],
            "B": ["Gi0/1", "Gi0/2"],
            "SW9": ["Gi0/1", "Gi0/2"],
        },
        (
            ("R1", "Gi0/1", "A", "Gi0/1"),
            ("R1", "Gi0/2", "B", "Gi0/1"),
            ("A", "Gi0/2", "SW9", "Gi0/1"),
            ("B", "Gi0/2", "SW9", "Gi0/2"),
        ),
    )


class PathConstructionTests(unittest.TestCase):
    def test_chain_end_to_end_all_hops_pass(self) -> None:
        result = investigate_path("R1", "SW2", snapshot=chain(), generated_at=NOW)
        self.assertEqual("connected", result.status)
        self.assertEqual(("R1", "SW1", "SW2"), result.path)
        self.assertEqual(3, len(result.hops))
        self.assertTrue(all(hop.status == "pass" for hop in result.hops))
        first, middle, last = result.hops
        self.assertIsNone(first.ingress_interface)
        self.assertEqual("Gi0/1", first.egress_interface)
        self.assertEqual("Gi0/1", middle.ingress_interface)
        self.assertEqual("Gi0/2", middle.egress_interface)
        self.assertEqual("Gi0/1", last.ingress_interface)
        self.assertIsNone(last.egress_interface)
        self.assertIsNone(result.failure_type)
        # The story narrates locating both endpoints, the constructed
        # path, every hop, and a conclusion.
        titles = [step.title for step in result.steps]
        self.assertIn("Locate source device R1", titles)
        self.assertIn("Construct path from topology evidence", titles)
        self.assertEqual("Conclusion", titles[-1])

    def test_evidence_is_cited_and_confidence_capped(self) -> None:
        result = investigate_path("R1", "SW2", snapshot=chain(), generated_at=NOW)
        self.assertLessEqual(result.confidence, 0.95)
        self.assertTrue(
            any("topology snapshot" in ref for ref in result.evidence_refs)
        )
        for hop in result.hops:
            self.assertLessEqual(hop.confidence, 0.95)
            self.assertTrue(hop.evidence, hop.device)
        middle = result.hops[1]
        self.assertTrue(
            any("interface table SW1 Gi0/2" in item for item in middle.evidence)
        )

    def test_management_address_resolves_like_a_hostname(self) -> None:
        # 10.0.0.1 is R1's management address in the fixture.
        result = investigate_path(
            "10.0.0.1", "SW2", snapshot=chain(), generated_at=NOW
        )
        self.assertEqual("connected", result.status)
        self.assertEqual(("R1", "SW1", "SW2"), result.path)

    def test_same_source_and_destination_validates_the_device_only(self) -> None:
        result = investigate_path("R1", "R1", snapshot=chain(), generated_at=NOW)
        self.assertEqual("connected", result.status)
        self.assertEqual(("R1",), result.path)
        self.assertEqual(1, len(result.hops))


class FirstFailureTests(unittest.TestCase):
    def test_operationally_down_interface_stops_the_walk(self) -> None:
        snapshot = set_interface_status(chain(), "SW1", "Gi0/2", "down")
        result = investigate_path("R1", "SW2", snapshot=snapshot, generated_at=NOW)
        self.assertEqual("failed", result.status)
        self.assertEqual("interface-down", result.failure_type)
        self.assertEqual("failed", result.hops[1].status)
        self.assertEqual("down", result.hops[1].link_state)
        self.assertIn("SW1 Gi0/2 is operationally down", result.hops[1].explanation)
        # Hops after the failure are honestly not evaluated — never
        # assumed healthy or broken.
        self.assertEqual("unknown", result.hops[2].status)
        self.assertIn("Not evaluated", result.hops[2].explanation)
        self.assertIn("SW1", result.failure_summary)
        self.assertTrue(
            any("physical layer" in item for item in result.recommendations)
        )

    def test_admin_shutdown_is_a_distinct_failure_with_its_own_why(self) -> None:
        snapshot = set_interface_status(
            chain(), "SW1", "Gi0/2", "administratively down"
        )
        result = investigate_path("R1", "SW2", snapshot=snapshot, generated_at=NOW)
        self.assertEqual("failed", result.status)
        self.assertEqual("administrative-shutdown", result.failure_type)
        self.assertEqual("administratively-down", result.hops[1].link_state)
        self.assertIn("administratively shut down", result.hops[1].explanation)
        self.assertIn("an operator disabled it", result.hops[1].explanation)
        self.assertTrue(
            any("why" in item.casefold() for item in result.recommendations)
        )

    def test_ingress_side_failures_are_detected_too(self) -> None:
        snapshot = set_interface_status(chain(), "SW2", "Gi0/1", "down")
        result = investigate_path("R1", "SW2", snapshot=snapshot, generated_at=NOW)
        self.assertEqual("failed", result.status)
        self.assertEqual("SW2", result.hops[2].device)
        self.assertEqual("failed", result.hops[2].status)

    def test_unreachable_device_fails_with_discovery_evidence(self) -> None:
        result = investigate_path(
            "R1",
            "SW2",
            snapshot=chain(),
            generated_at=NOW,
            failed_hosts=("10.0.0.2",),  # SW1's management address
        )
        self.assertEqual("failed", result.status)
        self.assertEqual("device-unreachable", result.failure_type)
        failed = result.hops[1]
        self.assertEqual("SW1", failed.device)
        self.assertEqual("failed", failed.management_state)
        self.assertIn("could not reach SW1", failed.explanation)
        self.assertTrue(
            any("powered" in item for item in result.recommendations)
        )

    def test_captured_configuration_is_cited_on_the_failed_hop(self) -> None:
        snapshot = set_interface_status(
            chain(), "SW1", "Gi0/2", "administratively down"
        )
        result = investigate_path(
            "R1",
            "SW2",
            snapshot=snapshot,
            generated_at=NOW,
            captured_config_devices=("SW1",),
        )
        self.assertTrue(
            any("running configuration" in item for item in result.hops[1].evidence)
        )
        self.assertTrue(
            any("configs/" in item for item in result.recommendations)
        )


class HonestyTests(unittest.TestCase):
    def test_unknown_source_is_reported_not_guessed(self) -> None:
        result = investigate_path("R9", "SW2", snapshot=chain(), generated_at=NOW)
        self.assertEqual("unknown", result.status)
        self.assertEqual("unknown-device", result.failure_type)
        self.assertIn("R9", result.failure_summary)
        self.assertTrue(
            any("Verify the device name" in item for item in result.recommendations)
        )

    def test_unknown_destination_recommends_discovery(self) -> None:
        result = investigate_path("R1", "SW99", snapshot=chain(), generated_at=NOW)
        self.assertEqual("unknown", result.status)
        self.assertEqual("unknown-destination", result.failure_type)
        self.assertTrue(
            any("fresh discovery" in item for item in result.recommendations)
        )

    def test_no_topology_edge_yields_unknown_path_never_a_guess(self) -> None:
        snapshot = topology(
            {"R1": ["Gi0/1"], "SW1": ["Gi0/1"], "LONER": ["Gi0/1"]},
            (("R1", "Gi0/1", "SW1", "Gi0/1"),),
        )
        result = investigate_path("R1", "LONER", snapshot=snapshot, generated_at=NOW)
        self.assertEqual("unknown", result.status)
        self.assertEqual("discovery-incomplete", result.failure_type)
        self.assertIn("no discovered links at all", result.failure_summary)
        self.assertTrue(
            any("CDP/LLDP" in item for item in result.recommendations)
        )
        self.assertTrue(result.unknowns)

    def test_equal_cost_paths_are_reported_as_redundancy(self) -> None:
        # Multiple equal-cost paths are REDUNDANCY (a resilient design), not
        # a failure: the endpoints are connected via several paths, reported
        # positively. Only WHICH path a flow uses stays an honest unknown.
        result = investigate_path("R1", "SW9", snapshot=diamond(), generated_at=NOW)
        self.assertEqual("connected", result.status)   # not "ambiguous"
        self.assertIsNone(result.failure_type)
        candidates = result.basis["redundant_paths"]
        self.assertEqual(2, len(candidates))
        self.assertIn("R1 → A → SW9", candidates)
        self.assertIn("R1 → B → SW9", candidates)
        self.assertEqual(2, result.basis["redundant_path_count"])
        self.assertEqual(2, result.basis["validated_up_paths"])
        self.assertEqual(0, result.basis["degraded_paths"])
        # A representative validated path carries the hop detail.
        self.assertTrue(result.hops)
        self.assertTrue(all(hop.status != "failed" for hop in result.hops))
        # Redundancy is framed as resilience.
        self.assertTrue(
            any("resilience" in item.casefold() for item in result.recommendations)
        )
        # Path selection stays an honest unknown, but never a failure.
        self.assertTrue(
            any("which of the equal-cost paths" in item.casefold()
                for item in result.unknowns)
        )

    def test_equal_cost_paths_with_all_down_is_a_real_failure(self) -> None:
        # If EVERY redundant path has a broken hop, that's a genuine failure.
        snap = diamond()
        snap = set_interface_status(snap, "A", "Gi0/2", "down")
        snap = set_interface_status(snap, "B", "Gi0/2", "down")
        result = investigate_path("R1", "SW9", snapshot=snap, generated_at=NOW)
        self.assertEqual("failed", result.status)

    def test_missing_interface_record_is_a_warning_not_a_failure(self) -> None:
        snapshot = chain()
        for entry in snapshot["devices"]:
            if entry["hostname"] == "SW1":
                entry["interfaces"] = [
                    item for item in entry["interfaces"] if item["name"] != "Gi0/2"
                ]
        result = investigate_path("R1", "SW2", snapshot=snapshot, generated_at=NOW)
        self.assertEqual("connected", result.status)
        middle = result.hops[1]
        self.assertEqual("warning", middle.status)
        self.assertTrue(middle.missing_evidence)
        self.assertIn(
            "absent from the collected interface table",
            middle.missing_evidence[0],
        )
        self.assertLess(middle.confidence, result.hops[0].confidence)
        self.assertTrue(result.unknowns)

    def test_neighbor_only_destination_is_flagged_not_trusted(self) -> None:
        snapshot = chain()
        snapshot["devices"] = [
            entry for entry in snapshot["devices"] if entry["hostname"] != "SW2"
        ]
        result = investigate_path("R1", "SW2", snapshot=snapshot, generated_at=NOW)
        self.assertEqual("connected", result.status)
        last = result.hops[-1]
        self.assertEqual("warning", last.status)
        self.assertIn("neighbor announcements", last.explanation)
        self.assertIn("has not discovered it directly", last.explanation)

    def test_stale_evidence_lowers_confidence_and_is_disclosed(self) -> None:
        fresh = investigate_path("R1", "SW2", snapshot=chain(), generated_at=NOW)
        stale = investigate_path(
            "R1", "SW2", snapshot=chain(), generated_at=NOW, fresh=False
        )
        self.assertLess(stale.confidence, fresh.confidence)
        self.assertTrue(
            any("freshness window" in item for item in stale.unknowns)
        )

    def test_no_snapshot_at_all_asks_for_a_discovery(self) -> None:
        result = investigate_path("R1", "SW2", snapshot=None, generated_at=NOW)
        self.assertEqual("unknown", result.status)
        self.assertEqual("discovery-incomplete", result.failure_type)
        self.assertIn("Run a discovery", result.recommendations[0])

    def test_identical_evidence_yields_byte_identical_reports(self) -> None:
        first = investigate_path("R1", "SW2", snapshot=chain(), generated_at=NOW)
        second = investigate_path("R1", "SW2", snapshot=chain(), generated_at=NOW)
        self.assertEqual(
            render_investigation_json(first), render_investigation_json(second)
        )
        self.assertEqual(first.investigation_id, second.investigation_id)


class ServiceAndHistoryTests(unittest.TestCase):
    def discover_lab(self, workdir: Path, *, a2_interfaces: str | None = None,
                     start=FIXED, service=None):
        if service is None:
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1")
        code, out, err = run_discover(
            workdir, service, network_a(a2_interfaces=a2_interfaces), "Lab A", start
        )
        assert code == 0, err
        return service, scope_dir(workdir, "lab-a")

    def test_investigation_over_real_scope_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, scope = self.discover_lab(workdir)
            result = investigate_path_for_scope(
                "A1",
                "A2",
                output_dir=scope,
                history_root=scope / "history",
                generated_at=(FIXED + timedelta(minutes=5)).isoformat(
                    timespec="seconds"
                ),
                profile_id="lab-a",
            )
            self.assertEqual("connected", result.status)
            self.assertEqual(("A1", "A2"), result.path)
            self.assertEqual("lab-a", result.profile_id)
            self.assertTrue((scope / "path_investigation_report.json").is_file())
            self.assertTrue((scope / "path_investigation_report.md").is_file())
            markdown = (scope / "path_investigation_report.md").read_text("utf-8")
            self.assertIn("# Atlas Path Investigation", markdown)
            self.assertIn("Investigation Story", markdown)
            self.assertNotIn(PASSWORD, markdown)

    def test_shut_interface_re_run_stops_at_the_failed_hop(self) -> None:
        """The CML acceptance scenario: all pass, then shut, then re-run."""

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, scope = self.discover_lab(workdir)
            when = (FIXED + timedelta(minutes=5)).isoformat(timespec="seconds")
            before = investigate_path_for_scope(
                "A1", "A2",
                output_dir=scope, history_root=scope / "history",
                generated_at=when, profile_id="lab-a",
            )
            self.assertEqual("connected", before.status)
            # An operator shuts A2's uplink; a re-discovery captures it.
            self.discover_lab(
                workdir, a2_interfaces=A2_DOWN_BRIEF,
                start=FIXED + timedelta(hours=2), service=service,
            )
            after = investigate_path_for_scope(
                "A1", "A2",
                output_dir=scope, history_root=scope / "history",
                generated_at=(FIXED + timedelta(hours=2, minutes=5)).isoformat(
                    timespec="seconds"
                ),
                profile_id="lab-a",
            )
            self.assertEqual("failed", after.status)
            self.assertEqual("administrative-shutdown", after.failure_type)
            self.assertEqual("A2", after.hops[-1].device)
            self.assertIn("administratively shut down", after.failure_summary)

    def test_history_records_every_investigation_for_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, scope = self.discover_lab(workdir)
            first_at = (FIXED + timedelta(minutes=5)).isoformat(timespec="seconds")
            first = investigate_path_for_scope(
                "A1", "A2",
                output_dir=scope, history_root=scope / "history",
                generated_at=first_at, profile_id="lab-a",
            )
            investigate_path_for_scope(
                "A2", "A1",
                output_dir=scope, history_root=scope / "history",
                generated_at=(FIXED + timedelta(minutes=6)).isoformat(
                    timespec="seconds"
                ),
                profile_id="lab-a",
            )
            history = load_investigation_history(scope)
            self.assertEqual(2, len(history))
            # Newest first; each entry is the COMPLETE result — evidence,
            # hops, confidence — so any investigation can be replayed.
            self.assertEqual("A2", history[0]["source"])
            self.assertEqual("A1", history[1]["source"])
            replayed = history[1]
            self.assertEqual(first.to_dict(), replayed)
            self.assertEqual("lab-a", replayed["profile_id"])
            self.assertIn("hops", replayed)
            self.assertIn("confidence_percent", replayed)
            self.assertNotIn(
                PASSWORD,
                (scope / "path_investigations.json").read_text("utf-8"),
            )

    def test_rendered_markdown_tells_the_whole_story(self) -> None:
        snapshot = set_interface_status(
            chain(), "SW1", "Gi0/2", "administratively down"
        )
        result = investigate_path("R1", "SW2", snapshot=snapshot, generated_at=NOW)
        markdown = render_investigation_markdown(result)
        self.assertIn("## Where Communication Stops", markdown)
        self.assertIn("## Investigation Story", markdown)
        self.assertIn("## Hop Detail", markdown)
        self.assertIn("[FAILED]", markdown)
        self.assertIn("## Recommended Next Actions", markdown)


class PathsGuiTests(unittest.TestCase):
    def build_world(self, workdir: Path, *, a2_interfaces: str | None = None):
        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1")
        run_discover(
            workdir, service, network_a(a2_interfaces=a2_interfaces), "Lab A", FIXED
        )
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return service, app.test_client()

    def test_paths_page_and_run_render_the_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            page = client.get("/paths?scope=lab-a").data
            self.assertIn(b"Investigate device-to-device connectivity", page)
            # Devices come from the async entity API, not a preloaded select.
            self.assertIn(b"data-picker", page)
            names = {
                item["value"] for item in client.get(
                    "/api/entities?kind=device&scope=lab-a"
                ).get_json()["results"]
            }
            self.assertIn("A1", names)
            self.assertIn("A2", names)
            response = client.post(
                "/paths/run",
                data={"source": "A1", "destination": "A2"},
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            self.assertIn(b"Investigation \xe2\x80\x94 A1 \xe2\x86\x92 A2", response.data)
            self.assertIn(b"Connected", response.data)
            self.assertIn(b"Investigation Story", response.data)
            self.assertIn(b"hop-badge-pass", response.data)
            self.assertIn(b"Evidence:", response.data)
            scope = scope_dir(workdir, "lab-a")
            self.assertTrue((scope / "path_investigation_report.json").is_file())
            self.assertTrue((scope / "path_investigations.json").is_file())
            self.assertNotIn(PASSWORD.encode(), response.data)

    def test_failed_path_shows_where_communication_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = self.build_world(workdir)
            client.get("/paths?scope=lab-a")
            client.post(
                "/paths/run",
                data={"source": "A1", "destination": "A2"},
                follow_redirects=True,
            )
            # The operator shuts A2's uplink; a re-discovery captures it.
            run_discover(
                workdir, service, network_a(a2_interfaces=A2_DOWN_BRIEF),
                "Lab A", FIXED + timedelta(hours=2),
            )
            response = client.post(
                "/paths/run",
                data={"source": "A1", "destination": "A2"},
                follow_redirects=True,
            )
            self.assertIn(b"Where communication stops", response.data)
            self.assertIn(b"administratively shut down", response.data)
            self.assertIn(b"hop-badge-failed", response.data)
            self.assertIn(b"Saved investigations", response.data)
            self.assertNotIn(PASSWORD.encode(), response.data)

    def test_unknown_destination_is_explained_in_the_gui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            client.get("/paths?scope=lab-a")
            response = client.post(
                "/paths/run",
                data={"source": "A1", "destination": "GHOST"},
                follow_redirects=True,
            )
            self.assertIn(b"Unknown", response.data)
            self.assertIn(b"GHOST", response.data)
            self.assertIn(b"fresh discovery", response.data)

    def test_all_networks_scope_investigates_the_enterprise(self) -> None:
        """PR-037A: All Networks is the enterprise scope, not a refusal."""

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            page = client.get("/paths?scope=all").data
            self.assertNotIn(b"Select a specific network", page)
            self.assertIn(b"Enterprise scope", page)
            response = client.post(
                "/paths/run",
                data={"source": "A1", "destination": "A2"},
                follow_redirects=True,
            )
            self.assertIn(b"Connected", response.data)
            self.assertNotIn(PASSWORD.encode(), response.data)


if __name__ == "__main__":
    unittest.main()
