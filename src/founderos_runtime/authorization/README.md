# Execution Plan Authorization

## Purpose

`AuthorizationEngine` is a pure deterministic policy gate for a validated `ExecutionPlan`. It evaluates the capabilities requested by plan step types and returns an immutable `AuthorizationDecision`.

```python
validation = PlanValidator(workspace).validate(plan)
decision = AuthorizationEngine().authorize(plan, validation)
```

This is runtime authorization, not authentication, RBAC, or a production policy service.

## Default Policies

Policies run in fixed order with deny-overrides behavior:

1. `deny_missing_validation` denies absent or invalid Validation reports.
2. `deny_unknown_capability` denies any capability outside the fixed PR-010 vocabulary.
3. `require_approval_for_high_risk` requires declared Approval gates for Activity or state-transition intent.
4. `allow_safe_plan` allows an otherwise valid, known-capability plan.

Identical plan and Validation inputs produce equal Decisions, policy results, required Approval references, reasons, and metadata.

## Authorization Versus Approval

Authorization decides whether a plan may proceed to its in-scope execution boundary. `required_approvals` reports gates the plan must eventually satisfy; it does not mean a human has approved them.

Approval is a separate persisted human decision about an exact subject. PR-010 performs no human interaction and creates no Approval record. The Journey Runner continues to skip Approval and transition execution.

## Authorization Versus Execution

An allow Decision does not execute anything and does not authorize Kernel mutation. The Journey Runner may perform only its existing deterministic in-memory Mock Provider and Evaluation operations. Future Provider, Tool, persistence, and Kernel work still requires the full authorization and durable Activity architecture.

## Known Limits

The policy set is fixed in code. There are no users, Actors, roles, tenant scopes, external policy files, database, clocks, policy persistence, or authorization audit Events. Capability inference is limited to current plan step types or explicit test metadata.

