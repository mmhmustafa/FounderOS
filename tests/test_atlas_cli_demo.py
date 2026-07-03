"""Integration test for the fixture-only Atlas Discovery CLI demo."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import socket
import unittest
from unittest.mock import patch
import urllib.request

from founderos_runtime.cli import main


class AtlasDiscoveryCliDemoTests(unittest.TestCase):
    def test_atlas_discovery_demo_is_successful_and_network_free(self) -> None:
        stdout, stderr = StringIO(), StringIO()
        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("network used")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = main(["atlas", "demo", "discovery"])

        output = stdout.getvalue()
        self.assertEqual(0, code, stderr.getvalue())
        self.assertEqual("", stderr.getvalue())
        self.assertIn("Atlas Discovery Demo", output)
        self.assertIn("Hostname: access-sw-01", output)
        self.assertIn("Vendor: Cisco", output)
        self.assertIn("Interfaces: 4", output)
        self.assertIn("Neighbors: 2", output)
        self.assertIn("|-- ap-01", output)
        self.assertIn("`-- dist-sw-01", output)
        self.assertIn("Devices: 1", output)
        self.assertIn("Edges: 2", output)
        self.assertIn("Discovery completed successfully.", output)
        self.assertNotIn("NetworkDevice(", output)


if __name__ == "__main__":
    unittest.main()
