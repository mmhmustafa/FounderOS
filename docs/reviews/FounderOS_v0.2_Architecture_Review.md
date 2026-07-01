# FounderOS v0.2 Architecture Review

> **Review type:** Formal architecture review board  
> **Blueprint reviewed:** `architecture/FounderOS_v0.2_Blueprint.md` (`v0.2-alpha`, draft)  
> **Baseline reviewed:** FounderOS v0.1 contracts, runtime specifications, Python runtime, CLI, and tests  
> **Decision recommendation:** **Proceed with changes**  
> **Implementation gate:** Do not begin the proposed Agent OS, Workflow OS, Provider Layer, Tool Platform, or Knowledge OS milestones until the blueprint changes identified as gates in this review are resolved.

## Executive Summary

The v0.2 blueprint points FounderOS in a credible long-term direction: domain-neutral runtime primitives, provider independence, controlled tools, structured knowledge, explicit approvals, and installable domain capabilities. Those principles fit the product vision and generally reinforce the strongest parts of v0.1.

The blueprint is not yet an implementable architecture. It mixes product vocabulary, packaging, runtime execution, and infrastructure into overlapping “OS” layers without defining authority boundaries between them. The most consequential ambiguity is the statement that workflows become Apps while an App also contains workflows. Implemented literally, this would create a second workflow model, duplicate existing Agent and Workflow contracts, and weaken the kernel's single mutation and execution authorities.

The proposed milestone sequence is also platform-first in the risky sense: it creates Agent, App, Provider, Tool, Knowledge, and Memory abstractions before proving one user-facing v0.2 outcome. That is likely to produce manifests and registries shaped by imagined marketplace needs rather than actual execution requirements. FounderOS already has executable Agent and Workflow definitions; creating parallel “manifest” systems before identifying their missing capabilities would be architectural churn, not progress.

The recommended direction is evolutionary:

1. Keep the five core objects and the existing runtime kernel.
2. Define an App as a versioned, installable package of existing definitions and assets, not a new execution primitive or sixth core object.
3. Keep Workflow as the only executable process definition and WorkflowRun as its durable execution record.
4. Separate the project lifecycle state machine from app/workflow run state so utility Apps do not force global startup-state transitions.
5. Add authorization and policy before provider or tool execution.
6. Specify durable command, activity, side-effect, and event semantics before cloud or multi-user claims.
7. Build one narrow v0.2 vertical slice—recommended: Validation—using only the minimum manifest, prompt, provider, and evidence capabilities it actually needs.

The review board therefore recommends **Proceed with changes**, with the architecture amendments in this document treated as implementation gates.

## Overall Verdict

**Decision: Proceed with changes.**

The blueprint should not proceed as-is, but it does not require a ground-up redesign. Its strategic principles are sound; its execution model, terminology, trust boundaries, and milestone order need revision.

| Perspective | Verdict | Primary finding |
|---|---|---|
| Enterprise Architect | Conditional approval | Coherent vision, but App/Workflow/Domain Pack boundaries and platform authorities overlap. |
| Distributed Systems Engineer | Not implementation-ready | Cloud concurrency, durable execution, event evolution, side effects, and tenancy are under-specified. |
| AI Systems Architect | Conditional approval | Provider independence is right, but canonical AI requests, grounding, prompt safety, budgets, and evaluation independence are missing. |
| Staff Software Engineer | Conditional approval | Existing contracts should be extended, not duplicated; proposed layers and registries are premature without a vertical slice. |
| Startup CTO | Narrow scope only | The full platform plan is over-engineered for current traction; build one useful workflow outcome first. |

### Enterprise Architect assessment

The architecture has coherent product concepts but not yet a coherent dependency structure. The Kernel is a sound center, while the named OS layers, App Platform, Domain Packs, and Master Orchestrator overlap in definition ownership and orchestration responsibility. It can scale conceptually to many domains only if package concerns are separated from runtime authority. Missing cross-cutting layers include application commands/queries, policy enforcement, configuration/secrets, package compatibility, and operational telemetry.

### Distributed Systems Engineer assessment

