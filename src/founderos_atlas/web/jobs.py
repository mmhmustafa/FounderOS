"""Background discovery jobs for the Atlas GUI (PR-032).

A deliberately lightweight, in-process job layer for Atlas:
one daemon thread per job, a global run lock that serializes pipeline
execution, and a small JSON file that preserves job history across server
restarts. The manager knows nothing about Flask or the discovery pipeline —
it drives an injected ``runner`` callable — so a production job backend
(queue, external workers) can replace it later behind the same interface.

Concurrency policy: at most one discovery pipeline executes
at a time. Starting a job for a profile that already has a queued/running
job returns that job instead of creating a duplicate; jobs for different
profiles queue behind the run lock. Correctness over concurrency.

Progress semantics: every value shown is derived from real pipeline
activity — transport connections (which device is being contacted) and the
pipeline's own ``[N/9]`` progress lines mapped onto seven user-facing
stages. Overall percentage is stage-based and labelled as such; Atlas never
fabricates per-device percentages during recursive discovery.

Jobs never hold or expose credentials: they carry only the profile identity
and safe metadata; credential resolution happens inside the pipeline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
from typing import Any
import uuid


STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrupted"
STATUS_CANCELLED = "cancelled"

_ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)

STAGES = (
    "Preparing discovery",
    "Connecting to seed device",
    "Discovering neighbors",
    "Collecting device facts",
    "Collecting configurations",
    "Analyzing changes and operational state",
    "Saving results and updating dashboard",
)
TOTAL_STAGES = len(STAGES)

_STEP_LINE = re.compile(r"^\[(\d)/9\] (.+?) \.\.\. (.+)$")
_DEVICES_DETAIL = re.compile(r"ok \((\d+) device\(s\), (\d+) failed\)")

# Pipeline step number ([N/9]) -> user-facing stage number.
_STEP_TO_STAGE = {1: 2, 2: 4, 3: 5, 4: 6, 5: 6, 6: 6, 7: 7, 8: 7, 9: 7}

_MAX_LOG_LINES = 200
_MAX_PERSISTED_JOBS = 20

Clock = Callable[[], datetime]

# runner(profile_name, on_line, on_connect) -> summary dict; raises on failure.
Runner = Callable[[str, Callable[[str], None], Callable[[str], None]], dict]


class JobCancelled(Exception):
    """Raised inside progress callbacks when an operator cancelled the job."""


@dataclass
class DiscoveryJob:
    """Mutable state of one GUI-driven discovery run. No secrets, ever."""

    job_id: str
    profile_id: str
    profile_name: str
    site: str | None
    management_ip: str
    status: str = STATUS_QUEUED
    stage_number: int = 1
    message: str = "Waiting to start"
    current_device: str | None = None
    current_depth: int | None = None  # not reported by the engine yet
    devices_discovered: int = 0
    failed_devices: int = 0
    # The two things a non-connecting address can mean, kept apart (PR-043.10's
    # rule, applied here): a device that refused us, and an address with no
    # device on it. Only the first is a problem.
    auth_failed_devices: int = 0
    addresses_without_device: int = 0
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    warning: str | None = None
    summary: dict[str, Any] | None = None
    # An opt-in the operator set in the wizard: after this read-only
    # discovery finishes, measure link latency (an ACTIVE, console-gated
    # pass). It rides on the job only so the completed run can tell the
    # browser to trigger the measurement; the pass itself never runs here.
    measure_latency: bool = False
    cancel_requested: bool = False
    log: list[str] = field(default_factory=list)
    _seen_hosts: set[str] = field(default_factory=set)
    _elapsed_seconds: float | None = None

    @property
    def stage(self) -> str:
        return STAGES[self.stage_number - 1]

    @property
    def is_active(self) -> bool:
        return self.status in _ACTIVE_STATUSES

    def to_dict(self, *, now: datetime | None = None) -> dict[str, Any]:
        elapsed = self._elapsed_seconds
        if elapsed is None and self.started_at and now is not None:
            try:
                started = datetime.fromisoformat(self.started_at)
                elapsed = max(0.0, (now - started).total_seconds())
            except ValueError:
                elapsed = None
        if self.status == STATUS_COMPLETED:
            percent = 100
        else:
            percent = int(round(100 * (self.stage_number - 1) / TOTAL_STAGES))
        return {
            "job_id": self.job_id,
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "site": self.site,
            "management_ip": self.management_ip,
            "status": self.status,
            "stage": self.stage,
            "stage_number": self.stage_number,
            "total_stages": TOTAL_STAGES,
            "message": self.message,
            "current_device": self.current_device,
            "current_depth": self.current_depth,
            "devices_discovered": self.devices_discovered,
            "failed_devices": self.failed_devices,
            "auth_failed_devices": self.auth_failed_devices,
            "addresses_without_device": self.addresses_without_device,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
            "error": self.error,
            "warning": self.warning,
            "cancel_requested": self.cancel_requested,
            "summary": self.summary,
            "measure_latency": self.measure_latency,
            "events": list(self.log[-12:]),
            "percent": percent,
            "progress_basis": "stages",  # stage-based, never false precision
        }


def friendly_failure(message: str, profile_name: str) -> str:
    """Turn a pipeline error into guidance a normal user can act on.

    Transport and workspace errors already carry human sentences; this only
    adds the profile context a GUI user needs. Raw technical detail stays in
    the job log, never in this string.
    """

    text = message.strip()
    lowered = text.casefold()
    if "authentication failed" in lowered:
        return (
            f"{text} Update the password saved in the "
            f"{profile_name} profile if it changed."
        )
    if "credential store" in lowered or "secure credential" in lowered:
        return (
            "Secure credential storage is unavailable. Check Atlas Settings, or "
            'reinstall the credential backend with: pip install "founderos-runtime[credentials]"'
        )
    return text


class DiscoveryJobManager:
    """Create, execute, track, and persist GUI discovery jobs."""

    def __init__(
        self,
        *,
        runner: Runner,
        profile_service,
        persist_path: str | Path | None = None,
        clock: Clock | None = None,
        thread_factory: Callable[..., threading.Thread] | None = None,
        on_failure: Callable[["DiscoveryJob"], None] | None = None,
    ) -> None:
        self._runner = runner
        self._profiles = profile_service
        self._on_failure = on_failure
        self._persist_path = Path(persist_path) if persist_path is not None else None
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._threads = thread_factory or (
            lambda **kwargs: threading.Thread(daemon=True, **kwargs)
        )
        self._lock = threading.RLock()  # guards job state
        self._run_lock = threading.Lock()  # serializes pipeline execution
        self._jobs: dict[str, DiscoveryJob] = {}
        self._order: list[str] = []
        self._workers: dict[str, threading.Thread] = {}
        self._restore()

    # -- public API -----------------------------------------------------------

    def start(
        self, profile_name: str, *, measure_latency: bool = False
    ) -> tuple[DiscoveryJob, bool]:
        """Start (or join) a discovery job for a saved profile.

        Returns ``(job, created)``; ``created`` is False when the profile
        already has a queued/running job — the existing job is returned so
        double-clicks and concurrent tabs can never duplicate a discovery.

        ``measure_latency`` carries the wizard's opt-in through to the
        completed job, where the browser reads it to run the active
        latency pass; a join returns the in-flight job unchanged.
        """

        profile = self._profiles.get_profile(profile_name)
        with self._lock:
            existing = self._active_for(profile.profile_id)
            if existing is not None:
                return existing, False
            job = DiscoveryJob(
                job_id=uuid.uuid4().hex[:12],
                profile_id=profile.profile_id,
                profile_name=profile.name,
                site=profile.site,
                management_ip=profile.management_ip,
                created_at=self._now(),
                message="Preparing discovery",
                measure_latency=bool(measure_latency),
            )
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            self._persist()
        worker = self._threads(target=self._execute, args=(job,))
        with self._lock:
            self._workers[job.job_id] = worker
        worker.start()
        return job, True

    def get(self, job_id: str) -> DiscoveryJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self, job: DiscoveryJob) -> dict[str, Any]:
        with self._lock:
            return job.to_dict(now=self._clock())

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            now = self._clock()
            recent = [self._jobs[job_id] for job_id in reversed(self._order)]
            return [job.to_dict(now=now) for job in recent[:limit]]

    def latest_for_profile(self, profile_id: str) -> DiscoveryJob | None:
        with self._lock:
            for job_id in reversed(self._order):
                job = self._jobs[job_id]
                if job.profile_id == profile_id:
                    return job
            return None

    def request_cancel(self, job_id: str) -> DiscoveryJob | None:
        """Ask an active job to stop at its next progress event.

        Cancellation is cooperative: the pipeline is not killed mid-write —
        it is stopped between observable steps, so partial results already
        persisted stay consistent. Returns the job, or None if unknown.
        """

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.is_active:
                job.cancel_requested = True
                job.message = "Cancellation requested"
                self._persist()
            return job

    def wait(self, job_id: str, timeout: float | None = None) -> DiscoveryJob | None:
        """Block until a job's worker finishes (sync fallback and tests)."""

        with self._lock:
            worker = self._workers.get(job_id)
        if worker is not None:
            worker.join(timeout)
        return self.get(job_id)

    # -- execution ------------------------------------------------------------

    def _execute(self, job: DiscoveryJob) -> None:
        with self._run_lock:  # all discoveries serialize: correctness first
            with self._lock:
                job.status = STATUS_RUNNING
                job.started_at = self._now()
                job.message = "Preparing discovery"
                self._persist()
            try:
                summary = self._runner(
                    job.profile_name,
                    lambda line: self._on_line(job, line),
                    lambda host: self._on_connect(job, host),
                )
            except JobCancelled:
                self._finish_cancelled(job)
                return
            except Exception as error:  # noqa: BLE001 - job boundary
                self._finish_failed(job, error)
                return
            self._finish_completed(job, summary or {})

    def _finish_completed(self, job: DiscoveryJob, summary: dict[str, Any]) -> None:
        with self._lock:
            job.status = STATUS_COMPLETED
            job.stage_number = TOTAL_STAGES
            job.completed_at = self._now()
            job._elapsed_seconds = self._elapsed(job)
            job.current_device = None
            job.summary = dict(summary)
            failed = int(summary.get("failed_devices") or job.failed_devices or 0)
            job.failed_devices = failed
            # An address that never answered is discovery COVERAGE, not a
            # failure. Sweeping a /24 that holds nine devices leaves 245
            # addresses silent — that is the correct answer, not a warning, and
            # calling those "verified management endpoints" was simply untrue:
            # they were never verified as anything. Only a device that ANSWERED
            # and refused our credentials is worth an operator's attention.
            #
            # enterprise_intelligence has drawn this line since PR-043.10; this
            # is the same rule, from the same function, finally applied to the
            # discovery job. (Older summaries carry neither key: then the honest
            # answer is to say nothing rather than guess.)
            refused = summary.get("auth_failed_devices")
            silent = summary.get("addresses_without_device")
            job.auth_failed_devices = int(refused or 0)
            job.addresses_without_device = int(silent or 0)

            if refused:
                job.warning = (
                    f"{int(refused)} device(s) refused authentication; Atlas "
                    "reached them but could not sign in. Successful results "
                    "were preserved."
                )
                job.message = "Discovery completed with warnings"
            else:
                job.warning = None
                job.message = "Discovery completed successfully"
            self._persist()

    def _finish_cancelled(self, job: DiscoveryJob) -> None:
        with self._lock:
            job.status = STATUS_CANCELLED
            job.completed_at = self._now()
            job._elapsed_seconds = self._elapsed(job)
            job.current_device = None
            job.message = "Discovery cancelled by the operator"
            job.log.append("cancelled: stopped at the operator's request")
            self._persist()

    def _finish_failed(self, job: DiscoveryJob, error: Exception) -> None:
        detail = str(error) or type(error).__name__
        with self._lock:
            job.status = STATUS_FAILED
            job.completed_at = self._now()
            job._elapsed_seconds = self._elapsed(job)
            job.error = friendly_failure(detail, job.profile_name)
            job.message = "Discovery failed"
            # Technical detail stays in the job log for troubleshooting —
            # never a traceback in the user-facing error.
            job.log.append(f"error: {type(error).__name__}: {detail}")
            self._persist()
        if self._on_failure is not None:
            try:
                self._on_failure(job)
            except Exception:  # noqa: BLE001 - notify must not mask failure
                pass

    # -- progress interpretation (real pipeline activity only) ----------------

    def _on_connect(self, job: DiscoveryJob, host: str) -> None:
        with self._lock:
            if job.cancel_requested:
                raise JobCancelled()
            job.current_device = host
            if job.stage_number >= 4:
                # Reconnections after the crawl are configuration collection.
                self._set_stage(job, 5, f"Collecting configuration from {host}")
                return
            if not job._seen_hosts:
                self._set_stage(job, 2, f"Connecting to seed device {host}")
            else:
                self._set_stage(job, 3, f"Discovering neighbors — contacting {host}")
            job._seen_hosts.add(host)
            job.devices_discovered = len(job._seen_hosts)

    def _on_line(self, job: DiscoveryJob, line: str) -> None:
        with self._lock:
            if job.cancel_requested:
                raise JobCancelled()
            if line.strip():
                job.log.append(line)
                del job.log[:-_MAX_LOG_LINES]
            match = _STEP_LINE.match(line.strip())
            if match is None:
                return
            step, label, detail = int(match.group(1)), match.group(2), match.group(3)
            stage = _STEP_TO_STAGE.get(step)
            if stage is None:
                return
            if step == 2:
                counts = _DEVICES_DETAIL.search(line)
                if counts is not None:
                    job.devices_discovered = int(counts.group(1))
                    job.failed_devices = int(counts.group(2))
                self._set_stage(
                    job,
                    4,
                    f"Collecting device facts — {job.devices_discovered} device(s)",
                )
                job.current_device = None
                return
            self._set_stage(job, stage, f"{label}: {detail}")

    @staticmethod
    def _set_stage(job: DiscoveryJob, stage_number: int, message: str) -> None:
        # Stages only ever move forward; late-arriving pipeline lines for
        # work that already happened must not rewind visible progress.
        if stage_number >= job.stage_number:
            job.stage_number = stage_number
        job.message = message

    # -- internals -------------------------------------------------------------

    def _active_for(self, profile_id: str) -> DiscoveryJob | None:
        for job_id in reversed(self._order):
            job = self._jobs[job_id]
            if job.profile_id == profile_id and job.is_active:
                return job
        return None

    def _now(self) -> str:
        return self._clock().isoformat(timespec="seconds")

    def _elapsed(self, job: DiscoveryJob) -> float | None:
        if not job.started_at or not job.completed_at:
            return None
        try:
            started = datetime.fromisoformat(job.started_at)
            completed = datetime.fromisoformat(job.completed_at)
        except ValueError:
            return None
        return max(0.0, (completed - started).total_seconds())

    # -- persistence (job history survives restarts; threads do not) ----------

    def _persist(self) -> None:
        if self._persist_path is None:
            return
        now = self._clock()
        entries = [
            self._jobs[job_id].to_dict(now=now)
            for job_id in self._order[-_MAX_PERSISTED_JOBS:]
        ]
        for entry in entries:
            entry.pop("events", None)  # keep the file small; logs are in-memory
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(
                json.dumps({"jobs": entries}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError:
            # Persistence is best-effort; never fail a discovery over it.
            pass

    def _restore(self) -> None:
        """Load persisted job history; mark stale active jobs interrupted.

        In-process jobs cannot survive a server restart, so anything still
        marked queued/running in the file was interrupted — say so honestly
        instead of showing a forever-running job.
        """

        if self._persist_path is None or not self._persist_path.is_file():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        entries = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            return
        changed = False
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("job_id"):
                continue
            job = DiscoveryJob(
                job_id=str(entry["job_id"]),
                profile_id=str(entry.get("profile_id") or ""),
                profile_name=str(entry.get("profile_name") or "unknown"),
                site=entry.get("site"),
                management_ip=str(entry.get("management_ip") or ""),
                status=str(entry.get("status") or STATUS_FAILED),
                stage_number=int(entry.get("stage_number") or 1),
                message=str(entry.get("message") or ""),
                devices_discovered=int(entry.get("devices_discovered") or 0),
                failed_devices=int(entry.get("failed_devices") or 0),
                auth_failed_devices=int(entry.get("auth_failed_devices") or 0),
                addresses_without_device=int(
                    entry.get("addresses_without_device") or 0
                ),
                created_at=entry.get("created_at"),
                started_at=entry.get("started_at"),
                completed_at=entry.get("completed_at"),
                error=entry.get("error"),
                warning=entry.get("warning"),
                summary=entry.get("summary"),
                measure_latency=bool(entry.get("measure_latency")),
            )
            job._elapsed_seconds = entry.get("elapsed_seconds")
            if job.status in _ACTIVE_STATUSES:
                job.status = STATUS_INTERRUPTED
                job.message = "Interrupted by an Atlas restart"
                job.error = (
                    "Atlas restarted while this discovery was running. "
                    "The run did not finish — run discovery again."
                )
                changed = True
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
        if changed:
            self._persist()
