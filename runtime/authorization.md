# Runtime Authorization Policy

> **Status:** Milestone 12C contract specification; runtime implementation not started  
> **Scope:** Runtime authorization only; no authentication, users, RBAC, permission database, Provider execution, Tool execution, or UI

## Purpose

FounderOS authorization determines whether a declared Actor may attempt an Action against a Resource under explicit Conditions. It exists to prevent interfaces, workflows, Agents, future Tools, future Providers, and orchestration code from reaching a protected Kernel mutation or sensitive read merely because they can construct a command.

Authorization is a prerequisite, not a mutation authority. An `allow` decision permits the command to continue to the owning Kernel service. The Kernel still validates contracts and references, applies optimistic concurrency, evaluates state guards and Approvals, commits records, and appends authoritative Events.

Authentication answers “who is this principal?” Authorization answers “may this Actor perform this Action on this Resource in this context?” Milestone 12C specifies only the second question. Local callers supply an Actor context; no identity proof or user system is implemented.

## Core Concepts

### Actor

The entity requesting or causing an operation.

Supported Actor types:

- `human` — a founder or future authorized person;
- `agent` — an Agent definition/run acting within delegated Workflow authority;
- `workflow` — Workflow coordination acting for an exact WorkflowRun;
- `tool` — a future controlled Tool acting only within a granted execution context; and
- `system` — a trusted FounderOS internal operation such as recovery or migration.

Actor type does not grant authority. IDs and attributes describe the request; PolicyRules decide it. Existing v0.1 runtime `actor` records remain unchanged until implementation explicitly maps them to authorization Actors.

### Action

A stable, namespaced operation code expressing intent. Actions describe authorization surface area; listing an Action does not implement it.

Canonical v0.2 action vocabulary:

| Area | Actions |
|---|---|
| Project | `project.create`, `project.read`, `project.update`, `project.archive` |
| Artifact | `artifact.create`, `artifact.read`, `artifact.update`, `artifact.delete`, `artifact.approve` |
| Decision | `decision.create`, `decision.read`, `decision.update` |
| State | `state.transition` |
| WorkflowRun | `workflow_run.create`, `workflow_run.read`, `workflow_run.update`, `workflow_run.cancel` |
| AgentRun | `agent_run.create`, `agent_run.read`, `agent_run.update`, `agent_run.cancel` |
| Approval | `approval.request`, `approval.read`, `approval.decide` |
| Evaluation | `evaluation.create`, `evaluation.read` |
| Definitions | `agent.register`, `workflow.register`, `app.execute` |
| Future Tool/Provider | `tool.execute`, `provider.invoke` |
| Future knowledge/memory | `knowledge.read`, `knowledge.write`, `memory.read`, `memory.write` |
| Configuration | `configuration.read`, `configuration.update` |

Aliases such as `create_artifact`, `transition_state`, and `invoke_provider` are documentation shorthand only. Contracts use the namespaced codes above to avoid collisions.

`artifact.delete`, `tool.execute`, `provider.invoke`, knowledge/memory actions, registration, and App execution are reserved policy vocabulary. Their presence does not authorize or implement those capabilities.

### Resource

The target of an Action. A Resource descriptor identifies its type, stable ID where one exists, Project scope, and exact version or revision when relevant. It carries only policy-relevant metadata and must never include Artifact content, prompts, secrets, credentials, raw Tool arguments, or sensitive memory.

Supported Resource types:

- `project`
- `artifact`
- `decision`
- `workflow`
- `workflow_run`
- `agent`
- `agent_run`
- `approval`
- `evaluation`
- `transition`
- `app_package`
- `knowledge_entry`
- `memory`
- `configuration`
- `tool`
- `provider`

### Effect

The Policy result: `allow` or `deny`.

FounderOS is deny-by-default. No match is a deny. An explicit matching deny overrides matching allows. An allow only opens the gate to the next boundary; it does not make the requested operation valid or successful.

### Condition

A declarative comparison against bounded request attributes. Conditions use allowlisted paths and operators; they cannot execute code, call services, read storage, inspect wall-clock time implicitly, or mutate data.

Supported conceptual operators:

- `equals`
- `not_equals`
- `in`
- `not_in`
- `exists`
- `not_exists`

Initial allowlisted paths include Actor type/ID, Action, Resource type/ID/Project scope, requested Project owner ID, current state, command name, and environment. Any time or expiry value must be explicit in the AuthorizationRequest so replay uses the same input.

