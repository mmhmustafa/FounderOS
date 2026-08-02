"""PR-163: the Advisor presenter — hierarchy, honesty, and grouping.

The presenter reorganizes what the engine already said; these tests pin
that it never invents a verdict the engine's words don't support, never
blends evidence freshness into answer confidence, and never lets the
display order change which stored conversation an action addresses.
"""

from __future__ import annotations

import unittest

from founderos_atlas.advisor.presentation import (
    group_conversations,
    present_answer,
)


def make_response(**overrides) -> dict:
    base = {
        "question": "Is the network healthy?",
        "intent": "health",
        "summary": "The enterprise is healthy. 3 managed devices. "
                   "No active issues.",
        "evidence": [
            {"label": "Enterprise Graph", "detail": "3 devices",
             "href": "/topology?scope=all"},
        ],
        "confidence": "High",
        "confidence_basis": "discovery is complete and fresh",
        "next_action": {"label": "Open Mission", "href": "/?scope=all"},
        "followups": [
            {"label": "What changed?", "question": "What changed?",
             "href": None},
            {"label": "Open History", "question": None, "href": "/history"},
        ],
        "unknowns": ["2 devices refused credentials"],
        "steps": ["asked the enterprise graph", "read the change report"],
        "generated_at": "2026-07-26T10:00:00+00:00",
    }
    base.update(overrides)
    return base


class VerdictHonestyTests(unittest.TestCase):
    def test_unknown_confidence_is_an_unknown_verdict(self) -> None:
        shown = present_answer(make_response(confidence="Unknown"))
        self.assertEqual("unknown", shown["verdict"]["tone"])
        # PR-164 Part 6: the natural-language honest sentence.
        self.assertIn("enough evidence to answer this",
                      shown["verdict"]["headline"])

    def test_no_active_issues_is_not_read_as_a_problem(self) -> None:
        """Negated phrases must never trip the concern markers."""

        shown = present_answer(make_response(
            summary="The enterprise is healthy. No active issues observed.",
        ))
        self.assertEqual("ok", shown["verdict"]["tone"])

    def test_engine_reported_concerns_surface_as_attention(self) -> None:
        shown = present_answer(make_response(
            summary="1 active issue at delhi-core. 2 interfaces down.",
            confidence="Medium",
        ))
        self.assertEqual("attention", shown["verdict"]["tone"])

    def test_a_neutral_listing_claims_neither_ok_nor_concern(self) -> None:
        shown = present_answer(make_response(
            intent="compass",
            summary="2 maintenance plans exist. 1 awaiting analysis.",
        ))
        self.assertEqual("info", shown["verdict"]["tone"])

    def test_answer_without_stored_fields_still_presents(self) -> None:
        """Older stored conversations (sparse dicts) must render."""

        shown = present_answer({"summary": "Something.", "confidence": "Low"})
        self.assertEqual("Low", shown["confidence"]["level"])
        self.assertEqual([], shown["findings"])
        self.assertEqual([], shown["actions"])
        self.assertIsNone(present_answer(None))


class HierarchyTests(unittest.TestCase):
    def test_summary_becomes_at_most_six_bullets(self) -> None:
        long = ". ".join(f"Sentence number {n}" for n in range(1, 10)) + "."
        shown = present_answer(make_response(summary=long))
        self.assertEqual(6, len(shown["summary_bullets"]))
        self.assertIn("further detail", shown["summary_bullets"][-1])

    def test_reasoning_is_separate_from_raw_evidence(self) -> None:
        shown = present_answer(make_response())
        self.assertIn("2 check(s)", shown["reasoning"])
        self.assertIn("1 cited artifact(s)", shown["reasoning"])
        self.assertIn("discovery is complete and fresh",
                      shown["reasoning"].casefold())
        self.assertIn("1 limitation(s)", shown["reasoning"])

    def test_every_recommendation_explains_why(self) -> None:
        shown = present_answer(make_response())
        self.assertTrue(shown["actions"])
        self.assertTrue(all(action["why"] for action in shown["actions"]))
        self.assertTrue(shown["actions"][0]["primary"])
        # Followups with an href become secondary recommendations; the
        # question-form followups stay chips.
        labels = [action["label"] for action in shown["actions"]]
        self.assertIn("Open History", labels)
        chips = [item["label"] for item in shown["followup_questions"]]
        self.assertEqual(["What changed?"], chips)


