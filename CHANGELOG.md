# Changelog

## Unreleased

### EPIC-002 / PR-019 - Atlas Real Device Discovery over Read-Only SSH

- Added a vendor-neutral `DeviceTransport` contract with `connect`, `disconnect`, `execute`, and `execute_many`, plus context-manager lifecycle.
- Added a Netmiko-backed `SSHDeviceTransport` for any reachable Cisco IOS/IOS-XE device; simulators (CML, EVE-NG, GNS3) are treated as ordinary SSH endpoints with no simulator-specific logic.
- Enforced a read-only architecture: only `show` commands pass the local allowlist, the transport never enters configuration mode, and no enable escalation occurs.
- Added `DeviceCredentials` with the password excluded from repr; passwords are never logged, persisted, or echoed in errors or CLI output.
- Added typed, user-friendly transport failures for authentication, timeout, SSH unavailability, unsupported platform, permission denial, and lost connections, classified without importing Netmiko.
- Added `run_live_discovery` composing transport collection with the unchanged DiscoveryEngine, TopologyReconciler, and TopologySnapshot.
- Added `founderos atlas discover` prompting for management IP, username, and hidden password, then delivering the topology viewer HTML, Morning Brief, and browser launch.
- Made Netmiko an optional lazily-imported dependency (`pip install founderos-runtime[ssh]`); all automated tests run against mocks with no live devices.
- Added no SNMP, NETCONF, RESTCONF, simulator APIs, persistence, credential storage, multi-hop discovery, or configuration commands.

### EPIC-002 / PR-018 - Atlas Morning Brief Journey

- Added Atlas's first operational utility Workflow and immutable `MorningBrief` Artifact model.
- Added deterministic current/previous Snapshot comparison, status, warning/conflict evidence, recommendations, and Markdown rendering.
- Extended `JourneyRunner` with exact, injected deterministic builders for declared `artifact_creation` steps while preserving planning, validation, authorization, ordering, Evaluation, and result ownership.
- Added a declarative Morning Brief Workflow, Artifact schemas, and deterministic quality rubric.
- Added `founderos atlas morning-brief` to run fixture snapshots through FounderOS Journey infrastructure and deliver `morning_brief.md`.
- Added 11 acceptance tests covering current-only operation, comparison, recommendations, Markdown, Workspace loading, Journey execution, Evaluation, schema conformance, determinism, CLI delivery, and network isolation.
- Added no AI, LLM, live network access, persistence, scheduling, email, notification, GUI, or Project state mutation.

### EPIC-001 / PR-017 - Atlas Interactive Topology Viewer

- Added a pure deterministic `TopologySnapshot` to Cytoscape element and standalone HTML renderer.
- Added a responsive plain-HTML viewer with automatic layout, pan, zoom, fit, vendor colors, hover tooltips, click details, and search highlighting.
- Added `founderos atlas demo topology` to reuse fixture discovery, reconciliation, and Snapshot creation before writing `atlas_topology.html` and opening the default browser.
- Kept observed remote neighbors as explicitly lightweight visualization nodes rather than fabricating discovered device records.
- Added focused renderer and CLI tests covering conversion, HTML behavior, determinism, CDN isolation, network isolation, output delivery, and browser launch injection.
- Added no SSH, SNMP, persistence, database, AI, authentication, real-time update, topology editing, or GUI framework.

### EPIC-001 / PR-016 - Atlas Topology Snapshot Contract

- Added immutable content-addressed TopologySnapshot creation from reconciled TopologyGraph values.
- Included canonical devices/interfaces, directed edges, reconciliation warnings, optional deterministic timestamps, counts, and versioned metadata.
- Added pure defensive dictionary, stable JSON, and human-readable Markdown exports.
- Replaced the preliminary topology schema with a complete versioned Snapshot contract and aligned the topology quality rubric.
- Extended the Atlas CLI demo with snapshot ID, device, edge, warning, and schema-version summary.
- Added 12 tests covering construction, content, warnings, defensive exports, JSON/Markdown, timestamps, ordering, schema validation, content addressing, and no file writes.
- Added no persistence, database, SSH, SNMP, GUI, AI, live discovery, or graph database.

### EPIC-001 / PR-015 - Atlas Multi-Device Topology Reconciliation

