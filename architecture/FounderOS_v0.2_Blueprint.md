# FounderOS v0.2 Blueprint

> **Version:** v0.2-alpha, revision 2  
> **Document type:** Strategic architecture blueprint  
> **Status:** Revised after Architecture Review Board; implementation gated  
> **Purpose:** Define an incremental evolution from the deterministic v0.1 runtime into a package-defined, policy-controlled AI operating platform without creating parallel execution models.

## 1. Executive Summary

FounderOS v0.1 established executable contracts, a deterministic Planner, guarded Project state transitions, runtime records, local persistence, recovery, audit diagnostics, Founder Setup, and Discovery v1.

FounderOS v0.2 will extend that foundation through a **modular monolith**. It will not create independent Agent OS, Workflow OS, Knowledge OS, or Tool Platform services. Those names may describe future capability areas, but v0.2 implements them only as modules and outbound ports governed by the existing runtime boundaries.

The core v0.2 model is:

```text
App       = versioned package of definitions and assets
Workflow  = executable process definition
Agent     = versioned role/capability performer used by a Workflow
Tool      = controlled external capability requested through policy
Provider  = AI/model backend behind a generation port
Kernel    = sole runtime domain-mutation authority
```

An App does not execute independently, update Project state, emit Events directly, or replace Workflow. An App packages one or more existing Workflow definitions together with their referenced definitions and assets.

The first v0.2 product proof should be one bundled, first-party Validation App. It must reuse the v0.1 contracts and safety boundaries. Broader platform features remain deferred until that vertical slice demonstrates a real need.

## 2. Architectural Goals

v0.2 should prove that FounderOS can:

- load a first-party package without hardcoding its workflow content in an application service;
- authorize every protected command before mutation or external execution;
- execute an existing Workflow definition through explicit coordination boundaries;
- use a deterministic fake structured-generation Provider;
- preserve Artifact, Evaluation, Approval, Decision, Transition, Event, replay, recovery, and audit semantics; and
- deliver a useful Validation outcome from `OPPORTUNITY_SELECTED`.

v0.2 is not a marketplace, distributed cloud runtime, general autonomous-agent framework, or broad integration platform.

## 3. Constitutional Principles

### 3.1 Preserve the five core objects

Agent, Artifact, Workflow, State, and Decision remain the product-level objects. App is a package and deployment concept, not a sixth core object. Provider, Tool, knowledge records, runs, approvals, evaluations, activities, effects, and Events are supporting runtime or integration concepts.

### 3.2 One executable process model

Workflow is the only executable process definition. WorkflowRun is the durable record of a Workflow execution. App packages may contain Workflows but may not define a competing step, retry, approval, transition, or recovery model.

### 3.3 One mutation authority

The FounderOS Kernel owns domain mutation through its existing services. The State Machine remains the sole authority for `Project.current_state`. Apps, Agents, Providers, Tools, prompts, interfaces, and the Master Orchestrator cannot mutate repositories or append authoritative Events directly.

### 3.4 Policy before execution

Authorization is evaluated before protected reads, mutations, Provider calls, Tool requests, approvals, and state transitions. Agent or App policy requirements request capabilities; they never grant capabilities.

### 3.5 Determinism before autonomy

Published definitions and assets are version-pinned. Model and external results are untrusted until structurally validated and evaluated. Human Approval remains mandatory for high-impact decisions and transitions.

### 3.6 Extract primitives from a vertical slice

Platform primitives must be justified by the bundled Validation App. v0.2 will not build speculative marketplace, provider, Tool, memory, or knowledge-graph abstractions.

## 4. Terminology and Authority

| Concept | Meaning | Owns | Must not do |
|---|---|---|---|
| App | Immutable, versioned package/index of definitions and assets | Package identity, compatibility declaration, asset references, fixtures | Execute steps, mutate Project state, grant policy, append Events |
| Workflow | Executable process definition | Steps, inputs/outputs, Agents, quality gates, failure policy, declared state effect | Write Project state directly or bypass approvals |
| WorkflowRun | Runtime execution record | Attempt, progress, referenced outputs, status | Become a second Project aggregate |
| Agent | Versioned specialist role/capability performer | Role, accepted/produced Artifact types, constraints, declared Tool needs | Select its own authority, approve its output, mutate Project state |
| Tool | Controlled external capability | Input/output contract, effect class, executor requirements | Run without authorization, secret scope, and execution receipt |
| Provider | AI/model backend adapter | Provider-specific transport behind canonical generation contracts | Leak provider details into App logic or become an authority |
| Kernel | Runtime domain services and contracts | Projects, transitions, runs, Artifacts, Decisions, Evaluations, Approvals, Events, persistence boundaries | Contain prompts, domain content, provider SDKs, Tool integrations, or UI logic |
| Master Orchestrator | Thin application facade | Command/query coordination and presentation of next actions | Become a specialist Agent, storage owner, or transition authority |

