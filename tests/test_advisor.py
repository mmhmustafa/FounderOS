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
            # PR-167: the steps are now the whole investigation plan
            # with each step's outcome, not a single engine call. The
            # path walk is still among them — it is the engine the
            # investigation orchestrates for reachability.
            steps = " | ".join(response.steps)
            self.assertIn("Walk the path hop by hop", steps)
            self.assertIn("done", steps)
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
            # No catalog keyword anywhere in this question: since PR-164
            # a mention of BGP/OSPF/policy ESCALATES to the matching
            # operational intent (that path is pinned in test_oir), so
            # the never-guess test needs a question nothing claims.
            response = ask(
                "What should I cook for dinner?",
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

    def test_ask_renders_the_answer_hierarchy(self) -> None:
        """PR-168: verdict, then key findings, then what to do next —
        and only then the supporting detail, collapsed.

        PR-163 pinned the opposite order (summary, findings, checks,
        reasoning, evidence, confidence, freshness, recommendations),
        which put the thing an operator needs first in eighth place.
        The order is still asserted as an ORDER, not a bag of headings;
        it is the order itself that changed.
        """

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            response = client.post(
                "/advisor/ask",
                data={"question": "Find GW"},
                follow_redirects=True,
            )
            body = response.data
            answer = body[body.index(b"verdict-card"):]
            sections = (b"verdict-chip",                  # the status
                        b"verdict-answer",                # the answer
                        b"Key findings</h2>",
                        b"What to do next</h2>",
                        b"Supporting detail</h2>",
                        b"Evidence</span>")
            for section in sections:
                self.assertIn(section, answer)
            positions = [answer.index(section) for section in sections]
            self.assertEqual(positions, sorted(positions))

            # The verdict card leads with a status word an operator can
            # act on, not an internal tone key.
            verdict = answer[:answer.index(b"Key findings</h2>")]
            self.assertTrue(
                any(status in verdict for status in
                    (b"Healthy", b"Attention required",
                     b"Not enough evidence", b"Informational")),
                "the verdict must state an operational status",
            )

            # Nothing was lost — the supporting detail still carries
            # every section the old hierarchy showed inline.
            supporting = body[body.index(b"Supporting detail</h2>"):]
            for kept in (b"Inventory summary", b"checks performed",
                         b"Why Atlas reached this conclusion",
                         b"artifact(s) cited", b"Evidence freshness</h3>"):
                self.assertIn(kept, supporting)

            self.assertIn(b"Found GW", body)
            self.assertIn(b"High confidence", body)
            self.assertIn(b"/devices/", body)
            self.assertNotIn(PASSWORD.encode(), body)

    def test_supporting_detail_is_collapsed_not_deleted(self) -> None:
        """Part 4: details on demand. Every supporting section must be
        a <details> — present in the DOM, reachable by keyboard and by
        a screen reader, and closed by default so it does not compete
        with the answer. Deleting them instead would be a regression
        dressed as a simplification."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            body = client.post(
                "/advisor/ask", data={"question": "Find GW"},
                follow_redirects=True,
            ).data.decode()
            supporting = body[body.index("Supporting detail</h2>"):]
            supporting = supporting[:supporting.index("</section>")]
            self.assertIn("<details", supporting)
            # Only Limitations may open by default: an unstated
            # limitation reads as a claim.
            opened = supporting.count("<details class=\"advisor-detail "
                                      "advisor-limitations\" open>")
            self.assertLessEqual(opened, 1)
            self.assertNotIn("<details class=\"advisor-detail\" open>",
                             supporting)

    def test_unknown_question_is_honest_in_the_gui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            # "about the moon" carries no catalog keyword — a BGP poem
            # would now escalate to the BGP intent (PR-164), which is a
            # different honest path, pinned in test_oir.
            response = client.post(
                "/advisor/ask",
                data={"question": "Write me a poem about the moon"},
                follow_redirects=True,
            )
            # Substring chosen to dodge the HTML-escaped apostrophe in
            # "Atlas doesn't currently have enough evidence…".
            self.assertIn(b"currently have enough evidence to answer this.",
                          response.data)
            self.assertIn(b"Unknown confidence", response.data)
            # PR-168 Part 9: the status word an operator reads is
            # "Not enough evidence" — a real answer, said plainly.
            self.assertIn(b"Not enough evidence", response.data)
            # The Operational Intent Router still wears its decision
            # openly; PR-168 moved it out of the headline and into the
            # collapsed "Why Atlas reached this conclusion", because it
            # describes ATLAS rather than the operator's network.
            self.assertIn(b"Understood as <strong>Unknown</strong>",
                          response.data)
            self.assertIn(b"Run Discovery", response.data)

    def test_status_cards_show_current_scope_honestly(self) -> None:
        """The summary is CURRENT scope status (an old stored answer
        may come from another scope), and Routing carries no invented
        health verdict.

        PR-169 replaced the six-card grid with one Enterprise status
        summary. Every dimension is still named, every metric is still
        reachable, and the honesty is unchanged: a dimension with no
        health state must SAY so rather than imply one.
        """

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            page = client.get("/advisor").data
            self.assertIn(b"Enterprise status", page)
            for card in (b"Health", b"Discovery", b"Incidents", b"Policy",
                         b"Identity", b"Routing"):
                self.assertIn(card, page)
            self.assertIn(b"independent of any stored answer", page)
            self.assertIn(b"no health state assessed", page)
            self.assertIn(b"no routing health", page)
            # Filler that tells an operator nothing they can act on.
            self.assertNotIn(b"count only", page)
            self.assertNotIn(b"not evaluated yet", page)

    def test_the_dashboard_is_context_not_the_answer(self) -> None:
        """PR-169: the summary supports the answer; it must not compete
        with it. With no question asked the readiness detail is open —
        there is nothing to compete with. The moment there IS an answer
        it steps back, and the verdict becomes the largest thing on the
        page.
        """

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            empty = client.get("/advisor").data.decode()
            self.assertIn('<details class="ops-detail" open>', empty)
            # Starters are front and centre when there is no answer.
            self.assertNotIn("Start a different investigation", empty)

            client.post("/advisor/ask", data={"question": "Find GW"},
                        follow_redirects=True)
            answered = client.get("/advisor").data.decode()
            self.assertIn('<details class="ops-detail">', answered)
            self.assertNotIn('<details class="ops-detail" open>', answered)
            # ...and the generic starters step back too, without being
            # removed — they are still there, still keyboard-reachable.
            self.assertIn("Start a different investigation", answered)
            for starter in ("Investigate an Issue", "Plan a Change",
                            "Discover Infrastructure",
                            "Explain Recent Changes",
                            "Summarize Enterprise Health"):
                self.assertIn(starter, answered)

            # The answer outranks the dashboard in the DOM order.
            self.assertLess(answered.index("verdict-card"),
                            answered.index("Recent Conversations"))

    def test_the_summary_keeps_every_metric_the_cards_had(self) -> None:
        """Part 12: no functionality removed. The compact chips are a
        summary OF the dimension detail, not a replacement for it."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            page = client.get("/advisor").data.decode()
            detail = page[page.index("Dimension detail"):]
            detail = detail[:detail.index("</details>")]
            # Every card still contributes a row with its own link...
            for href in ("/history", "/incidents", "/policy",
                         "/evidence/resolution-center", "/topology"):
                self.assertIn(href, detail)
            # ...and its own METRIC VALUE. Asserting only the links let
            # `{{ card.value }}` be deleted with the suite still green —
            # which is exactly the "collapsing is not removing" claim
            # this test exists to defend.
            import re as _re

            self.assertIn("devices", detail)
            self.assertIn("relationships", detail)
            rows = _re.findall(r"<li>.*?</li>", detail, _re.S)
            self.assertEqual(len(rows), 6)
            for row in rows:
                self.assertRegex(
                    row, r'<span class="muted">\s*\S',
                    "every dimension row must carry its metric value",
                )
            # The chips are present too, and are links, not decoration.
            # Five dimension chips; the sixth card is the overall
            # readiness, which is the status word above them.
            chips = page[page.index('class="ops-chips"'):]
            chips = chips[:chips.index("</ul>")]
            self.assertEqual(chips.count("ops-chip "), 5)
            self.assertNotIn(">Health</span>", chips)

    def test_conversations_group_pin_and_search(self) -> None:
        """History is grouped by recency, pinnable, and searchable —
        and every row action still addresses its TRUE stored index."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            client.post("/advisor/ask", data={"question": "Find GW"})
            client.post("/advisor/ask", data={"question": "What changed?"})
            page = client.get("/advisor").data
            # Both were asked moments ago: they group under Today.
            self.assertIn(b"Today", page)
            self.assertIn(b'id="advisor-conv-search"', page)
            # Pin the older conversation (stored index 1 = "Find GW").
            pinned = client.post(
                "/advisor/conversations/1/pin", follow_redirects=True
            ).data
            self.assertIn(b"Pinned", pinned)
            self.assertIn(b"Unpin", pinned)
            # The pinned row still exports/acts through index 1.
            self.assertIn(b"/advisor/conversations/1/export", pinned)

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


class AdvisorHonestyTests(unittest.TestCase):
    """Advisor must never claim evidence Atlas does not possess."""

    def test_unknown_device_answers_never_invent_facts(self) -> None:
        import tempfile
        from pathlib import Path

        from tests.test_polish import build_world

        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            # The hostname must carry NO intent keyword: the old fixture
            # name contained "discovered", which routed the question to
            # the discovery handler and made this test pass on a heading
            # technicality instead of a real no-match answer.
            page = client.post("/advisor/ask", data={
                "question": "Find widget-node-that-was-never-seen-xyz",
            }, follow_redirects=True).data.decode("utf-8")
            # The made-up hostname must not be presented as a known device
            # with facts attached; the honest outcome is a no-match answer.
            self.assertNotIn("widget-node-that-was-never-seen-xyz is",
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
                "artifact(s) cited" in page.casefold()
                or "no evidence supports this answer" in page.casefold()
            )


class WorkflowChoiceSecurityTests(unittest.TestCase):
    """PR-164.1 Part 10: the analytics choice endpoint validates its
    input — external URLs, traversal, unknown intents, and oversized
    fields are rejected; valid clicks are recorded with the schema."""

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

    def test_valid_workflow_clicks_are_recorded(self) -> None:
        from founderos_atlas.oir import IntentAnalytics

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client = self.build_client(workdir)
            response = client.post("/api/advisor/workflow-choice", json={
                "intent": "Enterprise Health",
                "label": "Open Topology",
                "href": "/topology?scope=all",
            })
            self.assertEqual(200, response.status_code)
            events = IntentAnalytics(workdir).entries()
            self.assertEqual(1, len(events))
            self.assertEqual("choice", events[0]["kind"])
            self.assertIn("schema", events[0])
            # Engine answers link to dynamic detail pages too.
            deep = client.post("/api/advisor/workflow-choice", json={
                "intent": "", "label": "Open chennai-sw2",
                "href": "/devices/chennai-sw2",
            })
            self.assertEqual(200, deep.status_code)

    def test_invalid_routes_and_fields_are_rejected(self) -> None:
        from founderos_atlas.oir import IntentAnalytics

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client = self.build_client(workdir)
            bad_hrefs = (
                "https://evil.example/phish",   # absolute URL
                "//evil.example/phish",         # scheme-relative
                "/not-an-atlas-area",           # unknown workflow area
                "/topology/../secret",          # traversal
                "\\\\host\\share",              # backslashes
                "",                             # missing
            )
            for href in bad_hrefs:
                with self.subTest(href=href):
                    response = client.post(
                        "/api/advisor/workflow-choice",
                        json={"intent": "", "label": "x", "href": href},
                    )
                    self.assertEqual(400, response.status_code)
            self.assertEqual(400, client.post(
                "/api/advisor/workflow-choice",
                json={"intent": "Made Up Intent", "label": "x",
                      "href": "/topology"},
            ).status_code)
            self.assertEqual(400, client.post(
                "/api/advisor/workflow-choice",
                json={"intent": "", "label": "y" * 200,
                      "href": "/topology"},
            ).status_code)
            # Nothing invalid was recorded.
            self.assertEqual([], IntentAnalytics(workdir).entries())

    def test_malformed_bodies_are_400_never_500(self) -> None:
        """PR-164.1: a non-object JSON document must be a clean 400 —
        the pre-hardening behaviour was an AttributeError 500 — and an
        oversized body is refused before parsing."""

        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            for body in (b"true", b'"abc"', b"[1,2]", b"123"):
                with self.subTest(body=body):
                    response = client.post(
                        "/api/advisor/workflow-choice", data=body,
                        content_type="application/json",
                    )
                    self.assertEqual(400, response.status_code)
            huge = json.dumps(
                {"href": "/topology", "label": "x" * 10000}
            ).encode()
            self.assertEqual(413, client.post(
                "/api/advisor/workflow-choice", data=huge,
                content_type="application/json",
            ).status_code)
            # The ask API shares the same guard.
            self.assertEqual(400, client.post(
                "/api/advisor/ask", data=b"[1,2]",
                content_type="application/json",
            ).status_code)

    def test_the_choice_endpoint_is_rate_limited(self) -> None:
        from founderos_atlas.web.security import _RATE_LIMITS

        self.assertIn("api_advisor_workflow_choice", _RATE_LIMITS)

    def test_the_beacon_carries_the_csrf_token_in_its_body(self) -> None:
        """sendBeacon cannot set headers, so in password mode the token
        must ride in the JSON body or every click 403s and writes a
        false CSRF-denial audit event."""

        script = Path("src/founderos_atlas/web/static/atlas.js").read_text(
            encoding="utf-8"
        )
        beacon = script.split("data-oir-choice", 1)[1][:1500]
        self.assertIn("atlas_csrf", beacon)
        self.assertIn("_csrf:", beacon)

    def test_diagnostics_endpoint_describes_the_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            report = client.get("/api/oir/diagnostics").get_json()
            self.assertTrue(report["frozen"])
            self.assertEqual("passed", report["validation"])
            self.assertGreaterEqual(report["intent_count"], 25)


if __name__ == "__main__":
    unittest.main()
