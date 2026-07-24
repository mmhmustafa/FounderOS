"""The opt-in latency pass, driven through its HTTP endpoint.

The measurement primitive is unit-tested in test_link_latency; here the
whole route is exercised against a discovered scope with a scripted SSH
client (no real packets): the readings land on the snapshot's edges, the
content address is re-minted so the mutated snapshot is not rejected as
tampered, the pass is audited like a console connection, and the
Enterprise scope is refused because latency is measured per network from
each device's own console.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tests.test_packet_trace_live import FakeSSHClient
from tests.test_polish import build_world


class MeasureLatencyEndpointTests(unittest.TestCase):
    def _world(self, tmp: Path):
        service, client = build_world(tmp)
        holder = {
            "ping_output": "round-trip min/avg/max = 5.0/12.1/13.0 ms",
            "commands": [],
        }
        shared = FakeSSHClient(holder)
        client.application.config["ATLAS_PROBE_CLIENT_FACTORY"] = lambda: shared
        scope_id = service.list_profiles()[0].profile_id
        return client, holder, scope_id

    def test_enterprise_scope_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client, _holder, _scope = self._world(Path(tmp))
            response = client.post("/api/topology/measure-latency?scope=all")
            self.assertEqual(409, response.status_code)
            self.assertIn("per network", response.get_json()["error"])

    def test_readings_land_on_edges_and_the_snapshot_re_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client, holder, scope_id = self._world(workdir)

            response = client.post(
                f"/api/topology/measure-latency?scope={scope_id}"
            )
            self.assertEqual(200, response.status_code, response.get_json())
            body = response.get_json()
            self.assertEqual("active", body["probe"])
            self.assertGreaterEqual(body["measured"], 1)
            # The scripted link answers 12.1 ms both ways.
            self.assertEqual(12.1, body["rtt_ms_max"])
            self.assertEqual(12.1, body["rtt_ms_min"])
            # The device saw a real ping command, address-only.
            self.assertTrue(any("ping" in c for c in holder["commands"]))

            # The reading is written onto an edge's metadata, and the
            # rewritten snapshot still loads (content address re-minted).
            from founderos_atlas.topology.snapshot import TopologySnapshot

            snapshot_path = next(workdir.rglob("topology_snapshot.json"))
            raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot = TopologySnapshot.from_dict(raw)  # would raise if tampered
            measured_edges = [
                edge for edge in snapshot.edges
                if (edge.get("metadata") or {}).get("rtt_ms") is not None
            ]
            self.assertTrue(measured_edges)
            self.assertEqual(12.1, measured_edges[0]["metadata"]["rtt_ms"])

    def test_the_pass_is_audited_like_a_console_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client, _holder, scope_id = self._world(workdir)
            client.post(f"/api/topology/measure-latency?scope={scope_id}")

            audit_path = workdir / ".atlas" / "console-audit.jsonl"
            entries = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            latency_events = [
                e for e in entries if e.get("event") == "latency-probe"
            ]
            self.assertTrue(latency_events)
            self.assertEqual("ok", latency_events[-1]["result"])
            # A reference names the secret; the secret itself never lands here.
            self.assertNotIn("password", latency_events[-1])

    def test_a_scope_with_no_topology_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, client = build_world(Path(tmp), discover=False)
            scope_id = service.list_profiles()[0].profile_id
            response = client.post(
                f"/api/topology/measure-latency?scope={scope_id}"
            )
            self.assertEqual(409, response.status_code)


class WizardOptInSurfaceTests(unittest.TestCase):
    def test_wizard_offers_the_opt_in_and_discovery_shows_the_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _service, client = build_world(Path(tmp))
            wizard = client.get("/discovery/wizard").get_data(as_text=True)
            self.assertIn('name="measure_latency"', wizard)
            page = client.get("/discovery").get_data(as_text=True)
            self.assertIn('id="summary-latency-row"', page)


if __name__ == "__main__":
    unittest.main()
