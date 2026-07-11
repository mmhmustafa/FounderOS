# Atlas Architecture

Atlas is an Enterprise Network Decision Platform built on the FounderOS
runtime. It evolves through five deliberate stages:

    Observe  ->  Understand  ->  Reason  ->  Predict  ->  Advise

Every stage is **deterministic**: rule-based engines over collected
evidence. No AI or LLM participates in observation, reasoning, or
prediction; a future AI layer will only *explain* — consuming the JSON
contracts the engines already emit (summary, evidence, risk, confidence,
recommendations).

## Engine stack (Observe -> Understand -> Reason)

| Stage | Engine | Package | Output |
|---|---|---|---|
| Observe | Discovery (multi-hop, boundaries, multi-credential) | `discovery/`, `credentials/`, `transport/` | topology snapshots, configs, per-run history |
| Observe | Canonical identity & enterprise topology | `identity/`, `enterprise/` | one canonical device set with provenance |
| Understand | Change intelligence (topology / config / operational) | `change/`, `config_intelligence/`, `state/` | classified diffs per profile scope |
| Understand | Site inference | `sites/` | evidence-based site assignments (may be Unknown) |
| Understand | Enterprise intelligence | `enterprise_intelligence/` | explained health score, risks, priorities, trends |
| Reason | Root cause analysis | `root_cause/` | evidence-cited explanations of *why* |
| **Predict** | **Predictive change intelligence** | `prediction/` | deterministic answers to *what happens if* |

Shared invariants: per-profile scope isolation (PR-031A), explainable
scores (every point is a named factor), banded confidence capped below
100%, honest unknowns, byte-identical output for identical evidence, and
zero secrets in any artifact.

## Prediction Architecture (PR-036A)

### Pipeline

    Change Request
        v  dependency resolution        (dependency.py)
        v  critical path evaluation     (critical_paths.py)
        v  redundancy evaluation        (redundancy.py)
        v  impact estimation            (impact.py — blast radius)
        v  risk estimation              (simulator.py)
        v  confidence calculation       (confidence.py)
        v  recommendations              (recommendations.py)
    Prediction (models.py — plain JSON, AI-consumable later)

The pipeline lives in `simulator.predict()` and is *closed for
modification, open for extension*: per-change-type **evaluators** are
registered (`register_evaluator`), and a change type without an evaluator
still predicts honestly — explicit unknowns, low confidence — instead of
failing or guessing.

### Change Request model

`ChangeRequest(request_id, change_type, target_device, target_object,
parameters)` — `change_type` is an open registry (`change_requests.py`)
seeded with shutdown-interface, remove-vlan, delete-route, modify-acl,
disable-protocol, reboot-device, upgrade-firmware. New types (disable-hsrp,
modify-security-group, restart-kubernetes-cni, ...) register at runtime
with zero model changes. `Boundary` scopes the evaluation (profiles,
sites, devices; empty = whole enterprise).

### Dependency model

`DependencyGraph` of typed nodes and directed edges across the layers

    device -> interface -> protocol -> topology -> service -> application -> users

Node *kinds are open strings* — VLAN, VRF, OSPF, HSRP, STP, LACP,
firewall, application, Kubernetes CNI, cloud resources all become nodes
without a schema change. Links are modeled through **both interface
endpoints**, so shutting either end breaks the path. The first builder
(`build_topology_dependency_graph`) populates device/interface/link layers
from the topology snapshot; future builders (config parsers, service maps,
cloud inventories) only *add* nodes and edges, and impact/redundancy
automatically get richer (tested).

### Blast Radius model

Not a number: affected devices, interfaces, protocols, paths, services,
applications, sites, and a user estimate, plus severity and summary.
Semantics are **reachability-based** — a node of any kind is affected when
it *loses connectivity* once the changed element is removed, not merely
when it is adjacent. Layers Atlas cannot see are declared in the
prediction's `unknowns`, never silently zeroed.

### Critical Path & Redundancy models

`CriticalPath(hops, dependencies, redundancy, criticality)` — the first
identifier reports device pairs whose connectivity **breaks** without the
changed node. `RedundancyAssessment(redundant, alternate_path_exists,
detail, confidence_band)` answers "does an alternate path exist?" from
topology reachability today; routing tables, HSRP/LACP awareness, and
WAN/SD-WAN policies refine it later behind the same model.

### Rollback model

`RollbackEstimate(complexity, reversible, prerequisites, dependencies,
estimated_effort, confidence)` — rule-based per change type: an interface
shutdown reverses with one command; deleting a route is low-complexity
*only when* the configuration was captured first (Atlas says so as a
prerequisite); reboots and firmware upgrades are honestly irreversible.

### Confidence model

