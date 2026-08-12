"""Shared Experience Language components (PR-178).

Step 1 of the approved plan: the honest-number renderer, the provenance
line, the answer band extracted from Advisor's verdict card, and the
filter chips extracted from Evidence — unit-tested BEFORE any page
adopts them. The core rule under test: every number is a measurement,
or it is not rendered as a number.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path


def _app():
    from founderos_atlas.web import create_app

    tmp = Path(tempfile.mkdtemp(prefix="pr178-el-"))
    app = create_app(
        output_dir=tmp,
        history_root=tmp / ".atlas" / "history",
        workspace_root=tmp / "workspace",
    )
    app.config.update(TESTING=True)
    return app


APP = _app()


def render(source: str, **context) -> str:
    with APP.test_request_context("/"):
        return APP.jinja_env.from_string(source).render(**context)


FMT = '{% import "_fmt.html" as fmt %}'
ANSWER = '{% import "_answer.html" as answer %}'


class MeasureTests(unittest.TestCase):
    """The four-state contract of _fmt.measure()."""

    def test_a_measured_number_renders_plainly(self) -> None:
        self.assertEqual(
            "42", render(FMT + "{{ fmt.measure(42) }}").strip()
        )

    def test_a_measured_zero_renders_as_zero(self) -> None:
        # ZERO is a measurement. It must never become an em-dash.
        self.assertEqual(
            "0", render(FMT + "{{ fmt.measure(0) }}").strip()
        )

    def test_never_measured_renders_words_never_a_digit(self) -> None:
        html = render(
            FMT + "{{ fmt.measure(None, unknown='Not compared', "
            "reason='needs two collections in this scope') }}"
        )
        self.assertIn("hop-badge-unknown", html)      # slate, never green/red
        self.assertIn("Not compared", html)
        self.assertIn("needs two collections in this scope", html)
        self.assertNotRegex(html, r">\s*0\s*<")

    def test_a_ratio_reads_as_one_fact(self) -> None:
        self.assertEqual(
            "3 of 10",
            render(FMT + "{{ fmt.measure(3, of=10) }}").strip(),
        )

    def test_a_count_without_its_denominator_says_so(self) -> None:
        # The mirror-image case: measured, but the denominator is not
        # defensible. Reuses the resolution centre's exact vocabulary.
        self.assertEqual(
            "7 observed · denominator unavailable",
            render(FMT + "{{ fmt.measure(7, of='unavailable') }}").strip(),
        )

    def test_units_attach_to_the_number(self) -> None:
        self.assertEqual(
            "5 device(s)",
            render(FMT + "{{ fmt.measure(5, unit='device(s)') }}").strip(),
        )


class BasisTests(unittest.TestCase):
    """One provenance line per page; missing clauses are omitted."""

    def test_full_line(self) -> None:
        html = render(
            FMT + "{{ fmt.basis('Configuration verdicts', scope='Enterprise', "
            "at='2026-08-12T10:00:00+00:00', source='Starter Pack v1.0') }}"
        )
        self.assertIn("Configuration verdicts", html)
        self.assertIn("Enterprise", html)
        self.assertIn("as of", html)
        self.assertIn('datetime="2026-08-12T10:00:00+00:00"', html)  # via when()
        self.assertIn("Starter Pack v1.0", html)
        self.assertIn('class="muted page-basis"', html)

    def test_missing_clauses_are_omitted_not_empty(self) -> None:
        html = render(FMT + "{{ fmt.basis('Chronology') }}")
        self.assertIn("Chronology", html)
        self.assertNotIn("as of", html)
        self.assertNotIn("· ·", html)
        self.assertNotIn("None", html)


class AnswerBandTests(unittest.TestCase):
    """The verdict card language, extracted from Advisor."""

    def test_renders_the_shipped_verdict_language(self) -> None:
        html = render(
            ANSWER + "{{ answer.answer_band('warning', 'Attention required', "
            "'482 of 922 judged checks fail.', "
            "note='Score is passed ÷ judged.') }}"
        )
        self.assertIn("verdict-card verdict-warning", html)
        self.assertIn("verdict-chip verdict-chip-warning", html)
        self.assertIn("Attention required", html)
        self.assertIn('class="verdict-answer"', html)
        self.assertIn("482 of 922 judged checks fail.", html)
        # The qualifier that makes the headline honest is INSIDE the
        # band and always visible — never collapsed.
        self.assertIn("verdict-note", html)
        self.assertIn("Score is passed ÷ judged.", html)
        self.assertNotIn("<details", html)

    def test_caller_block_adds_badges_beside_the_chip(self) -> None:
        html = render(
            ANSWER
            + "{% call answer.answer_band('ok', 'Connected', 'A reaches B.') %}"
            + '<span class="badge hop-badge hop-badge-pass">Very-High</span>'
            + "{% endcall %}"
        )
        self.assertIn("hop-badge-pass", html)
        self.assertIn("Connected", html)

    def test_context_rows_render_as_definition_list(self) -> None:
        html = render(
            ANSWER + "{{ answer.answer_band('info', 'Answered', 'Fine.', "
            "context=[{'label': 'Scope', 'value': 'Enterprise'}]) }}"
        )
        self.assertIn("verdict-context", html)
        self.assertIn("<dt>Scope</dt>", html)
        self.assertIn("<dd>Enterprise</dd>", html)

    def test_tone_never_comes_from_readiness_for(self) -> None:
        # The blocker from the architecture review: readiness_for()
        # knows six HEALTH states and answers "Not enough evidence" for
        # everything else. The macro must not import or call it.
        source = (
            Path("src/founderos_atlas/web/templates/_answer.html")
            .read_text(encoding="utf-8")
        )
        self.assertNotIn("readiness_for(", source.replace("readiness_for()", ""))


class FilterChipsTests(unittest.TestCase):
    """Active-filter chips: collapsed never means hidden state."""

    CHIPS = (
        "{{ fmt.filter_chips(["
        "{'field': 'platform', 'value': 'FRRouting', 'href': '/x?y=1'},"
        "{'field': 'status', 'value': 'fail', 'href': '/x?platform=FRRouting'}"
        "], summary='2 of 50 record(s)', clear_href='/x') }}"
    )

    def test_chip_format_matches_the_evidence_original(self) -> None:
        html = render(FMT + self.CHIPS)
        # The pinned Evidence format: "field: value" with a removal ×.
        self.assertIn("platform: FRRouting", html)
        self.assertIn("status: fail", html)
        self.assertIn('class="filter-chip"', html)
        self.assertIn('aria-label="Remove filter platform: FRRouting"', html)
        self.assertIn('<span aria-hidden="true">×</span>', html)
        self.assertIn('role="group"', html)
        self.assertIn("2 of 50 record(s)", html)
        self.assertIn("Clear all", html)

    def test_no_chips_renders_nothing(self) -> None:
        html = render(FMT + "{{ fmt.filter_chips([]) }}")
        self.assertNotIn("filter-chip", html)


if __name__ == "__main__":
    unittest.main()
