"""Packet trace (Phase 1): the topology viewer's animated path trace.

One engine, one record: /api/paths/trace runs the SAME deterministic
path investigation as the Paths page and persists to the same history,
returning per-hop verdicts the animation draws. Declared protocol/port
ride as recorded intent with the standing honesty note — ACL/firewall
policy is NOT evaluated in this phase, and the UI says so.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world

VIEWER = Path("src/founderos_atlas/visualization/templates/topology.html")


def _two_devices(client) -> tuple[str, str]:
    # build_world's Hyderabad fixture: A1 -- A2 with GW attached.
    return "A1", "A2"


class TraceApiTests(unittest.TestCase):
    def test_trace_returns_hops_and_persists_to_paths_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            source, destination = _two_devices(client)
            response = client.post("/api/paths/trace", json={
                "source": source, "destination": destination,
                "protocol": "tcp", "port": 443,
            })
            self.assertEqual(200, response.status_code)
            body = response.get_json()
            self.assertIn("hops", body)
            self.assertIn("status", body)
            for hop in body["hops"]:
                self.assertIn(
                    hop["status"], ("pass", "warning", "failed", "unknown")
                )
            # Declared intent is recorded with the honesty note.
            self.assertEqual(
                {"protocol": "tcp", "port": "443"}, body.get("intent")
            )
            self.assertIn("NOT", body.get("intent_note", ""))
            # Same record the Paths page shows.
            paths = client.get("/paths?scope=all").get_data(as_text=True)
            self.assertIn(source, paths)

    def test_validation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            no_source = client.post("/api/paths/trace", json={
                "destination": "x",
            })
            self.assertEqual(400, no_source.status_code)
            bad_protocol = client.post("/api/paths/trace", json={
                "source": "a", "destination": "b", "protocol": "gre",
            })
            self.assertEqual(400, bad_protocol.status_code)
            bad_port = client.post("/api/paths/trace", json={
                "source": "a", "destination": "b", "protocol": "tcp",
                "port": 99999,
            })
            self.assertEqual(400, bad_port.status_code)
            icmp_port = client.post("/api/paths/trace", json={
                "source": "a", "destination": "b", "protocol": "icmp",
                "port": 80,
            })
            self.assertEqual(400, icmp_port.status_code)

    def test_unknown_devices_get_an_honest_engine_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            response = client.post("/api/paths/trace", json={
                "source": "does-not-exist", "destination": "also-missing",
            })
            # The engine answers with an evidence-based unknown result,
            # not a 500 and not an invented path.
            self.assertEqual(200, response.status_code)
            body = response.get_json()
            self.assertNotEqual("connected", body.get("status"))

    def test_viewer_cannot_run_a_trace(self) -> None:
        from tests.test_production_security import (
            production_world, sign_in,
        )

        with production_world() as (app, _workdir):
            viewer, csrf = sign_in(app, "viewer")
            response = viewer.post(
                "/api/paths/trace",
                json={"source": "a", "destination": "b"},
                headers={"X-Atlas-CSRF": csrf},
            )
            self.assertEqual(403, response.status_code)


class ViewerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.viewer = VIEWER.read_text(encoding="utf-8")

    def test_right_click_sets_source_and_destination(self) -> None:
        self.assertIn("Trace packet from here", self.viewer)
        self.assertIn("Trace packet to here", self.viewer)
        self.assertIn("atlasTraceSet", self.viewer)

    def test_panel_offers_protocol_and_port(self) -> None:
        self.assertIn('id="trace-proto"', self.viewer)
        self.assertIn('id="trace-port"', self.viewer)
        # ICMP has no port; the panel enforces it like the API does.
        self.assertIn("protoSelect.value === 'icmp'", self.viewer)

    def test_animation_stops_at_the_failed_hop(self) -> None:
        self.assertIn("the packet goes no further", self.viewer)
        self.assertIn("trace-failed", self.viewer)
        self.assertIn("Stopped at ", self.viewer)

    def test_honesty_notes_are_present(self) -> None:
        # Un-evaluated hops are dashed, never painted healthy, and a
        # connected verdict caveats that port policy is not evaluated.
        self.assertIn("trace-unknown", self.viewer)
        self.assertIn("policy is not evaluated yet", self.viewer)

    def test_reduced_motion_is_respected(self) -> None:
        self.assertIn("prefers-reduced-motion", self.viewer)


if __name__ == "__main__":
    unittest.main()
