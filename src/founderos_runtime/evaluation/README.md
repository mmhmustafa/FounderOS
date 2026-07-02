# FounderOS Evaluation Contract and Runner

## Purpose

Evaluation is deterministic quality assessment of structured Artifact content or Provider output against declared rules. It answers whether content satisfies measurable requirements before a future human Approval, planning decision, or Workflow continuation.

```python
from founderos_runtime.evaluation import (
    EvaluationRequest,
    EvaluationRule,
    EvaluationRunner,
)

result = EvaluationRunner().run(
    EvaluationRequest(
        request_id="evaluation-001",
        artifact={"summary": "Evidence-backed opportunity"},
        rules=(
            EvaluationRule(
                id="summary.required",
                name="Summary required",
                description="A summary must exist.",
                severity="error",
                type="required_field",
                parameters={"field": "summary"},
            ),
        ),
    )
)
```

## Contracts

- `EvaluationRule` declares immutable rule identity, description, severity, type, and parameters.
- `EvaluationRequest` contains request identity, structured Artifact/Provider output, optional expected schema, immutable rules, and metadata.
- `EvaluationFinding` records one rule ID, severity, deterministic message, and pass/fail result.
- `EvaluationResult` records request identity, overall pass, normalized score, ordered findings, and deterministic metadata.

Supported severities are `info`, `warning`, `error`, and `critical`. Supported rule types are `required_field`, `schema`, `minimum_length`, `regex`, and `custom`.

These assessment contracts are distinct from the persisted runtime `Evaluation` record in `runtime/contracts/evaluation.schema.json`. PR-007 performs no repository or Event mutation. A future authorized Kernel service may translate an accepted result into persisted Evaluation evidence.

## Runner Semantics

Evaluation order is fixed:

1. built-in `content.not_empty` finding;
2. built-in `schema.expected` finding when `expected_schema` is supplied; and
3. declared rules sorted lexicographically by rule ID.

Score is the unweighted ratio of passed findings to total findings, rounded to six decimal places. Overall pass requires:

- score greater than or equal to the runner's configured `minimum_score`; and
- no failed `error` or `critical` finding.

Failed `info` and `warning` findings affect score but are not hard blockers. The default minimum score is `1.0`, so every finding must pass unless explicitly configured otherwise.

An empty rule list is valid. The built-in non-empty-content check still runs, producing score `1.0` for non-empty content and `0.0` for empty content.

## Built-in Rules

- `required_field`: requires a dotted `field` path to exist.
- `schema`: validates the Artifact or an optional field path against an inline Draft 2020-12 schema.
- `minimum_length`: requires `field` and non-negative integer `minimum` parameters.
- `regex`: applies a validated Python regular expression to a string field.
- `custom`: resolves a named callable supplied to `EvaluationRunner(custom_rules=...)`.

Dotted fields support mapping keys and numeric list indexes. Rule configurations reject missing, unknown, or invalid parameters before returning a result.

Custom handlers receive defensive JSON-compatible copies of the Artifact and parameters. They must return `bool` or `(bool, non-empty message)`. Handlers are caller-supplied pure functions; exceptions and invalid results become typed `EvaluationExecutionError` failures rather than findings.

## Provider Output vs Evaluation

A Provider response proves only that an adapter returned data. Schema-valid output proves shape, not truth, evidence, safety, or usefulness. Evaluation independently applies declared quality rules. Neither Provider success nor Evaluation pass creates an Artifact, grants authorization, records Approval, or changes Project state.

## Relationships

- **Approval:** Evaluation supplies machine-assessed evidence; it never records or replaces human Approval.
- **Planner:** a future Planner may inspect persisted Evaluation evidence. PR-007 neither invokes nor changes the Planner.
- **Workflow:** a future Workflow coordinator may request Evaluation and later submit its result through Kernel services. The runner executes no Workflow or step.
- **Provider:** Mock Provider output can be passed explicitly as Artifact input, but the runner never invokes any Provider.
- **Kernel:** this pure runner has no repository, Event, persistence, State Machine, or mutation dependency.

## Determinism and Safety

The runner performs no I/O, network access, time lookup, random generation, caching, global registration, or mutation. Given identical request, minimum score, schemas, and pure custom handlers, findings, score, metadata, and overall outcome are identical.

## Non-responsibilities

No human Approval, planning, Workflow/Agent execution, Provider execution, Tool execution, CLI, persistence, Event creation, Artifact lifecycle, authorization, or runtime mutation is implemented.

## Known Limitations and Recommended PR-008

Scoring is unweighted. Regex uses Python's local regular-expression engine without timeout controls. Custom-handler purity cannot be mechanically guaranteed. Evaluation rubrics are constructed in Python rather than loaded from package manifests. Results are not persisted or correlated with runtime Evaluation IDs.

PR-008 should define the versioned Evaluation Rubric Manifest schema and loader/Workspace support needed to package these rules declaratively. It must not add Workflow execution, real Providers, human Approval, or Kernel mutation.

## Evaluation Rubrics

PR-011 adds versioned declarative Evaluation Rubrics under `runtime/contracts/evaluation/`. `EvaluationRubricLoader` validates a rubric through the stateless Manifest Loader, converts its rules into existing immutable `EvaluationRule` objects, and configures the existing runner threshold. A rubric declares quality policy; it does not execute itself or grant Approval.

Workflow rubric path resolution and Journey adoption remain deferred to PR-012.
