# FounderOS App Package Manifest Contract

## Purpose

An App Package is an immutable, versioned, declarative index of the definitions and assets that deliver one cohesive FounderOS capability. It groups exact Workflow and Agent Manifest versions with Artifact schemas, prompt packs, Evaluation rules, policy requirements, deterministic fixtures, documentation, dependencies, and descriptive tags.

The canonical contract is `app.schema.yaml`. `examples/discovery-app.yaml` packages the Discovery contract assets conceptually. Both are YAML documents validated with JSON Schema Draft 2020-12.

## What an App Package Is Not

An App is not executable. It is not:

- a Workflow, WorkflowRun, scheduler, coordinator, or execution engine;
- an Agent, AgentRun, prompt renderer, or memory owner;
- a Provider or Tool adapter;
- an authorization grant or Approval;
- a repository, Event source, or Kernel mutation service; or
- installable plugin code.

The schema is closed with `additionalProperties: false`. Fields that imply execution, Provider calls, Tool invocation, memory, runtime mutation, secrets, or arbitrary code are rejected rather than treated as extensions.

## App, Workflow, and Agent Boundaries

- **App:** packaging. It answers which exact definitions and assets form a capability.
- **Workflow:** execution definition. It owns steps, Artifact flow, Evaluations, Approval requirements, recovery, and optional lifecycle transition intent.
- **Agent:** stateless role/capability definition selected by a Workflow.

An App never duplicates Workflow steps, entry/exit states, retry rules, Approvals, or transition intent. It references exact Workflow and Agent IDs, versions, and package-relative manifest paths.

## Runtime Relationship

A future package resolver may validate and resolve an App before a Workflow is selected. Resolution does not execute the App or authorize anything. Any future execution must still pass through application coordination, deny-by-default authorization, the appropriate Kernel services, RFC-0001 Activity boundaries for external work, and the State Machine for Project lifecycle changes.

Apps package capabilities but do not grant them. Package content cannot call Providers, invoke Tools, append Events, create runtime records, approve outputs, or mutate `Project.current_state`.

## Versioning and Immutability

`id` is a stable namespaced package identity such as `founderos.discovery`; App is a package concept and does not use a persisted core-object ULID prefix. `version` follows Semantic Versioning. Published content for an ID/version pair is immutable.

`content_digest` reserves a SHA-256 identity for the canonical packaged assets, excluding the digest field itself. PR-003 validates its shape only; canonical archive ordering and digest computation are intentionally deferred.

`compatible_runtime` and dependency `version_range` use one canonical form: `>=X.Y.Z <A.B.C`. This limited inclusive-minimum/exclusive-maximum form avoids ambiguous package-manager syntax while no resolver exists.

## Assets and References

- `workflows` and `agents` pin exact IDs, versions, and manifest paths.
- `artifacts` pin versioned content-schema paths.
- `prompts` reference versioned prompt-pack assets; prompt text is never embedded in the App Manifest.
- `evaluations` reference versioned rubric/rule assets.
- `policies` reference versioned policy-requirement assets; they request no authority and cannot override runtime authorization.
- `fixtures` reference deterministic data and exact SHA-256 digests.
- `documentation` references package documentation.
- `dependencies` reference other App packages by namespaced ID and bounded version range.

All paths are package-relative. Remote URLs, absolute paths, and parent-directory traversal are invalid.

## Future Marketplace Compatibility

Namespaced IDs, exact asset versions, bounded dependencies, publisher metadata, content digests, and immutable package contents are foundations for a possible marketplace. PR-003 accepts `trust: first_party` only. Signing, publisher verification, dependency resolution, installation, upgrades, rollback, revocation, sandboxing, and third-party trust are future architecture—not implied capabilities.

## Why Manifests Remain Declarative

Declarative packages can be reviewed, hashed, versioned, validated, audited, and resolved without executing untrusted code. Keeping process behavior in Workflows prevents Apps from becoming a second execution model. Keeping mutation in Kernel services prevents packages from becoming a second authority.

## Validation

JSON Schema validates structure, enums, exact reference forms, safe paths, compatibility syntax, digests, and non-empty Workflow/Agent indexes. Deterministic contract-test validation additionally rejects duplicate logical Workflow, Agent, asset, policy, and dependency identifiers that differ in other fields.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest tests/test_app_manifest_schema.py -q
```

The active `ContractRegistry` remains non-recursive and does not adopt this definition. PR-004's explicit Manifest Loader validates a requested App Manifest path without registry, installation, execution, CLI, Provider, Tool, marketplace, or Kernel behavior.

## Dependencies

- `runtime/contracts/agent/agent.schema.yaml`
- `runtime/contracts/workflow/workflow.schema.yaml`
- `architecture/FounderOS_v0.2_Blueprint.md`
- `runtime/authorization.md`
- `docs/rfcs/RFC-0001-durable-activity-and-side-effect-contracts.md`

## Risks and Next Step

No resolver proves that indexed files exist or that their internal IDs, versions, and digests match these references. Canonical package hashing, signatures, installation, and historical resolution remain undefined. The next PR should define prompt-pack and Evaluation-rubric asset contracts—or another explicitly approved narrow contract gate—before any package loading or execution is considered.
