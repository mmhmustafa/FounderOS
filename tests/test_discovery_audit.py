"""PR-043.5 — Discovery Execution Audit (TRUTH): characterization tests.

These tests do NOT change behavior. They PIN the audit's measured
findings so the truths are executable evidence and any future
optimization has a regression baseline. Each test's docstring states the
finding it locks in.
"""

from __future__ import annotations

import inspect
import unittest

from founderos_atlas.discovery.multihop import MultiHopConfig
from founderos_atlas.live import run_multihop_discovery

from tests.test_multihop_discovery import ScriptedNetwork, device_outputs


def _ios_no_hostname(ip: str) -> dict:
    outputs = dict(device_outputs("r1", ip))
    # `show version` without the "<hostname> uptime is" line: hostname
    # cannot be parsed, so identity falls back to the connection address.
    outputs["show version"] = "Cisco IOS Software, Version 15.9(3)M12\n"
    return outputs


class CountSemanticsAuditTests(unittest.TestCase):
    def test_finding4_one_device_on_many_ips_inflates_when_unidentified(self) -> None:
        """FINDING 4 — device_count counts distinct device_ids. When the
        hostname parses, one physical device reached on N management-subnet
        addresses dedups to 1; when it does NOT parse, device_id falls back
        to ``<family>:<connection-ip>`` and the SAME device counts as N.
        This is the measured 9-real / 24-reported inflation mechanism."""

        addrs = ("172.20.20.20", "172.20.20.21", "172.20.20.22")

        parsed = ScriptedNetwork({ip: device_outputs("r1", ip) for ip in addrs})
        _r, _g, snap = run_multihop_discovery(
            parsed.transport_factory, addrs[0], extra_seeds=addrs[1:],
            config=MultiHopConfig(max_depth=0, max_devices=64),
        )
        self.assertEqual(1, snap.device_count)  # correct: one device

        unparsed = ScriptedNetwork({ip: _ios_no_hostname(ip) for ip in addrs})
        _r2, g2, snap2 = run_multihop_discovery(
            unparsed.transport_factory, addrs[0], extra_seeds=addrs[1:],
            config=MultiHopConfig(max_depth=0, max_devices=64),
        )
        self.assertEqual(3, snap2.device_count)  # INFLATED: one device x3
        self.assertEqual(
            [
                "cisco-ios:172.20.20.20",
                "cisco-ios:172.20.20.21",
                "cisco-ios:172.20.20.22",
            ],
            sorted(d.device_id for d in g2.devices()),
        )


class ExecutionPathAuditTests(unittest.TestCase):
    def test_finding1_fixed_gui_job_runs_the_parallel_reachable_path(self) -> None:
        """FINDING 1 (FIXED by FALCON) — the GUI job now forwards a
        ``reachability`` prober and a multi-``workers`` count into the
        multihop, and the multihop discovers each BFS wave through a
        thread pool. Production discovery is parallel and reachability-
        gated (audit's #1 recommendation)."""

        from founderos_runtime.cli import commands
        from founderos_atlas.web import routes

        cmd_src = inspect.getsource(commands.atlas_discover_command)
        self.assertIn("workers=", cmd_src)
        self.assertIn("reachability=", cmd_src)

        runner_src = inspect.getsource(routes.make_pipeline_runner)
        self.assertIn("TcpReachability", runner_src)
        self.assertIn("reachability=reachability", runner_src)

        multihop_src = inspect.getsource(
            __import__("founderos_atlas.discovery.multihop", fromlist=["x"])
            .discover_multihop
        )
        self.assertIn("ThreadPoolExecutor", multihop_src)

    def test_finding5_fixed_reachability_gate_and_fast_timeouts(self) -> None:
        """FINDING 5 (FIXED) — a lightweight TCP reachability probe now
        gates SSH, and the connect/command timeouts are aggressive
        (5s/30s) instead of 15s/60s, so dead addresses fail fast."""

        from founderos_atlas.transport.ssh import SSHDeviceTransport
        from founderos_atlas.transport.reachability import TcpReachability

        sig = inspect.signature(SSHDeviceTransport.__init__)
        self.assertEqual(5.0, sig.parameters["connect_timeout"].default)
        self.assertEqual(30.0, sig.parameters["command_timeout"].default)
        # The prober exists and probes management ports.
        probe = TcpReachability()
        self.assertIn(22, probe.ports)

    def test_finding3_fixed_live_counter_is_labelled_addresses(self) -> None:
        """FINDING 3 (FIXED) — the live counter (still `_seen_hosts`) is
        now labelled 'Addresses contacted'; the summary keeps 'Devices
        discovered' = canonical `device_count`. One value, one honest
        label each."""

        import pathlib

        html = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src" / "founderos_atlas" / "web" / "templates" / "discovery.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '<span>Addresses contacted</span><span id="job-devices">', html
        )

    def test_finding10_queue_is_now_wave_parallel(self) -> None:
        """FINDING 10 (FIXED) — the multihop no longer drains one host at a
        time; it processes each BFS wave through a worker pool, integrating
        results in deterministic FIFO order."""

        from founderos_atlas.discovery import multihop

        source = inspect.getsource(multihop.discover_multihop)
        self.assertIn("wave = list(queue)", source)
        self.assertIn("ThreadPoolExecutor", source)


if __name__ == "__main__":
    unittest.main()
