# Atlas Sites — Evidence-Based Inference Foundation (PR-033)

A site is a location/administrative concept — never "a subnet". Assignment
weighs independent signals: explicit user mapping (high, decisive),
hostname conventions and seed-origin profile hints (assigning: one signal =
low, agreement = medium), and declared network ranges (corroborating only —
they raise confidence one step but can never assign by themselves, because
a site may hold many subnets and one supernet may span many sites).
Conflicting assigning signals yield **ambiguous**; no assigning signal
yields **unknown**. Every `SiteAssignment` carries status, confidence, the
explicit flag, and the full evidence list. The user-defined catalog lives
at `<workspace>/sites.json`.

## Explicit types and operator curation

Every catalog entry has an explicit `site_type`: `site`, `wan`, `internet`,
or `cloud`. Missing values in older catalogs load as `site`, so an unknown or
weakly inferred location is never promoted into a WAN/Internet symbol by
layout heuristics.

Durable device moves are overlays, not mutations of discovery evidence.
`SiteOverrideRepository` stores them in `<workspace>/site-overrides.json`,
uses stable serial/device/IP/hostname identity keys, checks an optimistic
catalog revision on every write, and records append-only events in
`site-overrides.audit.jsonl`. Revert returns a device to automatic inference;
undo restores the preceding effective override. If the underlying inference
changes, the viewer shows both conclusions as a conflict instead of hiding it.
