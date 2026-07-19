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

from founderos_atlas.console import parse_traceroute, traceroute_command
from founderos_atlas.console.probe import run_probe_command

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
        return None, FakeChannelFile(self._holder["output"].encode()), None

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


class ValidateLiveApiTests(unittest.TestCase):
    """build_world fixture: A1 (10.0.0.1) -- A2 (10.0.0.2), GW at 10.0.9.9."""

    def _world(self, tmp: Path):
        _, client = build_world(tmp)
        holder: dict = {"output": IOS_TRACEROUTE}
        client.application.config["ATLAS_PROBE_CLIENT_FACTORY"] = (
            lambda: FakeSSHClient(holder)
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


if __name__ == "__main__":
    unittest.main()
