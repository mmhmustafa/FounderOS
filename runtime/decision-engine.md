# Decision Engine

> **Status:** Contract-level specification; implementation not started
>
> **Schema:** `runtime/contracts/decision.schema.json`

## Purpose

The Decision Engine records explicit project choices, considered alternatives, rationale, ownership, evidence, approval, reversibility, and supersession.

## Inputs

- Active Project and state
- Decision proposal with options and owner
- Related Artifact/Evaluation evidence
- Human Approval for important decisions

## Outputs

- Versioned/revisioned Decision
- Decision lifecycle Events
- Exact Decision reference for workflows and transition guards

## Invariants

1. A proposed Decision has context and at least one option.
2. An approved Decision requires selected option, rationale, and Approval reference.
3. Agents may propose but cannot grant required human approval.
4. Approved Decisions are not edited in place; correction creates a superseding Decision.
5. Supersession preserves the complete prior record and reference chain.
6. Decision state code records where the choice was made; it does not itself transition Project state.
7. Related evidence must belong to the same Project and resolve exactly.

## Status Transitions

```text
proposed -> approved | rejected
approved -> superseded
```

Rejected and superseded Decisions are terminal.

## Important Decisions

Opportunity selection, validation go/no-go, target customer, MVP scope, architecture/technology choices, AI model strategy, launch authorization, and scaling require authorized human approval unless a later policy explicitly says otherwise.

## Dependencies

- Artifact Registry
- Evaluation and Human Approval services
- Project State
- Event store

## Failure and Recovery

Missing evidence or approval leaves the Decision proposed. Conflicting approved decisions require a new explicit superseding Decision; the engine never silently selects the newest record.

## Risks

- Decision conflict policy and role-based authority remain to be implemented.
- Confidence is normalized to `0..1` but is not a substitute for evidence or approval.

## Next Step

Implement proposal, approval, rejection, and supersession repository operations in Milestone 3.
