# FounderOS

FounderOS is an AI operating system for helping technical founders discover, validate, design, build, and launch B2B SaaS products.

## Current Version

v0.1-alpha

## Current Status

FounderOS now has an executable Founder Setup vertical slice and a minimal local CLI. It is not yet a production application.

Completed foundations:

- Repository scaffold
- AI governance in `.ai/`
- Architecture Specification v1.0-alpha
- Guarded state-transition and recovery specification
- Thin Master Orchestrator specification
- JSON Schema Draft 2020-12 contracts for five core objects and seven runtime records
- Persistence, state-mutation, and contract acceptance specifications
- Python runtime package with real JSON Schema validation
- In-memory repositories, Project State, ordered Events, guarded transitions, and run lifecycles
- Executable coverage of all 14 contract acceptance scenarios
- Deterministic Runtime Planner for workflow, artifact, agent-role, quality-gate, and next-state recommendations
- Structured Founder Brief content validation and immutable in-memory content storage
- Executable Founder Setup through human approval, guarded completion, and deterministic replay/resume
- Standard-library CLI with local JSON/JSONL persistence
- Single-writer locking, optimistic store revisions, validated backups, recovery, migrations, and persistence health checks
- Public repository import/export ports and reusable Artifact, Evaluation, Approval, WorkflowRun, and AgentRun lifecycle services
- Restart-safe idempotency keys for important CLI mutations
- Read-only correlated audit diagnostics with default sensitive-field redaction
- Deterministic local Discovery Workflow v1 producing an approved Opportunity Report and selection Decision
- Architecture-reviewed and revised FounderOS v0.2 Blueprint with explicit App, Workflow, Kernel, policy, and outbound-port boundaries
- Runtime authorization architecture with deterministic default-deny contracts and a Kernel-boundary ADR
- RFC-0001 durable Activity and side-effect contracts with idempotency, retry, cancellation, compensation, receipts, and audit semantics
- PR-001 Agent Manifest schema with an independently validated Product Manager definition
- PR-002 Workflow Manifest schema with lifecycle/utility boundaries and a validated Discovery definition
- PR-003 App Package Manifest schema with immutable first-party asset indexing and a validated Discovery App
- PR-004 deterministic Manifest Loader for explicit Agent, Workflow, and App YAML validation
- PR-005 read-only Workspace for bounded discovery, relationships, compatibility, and deterministic queries
- PR-006 immutable Provider contracts and a deterministic offline Mock Provider
- PR-007 immutable Evaluation contracts and deterministic quality-rule runner
- PR-008 deterministic Workspace Planner with immutable execution plans, dependency ordering, and quality/approval checkpoints
- PR-009 deterministic in-memory Journey Runner over Planner, Mock Provider, and Evaluation
- PR-010 deterministic ExecutionPlan validation and plan-scoped authorization preflight

Next: PR-011 Evaluation Rubric Manifest and Loader Foundation, replacing the Journey harness's minimal evaluation floor without adding real Providers or persistence.

Most lifecycle agent, prompt, template, domain, and roadmap files remain explicitly marked as planned placeholders. No web application, Validation, or Product module has been implemented; Discovery is currently deterministic and local-only.

## Runtime Contracts

The authoritative implementation contracts are indexed in [`runtime/contracts/README.md`](runtime/contracts/README.md). They define canonical identifiers, versioning, the five core objects, supporting runtime records, guarded transitions, recovery, persistence boundaries, and acceptance scenarios.

The revised [`FounderOS v0.2 Blueprint`](architecture/FounderOS_v0.2_Blueprint.md) defines App as first-party packaging over existing definitions, keeps Workflow as the executable unit, preserves the Kernel as sole mutation authority, and gates Provider/Tool work behind authorization and durable side-effect contracts. The supporting [Architecture Review](docs/reviews/FounderOS_v0.2_Architecture_Review.md) records the rationale and deferred scope.

[`runtime/authorization.md`](runtime/authorization.md) defines Actor, Action, Resource, Effect, Condition, Policy, AuthorizationRequest, AuthorizationDecision, and deterministic PolicyEngine semantics. The related schemas are placeholders under `runtime/contracts/authorization/`; they are intentionally not loaded or enforced by the current runtime. Authorization is not authentication, does not replace human Approval, and an allow decision never mutates Kernel state.

