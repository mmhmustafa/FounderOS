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
| **Reason** | **Path intelligence** | `path_intelligence/` | deterministic answers to *why can't A reach B* |
| **Federate** | **Enterprise federation** | `federation/` | one canonical enterprise graph from many observation points |

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

## Enterprise Federation (PR-037A, codename UNITY)

Discovery profiles are observation points, never enterprise boundaries.
Discovery keeps running per profile into fully isolated scopes;
federation happens AFTER discovery, reading each profile's latest
artifacts and assembling ONE canonical Enterprise Graph.

### Pipeline

```
profile scopes (isolated, untouched)
  → gather_scope_contributions (one observation set per profile:
    snapshot + run id + timestamp + site/domain hints)
  → PR-033 canonical identity engine (REUSED, not duplicated):
      serial numbers always merge · hostname+IP merges only within a
      declared administrative domain · hostname alone / IP alone NEVER
  → federation layer adds:
      canonical interfaces (union per device, newest state wins
        deterministically, observers listed)
      canonical links (edges resolved onto canonical devices — a far-end
        NAME resolves only within the observing profile; cross-profile
        connectivity arises only through devices merged on strong
        evidence — connectivity is never invented)
      merge decisions (the WHY + documented confidence per device)
      unknown boundaries (announced-but-undiscovered neighbors stay
        visible as boundary links, never inventory)
  → enterprise TopologySnapshot (same content-addressed contract as
    every per-profile snapshot) → every existing engine — prediction,
    path intelligence, the interactive topology viewer, device pickers —
    operates at enterprise scope UNCHANGED
```

### Models

`EnterpriseGraph` (devices = PR-033 `EnterpriseDevice` with untouched
per-observation provenance; `CanonicalInterface`; `CanonicalLink` with
`LinkObservation` provenance and cross-profile/boundary flags;
`MergeDecision`; `ContributionSummary` with freshness). Confidence
arithmetic is documented: serial merge 95%, corroborated hostname+IP
merge 75%, single observation with serial 90%, without 60% — capped
below 100% like everything else.

### Provenance

Every canonical object references the observations that produced it:
profile, run id, timestamp, observed hostname and management address;
links record which profile saw them in which run; interfaces list their
observers; credential information is a reference, never a secret.
Distinct never-merged devices are guaranteed distinct enterprise ids.

### Enterprise scope (All Networks)

All Networks is no longer a read-only aggregation: the dashboard gains
an Enterprise Summary (canonical/observation/merge counts, contributing
profiles with freshness, boundaries); Topology renders ONE federated
interactive viewer plus the canonical inventory with merge reasons and
provenance on demand; Predict and Paths run against the enterprise
snapshot (blast radii and investigations cross profiles wherever strong
evidence connects them), with freshness and configuration evidence
derived from every contributing profile. Incomplete evidence lowers
confidence and is displayed — it never auto-refuses. Enterprise
artifacts live in `.atlas/enterprise/` and are regenerated
deterministically from profile evidence — a view, never a second source
of truth.

### Services

`get_enterprise_graph()` · `get_enterprise_inventory()` ·
`resolve_canonical_device()` (unique match or honest ambiguity) ·
`search_enterprise()` · `merge_observations()` ·
`build_enterprise_snapshot()` · `write_enterprise_artifacts()` — shared
by GUI, CLI, future REST APIs, and the assistant.

## Path Intelligence (PR-037, codename FLOW)

The first vertical slice of end-to-end connectivity investigation:
given a source and a destination device, `investigate_path()`
(`path_intelligence/`) answers *where does communication stop, and why*
— from evidence alone. No packet simulation, no traceroute, no AI.

### Pipeline

```
Source + Destination
  → resolve devices (hostname or management address; Unknown reported)
  → construct path from discovered adjacency (CDP/LLDP edges in the
    current snapshot; BFS over sorted neighbors; equal-cost alternatives
    are enumerated and reported as AMBIGUOUS, never guessed through)
  → validate every hop in order:
      device exists → management reachability (last run's failures)
      → ingress/egress interfaces exist in collected inventory
      → operational state (up / down / administratively down)
  → stop at the FIRST deterministic failure; later hops are marked
    "not evaluated", never assumed healthy
  → narrate the investigation story (numbered steps with evidence)
  → recommend evidence-based next actions per failure type
```

### Models

`PathInvestigationResult` (status connected/failed/ambiguous/unknown,
path, hops, steps, failure type + summary, recommendations, banded
confidence, unknowns, evidence refs, basis) → `HopResult` (per-hop
status pass/warning/failed/unknown, ingress/egress interface, link
state, management state, per-hop confidence, cited evidence, missing
evidence) → `InvestigationStep` (the narrated story). Everything
serializes to plain JSON; the same structure feeds the GUI, CLI,
future REST APIs, and the assistant.

### Failure vocabulary (deterministic; protocol failures are never invented)

interface-down · administrative-shutdown · missing-topology-edge ·
device-unreachable · discovery-incomplete · unknown-path ·
unknown-device · unknown-destination · ambiguous-topology.

### Evidence & confidence

Hops validated against direct snapshot state carry ~90% confidence;
hops with missing evidence (device known only from neighbor
announcements, interfaces absent from the collected table) drop to ~50%
and surface the gap as a warning plus an unknown; stale snapshots cost
a documented penalty; the overall confidence is the minimum over the
evaluated hops, capped at 95%. `investigate_path_for_scope()` runs
against a scope's real artifacts (snapshot, history freshness, last
run's failed hosts, captured configurations) and appends the complete
result to `path_investigations.json` (newest first, capped) so any
past investigation can be replayed exactly.

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