The labels “Agent OS,” “Workflow OS,” “Knowledge OS,” and “Tool Platform” describe possible long-term capability families only. They are not v0.2 processes, services, databases, or independent mutation authorities.

## 5. Modular-Monolith Dependency Model

```text
CLI / future API
        |
        v
Application commands and queries / Master Orchestrator facade
        |
        v
Planner + Workflow coordination
        |
        v
FounderOS Kernel domain services
  - Project State and State Machine
  - WorkflowRun and AgentRun lifecycles
  - Artifact and Decision lifecycles
  - Evaluation and Approval lifecycles
  - Event, audit, replay, and recovery contracts
        |
        v
Outbound ports
  - Persistence and Event Store
  - AI structured-generation Provider
  - Tool Executor
  - Knowledge Repository/Retriever
  - Secret and Configuration Provider

First-party App packages supply immutable definitions and assets to
application/registry readers. They never call storage or Kernel internals.
```

### Dependency rules

1. Interfaces depend on application commands and queries, never on repositories.
2. Application coordination may call the Planner and Kernel services.
3. The Planner remains read-only.
4. Workflow coordination requests mutations through the owning Kernel service.
5. Kernel domain code depends on outbound port contracts, not concrete adapters.
6. Provider, Tool, knowledge, secret, and persistence adapters depend inward on ports; domain services do not import their SDKs.
7. App packages contain data and assets. They do not contain trusted runtime code in v0.2.
8. The architecture is logically modular but deployed as one local process in v0.2.

## 6. FounderOS Kernel

The v0.1 runtime foundation is the FounderOS Kernel.

### Kernel responsibilities

- Project aggregate and optimistic revision checks
- guarded Project state transitions
- WorkflowRun and AgentRun lifecycle records
- Artifact and Decision lifecycle records
- Evaluation and Approval records
- ordered authoritative Events
- contract and reference validation
- idempotency and correlation
- persistence ports, replay, recovery, and audit diagnostics
- authorization enforcement at protected domain boundaries after Milestone 12C

### Kernel exclusions

- App content and domain rules
- prompt templates and prompt rendering content
- model/provider SDK calls
- external Tool execution
- UI or CLI formatting
- knowledge ranking implementations
- secrets and credentials
- direct third-party package code execution

The Kernel is a set of cohesive domain services, not one controller class and not a separate microservice requirement.

## 7. App Package Model

### 7.1 Definition

An App is an immutable, versioned package/container/bundle that indexes the definitions and assets needed to deliver one cohesive user capability. It is packaging, not execution.

An App package contains or references:

- package identity and Semantic Version;
- compatible Kernel contract version range;
- included Workflow definitions and exact versions;
- referenced Agent definitions and exact versions;
- Artifact content schemas;
- prompt templates and their input/output schemas;
- Evaluation rubrics;
- policy/capability requirements;
- tests and deterministic fixtures; and
- optional documentation and domain resources.

### 7.2 App package boundary

The package manifest indexes assets. It must not duplicate fields already owned by Workflow, including steps, entry/exit behavior, retry policy, quality gates, approvals, or transition requests.

Conceptual manifest:

```yaml
app_package:
  package_id: founderos.validation
  version: 0.2.0
  kernel_contract: ">=1.0.0 <2.0.0"
  workflow_refs:
    - kind: workflow
      id: wfl_...
      version: 1.0.0
  agent_refs:
    - kind: agent
      id: agt_...
      version: 1.0.0
  artifact_schema_paths:
    - schemas/validation-report.schema.json
  prompt_template_paths:
    - prompts/interview-synthesis.v1.md
  evaluation_rubric_paths:
    - evaluations/validation-quality.v1.yaml
  required_capabilities:
    - project.read
    - artifact.create
  fixture_paths:
    - fixtures/validation-deterministic.json
```

This example is architectural, not an implemented contract.

### 7.3 Initial package layout

```text
apps/
  validation/
    app.yaml
    README.md
    workflows/
    agents/
    schemas/
    prompts/
    evaluations/
    fixtures/
    tests/
```

v0.2 supports bundled, first-party packages only. There is no installation command, remote registry, marketplace, arbitrary code hook, or third-party trust model.

### 7.4 Compatibility and history

