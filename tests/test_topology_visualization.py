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
from founderos_atlas.visualization import CYTOSCAPE_CDN, TopologyRenderer
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

    def test_rendering_is_deterministic(self) -> None:
        first = TopologyRenderer(self.snapshot).render()
        second = TopologyRenderer(self.snapshot).render()
        self.assertEqual(first, second)

    def test_renderer_uses_only_pinned_cytoscape_external_url(self) -> None:
        html = TopologyRenderer(self.snapshot).render()
        urls = re.findall(r"https://[^\"']+", html)
        self.assertEqual([CYTOSCAPE_CDN], urls)

    def test_renderer_performs_no_network_access(self) -> None:
        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("network used")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")),
        ):
            html = TopologyRenderer(self.snapshot).render()
        self.assertIn(CYTOSCAPE_CDN, html)

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
