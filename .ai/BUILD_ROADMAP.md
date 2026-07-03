# BUILD_ROADMAP

## Milestone 1 - Repository Reconciliation

- [x] Repository scaffold
- [x] Official `.ai/` governance location
- [x] Architecture Specification v1.0-alpha
- [x] Initial state catalogue
- [x] Thin Master Orchestrator specification
- [x] Honest status labels for planned placeholders

## Milestone 2 - Executable Runtime Contracts

- [x] Define canonical identifiers and versioning
- [x] Define machine-valid core-object schemas
- [x] Define Project, workflow-run, agent-run, transition, evaluation, approval, and event records
- [x] Define state-transition guards and recovery behavior
- [x] Define persistence and state-mutation boundaries
- [x] Define contract-level acceptance scenarios
- [x] Replace runtime placeholders with contract-level component specifications

## Milestone 3 - Runtime Foundation

- [x] Minimal Python package and dependency baseline
- [x] Contract loading and JSON Schema validation
- [x] In-memory repositories for required runtime records
- [x] Project State with optimistic revisions
- [x] Guarded State Machine transitions
- [x] Ordered Event append and Project replay
- [x] Basic WorkflowRun and AgentRun lifecycles
- [x] Automated contract acceptance scenarios

## Milestone 4 - Runtime Planner Engine

- [x] Immutable ExecutionContext
- [x] Immutable ExecutionPlan
- [x] State-aware WorkflowSelector
- [x] Approved-artifact gap analysis
- [x] Deterministic AgentRouter
- [x] State Machine route and quality-gate integration
- [x] Explicit blocking reasons and unknown-state rejection
- [x] Non-mutation and determinism tests

## Milestone 5 - First Executable Vertical Slice

- [x] Create or resume a project in the active runtime
- [x] Produce, validate, persist, and approve a structured Founder Brief
- [x] Persist run, evaluation, approval, event, artifact, and transition records in memory
- [x] Verify deterministic replay/resume behavior and idempotent completion

## Milestone 6 - FounderOS CLI

- [x] Add thin standard-library command parsing
- [x] Add `new`, `status`, `plan`, `founder-brief`, `approve`, `decisions`, and `events`
- [x] Persist one local Project as JSON, JSONL Events, and Artifact JSON files
- [x] Reload and validate runtime records across CLI invocations
- [x] Preserve Planner, Approval, and State Machine boundaries
- [x] Add CLI acceptance coverage

## Milestone 7 - Persistence Hardening

- [x] Add exclusive single-writer protection
- [x] Reject stale writes using monotonic store revisions
- [x] Create a validated backup before replacing committed files
- [x] Detect corrupt/missing state, Event errors, replay mismatch, and Artifact digest mismatch
- [x] Add explicit backup recovery and persistence health reporting
- [x] Add format-version migration structure and future-version rejection
- [x] Add corruption, locking, stale-write, migration, and recovery tests

## Milestone 8 - Runtime Service Boundary Hardening

- [x] Replace persistence hydration through repository internals with explicit import/export ports
- [x] Extract Artifact, Evaluation, and Approval lifecycle operations from the Founder Setup coordinator
- [x] Retain WorkflowRun and AgentRun services as reusable lifecycle boundaries
- [x] Persist command idempotency keys independently of in-process service instances
- [x] Define stale-lock inspection and guarded manual lock removal
- [x] Add failure-injection coverage across multi-file save phases

## Milestone 9 - Runtime Observability and Audit Diagnostics

- [x] Define structured runtime diagnostic summaries without adding a database
- [x] Add command correlation and operation timing summaries
- [x] Add inspectable run, transition, approval, Artifact, and persistence diagnostics
- [x] Add default redaction and explicit sensitive-content opt-in
- [x] Add end-to-end audit consistency checks
- [x] Add read-only audit, runs, and transitions CLI commands

## Milestone 10 - Discovery Workflow v1

- [x] Add deterministic Discovery service and static candidate input
- [x] Define Opportunity Report and Candidate contracts
- [x] Compute and rank six-factor scores deterministically
- [x] Persist runs, Artifact, Evaluation, Approval, and selection Decision
- [x] Apply guarded transitions through `DISCOVERY_RUNNING` to `OPPORTUNITY_SELECTED`
- [x] Add CLI, audit traceability, replay, and acceptance tests

## Milestone 11 - Developer Experience and Test Stability

- [x] Diagnose Windows pytest completion behavior
- [x] Diagnose and repair invalid Windows ACLs on pytest's standard cache path
- [x] Add official PowerShell and POSIX test scripts
- [x] Define pytest as an installable development dependency
- [x] Document editable setup, test commands, and Windows troubleshooting
- [x] Preserve runtime and CLI behavior while verifying the full suite

### Milestone 11.1 - Developer Experience Bug Fix

