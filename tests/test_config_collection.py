"""Acceptance tests for PR-023 read-only configuration collection."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.config import (
    ConfigurationCollectionError,
    collect_configuration,
    write_configuration_artifacts,
)
from founderos_atlas.discovery import DiscoveryEngine
from founderos_atlas.discovery.adapters import CiscoIOSAdapter
from founderos_atlas.transport import SSHDeviceTransport
from founderos_runtime.cli import main

from tests.test_atlas_transport import FakeConnection, PASSWORD, make_credentials
from tests.test_multihop_discovery import ScriptedNetwork, device_outputs


RUNNING_CONFIG = (
    "Building configuration...\r\n"
    "\r\n"
    "Current configuration : 1024 bytes\r\n"
    "!\r\n"
    "hostname R1\r\n"
    "!\r\n"
    "enable secret 5 $1$fixture$abcdefghijklmnop\r\n"
    "!\r\n"
    "interface GigabitEthernet0/0\r\n"
    " ip address 10.0.0.1 255.255.255.0\r\n"
    "!\r\n"
    "end\r\n"
)

STARTUP_CONFIG = "!\nhostname R1\n!\nend\n"
INVENTORY = 'NAME: "Chassis", DESCR: "IOSv chassis"\nPID: IOSv\n'
LICENSE = "License Level: advipservices\n"
MODULE = "Mod Ports Card Type\n1   4    IOSv virtual module\n"

UNSUPPORTED = "% Invalid input detected at '^' marker.\n"
DENIED = "% Authorization failed.\n"


def config_outputs(**overrides: str) -> dict[str, str]:
    outputs = {
        **device_outputs("R1", "10.0.0.1"),
        "show running-config": RUNNING_CONFIG,
        "show startup-config": STARTUP_CONFIG,
        "show inventory": INVENTORY,
        "show license summary": LICENSE,
        "show module": MODULE,
    }
    outputs.update(overrides)
    return outputs


def make_collection(outputs: dict[str, str]):
    connection = FakeConnection(outputs)
    transport = SSHDeviceTransport(
        make_credentials(host="10.0.0.1"),
        connection_factory=lambda **kwargs: connection,
    )
    result = DiscoveryEngine(CiscoIOSAdapter()).discover(
        {
            command: outputs[command]
            for command in CiscoIOSAdapter.required_commands
        },
        management_ip_hint="10.0.0.1",
    )
    return connection, transport, result


class ConfigurationCollectorTests(unittest.TestCase):
    def test_successful_collection(self) -> None:
        connection, transport, result = make_collection(config_outputs())
        artifact = collect_configuration(transport, result)
        self.assertEqual("complete", artifact.status)
        self.assertEqual((), artifact.warnings)
        self.assertEqual("R1", artifact.hostname)
        self.assertEqual("cisco", artifact.vendor)
        self.assertEqual("IOSv", artifact.platform)
        self.assertEqual("10.0.0.1", artifact.management_ip)
        self.assertIn("hostname R1", artifact.running_config)
        self.assertNotIn("\r", artifact.running_config)  # normalized line endings
        self.assertEqual(
            [
                ("show running-config", "collected"),
                ("show startup-config", "collected"),
                ("show inventory", "collected"),
                ("show license summary", "collected"),
                ("show module", "collected"),
            ],
            [(outcome.command, outcome.status) for outcome in artifact.commands],
        )
        self.assertEqual(
            {"show startup-config", "show inventory", "show license summary", "show module"},
            set(artifact.additional_outputs),
        )
        self.assertTrue(connection.disconnected)

    def test_unsupported_commands_degrade_gracefully(self) -> None:
        _, transport, result = make_collection(
            config_outputs(**{"show license summary": UNSUPPORTED, "show module": UNSUPPORTED})
        )
        artifact = collect_configuration(transport, result)
        self.assertEqual("partial", artifact.status)
        statuses = {outcome.command: outcome.status for outcome in artifact.commands}
        self.assertEqual("collected", statuses["show running-config"])
        self.assertEqual("unsupported", statuses["show license summary"])
        self.assertEqual("unsupported", statuses["show module"])
        self.assertEqual(2, len(artifact.warnings))
        self.assertTrue(all("not supported" in warning for warning in artifact.warnings))

    def test_partial_success_with_denied_startup_config(self) -> None:
        _, transport, result = make_collection(
            config_outputs(**{"show startup-config": DENIED})
        )
        artifact = collect_configuration(transport, result)
        self.assertEqual("partial", artifact.status)
        statuses = {outcome.command: outcome.status for outcome in artifact.commands}
        self.assertEqual("denied", statuses["show startup-config"])
        self.assertEqual("collected", statuses["show inventory"])
        self.assertNotIn("show startup-config", artifact.additional_outputs)
        self.assertTrue(any("denied" in warning for warning in artifact.warnings))

    def test_required_running_config_failure_raises(self) -> None:
        _, transport, result = make_collection(
            config_outputs(**{"show running-config": UNSUPPORTED})
        )
        with self.assertRaises(ConfigurationCollectionError) as caught:
            collect_configuration(transport, result)
        self.assertIn("running configuration", str(caught.exception))
        self.assertIn("R1", str(caught.exception))

    def test_optional_commands_can_be_disabled(self) -> None:
        connection, transport, result = make_collection(config_outputs())
        artifact = collect_configuration(transport, result, include_optional=False)
        self.assertEqual("complete", artifact.status)
        self.assertEqual(1, len(artifact.commands))
        self.assertEqual({}, dict(artifact.additional_outputs))
        self.assertNotIn("show inventory", connection.commands)

    def test_only_read_only_commands_are_sent(self) -> None:
        connection, transport, result = make_collection(config_outputs())
        collect_configuration(transport, result)
        for command in connection.commands:
            self.assertTrue(
                command == "terminal length 0" or command.startswith("show "),
                f"unexpected command sent: {command!r}",
            )

    def test_metadata_generation(self) -> None:
        _, transport, result = make_collection(
            config_outputs(**{"show module": UNSUPPORTED})
        )
        artifact = collect_configuration(transport, result, collected_at="2026-07-08T09:00:00Z")
        metadata = artifact.to_metadata_dict()
        self.assertEqual("R1", metadata["hostname"])
        self.assertEqual("cisco", metadata["vendor"])
        self.assertEqual("IOSv", metadata["platform"])
        self.assertEqual("IOS", metadata["os_name"])
        self.assertEqual("15.9(3)M12", metadata["os_version"])
        self.assertEqual("2026-07-08T09:00:00Z", metadata["collected_at"])
        self.assertEqual("partial", metadata["collection_status"])
        self.assertEqual(5, len(metadata["commands"]))
        self.assertEqual(1, len(metadata["warnings"]))
        self.assertTrue(metadata["read_only"])
        self.assertEqual(64, len(metadata["running_config_sha256"]))
        # Provenance only: metadata must never contain configuration content.
        serialized = json.dumps(metadata)
        self.assertNotIn("enable secret", serialized)
        self.assertNotIn("ip address 10.0.0.1 255.255.255.0", serialized)

    def test_collection_is_deterministic(self) -> None:
        first = collect_configuration(*make_collection(config_outputs())[1:])
        second = collect_configuration(*make_collection(config_outputs())[1:])
        self.assertEqual(first, second)


class ConfigurationStorageTests(unittest.TestCase):
    def test_artifact_generation(self) -> None:
        _, transport, result = make_collection(config_outputs())
        artifact = collect_configuration(transport, result)
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_configuration_artifacts(artifact, Path(tmp) / "R1")
            self.assertEqual("running_config.txt", paths.running_config.name)
            self.assertEqual("configuration_metadata.json", paths.metadata.name)
            self.assertIn("hostname R1", paths.running_config.read_text(encoding="utf-8"))
            metadata = json.loads(paths.metadata.read_text(encoding="utf-8"))
            self.assertEqual("complete", metadata["collection_status"])
            names = {path.name for path in paths.additional}
            self.assertEqual(
                {
                    "show_inventory.txt",
                    "show_license_summary.txt",
                    "show_module.txt",
                    "show_startup-config.txt",
                },
                names,
            )
            for path in paths.additional:
                self.assertTrue(path.read_text(encoding="utf-8").strip())


class DiscoverCliConfigCollectionTests(unittest.TestCase):
    def run_discover(self, answers: tuple[str, ...], workdir: Path, network=None):
        if network is None:
            network = ScriptedNetwork(
                {
                    "10.0.0.1": config_outputs(),
                    "10.0.0.2": {
                        **device_outputs("SW1", "10.0.0.2"),
                        "show running-config": RUNNING_CONFIG.replace("R1", "SW1"),
                        "show startup-config": STARTUP_CONFIG,
                        "show inventory": INVENTORY,
                        "show license summary": UNSUPPORTED,
                        "show module": UNSUPPORTED,
                    },
                }
            )
            network.topology["10.0.0.1"] = {
                **config_outputs(),
                "show cdp neighbors detail": device_outputs(
                    "R1", "10.0.0.1", (("SW1", "10.0.0.2"),)
                )["show cdp neighbors detail"],
            }
        replies = iter(answers)
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                ["atlas", "discover"],
                atlas_transport_factory=lambda credentials: network.transport_factory(
                    credentials.host
                ),
                atlas_input_reader=lambda prompt: next(replies, ""),
                atlas_password_reader=lambda prompt: PASSWORD,
                atlas_topology_output=workdir / "atlas_topology.html",
                atlas_snapshot_output=workdir / "topology_snapshot.json",
                atlas_morning_brief_output=workdir / "morning_brief.md",
                atlas_config_output_dir=workdir / "configs",
                atlas_dashboard_output=workdir / "dashboard.html",
                atlas_browser_opener=lambda uri: None,
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_discover_collects_configuration_when_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, output, error = self.run_discover(
                ("10.0.0.1", "atlas", "", "", "y"), workdir
            )
            self.assertEqual(0, code, error)
            self.assertIn("Configuration Collection", output)
            self.assertIn("[complete] R1 ->", output)
            self.assertIn("[partial] SW1 ->", output)
            r1_config = workdir / "configs" / "R1" / "running_config.txt"
            sw1_metadata = workdir / "configs" / "SW1" / "configuration_metadata.json"
            self.assertIn("hostname R1", r1_config.read_text(encoding="utf-8"))
            metadata = json.loads(sw1_metadata.read_text(encoding="utf-8"))
            self.assertEqual("partial", metadata["collection_status"])
            # Configuration content never reaches the console.
            self.assertNotIn("enable secret", output)
            self.assertNotIn(PASSWORD, output)

    def test_discover_skips_collection_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, output, error = self.run_discover(
                ("10.0.0.1", "atlas", "", "", ""), workdir
            )
            self.assertEqual(0, code, error)
            self.assertIn("Configuration Collection", output)
            self.assertIn("Skipped (not requested).", output)
            self.assertFalse((workdir / "configs").exists())

    def test_per_device_collection_failure_does_not_abort(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": {
                    **config_outputs(),
                    "show cdp neighbors detail": device_outputs(
                        "R1", "10.0.0.1", (("SW1", "10.0.0.2"),)
                    )["show cdp neighbors detail"],
                },
                "10.0.0.2": {
                    **device_outputs("SW1", "10.0.0.2"),
                    "show running-config": UNSUPPORTED,
                },
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, output, error = self.run_discover(
                ("10.0.0.1", "atlas", "", "", "y"), workdir, network=network
            )
            self.assertEqual(0, code, error)
            self.assertIn("[complete] R1 ->", output)
            self.assertIn("[failed] SW1 - ", output)
            self.assertIn("running configuration", output)
            self.assertTrue((workdir / "configs" / "R1" / "running_config.txt").exists())
            self.assertFalse((workdir / "configs" / "SW1").exists())


if __name__ == "__main__":
    unittest.main()