class FreshnessSeparationTests(unittest.TestCase):
    def test_stale_freshness_never_lowers_answer_confidence(self) -> None:
        """The two are different facts: freshness describes the evidence's
        age, confidence describes the reasoning. Display must keep them
        apart."""

        stale = {"last_discovery": "2026-07-20T00:00:00+00:00",
                 "age": "150 hour(s) old", "warn": True,
                 "note": "Latest discovery is 150 hour(s) old."}
        shown = present_answer(make_response(confidence="High"),
                               freshness=stale)
        self.assertEqual("High", shown["confidence"]["level"])
        self.assertTrue(shown["freshness"]["warn"])

    def test_missing_freshness_is_absent_not_invented(self) -> None:
        shown = present_answer(make_response())
        self.assertIsNone(shown["freshness"])


class ConversationGroupingTests(unittest.TestCase):
    NOW = "2026-07-26T12:00:00+00:00"

    def entry(self, asked_at, question, **extra) -> dict:
        record = {"asked_at": asked_at,
                  "response": {"question": question, "intent": "health",
                               "confidence": "High"}}
        record.update(extra)
        return record

    def test_groups_by_recency_with_pinned_first(self) -> None:
        entries = [
            self.entry("2026-07-26T09:00:00+00:00", "today"),
            self.entry("2026-07-25T09:00:00+00:00", "yesterday"),
            self.entry("2026-07-21T09:00:00+00:00", "last week",
                       pinned=True),
            self.entry("2026-06-01T09:00:00+00:00", "older"),
        ]
        groups = group_conversations(entries, now=self.NOW)
        self.assertEqual(
            ["Pinned", "Today", "Yesterday", "Older"],
            [group["title"] for group in groups],
        )

    def test_display_order_never_changes_the_stored_index(self) -> None:
        """Rename/delete/export/pin address conversations positionally;
        a pinned row floating to the top must keep its true index."""

        entries = [
            self.entry("2026-07-26T09:00:00+00:00", "newest"),
            self.entry("2026-07-26T08:00:00+00:00", "pinned one",
                       pinned=True),
        ]
        groups = group_conversations(entries, now=self.NOW)
        pinned_group = groups[0]
        self.assertEqual("Pinned", pinned_group["title"])
        self.assertEqual(1, pinned_group["items"][0]["index"])

    def test_unparseable_timestamps_fall_to_older_not_an_error(self) -> None:
        groups = group_conversations(
            [self.entry("not-a-timestamp", "odd one")], now=self.NOW
        )
        self.assertEqual(["Older"], [group["title"] for group in groups])