The v0.1 single-process consistency model is explicit and honest, but the blueprint jumps to cloud and multi-user outcomes without a distributed execution model. Local locks and snapshot persistence do not translate to multiple workers. The design needs durable activities, leases, transactional outbox/inbox, duplicate-delivery semantics, external-effect receipts, event schema evolution, and tenant partitioning before cloud execution. The Kernel is not too small; its domain responsibility is appropriate. It becomes too large only if provider adapters, tool execution, scheduling, package loading, policy evaluation, and projections are implemented inside one runtime class rather than behind ports.

### AI Systems Architect assessment

Separating Agents, Providers, Tools, prompts, memory, and Evaluations is directionally correct, but their enforceable boundaries are incomplete. Agent manifests currently mix role definition, routing, model preference, permission request, memory policy, and evaluation policy. Provider requests lack capability negotiation, budgets, error semantics, safety/refusal outcomes, and canonical structured content. Prompt injection, retrieval trust, grounding citations, evaluator independence, latency, spend, and bounded autonomy need explicit contracts before nondeterministic execution.

### Staff Software Engineer assessment

The proposed package tree is maintainable only if Apps are cohesive resource packages consumed through existing registries. Parallel Agent/App schemas and registries would be a long-term maintenance trap. Premature abstractions include Skills, marketplace installation, broad provider support, knowledge graph, and six memory scopes. Missing abstractions include package compatibility, activity/effect records, policy decisions, secret ports, and lifecycle-versus-utility workflow classification. Implementation should proceed through backward-compatible contract extensions driven by one vertical slice.

### Startup CTO assessment

The architecture supports the eventual platform vision but is too broad for the product's current proof level. FounderOS has demonstrated deterministic setup and Discovery, not demand for a marketplace or five OS subsystems. Building nine infrastructure milestones before another founder outcome delays learning and creates expensive speculative contracts. The fastest useful v0.2 is authorization plus one package-defined Validation workflow, initially deterministic or fake-provider-backed, with measured founder value before broader platform investment.

## What Is Strong

### Enterprise architecture strengths

- The Kernel boundary correctly excludes prompts, model calls, domain rules, UI behavior, and external tool execution.
- Provider independence and controlled tool execution are appropriate long-term seams.
- Human Approval, Artifact, Decision, Evaluation, and Event concepts align with the existing constitutional model rather than replacing it.
- Domain Packs recognize that enterprise networking expertise should be content and capability layered on a domain-neutral core.
- The blueprint explicitly resists treating Discovery as the platform, which protects later product breadth.

### Distributed systems strengths

- External AI and tool work is conceptually outside core state mutation.
- Auditability, recovery, approvals, and deterministic replay remain first-class goals.
- Versioned definitions and mockable providers are good prerequisites for repeatability.
- The existing v0.1 kernel already has useful foundations: optimistic revisions, idempotency keys, immutable outcomes, ordered per-project Events, explicit recovery, and exact definition references.

### AI systems strengths

- Agent, Workflow, Tool, Provider, Artifact, State, and Decision responsibilities are described separately.
- Agent output is expected to be structured and evaluated rather than silently trusted.
- Prompt packs are treated as versioned assets.
- Memory is explicitly distinguished from raw chat history.
- Model selection is intended to be policy-driven rather than hardcoded inside Apps.
- Every AI workflow is expected to work with a mock provider.

### Software engineering strengths

- The blueprint favors manifests and versioned assets over embedded prompt strings.
- App-local schemas and tests are a good packaging instinct.
- The proposed Kernel responsibilities mostly match existing service boundaries.
- The “what not to build yet” section correctly postpones Web UI, marketplace, cloud sync, billing, and real model integration.

### Product and startup strengths

- CLI-first is appropriate for the current technical-founder audience.
- Enterprise Networking is a plausible wedge with differentiated founder expertise.
- A local-first option can reduce trust friction for sensitive founder and network data.
- The emphasis on evidence, human control, and auditability differentiates FounderOS from an unstructured agent chat interface.

## What Is Weak

### Apps and Workflows are conflated

“Workflows become Apps” conflicts with the proposed App folder containing `workflows/`. An App is better understood as a distribution and configuration unit that contains one or more Workflow definitions, Agent definitions, schemas, prompts, policies, and optional domain resources. Workflow must remain the executable process primitive. App installation and App execution are separate concerns.

Without this correction, FounderOS will have two competing locations for entry state, exit state, steps, approvals, recovery, required artifacts, tools, and agents.

### The “OS” decomposition is branding, not a dependency model

