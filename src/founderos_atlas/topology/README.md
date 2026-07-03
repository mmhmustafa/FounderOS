# Atlas Topology

## Graph Model

`TopologyGraph` is a deterministic in-memory projection. Discovered `NetworkDevice` values are nodes; `NetworkNeighbor` observations are directed edges from a local device/interface to a remote hostname/interface.

Identical duplicate devices and edges are idempotent. Conflicting facts for the same identity are rejected rather than overwritten. Queries return stable tuples through `devices()`, `neighbors(device_id)`, and `edges()`, while `summary()` exposes deterministic counts and protocol coverage.

## Future Digital Twin

This graph is not yet a Digital Twin. That future capability requires bidirectional edge reconciliation, identity resolution, observation timestamps, provenance/version history, confidence, persistence, change events, and authorization. Those concerns should grow from evidence gathered by multiple DiscoveryResults rather than being guessed into this foundation.

## Boundaries

The graph performs no discovery, network access, persistence, topology mutation outside its own process, device configuration, planning, or FounderOS runtime mutation.
