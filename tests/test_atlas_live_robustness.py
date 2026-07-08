"""Acceptance tests for PR-019.1 global live-discovery robustness."""

from __future__ import annotations

import unittest

from founderos_atlas.discovery import (
    DiscoveryEngine,
    DiscoveryParseError,
    MissingCommandOutputError,
)
from founderos_atlas.discovery.adapters import CiscoIOSAdapter
from founderos_atlas.discovery.exceptions import sanitize_output_preview
from founderos_atlas.live import run_live_discovery
from founderos_atlas.transport import SSHDeviceTransport

from tests.test_atlas_transport import (
    FakeConnection,
    load_fixture_outputs,
    make_credentials,
)


IOSV_SHOW_VERSION = """\
Cisco IOS Software, IOSv Software (VIOS-ADVENTERPRISEK9-M), Version 15.9(3)M12, RELEASE SOFTWARE (fc1)
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2023 by Cisco Systems, Inc.
Compiled Wed 12-Apr-23 07:00 by prod_rel_team

ROM: Bootstrap program is IOSv

R1 uptime is 17 minutes
System returned to ROM by reload
System image file is "flash0:/vios-adventerprisek9-m"
Last reload reason: Unknown reason

Cisco IOSv (revision 1.0) with 435457K/87040K bytes of memory.
Processor board ID 98E1V6PIAG9GD290EBLWM
4 Gigabit Ethernet interfaces
DRAM configuration is 72 bits wide with parity enabled.
256K bytes of non-volatile configuration memory.
2097152K bytes of ATA System CompactFlash 0 (Read/Write)
"""

IOSV_SHOW_IP_INTERFACE_BRIEF = """\
Interface                  IP-Address      OK? Method Status                Protocol
GigabitEthernet0/0         10.255.0.11     YES manual up                    up
GigabitEthernet0/1         unassigned      YES unset  administratively down down
GigabitEthernet0/2         unassigned      YES unset  administratively down down
"""


def iosv_outputs(cdp: str = "") -> dict[str, str]:
    return {
        "show version": IOSV_SHOW_VERSION,
        "show ip interface brief": IOSV_SHOW_IP_INTERFACE_BRIEF,
        "show cdp neighbors detail": cdp,
    }


class CiscoIOSvParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CiscoIOSAdapter()
        self.engine = DiscoveryEngine(self.adapter)

    def test_iosv_show_version_parsing(self) -> None:
        device = self.adapter.parse_inventory(iosv_outputs())
        self.assertEqual("R1", device.hostname)
        self.assertEqual("cisco", device.vendor)
        self.assertEqual("IOSv", device.platform)
        self.assertEqual("IOS", device.os_name)
        self.assertEqual("15.9(3)M12", device.os_version)
        self.assertEqual("98E1V6PIAG9GD290EBLWM", device.serial_number)
        self.assertEqual("10.255.0.11", device.management_ip)
        self.assertEqual("cisco-ios:r1", device.device_id)
        self.assertNotIn("parse_warnings", device.metadata)

    def test_iosv_full_discovery_without_cdp(self) -> None:
        result = self.engine.discover(iosv_outputs())
        self.assertEqual("R1", result.device.hostname)
        self.assertEqual(3, len(result.interfaces))
        self.assertEqual((), result.neighbors)

    def test_classic_hardware_parsing_is_unchanged(self) -> None:
        device = self.adapter.parse_inventory(load_fixture_outputs())
        self.assertEqual("access-sw-01", device.hostname)
        self.assertEqual("WS-C2960X-48FPS-L", device.platform)
        self.assertEqual("IOS", device.os_name)
        self.assertEqual("15.2(7)E10", device.os_version)


class GracefulPartialDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DiscoveryEngine(CiscoIOSAdapter())

    def test_missing_cdp_output_returns_zero_neighbors(self) -> None:
        for cdp in ("", "% CDP is not enabled\n"):
            with self.subTest(cdp=cdp):
                result = self.engine.discover(iosv_outputs(cdp=cdp))
                self.assertEqual((), result.neighbors)

    def test_show_version_is_still_required(self) -> None:
        outputs = iosv_outputs()
        outputs["show version"] = "   "
        with self.assertRaises(MissingCommandOutputError):
            self.engine.discover(outputs)

    def test_missing_platform_falls_back_with_warning(self) -> None:
        outputs = iosv_outputs()
        outputs["show version"] = "\n".join(
            line
            for line in IOSV_SHOW_VERSION.splitlines()
            if not line.startswith(("Cisco IOS Software", "Cisco IOSv (revision"))
        )
        result = self.engine.discover(outputs)
        self.assertEqual("unknown", result.device.platform)
        self.assertEqual("R1", result.device.hostname)
        warnings = result.metadata["warnings"]
        self.assertTrue(any("platform was not parsed" in item for item in warnings))

    def test_missing_interfaces_warns_instead_of_crashing(self) -> None:
        outputs = iosv_outputs()
        outputs["show ip interface brief"] = ""
        result = self.engine.discover(outputs, management_ip_hint="192.0.2.9")
        self.assertEqual((), result.interfaces)
        self.assertEqual("192.0.2.9", result.device.management_ip)
        warnings = result.metadata["warnings"]
        self.assertTrue(any("no interfaces were parsed" in item for item in warnings))

    def test_hostname_fallback_uses_management_ip_identity(self) -> None:
        outputs = iosv_outputs()
        outputs["show version"] = "Some banner without a recognizable uptime line."
        result = self.engine.discover(outputs)
        self.assertEqual("cisco-ios:10.255.0.11", result.device.device_id)
        self.assertEqual("10.255.0.11", result.device.hostname)
        self.assertEqual("unknown", result.device.platform)
        self.assertEqual("unknown", result.device.os_version)
        warnings = result.metadata["warnings"]
        self.assertTrue(any("hostname was not parsed" in item for item in warnings))

    def test_clean_fixture_discovery_has_no_warnings(self) -> None:
        result = self.engine.discover(load_fixture_outputs())
        self.assertNotIn("warnings", result.metadata)


class ParserDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DiscoveryEngine(CiscoIOSAdapter())

    def test_malformed_show_version_returns_helpful_diagnostic(self) -> None:
        outputs = {
            "show version": "### completely unexpected banner ###",
            "show ip interface brief": "no parseable interface table here",
            "show cdp neighbors detail": "",
        }
        with self.assertRaises(DiscoveryParseError) as caught:
            self.engine.discover(outputs)
        message = str(caught.exception)
        self.assertIn("CiscoIOSAdapter", message)
        self.assertIn("show ip interface brief", message)
        self.assertIn("management_ip", message)
        self.assertIn("no parseable interface table here", message)
        self.assertIn("may not match this parser yet", message)
        self.assertEqual("CiscoIOSAdapter", caught.exception.adapter)
        self.assertEqual("show ip interface brief", caught.exception.command)
        self.assertEqual("management_ip", caught.exception.field)

    def test_output_preview_is_truncated_to_300_chars(self) -> None:
        preview = sanitize_output_preview("A" * 5000)
        self.assertLessEqual(len(preview), 300)
        self.assertTrue(preview.endswith("..."))

    def test_no_secrets_in_error_messages(self) -> None:
        leaky_output = (
            "line vty 0 4\n password SuperSecret123\n"
            "enable secret 5 $1$abcd$efghijklmnop\n"
            "snmp-server community PrivateString RO\n"
            "no version information here"
        )
        outputs = {
            "show version": leaky_output,
            "show ip interface brief": "nothing parseable",
            "show cdp neighbors detail": "",
        }
        with self.assertRaises(DiscoveryParseError) as caught:
            self.engine.discover(outputs)
        message = str(caught.exception)
        for secret in ("SuperSecret123", "$1$abcd$efghijklmnop", "PrivateString"):
            self.assertNotIn(secret, message)

    def test_plain_parse_error_message_is_unchanged(self) -> None:
        self.assertEqual("simple failure", str(DiscoveryParseError("simple failure")))


class LiveCollectorContractTests(unittest.TestCase):
    def test_collector_output_keys_match_adapter_expected_keys(self) -> None:
        adapter = CiscoIOSAdapter()
        connection = FakeConnection()
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: connection
        )
        with transport:
            collected = transport.execute_many(adapter.required_commands)
        self.assertEqual(tuple(collected.keys()), adapter.required_commands)
        for command, output in collected.items():
            self.assertEqual(connection.outputs[command], output)

    def test_live_discovery_uses_connection_address_as_identity_fallback(self) -> None:
        outputs = iosv_outputs()
        outputs["show version"] = "banner with no identity"
        outputs["show ip interface brief"] = ""
        connection = FakeConnection(outputs)
        transport = SSHDeviceTransport(
            make_credentials(host="10.9.9.9"),
            connection_factory=lambda **kwargs: connection,
        )
        result, graph, snapshot = run_live_discovery(transport)
        self.assertEqual("cisco-ios:10.9.9.9", result.device.device_id)
        self.assertEqual("10.9.9.9", result.device.management_ip)
        self.assertTrue(result.metadata["warnings"])
        self.assertEqual(1, graph.summary()["device_count"])
        self.assertEqual("atlas_live_discovery", snapshot.metadata["source"])

    def test_unsupported_terminal_length_does_not_break_collection(self) -> None:
        # FakeConnection raises KeyError for "terminal length 0" because it is
        # not among the prepared outputs — collection must still succeed.
        connection = FakeConnection(iosv_outputs())
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: connection
        )
        result, _, _ = run_live_discovery(transport)
        self.assertEqual("R1", result.device.hostname)
        self.assertEqual("terminal length 0", connection.commands[0])


if __name__ == "__main__":
    unittest.main()
