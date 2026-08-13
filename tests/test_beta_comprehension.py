"""Comprehension and reach (PR-180 Step 6).

Measured residues, each pinned here: the topology legend was
display:none at the `simple` level — exactly the level a fresh
workspace gives a first-time tester; the header counted unresolved
peers while the layer drawing them ships off; the canonical count
definitions lived only in title= on non-focusable divs and the page
said "hover any tile"; _device_actions.html kept computed reasons in
title= on a disabled (untabbable) control; seven <summary> elements
carried role="button", destroying the disclosure announcement; the
Ctrl+K selection was a ~1.1:1 tint; and the two sub-24px touch targets
(grid checkboxes, .chip-remove) were in no coarse-pointer rule.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / "src" / "founderos_atlas"
VIEWER = (ROOT / "visualization" / "templates" / "topology.html").read_text(
    encoding="utf-8"
)
TEMPLATES = ROOT / "web" / "templates"
CSS = (ROOT / "web" / "static" / "atlas.css").read_text(encoding="utf-8")


class TopologyViewerTests(unittest.TestCase):
    def test_the_legend_is_reachable_at_simple(self) -> None:
        # A <details> that the level script CLOSES at simple — never
        # display:none, which left first-time testers with dashed and
        # dotted lines and no key anywhere on screen.
        self.assertIn('<details id="legend" aria-label="Legend" open>',
                      VIEWER)
        self.assertIn("<summary>Legend</summary>", VIEWER)
        self.assertNotIn(
            'body[data-level="simple"] #legend { display: none; }', VIEWER
        )
        self.assertIn("legend.removeAttribute('open')", VIEWER)

    def test_the_unresolved_state_derives_from_the_live_checkbox(self) -> None:
        self.assertIn('id="unresolved-note"', VIEWER)
        self.assertIn("unresolvedNote.textContent = unresolvedBox.checked",
                      VIEWER)
        self.assertIn("not drawn until switched on", VIEWER)

    def test_the_summary_title_uses_a_property_assignment(self) -> None:
        self.assertIn(
            "document.getElementById('summary').title = "
            "snapshotSummary.unresolved_definition",
            VIEWER,
        )

    def test_the_zoom_tuning_is_untouched(self) -> None:
        # PR-180 explicitly changes nothing here; the arithmetic
        # comment and the tuned value must survive this PR byte-alike.
        self.assertIn("wheelSensitivity: 0.15", VIEWER)
        self.assertIn("maxZoom: 3", VIEWER)
        self.assertIn("const MIN_ZOOM = 0.05;", VIEWER)

    def test_the_renderer_ships_the_canonical_definition(self) -> None:
        from founderos_atlas.demo import run_atlas_discovery_demo
        from founderos_atlas.topology.vocabulary import DEFINITIONS
        from founderos_atlas.visualization import TopologyRenderer

        _result, _graph, snapshot = run_atlas_discovery_demo()
        html = TopologyRenderer(snapshot).render()
        self.assertIn("unresolved_definition", html)
        self.assertIn(
            DEFINITIONS["unresolved_peer_identities"].split(".")[0], html
        )


class WebTemplateReachTests(unittest.TestCase):
    def test_tile_definitions_have_an_accessible_home(self) -> None:
        body = (TEMPLATES / "_topology_facts.html").read_text(encoding="utf-8")
        self.assertIn("<summary>Canonical definitions</summary>", body)
        self.assertNotIn("hover any tile", body)

    def test_the_site_filter_states_its_active_entry(self) -> None:
        body = (TEMPLATES / "topology.html").read_text(encoding="utf-8")
        self.assertIn('aria-current="true"', body)

    def test_device_action_reasons_reach_assistive_tech(self) -> None:
        body = (TEMPLATES / "_device_actions.html").read_text(encoding="utf-8")
        # The disabled Web button is out of the tab order — its title
        # can never fire; the reason rides a visually-hidden span.
        self.assertIn(
            '<span class="visually-hidden"> — {{ web.reason }}</span>', body
        )
        self.assertIn(
            '<span class="visually-hidden"> — {{ target.reason }}</span>',
            body,
        )
        self.assertIn("certificate: {{ web.certificate_warnings", body)

    def test_no_summary_overrides_its_disclosure_role(self) -> None:
        # role="button" on <summary> strips the expanded/collapsed
        # announcement. The audit predicted one instance; seven
        # existed. Zero remain, and this sweep keeps it that way.
        offenders = [
            path.name
            for path in sorted(TEMPLATES.glob("*.html"))
            if re.search(r"<summary[^>]*role=\"button\"",
                         path.read_text(encoding="utf-8"))
        ]
        self.assertEqual([], offenders)


class ChromeCssTests(unittest.TestCase):
    def test_the_two_small_targets_join_the_coarse_block(self) -> None:
        self.assertIn(
            '.grid input[type="checkbox"] { width: var(--control-height-sm); '
            "height: var(--control-height-sm); }",
            CSS,
        )
        self.assertIn(
            ".chip-remove { min-width: var(--control-height-sm); "
            "min-height: var(--control-height-sm); }",
            CSS,
        )

    def test_the_dead_selector_is_gone(self) -> None:
        self.assertNotIn('input[type="checkbox"] + span', CSS)

    def test_ctrl_k_selection_is_not_colour_alone(self) -> None:
        self.assertIn(
            ".search-result.active { background: var(--accent-soft); "
            "box-shadow: inset 3px 0 0 var(--accent); }",
            CSS,
        )

    def test_the_search_input_regains_a_focus_indicator(self) -> None:
        self.assertIn(
            ".search-panel input:focus-visible { outline: none; "
            "box-shadow: inset 0 -2px 0 var(--accent); }",
            CSS,
        )


if __name__ == "__main__":
    unittest.main()
