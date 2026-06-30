# Changelog

## Unreleased

### Added

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