- A package declares the Kernel contract range it supports.
- Contained and referenced definitions use existing immutable IDs and versions.
- Runs pin exact Workflow, Agent, prompt, rubric, and package versions where applicable.
- Package configuration is an external overlay and cannot mutate published assets.
- Historical definitions required by existing records remain resolvable.
- Upgrade, rollback, signing, dependency resolution, and uninstall semantics beyond bundled packages are deferred.

## 8. Workflow Model

Workflow remains the executable process definition. Existing Workflow and WorkflowRun contracts evolve only through backward-compatible, use-case-driven changes.

### 8.1 Lifecycle Workflows

A lifecycle Workflow participates in the startup lifecycle. It may request a guarded Project state transition after its declared evidence, Evaluation, Decision, and Approval requirements are satisfied.

Rules:

- its entry and requested exit states must be declared and allowed;
- only the State Machine may apply the transition;
- the Workflow cannot update `Project.current_state` directly;
- a recommendation, successful AgentRun, or completed WorkflowRun does not imply transition approval.

Examples include Founder Setup, Discovery, and Validation.

### 8.2 Utility Workflows

A utility Workflow operates within a Project context but has no Project lifecycle state effect. It may produce Artifacts, Evaluations, Decisions, run records, and Events through Kernel services.

Rules:

- it must declare that it has no Project lifecycle state effect;
- it may restrict the Project states in which it can start;
- it cannot request or imply a change to `Project.current_state`;
- completion changes only its WorkflowRun and related records.

Examples may later include firewall review, documentation review, or incident analysis.

The exact compatible extension to the existing Workflow schema is a Milestone 12E design decision; this blueprint does not add it.

## 9. Agent Model

An Agent is a versioned role/capability performer selected by a Workflow. Existing Agent definitions remain authoritative.

Agents may declare:

- role and responsibilities;
- accepted and produced Artifact types;
- constraints and quality requirements;
- requested Tool capabilities;
- referenced prompt assets; and
- handoff and failure guidance.

Agents may not:

- grant themselves permissions;
- select a Provider in conflict with runtime policy;
- execute Tools directly;
- approve their own outputs;
- append authoritative Events directly; or
- mutate Project state.

“Skills” are not a first-class executable abstraction in v0.2. Capabilities may be descriptive routing metadata until a real workflow demonstrates a separate enforceable concept.

## 10. AI Structured-Generation Provider Port

Provider means an AI/model backend adapter behind a canonical outbound port. App and Workflow logic must not depend on OpenAI, Anthropic, Gemini, or another provider SDK.

The first Provider milestone supports only structured generation and a deterministic fake. Its future contract must cover:

- versioned prompt/template reference;
- canonical structured input;
- required output JSON Schema;
- model capability requirements;
- timeout and cancellation;
- typed refusal, rate-limit, transient, invalid-output, and terminal failures;
- usage, cost, and latency metadata;
- request fingerprint and correlation;
- data retention/redaction policy; and
- deterministic fixtures for tests.

Streaming, embeddings, provider fallback, autonomous model selection, and real provider integration are not part of the initial v0.2 implementation gates.

Provider output is untrusted. It must not become an approved Artifact or satisfy a transition without schema validation, Evaluation, and required human Approval.

## 11. Tool Executor Port

A Tool is a controlled external capability. v0.2 defines no broad Tool catalogue and implements no external-write Tool before authorization and durable side-effect contracts exist.

Future Tool execution must require:

- exact Tool definition/version;
- input and output schemas;
- authenticated principal and Project scope;
- policy decision and any argument-specific human Approval;
- least-privilege secret reference;
- risk/effect classification;
- idempotency key, deadline, and attempt limit;
- durable request/result or effect receipt;
- sanitized input/output digests and audit correlation; and
- reconciliation or compensation behavior for ambiguous outcomes.

An Agent requests a Tool capability through Workflow coordination. It never invokes the adapter directly.

## 12. Knowledge Boundary

Knowledge is supporting sourced material, not a sixth core object and not a separate service in v0.2.

If the Validation vertical slice proves a need, the first Knowledge capability is Project-scoped and provenance-first. It must retain source, immutable content digest, acquisition and verification times, access scope, freshness, and citations.

Retrieved knowledge cannot satisfy a state guard by itself. An Artifact or Evaluation must cite the exact source/digest before it becomes transition evidence.

Embeddings, organization/domain/global memory, knowledge graphs, cross-Project retrieval, and vector databases are deferred. Derived search indexes are disposable read models.

## 13. Authorization and Policy

Authorization is the first implementation gate after this blueprint revision.

Milestone 12C must define:

