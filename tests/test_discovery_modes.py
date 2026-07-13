"""Acceptance tests for PR-043.2 — Enterprise Discovery Modes.

Four deterministic entry methods (single seed / management network /
multiple seeds / CSV import) all resolve to the SAME candidate list the
multihop engine already consumes, so discovery keeps producing canonical
enterprise models and every downstream engine is untouched. CIDR
expansion is deterministic and safety-gated; candidate outcomes are
classified honestly; resume skips completed addresses; nothing here
holds a secret.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.discovery import (
    MODE_CSV,
    MODE_MULTI_SEED,
    MODE_SEED,
    MODE_SUBNET,
    POLICY_DEEP,
    POLICY_FAST,
    DiscoveryPlanError,
    assess_scan_safety,
    classify_candidate_outcomes,
    estimate_candidate_count,
    expand_management_network,
    parse_device_csv,
    resolve_plan,
    summarize_candidates,
)
from founderos_atlas.live import run_discovery_plan

from tests.test_atlas_transport import PASSWORD
from tests.test_multihop_discovery import (
    ScriptedNetwork,
    device_outputs,
)
from tests.test_platforms import frr_outputs
from tests.test_profile_isolation import FIXED
from tests.test_unified_pipeline import full_outputs


NOW = "2026-07-13T09:00:00+00:00"


# -- CIDR expansion & safety -----------------------------------------------------


class CidrExpansionTests(unittest.TestCase):
    def test_slash_29_excludes_network_and_broadcast(self) -> None:
        candidates = expand_management_network("10.20.20.0/29")
        addresses = [c.address for c in candidates]
        self.assertNotIn("10.20.20.0", addresses)   # network
        self.assertNotIn("10.20.20.7", addresses)   # broadcast
        self.assertEqual(
            ["10.20.20.1", "10.20.20.2", "10.20.20.3",
             "10.20.20.4", "10.20.20.5", "10.20.20.6"],
            addresses,
        )
        self.assertTrue(all(c.source == "management-network" for c in candidates))
        self.assertTrue(all(c.confidence == "low" for c in candidates))

    def test_user_exclusions_remove_addresses_and_subranges(self) -> None:
        candidates = expand_management_network(
            "10.0.0.0/28",
            exclusions=("10.0.0.1", "10.0.0.8/30", "garbage"),
        )
        addresses = {c.address for c in candidates}
        self.assertNotIn("10.0.0.1", addresses)          # single exclusion
        self.assertNotIn("10.0.0.9", addresses)          # inside /30
        self.assertNotIn("10.0.0.10", addresses)
        self.assertIn("10.0.0.2", addresses)

    def test_estimate_and_deterministic_order(self) -> None:
        self.assertEqual(254, estimate_candidate_count("192.168.1.0/24"))
        self.assertEqual(6, estimate_candidate_count("10.0.0.0/29"))
        first = [c.address for c in expand_management_network("10.0.0.0/28")]
        second = [c.address for c in expand_management_network("10.0.0.0/28")]
        self.assertEqual(first, second)

    def test_safety_thresholds(self) -> None:
        self.assertEqual("ok", assess_scan_safety("10.0.0.0/24").level)
        self.assertEqual("warn", assess_scan_safety("10.0.0.0/22").level)
        self.assertEqual("confirm", assess_scan_safety("10.0.0.0/18").level)
        reject = assess_scan_safety("10.0.0.0/8")
        self.assertEqual("reject", reject.level)
        self.assertFalse(reject.allowed)
        self.assertIn("exceeds the safe limit", reject.message)


# -- CSV import ------------------------------------------------------------------


class CsvImportTests(unittest.TestCase):
    def test_columns_are_case_and_order_insensitive(self) -> None:
        csv_text = (
            "Site,Management IP,Hostname,Platform\n"
            "hyderabad,10.0.0.1,R1,cisco-ios\n"
            "delhi,10.20.0.1,delhi-r1,frr\n"
        )
        candidates, warnings = parse_device_csv(csv_text)
        self.assertEqual((), warnings)
        self.assertEqual(2, len(candidates))
        self.assertEqual("R1", candidates[0].hostname)
        self.assertEqual("10.0.0.1", candidates[0].address)
        self.assertEqual("hyderabad", candidates[0].site_hint)
        self.assertEqual("frr", candidates[1].platform_hint)
        self.assertTrue(all(c.confidence == "high" for c in candidates))

    def test_invalid_and_duplicate_rows_are_reported_not_guessed(self) -> None:
        csv_text = (
            "hostname,ip\n"
            "R1,10.0.0.1\n"
            "BadRow,not-an-ip\n"
            "Dup,10.0.0.1\n"
            "NoIp,\n"
        )
        candidates, warnings = parse_device_csv(csv_text)
        self.assertEqual(1, len(candidates))
        self.assertTrue(any("BadRow" in w and "no valid" in w for w in warnings))
        self.assertTrue(any("duplicate" in w for w in warnings))
        self.assertTrue(any("NoIp" in w for w in warnings))

    def test_empty_csv_is_honest(self) -> None:
        _candidates, warnings = parse_device_csv("")
        self.assertIn("empty", warnings[0])


# -- plan resolution -------------------------------------------------------------


class PlanResolutionTests(unittest.TestCase):
    def test_seed_mode(self) -> None:
        plan = resolve_plan(MODE_SEED, seed="10.0.0.1")
        self.assertEqual(("10.0.0.1",), plan.seed_addresses)
        self.assertEqual("high", plan.candidates[0].confidence)

    def test_multiple_seeds_dedupe_and_validate(self) -> None:
        plan = resolve_plan(
            MODE_MULTI_SEED, seed="10.0.0.1",
            seeds=("10.0.0.1", "10.20.0.1", "bogus"),
        )
        self.assertEqual(("10.0.0.1", "10.20.0.1"), plan.seed_addresses)
        self.assertTrue(any("bogus" in w for w in plan.warnings))

    def test_subnet_mode_sizes_max_devices_to_candidates(self) -> None:
        plan = resolve_plan(MODE_SUBNET, cidr="10.20.20.0/29", max_devices=4)
        self.assertEqual(6, len(plan.candidates))
        self.assertGreaterEqual(plan.max_devices, 6)
        self.assertEqual("10.20.20.0/29", plan.attributes["cidr"])

    def test_subnet_large_scan_requires_override(self) -> None:
        with self.assertRaises(DiscoveryPlanError) as ctx:
            resolve_plan(MODE_SUBNET, cidr="10.0.0.0/18")
        self.assertIn("large scan", str(ctx.exception))
        plan = resolve_plan(
            MODE_SUBNET, cidr="10.0.0.0/18", allow_large_scan=True
        )
        self.assertGreater(len(plan.candidates), 16000)

    def test_subnet_reject_needs_override_too(self) -> None:
        with self.assertRaises(DiscoveryPlanError):
            resolve_plan(MODE_SUBNET, cidr="10.0.0.0/8")

    def test_csv_mode(self) -> None:
        plan = resolve_plan(
            MODE_CSV, csv_text="hostname,ip\nR1,10.0.0.1\ndelhi,10.20.0.1\n"
        )
        self.assertEqual(("10.0.0.1", "10.20.0.1"), plan.seed_addresses)

    def test_policies_shape_depth_and_configuration(self) -> None:
        fast = resolve_plan(MODE_SEED, seed="10.0.0.1", policy=POLICY_FAST,
                            max_depth=3)
        self.assertEqual(0, fast.effective_depth)  # candidates only
        self.assertFalse(fast.collect_configuration)
        deep = resolve_plan(MODE_SEED, seed="10.0.0.1", policy=POLICY_DEEP,
                            max_depth=2)
        self.assertEqual(2, deep.effective_depth)
        self.assertTrue(deep.collect_configuration)

    def test_bad_mode_and_policy_are_rejected(self) -> None:
        with self.assertRaises(DiscoveryPlanError):
            resolve_plan("telepathy", seed="10.0.0.1")
        with self.assertRaises(DiscoveryPlanError):
            resolve_plan(MODE_SEED, seed="10.0.0.1", policy="psychic")

    def test_plan_serializes_without_secrets(self) -> None:
        plan = resolve_plan(MODE_SUBNET, cidr="10.20.20.0/29")
        data = plan.to_dict()
        self.assertEqual("management-network", data["mode"])
        self.assertEqual(6, data["candidate_count"])
        self.assertNotIn(PASSWORD, json.dumps(data))


# -- candidate outcome classification --------------------------------------------


class OutcomeClassificationTests(unittest.TestCase):
    def plan(self):
        return resolve_plan(
            MODE_MULTI_SEED, seed="10.0.0.1",
            seeds=("10.0.0.2", "10.0.0.3", "10.0.0.4"),
        )

    def test_visits_map_to_candidate_states(self) -> None:
        visits = (
            ("10.0.0.1", "connected", "seed"),
            ("10.0.0.2", "failed", "connection to 10.0.0.2 timed out"),
            ("10.0.0.3", "failed", "Unsupported platform detected. ..."),
            ("10.0.0.4", "failed", "authentication failed for user atlas"),
        )
        outcomes = {
            c.address: c.status
            for c in classify_candidate_outcomes(self.plan(), visits)
        }
        self.assertEqual("discovered", outcomes["10.0.0.1"])
        self.assertEqual("unreachable", outcomes["10.0.0.2"])
        self.assertEqual("unsupported-platform", outcomes["10.0.0.3"])
        self.assertEqual("authentication-failed", outcomes["10.0.0.4"])

    def test_resume_marks_completed_without_reattempt(self) -> None:
        visits = (("10.0.0.1", "connected", "seed"),)
        outcomes = classify_candidate_outcomes(
            self.plan(), visits,
            completed_addresses=frozenset({"10.0.0.2"}),
        )
        by_address = {c.address: c for c in outcomes}
        self.assertEqual("discovered", by_address["10.0.0.2"].status)
        self.assertIn("cached", by_address["10.0.0.2"].reason)
        self.assertEqual("queued", by_address["10.0.0.3"].status)

    def test_summary_counts_are_honest(self) -> None:
        visits = (
            ("10.0.0.1", "connected", "seed"),
            ("10.0.0.2", "failed", "timed out"),
            ("10.0.0.3", "failed", "Unsupported platform detected"),
            ("10.0.0.4", "failed", "authentication failed"),
        )
        summary = summarize_candidates(
            classify_candidate_outcomes(self.plan(), visits)
        )
        self.assertEqual(4, summary["candidate_addresses"])
        self.assertEqual(1, summary["discovered"])
        self.assertEqual(1, summary["unsupported_platforms"])
        self.assertEqual(1, summary["authentication_failed"])
        self.assertEqual(1, summary["unreachable"])
        # SSH-reachable = anything that answered (discovered + auth-fail +
        # unsupported); an unreachable address did not answer.
        self.assertEqual(3, summary["ssh_reachable"])


# -- live plan execution ---------------------------------------------------------


def mixed_estate() -> ScriptedNetwork:
    """A management network with two IOS devices and one FRR device,
    plus empty addresses that will not answer."""

    return ScriptedNetwork(
        {
            "10.20.20.1": full_outputs("R1", "10.20.20.1"),
            "10.20.20.2": full_outputs("R2", "10.20.20.2"),
            "10.20.20.3": frr_outputs("delhi-r1", "10.20.20.3"),
        }
    )


class LivePlanExecutionTests(unittest.TestCase):
    def test_management_network_discovers_every_answering_device(self) -> None:
        plan = resolve_plan(MODE_SUBNET, cidr="10.20.20.0/29")
        report, _graph, snapshot, candidates, summary = run_discovery_plan(
            plan, mixed_estate().transport_factory
        )
        by_address = {c.address: c for c in candidates}
        self.assertEqual("discovered", by_address["10.20.20.1"].status)
        self.assertEqual("discovered", by_address["10.20.20.3"].status)
        self.assertEqual("unreachable", by_address["10.20.20.5"].status)
        self.assertEqual(3, summary["devices_discovered"])
        self.assertEqual(3, summary["discovered"])
        self.assertEqual(6, summary["candidate_addresses"])
        # Two platform families, one enterprise graph.
        self.assertEqual({"frr": 1, "ios": 2}, dict(summary["platforms"]))

    def test_multiple_seeds_disconnected_sites(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": full_outputs("hydR1", "10.0.0.1"),
                "10.20.0.1": frr_outputs("delhi-r1", "10.20.0.1"),
            }
        )
        plan = resolve_plan(
            MODE_MULTI_SEED, seed="10.0.0.1", seeds=("10.20.0.1",)
        )
        _report, _graph, _snapshot, candidates, summary = run_discovery_plan(
            plan, network.transport_factory
        )
        self.assertEqual(2, summary["devices_discovered"])
        self.assertTrue(all(c.status == "discovered" for c in candidates))

    def test_csv_import_end_to_end(self) -> None:
        network = mixed_estate()
        plan = resolve_plan(
            MODE_CSV,
            csv_text=(
                "hostname,management_ip,platform\n"
                "R1,10.20.20.1,cisco-ios\n"
                "delhi-r1,10.20.20.3,frr\n"
            ),
        )
        _report, _graph, snapshot, _candidates, summary = run_discovery_plan(
            plan, network.transport_factory
        )
        self.assertEqual(2, summary["devices_discovered"])
        hostnames = {d["hostname"] for d in snapshot.to_dict()["devices"]}
        self.assertEqual({"R1", "delhi-r1"}, hostnames)

    def test_resume_only_attempts_unfinished_candidates(self) -> None:
        recorded: list[str] = []

        class Recorder:
            def __init__(self, inner):
                self._inner = inner

            def transport_factory(self, host):
                recorded.append(host)
                return self._inner.transport_factory(host)

        network = Recorder(mixed_estate())
        plan = resolve_plan(MODE_SUBNET, cidr="10.20.20.0/29")
        _r, _g, _s, candidates, _summary = run_discovery_plan(
            plan, network.transport_factory,
            completed_addresses=frozenset({"10.20.20.1"}),
        )
        # The cached device was never contacted again.
        self.assertNotIn("10.20.20.1", recorded)
        by_address = {c.address: c for c in candidates}
        self.assertEqual("discovered", by_address["10.20.20.1"].status)
        self.assertIn("cached", by_address["10.20.20.1"].reason)
        self.assertEqual("discovered", by_address["10.20.20.3"].status)

    def test_deterministic_execution(self) -> None:
        plan = resolve_plan(MODE_SUBNET, cidr="10.20.20.0/29")
        first = run_discovery_plan(plan, mixed_estate().transport_factory)[4]
        second = run_discovery_plan(plan, mixed_estate().transport_factory)[4]
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )


class AdvisorDiscoveryTests(unittest.TestCase):
    def test_launch_requests_route_to_the_wizard(self) -> None:
        from founderos_atlas.advisor import classify, discovery_launch

        self.assertEqual("discovery", classify("Run discovery on 172.20.20.0/24"))
        self.assertEqual(
            {"kind": "subnet", "cidr": "172.20.20.0/24"},
            discovery_launch("Run discovery on 172.20.20.0/24"),
        )
        self.assertEqual(
            {"kind": "resume"}, discovery_launch("Resume discovery")
        )
        self.assertEqual(
            {"kind": "launch"}, discovery_launch("Discover Delhi Lab")
        )
        self.assertIsNone(discovery_launch("Summarize discovery"))

    def test_advisor_answer_guides_to_the_wizard(self) -> None:
        from founderos_atlas.advisor import ask
        from founderos_atlas.federation import (
            build_enterprise_snapshot, get_enterprise_graph,
        )
        from founderos_atlas.search import build_search_index
        from tests.test_profile_isolation import (
            add_profile, make_service, run_discover,
        )
        from tests.test_federation import hyderabad_network

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Hyderabad", "10.0.0.1")
            run_discover(workdir, service, hyderabad_network(), "Hyderabad",
                         FIXED)
            profiles = service.list_profiles()
            graph = get_enterprise_graph(workdir, profiles, now=NOW)
            snapshot = build_enterprise_snapshot(graph).to_dict()
            response = ask(
                "Run discovery on 172.20.20.0/24",
                base_output_dir=workdir, profiles=profiles, graph=graph,
                snapshot=snapshot,
                search_index=build_search_index(workdir, profiles),
                generated_at=NOW,
            )
            self.assertEqual("discovery", response.intent)
            self.assertIn("172.20.20.0/24", response.summary)
            self.assertEqual("/discovery/wizard", response.next_action_href)


class WizardGuiTests(unittest.TestCase):
    def client(self, workdir: Path):
        from founderos_atlas.web import create_app
        from tests.test_profile_isolation import make_service

        service = make_service(workdir)
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return service, app.test_client()

    def test_wizard_page_offers_all_four_methods(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _service, client = self.client(Path(tmp))
            page = client.get("/discovery/wizard").data
            self.assertIn(b"Discovery Wizard", page)
            for method in (b"Seed Device", b"Management Network",
                           b"Multiple Seeds", b"Import Device List"):
                self.assertIn(method, page)
            for policy in (b"Fast", b"Balanced", b"Deep"):
                self.assertIn(policy, page)
            # Discovery page links to the wizard.
            self.assertIn(b'href="/discovery/wizard"',
                          client.get("/discovery").data)

    def test_subnet_preview_shows_candidates_and_safety(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _service, client = self.client(Path(tmp))
            page = client.post(
                "/discovery/wizard/preview",
                data={"mode": "management-network", "cidr": "10.20.20.0/29",
                      "policy": "balanced"},
                follow_redirects=True,
            ).data
            self.assertIn(b"Step 5", page)
            self.assertIn(b"10.20.20.1", page)
            self.assertIn(b"6", page)  # candidate count
            self.assertIn(b"candidate address", page)

    def test_large_scan_preview_is_gated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _service, client = self.client(Path(tmp))
            page = client.post(
                "/discovery/wizard/preview",
                data={"mode": "management-network", "cidr": "10.0.0.0/8",
                      "policy": "balanced"},
            ).data
            self.assertIn(b"exceeds the safe limit", page)

    def test_wizard_creates_profile_and_starts_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = self.client(workdir)
            # Point the app's job manager at a scripted network.
            from founderos_atlas.web.jobs import DiscoveryJobManager
            from founderos_atlas.transport import SSHDeviceTransport

            network = ScriptedNetwork(
                {"10.0.0.1": full_outputs("R1", "10.0.0.1")}
            )
            client.application.config["ATLAS_TRANSPORT_FACTORY"] = (
                lambda credentials: network.transport_factory(credentials.host)
            )
            response = client.post(
                "/discovery/wizard/start",
                data={
                    "mode": "seed", "seed": "10.0.0.1", "policy": "balanced",
                    "name": "Hyderabad", "username": "atlas",
                    "password": PASSWORD,
                },
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            self.assertIn(b"Discovery started", response.data)
            # A reusable profile now exists with the seed as its entry point.
            profile = service.get_profile("Hyderabad")
            self.assertEqual("10.0.0.1", profile.management_ip)
            self.assertNotIn(PASSWORD.encode(), response.data)
            # The wizard launches an async job (daemon thread). Await its
            # completion before the temp dir is torn down, otherwise
            # cleanup races the still-writing job (Windows: .atlas busy).
            import time as _time

            for _ in range(200):
                jobs = client.get("/api/discovery/jobs").get_json()["jobs"]
                if jobs and jobs[0]["status"] not in ("queued", "running"):
                    break
                _time.sleep(0.05)

    def test_start_requires_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _service, client = self.client(Path(tmp))
            response = client.post(
                "/discovery/wizard/start",
                data={"mode": "seed", "seed": "10.0.0.1", "name": "X"},
                follow_redirects=True,
            )
            self.assertIn(b"username, and password are required", response.data)

    def test_mission_launches_the_wizard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _service, client = self.client(Path(tmp))
            self.assertIn(b'href="/discovery"',
                          client.get("/?scope=all").data)


if __name__ == "__main__":
    unittest.main()