class OperationalIntentTests(unittest.TestCase):
    """PR-164: the presenter shows the OIR's decision and the intent's
    declared workflows/limitations — additively, and tolerantly for
    conversations stored before the router existed."""

    OI = {
        "name": "Routing Investigation", "key": "routing-investigation",
        "domain": "routing", "routing_confidence": "High",
        "why": ["the question contains “health”",
                "the question mentions “routing”"],
        "escalated": False,
        "workflows": [{
            "label": "Open Topology (routing views)", "href": "/topology",
            "why": "The OSPF and BGP views draw the observed adjacencies.",
        }],
        "recommendations": [{
            "label": "Review Changes", "href": "/changes",
            "why": "Routing trouble usually follows a change.",
        }],
        "followups": [{"label": "Show BGP", "question": "Show me BGP"}],
        "limitations": ["Routing observations reflect discovery time."],
    }

    def test_domain_selects_the_summary_title(self) -> None:
        shown = present_answer(make_response(operational_intent=self.OI))
        self.assertEqual("Routing summary", shown["summary_title"])
        # Without the block (pre-OIR conversations) the classic title holds.
        self.assertEqual("Executive summary",
                         present_answer(make_response())["summary_title"])

    def test_intent_is_displayed_with_its_why(self) -> None:
        shown = present_answer(make_response(operational_intent=self.OI))
        self.assertEqual("Routing Investigation", shown["intent"]["name"])
        self.assertEqual("High", shown["intent"]["confidence"])
        self.assertEqual(2, len(shown["intent"]["why"]))
        self.assertIsNone(present_answer(make_response())["intent"])

    def test_intent_workflows_join_actions_with_their_whys(self) -> None:
        shown = present_answer(make_response(operational_intent=self.OI))
        by_href = {action["href"]: action for action in shown["actions"]}
        self.assertIn("/topology", by_href)
        self.assertIn("adjacencies", by_href["/topology"]["why"])
        self.assertIn("/changes", by_href)
        # The engine's own primary action still leads.
        self.assertTrue(shown["actions"][0]["primary"])

    def test_limitations_and_followups_merge_without_duplicates(self) -> None:
        oi = dict(self.OI)
        oi["limitations"] = ["2 devices refused credentials",
                             "A standing intent limitation."]
        oi["followups"] = [
            {"label": "What changed?", "question": "What changed?"},
            {"label": "Show BGP", "question": "Show me BGP"},
        ]
        shown = present_answer(make_response(operational_intent=oi))
        self.assertEqual(
            ["2 devices refused credentials",
             "A standing intent limitation."],
            shown["limitations"],
        )
        chips = [item["question"] for item in shown["followup_questions"]]
        self.assertEqual(["What changed?", "Show me BGP"], chips)

    def test_checks_get_operational_names_and_keep_raw_steps(self) -> None:
        shown = present_answer(make_response(
            steps=["Reading the Enterprise Knowledge Graph…",
                   "an unmapped bespoke step"],
        ))
        self.assertEqual("Enterprise Graph", shown["checked"][0]["label"])
        self.assertEqual("Reading the Enterprise Knowledge Graph…",
                         shown["checked"][0]["step"])
        # A step no name claims keeps its raw text — nothing invented.
        self.assertEqual("an unmapped bespoke step",
                         shown["checked"][1]["label"])


INVESTIGATION = {
    "request": {"protocol": "bgp"},
    "entities": {
        "source": {"query": "mumbai", "status": "resolved", "detail": ""},
        "destination": {"query": "chennai", "status": "resolved",
                        "detail": ""},
        "sites": [], "devices": [],
    },
    "plan": {"title": "BGP between two endpoints", "objective": "…",
             "steps": []},
    "findings": [
        {"label": "BGP session", "detail": "established", "href": "/x"},
        {"label": "No route flaps", "detail": "", "href": ""},
    ],
    "engines_used": ["graph", "routing", "changes"],
    "duration_ms": 4,
}


