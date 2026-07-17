"""Acceptance tests for the shared UI foundation.

Responsive shell (collapsible navigation drawer), the shared SVG icon
system (no emoji in interface controls), design tokens, labelled
responsive tables, accessible names, shared timestamp formatting, and
supported Cytoscape style values in the topology viewer.
"""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from tests.test_polish import build_world


EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF☀-⛿✀-➿⬀-⯿■-◿]"
)

PRIMARY_PAGES = (
    "/", "/advisor", "/discovery", "/profiles", "/credentials",
    "/topology", "/predict", "/paths", "/compass", "/history",
    "/changes", "/incidents", "/settings",
)


class ResponsiveShellTests(unittest.TestCase):
    def test_every_page_carries_the_navigation_drawer_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            for path in PRIMARY_PAGES:
                page = client.get(path, follow_redirects=True).data.decode("utf-8")
                self.assertIn('id="atlas-nav-toggle"', page, path)
                self.assertIn('aria-expanded="false"', page, path)
                self.assertIn('aria-controls="atlas-sidebar"', page, path)
                self.assertIn('id="atlas-sidebar-backdrop"', page, path)

    def test_stylesheet_defines_the_drawer_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            css = client.get("/static/atlas.css").data.decode("utf-8")
            # Drawer behind a breakpoint; the toggle is hidden on desktop.
            self.assertIn("@media (max-width: 1024px)", css)
            self.assertIn("body.nav-open .sidebar", css)
            # Design tokens exist for future pages.
            for token in ("--accent:", "--radius:", "--space-4:", "--focus-ring:",
                          "--touch-target:", "--weight-semibold:"):
                self.assertIn(token, css)
            # Reduced motion is honored.
            self.assertIn("prefers-reduced-motion", css)
            # Visible focus and the skip link survive.
            self.assertIn(".skip-link:focus", css)
            self.assertIn(":focus-visible", css)
            # Touch targets reach 44px on coarse pointers.
            self.assertIn("pointer: coarse", css)

    def test_tables_scroll_in_labelled_regions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/topology?scope=all").data.decode("utf-8")
            self.assertIn('class="table-scroll" role="region"', page)
            self.assertIn('aria-label="Device inventory"', page)
            self.assertIn('tabindex="0"', page)


class IconSystemTests(unittest.TestCase):
    def test_navigation_and_actions_use_svg_outline_icons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/").data.decode("utf-8")
            self.assertIn('class="icon icon-discovery"', page)
            self.assertIn('stroke="currentColor"', page)
            self.assertIn('aria-hidden="true"', page)
            self.assertNotIn(".png", page)
            self.assertNotIn(".gif", page)

    def test_no_emoji_in_any_primary_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            for path in PRIMARY_PAGES:
                page = client.get(path, follow_redirects=True).data.decode("utf-8")
                match = EMOJI_PATTERN.search(page)
                self.assertIsNone(
                    match, f"{path} still renders emoji {match.group(0) if match else ''!r}"
                )


class AccessibleNameTests(unittest.TestCase):
    def test_row_action_buttons_carry_specific_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/profiles").data.decode("utf-8")
            self.assertIn('aria-label="Run discovery for Hyderabad"', page)
            self.assertIn('aria-label="Edit Hyderabad"', page)
            self.assertIn('aria-label="Delete Hyderabad"', page)

    def test_search_dialog_is_a_modal_with_named_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get("/").data.decode("utf-8")
            self.assertIn('role="dialog" aria-modal="true"', page)
            self.assertIn('aria-label="Enterprise search"', page)
            self.assertIn("Skip to content", page)
            # The main landmark can receive skip-link focus.
            self.assertIn('id="atlas-main" tabindex="-1"', page)


class FormattingTests(unittest.TestCase):
    def test_timestamp_filter_formats_iso_and_passes_through_other_text(self) -> None:
        from founderos_atlas.web.models import format_timestamp

        self.assertEqual("09-Jul-2026 23:41", format_timestamp("2026-07-09T23:41:18+00:00"))
        self.assertEqual("already formatted", format_timestamp("already formatted"))
        self.assertEqual("never", format_timestamp(None))

    def test_templates_render_time_elements_with_precise_tooltips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/topology?scope=all").data.decode("utf-8")
            match = re.search(r'<time datetime="([^"]+)" title="\1">([^<]+)</time>', page)
            self.assertIsNotNone(match, "topology should render <time> with a precise tooltip")
            self.assertIn("-", match.group(2))  # DD-Mon-YYYY display format

    def test_risk_and_confidence_are_always_labelled(self) -> None:
        # The "low High (75%)" defect: a bare risk badge next to a bare
        # confidence band. Both values must carry their own label.
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/").data.decode("utf-8")
            for badge in re.findall(r'class="badge hop-badge[^"]*">([^<]+)<', page):
                if badge.strip().lower() in ("low", "medium", "high", "critical"):
                    self.fail(f"unlabelled risk badge {badge!r} — use fmt.risk_badge")


class TopologyViewerTests(unittest.TestCase):
    TEMPLATE = (
        Path(__file__).resolve().parents[1]
        / "src" / "founderos_atlas" / "visualization" / "templates" / "topology.html"
    )

    def test_only_supported_cytoscape_font_weights(self) -> None:
        text = self.TEMPLATE.read_text(encoding="utf-8")
        for value in re.findall(r"'font-weight':\s*(\d+)", text):
            self.assertIn(int(value), range(100, 1000, 100),
                          f"Cytoscape rejects font-weight {value}")
        self.assertNotIn("650", text)

    def test_viewer_offers_a_keyboard_alternative_and_handles_resize(self) -> None:
        text = self.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('id="node-list"', text)
        self.assertIn("keyboard alternative", text.lower())
        self.assertIn("addEventListener('resize'", text)
        self.assertIn("prefers-reduced-motion", text)
        # The details panel is never display:none'd away on small screens.
        self.assertNotIn("aside { display: none; }", text)

    def test_rendered_viewer_carries_the_fixes(self) -> None:
        from founderos_atlas.demo import run_atlas_discovery_demo
        from founderos_atlas.visualization.renderer import TopologyRenderer

        _, _, snapshot = run_atlas_discovery_demo()
        html = TopologyRenderer(snapshot).render()
        self.assertIn("'font-weight': 600", html)
        self.assertNotIn("font-weight: 650", html)
        self.assertIn('id="node-list"', html)


if __name__ == "__main__":
    unittest.main()