- local authenticated principal context without external authentication;
- Project ownership/membership rules;
- capability-based authorization for commands and protected reads;
- Approval and Transition authority;
- policy checks at Artifact, Evaluation, Decision, run, Provider, Tool, and knowledge boundaries;
- deny-by-default behavior;
- redacted denial diagnostics; and
- auditable policy decision references where required.

The actor recorded for audit is not by itself proof of identity or authority. App and Agent manifests may declare required capabilities, but only runtime policy grants them.

No Provider or Tool execution may be added before this gate is complete.

## 14. Durable Activity and Side-Effect Boundary

Provider and Tool work occurs outside Project mutation transactions. Before either becomes executable, Milestone 12D must define supporting contracts for:

- activity identity and exact definition references;
- attempts, leases, and heartbeat expiry;
- timeout, cancellation, and retry classification;
- command and activity idempotency;
- input/output or effect receipts;
- crash recovery and operator reconciliation;
- ambiguous external success after local commit failure;
- compensation policy for non-idempotent effects; and
- correlation from command through activity, output, Evaluation, Approval, Decision, and Transition.

These are supporting runtime records and do not expand the five product-level core objects. Database-specific outbox/inbox implementation is deferred until durable/cloud persistence is selected.

## 15. Evaluation, Approval, and Human Control

Every important generated output remains untrusted until evaluated.

Evaluation types remain distinct:

- structural/schema validation;
- deterministic consistency/risk checks;
- source-grounding verification;
- optional model-based critique;
- security review; and
- human review.

Rubrics and evaluators are version-pinned. A model-based score is not equivalent to independent evidence or human Approval. High-impact decisions, external side effects, and Project lifecycle transitions require explicit policy and Approval evidence.

## 16. Security and Data Rules

- Secrets are obtained through a Secret/Configuration Provider port and are never stored in package assets, Events, prompts, Artifacts, or diagnostics.
- Sensitive inputs and outputs are redacted by default in audit views.
- App packages are first-party data/assets only; arbitrary package code execution is prohibited.
- Provider and Tool adapters receive only the least data and capability required.
- Project-scoped data cannot cross Project boundaries without a future explicit sharing policy.
- Prompt templates distinguish trusted instructions from untrusted user, retrieved, and Tool-provided content.
- Cost, token, time, attempt, and external-effect budgets fail closed when exhausted.

Cloud encryption, tenant isolation, enterprise RBAC, retention, legal hold, and data residency require later architecture before cloud/multi-user operation.

## 17. v0.2 Scope

### Included

- existing modular Python runtime and local CLI;
- existing five core objects and supporting runtime records;
- architecture and governance decisions in this blueprint;
- authorization policy foundation;
- durable activity and side-effect contracts;
- minimal bundled first-party App package contract;
- backward-compatible Agent and Workflow contract extensions only when required;
- deterministic fake structured-generation Provider;
- package-defined Validation vertical slice;
- existing state, evidence, Approval, audit, replay, and recovery guarantees.

### Non-goals

v0.2 does not include:

- App Marketplace;
- third-party App installation or arbitrary package code;
- Web UI or Desktop UI;
- cloud or multi-user runtime;
- real LLM Provider integration before the fake-provider gate;
- broad Tool catalogue or external-write Tools;
- Knowledge OS service or knowledge graph;
- vector database or embeddings;
- global, organization, domain, or cross-Project memory;
- multiple Provider routing/fallback;
- REST API implementation;
- microservices;
- billing, enterprise RBAC, or cloud sync.

These may remain long-term directions but are not v0.2 acceptance criteria.

## 18. Implementation Gates and Revised Milestones

No Agent OS runtime, App registry runtime, Provider integration, Tool implementation, Knowledge runtime, or Validation implementation may begin before its preceding gate is complete.

### Milestone 12A — Architecture Review Board — complete

- Review the draft blueprint against architecture, runtime contracts, implementation, and tests.
- Record the decision to proceed with changes.

### Milestone 12B — Blueprint Revision and Architecture Decisions — complete

- Define App as packaging and Workflow as execution.
- Establish the modular-monolith dependency model.
- Define lifecycle and utility Workflow authority.
- Narrow v0.2 scope and non-goals.
- Establish implementation gates.

### Milestone 12C — Authorization Policy Foundation — contract specification complete

- Define Actor, Action, Resource, Effect, Condition, PolicyRule, Policy, and Decision concepts.
- Define placeholder AuthorizationRequest, AuthorizationDecision, PolicyRule, AuthorizationPolicy, PolicyEngine, and resolver contracts.
- Specify deterministic default-deny and deny-overrides behavior.
- Reserve authorization checks before every owning Kernel mutation boundary.
- Keep authentication, users, RBAC, persistence, and runtime wiring out of scope.

