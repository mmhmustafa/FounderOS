# Atlas History — Network Memory

Atlas automatically remembers every discovery. Engineers can review how
their network looked and changed over time — one of Atlas's core
differentiators.

## History Repository

Every successful `founderos atlas discover` is preserved under:

```
.atlas/history/
  2026-07-09_23-41-18/
    discovery_metadata.json      the record contract (see below)
    topology_snapshot.json       full topology snapshot
    atlas_topology.html          interactive viewer for THIS discovery
    morning_brief.md             the run's Morning Brief
    dashboard.html               the dashboard as it looked after the run
    configs/<hostname>/          configurations collected in the run
```

Rules:

- **Never overwritten.** Directory names come from the discovery start time;
  a same-second collision gets a `-2` suffix, so records are always unique.
- **Self-describing.** `discovery_metadata.json` records start/end time,
  duration, device and relationship counts, warnings, failed hosts,
  configuration collection status, Morning Brief quality score, network
  status, snapshot ID, and the discovery schema version.
- **Fault-tolerant loading.** A corrupt or unreadable record becomes a
  reported issue; the rest of history still loads.
- **Clock ownership.** The history layer is the only place Atlas reads the
  system clock (injected and overridable); the deterministic discovery core
  remains clock-free.

## Timeline

`founderos atlas timeline` renders `timeline.md`: discoveries grouped by
day, newest first, each entry showing devices (with deltas), status,
configuration collection, failures — and **what actually changed**, computed
by running change intelligence between consecutive stored snapshots. No new
diff logic; the PR-022 detector reads the archived snapshot files.

## Reviewing history

- `founderos atlas history` lists every record: time, devices, status,
  duration, and the record folder path.
- Open any record's `atlas_topology.html` to view that discovery's topology
  interactively — the current topology remains the default viewer.
- The dashboard shows the last discovery time, the last five discoveries,
  and links to history and the timeline.

## Retention

No automatic pruning (by design — see non-goals): every record is kept
until an operator deletes it. Each record is an ordinary directory; deleting
one never affects the others. Retention policy is a deliberate future
decision, not an accidental behavior.

## Future extensibility

The repository is artifact-oriented specifically so future PRs need no
storage redesign:

- **Configuration diff** — compare `configs/<hostname>/running_config.txt`
  between any two records.
- **Incident replay** — walk records across a time window and re-run change
  intelligence between each pair.
- **Historical topology playback** — each record carries its own snapshot
  and rendered viewer.
- **AI reasoning** — records are self-describing JSON plus plain-text
  artifacts, directly consumable as context.

New artifact types are added by writing more files into the record
directory and listing them in the record's `metadata.artifacts` — no schema
migration, no database.
