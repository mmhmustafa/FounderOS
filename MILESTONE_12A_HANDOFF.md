# FounderOS Milestone 12A Handoff

Milestone 12A — FounderOS v0.2 Architecture Review Board is complete.

## Review outcome

**Decision recommendation: Proceed with changes.**

The v0.2 Blueprint has a credible long-term direction, but it is not implementation-ready. It should be adopted as strategic intent only after its package semantics, runtime authorities, trust boundaries, distributed execution model, and implementation sequence are revised.

This is not a recommendation to discard the blueprint. It is a conditional approval intended to preserve the platform vision without committing FounderOS to speculative abstractions.

## Review document

The complete formal review is located at:

```text
docs/reviews/FounderOS_v0.2_Architecture_Review.md
```

It evaluates the blueprint from five perspectives:

- Enterprise Architect
- Distributed Systems Engineer
- AI Systems Architect
- Staff Software Engineer
- Startup CTO

## Strongest aspects of the blueprint

- The Kernel is correctly separated from prompts, model providers, domain logic, UI behavior, and external tools.
- Provider independence and controlled tool execution are sound long-term seams.
- Human Approval, structured Artifacts, Decisions, Evaluations, Events, and replay remain first-class.
- Domain Packs can preserve a domain-neutral core while allowing an Enterprise Networking wedge.
- CLI-first and local-first remain appropriate for the current product stage.

## Biggest architectural risks

### 1. Parallel App and Workflow models

The blueprint says Workflows become Apps while Apps contain Workflows. Implemented literally, this creates duplicate execution, state, approval, retry, and recovery authorities.

### 2. Authorization comes too late

Provider and Tool execution are unsafe before FounderOS has enforceable principals, project ownership, capabilities, policy decisions, secret scope, and denial diagnostics.

### 3. Cloud and multi-user execution are under-specified

The local lock and snapshot model cannot become a multi-worker cloud runtime without durable activities, leases, transactional outbox/inbox semantics, duplicate delivery handling, event evolution, and tenant isolation.

### 4. External side effects lack recovery semantics

The blueprint does not define how FounderOS recovers when a Tool succeeds externally but the local Event or state commit fails.

### 5. Global project state is coupled to every App

Lifecycle Apps such as Validation may change startup state. Utility Apps such as firewall review or incident review should produce Artifacts and Decisions without forcing global lifecycle transitions.

### 6. AI safety contracts are incomplete

Canonical provider requests, prompt rendering, tool-call isolation, grounding citations, evaluator independence, cost and autonomy budgets, typed failures, data retention, and prompt-injection defenses remain undefined.

### 7. Platform abstractions precede user value

The proposed sequence creates Agent, App, Provider, Tool, Knowledge, and Memory infrastructure before delivering the next useful founder outcome.

## Recommended architecture changes

1. Define an App as an installable first-party package containing existing Workflow and Agent definitions, prompts, schemas, rubrics, policies, and tests.
2. Keep Workflow as the only executable process definition and WorkflowRun as its durable execution record.
3. Extend existing Agent and Workflow contracts instead of creating parallel manifest systems.
4. Keep the Kernel as domain services behind explicit ports in a modular monolith.
5. Add an application command/query boundary between CLI/API interfaces and Kernel services.
6. Distinguish state-owning lifecycle Workflows from utility Workflows that cannot change global Project state.
7. Implement authorization before Provider or Tool execution.
8. Define durable activity, side-effect receipt, idempotency, cancellation, retry, and reconciliation contracts.
9. Start with structured generation and a deterministic fake provider; defer streaming, embeddings, and provider fallback.
10. Keep Knowledge project-scoped, sourced, access-controlled, and evidence-oriented initially.

## Recommended v0.2 scope

v0.2 should prove one package-defined, policy-controlled workflow without hardcoded vertical-slice orchestration while preserving all v0.1 safety boundaries.

Recommended included scope:

- existing five core objects and runtime records;
- modular monolith and local CLI;
- first-party App packaging over current definitions;
- backward-compatible Agent and Workflow extensions;
- authorization and capability checks;
- deterministic fake structured-generation provider;
- versioned prompt and response schemas;
- project-scoped evidence;
- one package-defined Validation workflow;
- existing approval, transition, audit, replay, and recovery guarantees.

## Recommended postponements

- App Marketplace and untrusted third-party packages
- Skills as a first-class executable abstraction
- six-level memory model
- organization, domain, and global memory
- knowledge graph and vector storage
- broad provider support and fallback routing
- streaming and embeddings
- broad Tool catalogue and external-write Tools
- Domain Pack installation framework
- REST API and Web UI implementation
- cloud/multi-user operation on local persistence
- enterprise RBAC, billing, and marketplace concerns

## Recommended next milestone

**Milestone 12B — Blueprint Revision and Architecture Decisions**

Before implementation, Milestone 12B should:

- define App versus Workflow semantics;
- replace the target dependency diagram;
- define lifecycle versus utility Workflows;
- specify authorization and policy decision points;
- specify durable activity and external-effect boundaries;
- define package compatibility and trust;
- reconcile v0.2 terminology with current contracts; and
- approve one narrow v0.2 acceptance scenario.

## Files changed

- Added `docs/reviews/FounderOS_v0.2_Architecture_Review.md`.
- Updated `CHANGELOG.md`.
- Added `MILESTONE_12A_HANDOFF.md` for this package.

No runtime, application, test, schema, CLI, Agent OS, Workflow OS, Provider, Tool, or Knowledge implementation was changed or added.
