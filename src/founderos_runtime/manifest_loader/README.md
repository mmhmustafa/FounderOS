# FounderOS Manifest Loader

## Purpose

The Manifest Loader is the first runtime capability for FounderOS v0.3 package contracts. It reads Agent, Workflow, and App YAML manifests, validates each against its canonical Draft 2020-12 schema, applies deterministic cross-field contract checks, and returns a defensive parsed dictionary.

Public API:

```python
from founderos_runtime.manifest_loader import (
    load_agent_manifest,
    load_workflow_manifest,
    load_app_manifest,
)
```

`ManifestLoader(contract_directory=...)` is also available for explicit contract roots and isolated testing.

## Responsibilities

- read YAML using `yaml.safe_load`;
- select the exact Agent, Workflow, or App schema;
- validate the schema itself before use;
- apply structural and established semantic contract validation;
- return parsed data without coercion or mutation; and
- raise typed errors carrying `file`, `field`, and `reason`.

Errors are sorted deterministically. Missing required fields and unknown fields identify the field directly. Malformed YAML reports stable line and column details without exposing a generic parser traceback.

## Non-responsibilities

The loader does not:

- discover directories or infer manifest kinds;
- register, index, install, resolve, upgrade, or cache manifests;
- verify App content digests, signatures, publisher identity, dependencies, or referenced files;
- execute Apps, Workflows, Agents, prompts, Activities, Providers, or Tools;
- create runtime records, Events, Approvals, Evaluations, or state transitions;
- call the Kernel, Planner, State Machine, authorization policy, memory, or persistence; or
- expose CLI or Web behavior.

## Architecture Relationships

- **Contracts:** schemas under `runtime/contracts/{agent,workflow,app}/` remain authoritative. The loader reads them on every call and does not copy or cache them.
- **Registry:** a future registry may consume validated manifests, but registration, uniqueness across packages, version resolution, and lifecycle are explicitly absent.
- **Kernel:** the loader is a pure input boundary and has no Kernel dependency or mutation authority.
- **Workflow execution:** loading a Workflow proves contract conformance only. It does not create a WorkflowRun or execute a step.
- **Provider layer:** the loader does not render prompts, select models, or invoke Providers.
- **Authorization:** schema validity grants no capability. Future registration, resolution, and execution remain deny-by-default authorization boundaries.

## Determinism and Side Effects

Given identical schema and manifest bytes, validation selects the same first error by field path, validator, and reason. Each call rereads both files and returns a new defensive object. The loader has no cache, global registry, background work, network access, or writes.

## Usage

```python
manifest = load_workflow_manifest(
    "runtime/contracts/workflow/examples/discovery-workflow.yaml"
)
```

Failures are specific:

```python
try:
    manifest = load_app_manifest("app.yaml")
except ManifestLoaderError as error:
    print(error.file, error.field, error.reason)
```

## Dependencies

- Python 3.11+
- PyYAML 6.x for safe YAML parsing
- jsonschema 4.x for Draft 2020-12 validation
- PR-001 Agent Manifest contract
- PR-002 Workflow Manifest contract
- PR-003 App Package Manifest contract

## Known Limitations and Next Step

The default contract lookup expects the source-tree `runtime/contracts/` directory, matching the current editable/local deployment. Wheel resource packaging is not defined yet. File-size limits, YAML alias limits, referenced-asset resolution, digest verification, and registry semantics remain future work.

PR-005's read-only Workspace now performs bounded discovery and delegates every supported file to this loader before building a semantic snapshot. The loader itself remains path-explicit, stateless, uncached, and independent from Workspace indexing.

## Evaluation Rubrics

PR-011 adds the explicit `load_evaluation_rubric_manifest` API. It uses the same safe YAML, Draft 2020-12 schema, typed error, no-cache, and defensive-copy behavior as Agent, Workflow, and App loading. Conversion into executable Evaluation contracts remains owned by `founderos_runtime.evaluation`.
