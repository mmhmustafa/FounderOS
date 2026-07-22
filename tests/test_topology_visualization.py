"""Tests for deterministic interactive Atlas topology HTML rendering."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import re
import socket
import unittest
from unittest.mock import patch
import urllib.request

from founderos_atlas.demo import run_atlas_discovery_demo
from founderos_atlas.visualization import (
    CYTOSCAPE_CDN,
    CYTOSCAPE_VERSION,
    TOPOLOGY_VISUAL_STYLE_MARKER,
    TOPOLOGY_VISUAL_STYLE_VERSION,
    TopologyRenderer,
    topology_visual_style_is_current,
)
from founderos_atlas.visualization.renderer import _addressed_interfaces
from founderos_runtime.cli import main


class TopologyVisualizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _, _, cls.snapshot = run_atlas_discovery_demo()

    def test_snapshot_converts_to_cytoscape_elements(self) -> None:
        elements = TopologyRenderer(self.snapshot).elements()
        self.assertEqual(4, len(elements["nodes"]))
        self.assertEqual(3, len(elements["edges"]))
        kinds = {node["data"]["kind"] for node in elements["nodes"]}
        self.assertEqual({"discovered", "observed"}, kinds)
        self.assertTrue(all(edge["data"]["source"] for edge in elements["edges"]))

    def test_the_native_menu_is_suppressed_over_the_graph(self) -> None:
        """Right-clicking a device must show Atlas's menu, not the
        browser's. Bound to #cy in the bubble phase, the suppression
        leaked intermittently — Cytoscape's canvas can stop the event
        before it reaches #cy. It now listens in the CAPTURE phase on the
        document (top-down, so it always sees the event) and is scoped to
        the graph, so right-click paste still works in the inputs."""

        html = TopologyRenderer(self.snapshot).render()
        handler = html.split("would cover ours", 1)[1][:1500]
        self.assertIn("addEventListener('contextmenu'", handler)
        self.assertIn("}, true)", handler)                 # capture phase
        self.assertIn("graph.contains(target)", handler)   # graph-scoped

    def test_a_second_right_click_is_not_swallowed_by_the_first_menu(self) -> None:
        """The reported bug: right-click worked once, then gave the browser
        menu. Our menu is a SIBLING of #cy and overlays the graph, so the
        menu one right-click opens sits on top of the device the next one
        aims at; that second click fails the "inside #cy" test and the
        native menu leaks.

        Two halves: a stale menu is closed on mousedown — which runs BEFORE
        contextmenu, so the browser hit-tests the device underneath — and a
        right-click that still lands on the menu is suppressed rather than
        handed to the browser.
        """

        html = TopologyRenderer(self.snapshot).render()
        block = html.split("would cover ours", 1)[1][:2400]
        self.assertIn("contextMenu.contains(target)", block)
        self.assertIn("addEventListener('mousedown'", block)
        # A press INSIDE the menu must not close it, or the item would
        # vanish before it could be chosen.
        self.assertIn("if (!contextMenu.contains(event.target))", block)

    def test_nodes_carry_their_addressed_interfaces(self) -> None:
        """The hover card names every IP a device answers on, so the node
        data must carry the addressed interfaces — not only the count and
        the management endpoint."""

        elements = TopologyRenderer(self.snapshot).elements()
        discovered = [
            node for node in elements["nodes"]
            if node["data"]["kind"] == "discovered"
        ]
        self.assertTrue(discovered)
        for node in discovered:
            listed = node["data"]["interface_addresses"]
            self.assertIsInstance(listed, list)
            # The fixture device has addressed interfaces; every entry
            # carries an IP and the port it sits on.
            self.assertTrue(listed)
            for entry in listed:
                self.assertIn("ip", entry)
                self.assertIn("name", entry)
                self.assertIn("description", entry)
                self.assertTrue(entry["ip"])

    def test_addressed_interfaces_lists_only_ip_bearing_ports(self) -> None:
        """A switchport with no L3 address is not an answer to "which IPs
        does this own", so it is left out; an addressed port keeps its
        name and description."""

        listed = _addressed_interfaces([
            {"name": "Gi0/0", "ip_address": "10.1.1.1",
             "description": "core uplink"},
            {"name": "Gi0/1", "ip_address": None, "description": "to access"},
            {"name": "Vlan10", "ip_address": "10.2.0.1", "description": ""},
        ])
        self.assertEqual(
            [
                {"name": "Gi0/0", "ip": "10.1.1.1", "description": "core uplink"},
                {"name": "Vlan10", "ip": "10.2.0.1", "description": ""},
            ],
            listed,
        )

    def test_the_hover_card_renders_interfaces_and_escapes_them(self) -> None:
        """Descriptions come from device configs — untrusted text — so the
        card builds escaped HTML, and it reads the addressed-interface
        data, not just the management IP."""

        html = TopologyRenderer(self.snapshot).render()
        self.assertIn("function deviceTooltipHtml", html)
        self.assertIn("data.interface_addresses", html)
        self.assertIn("escapeHtml(iface.ip)", html)
        self.assertIn("escapeHtml(iface.description)", html)

    def test_re_entering_a_device_re_shows_its_card(self) -> None:
        """The hover de-dupes repeat mouseover on the same node, so the
        guard must be cleared on mouseout — otherwise moving away and
        back to the same device never re-shows the card."""

        html = TopologyRenderer(self.snapshot).render()
        mouseout = html.split("cy.on('mouseout', 'node'", 1)[1][:400]
        self.assertIn("hoveredId = null", mouseout)

    def test_html_generation_contains_interactive_features(self) -> None:
        html = TopologyRenderer(self.snapshot).render()
        self.assertIn("Atlas Topology Viewer", html)
        self.assertIn("cytoscape({", html)
        self.assertIn("name: 'cose'", html)
        self.assertIn("minZoom:", html)
        self.assertIn("id=\"fit\"", html)
        self.assertIn("id=\"search\"", html)
        self.assertIn("cy.on('tap', 'node'", html)
        self.assertIn("cy.on('mouseover', 'node'", html)
        self.assertIn("search-match", html)
        # PORTAL-adjacent polish: the raw evidence kind must not be an edge
        # label, and interface names are the meaningful link caption.
        self.assertNotIn("'label': 'data(protocol)'", html)
        self.assertIn("data(source_interface)", html)
        self.assertIn("data(display_label)", html)
        self.assertIsNone(
            re.search(r"\son(?:click|change|submit|load|error|input|key\w+)\s*=", html),
            "topology artifacts must not contain executable event attributes",
        )
        self.assertIn('data-topology-action="toggle-site"', html)

    def test_protocol_views_are_separate_and_derive_domain_boundaries(self) -> None:
        routing_facts = {
            str(device["hostname"]): {
                "ospf_areas": ["0"],
                "ospf_process_ids": ["1"],
                "bgp_as": "64512",
            }
            for device in self.snapshot.devices
        }
        renderer = TopologyRenderer(
            self.snapshot, viewer_context={"routing_facts": routing_facts}
        )
        view = renderer.routing_view(renderer.elements())
        self.assertTrue(view["ospf"]["groups"])
        self.assertTrue(view["bgp"]["groups"])
        self.assertEqual(self.snapshot.device_count, view["ospf"]["covered_devices"])
        self.assertEqual(self.snapshot.device_count, view["bgp"]["covered_devices"])
        html = renderer.render()
        self.assertIn("OSPF areas", html)
        self.assertIn("BGP autonomous systems", html)
        self.assertIn("Edit topology", html)
        self.assertNotIn("site-hub", html)

    def test_rendering_is_deterministic(self) -> None:
        first = TopologyRenderer(self.snapshot).render()
        second = TopologyRenderer(self.snapshot).render()
        self.assertEqual(first, second)

    def test_rendering_carries_its_deterministic_visual_style_version(self) -> None:
        html = TopologyRenderer(self.snapshot).render()
        self.assertTrue(TOPOLOGY_VISUAL_STYLE_VERSION)
        self.assertEqual(1, html.count(TOPOLOGY_VISUAL_STYLE_MARKER))
        self.assertTrue(topology_visual_style_is_current(html))
        self.assertFalse(
            topology_visual_style_is_current(
                "<!-- TOPOLOGY_VISUAL_STYLE_VERSION=stale -->"
            )
        )

    def test_renderer_embeds_pinned_cytoscape_before_viewer_initialization(self) -> None:
        html = TopologyRenderer(self.snapshot).render()
        urls = re.findall(r"https://[^\"']+", html)
        self.assertEqual([], urls)
        self.assertNotIn(CYTOSCAPE_CDN, html)
        self.assertIn("Cytoscape Consortium", html)
        self.assertEqual("3.29.2", CYTOSCAPE_VERSION)
        self.assertLess(html.index("Cytoscape Consortium"), html.index("cytoscape({"))

    def test_renderer_performs_no_network_access(self) -> None:
        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("network used")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")),
        ):
            html = TopologyRenderer(self.snapshot).render()
        self.assertNotIn(CYTOSCAPE_CDN, html)
        self.assertIn("Cytoscape Consortium", html)

    def test_cli_generates_html_and_requests_browser_open(self) -> None:
        output_path = Path(__file__).resolve().parent / ".atlas_topology_viewer_test.html"
        opened: list[str] = []
        stdout, stderr = StringIO(), StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    ["atlas", "demo", "topology"],
                    atlas_topology_output=output_path,
                    atlas_browser_opener=opened.append,
                )
            self.assertEqual(0, code, stderr.getvalue())
            self.assertTrue(output_path.is_file())
            self.assertEqual([output_path.resolve().as_uri()], opened)
            self.assertIn("HTML generated:", stdout.getvalue())
            self.assertIn("Atlas Topology Viewer", output_path.read_text(encoding="utf-8"))
        finally:
            output_path.unlink(missing_ok=True)

    def test_html_embeds_data_without_python_representations(self) -> None:
        html = TopologyRenderer(self.snapshot).render()
        self.assertNotIn("mappingproxy", html)
        self.assertNotIn("NetworkDevice(", html)
        self.assertNotIn("__TOPOLOGY_ELEMENTS__", html)
        self.assertIn("access-sw-01", html)

    def test_renderer_rejects_non_snapshot(self) -> None:
        with self.assertRaisesRegex(TypeError, "TopologySnapshot"):
            TopologyRenderer({})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()


class SiteViewTests(unittest.TestCase):
    """PR-050 (SKYLINE): the site level of the topology.

    Grouping comes from the Site Catalog through the inference engine and
    from nowhere else; totals are preserved (a device can never be lost by
    folding); aggregated edges carry their constituents and the STRONGEST
    relationship; and with no catalog the feature simply is not there.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from founderos_atlas.sites.models import Site, SiteCatalog

        _, _, cls.snapshot = run_atlas_discovery_demo()
        elements = TopologyRenderer(cls.snapshot).elements()
        discovered = [
            n["data"] for n in elements["nodes"]
            if n["data"]["kind"] == "discovered"
        ]
        # Split the discovered estate across two explicit sites so at least
        # one real edge crosses the boundary. Explicit assignment is used on
        # purpose: it is the strongest signal and keeps the fixture
        # independent of the demo's hostname spelling.
        cls.first = discovered[0]["hostname"]
        cls.rest = [d["hostname"] for d in discovered[1:]]
        cls.catalog = SiteCatalog(sites=(
            Site(site_id="alpha", name="Alpha",
                 explicit_hostnames=(cls.first,)),
            Site(site_id="beta", name="Beta",
                 explicit_hostnames=tuple(cls.rest)),
        ))

    def _view(self, catalog=None):
        renderer = TopologyRenderer(
            self.snapshot, site_catalog=catalog or self.catalog
        )
        return renderer.site_view(renderer.elements()), renderer.elements()

    def test_no_catalog_means_no_site_view(self) -> None:
        from founderos_atlas.sites.models import SiteCatalog

        view, _ = self._view(catalog=SiteCatalog())
        self.assertEqual([], view["sites"])
        self.assertEqual({}, view["membership"])

    def test_every_node_is_grouped_and_none_is_lost(self) -> None:
        view, elements = self._view()
        self.assertEqual(len(view["membership"]), len(elements["nodes"]))
        total_in_sites = sum(site["count"] for site in view["sites"])
        self.assertEqual(total_in_sites, len(elements["nodes"]))

    def test_membership_comes_from_the_catalog_not_hostname_parsing(self) -> None:
        view, elements = self._view()
        by_id = {n["data"]["id"]: n["data"] for n in elements["nodes"]}
        for node_id, site_id in view["membership"].items():
            data = by_id[node_id]
            if data["kind"] == "observed":
                continue
            expected = "alpha" if data["hostname"] == self.first else "beta"
            self.assertEqual(expected, site_id, data["hostname"])

    def test_unresolved_peers_ride_with_the_site_that_observed_them(self) -> None:
        view, elements = self._view()
        observed = [
            n["data"]["id"] for n in elements["nodes"]
            if n["data"]["kind"] == "observed"
        ]
        self.assertTrue(observed)
        for node_id in observed:
            self.assertIn(view["membership"][node_id], ("alpha", "beta"))

    # The demo snapshot has ONE discovered device, so cross-site folding
    # cannot be exercised on it -- these tests build a small synthetic
    # estate instead: two sites, three devices, edges of mixed strength.
    @staticmethod
    def _synthetic():
        from founderos_atlas.sites.models import Site, SiteCatalog

        def node(node_id, hostname):
            return {"data": {"id": node_id, "hostname": hostname,
                             "label": hostname, "kind": "discovered",
                             "management_ip": "Unknown", "role": "router"}}

        elements = {
            "nodes": [node("d:a1", "a1"), node("d:b1", "b1"),
                      node("d:b2", "b2")],
            "edges": [
                {"data": {"id": "x1", "source": "d:a1", "target": "d:b1",
                          "relationship": "protocol-peer"}},
                {"data": {"id": "x2", "source": "d:a1", "target": "d:b1",
                          "relationship": "physical"}},
                {"data": {"id": "in1", "source": "d:b1", "target": "d:b2",
                          "relationship": "physical"}},
            ],
        }
        catalog = SiteCatalog(sites=(
            Site(site_id="alpha", name="Alpha", explicit_hostnames=("a1",)),
            Site(site_id="beta", name="Beta", explicit_hostnames=("b1", "b2")),
        ))
        return elements, catalog

    def test_aggregates_fold_every_cross_site_edge_and_only_those(self) -> None:
        elements, catalog = self._synthetic()
        renderer = TopologyRenderer(self.snapshot, site_catalog=catalog)
        view = renderer.site_view(elements)
        folded = [m for agg in view["aggregated_edges"] for m in agg["members"]]
        self.assertEqual(["x1", "x2"], sorted(folded))   # never the intra-site in1
        self.assertTrue(all(agg["count"] == len(agg["members"])
                            for agg in view["aggregated_edges"]))

    def test_the_strongest_relationship_wins_the_aggregate(self) -> None:
        # Two edges between the same pair: a weak BGP observation and a
        # physical link. The folded line must claim physical -- claiming less
        # would understate proven evidence, claiming an unproven kind would
        # invent it.
        elements, catalog = self._synthetic()
        renderer = TopologyRenderer(self.snapshot, site_catalog=catalog)
        agg = renderer.site_view(elements)["aggregated_edges"][0]
        self.assertEqual(2, agg["count"])
        self.assertEqual("physical", agg["relationship"])

    def test_site_view_is_deterministic(self) -> None:
        one, _ = self._view()
        two, _ = self._view()
        self.assertEqual(one, two)

    def test_the_artifact_embeds_the_site_view(self) -> None:
        html = TopologyRenderer(
            self.snapshot, site_catalog=self.catalog
        ).render()
        self.assertIn("const siteView = ", html)
        self.assertIn("site:alpha", html)   # embedded compact JSON
        self.assertNotIn("__SITE_VIEW__", html)
