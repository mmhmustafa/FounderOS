"""Row action menus (PR-178.1): native disclosure, and a menu you can see.

Two defects measured on the live estate, and the contracts that keep
them fixed:

1. The trigger carried ``role="button"`` + ``aria-haspopup="menu"`` with
   none of the rest of the ARIA menu pattern — discarding the
   expanded/collapsed state a native ``<details>`` announces for free.
   The decision (adversarial review §9) is NATIVE DISCLOSURE: no role
   override, no aria-haspopup, and deliberately NO arrow-key navigation
   — arrow keys are the ARIA-menu expectation, and adding them to a
   disclosure builds exactly the half-menu the pattern rules forbid.

2. The list is ``position: absolute`` inside ``.table-scroll``
   (``overflow-x: auto``), and an absolutely positioned box cannot
   escape an overflow ancestor on its containing-block chain — a
   last-row menu rendered 570px of unreachable items, and at 375px it
   opened entirely outside the viewport. Proven by hit test: only
   ``position: fixed`` paints outside the scroller. The enhancement
   switches the OPEN list to fixed at viewport-clamped coordinates,
   closes on any scroll, and resets on close. CSS keeps ``absolute`` so
   the no-JS baseline is exactly today's behaviour.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/founderos_atlas/web/static"
TEMPLATES = ROOT / "src/founderos_atlas/web/templates"


class MenuSemanticsTests(unittest.TestCase):
    """Native disclosure, whole — not half of two patterns."""

    def test_no_action_menu_summary_overrides_its_native_role(self) -> None:
        """role="button" on an action-menu <summary> silences the
        expanded/collapsed announcement the element makes natively.

        Scoped to ``details.action-menu`` — the row action menus this PR
        owns. (Seven non-menu disclosure summaries elsewhere carry a
        plain role="button" with no menu claim; they are a separate,
        lesser residual, recorded in the handover, not silently fixed
        here.)"""

        offenders = []
        for path in sorted(TEMPLATES.glob("*.html")):
            body = path.read_text(encoding="utf-8")
            for match in re.finditer(
                r'<details class="action-menu">.*?(<summary[^>]*>)',
                body, re.DOTALL,
            ):
                summary_tag = match.group(1)
                if "role=" in summary_tag:
                    offenders.append(f"{path.name}: {summary_tag[:60]}")
        self.assertEqual([], offenders, "action-menu summaries must keep native semantics")

    def test_no_incomplete_aria_menu_semantics_remain(self) -> None:
        """aria-haspopup promises an ARIA menu; the list is ordinary
        links inside a disclosure. Promise nothing you don't deliver.
        (Attribute form only — prose in comments may name the thing.)"""

        offenders = []
        for path in sorted(TEMPLATES.glob("*.html")):
            body = path.read_text(encoding="utf-8")
            if "aria-haspopup=" in body:
                offenders.append(f"{path.name}: aria-haspopup")
            if 'role="menu"' in body or 'role="menuitem"' in body:
                offenders.append(f"{path.name}: role=menu(item)")
        self.assertEqual([], offenders)

    def test_the_trigger_keeps_its_row_aware_accessible_name(self) -> None:
        macro = (TEMPLATES / "_entity_actions.html").read_text(encoding="utf-8")
        self.assertIn('aria-label="{{ label }} for {{ name }}"', macro)
        changes = (TEMPLATES / "changes.html").read_text(encoding="utf-8")
        self.assertIn(
            'aria-label="Actions for this change on', changes,
            "the hand-rolled Changes menu keeps its row-aware name",
        )

    def test_no_arrow_key_navigation_was_added_to_the_disclosure(self) -> None:
        """Arrow keys are the ARIA-menu expectation. A disclosure of
        links navigates by Tab; adding arrows would rebuild the
        forbidden half-menu. The menu enhancement section must not
        touch Arrow keys (Ctrl+K search legitimately does, below it)."""

        js = (STATIC / "atlas.js").read_text(encoding="utf-8")
        menu_section = js.split("-- Entity action menus")[1].split(
            "-- Responsive navigation drawer"
        )[0]
        self.assertNotIn("Arrow", menu_section)
        self.assertNotIn("roving", menu_section)
        self.assertNotIn("tabindex", menu_section)

    def test_escape_and_outside_click_still_close_and_single_open_holds(self) -> None:
        js = (STATIC / "atlas.js").read_text(encoding="utf-8")
        # One close implementation, called from Escape, outside click,
        # and the scroll-close below.
        self.assertIn("var closeMenus = function (except)", js)
        self.assertIn('document.querySelectorAll("details.action-menu[open]")', js)
        self.assertIn('} else if (event.key === "Escape") {', js)
        self.assertIn("closeMenus(null);", js)


class MenuPositioningTests(unittest.TestCase):
    """The open list escapes the scroll container — by position:fixed,
    set by JS, never by CSS alone (which cannot do it)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (STATIC / "atlas.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "atlas.css").read_text(encoding="utf-8")

    def test_css_keeps_absolute_as_the_no_js_baseline(self) -> None:
        """position:fixed in the stylesheet would anchor a no-JS menu to
        the viewport with auto offsets — it must only ever be applied by
        the script, on open."""

        match = re.search(
            r"^\.action-menu-list \{(.*?)\}", self.css, re.MULTILINE | re.DOTALL
        )
        self.assertIsNotNone(match, "the .action-menu-list rule must exist")
        self.assertIn("position: absolute", match.group(1))
        self.assertNotIn("fixed", match.group(1))

    def test_the_open_list_switches_to_fixed(self) -> None:
        self.assertIn('list.style.position = "fixed";', self.js)

    def test_the_switch_hangs_off_the_toggle_event_in_capture(self) -> None:
        # toggle does not bubble; only capture reaches it document-wide.
        self.assertIn('document.addEventListener("toggle", function (event) {', self.js)
        match = re.search(
            r'addEventListener\("toggle",.*?\}, true\);', self.js, re.DOTALL
        )
        self.assertIsNotNone(match, "toggle listener must use capture")

    def test_coordinates_are_viewport_clamped_and_flip(self) -> None:
        """Right-aligned to the trigger, flipped upward at the bottom
        edge, clamped inside both viewport axes."""

        self.assertIn("document.documentElement.clientWidth", self.js)
        self.assertIn("document.documentElement.clientHeight", self.js)
        self.assertIn("anchor.right - size.width", self.js)
        self.assertIn("anchor.top - gap - size.height", self.js)

    def test_scroll_closes_the_menu_rather_than_tracking_it(self) -> None:
        """A fixed list no longer follows its trigger. Capture catches
        the page AND every inner scroll container (.table-scroll)."""

        match = re.search(
            r'addEventListener\("scroll",.*?closeMenus\(\);.*?\}, true\);',
            self.js, re.DOTALL,
        )
        self.assertIsNotNone(match)

    def test_close_resets_every_inline_style_it_set(self) -> None:
        """A reopened menu must start from the stylesheet, not from the
        previous open's coordinates."""

        reset = self.js.split("var resetMenuList")[1].split("};")[0]
        for prop in ("position", "top", "left", "right", "width"):
            self.assertIn(f'list.style.{prop} = "";', reset)

    def test_the_width_is_locked_before_the_switch(self) -> None:
        """position:fixed re-resolves shrink-to-fit against the
        viewport; locking the measured width prevents reflow mid-open."""

        self.assertIn('list.style.width = size.width + "px";', self.js)

    def test_the_scroll_containers_keep_their_overflow(self) -> None:
        """The fix must not be 'remove overflow-x' — tables still scroll
        inside their region at every width."""

        self.assertIn("overflow-x: auto", self.css.split(".table-scroll {")[1].split("}")[0])


class NoJsBaselineTests(unittest.TestCase):
    def test_the_menu_is_server_rendered_and_complete_without_js(self) -> None:
        """The macro emits the full closed <details> — no template, no
        clone-on-open, nothing the script must build for the menu to
        exist. (On-demand DOM was explicitly rejected: adversarial
        review §11.)"""

        macro = (TEMPLATES / "_entity_actions.html").read_text(encoding="utf-8")
        self.assertIn("<details class=\"action-menu\">", macro)
        self.assertIn("<ul class=\"action-menu-list\">", macro)
        self.assertNotIn("<template", macro)
        js = (STATIC / "atlas.js").read_text(encoding="utf-8")
        self.assertNotIn("cloneNode", js.split("-- Entity action menus")[1].split(
            "-- Responsive navigation drawer")[0])


if __name__ == "__main__":
    unittest.main()
