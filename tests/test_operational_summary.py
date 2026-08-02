"""PR-169 — the Atlas operational dashboard standard.

The claim under test: a page can present enterprise context in about
three seconds without deciding anything. Every state here is read from
an assessment the health model already produced; the only arithmetic is
a percentage from a ratio Atlas already recorded.
"""

from __future__ import annotations

import unittest

from founderos_atlas.web.dashboard import (
    READINESS,
    percentage,
    readiness_for,
    summarise,
)


def cards():
    return [
        {"title": "Health", "state": "healthy", "chip": "Healthy",
         "detail": "All dimensions healthy.", "href": "/",
         "updated": "2026-08-02T10:00:00+00:00"},
        {"title": "Discovery", "state": "stale", "chip": "85",
         "detail": "Latest discovery is 3 day(s) old.", "href": "/history"},
        {"title": "Incidents", "state": "healthy", "chip": "0",
         "detail": "No active incidents.", "href": "/incidents"},
        {"title": "Policy", "state": "degraded", "chip": "53%",
         "detail": "538 of 1020 checks passed.", "href": "/policy"},
        {"title": "Identity", "state": "healthy", "chip": "85",
         "detail": "85 endpoints resolved.", "href": "/evidence"},
        {"title": "Routing", "state": None, "chip": "119",
         "detail": "Counts only — Atlas defines no routing health verdict.",
         "href": "/topology"},
    ]


class ReadinessTests(unittest.TestCase):
    """Part 2: reuse existing Atlas determinations, never invent."""

    def test_every_health_state_maps_to_an_operator_word(self) -> None:
        """A state with no mapping would silently read as 'Not enough
        evidence' — the PR-168 Warning bug, one layer up."""

        from founderos_atlas.health.model import HEALTH_STATES

        for state in HEALTH_STATES:
            with self.subTest(state=state):
                self.assertIn(state, READINESS)
                status, tone = readiness_for(state)
                self.assertTrue(status and tone)

    def test_the_overall_status_is_the_engines_own(self) -> None:
        for state, expected in (("healthy", "Healthy"),
                                ("degraded", "Warning"),
                                ("stale", "Warning"),
                                ("critical", "Attention required"),
                                ("unknown", "Not enough evidence"),
                                ("unavailable", "Not enough evidence")):
            with self.subTest(state=state):
                rows = cards()
                rows[0]["state"] = state
                self.assertEqual(summarise(rows)["status"], expected)

    def test_an_unrecognised_state_does_not_become_healthy(self) -> None:
        """The safe direction for an unknown input is "we cannot say",
        never "everything is fine"."""

        rows = cards()
        rows[0]["state"] = "something-new"
        self.assertEqual(summarise(rows)["status"], "Not enough evidence")

    def test_nothing_is_summarised_without_cards(self) -> None:
        empty = summarise([])
        self.assertFalse(empty["available"])
        self.assertEqual(empty["chips"], [])
        self.assertEqual(empty["status"], "Not enough evidence")


class PercentageTests(unittest.TestCase):
    """Arithmetic on Atlas's own numbers is not invention. Guessing at
    a denominator would be."""

    def test_a_ratio_becomes_a_percentage(self) -> None:
        self.assertEqual(percentage(538, 1020), "53%")
        self.assertEqual(percentage(1, 1), "100%")
        self.assertEqual(percentage(0, 7), "0%")

    def test_an_unknown_ratio_yields_nothing(self) -> None:
        for numerator, denominator in ((None, 10), (5, None), (5, 0),
                                       ("x", 10), (5, "y"), (None, None)):
            with self.subTest(pair=(numerator, denominator)):
                self.assertEqual(percentage(numerator, denominator), "")


class ChipTests(unittest.TestCase):
    """Part 3: chips are for scanning, not reading."""

    def test_one_chip_per_dimension_in_order(self) -> None:
        """The overall card is the readiness WORD, not a chip. Showing
        it in both places said one fact twice — and said it in the
        health model's vocabulary ("Health · Stale") beside the
        operator's ("Warning")."""

        chips = summarise(cards())["chips"]
        self.assertEqual([chip["label"] for chip in chips],
                         ["Discovery", "Incidents", "Policy",
                          "Identity", "Routing"])
        self.assertEqual([chip["value"] for chip in chips],
                         ["85", "0", "53%", "85", "119"])
        self.assertNotIn("Health", [chip["label"] for chip in chips])

    def test_a_chip_carries_its_state_and_its_link(self) -> None:
        chips = {c["label"]: c for c in summarise(cards())["chips"]}
        self.assertEqual(chips["Policy"]["tone"], "warning")
        self.assertEqual(chips["Policy"]["href"], "/policy")
        # Atlas's own sentence stays reachable from a 3-character chip.
        self.assertIn("538 of 1020", chips["Policy"]["detail"])

    def test_a_dimension_with_no_state_is_not_coloured(self) -> None:
        """Routing carries no health verdict, so its chip must not
        borrow one — including the neutral "unknown" styling, which
        would read as "Atlas tried and failed"."""

        chips = {c["label"]: c for c in summarise(cards())["chips"]}
        self.assertEqual(chips["Routing"]["tone"], "none")

    def test_a_missing_chip_value_is_an_em_dash(self) -> None:
        rows = cards()
        rows[3]["chip"] = ""
        chips = {c["label"]: c for c in summarise(rows)["chips"]}
        self.assertEqual(chips["Policy"]["value"], "—")


