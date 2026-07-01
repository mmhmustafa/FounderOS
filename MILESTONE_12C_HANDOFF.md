# FounderOS Milestone 12C Handoff

Milestone 12C — Authorization Policy Foundation is complete at the architecture and contract level.

## Outcome

FounderOS now has a defined deterministic authorization boundary that must precede protected Kernel mutations and future Provider or Tool execution.

Milestone 12C intentionally does not wire authorization into the current application or runtime. No existing Actor schema, repository, persistence format, service, CLI command, Event, or mutation behavior changed.

The distinction is important:

- authorization architecture and contracts now exist;
- runtime enforcement does not yet exist;
- an authorization allow never performs a mutation;
- the FounderOS Kernel remains the sole domain-mutation authority; and
- only the State Machine may change `Project.current_state`.

## Core authorization concepts

### Actor

The entity requesting or causing an operation. Contract Actor types are:

- `human`
- `agent`
- `workflow`
- `tool`
- `system`

Actor metadata does not prove identity or grant authority.

### Action

A stable namespaced operation code such as:

- `artifact.create`
- `artifact.update`
- `artifact.approve`
- `state.transition`
- `approval.decide`
- `workflow_run.create`
- `agent.register`
- `app.execute`
- `tool.execute`
- `provider.invoke`
- `memory.read`
- `memory.write`

Reserved actions do not implement their capabilities.

### Resource

The protected target, including Project, Artifact, Decision, Workflow, WorkflowRun, Agent, AgentRun, Approval, Evaluation, Transition, App package, KnowledgeEntry, Memory, Configuration, Tool, and Provider.

Resource descriptors contain only bounded policy metadata. They must not contain content, prompts, secrets, credentials, or raw external arguments.

### Effect

The Policy outcome: `allow` or `deny`.

FounderOS is deny-by-default. Explicit deny overrides matching allows.

### Condition

A declarative comparison over allowlisted request paths. Conditions cannot execute code, perform I/O, mutate state, or depend implicitly on time, randomness, network state, or mutable global data.

### PolicyRule and Policy

Rules and Policies are immutable and versioned. Policies use exact Rule references, `default_effect: deny`, and `combining_algorithm: deny_overrides`.

### AuthorizationDecision

The immutable result of evaluating one AuthorizationRequest against one exact Policy version. It is supporting policy evidence, not the product-level Decision core object.

## Contracts added

Under `runtime/contracts/authorization/`:

- `authorization-common.schema.json`
- `authorization-request.schema.json`
- `authorization-decision.schema.json`
- `policy-rule.schema.json`
- `authorization-policy.schema.json`
- `README.md`

These Draft 2020-12 schemas are intentionally placed in a non-recursive subdirectory. The current `ContractRegistry` does not load or enforce them.

Placeholder semantic interfaces are defined for:

- `PolicyEngine`
- `PolicyResolver`
- `AuthorizationBoundary`

No Python interface or implementation was added.

## Deterministic decision flow

```text
Command
   |
Application / Master Orchestrator facade
   |
Optional read-only Planner
   |
Authorization Policy Boundary
   |
   +-- deny --> redacted denial; no Kernel call; no mutation
   |
   `-- allow --> owning Kernel service
                        |
              contracts / revision / guards / Approval
                        |
                  commit + Event + audit
```

Evaluation order:

1. Validate request.
2. Resolve exact Policy and Rule versions.
3. Match Actor, Action, Resource, and Conditions.
4. Any matching deny returns `EXPLICIT_DENY`.
5. Otherwise a matching allow returns `ALLOW_RULE_MATCH`.
6. Otherwise return `DEFAULT_DENY`.

## Authorization versus authentication and Approval

- Authentication determines who a principal is; it is not implemented.
- Authorization determines whether an Actor may attempt an Action.
- Approval is a persisted human decision about a specific subject.
- State Machine guards determine whether transition evidence is satisfied.

An allow cannot create or replace Approval. Approval cannot bypass authorization. Both may be required before a guarded mutation succeeds.

## ADR

Added:

```text
architecture/decisions/ADR-001-authorization-policy-boundary.md
```

It records:

- authorization precedes protected Kernel mutation;
- PolicyEngine evaluation is pure and deterministic;
- deny-by-default and deny-overrides are mandatory;
- the Kernel retains validation, transaction, Event, replay, and recovery authority;
- Approval remains independent; and
- Provider/Tool execution remains prohibited until authorization enforcement and durable side-effect contracts exist.

## Architecture decisions added

- D-054 — Authorization is distinct from authentication.
- D-055 — Policies are immutable, exact-versioned, default-deny, and deterministic.
- D-056 — Allow permits Kernel entry but performs no mutation or bypass.
- D-057 — Authorization and human Approval are independent.
- D-058 — Placeholder authorization schemas remain unloaded and unenforced.

## Documentation updated

- `runtime/authorization.md`
- `runtime/contracts/README.md`
- `runtime/service-boundaries.md`
- `runtime/master-orchestrator.md`
- `architecture/FounderOS_v0.2_Blueprint.md`
- `.ai/BUILD_ROADMAP.md`
- `.ai/CURRENT_SPRINT.md`
- `.ai/PROJECT_CONTEXT.md`
- `.ai/DECISIONS.md`
- `README.md`
- `CHANGELOG.md`

## Verification

- Five authorization schemas passed JSON Schema Draft 2020-12 meta-validation.
- Representative PolicyRule, AuthorizationPolicy, AuthorizationRequest, and AuthorizationDecision records validated successfully.
- The active runtime schema count remains unchanged at 15.
- The complete existing suite passed: 86 tests and 5 subtests.
- No source or test file changed.
- No runtime behavior changed.

## Remaining risks and future work

- Existing runtime Actors are not mapped to authorization Actors.
- Policy resolution, storage, administration, caching, and assignment are undefined.
- No application or Kernel service enforces AuthorizationDecisions yet.
- Authorization decision persistence and audit Event treatment remain undefined.
- Redacted denial diagnostics and authorization acceptance tests require implementation.
- Cross-Project sharing and enterprise identity/tenant scope are deferred.
- Runtime authorization enforcement remains mandatory before Provider or Tool execution.

## Recommended next milestone

Proceed with **Milestone 12D — Durable Activity and Side-Effect Contracts**.

Milestone 12D should define activities, attempts, leases, deadlines, cancellation, idempotency, effect receipts, reconciliation, compensation, and correlation. It must not implement Provider or Tool execution.
