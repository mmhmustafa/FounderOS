# FounderOS Milestone 3 — Complete Handoff

## Outcome

Milestone 3 implementation is complete.

## Language and dependencies chosen

- Python 3.11+
- `jsonschema[format]` 4.x as the only direct runtime dependency
- Standard-library `unittest` for automated tests
- Setuptools for packaging
- No CLI, web framework, database framework, AI SDK, or unnecessary application framework

## Files changed

- Added `pyproject.toml`.
- Added the runtime package under `src/founderos_runtime/`.
- Added acceptance and foundation tests under `tests/`.
- Updated `.gitignore` for Python environment/build artifacts.
- Updated README, changelog, architecture status, runtime specifications, contracts documentation, build roadmap, current sprint, project context, and decisions.

## Tests added

Nineteen tests now cover:

- All 14 Milestone 2 contract acceptance scenarios
- Loading and meta-validating all 13 JSON schemas
- Valid and invalid schema records
- Exact typed-reference resolution
- Successful atomic state transitions
- Missing approvals and failed evaluations
- Invalid transitions and stale revisions
- WorkflowRun and AgentRun lifecycle behavior
- Retry creation and retry exhaustion
- Ordered Event replay and sequence-gap rejection
- Correlation-based transition idempotency
- Direct Project state-mutation prevention
- Knowledge exclusion from direct transition evidence
- Full rollback when the final Project write fails
- Defensive repository reads

Verification command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

Result: **19 tests passed**.

Dependency verification:

```text
No broken requirements found.
```

## What works now

- Runtime contracts load through a real JSON Schema Draft 2020-12 validator.
- RFC 3339 formats and local schema references are enforced.
- Canonical prefixed ULIDs and UTC timestamps can be generated.
- Projects can be created and updated in memory.
- Project mutations enforce optimistic revisions.
- In-memory repositories exist for Project, Artifact, Decision, WorkflowRun, AgentRun, Event, Approval, Evaluation, and Transition.
- Immutable Agent and Workflow definition repositories support exact version references.
- Repository reads return defensive copies.
- Events append in gap-free order per Project.
- Project state can be deterministically replayed from Events.
- Basic WorkflowRun and AgentRun lifecycles work.
- Agent retries create new records and preserve failed history.
- Retry exhaustion fails the governing WorkflowRun.
- The State Machine enforces all 22 allowed routes and ordered guards.
- Invalid routes, stale revisions, missing evidence, failed evaluations, and missing approvals produce rejected Transition records.
- Applied transitions atomically persist the Transition and Event and increment Project revision exactly once.
- Simulated partial-write failures roll back every affected in-memory repository.
- Duplicate transition commands return the existing result without duplicate effects.
- Direct Project state writes are rejected outside the State Machine boundary.

## Important decisions

- Python 3.11+ and `jsonschema` 4.x form the minimal runtime baseline.
- Milestone 3 uses thread-safe in-memory repositories behind explicit service boundaries.
- `Project.last_event_sequence` tracks the latest aggregate-mutating Event reflected by the Project snapshot; the Event repository independently owns the complete audit sequence.

## Remaining risks

- In-memory data is not durable and disappears when the process exits.
- Correlation/idempotency indexes are process-local.
- Authentication and general authorization are not implemented.
- Observability and cost accounting are not implemented.
- The Knowledge Base remains specification-only and has no KnowledgeEntry schema.
- Full Workflow step execution is not implemented.
- Artifact, Decision, Evaluation, and Approval repositories exist, but their full application-level lifecycle services are not yet implemented.
- Contract discovery currently assumes the repository layout unless an explicit contract path is provided.
- No CLI, web UI, LLM calls, Discovery, Validation, or Product module exists.

## Recommended next milestone

Proceed with **Milestone 4 — First Executable Vertical Slice**:

- Create or resume a Project
- Execute the Founder Setup Workflow
- Produce and persist a Founder Brief
- Require human review and Approval
- Transition to `FOUNDER_BRIEF_COMPLETE`
- Verify durable resume and deterministic replay

Do not begin Discovery, Validation, Product, general-purpose CLI, web UI, or LLM integration during that milestone.

## Git status

Git staging and commit remain pending because repository-write approval requests did not complete. All Milestone 3 changes are safely present in the working tree and included in this ZIP.

## Previously displayed handoff text

> Milestone 3 implementation is complete.
>
> - Language: Python 3.11+
> - Dependency: `jsonschema[format]` 4.x
> - Tests: 19/19 passing
> - Added contract validation, in-memory repositories, Project State, ordered Events, guarded atomic transitions, replay, and WorkflowRun/AgentRun lifecycles.
> - Updated architecture, roadmap, sprint, decisions, README, and changelog.
>
> Remaining risks:
>
> - In-memory data is not durable.
> - Authorization and observability remain unimplemented.
> - Idempotency state is process-local.
> - Knowledge Base remains specification-only.
>
> Recommended next milestone: **Milestone 4 — First Executable Vertical Slice**.
>
> Git staging/commit remains pending because repeated repository-write approval requests did not complete. All changes are safely present in the working tree.
