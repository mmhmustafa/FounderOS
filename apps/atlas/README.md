# Atlas

## Purpose

Atlas is the first flagship first-party networking App built on the FounderOS platform. Both names remain internal codenames. FounderOS supplies platform planning, Journey execution, validation, authorization, Evaluation, Artifact, and deterministic Workflow boundaries; Atlas owns networking models, adapters, normalized facts, and topology behavior.

## PR-014 Scope

This package demonstrates deterministic network discovery from checked-in Cisco IOS command-output fixtures. It includes declarative App, utility Workflow, Agent, Artifact schema, Evaluation Rubric, and fixture assets. The Python implementation parses only caller-supplied text and operates entirely in memory.

Atlas is vendor-neutral by design. Cisco IOS is the first reference adapter because it provides concrete acceptance data, not because Cisco is the product boundary.

## Inputs and Outputs

Input is a mapping containing `show version`, `show ip interface brief`, and `show cdp neighbors detail` text. Output is a vendor-neutral `DiscoveryResult` containing one device, interfaces, neighbors, and provenance facts. `TopologyGraph` projects results into nodes and edges.

## Boundaries

There is no SSH, SNMP, credential handling, device mutation, persistence, database, real AI Provider, API, GUI, live multi-hop discovery, cloud discovery, log ingestion, or change intelligence. Real device collection must later use authorized durable Activity/transport boundaries; it must not be added to parsers.

## Running the Atlas Discovery Demo

Install FounderOS in editable mode, then run:

```powershell
founderos atlas demo discovery
```

The command reads only the bundled Cisco IOS fixture files, invokes the existing `DiscoveryEngine`, creates a second deterministic mock observation, reconciles both observations into an in-memory `TopologyGraph`, and prints normalized device and topology facts. It performs no network access, credential handling, persistence, device mutation, or AI call.

## Topology Reconciliation

`TopologyReconciler` merges multiple `DiscoveryResult` observations into one coherent graph. Device identity matching is deterministic and follows this priority: hostname, management IP, serial number when present, then explicit device ID. Results are sorted before merge so input order cannot choose a different canonical device.

Reconciliation preserves normalized interfaces, device metadata, and all unique neighbor observations. Identical devices and relationships are idempotent. If matching observations disagree about a device, interface, or metadata value, Atlas keeps the deterministic canonical value and records a structured warning; it never silently overwrites the conflict.

`TopologyGraph` now supports `merge_discovery_result()`, `merge_graph()`, `device_count()`, `edge_count()`, `find_device()`, `interfaces()`, `neighbors()`, `warnings()`, and an expanded `summary()`.

## Topology Snapshot Contract

`TopologySnapshot.from_graph()` converts the current reconciled graph into an immutable, versioned Artifact-shaped value. It contains canonical devices and their interfaces, directed edges, reconciliation warnings, device/edge counts, and deterministic metadata.

Snapshot IDs are SHA-256 content addresses over canonical snapshot content. `created_at` is optional and never reads the system clock; callers may supply a deterministic timestamp when their workflow owns one. `TopologySnapshotExporter` returns defensive dictionaries, canonical formatted JSON, or human-readable Markdown entirely in memory.

The contract is described by `manifests/schemas/topology-snapshot.schema.json`, and the Atlas topology rubric now evaluates its `devices`, `edges`, and `warnings` collections.

## Topology Viewer Demo

Run the interactive viewer from an editable installation:

```powershell
founderos atlas demo topology
```

The command reuses the fixture-only Discovery Engine, reconciliation, and snapshot pipeline. It writes `atlas_topology.html` in the current directory and asks the default browser to open it. The page supports pan, zoom, fit, deterministic node and edge rendering, vendor colors, hover details, click-through device information, and search highlighting.

The renderer is a pure Snapshot-to-HTML adapter. It does not discover devices, mutate the graph, persist topology state, or make a Python network request. The generated page loads the pinned Cytoscape.js browser library from a CDN, so first-time interactive viewing requires browser access to that single asset.

## Morning Brief Journey

Run Atlas's first operational FounderOS Journey:

```powershell
founderos atlas morning-brief
```

The command loads deterministic fixture snapshots, then invokes the declared utility Workflow through FounderOS Workspace, Planner, plan validation, authorization, Journey Runner, and Evaluation boundaries. It prints an operational summary and writes `morning_brief.md` in the current directory.

`MorningBrief` contains overall status, deterministic generation time, topology counts, new/removed/changed devices, warnings, reconciliation conflicts, recommendations, and source Snapshot metadata. The current Snapshot is required; a previous Snapshot is optional. When no timestamp is supplied by the caller or Snapshot, the Artifact records `unrecorded` rather than reading the system clock.

The Journey performs no AI call, network access, Project state transition, persistence, scheduling, email, notification, or GUI operation. Markdown file delivery belongs to the CLI, not the Journey.

## Next Step

Extract a reusable deterministic Topology Change Set contract for richer operational journeys before considering persistence or live transport.
