# Atlas Product Audit (PR-041)

A holistic review of Atlas as a commercial product. Items marked ✔ were
implemented in PR-041; the rest are documented for future sprints.

## Top 20 UX improvements

1. ✔ Enterprise-first language: global scope label "All Networks" → **Enterprise**; selector label "Network" → "Scope".
2. ✔ Compass interface dropdown filters by selected device (was: every interface of every device).
3. ✔ Teaching empty states for History, Changes, and Incidents (what the capability is + quick actions).
4. ✔ Back links on detail pages (Device Details → Enterprise inventory; Plan Viewer → All plans).
5. ✔ Incidents at Enterprise scope points to Path Intelligence instead of reading like a dead end.
6. ✔ Visible keyboard focus everywhere (`:focus-visible`), skip-to-content link, `aria-current` nav, live-region search status.
7. ✔ Table row hover affordance for dense inventories.
8. Searchable combobox (type-ahead) for device selects on Predict/Paths/Compass — native selects today.
9. Site filter on the enterprise inventory should persist into Predict/Paths as an optional narrowing chip.
10. Interface labels in Compass could show the same rich context badges as Predict (added: same labels now; badges could go further with role hints).
11. Breadcrumbs on artifact pages (raw report views open bare markdown).
12. Toast-style flash messages (current flashes push content down).
13. Relative timestamps ("2 h ago") alongside ISO times, everywhere.
14. Dark theme.
15. Pagination/virtualization for very large inventory tables.
16. Compass plan timeline could show cumulative estimated time per step.
17. Prediction page: persist a small history of past predictions (only the latest is kept per scope).
18. Mission: allow dismissing/acknowledging a recommendation for the day.
19. Path investigation timeline could deep-link each hop to Device Details.
20. Topology viewer: legend for vendor colors and cross-profile links.

## Top 10 future enhancements

1. Investigation lifecycle (open/in-progress/closed + notes) — Mission becomes a work queue.
2. Configuration-derived role evidence (PR-036D) feeding prediction planes, Compass models, VRF/route search.
3. Routing evidence (`show ip route`) to resolve FLOW's equal-cost ambiguity.
4. Compass execution tracking + post-window outcome verification.
5. Cross-profile boundary corroboration (chassis-id/serial in CDP detail) to close WAN gaps.
6. Scheduled discoveries with freshness SLAs.
7. REST API surface over the existing services.
8. CAB-ready export bundles (plan + predictions + rollback notes).
9. Multi-vendor parser packs (Juniper/Arista) behind the same evidence contracts.
10. Atlas Assistant: natural language over search/FLOW/prediction/Compass — explains, never decides.

## Top 10 technical debt items

1. `web/routes.py` has grown past 1,200 lines — split into blueprint modules (mission, compass, search, enterprise).
2. Enterprise graph build is O(n²) cluster matching — fine at lab scale, needs an index for 10k devices.
3. ✔ (partial) Enterprise graph was rebuilt per request — now fingerprint-cached; artifact writes only on change.
4. `_read_json` is re-implemented in four modules — extract a shared `founderos_atlas.io` helper.
5. Freshness constants (24 h) exist in three places (federation, prediction, path) — single source.
6. GUI tests re-discover fixture worlds repeatedly (~55 s of suite time is world building) — session-scoped fixture caching would halve the suite.
7. No JS test runner: keyboard/modal behavior is pinned at source level plus manual browser checks — evaluate a lightweight DOM test harness.
8. Scope selector list rebuilds `known_scopes()` (disk stats) on every request.
9. `atlas.js` is one IIFE approaching 500 lines — split by feature when a bundler-free module pattern is agreed.
10. History records and path investigations grow unbounded (caps exist per file but not per scope-lifetime) — retention policy needed.

## Product readiness assessment

**Coherent**: one graph, one vocabulary (enterprise / site / observation
/ profile / investigation / prediction / maintenance plan), one design
language, workflows over modules. **Trustworthy**: every number is
auditable, every merge explainable, unknowns are first-class.
**Demo-ready**: the 7-step guided demo (docs/DEMO.md) lands the core
value in under 10 minutes on the two-lab CML topology. Gaps that would
show in a hostile Fortune-500 eval: single-vendor parsing, no RBAC/auth
(local-only alpha by design), no REST surface, and the items above.
