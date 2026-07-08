"""Acceptance tests for the interactive `founderos atlas discover` command."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import re
import socket
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from founderos_atlas.transport import (
    AuthenticationError,
    ConnectionTimeoutError,
    DeviceCredentials,
    DeviceTransport,
)
from founderos_runtime.cli import main

from tests.test_atlas_live_robustness import iosv_outputs
from tests.test_atlas_transport import PASSWORD, load_fixture_outputs


class FixtureTransport(DeviceTransport):
    """Serves bundled fixture outputs; records lifecycle for assertions."""

    outputs_override: dict[str, str] | None = None

    def __init__(self, credentials: DeviceCredentials) -> None:
        self.credentials = credentials
        self.connected = False
        self.disconnected = False
        self.outputs = dict(self.outputs_override or load_fixture_outputs())
        self.host = credentials.host

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    def execute(self, command: str) -> str:
        return self.outputs[command]


class FailingTransport(DeviceTransport):
    def __init__(self, error: Exception) -> None:
        self.error = error

    def connect(self) -> None:
        raise self.error

    def disconnect(self) -> None:
        pass

    def execute(self, command: str) -> str:
        raise AssertionError("execute must not run when connect fails")


class AtlasDiscoverCliTests(unittest.TestCase):
    def invoke(
        self,
        *,
        transport_factory,
        answers: tuple[str, ...] = ("10.0.0.10", "atlas", "", ""),
        password: str = PASSWORD,
    ):
        prompts: list[str] = []
        replies = iter(answers)

        def input_reader(prompt: str) -> str:
            prompts.append(prompt)
            return next(replies)

        def password_reader(prompt: str) -> str:
            prompts.append(prompt)
            return password

        opened: list[str] = []
        stdout, stderr = StringIO(), StringIO()
        with tempfile.TemporaryDirectory() as workdir:
            topology_path = Path(workdir) / "atlas_topology.html"
            snapshot_path = Path(workdir) / "topology_snapshot.json"
            brief_path = Path(workdir) / "morning_brief.md"
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    ["atlas", "discover"],
                    atlas_transport_factory=transport_factory,
                    atlas_input_reader=input_reader,
                    atlas_password_reader=password_reader,
                    atlas_topology_output=topology_path,
                    atlas_snapshot_output=snapshot_path,
                    atlas_morning_brief_output=brief_path,
                    atlas_browser_opener=opened.append,
                )
            artifacts = {
                name: path.read_text(encoding="utf-8") if path.exists() else None
                for name, path in (
                    ("topology", topology_path),
                    ("snapshot", snapshot_path),
                    ("brief", brief_path),
                )
            }
        return code, stdout.getvalue(), stderr.getvalue(), prompts, opened, artifacts

    def test_successful_discover_generates_all_artifacts(self) -> None:
        transports: list[FixtureTransport] = []

        def factory(credentials: DeviceCredentials) -> FixtureTransport:
            transport = FixtureTransport(credentials)
            transports.append(transport)
            return transport

        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("network used")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")),
        ):
            code, output, error, prompts, opened, artifacts = self.invoke(
                transport_factory=factory
            )

        self.assertEqual(0, code, error)
        self.assertEqual("", error)
        self.assertEqual(
            [
                "Management IP: ",
                "Username: ",
                "Password: ",
                "Max depth [1]: ",
                "Max devices [10]: ",
            ],
            prompts,
        )
        self.assertEqual("10.0.0.10", transports[0].credentials.host)
        self.assertEqual("atlas", transports[0].credentials.username)
        self.assertTrue(transports[0].connected)
        self.assertTrue(transports[0].disconnected)
        self.assertIn("Atlas Live Discovery", output)
        self.assertIn("Device discovered.", output)
        self.assertIn("Hostname: access-sw-01", output)
        self.assertIn("Vendor: Cisco", output)
        self.assertIn("Platform: WS-C2960X-48FPS-L", output)
        self.assertIn("Management IP: 10.0.0.10", output)
        self.assertIn("Interfaces: 4", output)
        self.assertIn("Neighbors: 2", output)
        self.assertNotIn("No neighbors discovered yet", output)
        self.assertIn("Snapshot ID: atlas-topology:", output)
        self.assertIn("Morning Brief", output)
        self.assertIn("Topology viewer saved:", output)
        self.assertIn("Topology snapshot saved:", output)
        self.assertIn("Morning brief saved:", output)
        self.assertIn("Live discovery completed successfully.", output)
        self.assertEqual(1, len(opened))
        self.assertTrue(opened[0].startswith("file://"))
        self.assertIn("access-sw-01", artifacts["topology"] or "")
        self.assertIn("## Network Status", artifacts["brief"] or "")
        snapshot = json.loads(artifacts["snapshot"] or "{}")
        self.assertEqual(1, snapshot["device_count"])
        self.assertEqual("access-sw-01", snapshot["devices"][0]["hostname"])
        self.assertTrue(snapshot["snapshot_id"].startswith("atlas-topology:"))

    def test_password_never_appears_in_any_output(self) -> None:
        code, output, error, _, _, artifacts = self.invoke(
            transport_factory=FixtureTransport
        )
        self.assertEqual(0, code, error)
        for text in (output, error, artifacts["topology"], artifacts["brief"]):
            self.assertNotIn(PASSWORD, text or "")

    def test_authentication_failure_is_reported_cleanly(self) -> None:
        message = "Authentication failed for 10.0.0.10. Verify the username and password."

        def factory(credentials: DeviceCredentials) -> FailingTransport:
            return FailingTransport(AuthenticationError(message))

        code, output, error, _, opened, artifacts = self.invoke(transport_factory=factory)
        self.assertEqual(1, code)
        self.assertEqual("", output)
        self.assertEqual(f"Error: {message}\n", error)
        self.assertNotIn(PASSWORD, error)
        self.assertEqual([], opened)
        self.assertIsNone(artifacts["topology"])
        self.assertIsNone(artifacts["snapshot"])
        self.assertIsNone(artifacts["brief"])

    def test_connection_timeout_is_reported_cleanly(self) -> None:
        message = "Connection to 10.0.0.10 timed out. Verify the device is reachable and SSH is enabled."

        def factory(credentials: DeviceCredentials) -> FailingTransport:
            return FailingTransport(ConnectionTimeoutError(message))

        code, output, error, _, _, _ = self.invoke(transport_factory=factory)
        self.assertEqual(1, code)
        self.assertEqual(f"Error: {message}\n", error)

    def test_zero_neighbor_discovery_still_generates_all_artifacts(self) -> None:
        class LonelyDeviceTransport(FixtureTransport):
            outputs_override = iosv_outputs(cdp="% CDP is not enabled\n")

        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("network used")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")),
        ):
            code, output, error, _, opened, artifacts = self.invoke(
                transport_factory=LonelyDeviceTransport
            )

        self.assertEqual(0, code, error)
        self.assertIn("Hostname: R1", output)
        self.assertIn("Platform: IOSv", output)
        self.assertIn("Neighbors: 0", output)
        self.assertIn("No neighbors discovered yet", output)
        self.assertIn("Live discovery completed successfully.", output)
        self.assertEqual(1, len(opened))
        snapshot = json.loads(artifacts["snapshot"] or "{}")
        self.assertEqual(1, snapshot["device_count"])
        self.assertEqual(0, snapshot["edge_count"])
        self.assertEqual([], snapshot["edges"])
        self.assertIn("R1", artifacts["topology"] or "")
        self.assertIn("## Network Status", artifacts["brief"] or "")

    def test_discover_output_is_deterministic(self) -> None:
        runs = []
        for _ in range(2):
            code, output, error, _, _, artifacts = self.invoke(
                transport_factory=FixtureTransport
            )
            self.assertEqual(0, code, error)
            # The temporary output directory differs per run; artifact paths
            # are the only permitted variance.
            normalized = re.sub(r"saved: \S+", "saved: <path>", output)
            runs.append((normalized, artifacts))
        self.assertEqual(runs[0][0], runs[1][0])
        self.assertEqual(runs[0][1], runs[1][1])

    def test_blank_answers_are_rejected_before_connecting(self) -> None:
        def factory(credentials: DeviceCredentials) -> FixtureTransport:
            raise AssertionError("no transport should be built without credentials")

        code, output, error, _, _, _ = self.invoke(
            transport_factory=factory, answers=("", ""), password=""
        )
        self.assertEqual(1, code)
        self.assertIn("Management IP, username, and password are all required", error)

    def test_help_lists_atlas_discover(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["help"])
        self.assertEqual(0, code)
        self.assertIn("founderos atlas discover", stdout.getvalue())
        self.assertIn("read-only SSH", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