### PolicyRule

An immutable, versioned statement containing an Effect, Actor types, Actions, Resource types, Conditions, priority, and optional non-authoritative obligations. A rule matches only when every declared selector and Condition matches.

### Policy

An immutable, versioned ordered set of exact PolicyRule references plus a combining algorithm and default Effect. Milestone 12C requires `deny_overrides` and `default_effect: deny`.

### Decision

The immutable result of evaluating one AuthorizationRequest against one exact Policy version. It records `allow` or `deny`, a stable reason code, matched rules, policy identity/version, evaluation time, and redacted diagnostics.

An AuthorizationDecision is not the product-level Decision core object. It is supporting policy evidence and uses a distinct contract and identifier namespace.

## Contract Inventory

Placeholder machine contracts live under `runtime/contracts/authorization/` so the current Runtime Foundation does not load or enforce them yet:

- `authorization-common.schema.json`
- `authorization-request.schema.json`
- `authorization-decision.schema.json`
- `policy-rule.schema.json`
- `authorization-policy.schema.json`

They are Draft 2020-12 schemas. Milestone 12C does not add them to `ContractRegistry`, repositories, persistence, Events, or application wiring.

## Placeholder Interfaces

These are semantic interfaces, not Python implementations:

```text
interface PolicyEngine:
    evaluate(
        request: AuthorizationRequest,
        policy: AuthorizationPolicy
    ) -> AuthorizationDecision

interface PolicyResolver:
    resolve(policy_id, exact_version) -> AuthorizationPolicy

interface AuthorizationBoundary:
    authorize(request) -> AuthorizationDecision
```

Interface rules:

1. `PolicyEngine.evaluate` is pure and performs no I/O or mutation.
2. `PolicyResolver` must return the exact requested immutable Policy version; it cannot silently use latest.
3. `AuthorizationBoundary` composes resolution and evaluation but cannot call the Kernel.
4. The application or owning Kernel service checks `decision.effect` and rejects before mutation when denied.
5. A future implementation must re-authorize at the owning mutation boundary, not rely solely on UI/CLI checks.

## Deterministic Policy Evaluation

Evaluation uses the following order:

1. Validate the AuthorizationRequest structurally.
2. Resolve the exact Policy and Rule versions.
3. Select enabled rules whose Actor, Action, Resource, and Conditions match.
4. If any matching rule has `deny`, return `deny` with `EXPLICIT_DENY`.
5. Otherwise, if any matching rule has `allow`, return `allow` with `ALLOW_RULE_MATCH` and the deterministic union of obligations.
6. Otherwise return `deny` with `DEFAULT_DENY`.

Matched rules are reported in descending priority and then lexicographic rule ID/version order. Obligations are deduplicated and lexicographically sorted. Identical request and policy inputs must produce the same Effect, reason, matched rules, and obligations.

Policy evaluation cannot depend on current time, randomness, network state, repository reads, mutable global state, or rule file order. Explicit request data may include a caller-supplied evaluation timestamp for audit, but it cannot alter matching unless represented through a declared Condition input.

## Decision Flow

### Planned workflow command

```text
Command
   |
   v
Application / Master Orchestrator facade
   |
   v
Planner (read-only, when planning is required)
   |
   v
Authorization Policy Boundary
   |
   +-- deny --> Redacted denial result; no Kernel call; no mutation
   |
   `-- allow
          |
          v
Owning FounderOS Kernel service
          |
          +-- contract/reference/guard/approval failure --> rejection
          |
          `-- commit --> authoritative Event --> Audit read model
```

The Planner is optional for commands that do not require planning. Authorization is mandatory immediately before every protected Kernel mutation.

### Trust and authority boundaries

```text
Untrusted intent and package declarations
  CLI | future API | App | Agent | Workflow | future Tool/Provider
                              |
                              v
                 Deterministic authorization gate
                              |
                   allow does not mutate
                              |
                              v
                    Kernel service boundary
             validation | revision | guards | approval
                              |
                              v
                 persistence + Events + audit
```

### Future outbound execution

```text
Authorized command
      |
      v
Kernel records durable activity request (future 12D)
      |
      v
Authorization re-check for exact Tool/Provider Resource and arguments digest
      |
      v
Outbound adapter (future; not implemented)
      |
      v
Result/effect receipt -> Kernel validation -> Event/Audit
```

## Mutation Boundary Coverage

