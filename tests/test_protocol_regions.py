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

    def test_the_layer_never_takes_a_negative_index(self) -> None:
        """The bug that made the whole feature invisible on first
        release. #cy is position:relative with z-index:auto, so it is not
        a stacking context — a negative index on a child does not put it
        behind the GRAPH, it puts it behind the nearest ancestor that IS
        a stacking context, and #cy's opaque white background then covers
        it. The tint was being drawn perfectly and painted underneath a
        white box for an entire session.

        Cytoscape's canvases sit at 1/2/3, so zero is both below them and
        above the container's background.
        """

        self.assertIn("Math.max(floor - 1, 0)", BLOCK)

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

    def test_a_circle_is_used_only_when_it_encloses_no_outsider(self) -> None:
        """A plain circle reads as ONE region where the union of discs
        reads as a cluster of blobs, so the circle is preferred — but it
        is only honest when nothing else falls inside it. The check is
        what separates this from the convex hull rejected above: a hull
        is fitted and then swallows whatever lies between the members,
        this circle is rejected the moment it covers a non-member.
        """

        self.assertIn("enclosingCircle(members, padding)", BLOCK)
        self.assertIn("if (!enclosesOutsider(circle, byId))", BLOCK)

    def test_the_outsider_check_uses_the_device_extent(self) -> None:
        """Centre-only would let a device sit half inside the tint and
        still pass, and half-covered reads as membership."""

        outsider = SOURCE.split("function enclosesOutsider", 1)[1][:700]
        self.assertIn("renderedWidth()", outsider)
        self.assertIn("- reach < circle.r", outsider)

    def test_a_region_is_discs_plus_capsules(self) -> None:
        self.assertIn("arc(", BLOCK)          # a disc per member
        self.assertIn("addCapsule", BLOCK)    # a capsule per member link

    def test_a_capsule_only_ever_joins_two_members(self) -> None:
        """Joining a member to a non-member would drag the region over a
        device that does not belong to it."""

        self.assertIn("if (!byId[other.id()]", BLOCK)

    def test_a_capsule_winds_with_the_discs_so_the_fill_has_no_holes(self) -> None:
        """The union is filled with the nonzero rule, which counts SIGNED
        winding. A capsule wound the opposite way to the disc arcs cancelled
        their winding where the two overlap, so nonzero left a white hole in
        the lens at every node a capsule meets — worst at the core, where
        several converge. The capsule must trace the same rotational sense
        as the arcs (from+n -> from-n -> to-n -> to+n) so the counts ADD to
        a solid fill instead of cancelling.
        """

        capsule = SOURCE.split("function addCapsule", 1)[1][:900]
        order = [
            capsule.index("from.x + nx"),
            capsule.index("from.x - nx"),
            capsule.index("to.x - nx"),
            capsule.index("to.x + nx"),
        ]
        self.assertEqual(order, sorted(order),
                         "capsule vertices must be from+n, from-n, to-n, to+n")

    def test_each_shape_is_filled_once(self) -> None:
        """Overlapping sub-shapes filled separately would darken where
        they cross, reading as a stronger claim in the middle of a
        region than at its edge. One fill per drawing path: the OSPF
        region and the BGP fabric, each a single merged fill."""

        self.assertIn("'nonzero'", BLOCK)
        self.assertEqual(2, BLOCK.count("ctx.fill(path"))

    def test_hidden_devices_are_not_given_a_region(self) -> None:
        # "Remove from my view" must not leave a tint where the device was.
        self.assertIn("node.style('display') !== 'none'", BLOCK)
        self.assertIn("edge.style('display') === 'none'", BLOCK)


