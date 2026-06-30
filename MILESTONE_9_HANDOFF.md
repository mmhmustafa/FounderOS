# FounderOS Milestone 9 Handoff

Milestone 9 — Runtime Observability and Audit Diagnostics — is complete.

## Files Changed

- Added `src/founderos_runtime/diagnostics.py`.
- Added `tests/test_diagnostics.py`.
- Added `runtime/observability.md`.
- Updated the application facade, CLI, package exports, Founder Setup, lifecycle services, Project State, and run services.
- Updated README, CHANGELOG, AI governance, roadmap, sprint, decisions, and runtime documentation.

## Audit and Diagnostic Features

`RuntimeDiagnostics` now provides structured, read-only summaries for:

- Project state.
- Ordered Events.
- Command groups and timing.
- WorkflowRuns.
- AgentRuns.
- Approvals.
- Evaluations.
- Transitions.
- Artifacts.
- Persistence health.
- Audit consistency.

## Command Correlation

Every CLI mutation uses one root correlation identifier:

```text
cli:<operation>:<token>
```

The root is retained across the CLI result, application facade, Project and run metadata, lifecycle records, Transition metadata, and child Events. Audit output normalizes suffixed child correlations back to their root command.

## Audit Traceability

Operators can determine:

- What happened.
- The exact Event order.
- Which command caused each effect.
- Which Approval permitted a transition.
- Which Transition changed Project state.
- Which Artifact was approved and involved.
- Whether persisted Project state matches deterministic Event replay.

## Redaction

Audit output omits Founder Brief content by default. Approval rationale and known sensitive fields are replaced with `[REDACTED]`.

Sensitive content is returned only with explicit opt-in:

```powershell
founderos audit --include-sensitive
```

## CLI Commands Added

- `founderos audit`
- `founderos runs`
- `founderos transitions`

All three commands are read-only and do not modify state, Events, records, or persistence files.

## Tests Added

Seven diagnostics tests cover:

- Command correlation across runtime boundaries.
- Ordered audit timelines and command summaries.
- Approval-to-Transition-to-Artifact traceability.
- Default redaction and explicit sensitive-content access.
- Recovery and audit consistency.
- Non-mutation by audit commands.
- Diagnostic coverage of runtime and persistence sections.

The complete test suite passes: **75 tests**.

## Remaining Risks

- Redaction rules must evolve when new schemas introduce sensitive fields.
- Explicit sensitive output can expose founder or customer information.
- Command timing uses persisted Event timestamps rather than full execution profiling.
- Older Events may not use normalized CLI correlation identifiers.
- Audit checks report inconsistencies but intentionally do not repair them.
- There is no database, Web UI, LLM integration, Discovery, or Validation implementation.

## Recommended Next Milestone

Milestone 10 — Authorization Policy Foundation: define local actor capabilities and Project ownership, enforce authorization at application and lifecycle boundaries, protect Approval and state-transition operations, and add redacted authorization-denial diagnostics without introducing external authentication.