class ExperienceLanguageTests(unittest.TestCase):
    """PR-168: the operator-facing layer. Every value here is a
    RELABELLING of something Atlas already recorded — the tests exist to
    stop that turning into a new judgement."""

    def test_the_verdict_carries_an_operational_status_word(self) -> None:
        for confidence, summary, expected in (
            ("High", "The enterprise is healthy.", "Healthy"),
            ("High", "2 interfaces down and a degraded link.",
             "Attention required"),
            ("Unknown", "Anything at all.", "Not enough evidence"),
            ("Medium", "Here are 4 devices.", "Informational"),
        ):
            with self.subTest(expected=expected):
                shown = present_answer(make_response(
                    summary=summary, confidence=confidence,
                ))
                self.assertEqual(shown["verdict"]["status"], expected)

    def test_the_status_never_outruns_the_engine(self) -> None:
        """The presenter may not decide a network is healthy. When the
        engine's words do not support a judgement, the status says so
        rather than guessing — this is the whole honesty contract of
        the verdict, restated for the new label."""

        shown = present_answer(make_response(
            summary="4 adjacency(ies) observed, 4 in Full state.",
            confidence="High",
        ))
        self.assertEqual(shown["verdict"]["status"], "Informational")
        self.assertNotEqual(shown["verdict"]["status"], "Healthy")

    def test_context_replaces_implementation_language(self) -> None:
        shown = present_answer(make_response(investigation=INVESTIGATION))
        rows = {row["label"]: row["value"] for row in shown["context"]}
        self.assertEqual(rows["Investigation"], "BGP between two endpoints")
        self.assertEqual(rows["Protocol"], "BGP")
        self.assertEqual(rows["Scope"], "mumbai to chennai")
        # Nothing in the operator-facing context names Atlas's router.
        self.assertNotIn("Understood as", repr(shown["context"]))

    def test_context_falls_back_to_a_kind_without_an_investigation(
        self,
    ) -> None:
        shown = present_answer(
            make_response(),
            # No investigation block: the intent name still becomes an
            # operator-facing KIND rather than being shown raw.
        )
        rows = {row["label"]: row["value"] for row in shown["context"]}
        self.assertIn("Investigation", rows)
        self.assertNotIn("Protocol", rows)

    def test_investigated_names_subjects_not_engines(self) -> None:
        shown = present_answer(make_response(investigation=INVESTIGATION))
        self.assertEqual(
            shown["investigated"],
            ["Mumbai", "Chennai", "BGP", "Devices & interfaces", "Routing",
             "Recent changes"],
            # "mumbai"/"chennai" are plain site words, so they are
            # capitalised for reading; an identifier would not be.
        )
        self.assertEqual(shown["investigated_ms"], 4)
        for engine in ("graph", "routing", "changes"):
            self.assertNotIn(engine, shown["investigated"])

    def test_an_unresolved_entity_is_never_shown_as_investigated(
        self,
    ) -> None:
        """A ✓ beside a name Atlas could not resolve claims work that
        did not happen. The chip row exists to make REAL work visible;
        an ambiguous or unknown entity belongs in the investigation
        detail, where its status is stated."""

        unresolved = dict(INVESTIGATION)
        unresolved["entities"] = {
            "source": {"query": "mumbai", "status": "resolved"},
            "destination": {"query": "atlantis", "status": "unknown"},
            "sites": [{"query": "delhi", "status": "ambiguous"}],
            "devices": [{"query": "core1", "status": "resolved"}],
        }
        shown = present_answer(make_response(investigation=unresolved))
        self.assertIn("Mumbai", shown["investigated"])
        self.assertIn("core1", shown["investigated"])
        self.assertNotIn("Atlantis", shown["investigated"])
        self.assertNotIn("Delhi", shown["investigated"])

    def test_an_identifier_is_shown_exactly_as_atlas_holds_it(self) -> None:
        """A site word is capitalised for reading; a hostname is not.
        "core1.example.net" title-cased to "Core1.Example.Net" — a
        string matching no device, unpasteable into search or a CLI."""

        graphish = dict(INVESTIGATION)
        graphish["entities"] = {
            "source": {"query": "core1.example.net", "status": "resolved"},
            "destination": {"query": "mumbai", "status": "resolved"},
            "sites": [], "devices": [],
        }
        shown = present_answer(make_response(investigation=graphish))
        self.assertIn("core1.example.net", shown["investigated"])
        self.assertIn("Mumbai", shown["investigated"])

    def test_a_protocol_chip_needs_an_engine_that_read_it(self) -> None:
        """The protocol is what the operator ASKED about. Emitting a ✓
        beside it because the question said "HSRP" claims Atlas
        investigated a protocol it has no engine for."""

        asked_only = dict(INVESTIGATION)
        asked_only["request"] = {"protocol": "hsrp"}
        asked_only["engines_used"] = ["graph", "changes"]
        shown = present_answer(make_response(investigation=asked_only))
        self.assertNotIn("HSRP", shown["investigated"])

        # With a routing engine in the run, the chip is earned.
        read_it = dict(asked_only)
        read_it["engines_used"] = ["graph", "routing"]
        shown = present_answer(make_response(investigation=read_it))
        self.assertIn("HSRP", shown["investigated"])

    def test_a_skipped_step_is_not_counted_as_a_check_performed(
        self,
    ) -> None:
        """An investigation records each step's outcome in the step
        text. Rendering "… — skipped" with a ✓ under "Operational
        checks performed" told an operator five checks ran when one
        did."""

        shown = present_answer(make_response(steps=[
            "Collect BGP sessions — done",
            "Walk the path hop by hop — skipped",
            "Read recent changes — blocked",
        ]))
        self.assertEqual([item["outcome"] for item in shown["checked"]],
                         ["done", "skipped", "blocked"])

    def test_the_engines_warning_state_is_not_flattened(self) -> None:
        """The enterprise health engine distinguishes Warning from
        Critical. No marker matched "Warning", so an estate Atlas had
        flagged rendered as a neutral "Informational" — the operator
        got no signal that a problem was developing."""

        shown = present_answer(make_response(
            summary="Enterprise health is Warning — 3 reconciliation "
                    "warning(s). The graph holds 85 device(s).",
            confidence="High",
        ))
        self.assertEqual(shown["verdict"]["status"], "Warning")
        self.assertEqual(shown["verdict"]["tone"], "warning")

        # Critical still outranks it, and a clean estate is unaffected.
        critical = present_answer(make_response(
            summary="Enterprise health is Critical — 2 interfaces down.",
            confidence="High",
        ))
        self.assertEqual(critical["verdict"]["status"], "Attention required")
        healthy = present_answer(make_response(
            summary="Enterprise health is Healthy — 0 reconciliation "
                    "warning(s); no active issues.",
            confidence="High",
        ))
        self.assertEqual(healthy["verdict"]["status"], "Healthy")

    def test_stored_intents_get_operator_names(self) -> None:
        from founderos_atlas.advisor.presentation import intent_label

        self.assertEqual(intent_label("health"), "Health")
        self.assertEqual(intent_label("path"), "Connectivity")
        # The history list tagged unroutable questions "unknown".
        self.assertEqual(intent_label("unknown"), "No evidence")
        self.assertEqual(intent_label(""), "Answer")

    def test_nothing_is_investigated_without_an_investigation(self) -> None:
        shown = present_answer(make_response())
        self.assertEqual(shown["investigated"], [])
        self.assertIsNone(shown["investigated_ms"])

    def test_key_findings_prefer_the_investigations_own(self) -> None:
        shown = present_answer(make_response(investigation=INVESTIGATION))
        self.assertEqual([item["label"] for item in shown["key_findings"]],
                         ["BGP session", "No route flaps"])
        self.assertEqual(shown["key_findings"][0]["detail"], "established")

    def test_key_findings_fall_back_to_cited_evidence(self) -> None:
        shown = present_answer(make_response())
        self.assertEqual([item["label"] for item in shown["key_findings"]],
                         ["Enterprise Graph"])

    def test_key_findings_are_capped(self) -> None:
        many = dict(INVESTIGATION)
        many["findings"] = [
            {"label": f"Finding {i}", "detail": "", "href": ""}
            for i in range(20)
        ]
        shown = present_answer(make_response(investigation=many))
        self.assertEqual(len(shown["key_findings"]), 6)

    def test_a_malformed_investigation_never_raises(self) -> None:
        """The GUI renders persisted dicts, so a stored answer from an
        older schema must degrade, not explode."""

        for bad in ({}, {"entities": "nope"}, {"findings": ["not a dict"]},
                    {"plan": None, "request": 7}):
            with self.subTest(bad=bad):
                shown = present_answer(make_response(investigation=bad))
                self.assertIsInstance(shown["context"], list)
                self.assertIsInstance(shown["investigated"], list)
                self.assertIsInstance(shown["key_findings"], list)


if __name__ == "__main__":
    unittest.main()