Agent OS, Workflow OS, and Knowledge OS are drawn as peer layers over the Runtime Foundation, but their direction of dependency, ownership of records, and allowed calls are undefined. The diagram also places CLI/API/Web UI below infrastructure, even though interfaces should call application/use-case boundaries above the kernel. Provider and Tool adapters should be outbound ports, not peers through which the entire runtime is layered.

### Existing contracts are ignored by the proposed sequence

FounderOS already has machine-valid Agent and Workflow definitions plus AgentRun and WorkflowRun records. “Agent Manifest Contracts” and “App Manifest Contracts” are described as new systems rather than compatible evolution of existing contracts. This invites duplicate registries, migrations, identifiers, and status vocabularies.

### Platform-before-features is applied too literally

The principle should mean “extract reusable primitives from real features,” not “build every anticipated platform subsystem before the next useful workflow.” The proposed roadmap creates up to nine abstraction milestones before Validation provides new user value.

### Security is a requirements list, not an architecture

Least privilege, tenant isolation, encryption, RBAC, and redaction are named but not tied to identities, trust zones, data classifications, policy decision points, secret handling, or enforcement boundaries. Provider and Tool integration cannot safely begin with these details deferred.

### The global startup state machine does not fit general Apps

Discovery and Validation naturally advance startup lifecycle state. Firewall review, NOC incident review, documentation, and configuration compliance do not. Forcing every App into `entry_state` and `exit_state` either bloats the global state catalogue or lets Apps mutate state that should be independent.

FounderOS needs an explicit distinction between:

- **state-owning workflows**, which may request guarded Project lifecycle transitions; and
- **utility workflows**, which run within a Project context and produce Artifacts/Decisions without changing the global lifecycle state.

## Missing Concepts

### Identity, tenancy, and authorization context

Before cloud or external effects, every command needs an authenticated principal, tenant/organization, project membership, roles/capabilities, and a policy decision. The existing `actor` shape is audit metadata, not proof of identity. Authorization was already the next v0.1 hardening milestone and should remain ahead of provider and tool execution.

### Application/use-case boundary

The target diagram omits the application layer that accepts commands, authorizes them, coordinates kernel services, and returns results. The Master Orchestrator is a facade, not a universal transaction script. CLI, API, and Web should be inbound adapters to application commands and queries.

### Durable execution and activity semantics

WorkflowRun and AgentRun lifecycles exist, but v0.2 needs semantics for:

- step checkpoints and resumability;
- work claims, leases, and heartbeat expiry;
- cancellation and deadlines;
- retry classification and backoff;
- duplicate delivery;
- idempotent activity keys;
- waiting for input or approval;
- process crash between external effect and Event commit;
- compensation or operator reconciliation.

These may be supporting runtime records; they do not need to become new product-level core objects.

### External side-effect receipts

Tool invocation needs a durable request/result/effect record containing idempotency key, exact tool version, authorization decision, sanitized input digest, output digest/reference, timing, side-effect class, provider request ID, and reconciliation status. An Event alone is insufficient to recover from “external write succeeded, local commit failed.”

### Schema and package compatibility

The App concept needs compatibility rules for:

- App version versus contained definition versions;
- required Kernel/API contract versions;
- dependency resolution and conflicts;
- migrations and uninstall behavior;
- immutable historical resolution after uninstall;
- trust/signature provenance;
- tenant-specific configuration without mutating published packages.

### Configuration and secret management

Provider keys and Tool credentials must come from a secret broker/configuration port. They must never be stored in Agent manifests, App packages, Events, Artifact content, or diagnostic metadata. Rotation, redaction, scope, and audit rules are missing.

### Data governance

Knowledge and Memory require retention, deletion, legal hold, export, sensitivity classification, residency, consent, and derived-data invalidation. “Editable/deletable” conflicts with immutable audit requirements unless the architecture distinguishes source deletion, tombstones, audit metadata, and derived indexes.

### Trust and provenance model

Knowledge needs more than a source string and confidence score. It needs immutable source snapshots or digests, citation spans, acquisition method, trust classification, license/usage constraints, freshness policy, contradiction/supersession links, and access scope. Confidence must identify who or what assigned it and by which evaluation version.

### Operational observability

Audit records explain business history; they are not sufficient operational telemetry. v0.2 needs separate traces, metrics, logs, cost/token usage, queue time, provider latency, retry counts, failure taxonomy, and correlation across command, workflow, activity, provider call, tool call, Artifact, and Transition.

