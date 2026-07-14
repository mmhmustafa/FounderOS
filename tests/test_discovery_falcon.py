"""Acceptance tests for PR-043.6 — Production Discovery Acceleration (FALCON).

Validates the audit's fixes: the production path runs concurrently
through the multihop worker pool; a lightweight TCP reachability probe
gates SSH so dead addresses never pay a connect timeout; serial-number
identity normalization collapses one physical device reached on several
addresses into one canonical device; and metrics stay honest.
"""

from __future__ import annotations

import threading
import time
import unittest

from founderos_atlas.discovery.multihop import MultiHopConfig, discover_multihop
from founderos_atlas.live import run_multihop_discovery
from founderos_atlas.transport.reachability import TcpReachability

from tests.test_multihop_discovery import ScriptedNetwork, device_outputs


def _ios_serial_no_hostname(ip: str, serial: str) -> dict:
    outputs = dict(device_outputs("r1", ip))
    outputs["show version"] = (
        f"Cisco IOS Software, Version 15.9(3)M12\nProcessor board ID {serial}\n"
    )
    return outputs


class ReachabilityTests(unittest.TestCase):
    def test_probe_gates_ssh_dead_addresses_never_connect(self) -> None:
        """A host that fails the reachability probe is never handed to the
        transport — no SSH attempt, no timeout."""

        network = ScriptedNetwork(
            {"10.0.0.1": device_outputs("r1", "10.0.0.1")}
        )
        alive = {"10.0.0.1"}

        class FakeReach:
            def is_reachable(self, host):
                return host in alive

        report = discover_multihop(
            "10.0.0.1", network.transport_factory,
            extra_seeds=("10.0.0.9", "10.0.0.10"),  # dead
            reachability=FakeReach(),
            config=MultiHopConfig(max_depth=0, max_devices=64),
        )
        # Dead addresses failed via the probe, never via SSH.
        self.assertNotIn("10.0.0.9", network.connect_attempts)
        self.assertNotIn("10.0.0.10", network.connect_attempts)
        self.assertEqual(["10.0.0.1"], network.connect_attempts)
        self.assertEqual(1, len(report.connected))
        self.assertEqual(2, len(report.failed))
        self.assertIn("reachability probe", report.failed[0].detail)

    def test_tcp_reachability_uses_injected_connector(self) -> None:
        seen = []

        def connector(host, port, timeout):
            seen.append((host, port))
            return host == "10.0.0.1" and port == 22

        probe = TcpReachability(ports=(22, 443), timeout=0.1, connector=connector)
        self.assertTrue(probe.is_reachable("10.0.0.1"))
        self.assertFalse(probe.is_reachable("10.0.0.9"))
        self.assertIn(("10.0.0.9", 22), seen)
        self.assertIn(("10.0.0.9", 443), seen)  # tried all ports


class ParallelismTests(unittest.TestCase):
    def test_a_wave_executes_concurrently(self) -> None:
        """Four seed candidates in one wave run simultaneously: with a
        blocking barrier, all four must be in-flight at once — impossible
        if execution were sequential."""

        addrs = [f"10.0.0.{i}" for i in range(1, 5)]
        network = ScriptedNetwork({a: device_outputs(f"r{a[-1]}", a) for a in addrs})
        barrier = threading.Barrier(4, timeout=5)
        real = network.transport_factory

        def barrier_factory(host):
            transport = real(host)
            original = transport.connect

            def gated():
                barrier.wait()  # only proceeds if all 4 arrive together
                return original()

            transport.connect = gated
            return transport

        report = discover_multihop(
            addrs[0], barrier_factory, extra_seeds=tuple(addrs[1:]),
            workers=4, config=MultiHopConfig(max_depth=0, max_devices=64),
        )
        self.assertEqual(4, len(report.connected))  # barrier proves concurrency

    def test_parallel_is_faster_than_sequential_on_slow_connects(self) -> None:
        addrs = [f"10.0.0.{i}" for i in range(1, 13)]
        base = {a: device_outputs(f"r{a.split('.')[-1]}", a) for a in addrs}

        def make(delay):
            network = ScriptedNetwork(dict(base))
            real = network.transport_factory

            def factory(host):
                t = real(host)
                oc = t.connect

                def slow():
                    time.sleep(delay)
                    return oc()

                t.connect = slow
                return t

            return factory

        start = time.perf_counter()
        discover_multihop(addrs[0], make(0.05), extra_seeds=tuple(addrs[1:]),
                          workers=1, config=MultiHopConfig(max_depth=0, max_devices=64))
        sequential = time.perf_counter() - start

        start = time.perf_counter()
        discover_multihop(addrs[0], make(0.05), extra_seeds=tuple(addrs[1:]),
                          workers=8, config=MultiHopConfig(max_depth=0, max_devices=64))
        parallel = time.perf_counter() - start
        self.assertLess(parallel, sequential / 2)

    def test_wave_parallel_output_matches_sequential(self) -> None:
        addrs = [f"10.0.0.{i}" for i in range(1, 8)]
        base = {a: device_outputs(f"r{a.split('.')[-1]}", a) for a in addrs}
        seq = discover_multihop(
            addrs[0], ScriptedNetwork(dict(base)).transport_factory,
            extra_seeds=tuple(addrs[1:]), workers=1,
            config=MultiHopConfig(max_depth=0, max_devices=64),
        )
        par = discover_multihop(
            addrs[0], ScriptedNetwork(dict(base)).transport_factory,
            extra_seeds=tuple(addrs[1:]), workers=8,
            config=MultiHopConfig(max_depth=0, max_devices=64),
        )
        # Byte-identical visits and results — only wall-time differs.
        self.assertEqual(
            [(v.host, v.status) for v in seq.visits],
            [(v.host, v.status) for v in par.visits],
        )
        self.assertEqual(
            [r.device.device_id for r in seq.results],
            [r.device.device_id for r in par.results],
        )


class IdentityNormalizationTests(unittest.TestCase):
    def test_serial_collapses_one_device_on_many_addresses(self) -> None:
        """The audited 9→24 case: one device reached on three addresses,
        hostname unparsed (id falls back to connection IP) but SERIAL
        present → ONE canonical device (was three)."""

        addrs = ("172.20.20.20", "172.20.20.21", "172.20.20.22")
        network = ScriptedNetwork(
            {ip: _ios_serial_no_hostname(ip, "SER-SHARED") for ip in addrs}
        )
        _r, _g, snap = run_multihop_discovery(
            network.transport_factory, addrs[0], extra_seeds=addrs[1:],
            workers=4, config=MultiHopConfig(max_depth=0, max_devices=64),
        )
        self.assertEqual(1, snap.device_count)  # collapsed by serial

    def test_distinct_serials_stay_distinct(self) -> None:
        """Different devices (different serials) are never merged."""

        network = ScriptedNetwork(
            {
                "10.0.0.1": _ios_serial_no_hostname("10.0.0.1", "SER-A"),
                "10.0.0.2": _ios_serial_no_hostname("10.0.0.2", "SER-B"),
            }
        )
        _r, _g, snap = run_multihop_discovery(
            network.transport_factory, "10.0.0.1", extra_seeds=("10.0.0.2",),
            workers=2, config=MultiHopConfig(max_depth=0, max_devices=64),
        )
        self.assertEqual(2, snap.device_count)


if __name__ == "__main__":
    unittest.main()