class ReviewRegressionTests(unittest.TestCase):
    """Defects an adversarial review found in this PR, each reproduced
    before it was fixed."""

    def test_state_reaches_the_operator_without_colour(self) -> None:
        """The chip carried its state ONLY as a border colour, while
        the CSS comment and the guide both claimed the value text
        carried it too. "Discovery 85" was byte-identical whether the
        dimension was stale or healthy — nothing for a colour-blind
        operator, a forced-colours display, or a screen reader."""

        chips = {c["label"]: c for c in summarise(cards())["chips"]}
        # A shape...
        self.assertEqual(chips["Discovery"]["mark"], "warning")
        self.assertEqual(chips["Identity"]["mark"], "check")
        # ...and a word, for the accessible name.
        self.assertEqual(chips["Discovery"]["status"], "Warning")
        self.assertEqual(chips["Identity"]["status"], "Healthy")

    def test_an_unassessed_chip_claims_no_state(self) -> None:
        chips = {c["label"]: c for c in summarise(cards())["chips"]}
        self.assertEqual(chips["Routing"]["mark"], "")
        self.assertEqual(chips["Routing"]["status"], "")

    def test_a_warning_is_never_reported_as_nothing_flagged(self) -> None:
        """The readiness word is the health model's worst-of over EVERY
        dimension, including ones this page gives no card. Counting
        only the cards let the header say "Warning" directly above
        "nothing flagged"."""

        rows = cards()
        rows[0]["state"] = "degraded"      # the overall says Warning...
        for row in rows[1:]:
            row["state"] = "healthy"       # ...but every card is clean
        summary = summarise(rows)
        self.assertEqual(summary["status"], "Warning")
        self.assertEqual(summary["concerns"], 0)
        self.assertTrue(summary["unlisted_concern"])

    def test_a_clean_estate_flags_nothing(self) -> None:
        rows = cards()
        for row in rows:
            row["state"] = "healthy"
        summary = summarise(rows)
        self.assertEqual(summary["concerns"], 0)
        self.assertFalse(summary["unlisted_concern"])

    def test_the_overall_detail_is_not_repeated_verbatim(self) -> None:
        """overall_detail is composed from the failing dimension's own
        summary, so on a carded dimension it repeated that observation
        word for word, two lines apart."""

        rows = cards()
        rows[0]["state"] = "stale"
        rows[0]["detail"] = rows[1]["detail"]     # the same sentence
        self.assertFalse(summarise(rows)["show_detail"])

        # ...including when the health model prefixes it with the
        # dimension's label, which an exact-match check missed.
        rows[0]["detail"] = "Discovery freshness: " + rows[1]["detail"]
        self.assertFalse(summarise(rows)["show_detail"])

        # ...but when it names something no card covers, it is shown.
        rows[0]["detail"] = "Reachability: 3 device(s) unreachable."
        self.assertTrue(summarise(rows)["show_detail"])


class ObservationTests(unittest.TestCase):
    """Part 2: supporting observations under the readiness word."""

    def test_observations_exclude_the_overall_card(self) -> None:
        """The verdict is not an observation about itself."""

        summary = summarise(cards())
        self.assertNotIn("Health",
                         [item["label"] for item in summary["observations"]])
        self.assertEqual(len(summary["observations"]), 5)

    def test_a_healthy_dimension_gets_a_check_icon(self) -> None:
        marks = {item["label"]: item["mark"]
                 for item in summarise(cards())["observations"]}
        self.assertEqual(marks["Incidents"], "check")
        self.assertEqual(marks["Identity"], "check")

    def test_a_troubled_dimension_gets_a_warning_icon(self) -> None:
        marks = {item["label"]: item["mark"]
                 for item in summarise(cards())["observations"]}
        self.assertEqual(marks["Discovery"], "warning")
        self.assertEqual(marks["Policy"], "warning")

    def test_an_unassessed_dimension_never_gets_a_tick(self) -> None:
        """A tick means "checked and fine". Routing was not checked."""

        observations = {item["label"]: item
                        for item in summarise(cards())["observations"]}
        self.assertEqual(observations["Routing"]["mark"], "dot")
        self.assertEqual(observations["Routing"]["tone"], "unknown")

    def test_an_unassessed_dimension_says_so(self) -> None:
        rows = cards()
        rows[1]["state"] = "unknown"
        rows[1]["detail"] = ""
        observations = {item["label"]: item
                        for item in summarise(rows)["observations"]}
        self.assertEqual(observations["Discovery"]["text"],
                         "Atlas has not assessed this.")

    def test_the_concern_count_lets_a_collapsed_summary_speak(self) -> None:
        """So an operator knows whether opening it is worth their time."""

        self.assertEqual(summarise(cards())["concerns"], 2)
        clean = cards()
        for row in clean[1:]:
            row["state"] = "healthy"
        self.assertEqual(summarise(clean)["concerns"], 0)


class ToleranceTests(unittest.TestCase):
    """A dashboard must not be the thing that breaks a page."""

    def test_malformed_cards_never_raise(self) -> None:
        for rows in ([{}], [{"title": None, "state": 7}],
                     [{"title": "X", "state": "healthy"}],
                     [{"chip": None, "detail": None, "href": None}]):
            with self.subTest(rows=rows):
                summary = summarise(rows)
                self.assertTrue(summary["available"])
                self.assertIsInstance(summary["chips"], list)
                self.assertIsInstance(summary["observations"], list)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
