# FounderOS Workflow Manifest Contract

## Purpose

A Workflow Manifest is an immutable, versioned, declarative process definition. It coordinates ordered steps, exact Agent definitions, Artifact requirements and outputs, Evaluations, human Approvals, recovery policy, and—only for lifecycle Workflows—Project state transition intent.

The canonical contract is `workflow.schema.yaml`. `examples/discovery-workflow.yaml` conceptually models the existing deterministic Discovery path without invoking its implementation. Both are YAML documents validated with JSON Schema Draft 2020-12.

## What a Workflow Manifest Is Not

A Workflow Manifest is not:

- an App package or asset index;
- an Agent, prompt, executable script, or Provider configuration;
- a WorkflowRun, scheduler, queue, worker, or execution engine;
- an authorization grant, human Approval record, Evaluation result, or Transition record; or
- permission to mutate repositories, append Events, execute an Activity, or change Project state.

Manifests are declarative because definitions must remain inspectable, version-pinned, deterministic, and safe to validate before any execution decision. A manifest does not execute itself.

## Architecture Relationships

- **App:** an App packages exact Workflow and Agent definitions plus assets. App is packaging; Workflow is the executable process definition.
- **Agent:** an Agent is a stateless role/capability performer. `required_agents` and `optional_agents` pin exact Agent IDs and versions; a step's `required_agent` must resolve from `required_agents`.
- **Kernel:** future coordination must request all mutations through the owning Kernel service. A Workflow cannot write repositories or authoritative Events.
- **Authorization:** every protected step, run mutation, Approval action, Activity, and transition request remains deny-by-default. Manifest declarations never grant authority.
- **Activities:** an `activity_request` step declares an RFC-0001 Activity category. A future coordinator must durably request and authorize the Activity; the step never performs the side effect.
- **Artifacts:** required and produced Artifacts are declarations. Actual content and lifecycle records remain Kernel-owned and contract-validated.
- **Evaluations:** requirements reference immutable rubrics. A declared Evaluation is not an Evaluation result and proves neither truth nor quality by itself.
- **Approvals:** requirements identify human decisions that must become Kernel Approval records. A declaration cannot approve anything.
- **Transitions:** `transition_intent` is a request. Only the State Machine may validate guards and update `Project.current_state`.

## Lifecycle and Utility Workflows

A `lifecycle` Workflow participates in the FounderOS Project lifecycle. It must declare a real `exit_state` and `transition_intent`. The intent's `from_state` and `to_state` must match the manifest's entry and exit states, and all referenced Approvals must be declared. Completion alone never applies the transition.

A `utility` Workflow can produce Artifacts, Evaluations, Decisions, run records, and Events through future Kernel coordination, but it cannot request a Project lifecycle transition. The schema therefore requires `exit_state: null` and `transition_intent: null` for every utility Workflow.

## Step Model

Supported step types are:

- `human_input`
- `agent_task`
- `evaluation`
- `approval`
- `activity_request`
- `artifact_creation`
- `transition_request`

Every step declares Artifact inputs/outputs, Approval need, and deterministic success/failure routing. `agent_task` requires an exact Agent reference. `activity_request` requires an RFC-0001 Activity category; all other step types require `activity_type: null`.

## Validation Layers

JSON Schema validates shape, enums, lifecycle/utility transition boundaries, exact reference form, and conditional step fields. Deterministic semantic validation additionally checks:

1. step Agent references are present in `required_agents`;
2. step Artifact references are declared by the Workflow;
3. transition states match entry and exit states;
4. transition Approval references resolve to required manifest Approval declarations; and
5. IDs for steps, Artifacts, Evaluations, and Approvals are unique in their scopes.

PR-002 established these semantic invariants in contract tests. PR-004's explicit Manifest Loader now applies the same invariants when a Workflow Manifest path is requested, without registering or executing it.

## Identity, Compatibility, and Recovery

`id` reuses the established canonical `wfl_` ULID namespace. `version` identifies immutable manifest content using Semantic Versioning. Compatibility pins minimum and exclusive-maximum Kernel contract versions plus the exact Agent Manifest schema version.

Recovery declarations bound attempts and state what a future coordinator should request after failure. They do not retry Activities, mutate WorkflowRuns, or bypass RFC-0001 ambiguity and idempotency rules.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_manifest_schema.py -q
```

The active `ContractRegistry` remains non-recursive and does not adopt this definition. PR-004's explicit Manifest Loader validates a requested path only; the active `workflow.schema.json`, runtime services, Planner, Discovery implementation, CLI, and persistence behavior remain unchanged.

## Dependencies

- `runtime/contracts/agent/agent.schema.yaml`
- `runtime/contracts/common.schema.json`
- `architecture/FounderOS_v0.2_Blueprint.md`
- `runtime/authorization.md`
- `docs/rfcs/RFC-0001-durable-activity-and-side-effect-contracts.md`

## Risks and Next Step

No package resolver currently proves that referenced Agent or rubric versions exist, and no runtime adopts this manifest. PR-003 now defines the first-party App Package Manifest that indexes exact Workflow, Agent, schema, prompt, rubric, fixture, and documentation assets; loading and resolution remain deferred.
