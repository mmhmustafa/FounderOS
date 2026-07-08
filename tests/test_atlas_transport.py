"""Acceptance tests for the read-only Atlas SSH transport layer."""

from __future__ import annotations

import importlib.util
import unittest

from founderos_atlas.demo import atlas_app_root
from founderos_atlas.live import run_live_discovery
from founderos_atlas.transport import (
    AuthenticationError,
    ConnectionLostError,
    ConnectionTimeoutError,
    DeviceCredentials,
    DeviceTransport,
    PermissionDeniedError,
    ReadOnlyViolationError,
    SSHUnavailableError,
    SSHDeviceTransport,
    TransportDependencyError,
    TransportNotConnectedError,
    UnsupportedPlatformError,
    ensure_read_only,
)


PASSWORD = "s3cret-fixture-password"


def load_fixture_outputs() -> dict[str, str]:
    root = atlas_app_root() / "fixtures" / "cisco_ios"
    return {
        "show version": (root / "show_version.txt").read_text(encoding="utf-8"),
        "show ip interface brief": (
            root / "show_ip_interface_brief.txt"
        ).read_text(encoding="utf-8"),
        "show cdp neighbors detail": (
            root / "show_cdp_neighbors_detail.txt"
        ).read_text(encoding="utf-8"),
    }


def make_credentials(**overrides) -> DeviceCredentials:
    values = {"host": "10.0.0.10", "username": "atlas", "password": PASSWORD}
    values.update(overrides)
    return DeviceCredentials(**values)


class FakeConnection:
    """Stands in for a Netmiko connection; records every interaction."""

    def __init__(self, outputs: dict[str, str] | None = None, error: Exception | None = None):
        self.outputs = outputs if outputs is not None else load_fixture_outputs()
        self.error = error
        self.commands: list[str] = []
        self.disconnected = False

    def send_command(self, command: str, **kwargs) -> str:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self.outputs[command]

    def disconnect(self) -> None:
        self.disconnected = True


class NetmikoAuthenticationException(Exception):
    """Local stand-in matched by class name, like the real Netmiko exception."""


class NetmikoTimeoutException(Exception):
    """Local stand-in matched by class name, like the real Netmiko exception."""


class ReadOnlyPolicyTests(unittest.TestCase):
    def test_show_commands_are_allowed_and_normalized(self) -> None:
        self.assertEqual("show version", ensure_read_only("  show   version "))
        self.assertEqual(
            "show cdp neighbors detail", ensure_read_only("show cdp neighbors detail")
        )

    def test_write_and_config_commands_are_rejected(self) -> None:
        for command in (
            "configure terminal",
            "write memory",
            "copy running-config startup-config",
            "reload",
            "erase startup-config",
            "delete flash:config.txt",
            "no shutdown",
            "enable",
            "",
        ):
            with self.subTest(command=command):
                with self.assertRaises(ReadOnlyViolationError):
                    ensure_read_only(command)

    def test_rejected_commands_never_reach_the_device(self) -> None:
        connection = FakeConnection()
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: connection
        )
        transport.connect()
        with self.assertRaises(ReadOnlyViolationError):
            transport.execute("configure terminal")
        # Only best-effort session preparation reached the device.
        self.assertEqual(["terminal length 0"], connection.commands)


class CredentialSafetyTests(unittest.TestCase):
    def test_password_is_absent_from_credential_and_transport_repr(self) -> None:
        credentials = make_credentials()
        transport = SSHDeviceTransport(credentials)
        self.assertNotIn(PASSWORD, repr(credentials))
        self.assertNotIn(PASSWORD, str(credentials))
        self.assertNotIn(PASSWORD, repr(transport))

    def test_transport_error_messages_never_contain_the_password(self) -> None:
        def refuse(**kwargs):
            raise NetmikoAuthenticationException(
                "Authentication to device failed: bad credentials"
            )

        transport = SSHDeviceTransport(make_credentials(), connection_factory=refuse)
        with self.assertRaises(AuthenticationError) as caught:
            transport.connect()
        self.assertNotIn(PASSWORD, str(caught.exception))

    def test_credentials_require_all_fields(self) -> None:
        for overrides in ({"host": " "}, {"username": ""}, {"password": ""}, {"port": 0}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    make_credentials(**overrides)


class SSHDeviceTransportTests(unittest.TestCase):
    def test_connect_passes_device_identity_to_the_factory(self) -> None:
        seen: dict = {}

        def factory(**kwargs):
            seen.update(kwargs)
            return FakeConnection()

        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=factory
        )
        transport.connect()
        self.assertEqual("cisco_ios", seen["device_type"])
        self.assertEqual("10.0.0.10", seen["host"])
        self.assertEqual(22, seen["port"])
        self.assertEqual("atlas", seen["username"])

    def test_execute_returns_raw_output_unchanged(self) -> None:
        outputs = load_fixture_outputs()
        connection = FakeConnection(outputs)
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: connection
        )
        transport.connect()
        self.assertEqual(outputs["show version"], transport.execute("show version"))

    def test_execute_many_preserves_command_keys_and_order(self) -> None:
        connection = FakeConnection()
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: connection
        )
        commands = (
            "show version",
            "show ip interface brief",
            "show cdp neighbors detail",
        )
        with transport:
            collected = transport.execute_many(commands)
        self.assertEqual(list(commands), list(collected))
        self.assertEqual(["terminal length 0", *commands], connection.commands)
        self.assertTrue(connection.disconnected)

    def test_execute_before_connect_is_rejected(self) -> None:
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: FakeConnection()
        )
        with self.assertRaises(TransportNotConnectedError):
            transport.execute("show version")

    def test_context_manager_disconnects_after_command_failure(self) -> None:
        connection = FakeConnection(error=EOFError("session closed"))
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: connection
        )
        with self.assertRaises(ConnectionLostError):
            with transport:
                transport.execute("show version")
        self.assertTrue(connection.disconnected)

    def test_unsupported_device_type_is_rejected_locally(self) -> None:
        with self.assertRaises(UnsupportedPlatformError):
            SSHDeviceTransport(make_credentials(), device_type="juniper_junos")

    @unittest.skipUnless(
        importlib.util.find_spec("netmiko") is None, "netmiko is installed"
    )
    def test_missing_netmiko_reports_the_dependency_cleanly(self) -> None:
        transport = SSHDeviceTransport(make_credentials())
        with self.assertRaises(TransportDependencyError) as caught:
            transport.connect()
        self.assertIn("netmiko", str(caught.exception).casefold())


