# FounderOS Milestone 12B Handoff

Milestone 12B — Blueprint Revision and Architecture Decisions is complete.

## Outcome

The FounderOS v0.2 Blueprint has been revised from a broad collection of implied “OS” platforms into an incremental, implementation-gated modular-monolith architecture.

The revised Blueprint incorporates the Architecture Review Board's **Proceed with changes** recommendation while preserving the long-term AI operating platform vision.

No application code, runtime behavior, schemas, tests, Agent OS runtime, App registry, Provider integration, Tool, Knowledge runtime, or Validation implementation was added.

## Blueprint changes

### Terminology and authority

- **App** is an immutable, versioned package/container/bundle of definitions and assets.
- **Workflow** remains the sole executable process definition.
- **WorkflowRun** remains the runtime execution record.
- **Agent** is a versioned role/capability performer selected by a Workflow.
- **Tool** is a controlled external capability accessed through policy and an executor port.
- **Provider** is an AI/model backend behind a canonical generation port.
- **Kernel** is the sole runtime domain-mutation authority.
- Only the State Machine may change `Project.current_state`.

App is not a sixth core object and has no independent execution, storage, Event, policy, approval, or state-transition authority.

### Modular-monolith dependency model

The previous diagram implying independent Agent OS, Workflow OS, Knowledge OS, and Tool Platform services was replaced with:

```text
CLI / future API
        |
Application commands and queries / Master Orchestrator facade
        |
Planner + Workflow coordination
        |
FounderOS Kernel domain services
        |
Outbound ports
  - Persistence and Event Store
  - AI structured-generation Provider
  - Tool Executor
  - Knowledge Repository/Retriever
  - Secret and Configuration Provider
```

The “OS” labels now describe possible future capability families only. They are not v0.2 processes, services, databases, or independent mutation authorities.

### Workflow classifications

Lifecycle Workflows may request guarded Project lifecycle transitions. They still cannot update Project state directly.

Utility Workflows may produce Artifacts, Evaluations, Decisions, run records, and Events through Kernel services but cannot change or imply changes to `Project.current_state`.

This prevents future review, documentation, incident, or networking Apps from distorting the startup lifecycle state machine.

### First-party App package boundary

An App package contains or references:

- package identity and Semantic Version;
- compatible Kernel contract version range;
- included Workflow definitions;
- referenced Agent definitions;
- Artifact content schemas;
- prompt templates and input/output schemas;
- Evaluation rubrics;
- required policies/capabilities;
- deterministic fixtures and tests; and
- optional documentation or domain resources.

The manifest indexes these assets. It does not duplicate Workflow steps, entry/exit behavior, retry policy, quality gates, approvals, or transitions.

Only bundled first-party packages are in v0.2 scope.

## v0.2 non-goals

The Blueprint now explicitly excludes:

- App Marketplace;
- third-party App installation or arbitrary package code;
- Web or Desktop UI;
- cloud or multi-user runtime;
- real LLM integration before the fake-provider gate;
- broad Tool catalogue or external-write Tools;
- Knowledge OS service or knowledge graph;
- vector database and embeddings;
- organization, domain, global, or cross-Project memory;
- multi-provider routing and fallback;
- REST API implementation;
- microservices;
- billing, enterprise RBAC, and cloud sync.

## Architecture decisions added

### D-047 — App is packaging

App packages definitions and assets. It is not a core runtime object or execution authority.

### D-048 — Workflow remains executable

Existing Workflow and WorkflowRun contracts remain the single process definition and execution model.

### D-049 — Kernel owns mutation

Apps, Agents, Providers, Tools, interfaces, and orchestration cannot bypass Kernel services or the State Machine.

### D-050 — Lifecycle versus utility Workflows

Only lifecycle Workflows may request guarded Project transitions. Utility Workflows have no Project lifecycle state effect.

### D-051 — Modular monolith and outbound ports

Provider, Tool, Knowledge, persistence, Event, and secret/configuration capabilities remain behind ports rather than independent services.

### D-052 — Authorization precedes external execution

Provider and Tool execution cannot begin until deny-by-default authorization and protected-boundary enforcement exist.

### D-053 — Validation drives platform extraction

One bundled package-defined Validation vertical slice will determine the minimum reusable App, Agent, Workflow, prompt, Provider, and evidence extensions.

## Revised roadmap

- Milestone 12A — Architecture Review Board: complete
- Milestone 12B — Blueprint Revision and Architecture Decisions: complete
- Milestone 12C — Authorization Policy Foundation: next
- Milestone 12D — Durable Activity and Side-Effect Contracts
- Milestone 12E — Minimal First-Party App Package Contract
- Milestone 12F — Fake Structured-Generation Provider
- Milestone 12G — Validation App Vertical Slice

Read-only Tool/Knowledge work and one real Provider adapter are conditional follow-ups only after Validation demonstrates a need and preceding safety gates pass.

## Implementation gates

1. Authorization must protect the current application and Kernel boundaries.
2. Durable activities and external side effects must define attempts, leases, cancellation, idempotency, receipts, reconciliation, and correlation.
3. App packaging must reuse existing Agent and Workflow definitions.
4. Structured generation must begin with a deterministic fake Provider.
5. Validation must prove the package-defined vertical slice before broader platform work.

## Files changed

- Revised `architecture/FounderOS_v0.2_Blueprint.md`.
- Updated `.ai/BUILD_ROADMAP.md`.
- Updated `.ai/CURRENT_SPRINT.md`.
- Updated `.ai/DECISIONS.md`.
- Updated `.ai/PROJECT_CONTEXT.md`.
- Updated `README.md`.
- Updated `CHANGELOG.md`.
- Added `MILESTONE_12B_HANDOFF.md`.

## Remaining risks

- Milestone 12C must still define the exact principal and capability vocabulary.
- Milestone 12D may require compatible extensions to Event and Run contracts.
- App package historical resolution and compatibility require executable acceptance scenarios.
- The fake Provider must not force artificial AI work into Validation if deterministic behavior is sufficient.
- Local persistence remains single-Project and single-writer; it is not a cloud foundation.
- Prompt grounding, evaluator independence, budgets, secret handling, and data-retention policy remain unresolved before real Provider integration.

## Recommended next milestone

Proceed with **Milestone 12C — Authorization Policy Foundation**.

Milestone 12C must not create App registries, Provider adapters, Tools, Knowledge services, or Validation behavior. It should establish enforceable local identity context, Project ownership, capabilities, Approval/Transition authority, protected-read policy, denial diagnostics, and reserved policy points for future outbound execution.
