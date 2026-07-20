"""Packet trace (Phase 3): live validation by a real traceroute.

The probe is the console's case, not the engine's: an operator
explicitly asks Atlas to run ONE active command on a device it has
authenticated to, gated as console.use and audited like a console
connection. The observed path overlays the prediction; silent hops and
unnameable addresses make the verdict inconclusive, never confirmed.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.console import (
    ProbeUnsupported,
    parse_service_result,
    parse_traceroute,
    platform_family,
    probe_hint,
    service_command,
    traceroute_command,
)
from founderos_atlas.console.probe import dataplane_address, run_probe_command

from tests.test_packet_trace import VIEWER
from tests.test_polish import build_world


IOS_TRACEROUTE = """\
Type escape sequence to abort.
Tracing the route to 10.0.0.2
VRF info: (vrf in name/id, vrf out name/id)
  1 10.0.0.2 4 msec 2 msec 1 msec
"""


class FakeChannelFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeSSHClient:
    """The paramiko surface run_probe_command touches, scripted."""

    def __init__(self, holder: dict) -> None:
        self._holder = holder
        self.commands: list[str] = []
        self.closed = False

    def set_missing_host_key_policy(self, policy) -> None:
        self._holder["policy"] = policy

    def connect(self, **kwargs) -> None:
        self._holder["connect"] = kwargs

    def exec_command(self, command: str, timeout=None):
        self.commands.append(command)
        self._holder["commands"] = self.commands
        stderr = self._holder.get("stderr")
        # The path probe and the service probe are different questions;
        # the double answers each in its own words.
        if command.startswith("traceroute"):
            body = self._holder["output"]
        else:
            body = self._holder.get(
                "service_output", "nc: connect to host port: Connection refused"
            )
        return (
            None,
            FakeChannelFile(body.encode()),
            FakeChannelFile(stderr.encode()) if stderr else None,
        )

    def close(self) -> None:
        self.closed = True


class TracerouteParserTests(unittest.TestCase):
    def test_ios_output_yields_addressed_hops(self) -> None:
        hops = parse_traceroute(IOS_TRACEROUTE)
        self.assertEqual(1, len(hops))
        self.assertEqual((1, "10.0.0.2"), (hops[0].index, hops[0].address))

    def test_silent_hops_are_none_never_invented(self) -> None:
        hops = parse_traceroute(
            "Tracing the route to 10.0.0.9\n"
            "  1 10.0.1.1 2 msec 1 msec 1 msec\n"
            "  2  *  *  *\n"
            "  3 10.0.0.9 5 msec 4 msec 4 msec\n"
        )
        self.assertEqual(
            [(1, "10.0.1.1"), (2, None), (3, "10.0.0.9")],
            [(hop.index, hop.address) for hop in hops],
        )

    def test_linux_style_output_parses_too(self) -> None:
        hops = parse_traceroute(
            "traceroute to 10.0.0.2 (10.0.0.2), 30 hops max\n"
            " 1  10.0.1.1 (10.0.1.1)  0.431 ms  0.402 ms\n"
        )
        self.assertEqual((1, "10.0.1.1"), (hops[0].index, hops[0].address))

    def test_probe_command_is_address_only_never_free_text(self) -> None:
        self.assertEqual("traceroute 10.0.0.2", traceroute_command("10.0.0.2"))
        with self.assertRaises(ValueError):
            traceroute_command("10.0.0.2; reload")
        with self.assertRaises(ValueError):
            traceroute_command("evil-hostname")


class RunProbeCommandTests(unittest.TestCase):
    def test_scripted_client_round_trip(self) -> None:
        holder: dict = {"output": IOS_TRACEROUTE}
        clients: list[FakeSSHClient] = []

        def factory() -> FakeSSHClient:
            client = FakeSSHClient(holder)
            clients.append(client)
            return client

        output = run_probe_command(
            host="10.0.0.1",
            port=22,
            username="atlas",
            password="secret",
            command="traceroute 10.0.0.2",
            host_key_store=None,
            client_factory=factory,
        )
        self.assertEqual(IOS_TRACEROUTE, output)
        self.assertEqual(["traceroute 10.0.0.2"], clients[0].commands)
        self.assertTrue(clients[0].closed)
        # The secret went to connect() and nowhere else.
        self.assertEqual("secret", holder["connect"]["password"])
        self.assertFalse(holder["connect"]["allow_agent"])


class PlatformAwareCommandTests(unittest.TestCase):
    """A device's SSH session is its CLI, not a shell."""

    def test_families_are_recognised_from_snapshot_strings(self) -> None:
        self.assertEqual("frr", platform_family("frrouting", "FRRouting"))
        self.assertEqual("cisco", platform_family("cisco", "IOS-XE"))
        self.assertEqual("junos", platform_family("juniper", "Junos"))
        self.assertEqual("eos", platform_family("arista", "EOS"))
        self.assertEqual("linux", platform_family("debian", "Linux"))
        self.assertEqual("unknown", platform_family("", None))

    def test_path_probe_is_bounded_where_the_cli_allows_options(self) -> None:
        # A shell can bound the walk; a routing CLI takes the bare form
        # only and would reject flags as an unknown command.
        self.assertIn("-m 15", traceroute_command("10.0.0.2", family="linux"))
        self.assertEqual(
            "traceroute 10.0.0.2",
            traceroute_command("10.0.0.2", family="frr"),
        )
        self.assertEqual(
            "traceroute 10.0.0.2",
            traceroute_command("10.0.0.2", family="cisco"),
        )
        self.assertIn("ttl 15", traceroute_command("10.0.0.2", family="junos"))

    def test_service_probe_per_platform_and_honest_refusal(self) -> None:
        self.assertEqual(
            "nc -z -w 5 -v 10.0.0.2 443",
            service_command("10.0.0.2", 443, family="linux"),
        )
        self.assertIn(
            "telnet 10.0.0.2 443",
            service_command("10.0.0.2", 443, family="cisco"),
        )
        self.assertIn(
            "port 443", service_command("10.0.0.2", 443, family="junos")
        )
        # FRR's vtysh is a routing CLI: it cannot open a socket, and
        # Atlas says so rather than probing from somewhere else.
        with self.assertRaises(ProbeUnsupported):
            service_command("10.0.0.2", 443, family="frr")

    def test_commands_are_built_from_validated_values_only(self) -> None:
        with self.assertRaises(ValueError):
            service_command("10.0.0.2; reload", 443, family="linux")
        with self.assertRaises(ValueError):
            service_command("10.0.0.2", "443; reload", family="linux")
        with self.assertRaises(ValueError):
            service_command("10.0.0.2", 99999, family="linux")


