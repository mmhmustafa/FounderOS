"""PR-174.1 — the topology wheel zoom is gradual, and stays that way.

The regression these tests pin: ``wheelSensitivity: 0.15`` (tuned in
PR-117) was deleted by ``096f630``, restoring Cytoscape's default of 1
— which, through its ``zoom × 10^(deltaY/−250 × sensitivity)`` wheel
formula, makes one 100-pixel notch a 2.512× jump and crosses the whole
0.05–3 zoom range in ~4.5 notches. The deletion survived because the
replacement comment argued taste; these tests argue arithmetic, against
the value parsed OUT OF THE SHIPPED TEMPLATE — never a duplicated
constant that could drift from what ships.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "src" / "founderos_atlas" / "visualization" / "templates"
    / "topology.html"
)


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _shipped_sensitivity(text: str) -> float:
    match = re.search(r"wheelSensitivity:\s*([0-9.]+)", text)
    if match is None:
        raise AssertionError(
            "wheelSensitivity is missing from the cytoscape options — "
            "this is the exact deletion (096f630) PR-174.1 exists to "
            "prevent recurring; one wheel notch is now a 2.512× jump."
        )
    return float(match.group(1))


def _notch_factor(sensitivity: float, delta_y: float,
                  delta_mode: int = 0) -> float:
    """Cytoscape's own wheel formula, from the bundled renderer:
    ``s = deltaY / -250; s *= wheelSensitivity;
    if (deltaMode === 1) s *= 33; zoom *= 10 ** s`` — evaluated here so
    the assertion tests what the shipped value DOES, not what it is."""

    step = delta_y / -250.0
    step *= sensitivity
    if delta_mode == 1:
        step *= 33.0
    return 10.0 ** step


class WheelSensitivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _template()
        cls.sensitivity = _shipped_sensitivity(cls.html)

    # T1 — the headline: the deleted line cannot be deleted again.
    def test_the_option_is_present_and_in_the_sane_band(self) -> None:
        self.assertGreaterEqual(self.sensitivity, 0.05)
        self.assertLessEqual(self.sensitivity, 0.35)

    # T2 — the comment records measured consequences, not preferences.
    def test_the_comment_argues_arithmetic_not_taste(self) -> None:
        for fact in ("2.512", "4.5 notches", "PR-117", "096f630",
                     "10^(deltaY/"):
            with self.subTest(fact=fact):
                self.assertIn(fact, self.html)

    # T3 — one physical notch is a small, bounded change.
    def test_one_notch_is_gradual(self) -> None:
        factor = _notch_factor(self.sensitivity, -100)
        self.assertGreaterEqual(factor, 1.05)
        self.assertLessEqual(factor, 1.30)

    # T4 — repeated notches progress gradually.
    def test_three_notches_stay_bounded(self) -> None:
        factor = _notch_factor(self.sensitivity, -300)
        self.assertLess(factor, 1.6)

    # T5 — trackpad-sized deltas remain smooth.
    def test_trackpad_deltas_are_smooth(self) -> None:
        self.assertLess(_notch_factor(self.sensitivity, -4), 1.02)

    # T6 — Firefox's line mode lands beside Chrome's pixel mode.
    def test_delta_modes_are_normalised(self) -> None:
        pixel = _notch_factor(self.sensitivity, -100, delta_mode=0)
        lines = _notch_factor(self.sensitivity, -3, delta_mode=1)
        self.assertLess(abs(lines - pixel) / pixel, 0.05)

    # T7 — one authoritative zoom path: no manual wheel handler may
    # ever sit beside Cytoscape's, or the same event zooms twice.
    def test_no_custom_wheel_handler_exists(self) -> None:
        for marker in ("addEventListener('wheel'",
                       'addEventListener("wheel"',
                       "onwheel", "mousewheel"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.html)

    # T8 — the listener count cannot grow: one instance, never
    # destroyed and recreated with different options.
    def test_one_cytoscape_instance_no_recreation(self) -> None:
        self.assertEqual(1, self.html.count("cytoscape({"))
        self.assertEqual(0, self.html.count("cy.destroy("))

    # T9 — the zoom limits are untouched.
    def test_zoom_limits_are_unchanged(self) -> None:
        self.assertIn("const MIN_ZOOM = 0.05", self.html)
        self.assertIn("minZoom: MIN_ZOOM", self.html)
        self.assertIn("maxZoom: 3", self.html)

    # T10 — the other zoom controls are exactly as they were.
    def test_stepped_controls_and_views_are_unchanged(self) -> None:
        self.assertIn("var STEP = 1.25;", self.html)
        self.assertIn('id="zoom-in"', self.html)
        self.assertIn('id="zoom-out"', self.html)
        self.assertIn('id="fit"', self.html)
        self.assertIn('id="zoom-all"', self.html)
        self.assertIn('id="magnifier-toggle"', self.html)
        # And the wheel stays FINER than the stepped buttons — the
        # relationship, not just the two numbers.
        self.assertLess(_notch_factor(self.sensitivity, -100), 1.25)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
