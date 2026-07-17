"""Acceptance tests for PR-042 — Atlas Advisor MVP.

Advisor is an evidence orchestration layer, never an answer generator:
a deterministic keyword router classifies every question onto an
existing engine, handlers perform REAL work through those engines, and
every response follows one fixed structure (Summary, Evidence,
Confidence, Recommended Next Action, Follow-ups) plus the steps
actually performed. Unknowns are stated, never guessed.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.advisor import (
    ConversationRepository,
    INTENT_CHANGES,
    INTENT_COMPASS,
    INTENT_CONTINUE,
    INTENT_DISCOVERY,
    INTENT_ENTERPRISE,
    INTENT_HEALTH,
    INTENT_PATH,
    INTENT_PREDICTION,
    INTENT_SEARCH,
    INTENT_UNKNOWN,
    NO_EVIDENCE_MESSAGE,
    ask,
    classify,
    path_endpoints,
    prediction_target,
    search_query,
)
from founderos_atlas.federation import (
    build_enterprise_snapshot,
    get_enterprise_graph,
)
from founderos_atlas.search import build_search_index

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


NOW = "2026-07-12T09:00:00+00:00"


class RoutingTests(unittest.TestCase):
    """Deterministic intent classification — the spec's own examples."""

    def test_spec_examples_route_correctly(self) -> None:
        for question, intent in (
            ("What changed?", INTENT_CHANGES),
            ("Find SW1", INTENT_SEARCH),
            ("Users cannot reach Branch", INTENT_PATH),
            ("What happens if I disable Gi0/1?", INTENT_PREDICTION),
            ("Continue yesterday's investigation", INTENT_CONTINUE),
            ("Help me plan maintenance", INTENT_COMPASS),
            ("Explain enterprise health", INTENT_HEALTH),
            ("Summarize discovery", INTENT_DISCOVERY),
            ("Summarize the enterprise", INTENT_ENTERPRISE),
            ("What is the meaning of life?", INTENT_UNKNOWN),
            ("", INTENT_UNKNOWN),
        ):
            self.assertEqual(intent, classify(question), question)

    def test_classification_is_deterministic(self) -> None:
        for question in ("What changed?", "Find SW1", "predict a reboot"):
            self.assertEqual(classify(question), classify(question))

    def test_search_query_strips_routing_verbs(self) -> None:
        self.assertEqual("SW1", search_query("Find SW1"))
        self.assertEqual("SW2", search_query("Can you find the device SW2?"))
        self.assertEqual("10.0.9.9", search_query("where is 10.0.9.9"))

    def test_path_endpoints_parse_the_common_shapes(self) -> None:
        self.assertEqual(("A1", "B1"), path_endpoints("path from A1 to B1"))
        self.assertEqual(("A1", "B1"), path_endpoints("Can A1 reach B1?"))
        self.assertEqual(("A1", "B1"), path_endpoints("A1 cannot reach B1"))
        self.assertEqual((None, None), path_endpoints("Users cannot reach"))

    def test_prediction_target_parses_device_and_interface(self) -> None:
        self.assertEqual(
            ("SW1", "Gi0/1"),
            prediction_target("What happens if I disable Gi0/1 on SW1?"),
        )
        self.assertEqual(
            ("GW", None), prediction_target("What happens if I reboot GW?")
        )
        self.assertEqual(
            (None, None), prediction_target("What happens if it rains?")
        )


def build_world(workdir: Path):
    service = make_service(workdir)
    add_profile(service, "Hyderabad", "10.0.0.1")
    add_profile(service, "Secunderabad", "10.0.1.1")
    run_discover(workdir, service, hyderabad_network(), "Hyderabad", FIXED)
    run_discover(
        workdir, service, secunderabad_network(), "Secunderabad",
        FIXED + timedelta(minutes=30),
    )
    return service


def advisor_kwargs(workdir: Path, service) -> dict:
    profiles = service.list_profiles()
    graph = get_enterprise_graph(workdir, profiles, now=NOW)
    snapshot = build_enterprise_snapshot(graph).to_dict() if graph.devices else None
    return {
        "base_output_dir": workdir,
        "profiles": profiles,
        "graph": graph,
        "snapshot": snapshot,
        "search_index": build_search_index(workdir, profiles),
        "generated_at": NOW,
    }


