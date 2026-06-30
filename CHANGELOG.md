# Changelog

## Unreleased

### Added

- Added deterministic Discovery Workflow v1 with no model, web, or external API calls.
- Added the Opportunity Report content contract and deterministic six-factor scoring/ranking.
- Added Discovery runs, quality Evaluation, human Approval, selection Decision, and guarded transitions to `OPPORTUNITY_SELECTED`.
- Added `founderos discovery` and `founderos approve-opportunity` with local JSON, correlation, persistence, audit, and idempotency.
- Added 11 Discovery tests covering prerequisites, scoring, approval gating, planner behavior, CLI, audit, redaction, idempotency, and replay.

- Added read-only `RuntimeDiagnostics` summaries for Project state, Events, WorkflowRuns, AgentRuns, Approvals, Evaluations, Transitions, Artifacts, and persistence health.
- Added `founderos audit`, `founderos runs`, and `founderos transitions` commands.
- Added one root command correlation across each CLI mutation, application call, runtime records, and child Events.
- Added approval-to-transition-to-Artifact traceability, ordered command summaries, operation timing, and audit consistency checks.
- Added recursive sensitive-field redaction and explicit `--include-sensitive` opt-in for Founder Brief content.
- Added seven diagnostics tests covering correlation, ordering, traceability, redaction, recovery consistency, completeness, and non-mutation.

- Added public repository import/export ports so local persistence no longer hydrates through private insertion methods.
- Added reusable Artifact, Evaluation, and Approval lifecycle services; existing WorkflowRun and AgentRun services remain the run boundaries.
- Added persistence format v2 with a restart-safe command-result journal and CLI `--idempotency-key` support for `new`, `founder-brief`, and `approve`.
- Added lock inspection and guarded stale-lock removal requiring an exact PID, a dead owner, and a minimum age.
- Added write-phase failure injection and eight service-boundary tests covering ports, lifecycle delegation, idempotency, lock policy, and recovery paths.

- Added exclusive local writer locks and optimistic store revisions to reject concurrent and stale writes.
- Added validated pre-write backups and explicit `founderos recover` restoration.
- Added `founderos health` for schema, Event replay, content digest, lock, format, and backup checks.
- Added an explicit version-to-version migration registry with v0-to-v1 compatibility and future-version rejection.
- Added 10 persistence-hardening tests plus CLI health coverage for corruption, missing files, stale writes, locks, backup restore, replay mismatch, and migrations.

- Added the standard-library `founderos` CLI with `new`, `status`, `plan`, `founder-brief`, `approve`, `decisions`, and `events` commands.
- Added a thin application facade that delegates planning and mutations to existing runtime services.
- Added validated local persistence using `project-state.json`, ordered `events.jsonl`, and immutable Artifact JSON files under `.founderos/`.
- Added nine CLI acceptance tests covering restart-style reloads, runtime guard enforcement, ordered Events, and the complete Founder Brief path.

- Added the first executable Founder Setup vertical slice: project start/resume, structured Founder Brief production, schema evaluation, human approval, guarded completion, and replay verification.
- Added `founder-brief-content.schema.json`, immutable canonical-JSON content storage, Founder Setup Agent/Workflow definitions, and six end-to-end tests.
- Added approved artifact references to the Project aggregate when a guarded transition applies.

- Added immutable ExecutionContext and ExecutionPlan read models.
- Added a deterministic Runtime Planner composed of ArtifactPlanner, WorkflowSelector, and AgentRouter.
- Added planning rules for all 22 known lifecycle states while reusing State Machine routes and guard requirements.
- Added missing-artifact blocking, workflow recommendations, agent-role routing, allowed transitions, quality-gate summaries, and next-state candidates.
- Added 13 planner tests covering required early lifecycle routes, approved-artifact filtering, plan completeness, context construction, unknown states, non-mutation, determinism, and rule/State Machine consistency.

- Added the Python 3.11+ `founderos_runtime` package with `jsonschema` 4.x as its only runtime dependency.
- Added a Draft 2020-12 contract registry with local reference resolution and RFC 3339 format enforcement.
- Added defensive in-memory repositories for Project, Artifact, Decision, WorkflowRun, AgentRun, Event, Approval, Evaluation, and Transition records, plus Agent and Workflow definitions.
- Added Project State creation/update operations with optimistic revision checks and atomic Event persistence.
- Added guarded State Machine transitions with exact evidence resolution, human Approval checks, rejection outcomes, idempotent correlation handling, and rollback on commit failure.
- Added ordered Event streams and deterministic Project event replay.
- Added basic WorkflowRun and AgentRun lifecycle services with bounded retry exhaustion behavior.
- Added 19 automated tests covering all 14 contract acceptance scenarios, schema loading, transaction rollback, revision conflicts, ordered Events, and defensive repository reads.

- Added JSON Schema Draft 2020-12 contracts under `runtime/contracts/` for Agent, Artifact, Workflow, State, Decision, Project, WorkflowRun, AgentRun, Transition, Evaluation, Approval, and Event.
- Added canonical ID, version, revision, timestamp, actor, status, and typed-reference conventions.
- Added transition guard ordering, complete allowed routes, atomic mutation rules, rejection behavior, and recovery semantics.
- Added persistence ownership, state-mutation boundaries, event ordering, concurrency, and artifact-content boundaries.
- Added 14 contract-level acceptance scenarios for structural, referential, transactional, recovery, replay, and idempotency behavior.

### Changed

- Established `.ai/` as the official location for AI governance and onboarding documents.
- Corrected governance document references to use `.ai/` paths.
- Reconciled project status across README, project context, roadmap, sprint, and decisions.
- Added a thin `runtime/master-orchestrator.md` specification aligned with the architecture and state catalogue.
- Marked empty Markdown scaffolds as planned placeholders instead of implied implementations.
- Set executable runtime contracts as the next milestone.
- Replaced runtime component placeholders with contract-level Project State, Workflow Engine, Agent Registry, Artifact Registry, Decision Engine, and Knowledge Base specifications.
- Expanded the State Machine from a state list into guarded transition and recovery contracts.
- Updated the Master Orchestrator to depend on the completed contract specifications while remaining unimplemented.
- Marked Executable Runtime Contracts complete and Runtime Foundation as the next milestone.
- Marked Runtime Foundation complete and First Executable Vertical Slice as the next milestone.
- Clarified that `Project.last_event_sequence` tracks the latest aggregate-mutating Event reflected by the Project snapshot; the Event repository owns the complete audit-stream sequence.
- Marked the Runtime Planner Engine complete and moved the first Founder Brief vertical slice to Milestone 5.

## v0.1-alpha

- Created initial FounderOS repository structure
- Added runtime, agents, prompts, templates, domains, examples, architecture and roadmap folders
