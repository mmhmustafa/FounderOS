# Atlas Roadmap

## Shipped — Platform v1 (PR-001 → PR-041)

| Capability | PRs |
|---|---|
| Multi-hop discovery, profiles, isolated scopes, history | 001–031A |
| GUI discovery jobs, enterprise seeds/boundaries/credentials, sites | 032–033 |
| Enterprise intelligence (explained health), root cause analysis | 034–035 |
| Predictive change intelligence (impact, planes, device-aware GUI) | 036A–C |
| Path Intelligence (FLOW) — hop-by-hop investigations | 037 |
| Enterprise Federation (UNITY) — one canonical graph, provenance | 037A |
| Universal Search (Ctrl+K) with deterministic ranking | 038, 038.1 |
| Compass — deterministic multi-change planning | 039 |
| Mission — the workflow workspace | 040 |
| Product polish: enterprise-first UX, a11y, perf, docs | 041 |

## Next (candidate order)

1. **Investigation Lifecycle** — open/in-progress/closed states with
   engineer notes so Mission's investigations card becomes a real work
   queue; incidents link to their path investigations and RCA.
2. **Configuration-derived role evidence (PR-036D)** — parse captured
   configs for gateway/HSRP/OSPF/ACL/VLAN statements to feed prediction
   planes, Compass impact models, and VRF/route search.
3. **Routing evidence for FLOW** — `show ip route` collection to resolve
   equal-cost path ambiguity and validate L3 next-hops.
4. **Compass execution tracking** — mark steps done mid-window,
   re-analyse, and verify outcomes against the next discovery.
5. **Boundary corroboration** — match boundary announcements across
   profiles (chassis id / serial via CDP detail) to close WAN gaps.
6. **CAB-ready exports** — plan/prediction/investigation reports as
   shareable markdown/PDF bundles.
7. **REST API surface** — the existing services behind versioned
   endpoints for integration.
8. **Atlas Assistant** — natural-language front end that *reuses*
   search, FLOW, prediction, and Compass services; explains, never
   decides.

## Later

Scheduled discoveries · alerting on state changes · multi-vendor
parser packs · application/service dependency ingestion · cloud and
Kubernetes builders on the same graph · site subnet/management-domain
modeling · mobile-friendly Mission.