- [x] Reproduce pytest cache access under the exact quiet command
- [x] Prove no runtime thread, subprocess, lock, or cleanup leak exists
- [x] Identify the protected non-inheriting `.pytest_cache` ACL
- [x] Restore inherited workspace permissions
- [x] Remove the alternate cache-directory workaround
- [x] Verify warning-free normal process termination

### Milestone 11.2 - Windows Stale-Lock Probe Fix

- [x] Isolate the hanging service-boundary lock test
- [x] Remove POSIX signal probing from the Windows runtime path
- [x] Use non-signalling Win32 process inspection with deterministic handle cleanup
- [x] Add Windows-specific regression coverage
- [x] Verify the service-boundary file and full suite terminate normally

## Milestone 12A - FounderOS v0.2 Architecture Review Board

- [x] Review the draft v0.2 Blueprint from enterprise, distributed systems, AI, software, and startup perspectives
- [x] Identify conflicting App/Workflow semantics and missing trust/execution boundaries
- [x] Recommend a narrower vertical-slice-driven v0.2 scope
- [x] Record conditional approval: proceed with changes

## Milestone 12B - Blueprint Revision and Architecture Decisions

- [x] Define App as a package and Workflow as the executable unit
- [x] Establish a modular-monolith dependency model with outbound ports
- [x] Preserve the Kernel and State Machine as sole domain/state mutation authorities
- [x] Define lifecycle versus utility Workflows
- [x] Define first-party App package contents and compatibility direction
- [x] Narrow v0.2 scope and explicit non-goals
- [x] Establish authorization, durable activity, package, fake-provider, and Validation implementation gates

## Milestone 12C - Authorization Policy Foundation

- [x] Define Actor, Action, Resource, Effect, Condition, Policy, and Decision concepts
- [x] Define placeholder AuthorizationRequest, AuthorizationDecision, PolicyRule, AuthorizationPolicy, and PolicyEngine contracts
- [x] Define deterministic default-deny and deny-overrides evaluation
- [x] Reserve authorization checks before every owning Kernel mutation boundary
- [x] Separate authorization from authentication, RBAC, and human Approval
- [x] Add redaction, future enterprise compatibility, diagrams, and an authorization ADR
- [x] Preserve runtime behavior by keeping contracts outside the active ContractRegistry

## Milestone 12D - Durable Activity and Side-Effect Contracts

- [x] Define Activity, Request, Result, Record, category, status, attempt, and policy concepts
- [x] Define retry, timeout, cancellation, compensation, lease, receipt, and failure semantics
- [x] Define stable idempotency, replay, ambiguous-outcome, and reconciliation rules
- [x] Define ActivityExecutor, ActivityRegistry, ActivityService, policy evaluator, and audit reader placeholder interfaces
- [x] Define Activity audit Events, correlation, redaction, and observability
- [x] Add RFC-0001, placeholder Draft 2020-12 contracts, and ADR-002
- [x] Keep executors, Providers, Tools, queues, workers, and runtime behavior out of scope

Authorization runtime enforcement remains mandatory before Provider or Tool execution. Milestone 12C defines the boundary but intentionally does not wire it into current services.

## Milestone 12E - Minimal First-Party App Package Contract (Deferred)

- [ ] Define package identity, Kernel compatibility, asset index, configuration, and historical resolution
- [ ] Reuse existing Agent and Workflow definitions and registries
- [ ] Define lifecycle versus utility Workflow contract extensions only as required

## Milestone 12F - Fake Structured-Generation Provider

- [ ] Define canonical structured generation requests/results, budgets, and typed failures
- [ ] Add versioned prompt rendering and deterministic fake behavior
- [ ] Keep real Provider integration out of scope

## Milestone 12G - Validation App Vertical Slice

- [ ] Package Validation as the first bundled first-party App
- [ ] Reuse Kernel Artifact, Evaluation, Approval, Decision, Transition, Event, replay, and audit boundaries
- [ ] Demonstrate value from `OPPORTUNITY_SELECTED` without Web, marketplace, broad Tools, or real Providers

## FounderOS v0.3 Contract Foundations

### PR-001 - Agent Manifest Schema Foundation

- [x] Add a strict, versioned Agent Manifest schema outside the active runtime loader
- [x] Add a valid Product Manager example
- [x] Define status, maturity, capabilities, Artifact ports, constraints, Tool categories, Provider-neutral preferences, Evaluation, and handoff metadata
- [x] Prohibit prompts, secrets, model configuration, runtime state, memory, and conversation history
- [x] Add deterministic independent schema validation tests
- [x] Preserve all existing runtime behavior

### PR-002 - Workflow Manifest Schema Foundation

