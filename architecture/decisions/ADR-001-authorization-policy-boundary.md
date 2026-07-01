# ADR-001: Authorization Policy Boundary Before Kernel Mutation

> **Status:** Accepted  
> **Date:** 2026-07-01  
> **Milestone:** 12C — Authorization Policy Foundation

## Context

FounderOS currently records Actors for audit and protects mutations with schemas, references, optimistic revisions, lifecycle services, State Machine guards, Evaluations, and human Approvals. Actor metadata does not prove that the Actor is allowed to attempt an operation.

Future Apps, Agents, Workflows, Tools, Providers, knowledge access, enterprise roles, and multi-user interfaces increase the number of callers that could reach Kernel services. Authorization must be explicit before these capabilities are implemented.

The Kernel must remain the sole owner of domain mutation. Moving mutation into a policy layer would split transaction, Event, replay, and recovery authority. Conversely, checking policy only in CLI/API presentation code would allow internal callers to bypass it.

## Decision

1. A deterministic authorization boundary evaluates every protected runtime mutation immediately before the owning Kernel service is invoked.
2. The PolicyEngine is a pure decision function over an AuthorizationRequest and an exact immutable Policy version.
3. Policy uses deny-by-default and deny-overrides combining semantics.
4. An allow decision permits the request to reach the Kernel; it does not perform or guarantee the mutation.
5. The owning Kernel service remains responsible for schema/reference validation, concurrency, state guards, Approval evidence, persistence, and authoritative Events.
6. Authorization and human Approval remain independent requirements; neither substitutes for the other.
7. Future Provider and Tool execution is prohibited until authorization enforcement and durable side-effect contracts exist.
8. Authentication, users, RBAC, role storage, policy administration, and UI are outside Milestone 12C.

## Decision Flow

```text
Command / intent
      |
      v
Application command boundary
      |
      v
AuthorizationRequest + exact Policy
      |
      v
Deterministic PolicyEngine
      |
      +-- deny --> no Kernel call, no domain mutation
      |
      `-- allow --> owning Kernel service
                         |
                         v
              validation / guards / Approval
                         |
                         v
                  commit + Event + audit
```

## Consequences

### Positive

- One consistent authorization model can serve local CLI, future API, enterprise roles, Agents, Workflows, Tools, and Providers.
- Default deny and deterministic rules are testable and replayable.
- Kernel transaction and Event authority remain intact.
- Future RBAC can compile roles into PolicyRules without changing mutation services conceptually.
- Approval remains explicit evidence rather than an implicit permission side effect.

### Costs and risks

- Every mutation boundary will require explicit authorization wiring in a future implementation milestone.
- Policy/resource context must be carefully minimized and redacted.
- Policy versioning and exact resolution become operational requirements.
- Checking only the application facade would be insufficient; the owning service boundary must enforce authorization.
- A future implementation must avoid time-, network-, or storage-dependent rules that break determinism.

## Rejected Alternatives

### Rely on existing Actor fields

Rejected because audit identity metadata does not grant authority and can be caller-supplied.

### Use human Approval as authorization

Rejected because Approval concerns a specific subject/business decision, while authorization governs whether an Actor may attempt an Action. Both may be required.

### Put mutations inside the PolicyEngine

Rejected because it would create a second mutation authority and break Kernel transaction, Event, replay, and recovery boundaries.

### Enforce policy only in CLI or future API

Rejected because Workflow, Agent, application, and future background callers could bypass presentation-layer checks.

### Implement RBAC first

Rejected because there is no authentication or user/role store, and runtime Actors include non-human entities. Capability/attribute PolicyRules preserve future RBAC compatibility without prematurely adding user infrastructure.