- Added `TopologyReconciler` for deterministic merging of multiple DiscoveryResult observations.
- Extended TopologyGraph with identity-aware result/graph merge, device and edge counts, identity lookup, interface retention, structured warnings, and reconciliation summaries.
- Defined hostname, management-IP, serial-number, and explicit-ID matching priority with stable canonical selection.
- Preserved unique interfaces, metadata, and neighbor observations while deduplicating devices and edges.
- Added deterministic conflict warnings instead of silent overwrite.
- Extended the Atlas CLI demo with before/after reconciliation counts, duplicate removal, warnings, and merged topology.
- Added 12 tests covering identity matching, preservation, conflicts, graph merge, summary correctness, determinism, duplicate removal, and fixture-only operation.
- Added no SSH, SNMP, live discovery, persistence, graph database, GUI, AI, or cloud discovery.

### PR-014.1 - Atlas Discovery CLI Demo

- Added `founderos atlas demo discovery` as a thin console demonstration over the existing fixture-only Atlas Discovery Engine.
- Added deterministic plain-text rendering for normalized device, interface, neighbor, topology, and summary information without exposing Python representations.
- Added one CLI integration test covering successful exit, expected report text, and network isolation.
- Added no parser changes, SSH, SNMP, credentials, persistence, AI Provider, API, GUI, or device mutation.

### EPIC-001 / PR-014 - Atlas Discovery Engine Foundation

- Added Atlas as a first-party FounderOS networking App package while retaining both names as internal codenames.
- Added immutable vendor-neutral Device, Interface, Neighbor, Fact, and DiscoveryResult models plus a transport-free DiscoveryAdapter contract.
- Added a deterministic Cisco IOS reference parser for checked-in `show version`, `show ip interface brief`, and `show cdp neighbors detail` fixtures.
- Added an in-memory DiscoveryEngine and deterministic TopologyGraph with idempotent identical duplicates and explicit conflict rejection.
- Added valid Atlas App, utility Workflow, Agent, Artifact schema, Evaluation Rubric, fixture, and documentation assets.
- Added 12 tests covering parsing, normalization, engine behavior, graph behavior, errors, manifest validation, network isolation, fixture-only inputs, and determinism.
- Added no SSH, SNMP, credentials, persistence, database, GUI, API, device mutation, real AI Provider, live multi-hop discovery, cloud discovery, logs, or change intelligence.

### PR-013 - FounderOS CLI Alpha

- Added a standard-library, plain-text public CLI package with `version`, `doctor`, `demo discovery`, and `help` commands.
- Kept planning, validation, authorization, Journey execution, Mock Provider behavior, and Evaluation in their existing runtime components; the CLI delegates once and only renders results.
- Preserved the established local Project CLI commands through an unchanged compatibility adapter while replacing the former single-module layout with a package.
- Added deterministic Doctor checks for runtime availability, bundled manifest loading, Evaluation, and Mock Provider availability.
- Added 10 tests covering commands, successful and failed demo behavior, deterministic output, exit codes, rendering, network isolation, and runtime/file non-mutation.
- Added no interactive prompts, persistence for the Alpha demo, real AI, configuration system, plugins, marketplace, authentication, Web UI, or Kernel mutation.

### PR-012 - Discovery Vertical Slice Foundation

- Added a complete first-party Discovery example package containing Agent, Workflow, App, Evaluation Rubric, input, schema, expected-output, and Mock Provider fixture assets.
- Added a small in-memory demo helper that composes Workspace, Planner, Plan Validation, Authorization, Journey Runner, Mock Provider, and the declared Evaluation Rubric.
- Extended Journey Runner with optional caller-supplied input Artifacts and exact injected rubric resolution while preserving its deterministic default behavior.
- Added 12 tests covering package loading, planning, validation, authorization, execution, fixture output, rubric assessment, result contents, determinism, network isolation, and persistence/runtime non-mutation.
- Added no CLI, real Provider, persistence, human Approval execution, Web UI, authentication, marketplace, Event recording, or Project/Kernel mutation.

### PR-011 - Evaluation Rubric Manifest and Loader Foundation

