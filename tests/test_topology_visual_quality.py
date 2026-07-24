"""Presentation-contract tests for a clear, scalable topology viewer."""

from __future__ import annotations

import unittest

from founderos_atlas.demo import run_atlas_discovery_demo
from founderos_atlas.visualization import TopologyRenderer


class TopologyVisualQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _, _, snapshot = run_atlas_discovery_demo()
        cls.html = TopologyRenderer(snapshot).render()

    def test_dom_and_canvas_share_an_explicit_typography_contract(self) -> None:
        self.assertIn('--font-sans:', self.html)
        self.assertIn('button, input, select, textarea { font: inherit; }', self.html)
        self.assertIn("'font-family': GRAPH_THEME.fontFamily", self.html)
        self.assertIn("'min-zoomed-font-size': 11", self.html)

    def test_render_density_is_supersampled_but_bounded(self) -> None:
        self.assertIn('const RENDER_PIXEL_RATIO = Math.min(', self.html)
        self.assertIn('Math.max(2, window.devicePixelRatio || 1)', self.html)
        self.assertIn('pixelRatio: RENDER_PIXEL_RATIO', self.html)
        self.assertNotIn('pixelRatio: Math.max(3', self.html)

    def test_semantic_zoom_replaces_collision_prone_font_growth(self) -> None:
        self.assertIn('const PEER_LABEL_ZOOM = 0.9', self.html)
        self.assertIn("node.label-suppressed", self.html)
        self.assertIn('syncSemanticZoom', self.html)
        self.assertNotIn('LABEL_MODEL_CAP', self.html)
        self.assertNotIn("cy.nodes().style('font-size'", self.html)

    def test_search_moves_small_result_sets_to_readable_focus(self) -> None:
        self.assertIn('cy.center(matches.closedNeighborhood())', self.html)
        self.assertIn('cy.fit(matches.closedNeighborhood(), 96)', self.html)
        self.assertIn('cy.zoom(Math.max(cy.zoom(), DETAIL_LABEL_ZOOM))', self.html)
        self.assertIn('? READABLE_DEVICE_ZOOM : READABLE_SITE_ZOOM', self.html)

    def test_viewer_preserves_graph_width_and_details_access(self) -> None:
        self.assertIn('id="details-toggle"', self.html)
        self.assertIn("window.matchMedia('(max-width: 1050px)')", self.html)
        self.assertIn('main.details-collapsed aside { display: none; }', self.html)
        self.assertIn('setDetailsOpen(false);', self.html)
        self.assertIn('revealDetails();', self.html)

    def test_full_topology_pans_at_a_readable_floor_instead_of_thumbnailing(self) -> None:
        """A large graph LANDS at a readable scale and pans, rather than
        auto-shrinking itself into an unreadable thumbnail.

        This once asserted the mechanism — cy.minZoom(floor) — but that
        clamp also froze the wheel, so an estate too big for one screen
        could never be seen whole (PR-110). The guarantee is about where
        the view lands; it is asserted here through the landing itself, and
        the clamp is asserted ABSENT so it cannot creep back.
        """

        self.assertIn('const READABLE_DEVICE_ZOOM = 0.86', self.html)
        self.assertIn('const READABLE_SITE_ZOOM = 0.84', self.html)
        self.assertIn('const needsPan = fittedZoom < floor;', self.html)
        self.assertIn('cy.zoom(floor);', self.html)
        self.assertIn('cy.center(elements);', self.html)
        self.assertNotIn('cy.minZoom(floor)', self.html)
        self.assertIn('applyReadableViewport(false);', self.html)
        self.assertIn('All devices (pan)', self.html)
        self.assertIn('id="viewport-hint"', self.html)
        self.assertNotIn('cy.fit(undefined, 40)', self.html)

    def test_sites_and_hostname_first_labels_are_the_default_density_model(self) -> None:
        self.assertIn("viewSelect.value = 'sites';", self.html)
        # Site clouds ring around the overview — now via the shared
        # siteRingSlots geometry rather than an inline skyline loop.
        self.assertIn("cy.nodes('[kind = \"site\"]')", self.html)
        self.assertIn('const angle = -Math.PI / 2', self.html)
        self.assertIn('radiusX * Math.cos(angle)', self.html)
        self.assertIn("'text-valign': 'center'", self.html)
        self.assertIn('display_label: site.label', self.html)
        self.assertIn("'label': 'data(label)'", self.html)
        self.assertIn('node.label-detailed', self.html)
        self.assertIn('const DETAIL_LABEL_ZOOM = 1.15', self.html)
        self.assertIn('if (matches.length !== 1) { return; }', self.html)

    def test_overview_never_invents_an_internet_centre(self) -> None:
        # An explicitly typed transit domain may take the centre — the
        # first, strongest signal, before any degree-based hub is even
        # considered (see siteRingSlots).
        self.assertIn("s.site_type === 'wan' || s.site_type === 'internet'", self.html)
        self.assertIn("transit.length === 1 && siteSet.has(transit[0].id)", self.html)

    def test_an_evidenced_hub_is_centred_but_a_mesh_is_not(self) -> None:
        """A site every other site reaches THROUGH is a hub, and drawing a
        star as a star is not inventing structure — it is the structure the
        links already show. The honesty guard: only when one site connects
        to a clear majority of the others and to strictly more than any
        rival. A full mesh has no hub, so none is chosen."""

        hub = self.html.split("if (!centre) {", 1)[1][:1300]
        self.assertIn("aggregated_edges", hub)
        # Majority-and-strictly-greatest, not mere maximum degree.
        self.assertIn("hubDeg >= Math.ceil(others * 0.6)", hub)
        self.assertIn("hubDeg > runnerUp", hub)

    def test_a_derived_cloud_shows_why_atlas_grouped_it(self) -> None:
        """A grouping the operator did not declare must explain itself —
        the convention it was read from, the AS its devices share — or it
        is an unexplained lump."""

        self.assertIn("How Atlas grouped this", self.html)
        self.assertIn("data.site_note", self.html)

    def test_opening_a_site_grows_it_in_place_not_into_a_column(self) -> None:
        """The reported complaint: opening a site scattered its devices
        into a band wedged alphabetically between other clouds. On one ring
        now, every site has a slot — a closed one shows its cloud there, an
        opened one clusters its devices there — so it grows where it stood."""

        self.assertIn("function siteRingSlots", self.html)
        expand = self.html.split("expandedSites.forEach(siteId =>", 1)[1][:600]
        # Devices packed around the site's OWN slot.
        self.assertIn("positions.get('site:' + siteId)", expand)
        self.assertIn("memberOf[n.data('id')] === siteId", expand)

    def test_the_ring_is_shared_by_the_closed_and_open_views(self) -> None:
        # A site must not move between shut and open, or opening reads as a
        # teleport rather than a growth. One geometry serves both.
        self.assertEqual(1, self.html.count("function siteRingSlots"))
        # Both the closed and the open branch call it.
        self.assertGreaterEqual(self.html.count("siteRingSlots("), 3)

    def test_edit_mode_never_mistakes_a_temporary_drag_for_a_saved_move(self) -> None:
        self.assertIn("node.drop-target", self.html)
        self.assertIn("const padding = 28", self.html)
        self.assertIn("Not saved: drop the device onto a different highlighted site cloud.", self.html)
        self.assertIn("Atlas could not be reached. The topology change was not saved.", self.html)
        self.assertIn("targetSiteId === '__none__'", self.html)
        self.assertIn("/api/topology/site-assignments/revert", self.html)
        self.assertIn("Return ${data.label} to automatic site identification?", self.html)

    def test_site_and_link_chrome_uses_thin_high_contrast_styles(self) -> None:
        self.assertIn("'line-color': GRAPH_THEME.physical, 'width': 1.5", self.html)
        self.assertIn("'line-color': GRAPH_THEME.routed, 'width': 1.35", self.html)
        self.assertIn("'border-width': 2, 'border-opacity': 1", self.html)
        self.assertNotIn('site.label.toUpperCase()', self.html)


if __name__ == "__main__":
    unittest.main()
