"""What the discovery panel says about a sweep.

A run over a /24 holding twelve devices reported "Addresses contacted:
12" and nothing else. Every number needed to explain that was already
recorded — 254 swept, 12 answered, 242 silent, 0 refused — and none of
it reached the screen, so a correct result read as a failure and took a
dig through the history file to explain.

The distinction the codebase already draws is kept: a silent address is
COVERAGE (there is no device there), a refused credential is a PROBLEM.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / "src/founderos_atlas/web"
TEMPLATE = (ROOT / "templates/discovery.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "static/atlas.js").read_text(encoding="utf-8")


class ProgressLabelTests(unittest.TestCase):
    def test_the_live_counter_keeps_its_audited_label(self) -> None:
        """"Addresses contacted" is correct and deliberate: the counter
        is fed by _on_connect(host), so it counts ADDRESSES Atlas
        connected to, not devices — which is why an earlier audit
        (FINDING 3, tests/test_discovery_audit.py) separated it from the
        summary's canonical "Devices discovered".

        Renaming it to "Devices answering" during this change was wrong
        and that audit caught it. The label was never the problem; the
        missing denominator was.
        """

        self.assertIn(
            '<span>Addresses contacted</span><span id="job-devices">',
            TEMPLATE,
        )


class SweepSummaryTests(unittest.TestCase):
    def test_the_summary_carries_the_denominator(self) -> None:
        self.assertIn('id="summary-sweep"', TEMPLATE)
        self.assertIn("Addresses swept", TEMPLATE)

    def test_silence_is_worded_as_coverage_not_failure(self) -> None:
        """245 quiet addresses on a swept /24 is the right answer, not a
        fault. Wording them as failures is what made an operator chase a
        non-problem."""

        self.assertIn("silent (no device answered)", TEMPLATE)
        self.assertIn("silent (no device answered)", SCRIPT)
        for word in ("failed", "unreachable", "error"):
            self.assertNotIn(
                f"{word} (no device", TEMPLATE.lower(),
                "a silent address must not be described as a failure",
            )

    def test_a_refused_credential_is_kept_separate(self) -> None:
        # The one case that IS worth an operator's attention.
        self.assertIn("refused credentials", TEMPLATE)
        self.assertIn("refused credentials", SCRIPT)

    def test_the_script_renders_the_same_facts_as_the_template(self) -> None:
        """The panel is server-rendered on load and updated live by the
        script; the two drifting apart is how a page starts telling two
        stories."""

        self.assertIn("sweepSummary", SCRIPT)
        for field in (
            "addresses_scanned",
            "addresses_without_device",
            "auth_failed_devices",
        ):
            self.assertIn(field, SCRIPT, f"script ignores {field}")
            self.assertIn(field, TEMPLATE, f"template ignores {field}")

    def test_a_run_that_recorded_no_sweep_says_nothing(self) -> None:
        """Older runs carry no sweep statistics. Saying nothing beats
        inventing a denominator."""

        block = SCRIPT.split("function sweepSummary", 1)[1][:400]
        self.assertIn('return "—"', block)


class SummaryFieldPlumbingTests(unittest.TestCase):
    def test_the_route_supplies_every_field_the_panel_shows(self) -> None:
        routes = (ROOT / "routes.py").read_text(encoding="utf-8")
        block = routes.split('"configurations_collected": record', 1)[1][:1200]
        for field in (
            "addresses_scanned",
            "addresses_without_device",
            "auth_failed_devices",
        ):
            self.assertIn(field, block, f"summary never carries {field}")


if __name__ == "__main__":
    unittest.main()