class ServiceResultTests(unittest.TestCase):
    def test_refusal_is_kept_apart_from_silence(self) -> None:
        state, _ = parse_service_result("nc: connect refused")
        self.assertEqual("refused", state)
        state, _ = parse_service_result("10.0.0.2 443 open")
        self.assertEqual("open", state)
        state, _ = parse_service_result("Connection timed out")
        self.assertEqual("no-answer", state)
        state, evidence = parse_service_result("")
        self.assertEqual("no-answer", state)
        self.assertIn("no output", evidence)

    def test_ios_telnet_success_reads_as_open(self) -> None:
        state, _ = parse_service_result(
            "Trying 10.0.0.2, 443 ... Open\nEscape character is '^]'."
        )
        self.assertEqual("open", state)


class ProbeHintTests(unittest.TestCase):
    def test_raw_socket_denial_gets_an_actionable_remedy(self) -> None:
        hint = probe_hint(
            "traceroute: socket(AF_INET,3,1): Operation not permitted"
        )
        self.assertIsNotNone(hint)
        self.assertIn("CAP_NET_RAW", hint)

    def test_missing_command_is_explained(self) -> None:
        self.assertIn("CLI", probe_hint("% Unknown command: nc"))
        self.assertIsNone(probe_hint("1 10.0.0.2 1 ms"))


class DataplaneAddressTests(unittest.TestCase):
    """The probe must target the plane the prediction is about."""

    DEVICES = [
        {
            "hostname": "hyd-server",
            "management_ip": "172.20.20.6",
            "interfaces": [
                {"name": "eth0", "ip_address": "172.20.20.6/24"},
                {"name": "eth1", "ip_address": "10.30.1.10/24"},
                {"name": "lo", "ip_address": "10.255.0.6/32"},
            ],
        },
    ]

    def test_loopback_wins_then_any_non_management_interface(self) -> None:
        self.assertEqual(
            ("10.255.0.6", "lo"),
            dataplane_address(self.DEVICES, "hyd-server", "172.20.20.6"),
        )
        no_loopback = [dict(self.DEVICES[0])]
        no_loopback[0]["interfaces"] = self.DEVICES[0]["interfaces"][:2]
        self.assertEqual(
            ("10.30.1.10", "eth1"),
            dataplane_address(no_loopback, "hyd-server", "172.20.20.6"),
        )

    def test_management_only_devices_yield_none(self) -> None:
        management_only = [
            {
                "hostname": "hyd-server",
                "management_ip": "172.20.20.6",
                "interfaces": [
                    {"name": "eth0", "ip_address": "172.20.20.6/24"}
                ],
            }
        ]
        self.assertIsNone(
            dataplane_address(management_only, "hyd-server", "172.20.20.6")
        )
        self.assertIsNone(dataplane_address(self.DEVICES, "absent", None))


