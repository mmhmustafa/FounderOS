"""The Discovery Execution Engine (PR-043.3, codename TURBO).

Discovery correctness, platform drivers, and canonical models are
UNCHANGED. This layer only changes *execution*: it turns the sequential,
blocking candidate walk into an observable, controllable worker pool
with per-stage instrumentation, explicit lifecycle states, and
pause/resume/cancel controls.

Why a thread pool: discovery is I/O-bound — nearly all wall-clock time
is spent blocked on TCP connect, the SSH handshake, authentication, and
per-command round-trips. Sequential execution pays every candidate's
latency (and every dead address's timeout) back to back. Threads
blocked on I/O release the GIL, so N workers process N candidates
concurrently and total time collapses from Σ(latencies) toward
max-over-workers.

Determinism is preserved: results are reconciled in candidate order
regardless of completion order, and reconciliation/identity are already
order-independent. Timestamps come from an injected monotonic clock so
metrics are testable without wall-clock flakiness.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import threading
from typing import Any


# -- lifecycle ---------------------------------------------------------------------

STATE_QUEUED = "queued"
STATE_STARTING = "starting"
STATE_INVENTORY = "inventory-pass"
STATE_DEEP = "deep-discovery-pass"
STATE_PAUSED = "paused"
STATE_RUNNING = "running"
STATE_COMPLETED = "completed"
STATE_CANCELLED = "cancelled"
STATE_FAILED = "failed"

_TERMINAL = frozenset({STATE_COMPLETED, STATE_CANCELLED, STATE_FAILED})

# Deterministic transition graph — every allowed move is explicit.
_TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_QUEUED: frozenset({STATE_STARTING, STATE_CANCELLED}),
    STATE_STARTING: frozenset({STATE_INVENTORY, STATE_CANCELLED, STATE_FAILED}),
    STATE_INVENTORY: frozenset(
        {STATE_DEEP, STATE_PAUSED, STATE_COMPLETED, STATE_CANCELLED, STATE_FAILED}
    ),
    STATE_DEEP: frozenset(
        {STATE_RUNNING, STATE_PAUSED, STATE_COMPLETED, STATE_CANCELLED, STATE_FAILED}
    ),
    STATE_RUNNING: frozenset(
        {STATE_PAUSED, STATE_COMPLETED, STATE_CANCELLED, STATE_FAILED}
    ),
    STATE_PAUSED: frozenset({STATE_RUNNING, STATE_DEEP, STATE_CANCELLED}),
    STATE_COMPLETED: frozenset(),
    STATE_CANCELLED: frozenset(),
    STATE_FAILED: frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(current, frozenset())


# -- candidate outcomes (execution-level, distinct from entry statuses) -----------

OUTCOME_QUEUED = "queued"
OUTCOME_RUNNING = "running"
OUTCOME_DISCOVERED = "discovered"
OUTCOME_AUTH_FAILED = "authentication-failed"
OUTCOME_UNSUPPORTED = "unsupported-platform"
OUTCOME_UNREACHABLE = "unreachable"
OUTCOME_SKIPPED = "skipped"
OUTCOME_CANCELLED = "cancelled"

# The per-candidate stages instrumented, in execution order.
STAGES = (
    "tcp_connect",
    "ssh_handshake",
    "authentication",
    "platform_detection",
    "identity",
    "interfaces",
    "neighbors",
    "routes",
    "configuration",
    "graph_update",
)


@dataclass(frozen=True)
class CandidateMetrics:
    """Per-stage timings for one candidate (seconds), plus the total."""

    address: str
    stages: dict[str, float] = field(default_factory=dict)
    total_seconds: float = 0.0
    outcome: str = OUTCOME_QUEUED
    platform: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "stages": {k: round(v, 4) for k, v in self.stages.items()},
            "total_seconds": round(self.total_seconds, 4),
            "outcome": self.outcome,
            "platform": self.platform,
        }


class StageTimer:
    """Records per-stage durations using an injected monotonic clock.

    Deterministic and thread-local: each candidate uses its own timer, so
    concurrent workers never share timing state.
    """

    def __init__(self, address: str, clock: Callable[[], float]) -> None:
        self._address = address
        self._clock = clock
        self._stages: dict[str, float] = {}
        self._start = clock()

    @contextmanager
    def stage(self, name: str):
        begin = self._clock()
        try:
            yield
        finally:
            self._stages[name] = self._stages.get(name, 0.0) + (
                self._clock() - begin
            )

    def record(self, name: str, seconds: float) -> None:
        self._stages[name] = self._stages.get(name, 0.0) + seconds

    def finish(self, outcome: str, platform: str | None = None) -> CandidateMetrics:
        return CandidateMetrics(
            address=self._address,
            stages=dict(self._stages),
            total_seconds=self._clock() - self._start,
            outcome=outcome,
            platform=platform,
        )


@dataclass(frozen=True)
class ExecutionMetrics:
    """Aggregate execution metrics — honest counts, never a bare total."""

    addresses_evaluated: int
    ssh_reachable: int
    authenticated: int
    discovered: int
    unsupported: int
    auth_failed: int
    unreachable: int
    skipped: int
    elapsed_seconds: float
    worker_count: int
    average_discovery_seconds: float
    average_authentication_seconds: float
    average_platform_detection_seconds: float
    slowest_stage: str | None
    slowest_stage_seconds: float
    devices_per_minute: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "addresses_evaluated": self.addresses_evaluated,
            "ssh_reachable": self.ssh_reachable,
            "authenticated": self.authenticated,
            "discovered": self.discovered,
            "unsupported_platforms": self.unsupported,
            "authentication_failures": self.auth_failed,
            "unreachable": self.unreachable,
            "skipped": self.skipped,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "worker_count": self.worker_count,
            "average_discovery_seconds": round(self.average_discovery_seconds, 4),
            "average_authentication_seconds": round(
                self.average_authentication_seconds, 4
            ),
            "average_platform_detection_seconds": round(
                self.average_platform_detection_seconds, 4
            ),
            "slowest_stage": self.slowest_stage,
            "slowest_stage_seconds": round(self.slowest_stage_seconds, 4),
            "devices_per_minute": round(self.devices_per_minute, 2),
        }


def aggregate_metrics(
    candidate_metrics: list[CandidateMetrics],
    *,
    elapsed_seconds: float,
    worker_count: int,
) -> ExecutionMetrics:
    """Deterministic aggregation over per-candidate metrics."""

    evaluated = len(candidate_metrics)
    discovered = [m for m in candidate_metrics if m.outcome == OUTCOME_DISCOVERED]
    auth_failed = sum(
        1 for m in candidate_metrics if m.outcome == OUTCOME_AUTH_FAILED
    )
    unsupported = sum(
        1 for m in candidate_metrics if m.outcome == OUTCOME_UNSUPPORTED
    )
    unreachable = sum(
        1 for m in candidate_metrics if m.outcome == OUTCOME_UNREACHABLE
    )
    skipped = sum(
        1 for m in candidate_metrics
        if m.outcome in (OUTCOME_SKIPPED, OUTCOME_CANCELLED)
    )
    # SSH-reachable = got past TCP connect (any stage after it ran).
    ssh_reachable = sum(
        1
        for m in candidate_metrics
        if m.stages.get("ssh_handshake") is not None
        or m.outcome not in (OUTCOME_UNREACHABLE, OUTCOME_SKIPPED, OUTCOME_CANCELLED)
    )
    authenticated = evaluated - auth_failed - unreachable - skipped
    stage_totals: dict[str, float] = {}
    for metric in candidate_metrics:
        for name, seconds in metric.stages.items():
            stage_totals[name] = stage_totals.get(name, 0.0) + seconds
    slowest = max(stage_totals.items(), key=lambda kv: kv[1], default=(None, 0.0))

    def _avg(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    avg_discovery = _avg([m.total_seconds for m in discovered])
    avg_auth = _avg(
        [m.stages["authentication"] for m in candidate_metrics
         if "authentication" in m.stages]
    )
    avg_detect = _avg(
        [m.stages["platform_detection"] for m in candidate_metrics
         if "platform_detection" in m.stages]
    )
    dpm = (len(discovered) / elapsed_seconds * 60.0) if elapsed_seconds > 0 else 0.0
    return ExecutionMetrics(
        addresses_evaluated=evaluated,
        ssh_reachable=ssh_reachable,
        authenticated=max(0, authenticated),
        discovered=len(discovered),
        unsupported=unsupported,
        auth_failed=auth_failed,
        unreachable=unreachable,
        skipped=skipped,
        elapsed_seconds=elapsed_seconds,
        worker_count=worker_count,
        average_discovery_seconds=avg_discovery,
        average_authentication_seconds=avg_auth,
        average_platform_detection_seconds=avg_detect,
        slowest_stage=slowest[0],
        slowest_stage_seconds=slowest[1],
        devices_per_minute=dpm,
    )


# -- worker + queue state ----------------------------------------------------------


@dataclass
class WorkerState:
    worker_id: int
    address: str | None = None
    stage: str | None = None
    idle: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "address": self.address,
            "stage": self.stage,
            "idle": self.idle,
        }


@dataclass
class LogEntry:
    address: str
    platform: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "platform": self.platform,
            "message": self.message,
        }


# The signature a per-candidate discovery worker must satisfy. It receives
# the address and a StageTimer to instrument, and returns (result_or_None,
# outcome, platform, log_message). Injected so tests use fake transports
# and the real caller wires the platform-driver pipeline unchanged.
CandidateWorker = Callable[[str, StageTimer], tuple[Any, str, str | None, str]]


class DiscoveryExecution:
    """The live, thread-safe execution state for one discovery run.

    Holds the queue, worker states, per-candidate metrics, log, and the
    control flags (pause/cancel). Every mutation is locked; every read
    returns a plain snapshot dict safe to serialize for the dashboard.
    """

    def __init__(
        self,
        addresses: list[str],
        *,
        worker_count: int = 4,
        completed: set[str] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        import time

        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._worker_count = max(1, int(worker_count))
        self._completed_addresses = set(completed or ())
        # De-duplicate while preserving order; already-completed candidates
        # are recorded as cached and never re-attempted (resume).
        seen: set[str] = set()
        self._order: list[str] = []
        self._pending: list[str] = []
        for address in addresses:
            if address in seen:
                continue
            seen.add(address)
            self._order.append(address)
            if address not in self._completed_addresses:
                self._pending.append(address)
        self._queue_index = 0
        self._state = STATE_QUEUED
        self._paused = threading.Event()
        self._cancelled = threading.Event()
        self._workers: dict[int, WorkerState] = {
            i: WorkerState(worker_id=i) for i in range(self._worker_count)
        }
        self._metrics: dict[str, CandidateMetrics] = {}
        self._results: dict[str, Any] = {}
        self._log: list[LogEntry] = []
        self._outcomes: dict[str, str] = {
            address: OUTCOME_DISCOVERED for address in self._completed_addresses
        }
        for address in self._pending:
            self._outcomes[address] = OUTCOME_QUEUED
        self._started_at: float | None = None
        self._finished_at: float | None = None

    # -- state transitions ---------------------------------------------------

    def transition(self, target: str) -> bool:
        with self._lock:
            if self._state == target:
                return True
            if not can_transition(self._state, target):
                return False
            self._state = target
            if target == STATE_STARTING and self._started_at is None:
                self._started_at = self._clock()
            if target in _TERMINAL:
                self._finished_at = self._clock()
            return True

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    # -- controls ------------------------------------------------------------

    def pause(self) -> None:
        with self._lock:
            self._paused.set()
            if self._state in (STATE_INVENTORY, STATE_DEEP, STATE_RUNNING):
                self._state = STATE_PAUSED

    def resume(self) -> None:
        with self._lock:
            self._paused.clear()
            if self._state == STATE_PAUSED:
                self._state = STATE_RUNNING

    def cancel(self) -> None:
        with self._lock:
            self._cancelled.set()
            self._paused.clear()  # release any paused workers to exit

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    # -- queue ---------------------------------------------------------------

    def next_address(self) -> str | None:
        """Hand the next pending candidate to a worker, or None when the
        queue is drained or cancelled. Paused workers wait without
        dequeuing new work (spec: pause completes current work only)."""

        while True:
            if self._cancelled.is_set():
                return None
            if self._paused.is_set():
                # Block here without taking a candidate; the pool joins
                # only after resume or cancel.
                if self._paused.wait(timeout=0.05):
                    continue
                continue
            with self._lock:
                if self._queue_index >= len(self._pending):
                    return None
                address = self._pending[self._queue_index]
                self._queue_index += 1
                self._outcomes[address] = OUTCOME_RUNNING
                return address

    # -- worker reporting ----------------------------------------------------

    def set_worker(self, worker_id: int, address: str | None, stage: str | None):
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker is not None:
                worker.address = address
                worker.stage = stage
                worker.idle = address is None

    def record(
        self,
        address: str,
        result: Any,
        metrics: CandidateMetrics,
        log_message: str,
    ) -> None:
        with self._lock:
            self._metrics[address] = metrics
            self._outcomes[address] = metrics.outcome
            if result is not None:
                self._results[address] = result
                self._completed_addresses.add(address)
            self._log.append(
                LogEntry(address, metrics.platform, log_message)
            )

    # -- snapshots -----------------------------------------------------------

    def results_in_order(self) -> list[Any]:
        """Discovered results in deterministic candidate order."""

        with self._lock:
            return [
                self._results[address]
                for address in self._order
                if address in self._results
            ]

    def completed_addresses(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._completed_addresses))

    def metrics(self) -> ExecutionMetrics:
        with self._lock:
            elapsed = (
                (self._finished_at or self._clock()) - self._started_at
                if self._started_at is not None
                else 0.0
            )
            return aggregate_metrics(
                list(self._metrics.values()),
                elapsed_seconds=elapsed,
                worker_count=self._worker_count,
            )

    def queue_snapshot(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for outcome in self._outcomes.values():
                counts[outcome] = counts.get(outcome, 0) + 1
            return {
                "total": len(self._order),
                "completed_cached": len(self._completed_addresses),
                "pending": max(0, len(self._pending) - self._queue_index),
                "by_outcome": dict(sorted(counts.items())),
            }

    def snapshot(self) -> dict[str, Any]:
        """One serializable dashboard snapshot — no secrets, ever."""

        with self._lock:
            metrics = self.metrics()
            pending = max(0, len(self._pending) - self._queue_index)
            done = len(self._metrics)
            total = len(self._pending)
            return {
                "state": self._state,
                "progress_percent": (
                    int(round(done / total * 100)) if total else 100
                ),
                "queue": self.queue_snapshot(),
                "queue_length": pending,
                "workers": [w.to_dict() for w in self._workers.values()],
                "metrics": metrics.to_dict(),
                "log": [entry.to_dict() for entry in self._log[-40:]],
                "candidate_metrics": [
                    m.to_dict() for m in self._metrics.values()
                ],
            }


def run_pool(
    execution: DiscoveryExecution,
    worker: CandidateWorker,
    *,
    on_progress: Callable[[], None] | None = None,
) -> DiscoveryExecution:
    """Drive one execution through its worker pool to a terminal state.

    Deterministic contract: every pending candidate is processed exactly
    once (unless cancelled), results are available in candidate order, and
    the same evidence yields the same reconciled graph regardless of which
    worker finished first.
    """

    execution.transition(STATE_STARTING)
    execution.transition(STATE_INVENTORY)
    execution.transition(STATE_DEEP)
    if execution.state == STATE_DEEP:
        execution.transition(STATE_RUNNING)

    def worker_loop(worker_id: int) -> None:
        while True:
            address = execution.next_address()
            if address is None:
                execution.set_worker(worker_id, None, None)
                return
            timer = StageTimer(address, execution._clock)
            execution.set_worker(worker_id, address, "connecting")
            try:
                result, outcome, platform, message = worker(address, timer)
            except Exception as error:  # noqa: BLE001 - recorded, never raised
                metrics = timer.finish(OUTCOME_UNREACHABLE)
                execution.record(
                    address, None, metrics, f"error: {str(error)[:120]}"
                )
                if on_progress is not None:
                    on_progress()
                continue
            metrics = timer.finish(outcome, platform)
            execution.record(address, result, metrics, message)
            if on_progress is not None:
                on_progress()

    threads = [
        threading.Thread(target=worker_loop, args=(i,), daemon=True)
        for i in range(execution._worker_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    if execution.is_cancelled:
        execution.transition(STATE_CANCELLED)
    else:
        execution.transition(STATE_COMPLETED)
    return execution