Every mutation owner must eventually require an AuthorizationDecision for the exact Actor, Action, Resource, Project scope, and current revision/version:

| Mutation boundary | Representative Actions |
|---|---|
| Project State | `project.create`, `project.update`, `project.archive` |
| State Machine | `state.transition` |
| Artifact lifecycle | `artifact.create`, `artifact.update`, `artifact.approve`, future `artifact.delete` |
| Decision lifecycle | `decision.create`, `decision.update` |
| WorkflowRun service | `workflow_run.create`, `workflow_run.update`, `workflow_run.cancel` |
| AgentRun service | `agent_run.create`, `agent_run.update`, `agent_run.cancel` |
| Approval service | `approval.request`, `approval.decide` |
| Evaluation service | `evaluation.create` |
| Future definition/package boundary | `agent.register`, `workflow.register`, `app.execute` |
| Future outbound boundaries | `tool.execute`, `provider.invoke` |
| Future knowledge/memory boundary | `knowledge.write`, `memory.write` |
| Future configuration boundary | `configuration.update` |

Read policy is reserved for sensitive resources even though the immediate milestone focuses on mutation. Audit views must redact denial context and must not reveal the existence or contents of resources the Actor cannot read.

## Authorization and Approval

Authorization and Approval solve different problems:

- Authorization decides whether an Actor may attempt an Action.
- Approval is a persisted human decision about a particular subject and operation.
- State Machine guards determine whether required runtime evidence is satisfied.

An allow decision cannot create, infer, or replace an Approval. A valid Approval does not bypass authorization. For example, `state.transition` requires both an authorized requester and all Approvals/evidence required by the route.

Policy obligations may state that an Approval type is required, but obligations are instructions to the command coordinator. Only a resolved, current Approval record satisfies a Kernel or State Machine requirement.

## Future RBAC and Enterprise Compatibility

The initial model is capability/attribute-based rather than RBAC-specific. Future roles can map to sets of PolicyRules without changing AuthorizationRequest or AuthorizationDecision.

Enterprise extensions can add:

- organization and tenant scope;
- role assignments and group membership;
- separation of duties;
- environment and data-classification Conditions;
- policy administration authority;
- external identity claims supplied by an authentication adapter;
- time-bounded delegation; and
- policy-decision retention and compliance reporting.

Those features extend Actor/context resolution. They do not move mutation authority out of the Kernel or allow roles to bypass explicit deny, Approval, schema, revision, or state guards.

## Failure and Security Semantics

- Invalid or unsupported request: deny with `INVALID_REQUEST`.
- Missing/unavailable exact Policy version: deny with `POLICY_UNAVAILABLE`.
- Explicit deny match: deny with `EXPLICIT_DENY`.
- No rule match: deny with `DEFAULT_DENY`.
- Evaluation error or unknown operator/path: deny with `POLICY_EVALUATION_ERROR`.
- Denials cause no Kernel call and no domain mutation.
- Diagnostics expose stable reason codes and rule IDs only when the caller is allowed to inspect policy metadata.
- Resource content, secrets, raw arguments, prompts, memory, and sensitive Condition values are excluded or redacted.
- A future audit Event for policy evaluation is observational evidence; it cannot authorize a later request by itself.

## Current Limitations

- No PolicyEngine implementation exists.
- No policy is loaded, stored, assigned, or enforced.
- Current runtime Actors are not mapped to authorization Actors.
- No mutation service accepts AuthorizationDecision yet.
- No authentication, users, RBAC, role assignments, permission database, or UI exists.
- Reserved Provider, Tool, App, knowledge, memory, and configuration Actions have no executable capability.
- Policy persistence, caching, administration, and audit retention are deferred.

## Acceptance Scenarios for Future Implementation

1. Identical request and policy inputs return identical decisions.
2. No matching rule returns `DEFAULT_DENY`.
3. A matching deny overrides every matching allow.
4. Cross-Project resource access is denied unless an explicit future sharing rule permits it.
5. An Agent cannot approve its own Artifact or request a Project transition without delegated capability.
6. A Workflow can request only Actions declared and granted for its exact run context.
7. An allow decision reaches the Kernel but cannot bypass stale revision, schema, evidence, Approval, or transition guards.
8. A denial produces no domain mutation.
9. Sensitive denial diagnostics are redacted.
10. A missing Policy version fails closed.

## Next Step

Milestone 12D should define durable Activity and external side-effect contracts. It must not implement Provider or Tool execution.
