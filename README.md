# FounderOS

FounderOS is an AI operating system for helping technical founders discover, validate, design, build, and launch B2B SaaS products.

## Current Version

v0.1-alpha

## Current Status

FounderOS is an architecture and runtime-specification project. It is not yet an executable application.

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

In progress:

- First executable Founder Brief vertical slice planning (Milestone 5)

Most lifecycle agent, prompt, template, domain, and roadmap files remain explicitly marked as planned placeholders. No application runtime, CLI, web application, Discovery, Validation, or Product module has been implemented.

## Runtime Contracts

The authoritative implementation contracts are indexed in [`runtime/contracts/README.md`](runtime/contracts/README.md). They define canonical identifiers, versioning, the five core objects, supporting runtime records, guarded transitions, recovery, persistence boundaries, and acceptance scenarios.

## Runtime Foundation

FounderOS uses Python 3.11+ and one runtime dependency, `jsonschema` 4.x. The package lives in `src/founderos_runtime/`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

The runtime can currently validate contracts, create Projects in memory, manage basic WorkflowRun and AgentRun lifecycles, resolve exact references, enforce optimistic revisions and transition guards, append ordered Events, replay Project state, and atomically apply or reject transitions.

The read-only Runtime Planner can build an ExecutionContext from repository state and produce a deterministic ExecutionPlan. It recommends workflows and agent roles, identifies missing approved artifacts, exposes allowed transitions and quality gates, and clearly blocks invalid progress without mutating repositories.

It has no durable database, workflow executor, CLI, web UI, authentication, LLM calls, Discovery content generation, or Validation content generation.

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
