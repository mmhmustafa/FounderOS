# CURRENT_SPRINT

Sprint: Atlas Topology Snapshot Diff and Change Classification (PR-017)

## Goal
Compare two Atlas Topology Snapshots deterministically and explain their structural changes without persistence or remediation.

## Prerequisites Completed
- PR-001 through PR-013 FounderOS platform, Journey, and CLI foundations
- EPIC-001 / PR-014 and PR-014.1 Atlas Discovery and CLI foundations
- EPIC-001 / PR-015 multi-device topology reconciliation
- EPIC-001 / PR-016 versioned content-addressed Topology Snapshot contract

## Expected Scope
- Deterministic device, interface, edge, warning, and metadata comparison
- Added, removed, and changed classifications
- Machine-readable and Markdown change reports
- No SSH, SNMP, credentials, persistence, graph database, GUI, AI, or remediation

## Definition of Done
Two valid snapshots produce one stable explainable change report independent of input ordering, with no external side effects.
