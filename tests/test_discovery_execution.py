"""Acceptance tests for PR-043.3 — the Discovery Execution Engine (TURBO).

Discovery correctness, platform drivers, and canonical models are
unchanged; these tests exercise EXECUTION: the worker pool, deterministic
lifecycle transitions, pause/resume/cancel, resume-skips-completed, the
per-stage instrumentation and aggregate metrics, fast-fail on dead
addresses, and the measured parallel speedup over sequential execution.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.discovery.executor import (
    OUTCOME_AUTH_FAILED,
    OUTCOME_DISCOVERED,
    OUTCOME_UNREACHABLE,
    STATE_CANCELLED,
    STATE_COMPLETED,
    STATE_DEEP,
    STATE_INVENTORY,
    STATE_PAUSED,
    STATE_QUEUED,
    STATE_RUNNING,
    STATE_STARTING,
    CandidateMetrics,
    DiscoveryExecution,
    StageTimer,
    aggregate_metrics,
    can_transition,
    run_pool,
)
from founderos_atlas.live import run_pooled_discovery

from tests.test_multihop_discovery import ScriptedNetwork, device_outputs
from tests.test_platforms import frr_outputs


# -- deterministic instrumentation ---------------------------------------------

class FakeClock:
    """A monotonic clock that advances by a fixed step on each read —
    deterministic for single-threaded timing assertions."""

    def __init__(self, step: float = 1.0) -> None:
        self._t = 0.0
        self._step = step

    def __call__(self) -> float:
        self._t += self._step
        return self._t


class StageTimerTests(unittest.TestCase):
    def test_stage_durations_use_the_injected_clock(self) -> None:
        clock = FakeClock(step=1.0)
        timer = StageTimer("10.0.0.1", clock)  # start reads t=1
        with timer.stage("tcp_connect"):        # 2 -> 3 => 1.0
            pass
        with timer.stage("authentication"):     # 4 -> 5 => 1.0
            pass
        metrics = timer.finish(OUTCOME_DISCOVERED, platform="ios")  # t=6
        self.assertEqual(1.0, metrics.stages["tcp_connect"])
        self.assertEqual(1.0, metrics.stages["authentication"])
        self.assertEqual(5.0, metrics.total_seconds)  # 6 - 1
        self.assertEqual("ios", metrics.platform)

    def test_aggregate_metrics_are_honest_counts(self) -> None:
        metrics = [
            CandidateMetrics("a", {"authentication": 0.2, "platform_detection": 0.1},
                             1.0, OUTCOME_DISCOVERED, "ios"),
            CandidateMetrics("b", {"authentication": 0.4, "platform_detection": 0.3},
                             2.0, OUTCOME_DISCOVERED, "frr"),
            CandidateMetrics("c", {}, 0.05, OUTCOME_UNREACHABLE),
            CandidateMetrics("d", {"authentication": 0.1}, 0.3, OUTCOME_AUTH_FAILED),
        ]
        agg = aggregate_metrics(metrics, elapsed_seconds=3.0, worker_count=4)
        self.assertEqual(4, agg.addresses_evaluated)
        self.assertEqual(2, agg.discovered)
        self.assertEqual(1, agg.unreachable)
        self.assertEqual(1, agg.auth_failed)
        self.assertEqual(1.5, agg.average_discovery_seconds)  # (1+2)/2
        self.assertAlmostEqual(40.0, agg.devices_per_minute)  # 2/3*60
        self.assertEqual("authentication", agg.slowest_stage)
        d = agg.to_dict()
        self.assertEqual(2, d["discovered"])
        self.assertEqual(1, d["authentication_failures"])

    def test_operational_metrics_worker_utilization_and_ssh(self) -> None:
        # 2 candidates each 1.0s busy; elapsed 1.0s across 2 workers =>
        # busy 2.0 / available 2.0 = 100% utilization.
        metrics = [
            CandidateMetrics("a", {"tcp_connect": 0.3}, 1.0, OUTCOME_DISCOVERED, "ios"),
            CandidateMetrics("b", {"tcp_connect": 0.5}, 1.0, OUTCOME_DISCOVERED, "ios"),
        ]
        agg = aggregate_metrics(metrics, elapsed_seconds=1.0, worker_count=2)
        self.assertEqual(1.0, agg.worker_utilization)
        self.assertEqual(100, agg.to_dict()["worker_utilization_percent"])
        self.assertAlmostEqual(0.4, agg.average_ssh_seconds)  # (0.3+0.5)/2
        # Half-idle: 2 busy-seconds over 4 available = 50%.
        agg2 = aggregate_metrics(metrics, elapsed_seconds=2.0, worker_count=2)
        self.assertEqual(50, agg2.to_dict()["worker_utilization_percent"])


class LifecycleTests(unittest.TestCase):
    def test_transitions_are_deterministic_and_gated(self) -> None:
        self.assertTrue(can_transition(STATE_QUEUED, STATE_STARTING))
        self.assertTrue(can_transition(STATE_INVENTORY, STATE_DEEP))
        self.assertTrue(can_transition(STATE_RUNNING, STATE_PAUSED))
        self.assertTrue(can_transition(STATE_PAUSED, STATE_RUNNING))
        # Illegal jumps are refused.
        self.assertFalse(can_transition(STATE_QUEUED, STATE_COMPLETED))
        self.assertFalse(can_transition(STATE_COMPLETED, STATE_RUNNING))
        self.assertFalse(can_transition(STATE_CANCELLED, STATE_RUNNING))

    def test_execution_rejects_illegal_transitions(self) -> None:
        execution = DiscoveryExecution(["10.0.0.1"], worker_count=1)
        self.assertEqual(STATE_QUEUED, execution.state)
        self.assertFalse(execution.transition(STATE_COMPLETED))  # no skip
        self.assertTrue(execution.transition(STATE_STARTING))
        self.assertTrue(execution.transition(STATE_INVENTORY))
        self.assertTrue(execution.transition(STATE_COMPLETED))
        self.assertFalse(execution.transition(STATE_RUNNING))  # terminal


# -- worker pool ---------------------------------------------------------------

def instant_worker(address, timer):
    with timer.stage("tcp_connect"):
        pass
    return object(), OUTCOME_DISCOVERED, "ios", f"{address} inventory complete"


class WorkerPoolTests(unittest.TestCase):
    def test_every_candidate_processed_exactly_once(self) -> None:
        addresses = [f"10.0.0.{i}" for i in range(1, 21)]
        seen: list[str] = []
        lock = threading.Lock()

        def worker(address, timer):
            with lock:
                seen.append(address)
            return object(), OUTCOME_DISCOVERED, "ios", "ok"

        execution = DiscoveryExecution(addresses, worker_count=5)
        run_pool(execution, worker)
        self.assertEqual(STATE_COMPLETED, execution.state)
        self.assertEqual(sorted(addresses), sorted(seen))
        self.assertEqual(20, len(seen))  # exactly once each
        self.assertEqual(20, execution.metrics().discovered)

    def test_results_are_in_candidate_order_regardless_of_completion(self) -> None:
        addresses = ["10.0.0.3", "10.0.0.1", "10.0.0.2"]

        def worker(address, timer):
            # Reverse the completion order vs the queue order.
            time.sleep({"10.0.0.3": 0.0, "10.0.0.1": 0.02, "10.0.0.2": 0.01}[address])
            return address, OUTCOME_DISCOVERED, "ios", "ok"

        execution = DiscoveryExecution(addresses, worker_count=3)
        run_pool(execution, worker)
        self.assertEqual(addresses, execution.results_in_order())  # queue order

    def test_worker_exceptions_are_recorded_never_raised(self) -> None:
        def worker(address, timer):
            raise RuntimeError("boom")

        execution = DiscoveryExecution(["10.0.0.1"], worker_count=1)
        run_pool(execution, worker)  # must not raise
        self.assertEqual(STATE_COMPLETED, execution.state)
        self.assertEqual(1, execution.metrics().unreachable)


class ControlTests(unittest.TestCase):
    def test_cancel_stops_dequeuing_and_persists_completed(self) -> None:
        addresses = [f"10.0.0.{i}" for i in range(1, 51)]
        processed = threading.Event()
        gate = threading.Event()

        def worker(address, timer):
            processed.set()
            gate.wait(timeout=2)  # hold workers so cancel lands mid-run
            return address, OUTCOME_DISCOVERED, "ios", "ok"

        execution = DiscoveryExecution(addresses, worker_count=2)
        thread = threading.Thread(
            target=lambda: run_pool(execution, worker), daemon=True
        )
        thread.start()
        self.assertTrue(processed.wait(timeout=2))
        execution.cancel()
        gate.set()
        thread.join(timeout=3)
        self.assertEqual(STATE_CANCELLED, execution.state)
        # Not every candidate was attempted (cancel stopped dequeuing).
        self.assertLess(execution.metrics().addresses_evaluated, 50)
        # Completed work is persisted for resume.
        self.assertTrue(execution.completed_addresses())

    def test_pause_holds_then_resume_completes(self) -> None:
        addresses = [f"10.0.0.{i}" for i in range(1, 13)]
        release = threading.Event()

        def worker(address, timer):
            return address, OUTCOME_DISCOVERED, "ios", "ok"

        execution = DiscoveryExecution(addresses, worker_count=2)
        execution.pause()  # pause before starting: workers must not dequeue
        thread = threading.Thread(
            target=lambda: run_pool(execution, worker), daemon=True
        )
        thread.start()
        time.sleep(0.1)
        # Paused: nothing processed yet.
        self.assertEqual(0, execution.metrics().addresses_evaluated)
        self.assertTrue(execution.is_paused)
        execution.resume()
        thread.join(timeout=3)
        self.assertEqual(STATE_COMPLETED, execution.state)
        self.assertEqual(12, execution.metrics().discovered)


class ResumeTests(unittest.TestCase):
    def test_completed_candidates_are_not_reattempted(self) -> None:
        addresses = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
        attempted: list[str] = []
        lock = threading.Lock()

        def worker(address, timer):
            with lock:
                attempted.append(address)
            return address, OUTCOME_DISCOVERED, "ios", "ok"

        execution = DiscoveryExecution(
            addresses, worker_count=2, completed={"10.0.0.2"}
        )
        # At construction, one candidate is already cached and only two
        # remain pending — resume attempts only the unfinished work.
        self.assertEqual(1, execution.queue_snapshot()["completed_cached"])
        self.assertEqual(2, execution.queue_snapshot()["pending"])
        run_pool(execution, worker)
        # The cached candidate was never handed to a worker.
        self.assertNotIn("10.0.0.2", attempted)
        self.assertEqual({"10.0.0.1", "10.0.0.3"}, set(attempted))
        # It remains part of the completed set for the graph; all three
        # are now complete.
        self.assertIn("10.0.0.2", execution.completed_addresses())
        self.assertEqual(3, execution.queue_snapshot()["completed_cached"])

    def test_snapshot_is_serializable_without_secrets(self) -> None:
        import json

        execution = DiscoveryExecution(["10.0.0.1"], worker_count=1)
        run_pool(execution, instant_worker)
        snapshot = execution.snapshot()
        text = json.dumps(snapshot)
        self.assertNotIn("password", text.lower())
        self.assertIn("state", snapshot)
        self.assertIn("metrics", snapshot)
        self.assertIn("workers", snapshot)
        self.assertIn("queue", snapshot)


# -- pooled live discovery + performance ---------------------------------------

def slow_network(count: int, delay: float) -> tuple[ScriptedNetwork, list[str]]:
    """A management network of `count` IOS devices, each `delay`s to connect."""

    topology = {}
    addresses = []
    for i in range(1, count + 1):
        address = f"10.0.0.{i}"
        addresses.append(address)
        topology[address] = device_outputs(f"r{i}", address)
    network = ScriptedNetwork(topology)
    real_factory = network.transport_factory

    def delayed_factory(host: str):
        transport = real_factory(host)
        original_connect = transport.connect

        def slow_connect():
            time.sleep(delay)
            return original_connect()

        transport.connect = slow_connect
        return transport

    return delayed_factory, addresses


class PooledDiscoveryTests(unittest.TestCase):
    def test_pool_discovers_a_management_network_into_one_graph(self) -> None:
        factory, addresses = slow_network(6, delay=0.0)
        execution, graph, snapshot = run_pooled_discovery(
            addresses, factory, worker_count=4
        )
        self.assertEqual(STATE_COMPLETED, execution.state)
        self.assertEqual(6, snapshot.device_count)
        self.assertEqual(6, execution.metrics().discovered)
        self.assertEqual({"ios": 6}, dict(snapshot.metadata["platforms"]))

    def test_mixed_platform_pool(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs("r1", "10.0.0.1"),
                "10.0.0.2": device_outputs("r2", "10.0.0.2"),
                "10.20.0.1": frr_outputs("delhi-r1", "10.20.0.1"),
            }
        )
        _execution, _graph, snapshot = run_pooled_discovery(
            ["10.0.0.1", "10.0.0.2", "10.20.0.1"],
            network.transport_factory,
            worker_count=3,
        )
        self.assertEqual({"frr": 1, "ios": 2}, dict(snapshot.metadata["platforms"]))

    def test_dead_addresses_are_unreachable_not_crashes(self) -> None:
        network = ScriptedNetwork(
            {"10.0.0.1": device_outputs("r1", "10.0.0.1")},
            unreachable=frozenset({"10.0.0.9"}),
        )
        execution, _graph, snapshot = run_pooled_discovery(
            ["10.0.0.1", "10.0.0.9"], network.transport_factory, worker_count=2
        )
        metrics = execution.metrics()
        self.assertEqual(1, metrics.discovered)
        self.assertEqual(1, metrics.unreachable)
        self.assertEqual(1, snapshot.device_count)

    def test_pooled_output_matches_sequential_evidence(self) -> None:
        import json

        factory, addresses = slow_network(5, delay=0.0)
        _e1, _g1, s1 = run_pooled_discovery(addresses, factory, worker_count=1)
        factory2, _ = slow_network(5, delay=0.0)
        _e2, _g2, s2 = run_pooled_discovery(addresses, factory2, worker_count=5)
        # Same evidence, same reconciled snapshot regardless of worker count.
        self.assertEqual(
            {d["hostname"] for d in s1.devices},
            {d["hostname"] for d in s2.devices},
        )
        self.assertEqual(s1.device_count, s2.device_count)

    def test_parallel_is_faster_than_sequential(self) -> None:
        """Before/after: I/O-bound candidates parallelize near-linearly."""

        count, delay = 12, 0.05

        factory1, addresses = slow_network(count, delay)
        start = time.perf_counter()
        run_pooled_discovery(addresses, factory1, worker_count=1)
        sequential = time.perf_counter() - start

        factory8, addresses = slow_network(count, delay)
        start = time.perf_counter()
        run_pooled_discovery(addresses, factory8, worker_count=8)
        parallel = time.perf_counter() - start

        # Sequential pays ~count*delay; 8 workers pay ~ceil(count/8)*delay.
        self.assertGreaterEqual(sequential, count * delay * 0.8)
        self.assertLess(parallel, sequential / 2)  # at least 2x, usually ~6x


class ProgressiveInventoryTests(unittest.TestCase):
    def test_snapshot_exposes_live_nodes_eta_and_first_device(self) -> None:
        factory, addresses = slow_network(6, delay=0.0)
        execution, _graph, _snapshot = run_pooled_discovery(
            addresses, factory, worker_count=3
        )
        snap = execution.snapshot()
        # Progressive inventory: a node per discovered device, with role.
        self.assertEqual(6, len(snap["nodes"]))
        node = snap["nodes"][0]
        self.assertIn("hostname", node)
        self.assertIn("role", node)          # evidence-based role (043.1)
        self.assertIn("stencil", node)       # role stencil for live topology
        self.assertIsNotNone(snap["time_to_first_device_seconds"])
        self.assertEqual(6, snap["processed"])
        self.assertEqual(6, snap["total"])
        # Completed run: no remaining ETA.
        self.assertIsNone(snap["eta_seconds"])

    def test_nodes_appear_in_candidate_order(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs("alpha", "10.0.0.1"),
                "10.0.0.2": device_outputs("bravo", "10.0.0.2"),
                "10.0.0.3": device_outputs("charlie", "10.0.0.3"),
            }
        )
        execution, _g, _s = run_pooled_discovery(
            ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            network.transport_factory, worker_count=3,
        )
        hostnames = [n["hostname"] for n in execution.snapshot()["nodes"]]
        self.assertEqual(["alpha", "bravo", "charlie"], hostnames)


class ConsoleGuiTests(unittest.TestCase):
    def build_client(self, workdir: Path):
        from founderos_atlas.web import create_app
        from tests.test_profile_isolation import add_profile, make_service

        service = make_service(workdir)
        add_profile(service, "Hyderabad", "10.0.0.1")
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return app.test_client()

    def test_console_is_an_operations_console(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            page = client.get("/discovery/console").data
            self.assertIn(b"Enterprise Discovery", page)
            # Action bar controls.
            for control in (b"Pause", b"Resume", b"Stop", b"Restart", b"Logs"):
                self.assertIn(control, page)
            # The operational panels the spec requires.
            for panel in (b"Discovery Pipeline", b"Workers", b"Queue",
                          b"Live Inventory", b"Discovery Metrics",
                          b"Discovery Log", b"Discovery complete"):
                self.assertIn(panel, page)
            # Operational metrics, not "devices discovered".
            for metric in (b"Worker utilization", b"Avg SSH time",
                           b"SSH reachable", b"Devices / min"):
                self.assertIn(metric, page)
            # Completion shortcuts.
            self.assertIn(b"Open Mission", page)
            self.assertIn(b"Enterprise Topology", page)
            # Accessibility affordances.
            self.assertIn(b'role="toolbar"', page)
            self.assertIn(b'aria-live="polite"', page)

    def test_completed_demo_snapshot_is_honest_and_rich(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            snap = client.get("/api/discovery/execution/demo").get_json()
            self.assertEqual("completed", snap["state"])
            self.assertEqual(100, snap["progress_percent"])
            metrics = snap["metrics"]
            self.assertEqual(16, metrics["addresses_evaluated"])
            self.assertIn("authentication_failures", metrics)
            self.assertIn("worker_utilization_percent", metrics)
            self.assertIn("average_ssh_seconds", metrics)
            self.assertEqual(8, metrics["worker_count"])
            # Progressive inventory with roles/stencils for live topology.
            self.assertTrue(snap["nodes"])
            self.assertIn("role", snap["nodes"][0])
            self.assertIsNotNone(snap["time_to_first_device_seconds"])
            self.assertTrue(snap["log"])
            import json

            self.assertNotIn("password", json.dumps(snap).lower())

    def test_running_demo_snapshot_shows_alive_workers_and_eta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            snap = client.get(
                "/api/discovery/execution/demo?state=running"
            ).get_json()
            self.assertEqual("running", snap["state"])
            self.assertEqual(42, snap["progress_percent"])
            self.assertEqual(48.0, snap["eta_seconds"])
            # Workers look alive — none idle in the running sample.
            self.assertTrue(all(not w["idle"] for w in snap["workers"]))
            self.assertEqual(8, len(snap["workers"]))
            self.assertIn("collecting interfaces", snap["workers"][0]["stage"])
            self.assertGreater(snap["metrics"]["worker_utilization_percent"], 50)
            self.assertTrue(snap["nodes"])

    def test_discovery_page_links_to_the_console(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_client(Path(tmp))
            page = client.get("/discovery").data
            self.assertIn(b'href="/discovery/console"', page)


if __name__ == "__main__":
    unittest.main()
