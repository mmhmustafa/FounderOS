"""Protocol regions on the whole-estate view.

A soft tint behind the devices sharing an OSPF area or a BGP AS, so the
control-plane boundaries are readable without leaving the diagram.

The design constraint that shapes the whole feature: a region must never
enclose a device that is not in it. A convex hull around scattered
members swallows whatever sits between them, and the map would then be
asserting a membership the evidence does not support — the one thing
this viewer must never do. Each region is therefore the union of a disc
per member and a capsule along each member-to-member link, a shape that
follows the actual membership and cannot enclose a non-member.
"""

from __future__ import annotations

from pathlib import Path
import unittest

VIEWER = (
    Path(__file__).resolve().parents[1]
    / "src/founderos_atlas/visualization/templates/topology.html"
)
SOURCE = VIEWER.read_text(encoding="utf-8")
BLOCK = SOURCE.split("function protocolRegions()", 1)[1].split(
    "-- Per-user hidden devices", 1
)[0]


class LayerPlumbingTests(unittest.TestCase):
    def test_the_region_layer_is_its_own_top_level_block(self) -> None:
        """Appending it inside another feature's IIFE is how a viewer
        addition silently never runs — that exact mistake cost a
        debugging round on the row-selection work."""

        self.assertIn("(function protocolRegions() {", SOURCE)

    def test_it_paints_beneath_every_cytoscape_canvas(self) -> None:
        # A tint drawn ON TOP would grey out the devices it describes.
        self.assertIn("Math.min.apply(null, zIndexes", BLOCK)
        self.assertIn("insertBefore(canvas, container.firstChild)", BLOCK)

    def test_the_overlay_never_swallows_clicks(self) -> None:
        self.assertIn("canvas.style.pointerEvents = 'none'", BLOCK)

    def test_the_layer_has_a_toggle(self) -> None:
        self.assertIn('data-layer="protocolRegions"', SOURCE)


class HonestShapeTests(unittest.TestCase):
    def test_it_is_not_a_convex_hull(self) -> None:
        """The rejected design. A hull is the obvious way to draw a
        region and the reason it is wrong is not obvious, so the absence
        is worth pinning."""

        for banned in ("convexHull", "convex_hull", "grahamScan", "hull("):
            self.assertNotIn(banned, BLOCK)

    def test_a_region_is_discs_plus_capsules(self) -> None:
        self.assertIn("arc(", BLOCK)          # a disc per member
        self.assertIn("addCapsule", BLOCK)    # a capsule per member link

    def test_a_capsule_only_ever_joins_two_members(self) -> None:
        """Joining a member to a non-member would drag the region over a
        device that does not belong to it."""

        self.assertIn("if (!byId[other.id()]", BLOCK)

    def test_each_region_is_filled_once(self) -> None:
        """Overlapping sub-shapes filled separately would darken where
        they cross, reading as a stronger claim in the middle of a
        region than at its edge."""

        self.assertIn("'nonzero'", BLOCK)
        self.assertEqual(1, BLOCK.count("ctx.fill(path"))

    def test_hidden_devices_are_not_given_a_region(self) -> None:
        # "Remove from my view" must not leave a tint where the device was.
        self.assertIn("node.style('display') !== 'none'", BLOCK)
        self.assertIn("edge.style('display') === 'none'", BLOCK)


class ScopeTests(unittest.TestCase):
    def test_regions_are_drawn_only_on_the_whole_estate_view(self) -> None:
        """The OSPF and BGP views already draw these domains as boxes and
        the site view has its own; tinting there would double the same
        statement in two visual languages."""

        self.assertIn("if (mode !== 'full' || !regionsEnabled())", BLOCK)

    def test_the_canvas_is_cleared_before_the_scope_check(self) -> None:
        """Leaving the previous view's tint on screen after switching is
        the failure this ordering prevents."""

        cleared = BLOCK.index("ctx.clearRect")
        guarded = BLOCK.index("if (mode !== 'full'")
        self.assertLess(cleared, guarded)

    def test_it_redraws_as_the_graph_moves(self) -> None:
        self.assertIn("cy.on('render', draw)", BLOCK)


if __name__ == "__main__":
    unittest.main()
