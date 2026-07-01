# FounderOS Executable Runtime Contracts

> **Status:** Milestone 2 specification; enforced by the Milestone 3 in-memory runtime foundation
>
> **Schema dialect:** JSON Schema Draft 2020-12
>
> **Scope:** Contracts only; no application behavior is implemented here

## Purpose

This folder is the machine-valid boundary between the FounderOS architecture and the future runtime implementation. JSON Schema validates record shape. The semantic documents define cross-record invariants, transition behavior, persistence ownership, and acceptance scenarios that cannot be expressed completely in JSON Schema.

## Contract Inventory

### Shared types

- `common.schema.json` — canonical identifiers, versions, revisions, timestamps, typed references, actors, and shared value types

### Five core objects

- `agent.schema.json`
- `artifact.schema.json`
- `workflow.schema.json`
- `state.schema.json`
- `decision.schema.json`

### Supporting runtime records

- `project.schema.json`
- `workflow-run.schema.json`
- `agent-run.schema.json`
- `transition.schema.json`
- `evaluation.schema.json`
- `approval.schema.json`
- `event.schema.json`

### Executable artifact content contracts

- `founder-brief-content.schema.json` — structured, versioned Founder Brief content
- `opportunity-report-content.schema.json` — deterministic Opportunity Report candidates and scoring

### Semantic contracts

- `transition-and-recovery.md`
- `persistence-boundaries.md`
- `acceptance-scenarios.md`

### Future authorization contracts

- `authorization/` — Milestone 12C placeholder AuthorizationRequest, AuthorizationDecision, PolicyRule, and AuthorizationPolicy schemas. They are intentionally outside the current runtime registry and do not change executable behavior.

### Future durable Activity contracts

- `activity/` — RFC-0001 placeholder ActivityRequest, ActivityResult, RetryPolicy, ActivityPolicy, ActivityRecord, and ActivityAuditRecord schemas. They are intentionally outside the current runtime registry and implement no executor or side effect.

### Agent package contracts

- `agent/agent.schema.yaml` - PR-001's independently validated, versioned Agent Manifest contract and Product Manager example. It is intentionally outside the current runtime registry and does not replace or alter the active `agent.schema.json` runtime definition contract.

### Workflow package contracts

- `workflow/workflow.schema.yaml` - PR-002's independently validated, versioned Workflow Manifest contract and Discovery example. It defines declarative process coordination and lifecycle/utility boundaries without replacing the active `workflow.schema.json` contract or implementing execution.

### App package contracts

- `app/app.schema.yaml` - PR-003's independently validated, versioned App Package Manifest contract and Discovery App example. It indexes exact definitions and assets without adding an App runtime, registry, installer, or execution authority.

### Manifest loading

`src/founderos_runtime/manifest_loader/` provides explicit Agent, Workflow, and App YAML loading with structural and semantic validation. It is separate from the active runtime `ContractRegistry`: loading returns a defensive object but performs no registration, resolution, installation, execution, or mutation.

`src/founderos_runtime/workspace/` builds a fresh read-only semantic snapshot from manifests beneath one bounded root. It validates exact App/Workflow/Agent relationships, compatibility, duplicates, and dependency cycles without creating a registry or execution authority.

`src/founderos_runtime/provider/` defines immutable structured generation contracts and a deterministic offline Mock Provider. It does not add a real Provider adapter, registry, prompt renderer, Activity integration, or runtime mutation path.

## Canonical Conventions

### Identifiers

Every persisted entity has an immutable type-prefixed ULID:

| Entity | Prefix |
|---|---|
| Agent | `agt_` |
| Artifact | `art_` |
| Workflow | `wfl_` |
| State | `sta_` |
| Decision | `dec_` |
| Project | `prj_` |
| Workflow Run | `wfr_` |
| Agent Run | `agr_` |
| Transition | `trn_` |
| Evaluation | `evl_` |
| Approval | `apr_` |
| Event | `evt_` |

Example: `prj_01JBY9M6H7Q5A3X2K8C4N0T1VW`.

IDs never encode mutable business meaning and are never reused. Stable state names such as `FOUNDER_SETUP` are state codes, not entity IDs.

### Versions and revisions

- Definition and content versions use Semantic Versioning, for example `1.2.0`.
- A version identifies an immutable definition or artifact content version.
- Mutable records use an integer `revision` starting at `1`.
- Every successful mutation increments the record revision exactly once.
- A caller must provide the expected revision for state-changing operations.
- A version never substitutes for an optimistic-concurrency revision.

### Timestamps

- Timestamps are RFC 3339 `date-time` strings normalized to UTC with a trailing `Z`.
- `created_at` is immutable.
- `updated_at` changes only when the record revision changes.
- Domain occurrence time and persistence time remain separate on events.

### References

A reference contains `kind`, `id`, and optionally an immutable `version` or mutable `revision`.

The runtime must enforce these semantic rules in addition to schema validation:

1. The ID prefix must match `kind`.
2. The referenced record must exist within the permitted project or global definition scope.
3. Versioned references resolve exactly; implementations must not silently substitute a newer version.
4. Revisioned references fail when the target revision differs.
5. Project-owned records must not reference records owned by another project unless an explicit shared-definition rule permits it.

## Object Boundary

Agent, Artifact, Workflow, State, and Decision are the five product-level objects. Project and execution records support their operation; they do not expand the product-level object model.

Definitions (`Agent`, `Workflow`, `State`) are immutable by version. Execution records (`WorkflowRun`, `AgentRun`, `Transition`, `Evaluation`, `Approval`, `Event`) capture what happened. `Artifact`, `Decision`, and `Project` are project-owned records with explicit revisions and/or versions.

## Status Ownership

Each schema owns its status vocabulary. Status strings must not be inferred across entity types. For example, an approved Artifact does not imply an applied Transition; both records and their linking approval/evaluation evidence are required.

## Validation Layers

1. **Syntactic:** Valid JSON.
2. **Structural:** Valid against the declared JSON Schema.
3. **Referential:** Typed references exist and match kind, project, version, and revision.
4. **Semantic:** Cross-record invariants and transition guards pass.
5. **Authorization:** The actor may perform the requested operation.
6. **Persistence:** The operation commits atomically or has no externally visible effect.

Passing an earlier layer never bypasses a later layer.

The runtime validator must enable RFC 3339 `date-time` format assertion; treating `format` as annotation-only is non-conformant.

## Compatibility

- Patch versions may clarify descriptions or add non-breaking optional fields.
- Minor versions may add optional behavior without invalidating existing records.
- Major versions are required for removed fields, changed meanings, stricter existing constraints, or status/transition incompatibility.
- Runtime implementations must reject unsupported major versions rather than guessing.

## Dependencies

- `architecture/FounderOS_Architecture_Specification_v1.0.md`
- `runtime/state-machine.md`
- `runtime/master-orchestrator.md`

## Risks

- JSON Schema cannot enforce database uniqueness, authorization, reference existence, event ordering, or transactionality.
- The architecture's universal confidence threshold is normalized to `0.70`; calibration remains future work.
- Authentication and tenant policy are intentionally deferred, but actor and project boundaries are reserved in the contracts.

## Runtime Implementation

`src/founderos_runtime/` loads these schemas through a Draft 2020-12 validator, enables format checking, and enforces repository, reference, revision, transition, and event semantics. `tests/test_acceptance_scenarios.py` executes the specified acceptance scenarios.

## Next Step

Milestone 6 should add durable storage ports and one restart-safe adapter without weakening these contracts.