class EvidenceAnswerTests(unittest.TestCase):
    def test_health_answer_cites_reports_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            response = ask("Explain enterprise health",
                           **advisor_kwargs(workdir, service))
            self.assertEqual(INTENT_HEALTH, response.intent)
            self.assertIn("Hyderabad", response.summary)
            self.assertIn("Secunderabad", response.summary)
            self.assertIn("100/100", response.summary)
            labels = [item.label for item in response.evidence]
            self.assertIn("Enterprise Graph", labels)
            self.assertTrue(
                any("Intelligence report" in label for label in labels)
            )
            # FIXED evidence vs NOW: two days stale -> Medium, honestly.
            self.assertEqual("Medium", response.confidence)
            self.assertIn("freshness window", response.confidence_basis)
            self.assertTrue(response.steps)
            self.assertTrue(response.next_action_href)

    def test_find_device_answers_from_search_with_rank_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            response = ask("Find GW", **advisor_kwargs(workdir, service))
            self.assertEqual(INTENT_SEARCH, response.intent)
            self.assertIn("Found GW", response.summary)
            self.assertIn("observed by: Hyderabad, Secunderabad", response.summary)
            self.assertIn("identity confidence 95%", response.summary)
            self.assertEqual("High", response.confidence)
            self.assertIn("exact", response.confidence_basis)
            self.assertTrue(response.next_action_href.startswith("/devices/"))

    def test_search_miss_is_honest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            response = ask("Find UNICORN9", **advisor_kwargs(workdir, service))
            self.assertIn(NO_EVIDENCE_MESSAGE, response.summary)
            self.assertIn("UNICORN9", response.summary)
            self.assertEqual("Unknown", response.confidence)
            self.assertEqual("/discovery", response.next_action_href)

    def test_path_question_runs_a_real_investigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            response = ask("Can A1 reach B1?", **advisor_kwargs(workdir, service))
            self.assertEqual(INTENT_PATH, response.intent)
            self.assertIn("A1 can reach B1", response.summary)
            self.assertIn("A1 → GW → B1", response.summary)
            self.assertIn(
                "Running a path investigation", response.steps[0]
            )
            self.assertIn(response.confidence, ("High", "Medium", "Low"))

    def test_path_question_without_endpoints_routes_to_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            response = ask(
                "Users cannot reach the branch office",
                **advisor_kwargs(workdir, service),
            )
            self.assertEqual(INTENT_PATH, response.intent)
            self.assertIn("connectivity investigation", response.summary)
            self.assertEqual("/paths?scope=all", response.next_action_href)

    def test_prediction_question_runs_the_prediction_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            response = ask(
                "What happens if I disable Gi0/1 on A1?",
                **advisor_kwargs(workdir, service),
            )
            self.assertEqual(INTENT_PREDICTION, response.intent)
            self.assertIn("Predicted risk", response.summary)
            self.assertIn("GigabitEthernet0/1", response.steps[0])
            self.assertIn("Recommendation:", response.summary)
            self.assertIn(
                "prediction confidence", response.confidence_basis
            )

    def test_prediction_on_unknown_device_is_honest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            response = ask(
                "What happens if I reboot GHOST9?",
                **advisor_kwargs(workdir, service),
            )
            self.assertIn("GHOST9", response.summary)
            self.assertIn("no evidence", response.confidence_basis)
            self.assertEqual("Unknown", response.confidence)

    def test_changes_and_discovery_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            run_discover(
                workdir, service, network_a(a2_interfaces=A2_DOWN_BRIEF),
                "Hyderabad", FIXED + timedelta(hours=2),
            )
            kwargs = advisor_kwargs(workdir, service)
            changes = ask("What changed?", **kwargs)
            self.assertEqual(INTENT_CHANGES, changes.intent)
            self.assertIn("active issue", changes.summary)
            self.assertEqual("High", changes.confidence)
            discovery = ask("Summarize discovery", **kwargs)
            self.assertEqual(INTENT_DISCOVERY, discovery.intent)
            self.assertIn("Hyderabad", discovery.summary)
            self.assertIn("device(s) at", discovery.summary)

    def test_continue_resumes_the_latest_investigation(self) -> None:
        from founderos_atlas.path_intelligence import investigate_path_for_scope
        from founderos_atlas.federation import enterprise_scope_dir

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            kwargs = advisor_kwargs(workdir, service)
            empty = ask("Continue my investigation", **kwargs)
            self.assertIn(NO_EVIDENCE_MESSAGE, empty.summary)
            enterprise_dir = enterprise_scope_dir(workdir)
            enterprise_dir.mkdir(parents=True, exist_ok=True)
            (enterprise_dir / "topology_snapshot.json").write_text(
                json.dumps(kwargs["snapshot"]), encoding="utf-8"
            )
            investigate_path_for_scope(
                "A2", "B1",
                output_dir=enterprise_dir,
                history_root=enterprise_dir / "history",
                generated_at=NOW, profile_id="all",
            )
            resumed = ask("Continue my investigation", **kwargs)
            self.assertIn("A2 → B1", resumed.summary)
            self.assertEqual("Resume Investigation", resumed.next_action_label)
            self.assertEqual("/paths?scope=all", resumed.next_action_href)

    def test_compass_summary_reads_the_plan_repository(self) -> None:
        from founderos_atlas.compass import (
            PlanRepository, PlannedChange, add_change, create_plan,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            kwargs = advisor_kwargs(workdir, service)
            none_yet = ask("Help me plan maintenance", **kwargs)
            self.assertEqual(INTENT_COMPASS, none_yet.intent)
            self.assertIn("No maintenance plans exist yet", none_yet.summary)
            repository = PlanRepository(workdir)
            plan = create_plan(
                repository, title="Core Upgrade", maintenance_window="Tonight",
                engineer="netops", created_at=NOW,
            )
            add_change(
                repository, plan,
                PlannedChange(change_id="c1", device="GW",
                              change_type="ios-upgrade"),
                updated_at=NOW,
            )
            some = ask("Help me plan maintenance", **kwargs)
            self.assertIn("Core Upgrade", some.summary)
            self.assertIn("1 awaiting analysis", some.summary)
            self.assertEqual("/compass/core-upgrade", some.next_action_href)

    def test_unknown_question_never_guesses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            response = ask(
                "What is the best BGP timer configuration?",
                **advisor_kwargs(workdir, service),
            )
            self.assertEqual(INTENT_UNKNOWN, response.intent)
            self.assertIn(NO_EVIDENCE_MESSAGE, response.summary)
            self.assertEqual("Unknown", response.confidence)
            labels = [item.label for item in response.followups]
            for expected in ("Run Discovery", "Open an Investigation",
                             "Run a Prediction"):
                self.assertIn(expected, labels)

    def test_responses_are_structured_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            kwargs = advisor_kwargs(workdir, service)
            first = ask("Find GW", **kwargs).to_dict()
            second = ask("Find GW", **kwargs).to_dict()
            self.assertEqual(
                json.dumps(first, sort_keys=True),
                json.dumps(second, sort_keys=True),
            )
            for key in ("summary", "evidence", "confidence",
                        "confidence_basis", "next_action", "followups",
                        "steps", "intent"):
                self.assertIn(key, first)

    def test_conversations_persist_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = build_world(workdir)
            repository = ConversationRepository(workdir)
            ask("Find GW", repository=repository,
                **advisor_kwargs(workdir, service))
            ask("Explain enterprise health", repository=repository,
                **advisor_kwargs(workdir, service))
            stored = repository.list_conversations()
            self.assertEqual(2, len(stored))
            self.assertEqual(
                "Explain enterprise health",
                stored[0]["response"]["question"],
            )
            self.assertNotIn(PASSWORD, repository.path.read_text("utf-8"))


class AdvisorGuiTests(unittest.TestCase):
    def build_client(self, workdir: Path):
        from founderos_atlas.web import create_app

        service = build_world(workdir)
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return app.test_client()

    def test_advisor_home_offers_workflows_not_a_chatbot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            page = client.get("/advisor").data
            self.assertIn(b"Atlas Advisor", page)
            self.assertIn(b"How can I help today?", page)
            self.assertIn(b"Ask Atlas Advisor", page)
            for chip in (b"Investigate an Issue", b"Plan a Change",
                         b"Discover Infrastructure",
                         b"Explain Recent Changes",
                         b"Summarize Enterprise Health"):
                self.assertIn(chip, page)
            # Workflows stay visible; the conversation never dominates.
            self.assertIn(b"Continue Elsewhere", page)
            self.assertIn(b"Recent Conversations", page)

    def test_ask_renders_the_fixed_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            response = client.post(
                "/advisor/ask",
                data={"question": "Find GW"},
                follow_redirects=True,
            )
            body = response.data
            for section in (b"Summary", b"Evidence", b"Confidence",
                            b"Recommended Next Action", b"Follow-up",
                            b"How this answer was prepared"):
                self.assertIn(section, body)
            self.assertIn(b"Found GW", body)
            self.assertIn(b"Confidence: High", body)
            self.assertIn(b"/devices/", body)
            self.assertNotIn(PASSWORD.encode(), body)

    def test_unknown_question_is_honest_in_the_gui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            response = client.post(
                "/advisor/ask",
                data={"question": "Write me a poem about BGP"},
                follow_redirects=True,
            )
            # The apostrophe is HTML-escaped in the rendered page.
            self.assertIn(b"currently have enough evidence.", response.data)
            self.assertIn(b"Confidence: Unknown", response.data)
            self.assertIn(b"Run Discovery", response.data)

    def test_conversations_are_listed_and_reopenable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            client.post("/advisor/ask", data={"question": "Find GW"})
            client.post("/advisor/ask", data={"question": "What changed?"})
            page = client.get("/advisor").data
            self.assertIn(b"Find GW", page)
            self.assertIn(b"What changed?", page)
            reopened = client.get("/advisor?conversation=1").data
            self.assertIn(b"Found GW", reopened)

    def test_api_endpoint_returns_the_structured_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            payload = client.post(
                "/api/advisor/ask", json={"question": "Summarize discovery"}
            ).get_json()
            self.assertEqual("discovery", payload["intent"])
            self.assertIn("Hyderabad", payload["summary"])
            self.assertTrue(payload["evidence"])
            self.assertTrue(payload["steps"])
            empty = client.post("/api/advisor/ask", json={})
            self.assertEqual(400, empty.status_code)

    def test_mission_launches_advisor_and_advisor_links_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            mission = client.get("/?scope=all").data
            self.assertIn(b"Ask Atlas Advisor", mission)
            self.assertIn(b'href="/advisor"', mission)
            advisor = client.get("/advisor").data
            self.assertIn(b'href="/?scope=all"', advisor)


if __name__ == "__main__":
    unittest.main()


class AdvisorHonestyTests(unittest.TestCase):
    """Advisor must never claim evidence Atlas does not possess."""

    def test_unknown_device_answers_never_invent_facts(self) -> None:
        import tempfile
        from pathlib import Path

        from tests.test_polish import build_world

        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.post("/advisor/ask", data={
                "question": "Find device-that-was-never-discovered-xyz",
            }, follow_redirects=True).data.decode("utf-8")
            # The made-up hostname must not be presented as a known device
            # with facts attached; the honest outcome is a no-match answer.
            self.assertNotIn("device-that-was-never-discovered-xyz is",
                             page.casefold())
            self.assertTrue(
                "no match" in page.casefold()
                or "not found" in page.casefold()
                or "cannot" in page.casefold()
                or "0 result" in page.casefold()
                or "nothing" in page.casefold(),
                "the answer neither matched nor admitted the gap",
            )

    def test_stale_scope_answers_state_their_evidence_age(self) -> None:
        import tempfile
        from pathlib import Path

        from tests.test_polish import build_world

        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.post("/advisor/ask", data={
                "question": "Explain enterprise health",
            }, follow_redirects=True).data.decode("utf-8")
            # Every answer names its scope and cites evidence or admits the
            # absence — no free-floating claims.
            self.assertIn("scope:", page.casefold())
            self.assertTrue(
                "evidence used" in page.casefold()
                or "no evidence supports this answer" in page.casefold()
            )