- [x] Define the versioned Workflow Manifest contract
- [x] Reference exact Agent Manifest IDs and versions
- [x] Preserve lifecycle versus utility Workflow semantics
- [x] Define steps, Artifact declarations, Evaluations, Approvals, transition intent, recovery, and compatibility
- [x] Add a Discovery example and deterministic structural/semantic validation
- [x] Preserve all existing runtime behavior

### PR-003 - Minimal First-Party App Package Manifest Foundation

- [x] Define immutable namespaced package identity, runtime compatibility, and bundled first-party trust metadata
- [x] Index exact Workflow and Agent definitions plus schemas, prompts, rubrics, fixtures, and documentation
- [x] Define content digest shape, bounded dependencies, and safe package-relative paths
- [x] Add a Discovery App example and deterministic structural/semantic validation
- [x] Preserve all existing runtime behavior

### PR-004 - Manifest Loader Foundation

- [x] Add explicit Agent, Workflow, and App YAML loading APIs
- [x] Validate schemas, structure, and established semantic invariants deterministically
- [x] Return defensive parsed objects and typed file/field/reason failures
- [x] Keep loading stateless, uncached, read-only, and independent from Kernel, execution, Providers, and registries
- [x] Add comprehensive loader and regression tests

### PR-005 - Workspace Foundation

- [x] Discover Agent, Workflow, and App manifests beneath explicit bounded roots
- [x] Delegate every discovered manifest to PR-004 loading and validation
- [x] Build exact App/Workflow/Agent relationships and reject duplicate IDs or missing references
- [x] Enforce runtime, Kernel, and App dependency compatibility plus cycle detection
- [x] Expose sorted defensive read-only query and summary APIs
- [x] Preserve all existing Planner, registry, execution, Provider, Tool, CLI, and Kernel behavior

### PR-006 - Mock Provider Foundation

- [x] Define immutable structured Provider request, response, status, and error contracts
- [x] Add deterministic fallback and exact fixture-based responses
- [x] Add simulated Provider failures and expected-output schema validation
- [x] Preserve correlation and idempotency metadata without timestamps or randomness
- [x] Require no network, API keys, real Provider SDK, registry, execution, Activity, or Kernel integration
- [x] Add comprehensive deterministic and isolation tests

### PR-007 - Evaluation Contract and Runner Foundation

- [x] Define immutable Evaluation rules, requests, findings, results, severities, and rule types
- [x] Add deterministic content, expected-schema, required-field, schema, minimum-length, regex, and custom-rule checks
- [x] Define configurable score thresholds and hard-blocking error/critical semantics
- [x] Keep assessment separate from persisted runtime Evaluation records and human Approval
- [x] Add comprehensive deterministic contract and runner tests
- [x] Preserve all Planner, Workflow, Provider, Tool, CLI, persistence, and Kernel behavior

### PR-008 - Planner Foundation

- [x] Produce immutable deterministic Execution Plans from Workspace Workflows
- [x] Resolve exact Agent and Artifact references
- [x] Order steps from Artifact dependencies and reject cycles
- [x] Insert declared Evaluation and Approval checkpoints
- [x] Preserve transition intent as a non-authoritative request
- [x] Add no Workflow execution, persistence, CLI, or Kernel mutation

### PR-009 - Founder Journey Runner Foundation

- [x] Ask the Workspace Planner for one immutable Execution Plan
- [x] Execute deterministic sequential Agent tasks through Mock Provider only
- [x] Run Evaluation checkpoints and stop on critical findings
- [x] Return immutable in-memory Journey results and ordered logs
- [x] Explicitly skip Approval, transition, and Activity execution
- [x] Add no persistence, CLI, real Provider, or Project/Kernel mutation

### PR-010 - Plan Validation and Authorization Foundation

- [x] Validate Workflow, Agent, Artifact, ID, dependency, order, and Evaluation checkpoint integrity
- [x] Apply deterministic missing-validation, unknown-capability, high-risk, and safe-plan policies
- [x] Gate Journey execution on validation and authorization decisions
- [x] Return descriptive failures without Provider calls or mutation
- [x] Add no human Approval, persistence, CLI, real Provider, or Kernel mutation

### PR-011 - Evaluation Rubric Manifest and Loader Foundation

- [x] Define immutable rubric identity, version, target, threshold, and deterministic rule metadata
- [x] Add an Opportunity Report rubric example
- [x] Load and validate rubric manifests through the stateless Manifest Loader
- [x] Map rubric rules exactly to the existing deterministic Evaluation Runner
- [x] Add no real Provider, human Approval, persistence, or Kernel mutation

### PR-012 - Discovery Vertical Slice Foundation