class BgpFabricTests(unittest.TestCase):
    """BGP answers a different question from OSPF. An OSPF area is a
    region — "these devices share an area". BGP's question is "who peers
    with whom", so its ASes are drawn as distinct circles tied together
    by a ribbon along each observed session, never merged into one shape
    that would claim a single AS.
    """

    FABRIC = SOURCE.split("function drawBgpFabric", 1)[1].split(
        "function draw()", 1
    )[0]

    def test_bgp_is_drawn_as_a_fabric_not_as_regions(self) -> None:
        self.assertIn("drawBgpFabric(ctx, routingView.bgp.groups", BLOCK)
        self.assertIn("drawRegion(ctx, 'ospf', group)", BLOCK)

    def test_the_ribbon_traces_a_real_session(self) -> None:
        """A ribbon where there is no session would invent a peering.
        Membership in an AS is not a session — the edge must be one."""

        self.assertIn("if (!isBgpEdge(edge))", self.FABRIC)

    def test_bgp_evidence_is_read_past_the_relationship_type(self) -> None:
        """The mesh between edge routers is typed "verified-routed"; the
        BGP evidence rides on bgp_health / protocols. Keying only on
        relationship would draw an empty fabric — exactly what happened
        the first time."""

        finder = SOURCE.split("function isBgpEdge", 1)[1][:500]
        self.assertIn("bgp_health", finder)
        self.assertIn("protocols", finder)

    def test_the_ribbon_only_ever_joins_two_ases(self) -> None:
        # Joining a member to a non-member would drag the tint onto a
        # device that speaks no BGP.
        self.assertIn("if (!byId[other.id()]", self.FABRIC)

    def test_the_ribbon_is_thinner_than_a_member_disc(self) -> None:
        """It must read as a connection between ASes, not a region of its
        own — a full-width capsule would look like one merged AS."""

        self.assertIn("PEER_HALF_WIDTH", self.FABRIC)

    def test_each_as_keeps_its_own_caption(self) -> None:
        # The ribbon says they peer; the labels say they are different
        # autonomous systems. Dropping the labels is what made four
        # distinct ASes read as one anonymous purple blob.
        self.assertIn("label(ctx, 'bgp', group.label, anchor)", self.FABRIC)


class ReadabilityTests(unittest.TestCase):
    def test_every_region_is_captioned(self) -> None:
        """Shipped without this, the layer was four blue shapes and four
        purple ones with nothing saying which area or which AS — the
        operator's first reaction was "I can just see the colours".
        """

        self.assertIn("label(ctx, protocol, group.label, anchor)", BLOCK)

    def test_the_caption_sits_above_the_region(self) -> None:
        # Centred in the tint, it would collide with the devices.
        self.assertIn("y: circle.y - circle.r", BLOCK)
        self.assertIn("point.y - radius < anchor.y", BLOCK)


class ScopeTests(unittest.TestCase):
    def test_regions_are_drawn_only_on_the_whole_estate_view(self) -> None:
        """The OSPF and BGP views already draw these domains as boxes and
        the site view has its own; tinting there would double the same
        statement in two visual languages."""

        self.assertIn("if (mode !== 'full' || !regionsEnabled())", BLOCK)

    def test_the_canvas_is_cleared_before_the_scope_check(self) -> None:
        """Leaving the previous view's tint on screen after switching is
        the failure this ordering prevents.

        The scope check now lives in renderTo(), which an export shares, so
        this compares where each RUNS rather than where each appears in the
        file: draw() clears unconditionally and only then delegates, so an
        early return cannot skip the clear."""

        draw = BLOCK.split("function draw()", 1)[1].split("\n      }", 1)[0]
        self.assertLess(draw.index("ctx.clearRect"), draw.index("renderTo(ctx)"))
        # And the guard is genuinely inside the delegate, not lost.
        render_to = BLOCK.split("function renderTo(ctx)", 1)[1][:400]
        self.assertIn("if (mode !== 'full'", render_to)

    def test_it_redraws_as_the_graph_moves(self) -> None:
        self.assertIn("cy.on('render', draw)", BLOCK)

    def test_it_redraws_itself_when_the_view_changes(self) -> None:
        """The view select decides whether this layer draws at all, so it
        must not depend on Cytoscape incidentally issuing a render to
        notice. Waiting for someone else's repaint is how a layer ends up
        showing the previous view's answer."""

        self.assertIn("viewSelect.addEventListener('change'", BLOCK)


if __name__ == "__main__":
    unittest.main()
