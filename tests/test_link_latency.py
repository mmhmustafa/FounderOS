"""The opt-in active latency pass: ping each link, read the RTT.

This is not read-only discovery — it sends packets, and it is the console
case, gated like the live traceroute. These tests exercise the
orchestration with an injected command runner, so no real SSH or ICMP is
involved; the honesty rules are what they pin — one bad link never kills
the pass, and an unmeasured link records absence, never a zero.
"""

from __future__ import annotations

import unittest

from founderos_atlas.console.latency import (
    LinkProbe,
    apply_latency_to_edges,
    measure_link_latency,
)


def _probe(local: str, remote: str, target: str, platform: str = "frr") -> LinkProbe:
    return LinkProbe(
        local_device_id=local, remote_hostname=remote,
        host="10.0.0.1", port=22, username="atlas", password="secret",
        target_ip=target, platform=platform,
    )


class MeasurementTests(unittest.TestCase):
    def test_the_average_rtt_of_each_link_is_recorded(self) -> None:
        outputs = {
            "10.255.0.2": "round-trip min/avg/max = 5.9/12.1/12.7 ms",
            "172.30.0.2": "rtt min/avg/max/mdev = 0.4/0.5/0.6/0.1 ms",
        }

        def runner(**kwargs):
            for ip, text in outputs.items():
                if ip in kwargs["command"]:
                    return text
            return ""

        result = measure_link_latency(
            [_probe("frr:wan-pe1", "wan-pe2", "10.255.0.2"),
             _probe("frr:core", "sw1", "172.30.0.2")],
            host_key_store=object(), run_command=runner,
        )
        by_remote = {m.remote_hostname: m.rtt_ms for m in result}
        self.assertEqual(12.1, by_remote["wan-pe2"])
        self.assertEqual(0.5, by_remote["sw1"])

    def test_the_ping_is_run_from_the_devices_own_cli(self) -> None:
        """Device-to-device: the command reaches the LOCAL device and pings
        the neighbour's address — distance between them, not from Atlas."""

        seen = {}

        def runner(**kwargs):
            seen["host"] = kwargs["host"]
            seen["command"] = kwargs["command"]
            return "round-trip min/avg/max = 1/2/3 ms"

        measure_link_latency(
            [_probe("frr:wan-pe1", "wan-pe2", "10.255.0.2")],
            host_key_store=object(), run_command=runner,
        )
        self.assertEqual("10.0.0.1", seen["host"])     # the local device
        self.assertIn("10.255.0.2", seen["command"])   # pinging the neighbour
        self.assertIn("ping", seen["command"])

    def test_one_unreachable_link_never_kills_the_pass(self) -> None:
        def runner(**kwargs):
            if "10.255.0.2" in kwargs["command"]:
                raise RuntimeError("connection refused")
            return "round-trip min/avg/max = 1/2/3 ms"

        result = measure_link_latency(
            [_probe("frr:a", "b", "10.255.0.2"),
             _probe("frr:c", "d", "172.30.0.2")],
            host_key_store=object(), run_command=runner,
        )
        byr = {m.remote_hostname: m for m in result}
        self.assertIsNone(byr["b"].rtt_ms)
        self.assertIn("could not reach", byr["b"].detail)
        self.assertEqual(2.0, byr["d"].rtt_ms)   # the other link still measured

    def test_a_link_that_answers_no_timing_records_absence(self) -> None:
        def runner(**kwargs):
            return "3 packets transmitted, 0 received, 100% packet loss"

        result = measure_link_latency(
            [_probe("frr:a", "b", "10.0.0.9")],
            host_key_store=object(), run_command=runner,
        )
        self.assertIsNone(result[0].rtt_ms)   # not a zero


class ApplyToEdgesTests(unittest.TestCase):
    def test_a_measurement_lands_on_its_own_edge(self) -> None:
        edges = [
            {"local_device_id": "frr:wan-pe1", "remote_hostname": "wan-pe2",
             "metadata": {"source_command": "show lldp neighbors"}},
            {"local_device_id": "frr:core", "remote_hostname": "sw1",
             "metadata": {}},
        ]
        result = measure_link_latency(
            [_probe("frr:wan-pe1", "wan-pe2", "10.255.0.2")],
            host_key_store=object(),
            run_command=lambda **k: "round-trip min/avg/max = 5/12.1/13 ms",
        )
        out = apply_latency_to_edges(edges, result)
        self.assertEqual(12.1, out[0]["metadata"]["rtt_ms"])
        # The measurement is added, not a replacement of existing evidence.
        self.assertEqual("show lldp neighbors",
                         out[0]["metadata"]["source_command"])
        # An unmeasured edge is left exactly as it was.
        self.assertNotIn("rtt_ms", out[1]["metadata"])


if __name__ == "__main__":
    unittest.main()
