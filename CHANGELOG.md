# Changelog

## Unreleased

### Added

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

## v0.1-alpha

- Created initial FounderOS repository structure
- Added runtime, agents, prompts, templates, domains, examples, architecture and roadmap folders
