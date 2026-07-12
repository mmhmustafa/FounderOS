"""Acceptance tests for PR-040 — the MISSION operational workspace.

MISSION is orchestration, never business logic: the All Networks
landing page presents workflows ("What would you like to do?"), an
Enterprise Health card, deterministic evidence-cited recommendations,
and resume-able recent activity — every card reading artifacts the
existing engines already produced. Scoped dashboards, search, Compass,
prediction, and path intelligence remain authoritative and unchanged.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.web.mission import build_recommendations, describe_age

from tests.test_atlas_transport import PASSWORD
from tests.test_federation import hyderabad_network, secunderabad_network
from tests.test_profile_isolation import (
    A2_DOWN_BRIEF,
    FIXED,
    add_profile,
    make_service,
    network_a,
    run_discover,
)


NOW = "2026-07-11T08:00:00+00:00"


class RecommendationTests(unittest.TestCase):
    """The deterministic recommendation builder (pure unit tests)."""

    def test_no_data_recommends_first_discovery(self) -> None:
        recommendations = build_recommendations(
            contributions=[], draft_plan_count=0, discovery_failures=[],
            predictions=[], active_issues=[], has_any_data=False, now=NOW,
        )
        self.assertEqual(1, len(recommendations))
        self.assertIn("No discovery has run yet", recommendations[0]["text"])
        self.assertEqual("/discovery", recommendations[0]["href"])

    def test_stale_contribution_recommends_rediscovery(self) -> None:
        recommendations = build_recommendations(
            contributions=[
                {"profile_id": "hyd", "profile_name": "Hyderabad",
                 "fresh": False, "observed_at": "2026-07-08T08:00:00+00:00"},
                {"profile_id": "sec", "profile_name": "Secunderabad",
                 "fresh": True, "observed_at": NOW},
            ],
            draft_plan_count=0, discovery_failures=[], predictions=[],
            active_issues=[], has_any_data=True, now=NOW,
        )
        self.assertEqual(1, len(recommendations))
        self.assertIn("Hyderabad", recommendations[0]["text"])
        self.assertIn("3 day(s) old", recommendations[0]["text"])
        self.assertIn("2026-07-08", recommendations[0]["evidence"])

    def test_failures_drafts_issues_and_low_confidence_each_cite_evidence(self) -> None:
        recommendations = build_recommendations(
            contributions=[],
            draft_plan_count=2,
            discovery_failures=[
                {"network": "Hyderabad", "scope_id": "hyd",
                 "run_id": "run-9", "count": 1},
            ],
            predictions=[
                {"subject": "shutdown-interface GW Gi0/1",
                 "confidence_band": "medium", "confidence_percent": 55,
                 "href": "/predict?scope=all"},
            ],
            active_issues=[
                {"network": "Hyderabad", "scope_id": "hyd", "count": 1},
            ],
            has_any_data=True,
            now=NOW,
        )
        texts = [item["text"] for item in recommendations]
        self.assertEqual(4, len(recommendations))
        # Deterministic order: failures, drafts, issues, low confidence.
        self.assertIn("could not reach 1 host(s)", texts[0])
        self.assertIn("2 maintenance plan(s)", texts[1])
        self.assertIn("active", texts[2])
        self.assertIn("medium confidence", texts[3])
        for item in recommendations:
            self.assertTrue(item["evidence"], item["text"])
            self.assertTrue(item["href"], item["text"])

    def test_fresh_healthy_world_recommends_nothing(self) -> None:
        recommendations = build_recommendations(
            contributions=[
                {"profile_id": "hyd", "profile_name": "Hyderabad",
                 "fresh": True, "observed_at": NOW},
            ],
            draft_plan_count=0, discovery_failures=[], predictions=[
                {"subject": "x", "confidence_band": "very-high",
                 "confidence_percent": 92, "href": "/predict?scope=all"},
            ],
            active_issues=[], has_any_data=True, now=NOW,
        )
        self.assertEqual([], recommendations)

    def test_describe_age_is_deterministic(self) -> None:
        self.assertEqual(
            "3 day(s) old",
            describe_age("2026-07-08T08:00:00+00:00", NOW),
        )
        self.assertEqual(
            "5 hour(s) old",
            describe_age("2026-07-11T03:00:00+00:00", NOW),
        )
        self.assertIsNone(describe_age(None, NOW))


class MissionGuiTests(unittest.TestCase):
    def build_world(self, workdir: Path, *, discover: bool = True):
        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Hyderabad", "10.0.0.1")
        add_profile(service, "Secunderabad", "10.0.1.1")
        if discover:
            run_discover(workdir, service, hyderabad_network(), "Hyderabad", FIXED)
            run_discover(
                workdir, service, secunderabad_network(), "Secunderabad",
                FIXED + timedelta(minutes=30),
            )
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return service, app.test_client()

    def test_mission_is_the_enterprise_landing_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build_world(Path(tmp))
            page = client.get("/?scope=all").data
            self.assertIn(b"Mission", page)
            # PR-040.1: the page opens with the question, not metrics.
            self.assertIn(b"What would you like to do?", page)
            for action in (
                b"Investigate an Issue", b"Plan a Change",
                b"Run Discovery", b"Review Changes",
                b"Search Enterprise",
            ):
                self.assertIn(action, page)
            self.assertNotIn(b"Dashboard", page)
            self.assertNotIn(PASSWORD.encode(), page)

    def test_actions_come_before_metrics(self) -> None:
        """PR-040.1: the first thing an engineer sees is never metrics."""

        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build_world(Path(tmp))
            page = client.get("/?scope=all").data.decode("utf-8")
            self.assertLess(
                page.index("What would you like to do?"),
                page.index("Enterprise Health"),
            )
            self.assertLess(
                page.index("Continue Working"),
                page.index("Enterprise Health"),
            )
            # The status strip (one sentence, not metrics) may lead.
            self.assertLess(
                page.index("status-banner"),
                page.index("What would you like to do?"),
            )

    def test_enterprise_health_freshness_and_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build_world(Path(tmp))
            page = client.get("/?scope=all").data
            self.assertIn(b"Enterprise Health", page)
            self.assertIn(b"<strong>Networks</strong><span>2</span>", page)
            self.assertIn(b"Canonical devices", page)
            self.assertIn(b"Discovery freshness:", page)
            self.assertIn(b"Recent Activity", page)
            self.assertIn(b"Discovery completed", page)
            self.assertIn(b"Hyderabad", page)
            self.assertIn(b"Secunderabad", page)

    def test_workflow_launch_targets_all_respond(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build_world(Path(tmp))
            for href in ("/paths?scope=all", "/compass", "/discovery",
                         "/changes?scope=all", "/topology?scope=all",
                         "/predict?scope=all", "/history?scope=all"):
                self.assertEqual(200, client.get(href).status_code, href)

    def test_recommendations_from_stale_evidence_and_draft_plans(self) -> None:
        from founderos_atlas.compass import PlanRepository, create_plan

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            create_plan(
                PlanRepository(workdir), title="Core window",
                maintenance_window="Sat", engineer="netops", created_at=NOW,
            )
            page = client.get("/?scope=all").data.decode("utf-8")
            self.assertIn("Today's Recommendations", page)
            # The world was discovered at FIXED (2026-07-10) and the app
            # clock is real time: the evidence is deterministically stale.
            self.assertIn("run discovery to refresh", page)
            self.assertIn("Evidence:", page)
            self.assertIn("have not been analysed yet", page)
            self.assertIn("Open Compass", page)

    def test_discovery_failures_produce_a_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1")
            # A2 present in CDP but unreachable: a recorded failure.
            from tests.test_multihop_discovery import ScriptedNetwork
            from tests.test_unified_pipeline import full_outputs

            network = ScriptedNetwork(
                {"10.0.0.1": full_outputs("A1", "10.0.0.1", (("A2", "10.0.0.2"),))},
                unreachable=frozenset({"10.0.0.2"}),
            )
            run_discover(workdir, service, network, "Lab A", FIXED)
            from founderos_atlas.web import create_app

            app = create_app(
                profile_service=service,
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                workspace_root=workdir / "workspace",
            )
            app.config.update(TESTING=True)
            page = app.test_client().get("/?scope=all").data.decode("utf-8")
            self.assertIn("could not reach 1 host(s)", page)
            self.assertIn("Open History", page)

    def test_compass_plans_appear_with_risk_and_open_action(self) -> None:
        from founderos_atlas.compass import (
            PlanRepository, PlannedChange, add_change, create_plan,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            repository = PlanRepository(workdir)
            created = create_plan(
                repository, title="Core Upgrade", maintenance_window="Tonight",
                engineer="netops", created_at=NOW,
            )
            add_change(
                repository, created,
                PlannedChange(
                    change_id="c1", device="GW", change_type="ios-upgrade",
                ),
                updated_at=NOW,
            )
            client.post("/compass/core-upgrade/analyse", follow_redirects=True)
            page = client.get("/?scope=all").data.decode("utf-8")
            # PR-040.1: plans surface as resumable work, not a stats card.
            self.assertIn("Continue Working", page)
            self.assertIn("Core Upgrade", page)
            self.assertIn("Tonight", page)
            self.assertIn("Resume Plan", page)
            self.assertIn('href="/compass/core-upgrade"', page)
            self.assertIn("Maintenance plan analysed", page)  # the timeline

    def test_investigations_appear_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            client.get("/paths?scope=all")
            client.post(
                "/paths/run",
                data={"source": "A2", "destination": "B1"},
                follow_redirects=True,
            )
            page = client.get("/?scope=all").data.decode("utf-8")
            self.assertIn("Continue Working", page)
            self.assertIn("A2 → B1", page)
            self.assertIn("connected", page)
            self.assertIn("Resume Investigation", page)
            self.assertIn("Path investigation", page)  # the timeline entry
            resume = client.get("/paths?scope=all").data
            self.assertIn(b"A2 \xe2\x86\x92 B1", resume)

    def test_predictions_and_changes_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = self.build_world(workdir)
            client.get("/predict?scope=all")
            client.post(
                "/predict/run",
                data={"device": "GW", "interface": "Gi0/1"},
                follow_redirects=True,
            )
            # An operational change: A2's uplink goes admin-down.
            run_discover(
                workdir, service, network_a(a2_interfaces=A2_DOWN_BRIEF),
                "Hyderabad", FIXED + timedelta(hours=2),
            )
            page = client.get("/?scope=all").data.decode("utf-8")
            # PR-040.1: the prediction is a resumable item plus a
            # timeline entry — no dominating engine card.
            self.assertIn("Review Prediction", page)
            self.assertIn("GW GigabitEthernet0/1", page)
            self.assertIn("Prediction created", page)
            self.assertIn("Operational changes", page)  # timeline entry
            self.assertIn("active issue(s)", page)
            self.assertIn("Review Changes", page)  # the recommendation

    def test_search_is_embedded_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build_world(Path(tmp))
            page = client.get("/?scope=all").data.decode("utf-8")
            self.assertEqual(1, page.count('id="atlas-search"'))
            self.assertGreaterEqual(page.count("js-open-search"), 1)
            self.assertIn("mission-recent-searches", page)
            self.assertIn("mission-recent-devices", page)
            script = client.get("/static/atlas.js").data.decode("utf-8")
            self.assertIn("js-open-search", script)
            self.assertIn("atlas-recent-devices", script)
            self.assertIn("stored in this browser only", page.casefold())

    def test_context_scope_selection_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build_world(Path(tmp))
            client.get("/?scope=hyderabad")
            page = client.get("/topology").data
            self.assertIn(b"Topology \xe2\x80\x94 Hyderabad", page)
            client.get("/?scope=all")
            page = client.get("/").data
            self.assertIn(b"What would you like to do?", page)

    def test_scoped_mission_keeps_metrics_and_gains_workflows(self) -> None:
        """PR-040.1: Dashboard terminology disappears — the scoped page
        is Mission too, actions first, its metric panels preserved."""

        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build_world(Path(tmp))
            page = client.get("/?scope=hyderabad").data
            self.assertIn(b"Mission \xe2\x80\x94 Hyderabad", page)
            self.assertNotIn(b"Dashboard", page)
            self.assertIn(b"What would you like to do?", page)
            self.assertIn(b"Recent Discoveries", page)
            text = page.decode("utf-8")
            self.assertLess(
                text.index("What would you like to do?"),
                text.index("Recent Discoveries"),
            )
            # Enterprise-only cards stay off the scoped page.
            self.assertNotIn(b"Continue Working", page)

    def test_empty_world_teaches_with_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build_world(Path(tmp), discover=False)
            page = client.get("/?scope=all").data.decode("utf-8")
            self.assertIn("What would you like to do?", page)
            self.assertIn("No discovery has run yet", page)
            self.assertIn("Run Discovery", page)
            # The Continue Working empty state teaches by example.
            self.assertIn("Start your first investigation", page)
            for example in ("Routing issue", "VLAN problem",
                            "Device unreachable", "Change tonight"):
                self.assertIn(example, page)

    def test_expert_tools_stay_in_the_sidebar(self) -> None:
        """Mission is the front door, never a replacement for expert
        navigation."""

        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build_world(Path(tmp))
            page = client.get("/?scope=all").data.decode("utf-8")
            for href in ('href="/predict"', 'href="/paths"',
                         'href="/topology"', 'href="/history"',
                         'href="/compass"'):
                self.assertIn(href, page)


if __name__ == "__main__":
    unittest.main()