## Over-Engineered Areas

### Five branded “OS” subsystems

Agent OS, Workflow OS, and Knowledge OS imply independently complex platforms before their responsibilities justify separate packages or deployable components. Start with cohesive modules behind ports in a modular monolith. Split deployment only when scaling, ownership, or reliability data demands it.

### App Marketplace and SDK direction

Marketplace installation, third-party packages, signatures, dependency resolution, billing, discovery, and sandboxing are a product of their own. Design packages so a marketplace remains possible, but do not optimize v0.2 contracts for untrusted third-party distribution.

### Capabilities versus Skills

The distinction is not operationally defined. If both are tags, one taxonomy is enough. If Skills are executable assets, they need inputs, outputs, permissions, versions, tests, and invocation semantics—effectively overlapping Workflow steps or Tools. Defer Skills as a first-class concept until a real workflow demonstrates the need.

### Six memory levels and a future knowledge graph

Project-scoped sourced knowledge is enough for v0.2. Organization, domain, founder, and global memory introduce cross-tenant leakage, consent, precedence, freshness, and deletion problems. A knowledge graph is a derived index, not an initial source of truth.

### Broad provider surface

Supporting completion, streaming, and embeddings across seven provider families before one production use case is unnecessary. Define a minimal canonical structured-generation port and one deterministic fake. Add streaming and embeddings only when a user-facing path requires them.

### Broad Tool catalogue

Listing dozens of integrations creates the appearance of architecture without choosing a safe first effect boundary. Start with no external-write tool. Add one read-only capability required by the selected v0.2 vertical slice.

## Under-Specified Areas

### Agent execution

The Agent object combines identity, routing tags, prompt selection, provider preference, memory scope, authorization policy, evaluation policy, and handoff policy. It is unclear which values are declarative metadata, enforceable policy, or runtime configuration. Provider preference in an Agent can conflict with tenant policy, cost budgets, data residency, or App requirements.

### Prompt contracts

Prompt packs need variable schemas, rendering rules, escaping, content ownership, version pinning, provider-neutral message representation, prompt-injection boundaries, response schema linkage, test fixtures, and redaction requirements. A filename convention is not an execution contract.

### Provider contract

`complete`, `stream`, and `embed` omit:

- canonical message/content-part representation;
- structured-output schema and validation mode;
- tool-call requests and results;
- capability discovery;
- model/provider version identity;
- usage, cost, and latency accounting;
- timeout, cancellation, retry, rate-limit, and error taxonomy;
- safety/refusal outcomes;
- data-retention and residency policy;
- raw-response retention/redaction;
- deterministic request fingerprints.

### Tool contract

The Tool object does not define executor isolation, credential scope, network policy, input/output size, streaming, cancellation, idempotency, side-effect confirmation, result retention, sandboxing, or compensation. `approval_required` is too coarse; approval should be a policy decision based on actor, project, specific arguments, target resource, environment, and effect class.

### Evaluation independence

The blueprint says every important AI output is evaluated but does not define who evaluates, whether the evaluator may use the same model/prompt, how rubrics are versioned, what evidence supports a hallucination or grounding check, or how false confidence is handled. Schema validation, deterministic checks, model critique, source verification, and human review must remain distinct outcomes.

### Cost and autonomy budgets

`max_cost_usd` on a model policy is not sufficient. A WorkflowRun needs total budgets for cost, tokens, time, attempts, tool effects, and human-interaction limits. Exhaustion behavior must be deterministic and auditable. Autonomy should be capability-based and deny-by-default, not a general Agent attribute.

### Event ownership and evolution

An App manifest listing `events_emitted` could imply that package code writes Events directly. Only authoritative services should append Events. Event types need ownership, payload schema versions, compatibility rules, retention, and projection rebuild semantics.

### App installation and trust

The blueprint defines App execution but not installation state, publication, enablement, configuration, trust, verification, upgrade, rollback, removal, or historical resolution. These are essential even for first-party packages if App is a real packaging boundary.

## Major Risks

