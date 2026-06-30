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

Next: runtime observability and audit diagnostics (Milestone 9).

Most lifecycle agent, prompt, template, domain, and roadmap files remain explicitly marked as planned placeholders. No web application, Discovery, Validation, or Product module has been implemented.

## Runtime Contracts

The authoritative implementation contracts are indexed in [`runtime/contracts/README.md`](runtime/contracts/README.md). They define canonical identifiers, versioning, the five core objects, supporting runtime records, guarded transitions, recovery, persistence boundaries, and acceptance scenarios.

## Runtime Foundation

FounderOS uses Python 3.11+ and one runtime dependency, `jsonschema` 4.x. The package lives in `src/founderos_runtime/`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

The runtime can currently validate contracts, create Projects in memory, execute Founder Setup, persist a structured Founder Brief in memory, require human approval, enforce optimistic revisions and transition guards, append ordered Events, and replay Project state.

The read-only Runtime Planner can build an ExecutionContext from repository state and produce a deterministic ExecutionPlan. It recommends workflows and agent roles, identifies missing approved artifacts, exposes allowed transitions and quality gates, and clearly blocks invalid progress without mutating repositories.

It has no database, general workflow executor, web UI, authentication, LLM calls, Discovery content generation, or Validation content generation.

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
```

Mutation commands accept `--idempotency-key KEY`. Reusing the same key for the same command returns its persisted result without duplicating Projects, Artifacts, Approvals, runs, transitions, or Events. Reusing a key for another command is rejected.

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
