# FounderOS Milestone 11.1 Handoff

Milestone 11.1 — Developer Experience Bug Fix is complete.

> Superseded diagnostic note: Milestone 11.1 fixed the independent `.pytest_cache` ACL warning, but it did not explain the user-machine hang in the service-boundary lock test. Milestone 11.2 identified that hang as unsafe Windows use of `os.kill(pid, 0)` and replaced it with non-signalling Win32 process inspection.

## Root cause

The repository's `.pytest_cache` directory had a protected, non-inheriting Windows ACL (`D:P`). Its access list contained only SYSTEM, Administrators, and Owner Rights instead of inheriting the workspace permissions required by the normal test process.

Pytest could run every test, but its cache provider could not reliably traverse or update the cache during session completion. This produced `PytestCacheWarning`. Because the persistence-heavy suite also takes roughly 80 seconds with sparse quiet-mode output, manual interruption could present as a shutdown `KeyboardInterrupt`.

Investigation found no application-level shutdown leak:

- no background or daemon threads;
- no subprocesses;
- no `atexit` handlers;
- no unclosed writer locks;
- no lingering file handles identified in runtime context managers;
- no temporary-directory cleanup failure; and
- no Python process remained after pytest returned.

## Proper fix

The cache ACL was reset recursively so `.pytest_cache` inherits the workspace permissions:

```powershell
icacls .pytest_cache /reset /T /C
```

The temporary `cache_dir = ".test-cache/pytest"` redirection was removed from `pyproject.toml`, and the obsolete `.test-cache` directory was removed. Pytest now uses its standard ignored `.pytest_cache` path.

This fixes the filesystem defect instead of disabling the cache provider or hiding its warning.

## Files changed

- `pyproject.toml`
- `.gitignore`
- `README.md`
- `CHANGELOG.md`
- `.ai/BUILD_ROADMAP.md`
- `.ai/PROJECT_CONTEXT.md`
- `.ai/DECISIONS.md`
- `MILESTONE_11_HANDOFF.md`
- `MILESTONE_11_1_HANDOFF.md`

No FounderOS runtime, workflow, persistence, planner, Discovery, or CLI behavior was changed.

## Verification

The exact acceptance command was run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result:

```text
86 passed, 5 subtests passed in 80.63s
Exit code: 0
PytestCacheWarning: none
KeyboardInterrupt: none
Lingering workspace Python processes: 0
```

PowerShell regained control immediately after pytest returned. Startup, test execution, cache finalization, and process shutdown took 81.69 seconds in total, approximately one second beyond pytest's reported test-session duration.

The current repository contains 86 tests, not the 81 tests from the earlier observation.

## Documentation

README now documents how to inspect and repair this specific Windows ACL failure:

```powershell
icacls .pytest_cache
icacls .pytest_cache /reset /T /C
```

The cache remains disposable and ignored by Git.

## Regression-test decision

No application test was added because the defect is external filesystem security metadata, not Python behavior. A test that deliberately rewrote the repository cache ACL would require elevated privileges, mutate developer-machine security state, and be unsafe in the normal suite. The exact full pytest invocation serves as the appropriate process-level regression verification.

## Remaining risk

Copying or restoring `.pytest_cache` from another Windows security context could recreate an invalid ACL. The cache must never be distributed as repository output; the documented reset command repairs it if encountered.

## Recommended next milestone

Milestone 12: Authorization Policy Foundation.
