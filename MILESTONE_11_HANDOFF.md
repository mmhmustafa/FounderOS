# FounderOS Milestone 11 Handoff

Milestone 11 — Developer Experience and Test Stability is complete.

Windows pytest now exits cleanly without the legacy cache warning or apparent shutdown hang.

## Root cause

Investigation found no surviving subprocess, background thread, persistence lock, temporary-directory cleanup failure, or pytest shutdown deadlock.

Two independent conditions created the reported behavior:

1. The persistence- and schema-heavy suite legitimately takes approximately 80 seconds on this Windows environment. Quiet mode provides sparse progress, so an active run could look stalled and manual interruption produced `KeyboardInterrupt`.
2. Pytest attempted to write into an inaccessible legacy `.pytest_cache` directory created under a different Windows or sandbox permission context. This produced a cache warning but did not prevent a successful test result.

The protected ACL on `.pytest_cache` was reset to inherit the workspace permissions. Pytest continues to use its standard cache path. The official scripts use verbose progress and report the ten slowest tests, making active work and a genuine stall distinguishable.

## Files changed

- Added `scripts/test.ps1`.
- Added `scripts/test.sh`.
- Updated `pyproject.toml` with a `dev` optional dependency group and pytest configuration.
- Updated `.gitignore` for pytest's standard cache path.
- Updated `README.md` with complete Windows and POSIX setup, official test commands, and Windows troubleshooting.
- Updated `CHANGELOG.md`.
- Updated `.ai/BUILD_ROADMAP.md`.
- Updated `.ai/CURRENT_SPRINT.md`.
- Updated `.ai/PROJECT_CONTEXT.md`.
- Updated `.ai/DECISIONS.md`.

## Scripts added

Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

Linux, macOS, or Git Bash:

```sh
sh ./scripts/test.sh
```

Both scripts locate the repository virtual environment, run from the repository root, invoke pytest through that environment's Python interpreter, show per-test progress, report slow tests, and propagate failures.

The Windows command applies execution-policy bypass only to its child process. It does not change persistent user or machine policy.

## Developer installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Pytest is now the official developer test runner and remains outside production runtime dependencies.

## Tests run

- Official PowerShell script: 86 tests passed, with 5 subtests.
- Exact `python -m pytest -q`: 86 tests passed, with 5 subtests.
- Direct pytest exit code: 0.
- Runtime: approximately 77–79 seconds.
- No pytest cache warning occurred after the ACL repair.
- `git diff --check` passed.

No runtime or CLI behavior was changed.

## Remaining risks

- The suite is stable but relatively slow because integration tests repeatedly validate schemas, serialize local persistence, create backups, and replay Events.
- The POSIX script was reviewed but could not be executed on this Windows environment because a POSIX shell is not installed.
- A cache directory copied from another security context may reproduce the ACL issue; README documents the exact inspection and repair commands.

## Recommended next milestone

Milestone 12: Authorization Policy Foundation. Define actor capabilities and enforce founder ownership at application and runtime service boundaries before implementing Validation.
