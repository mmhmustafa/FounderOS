# Atlas Topology

## Graph Model

`TopologyGraph` is a deterministic in-memory projection. Reconciled `NetworkDevice` values are nodes; `NetworkNeighbor` observations are directed edges from a local device/interface to a remote hostname/interface. The graph also retains normalized interfaces and structured reconciliation warnings per canonical device.

Identical duplicate devices and edges are idempotent. Strict `add_device()` still rejects conflicting explicit IDs, while reconciliation records conflicts as warnings rather than overwriting them. Queries return stable tuples through `devices()`, `interfaces(device_id)`, `neighbors(device_id)`, and `edges()`, while `summary()` exposes deterministic counts, warnings, and protocol coverage.

## Device Identity

`TopologyReconciler` evaluates identity in fixed priority order:

1. case-insensitive hostname;
2. normalized management IP;
3. serial number when both observations provide one; and
4. explicit device ID.

Observations are sorted by stable device fields before merge. Alternate device IDs remain aliases of the selected canonical device, so later neighbor and interface queries resolve consistently.

## Merge Strategy

- Matching devices become one canonical node.
- Unique interfaces from every observation are retained by case-insensitive interface name.
- Compatible metadata keys are combined.
- Neighbor edges are remapped to the canonical local device and deduplicated by local interface, remote hostname, and remote interface.
- `merge_graph()` applies the same rules when combining existing in-memory graphs.

## Conflict Strategy

Atlas never uses last-write-wins. When matching observations disagree, the canonical value selected by stable input ordering remains authoritative for that reconciliation run and a deterministic `TopologyWarning` records the field and both values. Warnings are inspectable and included in `summary()`; PR-015 does not attempt policy-based resolution.

## Future Digital Twin

This graph is not yet a Digital Twin. Reconciliation establishes canonical identity and preserved observations, but future evolution still requires bidirectional link resolution, observation timestamps, provenance/version history, confidence, persistence, change events, and authorization.

## Topology Snapshot

`TopologySnapshot` is an immutable point-in-time projection of one reconciled graph. It includes:

- content-addressed `snapshot_id`;
- optional caller-supplied deterministic `created_at`;
- canonical devices with normalized interfaces;
- directed neighbor edges;
- structured reconciliation warnings; and
- schema version, observation, duplicate, warning, deterministic, and in-memory metadata.

The default snapshot ID is `atlas-topology:<sha256>`, calculated from canonical JSON content without randomness or clock access. Equal graph content and metadata therefore produce the same ID regardless of process or caller ordering.

`TopologySnapshotExporter` provides three pure projections:

- `to_dict()` returns a defensive JSON-compatible mapping;
- `to_json()` returns stable sorted, indented JSON; and
- `to_markdown()` returns a human-readable device, edge, and warning report.

Exporters return strings or values only. They never write files, persist snapshots, call FounderOS runtime services, or perform network access.

## Boundaries

The graph performs no discovery, network access, persistence, topology mutation outside its own process, device configuration, planning, or FounderOS runtime mutation.