[`RFC-0001`](docs/rfcs/RFC-0001-durable-activity-and-side-effect-contracts.md) defines the required boundary for future external operations. Workflows create durable Activity intent through a future Kernel service; executors run outside Kernel transactions and submit immutable results/receipts. Replay reuses recorded results and never repeats an external effect. Placeholder schemas under `runtime/contracts/activity/` are intentionally not loaded or implemented.

[`runtime/contracts/agent/`](runtime/contracts/agent/) contains the first v0.3 package contract: a strict, versioned Agent Manifest schema and Product Manager example. Manifests declare stateless role metadata and constraints; they contain no prompts, secrets, memory, runtime state, Provider/model configuration, or execution behavior.

[`runtime/contracts/workflow/`](runtime/contracts/workflow/) defines the strict, versioned Workflow Manifest and a conceptual Discovery example. Lifecycle Workflows may declare transition intent; utility Workflows are structurally barred from doing so. Manifests coordinate declarations only: they do not execute steps, grant authorization, perform Activities, create Approvals, or mutate Project state.

[`runtime/contracts/app/`](runtime/contracts/app/) defines the strict, versioned App Package Manifest and a Discovery App example. Apps index exact Workflow and Agent definitions plus schemas, prompts, Evaluation rules, policy requirements, fixtures, documentation, and bounded dependencies. Apps are packaging only: they do not execute, grant capabilities, own memory, call Providers or Tools, or mutate the runtime.

[`founderos_runtime.manifest_loader`](src/founderos_runtime/manifest_loader/) explicitly loads and validates requested Agent, Workflow, and App YAML paths. It returns defensive parsed objects and typed deterministic errors; it performs no discovery, caching, registration, reference resolution, execution, authorization, persistence, or Kernel mutation.

[`founderos_runtime.workspace`](src/founderos_runtime/workspace/) builds a fresh read-only semantic snapshot from validated manifests beneath one bounded project root. It detects duplicates, missing exact references, runtime/dependency incompatibility, and App dependency cycles, then exposes sorted defensive query results. It has no registry lifecycle, execution, Provider, Tool, authorization, memory, persistence, CLI, or Kernel mutation behavior.

[`founderos_runtime.provider`](src/founderos_runtime/provider/) defines frozen structured generation requests/responses and an offline deterministic Mock Provider. It supports exact fixtures, simulated failures, output-schema validation, correlation, and idempotency metadata without network access, API keys, real models, Provider registry, Activities, execution, persistence, or Kernel mutation.

[`founderos_runtime.evaluation`](src/founderos_runtime/evaluation/) defines frozen rules, requests, findings, results, and a pure deterministic Evaluation Runner. It supports required fields, schemas, minimum lengths, regexes, custom rules, score thresholds, and hard-blocking severity without invoking Providers, executing Workflows, recording Approvals, persisting `evl_` records, or mutating runtime state.

[`founderos_runtime.planner`](src/founderos_runtime/planner/) converts one validated Workspace Workflow into an immutable, deterministic Execution Plan. It resolves exact Agent and Artifact references, orders steps by Artifact dependencies, adds declared Evaluation and Approval checkpoints, and reports non-authoritative transition intent. It does not execute steps, call Providers or Tools, approve work, persist records, or mutate the Workspace or Kernel. The earlier state-aware lifecycle planner remains available through the package root for CLI and vertical-slice compatibility.

[`founderos_runtime.journey`](src/founderos_runtime/journey/) is a deterministic in-memory orchestration harness. It asks the Workspace Planner for one plan, executes sequential Agent tasks through `MockProvider`, runs deterministic Evaluation checkpoints, stops on critical findings, and returns an immutable `JourneyResult`. Approval, transition, and Activity steps are explicitly skipped; no files, Events, repositories, Project state, real Providers, or external systems are touched.

[`founderos_runtime.validation`](src/founderos_runtime/validation/) verifies Workflow, Agent, Artifact, ID, dependency-order, cycle, and Evaluation-checkpoint invariants on an immutable ExecutionPlan. [`founderos_runtime.authorization`](src/founderos_runtime/authorization/) then applies fixed deterministic default-deny capability policies. Validation, authorization, Approval, and execution remain distinct: neither preflight component executes work, performs human Approval, persists data, or grants Kernel mutation authority.

## Developer Setup and Testing

