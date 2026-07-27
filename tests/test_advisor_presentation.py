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


if __name__ == "__main__":
    unittest.main()