class StderrCaptureTests(unittest.TestCase):
    def test_what_the_device_said_on_stderr_is_kept(self) -> None:
        holder: dict = {"output": "", "stderr": "sh: traceroute: not found"}
        output = run_probe_command(
            host="10.0.0.1", port=22, username="atlas", password="x",
            command="traceroute 10.0.0.2", host_key_store=None,
            client_factory=lambda: FakeSSHClient(holder),
        )
        self.assertIn("[stderr] sh: traceroute: not found", output)


class ValidateLiveApiTests(unittest.TestCase):
    """build_world fixture: A1 (10.0.0.1) -- A2 (10.0.0.2), GW at 10.0.9.9."""

    def _world(self, tmp: Path):
        _, client = build_world(tmp)
        holder: dict = {"output": IOS_TRACEROUTE, "commands": []}
        shared = FakeSSHClient(holder)
        client.application.config["ATLAS_PROBE_CLIENT_FACTORY"] = (
            lambda: shared
        )
        return client, holder

    def _trace(self, client) -> None:
        response = client.post(
            "/api/paths/trace",
            json={"source": "A1", "destination": "A2"},
        )
        assert response.status_code == 200, response.status_code

    def test_probe_requires_a_recorded_prediction_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, _holder = self._world(Path(tmp))
            response = client.post(
                "/api/paths/validate-live",
                json={"source": "A1", "destination": "A2"},
            )
            self.assertEqual(409, response.status_code)
            self.assertIn("trace", response.get_json()["error"])

    def test_confirming_probe_and_audit_trail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, holder = self._world(Path(tmp))
            self._trace(client)
            response = client.post(
                "/api/paths/validate-live",
                json={"source": "A1", "destination": "A2"},
            )
            self.assertEqual(200, response.status_code)
            body = response.get_json()
            self.assertEqual("active", body["probe"])
            self.assertEqual("confirmed", body["verdict"])
            self.assertEqual("traceroute 10.0.0.2", body["command"])
            self.assertEqual("A2", body["hops"][0]["device"])
            self.assertIn("real packets", body["probe_note"])
            # The device saw exactly the address-only command.
            self.assertEqual(["traceroute 10.0.0.2"], holder["commands"])
            # Audited like a console connection — event, operator, device.
            audit = (
                Path(tmp) / ".atlas" / "console-audit.jsonl"
            ).read_text(encoding="utf-8")
            entries = [json.loads(line) for line in audit.splitlines()]
            probe_events = [
                e for e in entries if e.get("event") == "live-probe"
            ]
            self.assertTrue(probe_events)
            self.assertEqual("ok", probe_events[-1]["result"])
            self.assertEqual("A1", probe_events[-1]["hostname"])

    def test_devices_that_do_not_decrement_ttl_are_not_divergence(self) -> None:
        # A1 -- GW -- B1 in the fixture: a trace across the gateway.
        # If the probe only sees the far end (as it would when an
        # intermediate device is L2 and never answers), that is a
        # subsequence of the prediction, not a contradiction of it.
        with tempfile.TemporaryDirectory() as tmp:
            client, holder = self._world(Path(tmp))
            trace = client.post(
                "/api/paths/trace",
                json={"source": "A1", "destination": "B1"},
            ).get_json()
            self.assertIn("GW", trace["path"])
            holder["output"] = (
                "Tracing the route to 10.0.1.1\n"
                "  1 10.0.1.1 2 msec 1 msec 1 msec\n"
            )
            body = client.post(
                "/api/paths/validate-live",
                json={"source": "A1", "destination": "B1"},
            ).get_json()
            self.assertNotEqual("diverged", body["verdict"])
            self.assertEqual("confirmed", body["verdict"])
            self.assertIn("did not answer", body["verdict_detail"])

    def test_off_path_device_is_real_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, holder = self._world(Path(tmp))
            self._trace(client)     # A1 -> A2, direct
            holder["output"] = (
                "Tracing the route to 10.0.0.2\n"
                "  1 10.0.9.9 3 msec 2 msec 2 msec\n"
                "  2 10.0.0.2 3 msec 2 msec 2 msec\n"
            )
            body = client.post(
                "/api/paths/validate-live",
                json={"source": "A1", "destination": "A2"},
            ).get_json()
            self.assertEqual("diverged", body["verdict"])
            self.assertIn("never routes through", body["verdict_detail"])

    def test_divergence_is_reported_with_the_observed_device(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, holder = self._world(Path(tmp))
            self._trace(client)
            holder["output"] = (
                "Tracing the route to 10.0.0.2\n"
                "  1 10.0.9.9 3 msec 2 msec 2 msec\n"
            )
            body = client.post(
                "/api/paths/validate-live",
                json={"source": "A1", "destination": "A2"},
            ).get_json()
            self.assertEqual("diverged", body["verdict"])
            self.assertIn("10.0.9.9", body["verdict_detail"])
            self.assertIn("GW", body["verdict_detail"])

    def test_silence_is_inconclusive_never_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, holder = self._world(Path(tmp))
            self._trace(client)
            holder["output"] = (
                "Tracing the route to 10.0.0.2\n  1  *  *  *\n"
            )
            body = client.post(
                "/api/paths/validate-live",
                json={"source": "A1", "destination": "A2"},
            ).get_json()
            self.assertEqual("inconclusive", body["verdict"])
            self.assertIn("did not reply", body["verdict_detail"])

    def test_declared_port_triggers_a_real_service_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, holder = self._world(Path(tmp))
            # A trace that declared TCP/443 asks two questions.
            client.post("/api/paths/trace", json={
                "source": "A1", "destination": "A2",
                "protocol": "tcp", "port": 443,
            })
            holder["output"] = (
                "Tracing the route to 10.0.0.2\n"
                "  1 10.0.0.2 1 msec 1 msec 1 msec\n"
            )
            body = client.post(
                "/api/paths/validate-live",
                json={"source": "A1", "destination": "A2"},
            ).get_json()
            service = body["service"]
            self.assertIsNotNone(service)
            # Both questions were asked: path, then port.
            self.assertEqual(2, len(holder["commands"]))
            self.assertIn("443", holder["commands"][1])
            # The refusal is read as the service, not the path.
            self.assertEqual("refused", service["state"])
            self.assertIn("not the path", service["detail"])

    def test_no_declared_port_asks_no_service_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, holder = self._world(Path(tmp))
            self._trace(client)
            body = client.post(
                "/api/paths/validate-live",
                json={"source": "A1", "destination": "A2"},
            ).get_json()
            self.assertIsNone(body["service"])
            self.assertEqual(1, len(holder["commands"]))

    def test_empty_device_output_is_said_out_loud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, holder = self._world(Path(tmp))
            self._trace(client)
            holder["output"] = ""
            body = client.post(
                "/api/paths/validate-live",
                json={"source": "A1", "destination": "A2"},
            ).get_json()
            self.assertEqual("inconclusive", body["verdict"])
            self.assertIn("no traceroute hops", body["verdict_detail"])


class ProbePermissionTests(unittest.TestCase):
    def test_probe_is_console_tier_not_investigate_tier(self) -> None:
        from tests.test_production_security import production_world, sign_in

        with production_world() as (app, _workdir):
            for username in ("viewer", "investigator"):
                client, csrf = sign_in(app, username)
                response = client.post(
                    "/api/paths/validate-live",
                    json={"source": "a", "destination": "b"},
                    headers={"X-Atlas-CSRF": csrf},
                )
                self.assertEqual(403, response.status_code, username)
            # network-operator holds console.use: the gate opens (the
            # request then fails honestly on having no recorded trace).
            operator, csrf = sign_in(app, "operator")
            response = operator.post(
                "/api/paths/validate-live",
                json={"source": "a", "destination": "b"},
                headers={"X-Atlas-CSRF": csrf},
            )
            self.assertEqual(409, response.status_code)


class ViewerLiveContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.viewer = VIEWER.read_text(encoding="utf-8")

    def test_validate_live_button_is_labeled_as_an_active_probe(self) -> None:
        self.assertIn('id="trace-live"', self.viewer)
        self.assertIn("Validate live", self.viewer)
        self.assertIn("ACTIVE PROBE", self.viewer)
        self.assertIn("sends live packets", self.viewer)

    def test_overlay_draws_observed_path_distinctly(self) -> None:
        self.assertIn("trace-actual", self.viewer)
        self.assertIn("/api/paths/validate-live", self.viewer)
        # A 403 explains the console-permission requirement.
        self.assertIn("console permission", self.viewer)

    def test_raw_probe_output_is_shown_to_the_operator(self) -> None:
        self.assertIn('id="trace-live-output"', self.viewer)
        self.assertIn("Probe output", self.viewer)
        self.assertIn("the device returned no output", self.viewer)

    def test_service_answer_is_reported_beside_the_path_answer(self) -> None:
        # Two questions, two sentences — neither masks the other.
        self.assertIn("Service check: ", self.viewer)
        self.assertIn("body.service", self.viewer)


if __name__ == "__main__":
    unittest.main()