FounderOS requires Python 3.11+. Create a virtual environment and install the editable package with its test dependency:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Run the complete suite on Windows PowerShell with the official command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

On Linux, macOS, or Git Bash:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
sh ./scripts/test.sh
```

The direct runner command is also supported:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

### Windows Test Troubleshooting

- A normal full run currently takes roughly 80Ã¢â‚¬â€œ90 seconds. The official script prints every test so expected work does not look like a stalled process.
- Pytest uses its standard ignored `.pytest_cache` directory. If it reports `Access is denied`, inspect `icacls .pytest_cache`; a protected non-inheriting ACL is invalid for this workspace.
- Repair that disposable cache with `icacls .pytest_cache /reset /T /C`. This restores inherited workspace permissions without redirecting or disabling pytest's cache provider.
- Stale writer-lock inspection uses a non-signalling Win32 process query. It does not use POSIX-style `os.kill(pid, 0)` on Windows.
- The official command applies `ExecutionPolicy Bypass` only to its child PowerShell process; it does not modify the user or machine policy.
- If a run truly stops producing progress, press Ctrl+C once and retain the traceback; it identifies the active test instead of masking it as a shutdown problem.

## Runtime Foundation

FounderOS uses `jsonschema` 4.x for contract validation and PyYAML 6.x for safe manifest parsing. The package lives in `src/founderos_runtime/`.

The runtime can currently validate contracts, create Projects in memory, execute Founder Setup, persist a structured Founder Brief in memory, require human approval, enforce optimistic revisions and transition guards, append ordered Events, and replay Project state.

The read-only Runtime Planner can build an ExecutionContext from repository state and produce a deterministic ExecutionPlan. It recommends workflows and agent roles, identifies missing approved artifacts, exposes allowed transitions and quality gates, and clearly blocks invalid progress without mutating repositories.

It has no database, general workflow executor, web UI, authentication, LLM calls, external Discovery research, or Validation content generation.

## CLI

Install the package in editable mode, then create a project:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
founderos new --name "My SaaS" --founder-name "Founder" --domain "B2B SaaS"
founderos status
founderos plan
```

Create `founder-brief.json` with `founder_profile`, `startup_context`, and optional `assumptions`, `risks`, and `open_questions`, then run:

```powershell
founderos founder-brief --input founder-brief.json
founderos approve --rationale "The brief accurately represents my constraints"
founderos decisions
founderos events
founderos health
founderos recover
founderos audit
founderos runs
founderos transitions
```

After Founder Setup reaches `FOUNDER_BRIEF_COMPLETE`:

```powershell
founderos discovery --input opportunities.json --idempotency-key discovery-1
founderos approve-opportunity --rationale "Highest deterministic score" --idempotency-key select-1
```

Discovery input is either a candidate array or `{ "candidates": [...] }`. Each candidate supplies a problem, target user, six integer scores from 0Ã¢â‚¬â€œ10, assumptions, and risks. `total_score` is the deterministic unweighted sum.

Mutation commands accept `--idempotency-key KEY`. Reusing the same key for the same command returns its persisted result without duplicating Projects, Artifacts, Approvals, runs, transitions, or Events. Reusing a key for another command is rejected.

`founderos audit` returns an ordered timeline, command correlations and timing, Project and persistence diagnostics, runs, approvals, evaluations, transitions, artifacts, and consistency checks. Founder Brief content and sensitive rationale fields are redacted by default; use `founderos audit --include-sensitive` only when explicitly required.

Use `--project-dir PATH` before the command to choose a store other than `.founderos`. CLI output is JSON. Local state uses `.founderos/project-state.json`, `.founderos/events.jsonl`, and `.founderos/artifacts/*.json`; the last validated pre-write state is retained under `.founderos/backup/`.

`founderos health` validates schemas, Event ordering and replay, Artifact digests, format support, backup validity, and writer-lock state. If health reports `recoverable`, `founderos recover` restores and revalidates the last backup. Recovery may lose the most recent write because the backup intentionally represents the preceding committed state.

## AI and Engineering Onboarding

Start with [`.ai/README.md`](.ai/README.md) and follow the documents in the listed order.

## First Specialization

Enterprise Networking SaaS

## Workflow

1. Founder Brief
2. Discovery
3. Validation
4. Product Design
5. Engineering
6. Development
7. Launch
8. CEO Review

This lifecycle is the intended product direction; the modules are not implemented yet.
