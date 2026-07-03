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

## Next Step

Define a versioned Topology Snapshot Artifact and deterministic quality rubric before considering persistence, visualization, or live transport.
