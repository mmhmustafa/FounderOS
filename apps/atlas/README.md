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

## Next Step

Add a fixture-driven multi-device discovery Journey and topology reconciliation contract before considering any live transport.