- [x] Add a complete first-party Discovery package with exact Agent, Workflow, App, rubric, schema, input, and fixture assets
- [x] Compose Workspace, Planner, Plan Validation, Authorization, Journey Runner, Mock Provider, and Evaluation Rubric in memory
- [x] Supply the Founder Brief as an actual in-memory input Artifact and resolve the exact bounded rubric reference
- [x] Prove deterministic output, network isolation, and persistence/runtime non-mutation
- [x] Add no CLI, real Provider, human Approval execution, persistence, Web UI, or Kernel mutation

### PR-013 - FounderOS CLI Alpha

- [x] Add `version`, `doctor`, `demo discovery`, and `help` through a standard-library CLI package
- [x] Present deterministic Journey progress, Artifact, Evaluation, status, and duration information
- [x] Keep orchestration, validation, authorization, and execution in existing runtime components
- [x] Preserve established local Project CLI behavior through a compatibility adapter
- [x] Add no persistence for the demo, real Provider, Web UI, or Kernel mutation

### EPIC-001 / PR-014 - Atlas Discovery Engine Foundation

- [x] Add Atlas as a first-party App package separate from the FounderOS runtime
- [x] Define immutable vendor-neutral Device, Interface, Neighbor, Fact, and DiscoveryResult models
- [x] Add a transport-free DiscoveryAdapter and deterministic Cisco IOS fixture parser
- [x] Add in-memory DiscoveryEngine and TopologyGraph components
- [x] Validate Atlas manifests and prove fixture-only, network-free deterministic behavior
- [x] Add no SSH, SNMP, credentials, persistence, GUI, API, device mutation, or real AI

### PR-015 - Atlas Multi-Device Topology Reconciliation

- [x] Reconcile multiple fixture/mock DiscoveryResult observations through deterministic identity priority
- [x] Preserve unique interfaces, metadata, and neighbor relationships on canonical devices
- [x] Add identity-aware result/graph merge, lookup, counts, warnings, and summaries
- [x] Record deterministic conflicts without silent overwrite
- [x] Extend the CLI demo with before/after reconciliation output
- [x] Preserve transport-free, in-memory, vendor-neutral boundaries

### PR-016 - Atlas Topology Snapshot Contract and Evaluation

- [x] Define immutable deterministic TopologySnapshot creation from reconciled graphs
- [x] Add content-addressed IDs and optional caller-supplied deterministic timestamps
- [x] Add defensive dictionary, stable JSON, and human-readable Markdown exports
- [x] Replace the preliminary schema with a complete versioned Topology Snapshot contract
- [x] Align the deterministic topology rubric and CLI demo summary
- [x] Keep snapshots in memory with no database, GUI, live transport, or device mutation

### PR-017 - Atlas Interactive Topology Viewer

- [x] Render a TopologySnapshot as deterministic Cytoscape nodes and edges
- [x] Add a plain-HTML interactive viewer with layout, pan, zoom, fit, details, tooltips, and search
- [x] Add `founderos atlas demo topology` as a thin fixture-only delivery adapter
- [x] Write one standalone HTML document and open it through the default browser
- [x] Keep discovery, reconciliation, Snapshot creation, and visualization responsibilities separated
- [x] Add no persistence, GUI framework, live transport, AI, authentication, or editing

### EPIC-002 / PR-018 - Atlas Morning Brief Journey

- [x] Define a declarative Atlas Morning Brief utility Workflow
- [x] Compare a current Snapshot with an optional previous Snapshot deterministically
- [x] Produce an immutable structured MorningBrief and human-readable Markdown
- [x] Execute through Workspace, Planner, plan validation, authorization, Journey Runner, and Evaluation
- [x] Add deterministic quality rules and a scored Evaluation result
- [x] Add `founderos atlas morning-brief` with CLI-owned Markdown delivery
- [x] Add no AI, network access, persistence, scheduling, notifications, GUI, or state mutation

### EPIC-002 / PR-019 - Atlas Topology Change Set Foundation (Next)

- [ ] Extract reusable deterministic Snapshot comparison from Morning Brief composition
- [ ] Classify added, removed, and changed devices, interfaces, edges, and warnings
- [ ] Produce immutable machine-readable change evidence for multiple operational Journeys
- [ ] Add no persistence, live transport, AI, scheduling, or automated remediation

## Deferred Runtime Hardening

- Database-grade persistence adapters
- Knowledge Entry schema and executable Knowledge Base
- Authentication and authorization
- Observability and cost accounting
- Full workflow step execution and external tool/AI adapters

## Conditional v0.2 Follow-ups

- One read-only Tool or Knowledge capability only if required by Validation
- One opt-in real Provider adapter only after fake-provider acceptance and a security/cost review
- v0.2 adoption review before adding further platform breadth

## Later Milestones

- Discovery, Validation, and Product runtimes
- Engineering, AI, Development, UX, QA, and Deployment runtimes
- Growth, Sales, and CEO Review runtimes

Later lifecycle modules must not begin before the executable runtime contracts, planner, and first vertical slice are validated.