| Risk | Severity | Why it matters | Required mitigation |
|---|---|---|---|
| Parallel App and Workflow execution models | Critical | Duplicates authority and produces incompatible state, retry, and approval semantics. | Define App as package; Workflow remains executable authority. |
| Provider/Tool execution before authorization | Critical | External data and side effects would be reachable with audit actors but no enforceable identity policy. | Complete authorization policy and secret boundaries first. |
| Local persistence treated as cloud foundation | Critical | File locks, whole-snapshot hydration, and per-file replacement cannot support multi-user workers. | Specify durable store, transaction, outbox/inbox, lease, and migration ports before cloud execution. |
| External effect ambiguity | Critical | A tool may succeed while local commit fails, causing unsafe duplicate actions. | Durable effect request/receipt, idempotency, reconciliation, and compensation policy. |
| Global state-machine coupling | High | Utility Apps either distort startup state or bypass the State Machine. | Separate Project lifecycle transitions from utility WorkflowRun lifecycle. |
| Manifest proliferation | High | Agent/App/Tool/Knowledge manifests can become duplicated schemas with no proven execution consumer. | Extend existing contracts only through a vertical slice. |
| Memory leakage and stale grounding | High | Cross-project/global memory can expose sensitive data or silently bias current intent. | Project scope only, provenance, ACLs, freshness, explicit retrieval citations. |
| Prompt/tool injection | High | Retrieved or tool-returned text can manipulate Agent behavior and request unsafe effects. | Trust labels, content isolation, policy checks, constrained tool calls, and human gates. |
| Evaluation theater | High | Model-generated scores can appear as quality assurance without independent evidence. | Separate deterministic, grounded, model, and human evaluations with versioned rubrics. |
| Provider abstraction at wrong level | Medium | Lowest-common-denominator interfaces leak provider quirks into Apps or hide needed capability differences. | Canonical request/result plus explicit capability negotiation and adapter-specific metadata. |
| Marketplace-driven design | Medium | Untrusted package concerns can delay a useful first-party product. | First-party signed packages only; marketplace deferred. |
| Kernel growth | Medium | Artifact, Approval, Evaluation, policy, execution, audit, and persistence can become a monolith. | Keep kernel as domain services and ports, not one class/process; enforce dependency directions. |

## Suggested Architecture Changes

### 1. Replace the target diagram with explicit ports and authorities

Use a modular-monolith model for v0.2:

```text
CLI / future API
        |
Application commands and queries / Master Orchestrator facade
        |
Planner + Workflow coordination
        |
FounderOS Kernel domain services
  - Project State / State Machine
  - Runs / Artifacts / Decisions / Evaluations / Approvals
  - Event and audit contracts
        |
Outbound ports
  - Persistence/Event Store
  - AI Generation Provider
  - Tool Executor
  - Knowledge Repository/Retriever
  - Secret/Configuration Provider

App packages supply immutable definitions and assets to registries;
they do not bypass application or kernel services.
```

This is a logical dependency model, not a requirement for microservices.

### 2. Define App as packaging, not execution

An App package should contain:

- package identity and version;
- compatible Kernel contract range;
- one or more existing Workflow definitions;
- referenced Agent definitions;
- Artifact content schemas;
- prompt templates and response schemas;
- evaluation rubrics;
- policy requirements;
- optional first-party Tool declarations;
- tests and fixtures.

The manifest indexes these assets. It must not duplicate Workflow steps, entry/exit state, quality gates, or approvals.

### 3. Evolve current Agent and Workflow contracts

Perform a field-by-field compatibility review against `agent.schema.json` and `workflow.schema.json`. Add only fields required by the first v0.2 vertical slice. Preserve IDs, version semantics, historical references, registries, and Run records. Do not create Agent Manifest and App Workflow models that shadow existing definitions.

### 4. Split lifecycle state ownership from utility execution

Add a Workflow classification or policy such as `state_effect: lifecycle | none`. Only lifecycle Workflows declare and request Project state transitions. Utility Workflows can run in allowed Project states and produce records without changing `Project.current_state`.

### 5. Put policy ahead of execution

Define authorization as a Kernel/application prerequisite:

- authenticated principal and tenant context;
- capability-based command authorization;
- Project membership/ownership;
- Agent, Workflow, Provider, Tool, Knowledge, and Artifact access decisions;
- argument-aware Tool approval;
- redacted denial diagnostics;
- policy decision references in audit records.

Agent policy declarations request capabilities; they do not grant them.

### 6. Introduce a minimal durable activity boundary