- Added a strict versioned Evaluation Rubric schema and deterministic Opportunity Report example.
- Extended the stateless Manifest Loader with explicit Evaluation Rubric loading and existing typed validation errors.
- Added immutable EvaluationRubric translation into existing EvaluationRule, EvaluationRequest, and EvaluationRunner contracts.
- Added 11 tests covering schema failures, loading, valid and invalid Artifact evaluation, deterministic scoring, Provider isolation, and runtime non-mutation.
- Added no Journey execution changes, human Approval, persistence, CLI, real Provider, network access, or runtime state mutation.

### PR-010 - Plan Validation and Authorization Foundation

- Added deterministic PlanValidator and immutable ValidationReport contracts covering Workflow, Agent, Artifact, duplicate-ID, dependency-cycle/order, and Evaluation-checkpoint integrity.
- Added a pure AuthorizationEngine with missing-validation denial, unknown-capability denial, high-risk Approval-gate requirements, and safe-plan allowance.
- Integrated both gates into JourneyRunner before any Provider or Evaluation step; denied journeys return descriptive immutable results and perform no work.
- Added 15 focused tests plus preserved all existing Journey behavior.
- Added no human Approval, persistence, CLI, real Provider, network call, runtime Event, or Project/Kernel mutation.

### PR-009 - Founder Journey Runner Foundation

- Added an in-memory deterministic Journey Runner that consumes one Workspace Planner Execution Plan without replanning.
- Added immutable JourneyResult values containing completed/skipped steps, Evaluation results, generated Artifacts, ordered logs, and execution metadata.
- Added sequential Mock Provider Agent-task execution and deterministic Evaluation checkpoints with critical-failure stopping.
- Explicitly skipped Approval, transition-request, and Activity execution rather than claiming unavailable authority or side effects.
- Added 10 tests covering Discovery orchestration, Provider calls, Evaluation success/failure, unknown and empty plans, determinism, summaries, multiple Agent steps, Artifact results, and Workspace non-mutation.
- Added no persistence, CLI, real Provider, human interaction, asynchronous execution, Event recording, or Project/Kernel state mutation.

### PR-008 - Planner Foundation

- Added a read-only Workspace Planner that produces immutable deterministic Execution Plans from validated Workflow manifests.
- Added exact Agent and Artifact resolution, Artifact-dependency topological ordering, cycle detection, and descriptive typed planning failures.
- Added deterministic Evaluation and Approval checkpoint insertion while preserving transition intent as a non-authoritative request.
- Preserved the existing state-aware lifecycle Planner for CLI and vertical-slice compatibility under an explicit internal module.
- Added 10 tests covering plan generation, missing references, cycles, checkpoints, determinism, summaries, invalid definitions, and non-mutation.
- Added no Workflow execution, Provider or Tool calls, Approval execution, persistence, CLI changes, or Kernel state mutation.

### PR-007 - Evaluation Contract and Runner Foundation

- Added immutable EvaluationRule, EvaluationRequest, EvaluationFinding, and EvaluationResult contracts with explicit severity and rule-type enums.
- Added a pure deterministic Evaluation Runner with non-empty content, expected-schema, required-field, schema, minimum-length, regex, and injected custom-rule evaluation.
- Defined unweighted six-decimal scoring, configurable minimum score, and hard blocking for failed error/critical findings.
- Added typed configuration, request, and custom-execution failures with no generic runtime mutation behavior.
- Added 12 tests covering successful assessment, missing fields, empty content, schema mismatch, length, regex, custom rules, deterministic ordering/scoring, multiple findings, critical blocking, invalid configuration, and empty rule lists.
- Kept assessment results separate from persisted runtime Evaluation records and added no Approval, Planner, Workflow/Provider/Tool execution, CLI, persistence, Event, or Kernel mutation.

### PR-006 - Mock Provider Foundation

- Added immutable `ProviderRequest`, `ProviderResponse`, `ProviderStatus`, and structured `ProviderError` contracts.
- Added a deterministic offline Mock Provider with canonical request fingerprints, correlation/idempotency metadata, fallback output, strict JSON fixtures, simulated failures, and expected-output schema validation.
- Added typed request, fixture, and missing-fixture errors with no real Provider SDK, network access, API keys, or external dependency.
- Added 11 tests covering deterministic output, repeated requests, fixtures, missing fixtures, simulated errors, Provider metadata, network isolation, runtime non-mutation, invalid requests, output-schema failures, and immutability.
- Kept Provider behavior disconnected from Workspace, Apps, Workflows, Agents, Activities, authorization, Kernel services, persistence, CLI, and runtime state.

