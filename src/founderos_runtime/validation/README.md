# Execution Plan Validation

## Purpose

`PlanValidator` is a deterministic, read-only preflight boundary for an immutable Workspace `ExecutionPlan`. It answers whether the plan is internally coherent and still compatible with its Workspace definitions before any Journey step runs.

```python
report = PlanValidator(workspace).validate(plan)
```

## Validation Rules

The validator checks:

- the Workflow exists at the planned version;
- required Agents exist at exact versions;
- step Agent references are declared;
- Artifact inputs and outputs are declared;
- every produced Artifact has exactly one producer;
- IDs are not duplicated;
- Artifact dependencies are acyclic;
- producers precede consumers in execution order; and
- required Evaluations have valid Artifact subjects and checkpoints.

All rules run without short-circuiting so one immutable `ValidationReport` can describe every deterministic finding. Errors make the report invalid; warnings are non-blocking. Finding order is stable.

## Validation Is Not Authorization

Validation answers “is this plan structurally coherent?” Authorization answers “may this validated plan request these capabilities?” A valid plan can still be denied. Validation never grants capability, records Approval, executes a step, or calls the Kernel.

## Validation Is Not Approval or Execution

Human Approval is durable evidence about a specific subject. This validator does not ask a human or satisfy Approval gates. Execution performs work; validation performs no Provider call, Tool call, file write, persistence, Event append, or state mutation.

## Known Limits

PR-010 validates the dependency information expressible through Artifact flow. It does not load Evaluation rubric assets, inspect live Project state, verify authorization Actors, or compare against persisted run history.