Before cloud workers, define an Activity/Effect execution contract with leases, attempts, deadlines, idempotency, cancellation, receipts, and reconciliation. Keep AI/Tool calls outside Project mutation transactions. Use transactional outbox/inbox semantics when a durable database adapter is introduced.

### 7. Narrow AI v0.2 to structured generation

Start with a provider-neutral `GenerationRequest` and `GenerationResult`, a deterministic fake provider, exact prompt/template version, response JSON Schema, capability requirements, usage/cost fields, timeout/cancellation, and typed errors. Do not add streaming or embeddings until a real interface or retrieval path needs them.

### 8. Make Knowledge project-scoped and evidence-oriented

Implement sourced Project Knowledge only when a selected workflow requires retrieval. Persist provenance and immutable content references; treat embeddings and search indexes as disposable projections. Retrieved knowledge never satisfies a guard until cited by an Artifact or Evaluation, preserving the existing contract.

### 9. Separate audit from telemetry

Keep Events as authoritative business audit. Add operational traces/metrics through ports so instrumentation cannot mutate domain records. Correlation should span command, WorkflowRun, AgentRun/activity, provider/tool request, Artifact, Evaluation, Approval, Decision, and Transition.

### 10. Establish package and contract compatibility rules

Before registries load packages, specify supported contract versions, dependency resolution, immutable historical access, upgrade/rollback, configuration overlays, trust provenance, and failure behavior. Initially support only bundled first-party Apps.

## Recommended v0.2 Scope

v0.2 should prove that FounderOS can execute one package-defined, policy-controlled workflow without hardcoded vertical-slice orchestration while preserving v0.1 safety.

Recommended scope:

- modular monolith and existing local CLI;
- existing five core objects and runtime records;
- App as a first-party package/index over existing definitions;
- minimal backward-compatible Agent and Workflow contract extensions;
- explicit authorization/capability checks;
- deterministic fake generation provider;
- versioned prompt template and structured response contract;
- Project-scoped evidence references;
- one package-defined Validation workflow vertical slice;
- existing Artifact, Evaluation, Approval, Decision, Transition, Event, replay, and audit boundaries;
- cost/attempt/time budgets represented even when the fake provider costs zero.

Success should be measured by removing hardcoded workflow coordination for the new slice, not by the number of registries or manifests created.

## What To Remove or Postpone

Remove from the immediate v0.2 implementation plan:

- separate Agent OS, Workflow OS, and Knowledge OS deployable-service assumptions;
- a new App execution object that duplicates Workflow;
- Skills as a first-class executable abstraction;
- App Marketplace commands and third-party package support;
- organization, domain, founder, and global memory;
- knowledge graph;
- embeddings/vector storage;
- streaming provider interface;
- multi-provider fallback routing;
- broad Tool catalogue and all external-write Tools;
- Domain Pack installation framework;
- REST API and Web UI surface design;
- cloud/multi-user operation on the local file adapter;
- enterprise RBAC, billing, and marketplace concerns.

Retain these as explicit future directions, not v0.2 acceptance criteria.

## What To Build First

Before application code, revise the blueprint and approve architecture decisions for:

1. App versus Workflow semantics.
2. Logical dependency directions and authority boundaries.
3. Lifecycle versus utility Workflow state effects.
4. Authorization and policy decision points.
5. AI/Tool activity, side-effect, idempotency, and recovery semantics.
6. Package compatibility and trust.
7. A narrow v0.2 vertical-slice acceptance scenario.

The first executable work after those decisions should be authorization enforcement, because provider and tool abstractions are unsafe without it. The first product-facing v0.2 work should then be a package-defined Validation workflow using deterministic inputs or a fake provider. This creates user value and forces manifest boundaries to solve real needs.

## Revised Milestone Plan

### Milestone 12A — Architecture Review Board

- Review the blueprint against the existing runtime and contracts.
- Record conditional approval and implementation gates.

### Milestone 12B — Blueprint Revision and Architecture Decisions

- Define App as a package over Workflow/Agent definitions.
- Replace the target dependency diagram.
- Define lifecycle versus utility Workflows.
- Specify v0.2 scope, non-goals, compatibility, and acceptance scenarios.
- Reconcile terminology with the five core objects and existing contracts.

### Milestone 12C — Authorization Policy Foundation

- Implement principal, tenant/project scope, capabilities, and policy decisions at application and lifecycle boundaries.
- Protect Approvals, Transitions, provider requests, tool requests, and sensitive reads.
- Keep external authentication out of scope initially.