class FailureClassificationTests(unittest.TestCase):
    def classify_connect(self, error: Exception):
        def factory(**kwargs):
            raise error

        transport = SSHDeviceTransport(make_credentials(), connection_factory=factory)
        try:
            transport.connect()
        except Exception as raised:
            return raised
        self.fail("connect() should have raised")

    def test_authentication_failure(self) -> None:
        raised = self.classify_connect(NetmikoAuthenticationException("denied"))
        self.assertIsInstance(raised, AuthenticationError)
        self.assertIn("Authentication failed", str(raised))

    def test_connection_timeout(self) -> None:
        raised = self.classify_connect(
            NetmikoTimeoutException("Connection to device timed-out")
        )
        self.assertIsInstance(raised, ConnectionTimeoutError)

    def test_ssh_unavailable_when_refused(self) -> None:
        raised = self.classify_connect(ConnectionRefusedError("connection refused"))
        self.assertIsInstance(raised, SSHUnavailableError)

    def test_unsupported_platform_from_factory(self) -> None:
        raised = self.classify_connect(
            ValueError("Unsupported 'device_type' currently supported platforms are ...")
        )
        self.assertIsInstance(raised, UnsupportedPlatformError)

    def test_permission_denied_output_is_detected(self) -> None:
        connection = FakeConnection(
            outputs={"show version": "% Authorization failed."}
        )
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: connection
        )
        transport.connect()
        with self.assertRaises(PermissionDeniedError):
            transport.execute("show version")

    def test_unrecognized_command_output_flags_unsupported_platform(self) -> None:
        connection = FakeConnection(
            outputs={"show version": "% Invalid input detected at '^' marker."}
        )
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: connection
        )
        transport.connect()
        with self.assertRaises(UnsupportedPlatformError):
            transport.execute("show version")

    def test_connection_lost_mid_collection(self) -> None:
        connection = FakeConnection(error=OSError("Socket is closed"))
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: connection
        )
        transport.connect()
        with self.assertRaises(ConnectionLostError):
            transport.execute("show ip interface brief")


class LiveDiscoveryCompositionTests(unittest.TestCase):
    def test_transport_output_flows_through_the_existing_engine(self) -> None:
        connection = FakeConnection()
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: connection
        )
        result, graph, snapshot = run_live_discovery(transport)
        self.assertEqual("access-sw-01", result.device.hostname)
        self.assertEqual("cisco", result.device.vendor)
        self.assertEqual(4, len(result.interfaces))
        self.assertEqual(2, len(result.neighbors))
        self.assertEqual(1, graph.summary()["device_count"])
        self.assertEqual("atlas_live_discovery", snapshot.metadata["source"])
        self.assertEqual("ssh", snapshot.metadata["transport"])
        self.assertTrue(snapshot.metadata["read_only"])
        self.assertEqual(
            [
                "terminal length 0",
                "show version",
                "show ip interface brief",
                "show cdp neighbors detail",
            ],
            connection.commands,
        )
        self.assertTrue(connection.disconnected)

    def test_live_discovery_requires_a_device_transport(self) -> None:
        with self.assertRaises(TypeError):
            run_live_discovery(object())

    def test_live_discovery_disconnects_when_collection_fails(self) -> None:
        connection = FakeConnection(error=EOFError("dropped"))
        transport = SSHDeviceTransport(
            make_credentials(), connection_factory=lambda **kwargs: connection
        )
        with self.assertRaises(ConnectionLostError):
            run_live_discovery(transport)
        self.assertTrue(connection.disconnected)

    def test_fake_transport_subclass_is_accepted(self) -> None:
        outputs = load_fixture_outputs()

        class FixtureTransport(DeviceTransport):
            def connect(self) -> None:
                pass

            def disconnect(self) -> None:
                pass

            def execute(self, command: str) -> str:
                return outputs[command]

        result, _, snapshot = run_live_discovery(FixtureTransport())
        self.assertEqual("access-sw-01", result.device.hostname)
        self.assertEqual("1.0.0", snapshot.metadata["schema_version"])


if __name__ == "__main__":
    unittest.main()
