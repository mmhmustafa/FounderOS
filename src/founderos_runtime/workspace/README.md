# FounderOS Workspace

## Purpose

The Workspace is an immutable-by-interface, in-memory semantic snapshot of one FounderOS project root. It discovers supported YAML manifests, delegates all parsing and contract validation to PR-004's Manifest Loader, indexes exact App, Workflow, and Agent definitions, validates their relationships and compatibility, and exposes deterministic read-only queries.

```python
from founderos_runtime.workspace import Workspace

workspace = Workspace.load("path/to/project")
workspace.apps()
workspace.workflows()
workspace.agents()
workspace.get_app("founderos.discovery")
workspace.summary()
```

## Why It Exists

Individual manifests describe definitions; the Workspace answers whether a bounded project tree forms one coherent model. It catches duplicate identities, unresolved exact references, incompatible runtime versions, dependency incompatibility, and circular App dependencies before any future planning or execution boundary sees the definitions.

The Workspace is not a registry. It has no global state, registration API, lifecycle, version resolver, persistence, or mutation operations. Every `Workspace.load` creates a fresh independent snapshot.

## Discovery Convention

The Workspace scans `.yaml` and `.yml` files beneath the supplied root. A manifest kind is determined by its nearest ancestor directory named:

- `agents` for Agent Manifests;
- `workflows` for Workflow Manifests; or
- `apps` for App Package Manifests.

Files outside those directories are ignored. Results are ordered by normalized relative path. Symbolic-link roots and manifest files are rejected, and resolved files must remain inside the Workspace root.

## Validation

Loading performs, in order:

1. bounded deterministic discovery;
2. PR-004 structural and semantic manifest validation;
3. duplicate Agent, Workflow, and App ID detection;
4. App/runtime and Workflow/Kernel compatibility checks;
5. exact App-to-Workflow and App-to-Agent reference checks;
6. exact Workflow-to-Agent reference checks;
7. required App dependency existence/version checks; and
8. deterministic circular App dependency detection.

Optional missing App dependencies are allowed. An optional dependency that is present must still satisfy its declared range and participates in cycle detection.

## Read-only Query Model

`apps()`, `workflows()`, and `agents()` return tuples sorted by ID. `get_app`, `get_workflow`, and `get_agent` return defensive copies and raise `WorkspaceItemNotFoundError` for unknown IDs. `summary()` returns deterministic counts and sorted identifier lists. Mutating any returned object cannot change the Workspace snapshot.

## Relationships

- **Manifest Loader:** owns YAML parsing and per-file contract validation. Workspace does not duplicate that boundary.
- **Planner:** a future Planner adapter may read a Workspace snapshot, but PR-005 neither changes nor invokes the current Planner.
- **Runtime/Kernel:** Workspace is a read model only. It creates no runtime records, Events, runs, Approvals, Evaluations, Artifacts, or transitions.
- **Registry:** a future registry may manage definition lifecycle and version resolution. Workspace only indexes one load and exposes no registration API.
- **Authorization:** Workspace performs no authorization and grants no capabilities. Future consumers must authorize protected operations independently.

## Non-responsibilities

Workspace cannot execute Workflows or Agents, select or invoke Providers, call Tools, render prompts, manage memory, authorize actors, mutate Project state, persist definitions, install Apps, resolve marketplace packages, or call the Kernel.

## Known Limitations

- Runtime compatibility supports core `X.Y.Z` versions only; prerelease ordering is deferred.
- App `manifest_ref` paths and other packaged assets are not yet resolved or digest-verified; relationships resolve exact IDs and versions from loaded manifests.
- Workspace scans the complete bounded tree on every load and has no incremental refresh or cache.
- Directory symlink hardening is limited by platform filesystem semantics; manifest symlinks and resolved root escapes are rejected.
- One active manifest per logical ID is allowed; side-by-side versions require a future registry/version resolver.

## Recommended PR-008

Define a versioned Evaluation Rubric Manifest that packages deterministic rules for the PR-007 runner. Keep Workspace read-only and do not add Workflow execution, human Approval, persistence, or Kernel mutation.