### PR-005 - Workspace Foundation

- Added a read-only in-memory Workspace that discovers Agent, Workflow, and App YAML beneath bounded project roots and delegates validation to PR-004.
- Added deterministic duplicate-ID, exact-reference, runtime/Kernel compatibility, App dependency compatibility, and circular dependency checks.
- Added sorted defensive `apps`, `workflows`, `agents`, `get_*`, and `summary` query APIs with no registration or mutation surface.
- Added typed discovery, duplicate, missing-reference, compatibility, dependency-cycle, and query errors.
- Added 10 tests plus duplicate-kind subtests covering empty, single-App, multi-App, duplicates, missing references, compatibility, queries, summaries, defensive results, and dependency cycles.
- Added no Planner, registry, execution, Provider, Tool, authorization, memory, CLI, persistence, state transition, or Kernel integration.

### PR-004 - Manifest Loader Foundation

- Added a stateless `founderos_runtime.manifest_loader` package with explicit Agent, Workflow, and App loading APIs.
- Added safe YAML parsing, per-kind schema selection, Draft 2020-12 validation, and established Workflow/App semantic validation.
- Added typed missing-file, read, malformed-YAML, invalid-schema, and validation exceptions carrying deterministic `file`, `field`, and `reason` details.
- Added 13 tests covering valid manifests, missing files, malformed YAML/UTF-8, invalid schemas, structural failures, unknown/missing fields, error messages, semantic regressions, deterministic selection, and no caching.
- Promoted PyYAML from development-only to a runtime dependency because manifest parsing is now executable behavior.
- Added no discovery, registry, resolution, installation, execution, Provider, Tool, CLI, State Machine, persistence, or Kernel integration.

### PR-003 - App Package Manifest Schema Foundation

- Added a self-contained JSON Schema Draft 2020-12 App Package Manifest contract expressed as YAML.
- Added a valid Discovery App example indexing the Discovery Workflow, Product Manager and Market Research Agents, Opportunity Report schema, prompt pack, Evaluation rule, policy requirement, deterministic fixture, and documentation.
- Added namespaced package identity, Semantic Versioning, canonical runtime/dependency ranges, first-party publisher metadata, content digest shape, safe package-relative paths, and immutable exact definition references.
- Added deterministic structural and semantic tests for required fields, identity, versions, maturity, non-empty Workflow/Agent indexes, duplicate Workflow IDs, runtime compatibility, dependency format, and prohibited execution/runtime-authority fields.
- Kept the App contract outside the active runtime registry; no loader, registry, marketplace, plugin installation, Workflow execution, Provider, Tool, CLI, or runtime behavior changed.

### PR-002 - Workflow Manifest Schema Foundation

- Added a self-contained JSON Schema Draft 2020-12 Workflow Manifest contract expressed as YAML.
- Added a valid conceptual Discovery Workflow with exact Agent references, Artifact declarations, ordered steps, Evaluation and Approval requirements, transition intent, recovery, and compatibility bounds.
- Structurally separated lifecycle Workflows, which require transition intent, from utility Workflows, which require null exit state and transition intent.
- Added deterministic structural and semantic tests for required fields, canonical IDs, Semantic Versioning, enums, step types, lifecycle/utility rules, and step-to-Agent reference integrity.
- Kept the new schema outside the active runtime registry; no Workflow loader, registry, execution engine, Planner, CLI, Discovery implementation, persistence, or runtime behavior changed.

### PR-001 - Agent Manifest Schema Foundation

- Added a self-contained JSON Schema Draft 2020-12 Agent Manifest contract expressed as YAML.
- Added a valid Product Manager manifest with explicit capabilities, Artifact ports, constraints, Tool-category ceiling, Provider-neutral preferences, Evaluation, handoff, status, and maturity.
- Added deterministic schema tests for required fields, canonical IDs, Semantic Versioning, maturity, Tool categories, capabilities, prohibited runtime/prompt fields, and the example.
- Added PyYAML only to development dependencies; the runtime dependency set and runtime contract loader are unchanged.
- Documented the stateless Agent boundary and its relationships to Apps, Workflows, Providers, Tools, authorization, memory, and the Kernel.