### Milestone 12D — Durable Activity and Side-Effect Contracts

- Specify activity attempts, leases, cancellation, deadlines, idempotency, effect receipts, reconciliation, and Event correlation.
- No provider or Tool integration yet.

### Milestone 12E — Minimal First-Party App Package Contract

- Define package identity, compatibility, asset index, configuration overlay, and trust provenance.
- Reuse existing Agent and Workflow schemas; add only proven extensions.
- Load bundled first-party packages read-only.

### Milestone 12F — Structured Generation Port and Fake Provider

- Add canonical structured generation request/result contracts.
- Add prompt rendering, response schema validation, usage/budget fields, typed errors, and deterministic fake behavior.
- No real provider integration.

### Milestone 12G — Validation App Vertical Slice

- Build Validation as the first package-defined workflow.
- Exercise Agent, prompt, Artifact, Evaluation, Approval, Decision, Transition, audit, replay, and recovery boundaries.
- Demonstrate value from `OPPORTUNITY_SELECTED` without general marketplace or Tool infrastructure.

### Milestone 12H — First Read-Only Tool or Knowledge Capability, If Required

- Select exactly one capability demanded by Validation.
- Add source provenance, permission policy, result/effect receipt, and deterministic fake.
- Skip this milestone if Validation does not need it.

### Milestone 12I — One Real Provider Adapter, Opt-In

- Add one provider only after fake-provider acceptance passes.
- Enforce budgets, retention policy, redaction, timeout, error taxonomy, and explicit user configuration.

### Milestone 12J — v0.2 Hardening and Adoption Review

- Review user value, failure data, cost, latency, package ergonomics, and operational diagnostics.
- Decide whether additional providers, Tools, Knowledge retrieval, database persistence, or a second App are justified.

## Open Questions

1. Is an App only a distributable package, or is it intended to be a persisted runtime entity? If persisted, what unique lifecycle does it have that Workflow/WorkflowRun do not?
2. Can one App contain multiple Workflows, and can multiple Apps reference the same immutable Agent or Workflow definition?
3. How are installed package versions pinned for historical replay after upgrade or removal?
4. Which Workflows may request Project lifecycle transitions, and how are utility Workflows constrained?
5. What is the first concrete v0.2 user outcome that cannot be delivered cleanly with current contracts?
6. Is Validation the correct forcing function, or is another narrow workflow more valuable to target users now?
7. What constitutes an authenticated principal in local mode, and how does that map to a future tenant identity?
8. Where is the policy decision made when Agent, App, tenant, Tool, and provider constraints disagree?
9. What record proves an external side effect occurred when local persistence fails immediately afterward?
10. What are the retry and compensation semantics for non-idempotent Tools?
11. Which prompt representation is canonical across providers, and how are templates protected from untrusted retrieved content?
12. How are model capabilities negotiated without reducing the provider interface to an unusable lowest common denominator?
13. Who evaluates AI output, with which rubric version and evidence, and how is evaluator independence represented?
14. What are the per-command and per-WorkflowRun limits for spend, tokens, wall time, attempts, and external effects?
15. What knowledge can cross Project boundaries, who authorizes it, and how are deletion and derived indexes handled?
16. Are Domain Packs packages containing Apps and knowledge, configuration overlays, or a separate installable concept?
17. What compatibility promise does v0.2 make to existing v0.1 Projects, Events, Agent/Workflow definitions, and local stores?
18. What evidence would justify moving from a modular monolith to separate services?

## Final Recommendation

**Proceed with changes.**

Adopt the blueprint as a strategic direction, not as an executable specification. Revise it before implementation so that:

- App means package, Workflow means execution;
- existing Agent and Workflow contracts evolve rather than fork;
- the Kernel retains sole domain mutation authority;
- application commands sit between interfaces and the Kernel;
- authorization precedes providers and Tools;
- Project lifecycle state is not coupled to every App;
- durable activity and external-effect recovery are explicit;
- AI requests, prompts, evaluations, budgets, grounding, and provenance have enforceable contracts; and
- one narrow Validation vertical slice drives all new abstractions.

FounderOS should protect the platform vision by refusing to build the entire platform speculatively. The fastest credible path to v0.2 is one useful, package-defined, safely authorized workflow that proves the seams end to end.