Executable enforcement remains required before Provider or Tool execution; Milestone 12C intentionally changes no current runtime behavior.

### Milestone 12D — Durable Activity and Side-Effect Contracts — next

- Specify activities, attempts, leases, deadlines, cancellation, idempotency, receipts, reconciliation, and correlation.
- Do not integrate a Provider or Tool.

### Milestone 12E — Minimal First-Party App Package Contract

- Define package identity, Kernel compatibility, asset index, configuration overlay, historical resolution, and bundled trust.
- Reuse existing Agent and Workflow contracts and registries.
- Add only contract extensions required by the Validation acceptance scenario.

### Milestone 12F — Fake Structured-Generation Provider

- Define canonical request/result contracts, prompt rendering, output validation, budgets, typed failures, and a deterministic fake.
- Do not add a real LLM Provider.

### Milestone 12G — Validation App Vertical Slice

- Deliver package-defined Validation from `OPPORTUNITY_SELECTED`.
- Exercise the package, Workflow, Agent, fake Provider, Artifact, Evaluation, Approval, Decision, Transition, Event, replay, and audit boundaries.
- Keep Web, marketplace, broad Tools, and real Providers out of scope.

### Milestone 12H — Conditional Read-Only Tool or Knowledge Capability

- Proceed only if Validation demonstrates a concrete requirement.
- Add exactly one read-only capability with policy, provenance, deterministic fixture, and receipt semantics.

### Milestone 12I — Conditional Real Provider Adapter

- Proceed only after the fake-provider vertical slice passes and an explicit opt-in security/cost review is approved.

## 19. v0.2 Architecture Acceptance Criteria

Before v0.2 is considered complete:

1. No App duplicates Workflow execution semantics.
2. Existing v0.1 Projects, definitions, Events, and stores remain compatible or have an explicit migration.
3. Every protected operation is authorized at its owning boundary.
4. Only the State Machine changes `Project.current_state`.
5. Utility Workflow completion cannot change `Project.current_state`.
6. External activity contracts are idempotent, bounded, correlated, and recoverable before external execution is enabled.
7. The fake Provider produces deterministic schema-valid fixtures and records usage/budget metadata.
8. Generated output remains untrusted until evaluated and approved where policy requires.
9. The Validation App is a bundled package using existing Kernel services rather than a hardcoded alternate runtime.
10. Audit and replay can explain the command, package/definition versions, runs, output, Evaluation, Approval, Decision, and Transition.

## 20. Architecture Decisions

### AD-v0.2-01 — App is packaging, not execution

An App is a versioned first-party package/index of definitions and assets. It is not a sixth core object and has no independent execution or mutation authority.

### AD-v0.2-02 — Workflow remains executable

Workflow is the sole executable process definition. WorkflowRun remains its runtime execution record. Existing contracts evolve rather than fork.

### AD-v0.2-03 — Kernel is the sole mutation authority

All domain writes and authoritative Events pass through the owning Kernel service. Only the State Machine changes Project lifecycle state.

### AD-v0.2-04 — Authorization precedes Providers and Tools

No AI Provider or Tool execution is implemented until principal, capability, Project-scope, Approval, and policy enforcement exist.

### AD-v0.2-05 — v0.2 is a modular monolith

Agent, Workflow, knowledge, Provider, and Tool capabilities are modules or outbound ports, not independent services. Deployment separation requires future evidence.

### AD-v0.2-06 — Validation drives platform extraction

The first package-defined Validation vertical slice determines the minimum App, Agent, Workflow, prompt, Provider, and evidence extensions. Speculative marketplace-scale abstractions are deferred.

## 21. Remaining Risks

- The authorization capability vocabulary is specified but not yet enforced by runtime services.
- Durable Activity/Effect records may expose needed changes to Event and run contracts.
- App package compatibility and historical resolution need executable acceptance scenarios.
- Validation may not require a Provider initially; the fake Provider must not force artificial AI work into the workflow.
- Local persistence remains single-Project and single-writer; it is not a cloud foundation.
- Prompt grounding, model evaluation independence, cost calibration, and secret handling remain design work before real Provider integration.

## 22. Immediate Next Step

Proceed with **Milestone 12D: Durable Activity and Side-Effect Contracts**.

Do not create App registries, Agent OS runtimes, Provider adapters, Tools, Knowledge services, or Validation behavior during 12D. Authorization enforcement remains a required implementation gate before any Provider or Tool execution.
