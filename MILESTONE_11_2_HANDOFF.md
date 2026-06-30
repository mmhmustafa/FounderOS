# FounderOS Milestone 11.2 Handoff

Milestone 11.2 — Windows Stale-Lock Probe Fix is complete.

## Root cause

`LocalProjectStore._pid_alive()` used `os.kill(pid, 0)` to check whether the owner recorded in `.write.lock` still existed. That is a POSIX process-existence idiom, not a portable Windows API. Its Windows behavior varies by Python and operating-system version and can interact with the current pytest process instead of performing a harmless existence check.

The hanging test calls `inspect_lock()` for a lock owned by `os.getpid()`. That immediately invokes `_pid_alive()` against pytest itself, matching the observed stop at `test_lock_inspection_and_safe_stale_lock_policy`.

The `.pytest_cache` ACL diagnosed in Milestone 11.1 was a separate warning source. Redirecting or repairing pytest's cache could not fix this runtime lock-probe defect.

## Fix

On Windows, process liveness now uses:

1. `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, ...)`;
2. `GetExitCodeProcess(...)` and `STILL_ACTIVE`;
3. `CloseHandle(...)` in a `finally` block.

No signal is sent. Invalid PIDs return dead. Access-denied or indeterminate queries are treated as alive so stale-lock cleanup fails closed rather than risking concurrent writers.

POSIX platforms retain `os.kill(pid, 0)`.

## Regression coverage

The existing stale-lock policy test patches `os.kill` to raise on Windows while verifying both the current PID and a nonexistent PID. This proves the Windows path is non-signalling without changing the expected 86-test count.

## Verification

- Original service-boundary file before the fix: 8 tests passed locally, demonstrating the bug is Windows/Python-version dependent.
- Original isolated test before the fix: passed locally in 0.31 seconds.
- An initial separate regression test passed alongside the isolated lock test; it was then folded into the existing test to preserve the 86-test suite count.
- Exact `python -m pytest -q`: 86 passed with 5 subtests in 79.90 seconds; exit code 0; no lingering workspace Python process.
- Official PowerShell script: 86 passed with 5 subtests in 81.96 seconds; exit code 0.
- No `KeyboardInterrupt`, `PytestCacheWarning`, hang, or process leak occurred.

## Files changed

- `src/founderos_runtime/local_store.py`
- `tests/test_service_boundaries.py`
- `CHANGELOG.md`
- `README.md`
- `.ai/BUILD_ROADMAP.md`
- `.ai/DECISIONS.md`
- `MILESTONE_11_1_HANDOFF.md`
- `MILESTONE_11_2_HANDOFF.md`

No FounderOS feature or unrelated runtime behavior was added.
