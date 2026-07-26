# Atlas Roadmap

Updated: 26 July 2026

This is the current product roadmap. Historical PR and milestone documents
remain evidence of what was planned at the time; they are not statements of
the present release.

## Shipped through PR-162

- Evidence-first multi-profile discovery with secure credential providers,
  resumable safety previews, configuration/evidence history, and enterprise
  federation.
- Authentication modes, server-side RBAC/CSRF/session controls, administration,
  diagnostics, backup/restore, audit, and authoritative release metadata.
- Policy, Changes, Incidents, Advisor, Paths, Predict, and Compass workflows.
- Persistent, audited, undoable topology curation; explicit site, WAN, and
  Internet types; OSPF and BGP operational views and provenance.
- Scalable site-first topology with derived membership, shared transit,
  latency corroboration, tiered interiors, routed inter-site links, focus,
  navigation memory, mini-map, hover lens, and sharp vector export.
- PR-155 stabilization: responsive topology controls, bounded supporting
  inventories, metadata hygiene, Home simplification, and Discovery draft
  lifecycle controls.
- PR-156 Evidence and Identity Resolution Center with confidence, provenance,
  audited decisions, conflict handling, bulk safeguards, and undo.
- PR-157 policy intent and applicability, baselines, approved deviations,
  calibration history, regression-first prioritization, and posture trends.
- PR-158 Action Center with deduplication, ownership, priority, snooze,
  recurrence, exact links, delivery outbox, reconciliation, and audit.
- PR-159 Network Time Travel across immutable discoveries, including topology,
  identity, OSPF/BGP, provenance, and missing-evidence changes.
- PR-160 unified investigation cases spanning Incidents, Paths, Advisor,
  Predict, Compass, participants, evidence, validation, risks, and follow-ups.
- PR-161 durable scheduled operations with leases, fencing, retries,
  maintenance windows, DST-safe cadence, recovery, and worker diagnostics.
- PR-162 vendor-neutral telemetry adapters with bounded, redacted,
  provenance-preserving collection and read-only operational overlays.

## Current release verification

1. Run the complete automated, security, packaging, documentation, dependency,
   performance, persistence, and real-browser gates after integration.
2. Treat every confirmed regression as release-blocking, correct it, and rerun
   the affected gate.
3. Keep adapter boundaries and accepted risks visible; do not present
   unavailable external capabilities as implemented.

## Next product increments

1. **Transactional workspace journal** — place state changes and their local
   audit records in one crash-consistent transaction boundary.
2. **Historical path replay adapters** — replay vendor-specific forwarding
   behavior from immutable history where sufficient evidence was retained.
3. **Production delivery providers** — deployer-supplied email/chat/webhook
   adapters with organization-specific secrets, routing, and retry policy.
4. **Live telemetry providers** — deployer-supplied vendor/controller adapters
   wired through the implemented registry and normalization boundary.

## Explicit adapter boundaries

- FortiOS per-VDOM detail needs an API-scoped collector because the read-only
  CLI transport refuses configuration-mode scoping.
- PAN-OS unbound zones require rulebase evidence beyond the interface table.
- Catalyst 9800 is currently treated as IOS-XE routed evidence; wireless
  relationships need a controller adapter.
- Cloud collectors normalize and preserve facts, but live federated-topology
  integration remains a separate adapter boundary.
- State JSON and the dedicated audit JSONL are individually atomic but are not
  yet one cross-file transaction; a transactional journal is the planned
  architectural boundary.