Documented arithmetic (`confidence.py`): base 0.50 + topology evidence
+ freshness + captured configuration + history + modeled change type
− unknown dependency layers − contradictions, clamped to **0.95 — never
100%** — and banded with the same very-high/high/medium/low vocabulary the
root-cause engine uses (reused, not duplicated).

### Relationship to existing engines

The simulator consumes what already exists — topology snapshots,
history records, configuration presence, enterprise intelligence — as
inputs; it re-implements none of it. Predictions serialize to plain JSON
like every other Atlas artifact.

### Implemented vertical slice (PR-036B)

Interface-shutdown prediction is fully implemented end to end:

- `ChangeRequest` carries change-management context (reason, maintenance
  window, requester);
- **risk engine** (`prediction/risk.py`): Low/Medium/High/Critical from
  documented, auditable factors — broken forwarding paths (+25), devices
  losing connectivity (+5 each, cap +15), production links (+5), unknown
  redundancy (+10 — never assumed), verified redundancy (−10), degraded
  enterprise health (+5/+10), historical target instability (+10), low
  prediction confidence (+5); levels at 15/30/50;
- **advice ladder** (`prediction/recommendations.py`): critical or broken
  paths → *High Risk — CAB approval recommended*; high with unknown
  redundancy → *Investigate redundancy first*; medium or touching
  production links → *Proceed during a maintenance window*; missing target
  → *Run a fresh discovery first*; else *Proceed* — always with reasons;
- **explanation**: every prediction narrates its reasoning, cites the
  evidence artifacts, projects the enterprise-health impact using the
  intelligence weights, and states what Atlas cannot see;
- **service API** (`prediction/service.py`): `predict_change()` gathers a
  scope's real evidence (snapshot, history freshness, target instability,
  captured configuration, intelligence health, site catalog) and renders
  CAB-ready JSON/markdown reports;
- **GUI**: the Predict page (device picker from the scope's topology,
  optional reason/window/requester) and a Latest Prediction dashboard
  panel; reports stored per scope (`prediction_report.json`/`.md`).

Current limitations (honest by design): only `shutdown-interface` (and
`reboot-device` at architecture level) is modeled; redundancy is
topology-layer only (routing/HSRP/LACP unknown → stated as unknown);
services/applications/users appear in blast radii only when future
builders add them; predictions are on-demand and not archived in history.

### Plane-aware logical-interface prediction (PR-036C)

Real CML testing exposed a model gap: shutting SW1's `Vlan1` SVI (owner of
`10.10.10.2`, the address Atlas connects through) predicted *zero* impact
because only physical adjacency was modeled. PR-036C adds plane-aware
impact (`prediction/planes.py`):

- **Interface semantics** — canonical-name classification (physical / SVI
  / loopback / tunnel / port-channel / subinterface / unknown); logical
  interfaces are never treated as ordinary unused ports.
- **Management plane** — deterministic reachability: does the target
  interface own the device's active management address (the address Atlas
  discovered it through) or a profile seed? Alternate paths are *verified*
  only when the candidate address is itself a proven connection address;
  a merely-existing second address is a candidate, never assumed.
- **Control plane** — protocol impact only from explicit role evidence
  (the `role_evidence` extension point for future collectors); no
  evidence → no known impact, with the missing evidence listed.
- **Data plane** — gateway impact only with gateway role evidence;
  otherwise honestly unknown, while noting that discovered physical links
  remain up (Layer-2 switching continues).
- **Observability plane** — follows management: a lost management address
  is a monitoring blind spot (future discovery, collection, alerting).

Each plane carries status (no_known_impact / degraded / lost / unknown),
severity, **its own confidence**, affected objects, supporting and missing
evidence, and an explanation. Risk gains management/gateway/control
factors (management loss +25 covering the single shared dependency —
SSH/discovery/collection/monitoring — never double-counted; unverified
alternate +10; verified alternate −10; the unknown-forwarding-redundancy
factor now applies only when the change actually touches forwarding).
The advice ladder gains a top rule: management lost without a verified
alternate → **"Do not proceed until an alternate management path is
verified"** — you must be able to reach the device to roll back at all.

### Future roadmap (later PRs; no redesign required)

1. Configuration-aware evaluators (VLAN/route/ACL simulation from parsed
   configs) — new graph builders + evaluators.
2. Routing & gateway protocol awareness (OSPF/BGP/HSRP nodes; redundancy
   beyond physical topology).
3. Service/application dependency ingestion — richer blast radii and
   user-impact estimates.
4. Change-request intake in the GUI with prediction reports per CAB
   review; prediction artifacts archived like every other report.
5. WAN/SD-WAN, firewall policy, cloud and Kubernetes builders — all new
   node kinds and evaluators on the same graph and pipeline.
6. AI explanation layer over the Prediction JSON (explain, never decide).