### Milestone 12A - FounderOS v0.2 Architecture Review Board

- Added a formal five-perspective architecture review of the draft FounderOS v0.2 Blueprint.
- Recommended proceeding only after resolving App/Workflow semantics, authorization order, durable execution boundaries, AI safety contracts, and the platform-first milestone sequence.
- Proposed a narrower v0.2 scope centered on first-party App packaging and one package-defined Validation vertical slice.

### Milestone 12B - Blueprint Revision and Architecture Decisions

- Revised the v0.2 Blueprint so App is packaging, Workflow remains execution, and the Kernel remains the sole runtime mutation authority.
- Replaced independent “OS” service implications with a modular-monolith dependency model and explicit outbound ports.
- Defined lifecycle and utility Workflow state authority, first-party App package boundaries, compatibility direction, and v0.2 non-goals.
- Added authorization, durable activity/effect, App package, fake structured-generation Provider, and Validation vertical-slice implementation gates.
- Reconciled roadmap, sprint, project context, README, and architecture decisions around Milestone 12C as the next step.

### Milestone 12C - Authorization Policy Foundation

- Defined runtime authorization concepts, supported Actor/Action/Resource vocabularies, deterministic decision flow, failure semantics, and future RBAC/enterprise compatibility.
- Added placeholder Draft 2020-12 schemas for AuthorizationRequest, AuthorizationDecision, PolicyRule, and AuthorizationPolicy without registering or enforcing them in the runtime.
- Specified a pure PolicyEngine interface using default-deny and deny-overrides semantics with exact Policy versions.
- Added diagrams for command, trust-boundary, and future outbound-execution flows.
- Added ADR-001 establishing that authorization precedes protected mutation while the Kernel and State Machine retain sole mutation authority.
- Clarified that authorization, authentication, and human Approval are separate concerns and that Milestone 12C changes no runtime behavior.

### RFC-0001 - Durable Activity and Side-Effect Contracts

- Defined durable Activity intent, result, lifecycle record, categories, statuses, attempts, policies, and audit facts for all future external operations.
- Defined effectively-once idempotency, deterministic retry, timeout, lease, cancellation, ambiguous-outcome reconciliation, and separate compensation semantics.
- Added placeholder ActivityExecutor, ActivityRegistry, ActivityService, ActivityPolicyEvaluator, and ActivityAuditReader interfaces without runtime implementation.
- Added seven non-loaded Draft 2020-12 Activity schemas and reserved authoritative Activity Event types.
- Added ADR-002 requiring external execution outside Kernel transactions and prohibiting executor repository/Event mutation.
- Updated the v0.2 Blueprint, runtime boundaries, observability, roadmap, sprint, project context, decisions, and README without adding any executor, Provider, Tool, or side effect.

### Milestone 11 - Developer Experience and Test Stability

- Added official PowerShell and POSIX test scripts with per-test progress and slow-test diagnostics.
- Added a `dev` dependency group containing pytest and documented editable developer installation.
- Diagnosed a protected, non-inheriting ACL on `.pytest_cache` as the cause of Windows cache access failures and reset it to inherited workspace permissions.
- Added Windows troubleshooting guidance and a policy-independent official test command.
- Verified that the reported apparent hang was the quiet 80–90 second suite run, not a surviving thread, subprocess, or shutdown deadlock.

### Milestone 11.1 - Developer Experience Bug Fix

- Removed the alternate pytest cache-path workaround after identifying the filesystem ACL root cause.
- Restored pytest's standard `.pytest_cache` behavior and documented exact ACL inspection and repair commands.
- Verified that the exact `python -m pytest -q` command returns immediately after the passing summary without warnings or interruption.

### Milestone 11.2 - Windows Stale-Lock Probe Fix

- Replaced POSIX-style `os.kill(pid, 0)` process probing on Windows with a non-signalling Win32 process-handle query.
- Guaranteed that the Windows process handle is closed after every successful probe.
- Made access-denied and indeterminate process checks fail closed so stale-lock recovery cannot remove a potentially live owner's lock.
- Added a Windows regression test proving stale-lock inspection never calls `os.kill`.

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
