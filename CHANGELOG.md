# Changelog

## Unreleased

### EPIC-002 / PR-040.1 - Mission UX Alignment (MISSION REFINEMENT)

- **Product-design sprint, zero backend change**: Mission no longer reads as "Dashboard v2". The page now flows Status → **"What would you like to do?"** → **Continue Working** → Today's Recommendations → Enterprise Health → **Recent Activity** — actions first, metrics demoted to supporting decisions (pinned by a test asserting the DOM order).
- **Continue Working replaces the engine cards**: the dominating Latest Predictions card and the separate plans/investigations/changes/discoveries columns are folded into one resume list — Resume Investigation, Resume Plan, Review Prediction — because Mission is about workflows, not engines. Its empty state teaches with concrete starting points (routing issue, VLAN problem, device unreachable, change tonight).
- **One operational timeline**: `build_activity_stream` (pure view-model shaping in `web/mission.py`) merges discoveries, investigations, predictions, maintenance-plan edits, and detected changes into a single newest-first Recent Activity stream with kind chips and resume links.
- **Dashboard terminology disappears**: the scoped page is now **Mission — <profile>** too, opening with its status strip and the same five workflow launchers (scoped targets) before its metric panels — which are all preserved (Latest Prediction, risks/recommendations, changes, discoveries). Action verbs aligned: Run Discovery, Review Changes, Search Enterprise.
- Visual refinement: slim status strip, activity-kind chips, inline recent-searches/devices chips (still browser-local only), fewer cards (9 → 5 on a healthy enterprise page) — calm over dashboard overload. Expert tools remain one click away in the sidebar (pinned by test).
- Tests: `tests/test_mission.py` updated to the new structure and grown to 19 (actions-before-metrics DOM order; the five workflow launchers with "Dashboard" asserted absent; Continue Working resume flows for investigations/plans/predictions with their timeline entries; teaching empty state with all four examples; scoped Mission keeps metrics and gains workflows; expert sidebar preserved); one wording assertion in `test_web_app.py` follows the new heading. Verified live in a browser: section order, all five launchers, search-from-card open/Escape-close, no "Dashboard" text anywhere.

### EPIC-002 / PR-041 - Atlas Product Readiness (POLISH)

- **No new engines — a refinement sprint** treating every page as a Fortune-500 demo. Backward compatible throughout: scope ids, URLs, sessions, and artifacts are unchanged.
- **Enterprise-first language**: the global scope's label is now **"Enterprise"** (`GLOBAL_SCOPE_LABEL`; the id stays `all` for stable URLs/sessions), the topbar selector reads **"Scope"**, page titles follow (Mission — Enterprise, Topology — Enterprise), search subtitles label enterprise-scope reports "Enterprise", and remaining "select a network" phrasing became scope-based. Two test assertions updated to the new label (documented in-line).
- **Forms**: the Compass interface dropdown is now **device-aware** — the generalized `bindInterfaceFilter` (shared with Predict, one implementation) filters interfaces to the selected device, keeps the explicit "none / device-level" option, and shows the same rich context labels as Predict. Server-side validation unchanged.
- **Teaching empty states**: History, Changes, and Incidents now explain what the capability is and offer quick actions instead of a bare "nothing yet" line; the Incidents page at Enterprise scope points to Path Intelligence for enterprise-wide questions instead of reading like a dead end.
- **Navigation**: back links on detail pages (Device Details → Enterprise inventory; Plan Viewer → All maintenance plans); no dead ends at enterprise scope.
- **Accessibility**: skip-to-content link, visible `:focus-visible` outlines on every interactive element, `aria-current="page"` on the active nav item, `aria-live="polite"` on the search status (result counts are announced), a descriptive scope-selector label, and table row hover affordance.
- **Performance**: the enterprise graph is now **cached per evidence fingerprint** (`enterprise_evidence_fingerprint` — profile snapshots + run history + workspace state, deliberately excluding the derived `.atlas/enterprise/` artifacts so the cache never invalidates itself). Enterprise pages stop rebuilding the graph and rewriting artifacts on every request; freshness flags are still re-evaluated against the current clock on cache hits, and any discovery/workspace change rebuilds.
- **Documentation set**: VISION.md gains the Atlas Platform v1 vision (the FounderOS vision preserved); new ENGINEERING_PRINCIPLES.md (the 12 rules every PR has followed), ROADMAP.md (shipped v1 table + ordered next milestones), DECISION_LOG.md (21 key decisions with their WHY and PR), docs/DEMO.md (the 5–10 minute guided two-lab demo), and docs/PRODUCT_AUDIT.md (top 20 UX improvements — 7 shipped in this PR, top 10 future enhancements, top 10 technical debt items, and a product readiness assessment). ARCHITECTURE.md links the set.
- Added 10 tests (`tests/test_polish.py`): the Enterprise label with stable scope id; enterprise wording on selector/titles with "All Networks" absent; search subtitles; back links on both detail pages; the incidents no-dead-end teaching state; empty states for history/changes/incidents; device-aware Compass interface filtering (markup + shared JS binding, Predict unchanged); skip link/focus-visible/aria-current/aria-live; the enterprise-graph cache (byte-stable artifacts across repeated requests, rebuild on new discovery); no secrets on cached pages.

### EPIC-002 / PR-040 - Atlas Mission Workspace (MISSION)

- **All Networks now lands on MISSION** — the workflow-oriented operational workspace. Engineers think in goals, not modules: the page opens with *"What are you trying to do?"* and six workflow launchers (🔍 Investigate an Issue → Path Intelligence, 🛠 Plan a Change → Compass, 🌐 Discover Infrastructure → Discovery, 📈 Review Overnight Changes → Changes, 🔎 Search the Enterprise → the existing Ctrl+K overlay, 📚 Review Previous Investigations → stored investigations). MISSION orchestrates; the engines execute — **no engine logic moved**, every card reads artifacts the engines already produced, and the engines remain authoritative.
- **Enterprise Health card**: status banner, network/device tiles plus the canonical federation tiles, per-profile freshness with evidence age ("3 day(s) old"), and the per-network table with Open links to the unchanged scoped dashboards.
- **Today's Recommendations — deterministic, evidence-cited** (`web/mission.py`): each recommendation exists only because evidence produced it — no discovery yet → run one; a discovery run recorded failures (run id cited); a contribution is stale (age cited); N plans sit unanalysed → open Compass; a network reports active operational issues; the latest prediction has medium/low confidence → review its evidence. A fresh, analysed, issue-free world honestly shows "nothing needs your attention".
- **Integration cards, all resume-able**: Pending Maintenance Plans (window, change count, risk badge, Open Plan), Recent Investigations (source → destination, status badge, Continue), Latest Predictions (subject, risk, confidence band, Review), Recent Changes (counts + active-issue warnings), Recent Discoveries, and Quick Actions (Run Discovery, New Investigation, New Maintenance Plan, Search, Open Topology, Review Predictions, Open Compass).
- **Context awareness without server-side persistence**: the active scope stays in the session (existing behavior); recent searches and recently viewed devices render from browser localStorage only — clicking a recent search reopens the Ctrl+K overlay pre-filled; visiting a Device Details page records it locally for the Recent Devices list. Nothing sensitive is persisted.
- **Search embedded, never duplicated**: any `.js-open-search` element opens the single existing overlay; MISSION adds zero search markup of its own.
- Backward compatible: scoped dashboards (`/?scope=<profile>`) are byte-for-byte the same experience; the superseded `dashboard_global.html` template is retired; two existing tests were updated to the new landing contract (the web-shell smoke test and the federation dashboard test, both documented in-line).
- Added 18 tests (`tests/test_mission.py`): the pure recommendation builder (no-data onboarding, stale-with-age, failures/drafts/issues/low-confidence each citing evidence in deterministic order, healthy-world silence, age wording); MISSION as the All Networks landing page with all six workflows; enterprise health/freshness/recent discoveries; every workflow target responding; stale-evidence and draft-plan recommendations rendered with evidence; discovery-failure recommendation from a real failed run; Compass plans with risk and Open Plan; investigations appearing and resuming; predictions + changes cards (including the active-issue recommendation); search embedded once with local-only recent activity; scope-selection persistence; scoped dashboards unchanged; honest empty-world onboarding; quick actions — no secrets anywhere.

### EPIC-002 / PR-039 - Compass (deterministic change planning)

- Atlas now plans **many changes**, not just one. New `founderos_atlas/compass/` domain: a `ChangePlan` (title, maintenance window, engineer, optional CAB reference, enterprise scope, status, timestamps) holds `PlannedChange`s (device, optional interface, change type, reason, estimated duration, rollback availability — honestly tri-state, notes). Compass is an ADVISOR, never an approval workflow: conflicts warn, nothing blocks, the engineer stays in control.
- **Change vocabulary** (future types plug in with one entry): shutdown-interface, enable-interface (bring up), configuration-change, ios-upgrade, acl-change, vlan-change, static-route-change — each mapped onto the prediction engine's open registry. An IOS upgrade is predicted through the modeled reload semantics (an upgrade deterministically includes a reload — evidence, not invention); unmodeled types predict honestly with low confidence and their unknown dependencies are stated ("unknown, not absent").
- **Per-change analysis reuses the prediction engine** — risk level/score, blast radius, confidence, health impact, rollback reversibility, unknowns, evidence — no duplicated impact logic anywhere.
- **Dependencies from cited evidence only**: (1) change B's device inside change A's predicted blast radius ⇒ B runs before A — you cannot configure a device you just cut off (evidence: the prediction's blast radius); (2) work on a device precedes that device's IOS upgrade/reload (evidence: the reload). Nothing else is inferred. Circular dependencies (mutual isolations) are reported honestly — "Atlas cannot determine a provably safe order" — then broken deterministically so a full order still exists.
- **Recommended execution order**: deterministic topological sort; among runnable steps the lowest predicted risk runs first; a blast radius spanning ≥ half the visible enterprise is scheduled last and flagged **"separate window"**. Every step displays order, WHY (independent / runs-after with dependency reasons / scheduled-early because later steps depend on it / separate-window), risk, banded confidence, and cited evidence.
- **Conflict detection (warn, never block)**: duplicate change, mutually exclusive shutdown+enable on one interface, two different changes touching one interface, multiple IOS upgrades of one device.
- **Risk summary**: overall plan risk, highest-risk step, largest blast radius, total devices impacted (targets ∪ blast radii), rollback coverage (covered / unavailable / honestly unknown), and total estimated duration (honestly unknown when any change omits an estimate).
- **Enterprise-scope by design**: analysis runs against the UNITY enterprise snapshot with per-profile freshness and seed evidence — cross-profile dependencies emerge naturally (upgrading the shared gateway orders the other lab's work first). Plans persist in `.atlas/compass/plans.json` (gitignored) with their latest assessments.
- **GUI**: new **Compass** nav page — plan list with status/risk badges and a New Plan form; a Plan Viewer with the planned-changes table (rollback visibility per change), an add-change form (device/interface validated server-side against enterprise evidence, canonical names enforced), Analyse button, Risk Summary tiles, the color-coded Recommended Execution Order timeline (expandable WHY + evidence per step, separate-window badges), Conflicts panel, Dependencies panel with evidence, and the What-Atlas-Cannot-See panel.
- **Search integration**: plans are a new search group — findable by title, CAB reference (canonical rank), engineer, and every device inside the plan; the index fingerprint watches `plans.json` so new plans surface immediately.
- **Reusable services**: `create_plan()`, `add_change()`/`remove_change()`, `analyse_plan()`, `recommend_order()`, `detect_dependencies()`, `detect_conflicts()`, `estimate_plan_risk()`, `analyse_plan_for_workspace()`, `PlanRepository` — shared by GUI, CLI, and future REST/assistant clients.
- Added 28 tests (`tests/test_compass.py`): model round-trips and invalid-type rejection; single-change analysis via prediction with capped confidence; IOS-upgrade reload semantics (irreversible, real blast radius); safest-first ordering of independent changes; the ACL-before-shutdown blast-radius dependency with cited evidence and step WHYs; same-device-before-upgrade; largest-blast-last with the separate-window flag; honest circular-dependency reporting with a still-complete order; byte-identical determinism; unmodeled-type honesty; no-evidence-no-dependencies; stale-evidence disclosure; all four conflict kinds warning without blocking; risk-summary totals including tri-state rollback coverage and honestly-unknown durations; plan persistence (unique ids, draft/analysed status, updated_at); workspace analysis over the two-lab enterprise with a cross-profile dependency; search integration (title/CAB/engineer/device with automatic rebuild); and the full GUI flow (create → add validated changes → analyse → order/risk/conflicts/unknowns rendered, GHOST device and bad interface rejected, no secrets).

### EPIC-002 / PR-038 - Atlas Universal Search (SEARCH)

- **Ctrl+K anywhere**: a persistent topbar search opens an overlay that searches the whole enterprise while typing — new `founderos_atlas/search/` domain operating on the UNITY Enterprise Graph. Deterministic end to end: entries exist only because evidence produced them, ranking never uses fuzzy AI, identical evidence yields identical results, and search never invents objects.
- **Searchable evidence**: canonical devices (hostname, aliases, management IPs, serial numbers, enterprise ids, platform, OS, site), interfaces — including deterministic short aliases (`Gi0/1` finds `GigabitEthernet0/1`) and **SVI-derived VLAN ids** (`VLAN20` finds the discovered `Vlan20`; the only VLAN evidence Atlas collects today) — sites, topology links (cross-profile/boundary flagged), profiles (names, ids, seeds), credential set **names only** (no usernames, no secrets — asserted), the latest predictions, path-investigation history, change summaries, and discovery runs per scope **including the enterprise scope's own reports**.
- **Deterministic ranking** (spec order): exact on the primary name → exact on a canonical identifier (enterprise id, serial, alias, run id) → prefix → partial; historical objects rank +10 after live ones; ties break on group order/title/subtitle. Every hit names the matching field and rank label — the WHY of the result. Results are grouped (Devices, Interfaces, Sites, Topology, Predictions, Investigations, Changes, Profiles, Credentials, History) with full counts even when display-limited.
- **Lightweight index, automatic rebuilds, no Elasticsearch**: a flat in-memory entry tuple built in two pure layers (`entries_from_graph`, `entries_from_workspace`); `SearchService` caches it behind a deterministic fingerprint over the evidence files (scope artifacts, history run lists, workspace state, enterprise scope) — after discovery, federation, prediction, investigation, or change updates the fingerprint differs and the next search rebuilds. No daemon, no background thread.
- **Experience**: search-as-you-type (150 ms debounce), grouped results with counts, highlighted matches, `↑`/`↓`/`Enter`/`Escape` keyboard navigation, recent searches (client-side localStorage only), loading state, and an honest empty state ("Atlas never invents results"). Device results show management IP, platform, site, health (the owning network's score when unambiguous), last seen, observation count, and enterprise identity confidence; interface results show device, status, description, and neighbor.
- **Device Details page** (`/devices/<enterprise_id>`): a search hit opens the canonical device — identity, merge evidence and identity confidence, every observation with provenance, the interface table with neighbors, links (cross-profile/boundary badged), and action shortcuts. Unknown ids get an honest 404.
- **Reusable service**: `GET /api/search?q=` serves the same grouped JSON the GUI renders; `search_enterprise()`, `search_devices()`, `search_interfaces()`, `search_predictions()`, `build_search_index()`, `SearchService` are importable for CLI, REST, and the future Atlas Assistant.
- **Modal lifecycle fix (post-manual-test correction)**: the search overlay rendered OPEN on every page load and could not be closed — root cause: `.search-overlay { display: flex }` (author CSS) silently overrode the user-agent's `[hidden] { display: none }` rule, so the `hidden` attribute the markup and JS managed correctly never took visual effect; every close handler ran invisibly and Ctrl+K appeared to "expand" a permanently painted panel. Fixed with an explicit hidden state (`.search-overlay[hidden] { display: none; }`) plus lifecycle hardening: `aria-hidden` mirrored on open/close, `aria-modal` dialog semantics, focus captured on open and restored to the opener on close, Escape closes from inside the input (taking precedence over result navigation and the browser's native search-input clear), Ctrl+K/Meta+K cleanly toggle with the browser default prevented, and reopening preserves the last query with its text selected (documented UX choice: results persist for quick resume and are replaced on the next keystroke). One overlay, one backdrop, one initialization per page — verified live in a real browser (open/close/toggle/backdrop/focus/navigation on multiple pages) and pinned by 8 new lifecycle tests.
- Added 31 tests (`tests/test_search.py`; 23 feature + 8 modal-lifecycle): exact/prefix/partial hostname ranking order; management-IP, serial (canonical rank), enterprise-id, and platform matches; interface results with device/status/neighbor; VLAN via discovered SVI; site grouping; honest empty results; group counts vs display limits; byte-identical determinism; profiles/history/"recent" searches over a real discovered workspace; live-before-historical ordering; **automatic index rebuild on evidence change (cached instance reused until the fingerprint moves)**; credentials indexed by name only with usernames and secrets asserted absent; 500-device enterprise build/search performance bounds; and the GUI slice — search markup + keyboard wiring on every page, grouped deterministic `/api/search` responses (merged GW at 95% identity confidence), IP/interface/empty API queries, Device Details from a search hit with provenance, honest 404, and predictions appearing in search immediately after a run without restart.

### EPIC-002 / PR-037A - Enterprise Federation (UNITY)

- Atlas now reasons about **one enterprise observed from many discovery points**. New `founderos_atlas/federation/` domain builds a canonical Enterprise Graph from every profile's latest isolated evidence — AFTER discovery, without touching profile scopes, and **reusing the PR-033 identity engine** (serial numbers always merge; hostname+IP merges only within a declared administrative domain; a hostname alone or an IP alone never merges). Discovery itself is unchanged.
- **Observations are never destroyed**: every canonical device references its observations (profile, run id, timestamp, observed hostname and management address); canonical interfaces are the union per device with the newest observation winning state conflicts deterministically and every observer listed; canonical links carry per-run `LinkObservation` provenance.
- **Every merge is explainable**: each canonical device gets a `MergeDecision` stating the WHY ("every observation reports the same serial number — strong evidence of one physical device") with documented confidence — serial merge 95%, corroborated hostname+IP merge 75%, single observation with/without a strong identifier 90%/60% — capped below 100%. Distinct never-merged devices are guaranteed distinct enterprise ids (same-hostname+IP twins no longer risk an id collision).
- **Connectivity is never invented**: an edge's far-end NAME resolves only within the observing profile's own snapshot; cross-profile links arise naturally only through devices merged on strong evidence (the shared WAN gateway both labs discovered). Announced-but-undiscovered neighbors become **visible unknown boundaries**, never inventory.
- **Enterprise snapshot**: the graph renders as a content-addressed `TopologySnapshot` (the same contract as every per-profile snapshot, via the newly public `topology.content_address`), so **every existing engine — prediction, path intelligence, the interactive topology viewer, device pickers — operates at enterprise scope unchanged**. Enterprise ids ride as device ids; provenance rides in metadata.
- **All Networks becomes the enterprise scope** (restrictions replaced, not refused): the dashboard gains an Enterprise Summary (canonical devices, observations, merged devices, cross-profile links, unknown boundaries, contributing profiles with per-profile freshness); Topology shows ONE federated interactive viewer spanning every lab where evidence exists, the canonical inventory with merge badges, identity confidence, and provenance on demand, a Merge Decisions table, and the Unknown Boundaries list; **Predict** and **Paths** now run at All Networks against the federated snapshot — blast radii and path investigations cross profiles wherever strong evidence connects them, with freshness, failed hosts, and captured configurations derived from every contributing profile. Incomplete evidence lowers confidence honestly instead of blocking.
- **Reusable enterprise services**: `get_enterprise_graph()`, `get_enterprise_inventory()`, `resolve_canonical_device()` (unique match or honest ambiguity naming every candidate), `search_enterprise()`, `merge_observations()`, `build_enterprise_snapshot()`, `write_enterprise_artifacts()` — shared by GUI, CLI, future REST APIs, and the assistant. Enterprise artifacts live in `.atlas/enterprise/` (gitignored) and are regenerated deterministically from profile evidence — a view, never a second source of truth.
- Additive service hooks: `predict_change()` gains optional `fresh`/`history_available`/`configuration_captured` overrides and `investigate_path_for_scope()` gains optional `fresh`/`failed_hosts`/`captured_config_devices` overrides so enterprise-scope evidence can come from every contributing profile; scoped behavior is unchanged when they are omitted.
- Added 29 tests (`tests/test_federation.py`): serial merge across profiles; hostname-only and IP-only non-merges; hostname+IP requiring a declared domain (and distinct ids for never-merged twins); merge decisions with WHY and confidence ordering; the `merge_observations` API; observation and inventory provenance; interface union with newest-wins state; cross-profile topology through a merged gateway; the no-invented-connectivity guarantee (a neighbor NAME never attaches to another profile's device); visible unknown boundaries; link observation provenance; content-addressed deterministic enterprise snapshots with canonical devices; enterprise path investigation crossing profiles (A1 → GW → B1); enterprise prediction with cross-profile blast radius; resolve/search honesty (ambiguity named, unknowns honest); and the full two-lab CML GUI scenario (enterprise summary, one spanning topology viewer, merged inventory with 95% identity confidence, cross-lab FLOW A2→A1→GW→B1, enterprise prediction, per-profile isolation untouched, no secrets anywhere).

### EPIC-002 / PR-037 - Atlas Path Intelligence (FLOW)

- Atlas answers the question every engineer starts with: **"why can't A reach B?"** New `founderos_atlas/path_intelligence/` domain — the first vertical slice of end-to-end connectivity investigation. Given a source and a destination device, `investigate_path()` constructs the known path from discovered topology (CDP/LLDP edges in the current snapshot), validates every hop against collected evidence, **stops at the first deterministic failure, explains WHY with cited evidence**, and recommends the next action. Deterministic only: no packet simulation, no traceroute, no AI, no guessing.
- **Hop validation pipeline**: device exists → management reachability (the last discovery's failed hosts are direct evidence) → ingress/egress interfaces exist in the collected inventory → operational state (up / down / administratively down). Each `HopResult` carries status (Pass/Warning/Failed/Unknown), ingress/egress interfaces, link state, management state, per-hop banded confidence, cited evidence, and missing evidence. Hops after a failure are marked **"not evaluated" — never assumed healthy or broken**.
- **Deterministic failure vocabulary** (protocol failures are never invented): interface-down, administrative-shutdown, missing-topology-edge, device-unreachable, discovery-incomplete, unknown-path, unknown-device, unknown-destination, ambiguous-topology. Each failure type carries its own evidence-based recommendations (physical-layer checks for a down link, "find out why it was shut" for an administrative shutdown, power/credentials/discovery for an unreachable device, fresh discovery with depth/seeds/credentials for incomplete evidence). A captured running configuration for the failing device is cited when available.
- **Honesty guarantees**: equal-cost paths are reported as **AMBIGUOUS with every candidate enumerated** — Atlas never guesses which path traffic uses; unknown devices and unreachable destinations are explained, not fabricated; devices known only from neighbor announcements are flagged as unvalidated warnings; missing interface records lower confidence and appear as unknowns; stale snapshots cost a documented confidence penalty; overall confidence is the minimum over evaluated hops, capped at 95%.
- **Investigation story**: every result narrates the investigation as numbered steps (locate endpoints → construct path → validate each hop → conclusion), each step carrying its status and evidence — the timeline a senior engineer would have written down.
- **Service + history** (`investigate_path_for_scope()`): runs against a profile scope's real artifacts (snapshot, history freshness, last run's failed hosts, captured configurations), writes `path_investigation_report.json`/`.md`, and appends the **complete result** to `path_investigations.json` (newest first, capped at 50) — timestamp, profile, source, destination, evidence, result, confidence — so any past investigation can be replayed exactly. All new artifacts are scope-local and gitignored.
- **GUI**: new **Paths** page — source/destination device dropdowns from the active network's latest snapshot, an **Investigate Path** button, and an expandable timeline (green Pass / yellow Warning / red Failure / grey Unknown) with per-hop evidence, confidence, link and management state, plus "Where communication stops", recommended next actions, what Atlas cannot see, and the recent-investigations table. Global scope honestly asks for a specific network. The API returns plain JSON reusable by CLI, REST, and the future assistant.
- Reuses existing engines (topology snapshots, history repository, root-cause confidence bands, discovery artifacts) — no duplicated logic; nothing about discovery, prediction, RCA, or profiles changes.
- Added 26 tests (`tests/test_path_intelligence.py`): chain construction with correct ingress/egress per hop; evidence citation + capped confidence; management-address resolution; same-device investigation; first-failure stop for operational-down, administrative-shutdown (distinct WHY), ingress-side failure, and unreachable device; captured-config citation; unknown source/destination honesty; isolated device → discovery-incomplete; equal-cost diamond → ambiguity with both candidates; missing interface record → warning not failure; neighbor-only destination flagged; stale-evidence confidence loss; byte-identical determinism; service runs over real discovered scopes; the CML acceptance scenario (all pass → shut an interface → re-discover → investigation stops exactly at the failed hop and explains why); replayable history; whole-story markdown; GUI page/timeline/failure/unknown/scope-required scenarios with no secrets anywhere.

### EPIC-002 / PR-036C - Logical Dependency and Management Reachability Prediction (PLANES)

- Fixes a genuine model gap found in real CML testing: shutting SW1's `Vlan1` SVI — owner of `10.10.10.2`, the very address Atlas manages the device through — predicted zero impact because only physical adjacency was modeled. Atlas now evaluates every interface-shutdown prediction across **four planes**: Management, Control, Data, and Observability (`prediction/planes.py`), reusing the PR-036A/B pipeline — no separate engine.
- **Interface semantics**: deterministic classification from canonical discovered names (physical / SVI / loopback / tunnel / port-channel / subinterface / **unknown** — never forced); the engine identifies the type from evidence, never from user input.
- **Management reachability evaluator**: detects when the target interface owns the device's active management address (the address Atlas discovered it through) or a profile seed → Management Plane **Lost**, with careful wording ("services using this management address **may** become unavailable: SSH management, future discovery, configuration collection, monitoring"). **Alternate paths are verified only by proof** — the candidate address must itself be a proven connection address (a seed or the active management IP); a merely-existing second address is a candidate, never assumed reachable.
- **Control plane**: protocol impact only from explicit role evidence (the `role_evidence` extension point for future routing/HSRP collectors); with none collected, Atlas reports no known impact and lists the missing evidence instead of inventing adjacencies. **Data plane**: gateway impact only with gateway role evidence; otherwise honestly unknown while noting that discovered physical links remain up (Layer-2 switching continues). **Observability**: follows management — a lost management address is a monitoring blind spot (future discoveries fail, state goes stale, alerting stops).
- Each plane impact carries status (no_known_impact/degraded/lost/unknown), severity, **its own confidence** (management ~90% on direct address-ownership evidence; data ~45% when VLAN/endpoint evidence is missing; staleness lowers all), affected objects, supporting evidence, missing evidence (which also feeds the prediction's unknowns), and an explanation.
- **Risk arithmetic extended** (documented, never double-counted): management-address loss +25 (one factor for the single shared dependency), unverified alternate +10 / verified alternate −10, verified gateway loss +15, verified control-plane loss +15; the unknown-forwarding-redundancy factor now applies only when the change actually touches forwarding. **Advice ladder** gains the top rule: management lost without a verified alternate → *"Do not proceed until an alternate management path is verified"* — you must be able to reach the device to roll back at all.
- **GUI**: the interface dropdown badges logical interfaces (`Vlan1 [SVI] — up/up — 10.10.10.2 — management address`) and the prediction result renders four color-coded plane cards (status, per-plane confidence, explanation, evidence, missing evidence). Server-side validation, canonical names, and alias normalization unchanged. `predict_change()` gains `seed_addresses` (the GUI passes the profile's proven seeds); presentation stays separate from domain reasoning.
- Physical-interface predictions are unchanged (pinned: the PR-036B chain scenario keeps score 45 and its CAB recommendation; no management factors fire when the target carries no address).
- Added 21 tests (`tests/test_prediction_planes.py`): interface classification and SVI alias resolution; SVI-owns-management-address loss with discovery/collection consequences and careful wording; risk/recommendation reflecting manageability loss with auditable sums; physical links not reported down; verified-alternate risk reduction vs candidate-never-verified; loopback management dependency; dedicated out-of-band interface safety; data-plane unknown without gateway evidence; verified gateway and routing-role impacts; no invented protocol impact; observability blind spot; plane-specific confidence; staleness lowering confidence; deterministic serialization with four planes; physical-prediction regression pin; the full CML GUI scenario (SVI badge, management-address marker, four plane cards, "do not proceed" recommendation, no secrets).

### EPIC-002 / PR-036B - Predictive Change Intelligence (IMPACT)

- Atlas makes its **first deterministic prediction**: propose "shutdown interface Gi0/1" and Atlas answers with affected devices/interfaces/links/sites, blast radius, operational risk, a recommendation with the WHY, confidence, and a full explanation — evidence-based, never guessed, Unknown stated explicitly. Vertical slice: interface shutdown only; everything else remains registered architecture.
- **Risk engine** (`prediction/risk.py`): Low/Medium/High/Critical from documented, auditable factors (broken forwarding paths +25; devices losing connectivity +5 each cap +15; production links +5; **unknown redundancy +10 — Atlas never assumes an alternate path exists**; verified redundancy −10; degraded enterprise health +5/+10; historical target instability +10; low prediction confidence +5; levels at 15/30/50). Factor list always sums to the score.
- **Advice ladder** (`prediction/recommendations.py` → structured `Advice(action, reasons)`): critical risk or broken paths → *High Risk — CAB approval recommended*; high risk with unknown redundancy → *Investigate redundancy first*; medium risk or touching production links → *Proceed during a maintenance window*; target missing from topology → *Run a fresh discovery first*; otherwise *Proceed*. Every action explains why.
- **Honest redundancy**: when no alternate path is visible, redundancy is reported **unknown, not absent** — undiscovered links may exist; verified alternates lower risk, unknowns raise it.
- **Explanation**: every prediction narrates its causal reasoning, cites evidence artifacts (topology, operational state, discovery history, intelligence), projects the enterprise-health impact using the intelligence weights (e.g. −14 points for a link plus one isolated device), and lists what Atlas cannot see.
- **ChangeRequest** gains change-management context: reason, maintenance window, requester (all optional; round-trip serialized into the CAB-ready markdown report).
- **Prediction service API** (`predict_change()`): gathers a profile scope's real evidence — snapshot, history (freshness, target instability), captured configuration, intelligence health score, site catalog — and renders `prediction_report.json`/`.md`. Generic entry point; future change types (ACL/VLAN/routing/firmware/firewall/cloud) flow through the same API via registered evaluators.
- **GUI**: new **Predict** page (device picker from the active network's topology, interface + optional reason/window/requester → full prediction panel with risk badge, confidence, blast radius, explanation, recommendation, unknowns) and a **Latest Prediction** dashboard panel (proposed change, risk, confidence, blast radius, recommendation). Global scope honestly asks for a specific network. Reports are scope-local and gitignored.
- Backward compatible and additive: no existing workflow changes; the PR-036A architecture tests pass unchanged against the enriched engine.
- **Device-aware interface selection** (post-CML usability correction): the Predict page's free-text interface field is replaced by a dropdown populated from the selected device's latest discovered inventory, with context labels (admin/protocol status, IP address, description, connected neighbor — e.g. `GigabitEthernet0/1 — up/up — connected to SW2`). Submitted values are always canonical Atlas interface names. The **server independently validates** against the scope's latest snapshot — device exists in the scope, interface belongs to that device — client-side selection is never trusted. A new deterministic normalization layer (`prediction/interfaces.py`, `resolve_interface`) accepts CLI-style aliases (`Gi0/1`, `Gig0/1` → `GigabitEthernet0/1`); ambiguous aliases are rejected with both candidates named — Atlas never guesses — and typos are rejected cleanly. Devices with no discovered interfaces get "No discovered interfaces are available. Run discovery first." Added 14 tests (alias/typo/ambiguity/empty-inventory resolution, device-tagged dropdown with context, latest-snapshot freshness, cross-device interface rejection, canonical + alias acceptance with canonical persistence, unknown device/interface rejection, no-interface message, cross-profile isolation, no secrets).
- Added 18 tests (`tests/test_prediction_impact.py`): access-port low-risk Proceed, transit-shutdown CAB with auditable score arithmetic, verified-redundancy maintenance-window downgrade, never-assumed unknown redundancy, degraded-health + instability escalation to critical, unknown interface/device → fresh-discovery advice, no-topology confidence honesty, sites + projected health impact in blast radii, evidence-citing explanations, confidence growth with evidence (≤95%), full serialization with context fields, CAB-ready markdown, service-level predictions over a real discovered scope (history/freshness/instability factors), stale-evidence freshness loss, GUI page + run + stored reports + dashboard panel + scope requirement + no secrets.

### EPIC-002 / PR-036A - Predictive Change Intelligence Architecture

- Architecture milestone: Atlas begins the Predict stage of Observe → Understand → Reason → **Predict** → Advise. New `founderos_atlas/prediction/` domain establishing the deterministic foundation future prediction engines build on — no AI, no LLM, no guessing; identical inputs yield identical predictions (tested).
- **First-class models**: `ChangeRequest` (open change-type registry seeded with shutdown-interface, remove-vlan, delete-route, modify-acl, disable-protocol, reboot-device, upgrade-firmware — new types register at runtime with zero model changes), `Boundary`, `PredictedOutcome`, `BlastRadius`, `CriticalPath`, `RedundancyAssessment`, `RollbackEstimate`, `ConfidenceAssessment`, `Prediction` — all plain-JSON serializable for a future AI explanation layer.
- **Dependency graph**: extensible, layered (device → interface → protocol → topology → service → application → users); node kinds are open strings so VLANs/VRFs/OSPF/HSRP/firewalls/applications/Kubernetes/cloud resources become nodes without schema changes. Links are modeled through **both interface endpoints** so shutting either end breaks the path. First builder populates device/interface/link layers from topology snapshots; future builders only add nodes — impact and redundancy get richer automatically (tested with injected service/application nodes).
- **Deterministic pipeline** (`simulator.predict`): Change Request → dependency resolution → critical paths → redundancy → impact → risk → confidence → recommendations. Per-change-type **evaluators** are registered, never hardcoded; unmodeled change types predict honestly with explicit unknowns and low confidence instead of failing.
- **Blast radius by lost reachability**, not adjacency: a node of any kind is affected when it loses connectivity once the changed element is removed. **Critical paths** report device pairs whose connectivity breaks; **redundancy** answers whether alternate topology paths absorb the change. **Rollback** is rule-based per change type (one-command interface recovery; route/VLAN/ACL rollback complexity depends on whether configuration was captured first — stated as a prerequisite; reboots and firmware upgrades are honestly irreversible). **Confidence** is documented arithmetic capped at 0.95, reusing the root-cause bands.
- **First working slice** proving the architecture answers the customer question: `shutdown-interface` and `reboot-device` evaluators over real topology evidence — in a chain topology, shutting the transit interface predicts the isolated device, the broken critical path, high severity, and a maintenance-window recommendation; in a triangle, redundancy absorbs the same change.
- Consumes existing artifacts (topology snapshots, history, configuration presence) — no duplicated logic. No GUI this PR (deliberate — no placeholder cruft); the API is service-level. New `ARCHITECTURE.md` documenting the full engine stack and the prediction architecture with its roadmap (config/routing/firewall simulation, service/app dependency, WAN/SD-WAN, cloud, Kubernetes — all via new builders/evaluators, no redesign).
- Added 21 tests (`tests/test_prediction_architecture.py`): model round-trips and validation, full-prediction serialization, built-in change vocabulary, runtime change-type registration, graph construction, both-endpoint link semantics, future-layer extensibility (service/application/Kubernetes nodes), the chain-vs-triangle WOW scenario, richer-graph→richer-blast-radius, reboot semantics, honest unregistered-type and missing-target behavior, evaluator registry extensibility, byte-identical determinism, documented confidence (sum-consistent, never 100%, unknown-layers and contradictions lower it, missing evidence lowers it), and rollback rules per change type.

### EPIC-002 / PR-035 - Evidence-Based Root Cause Analysis Engine

- Atlas now explains **why** — deterministically. New `founderos_atlas/root_cause/` package: an evidence-based reasoning engine (no AI, no LLM, no guessing; identical evidence yields byte-identical explanations, proven by test).
- **Evidence engine**: configuration, operational, topology, discovery, and incident artifacts normalized into citable evidence items (timestamp, causal rank, affected devices/interfaces, source artifact, attributes). **Timeline engine**: deterministic ordering by timestamp then causal rank (configuration → interface → protocol → topology → incident) — intra-run ordering is causal because Atlas has run-level timestamps, not per-event device clocks; the report says so explicitly rather than inventing seconds.
- **Correlation engine + internal causal graph**: edges only along documented rules over real shared devices/interfaces/adjacency — a config change links to an interface failure on the same device (stronger when the change names the interface), interface links to protocol on the same interface, and a failure links to the removal/discovery-failure of a device that was *adjacent in the previous topology*. Unrelated evidence is never connected. The graph stays internal; the artifact carries derived reasoning with evidence ids.
- **Hypothesis engine**: competing rule-based causes per problem — configuration change, physical failure, deliberate shutdown, authentication issue, device unreachable, upstream isolation, expected maintenance — each with supporting AND contradicting evidence (a config change on the failing device supports the configuration hypothesis and contradicts the hardware one).
- **Confidence engine**: documented arithmetic (base + 0.08×supporting − 0.15×contradicting + interface-match + recurrence − staleness), clamped to 0.95 — **never 100%** — and banded very-high / high / medium / low.
- **Explanation engine**: human-readable reasoning chains that follow the causal graph and cite an evidence id in every sentence, ending in the conclusion with its confidence band — fully inspectable.
- **Pipeline**: every discovery writes `root_cause_report.json`/`.md` (profile-scoped, archived in history, gitignored) with a `Root cause: …` progress line. **Historical replay**: `analyze_record()` re-analyzes any archived discovery's stored artifacts and reproduces the stored explanation byte for byte — "what happened yesterday" answered from evidence.
- **Incident integration**: every investigation (GUI and CLI) automatically appends the Root Cause Analysis — likely cause, supporting evidence, timeline/reasoning, confidence, recommended next step — and the Incidents page shows the analysis card.
- **Dashboard**: when a high/very-high-confidence root cause exists, both the generated dashboard and the web GUI lead with **Most Likely Root Cause** (statement, confidence band and percent, next step) instead of only the raw alarm. **Morning Brief** gains a "Most Important Root Cause" section when one exists.
- Added 20 tests (`tests/test_root_cause.py`): confidence arithmetic/caps/bands and contradiction effects, timeline ordering, correlation of related evidence with reasoning-chain citations, non-correlation of unrelated devices, adjacency-only downstream blame, ranked multiple hypotheses, conflicting evidence recorded against the losing hypothesis, physical-primary without config evidence, deliberate-shutdown detection, credential hypotheses for auth failures, maintenance alternatives for lone removals, byte-for-byte determinism, evidence citation in every conclusion, the full config-shutdown pipeline scenario (report + brief + dashboard + archive + no secrets), byte-identical historical replay, incident integration (GUI + markdown), and renderer behavior on empty reports.

### EPIC-002 / PR-034 - Enterprise Intelligence Engine

- Atlas stops reporting raw events and starts answering what a network manager asks: *what matters, what changed, should I care, what should I do first.* New `founderos_atlas/enterprise_intelligence/` domain consuming topology, operational state, configuration changes, discovery history, incidents, and provenance — fully deterministic, rule-based, no AI.
- **Calculated Enterprise Health (0–100), fully explained**: replaces the coarse Healthy/Warning/Critical with a score where every point is a named, capped factor with evidence (`score == clamp(100 + sum(factor points))` always holds; the weight table is documented in `health.py`). Signals include interface failures, other active operational issues, authentication failures (classified separately from unreachable devices), discovery failures, topology and configuration changes, repeated device instability across recent runs, open incidents, evidence staleness — plus credits for recoveries and topology stability. Confidence (high/medium/low) reflects evidence quality: baseline presence, freshness, and discovery failure share.
- **Risk engine**: every finding carries severity, risk (blast radius from real topology degree, recurrence), confidence, and urgency (immediate/soon/scheduled).
- **Priority engine**: a documented weighted ranking (urgency + severity + risk + blast radius + recurrence, scaled by confidence) produces the "top 5 things you should care about" with deterministic tie-breaking — findings are ranked, never listed equally.
- **Recommendation engine**: likely cause first, concrete next step second, with cross-signal reasoning — an interface failure on a device whose configuration also changed this run recommends comparing the configuration diff *before* investigating hardware; auth failures point at the credential set to fix; removed hub devices quote how many neighbors they connected.
- **Trend engine**: health trajectory versus the previous run's archived intelligence report (improving/declining/stable/baseline), configuration churn, recurring link/device instability, discovery-failure direction, and topology stability across the recent history window.
- **Morning Brief v2**: the brief now opens the day like a senior engineer — Enterprise Health X/100 with trend and confidence, Top Risks, Top Recommendations, Changes Since Yesterday, Biggest Improvement, Biggest Regression, and a Suggested Investigation. (Appended deterministically at the pipeline layer; the existing brief content and its evaluation are unchanged.)
- **Dashboard**: Enterprise Health tile with trend, Top Risks, Top Recommendations, priority queue, and improvement/regression callouts in both the generated dashboard.html and the web GUI; the All Networks table gains a per-network Health column.
- **Pipeline**: every discovery writes `intelligence_report.json` (the machine contract a future AI layer can consume — summary, evidence, risk, confidence, recommendations; no LLM integrated) and `intelligence_report.md`, profile-scoped like every other artifact and archived in history so trends compare run over run. New progress line: `Intelligence: health N/100 (trend)`. New gitignore entries for the generated reports.
- Added 23 tests (`tests/test_enterprise_intelligence.py`): perfect-network scoring and stability credit, full point-by-point explainability, deduction caps, auth-vs-unreachable classification, recovery credits, confidence rules, byte-identical determinism, risk classification with real blast radius, removed-device risk from the previous topology, priority ordering and top-5 bound, cross-signal and hardware-path recommendations, credential-fix recommendations, all four trend directions, configuration-churn and recurring-instability trends, historical improvement/regression naming, end-to-end pipeline artifacts + Morning Brief v2 sections + dashboard + history archiving, recovery turning the trend around, no secret exposure, and web dashboard/All Networks health display.

### EPIC-002 / PR-033 - Enterprise Discovery Architecture: Seeds, Boundaries, Multi-Credential Strategy, Site Inference Foundation

- **Profiles are entry points, not site boundaries.** `DiscoveryProfile` gains optional description, additional `seeds` (the legacy management IP stays seed #1), a `boundary` policy, `credential_sets` references, and `site_hint`/`domain_hint`. All fields default — profiles saved by earlier versions load and behave unchanged.
- **Discovery boundaries** (`discovery/policy.py`): include/exclude CIDRs, allow/deny hostname globs, allowed protocols. Every observed neighbor gets a structured decision — `allowed` / `denied` / `observe-only` / `unknown` — with a reason; only `allowed` neighbors are traversed, the rest are *recorded* as visits (the relationship is preserved, never silently followed and never erased). Uncertainty never auto-traverses. Multi-seed traversal: all seeds start at depth 0; with multiple seeds one failed seed no longer aborts the run. `max_depth`/`max_devices` unchanged and still enforced.
- **Multi-credential strategy** (`credentials/` package): named credential sets whose entries carry priority and a generic, vendor-neutral scope (vendor, platform, hostname globs, CIDRs, sites, profiles, device ids; extensible `kind` for future SNMP/NETCONF/API/cloud credentials). Deterministic, lockout-safe resolution precedence: remembered-successful reference first; the profile's own credential first **on the profile's seed devices only** (and trivially for legacy profiles without sets); on every other device, scope-matching entries by **match specificity** (explicit device id > exact host/IP or exact hostname > CIDR/hostname pattern > vendor/platform > site/role/profile, priority and declaration order breaking ties within a class) before the generic profile credential, with unrestricted general-fallback entries last — so a targeted credential is never preceded by a generic one that would burn a failed attempt against the device. Bounded attempts (default 3 — lockout protection), never the same failed credential twice on one device, immediate stop on non-auth errors, stop at first success. Only credential *references* are remembered (`credential_memory.json`) and recorded in run provenance (`credential_use` in history metadata) — never secrets. The profile's own credential is the implicit priority-0 candidate, which is the backward-compatibility layer: legacy single-credential profiles behave identically. Configuration collection uses the same per-device resolution.
- **Site inference foundation** (`sites/` package): evidence-based, multi-signal assignment with honest uncertainty. Explicit user mapping → high confidence; hostname conventions and seed-origin hints assign at low/medium; declared network ranges **corroborate only** — a subnet can raise confidence but never assigns a site by itself (a site may hold many subnets; one supernet may span many sites). Conflicts → *ambiguous*; no evidence → *unknown*. Every assignment carries confidence and its evidence list. User catalog at `<workspace>/sites.json`.
- **Enterprise topology** (`enterprise/` package): all profiles contribute to one view with per-observation provenance (profile id, run id, timestamp). Cross-profile canonical identity is strictly evidence-based: serials always merge; hostname+IP merges only under an explicitly shared administrative domain; hostname alone or IP alone never merges. Aggregation, not comparison — no false removals possible; per-profile histories and baselines (PR-031A) untouched.
- **GUI (minimal but sufficient)**: new Credentials page (list sets with priority/scope/last-success, add/delete entries; secrets never displayed); Topology → All Networks becomes the enterprise inventory (canonical devices, site + confidence, observed-via networks, credential reference used, `?site=` filter including unknown); profile form gains an "Enterprise discovery options" section (seeds, boundaries, credential sets, site/domain hints). Estates with only legacy unscoped data keep the previous per-network inventory.
- **Migration**: no data rewrite. Existing profiles load with empty enterprise fields; the single seed is the first seed; the existing credential reference acts as the first (priority-0) credential candidate; scoped histories and baselines remain valid byte-for-byte. Profile schema version 1.1.0 (older readers unaffected — new keys are additive).
- Added 49 tests across `test_credential_resolution.py` (scope matching, priority ordering, remembered-credential preference, vendor/CIDR scoping, bounded attempts, lockout, cross-site credential fallback end-to-end, provenance refs, zero secret exposure on disk), `test_site_inference.py` (explicit/high, convention/low, agreement/medium, subnet corroboration, subnet-alone → unknown, conflicts → ambiguous, multi-subnet sites, supernet across sites, catalog round-trip), and `test_enterprise_discovery.py` (boundary verdicts, observe-only recording without traversal, deny reasons, limits with policy, multi-seed, cross-profile aggregation, strong-evidence merge with run-id provenance, no hostname/IP false merges, declared-domain merge, site flow, the full cross-site scenario with independent baselines, GUI enterprise/site/credential exposure with no secrets, legacy profile compatibility).
- Updated 1 existing test fixture (`test_overlapping_hostnames...`): the two devices sharing hostname+IP now carry distinct serial numbers, expressing their intent (physically distinct devices) under evidence-based identity.

### EPIC-002 / PR-032 - GUI-Driven Discovery Execution and Live Progress

- Discovery is now fully executable and observable from the web GUI: select a network, click **Run Discovery**, watch real progress, keep using Atlas while it runs, and see topology/health/changes/history/dashboard update on completion. No CLI required for normal operation.
- **Shared discovery service**: the GUI job layer executes the exact same `atlas_discover_command` pipeline the CLI uses — in-process, never a subprocess, never duplicated logic. Credentials are resolved server-side from the secure store; the browser only ever sees profile identity and safe job metadata.
- **In-process job manager** (`founderos_atlas/web/jobs.py`): `POST /api/discovery/jobs` creates a job and returns immediately; the Discover page polls `GET /api/discovery/jobs/<id>` every 1.5s. One daemon thread per job behind a narrow manager interface so a production job backend can replace it later; no Redis/Celery/external infrastructure.
- **Honest progress**: seven user-facing stages (Preparing → Connecting to seed → Discovering neighbors → Collecting device facts → Collecting configurations → Analyzing changes & state → Saving results) driven entirely by real pipeline activity — actual transport connections (current device, devices contacted) and the pipeline's own `[N/9]` lines. Overall percentage is stage-based and labelled as such; no timers, no fake precision, and depth is reported as unknown rather than invented.
- **Job model**: job_id, profile identity, status (`queued`/`running`/`completed`/`failed`/`interrupted`), stage, message, current device, devices discovered, timestamps, elapsed, friendly error, warning, completion summary (devices, relationships, configurations, duration), recent events. Never a password, secret, or credential reference.
- **Concurrency safety**: duplicate jobs for the same profile are rejected (the running job is returned, HTTP 409); jobs for different profiles are accepted but **all discovery execution is serialized** behind one run lock — correctness over concurrency, documented as a local-alpha limitation.
- **Profile selection**: discovery always targets one explicit profile. With All Networks active, the Discover page requires choosing a network (profile table shows name, site, seed IP, last discovery, current status); the API rejects profile-less requests. Starting a job focuses the GUI scope on that network.
- **Failure handling**: authentication failures, connection timeouts, and an unavailable credential store surface as plain-language guidance (which profile to fix, what to check); partial discoveries complete with a warning ("N device(s) could not be reached"); technical detail stays in the job log — no tracebacks in the GUI.
- **Refresh/restart behavior**: browser refresh or navigation never cancels a run (the Discover page re-attaches to the live job); job history persists to `.atlas/jobs.json`; after a server restart, jobs that were queued/running are marked `interrupted` with an honest message instead of appearing to run forever. In-process jobs cannot survive a restart — documented limitation.
- **Isolation preserved (hard invariant)**: GUI jobs run through the PR-031A scoped pipeline — each profile's credentials, seed, artifacts, history, and baselines only. Regression tests re-verify A-then-B-then-A produces zero false removals and leaves the other scope byte-for-byte untouched.
- The no-JS fallback (`POST /discovery/run`) runs synchronously through the same job manager, so there is exactly one execution path.
- Added 19 tests (`tests/test_discovery_jobs.py`): API lifecycle with real artifacts, explicit-profile requirement, unknown profile, no secrets in any API response or persisted job file, mid-flight progress reflects the real seed connection and pipeline lines, duplicate prevention, cross-profile serialization, friendly auth/timeout/credential-store failures, GUI-job isolation (byte-for-byte), scope focus, dashboard freshness without restart, Discover page details/preselection/re-attach on refresh, sync fallback through the manager, interrupted-job marking after restart.

### EPIC-002 / PR-031A - Profile-Scoped Discovery Isolation & Multi-Network Architecture

- Every discovery profile now owns an **isolated discovery scope**: its own current artifacts (topology snapshot, viewer, morning brief, dashboard, change/config/state reports), its own collected configurations, and its own discovery history, stored under `<workdir>/.atlas/profiles/<profile_id>/`. Discovering one profile can no longer overwrite another profile's current view or history.
- **Comparison baselines are profile-scoped**: step 5 of the unified pipeline loads the previous baseline from the active profile's own history only. Discovering network B immediately after network A no longer produces false "device is no longer discovered" topology changes, phantom operational events, or polluted health status. Genuine changes within a profile are still detected exactly as before.
- The scope identifier is the profile's stable `profile_id` (created once, filesystem-safe), never the display name. Profiles can now be **renamed** (`ProfileService.update_profile(new_name=...)`, GUI edit form): the id, stored credential, history, baselines, and reports all survive a rename. New profile ids are guaranteed unique even when different names slug identically ("Lab A" / "Lab-A").
- History records are stamped with `profile_id` and `profile_name` (both optional in the schema — records written before PR-031A load unchanged).
- **Backward compatibility / migration**: profile-less interactive `atlas discover` is byte-for-byte unchanged and keeps using the classic unscoped layout (CWD artifacts + `.atlas/history`), now called the *default scope* ("Local workspace" in the GUI). Legacy history recorded before this change stays in the default scope and is deliberately **never reassigned** to any profile — Atlas cannot know which network produced it, so guessing would corrupt history. Each profile's scope starts empty; its first scoped discovery is a clean "first discovery" baseline.
- **GUI multi-network support**: a Network selector (each profile / All Networks / Local workspace when legacy data exists) on Dashboard, Topology, History, Changes, and Incidents; the selection is clearly shown in every page title and persists in the session. Running a discovery focuses the GUI on that profile's network.
- **All Networks / Global View**: aggregates the latest successful state of every scope — combined device/relationship/configuration counts, worst-of status, per-network summary cards, merged device inventory (Topology), merged history with a Network column, and per-network change/incident cards. Aggregation never compares one network against another.
- CLI: `--profile <name>` added to `atlas history`, `atlas timeline`, `atlas dashboard`, `atlas investigate`, `atlas config-diff --latest`, and `atlas state-diff --latest` so every read-side command can address a profile's scope. All existing invocations are unchanged.
- Incidents are scope-isolated: GUI investigations read and write only the active network's artifacts; the All Networks view lists each network's latest report but cannot run a cross-network investigation.
- **Legacy-data policy** (added after manual CML acceptance testing): profile scopes that have completed a discovery are authoritative for All Networks. The legacy Local workspace participates in aggregation **only while no profile scope holds data** — so pre-scoping installations keep a working All Networks view, but once explicit profiles have discovered, stale legacy artifacts can no longer duplicate devices, inflate network/device counts, pollute merged history, or degrade aggregated health (a stale legacy Critical state cannot make All Networks Critical). Legacy data is never deleted: it stays fully accessible by selecting "Local workspace (legacy)" in the Network selector, which reports its state faithfully. Policy implemented as the pure domain function `active_scopes()` in `workspace/scopes.py`.
- Devices are **never deduplicated by hostname or IP across active profiles** — two sites may legitimately reuse RFC1918 addresses and hostnames; the stable profile id remains the only isolation key (regression-tested).
- All Networks topology is deliberately a **combined inventory plus per-network interactive viewers** (option a); a single federated cross-network graph is documented future work because the viewer resolves edges by hostname, which is ambiguous across networks. UI wording states this.
- Added 32 tests (`tests/test_profile_isolation.py`): two-profile isolation end-to-end, no false removals in either direction, profile-own baselines, genuine within-profile removal detection, history stamping, rename preservation, config/operational isolation, legacy unscoped behavior, unique profile ids, scoped CLI commands, GUI scope filtering (dashboard counts per scope and global, topology inventory, history, changes, incident isolation, selector visibility, session persistence), per-scope viewer existence, and the legacy-data policy (hidden from aggregation once profiles discover, preserved when they haven't, selectable archive, stale-Critical suppression, overlapping hostname/IP non-deduplication).
- Updated 3 existing tests that asserted profile-run artifacts at unscoped paths (intentional behavior change; the unscoped pipeline tests are untouched).

### EPIC-002 / PR-031 - Atlas GUI Application Shell

- Added `founderos_atlas/web/`: the first local Atlas web GUI shell (Flask), a single-user local-only alpha interface over the existing backend services — not a production or multi-user deployment.
- `create_app()` factory with injectable services (profile service, output dir, history root, transport factory, clock) so the whole GUI, including a real discovery run, is testable against a scripted network; binds to `127.0.0.1` by default and never `0.0.0.0`.
- Eight pages behind a professional sidebar shell (Dashboard, Discover, Profiles, Topology, History, Changes, Incidents, Settings) with an "Atlas · Enterprise Network Intelligence" header and a primary Run Discovery button; framework-free CSS/JS.
- Every route is a thin adapter over existing services: `ProfileService` (list/add/edit/delete), the unified discovery pipeline (`atlas_discover_command` in-process — never a subprocess), `build_dashboard_summary`, `HistoryRepository`, the generated change/config/operational reports, and `IncidentInvestigator`. No business logic or profile logic is duplicated in the web layer.
- Discovery runs from a saved profile with no IP/username/password entry in the GUI; the profile's last-discovery timestamp updates. The embedded topology viewer reuses the existing generated HTML.
- Added `founderos atlas web`: starts the local server, prints `http://127.0.0.1:8765`, and opens the browser (server runner and browser opener are injectable for tests).
- Security: local-only bind, no authentication (documented as alpha), passwords never rendered in HTML, returned in responses, or logged; profiles store only a credential reference and the secret stays in the OS keyring; password form fields are masked and never pre-filled on edit.
- Added Flask as an optional `web` extra and web templates/static to package data.
- Added 13 tests (app starts and binds loopback; dashboard/profiles/settings/discovery routes; add-profile form has masked password with no value; profile list exposes no password; discovery runs from a saved profile without credentials and produces real artifacts in-process; discovery requires a profile; settings shows credential provider status; no subprocess used for discovery; missing workspace handled gracefully; `atlas web` prints the URL and binds 127.0.0.1; help lists web).
- No production authentication, RBAC, job queue, WebSockets, JS framework, database, or AI — per non-goals.

### EPIC-002 / PR-030.1 - Atlas Alpha Stabilization

- Packaging: the `credentials` extra (keyring) is correctly declared in `pyproject.toml`; the earlier "does not provide the extra 'credentials'" warning was stale editable-install metadata (egg-info at version 0.1.0). Documented `pip install -e ".[credentials]"` and added a test asserting the extra requires keyring with no plaintext dependency.
- Operational health now separates current health, historical events, and active unresolved issues. `StateChange` carries an event type (failure / degradation / recovery / informational); `StateChangeReport` exposes `active_issues`, `recoveries`, `active_issue_count`, and `current_health`. Current health is derived from unresolved issues only — a recovered interface (down → up) is preserved in history but returns health to Healthy and no longer leaves Atlas permanently in Warning/Attention Required. The dashboard, Morning Brief, and CLI report current health and active issues instead of raw change counts.
- Configuration intelligence now filters dynamic Cisco IOS/IOS-XE metadata (`Current configuration : <n> bytes`, `! Last configuration change at <timestamp>`, and similar) before semantic comparison, so changing byte counts and save timestamps no longer masquerade as configuration changes. The filter is per-vendor and extensible; real `shutdown` / `no shutdown` changes are still detected as the single meaningful change.
- Added 14 regression tests (credentials extra declaration; failure changes health, recovery restores Healthy, recovery preserved in history, historical-only changes do not cause Attention Required; byte-count and timestamp metadata ignored while shutdown/no-shutdown still detected). Updated existing operational/pipeline assertions to the new health-vs-history semantics. Full suite passes.

### EPIC-002 / PR-030 - Atlas Workspace & Saved Discovery Profiles

- Added `founderos_atlas/workspace/`: a persistent workspace and saved discovery profile system — the reusable backend foundation for the Atlas GUI (PR-031).
- `DiscoveryProfile` model stores name, site, management IP, username, credential reference, max depth, max devices, collect-configuration setting, and created/updated/last-discovery timestamps — and has **no password field** by design, so a profile can never serialize a secret.
- `CredentialProvider` abstraction with `KeyringCredentialProvider` (OS-native storage via the optional `keyring` extra) and `InMemoryCredentialProvider` (tests/sessions); there is deliberately no plaintext fallback, and the abstraction is extensible for future enterprise backends (Vault, AWS Secrets Manager, Azure Key Vault).
- `ProfileRepository` persists profiles as JSON under `~/.atlas/workspace/` (override with `ATLAS_HOME`), keyed by case-insensitive name, corruption-tolerant.
- `ProfileService` holds all profile/credential business logic (add/list/get/update/delete, resolve discovery inputs, record last-discovery) — the CLI is a thin adapter and PR-031's GUI will call the same service directly.
- Added `founderos atlas profile add | list | show | update | delete` with masked password input; passwords are never displayed.
- Added `founderos atlas discover --profile <name>`: loads the saved profile, resolves the secure credential, runs the existing unified pipeline unchanged (topology snapshot, viewer, dashboard, morning brief, history, topology/config/operational change reports), and updates the profile's last-discovery timestamp. The interactive `founderos atlas discover` is unchanged and fully backward compatible.
- Security: a known test password is verified absent from profile storage, console output, generated HTML, Markdown reports, JSON snapshots, and history; graceful, password-free errors for duplicate name, invalid IP, missing profile, missing credential, corrupted workspace, and unavailable credential store.
- Added 27 tests (model, service CRUD, duplicate/invalid/missing rejection, credential security regression, keyring-unavailable behavior, the profile CLI, and end-to-end discovery via a saved profile with a no-prompt assertion). All existing tests continue to pass; the unified discovery pipeline is unchanged.
- Did not build the GUI in this PR.

### EPIC-002 / PR-029 - Operational State Intelligence

- Added `founderos_atlas/state/`: deterministic operational state detection between two topology snapshots — the third change dimension alongside topology and configuration intelligence, detecting changes in the live network even when the saved configuration is identical.
- Detects interface status up → down (high; check cable, remote device, errors, spanning-tree), line protocol up → down (high; reported separately from admin shutdown), status up → administratively down (medium), IP address change (medium), interface removed (medium), new interface (low), and interface recovery (low). Interface state is read from the topology snapshot (`show ip interface brief`); no extra collection required.
- `interfaces_down` counts distinct down interfaces (an admin-shut interface whose status and protocol both drop counts once).
- Added `founderos atlas state-diff <previous.json> <current.json>` and `--latest` (compares the two most recent history snapshots), writing `state_change_report.json` and `state_change_report.md`.
- Moved interface-level change detection out of the topology change detector: an interface going down is neither a topology change (devices/relationships unchanged) nor a configuration change — this is what lets the Morning Brief honestly say "1 interface down · no topology changes · no configuration changes".
- Unified pipeline step 5 now compares topology and operational state together; operational comparison runs automatically on every discovery with a baseline, and the state reports are archived in history.
- Morning Brief: operational changes drive Attention Required status, an Operational Changes section, and a "N interface(s) down" bullet in Today's Summary.
- Dashboard: added an Operational Changes card (status, devices changed, interfaces down, severity counts) plus an Open Operational Changes action; high-severity operational changes count toward the Critical status.
- Added 24 tests: status/protocol/IP/new/removed interface detection, admin-shutdown separation, recovery, determinism, JSON/Markdown generation, the state-diff CLI, and end-to-end pipeline auto-detection; all existing tests continue to pass.

### EPIC-002 / PR-028 - Unified Discovery Pipeline (Alpha Polish)

- `founderos atlas discover` now executes the complete Atlas workflow automatically with step-by-step progress ([1/9]…[9/9]): discovery → configuration collection → previous-baseline loading from history → topology comparison → configuration comparison → report building → archiving → dashboard refresh. No manual compare/config-diff/dashboard/history invocation is required.
- Added `founderos_atlas/pipeline.py`: baseline loading (integrity-checked snapshot reconstruction via new `TopologySnapshot.from_dict`), automatic topology change intelligence, automatic per-device configuration intelligence against the baseline record's configs, and aggregated multi-device configuration reports (devices changed, merged severity counts).
- Change detection now flags interface status transitions (up → down / administratively down) as medium-severity changes with a "verify the shutdown was planned" recommendation.
- Morning Brief is manager-friendly: a Today's Summary section (devices, relationships, configurations collected, topology/configuration change counts, failures) and real Started/Completed/Duration generation timing, with the previous snapshot as an automatic baseline.
- Topology viewer node details now show neighbors, discovery depth, last discovered, configuration collected, and last configuration change, alongside the existing identity and platform facts; the viewer is change-highlighted automatically when a baseline exists.
- Every history record now archives change_report.json/md, config_change_report.json/md, and incident_report.json (when present) alongside the snapshot, viewer, brief, dashboard, and configurations; discovery metadata records the Atlas version.
- Steps 8 and 9 run archive-then-dashboard (labels reflect actual order) so the refreshed dashboard always lists the run just archived.
- Added 11 integration tests covering first discovery, automatic baselining, automatic configuration and topology change detection, interface shutdown flagging, discovery failure resilience, partial configuration collection, complete history artifact sets, dashboard freshness, the manager-friendly brief, and enriched viewer details.
- No AI in this PR.

### EPIC-002 / PR-027 - Atlas Incident Investigation Journey Foundation

- Added `founderos_atlas/incidents/`: a deterministic, evidence-based incident investigation over existing Atlas artifacts — not AI and not root-cause automation.
- Affected devices are matched from the incident text by hostname, canonical-identity alias, and management IP; when nothing specific matches, the whole known network is treated as in scope with a recorded limitation.
- Evidence assembly from the topology snapshot (device facts and logical links), the change report, the configuration change report, collected configurations, and history depth — every statement names its source artifact.
- Honesty rules: missing `change_report.json` states exactly "Topology change evidence is not available."; missing `config_change_report.json` states "Configuration change evidence is not available."; facts are never invented, and limitations always record that no live device access occurred.
- Investigation steps come from a fixed base sequence plus keyword tables (VLAN numbers, internet/gateway, slowness, lost/down/unreachable); recommendations derive from steps and detected changes, deduplicated deterministically.
- Deterministic confidence: low without a snapshot; high when named devices matched and both change reports exist; medium otherwise. Incident IDs are content-addressed (`INC-…`).
- Added `founderos atlas investigate` prompting for title and description, writing `incident_report.md` and `incident_report.json`, and printing the investigation summary.
- Dashboard shows a Recent Incident Investigation card (title, generated time, confidence) plus an Open Incident Report quick action when a report exists.
- Added 17 tests covering topology-only reports, config-report evidence, missing artifacts, hostname/alias/IP device detection, spec-example keyword steps, deterministic reports and IDs, fact non-invention, JSON and Markdown generation, no-AI source scan, no network access, the CLI flow, title validation, help listing, and dashboard integration.
- Added no AI, live troubleshooting commands, packet capture, remediation, config push, ticketing integration, or database.

### EPIC-002 / PR-026 - Atlas Configuration Intelligence Foundation

- Added `founderos_atlas/config_intelligence/`: classified, secret-masked comparison of two device configurations — section-aware diffing (top-level sections plus indented children; global one-liners are single-line sections), not a raw line diff.
- Classification via ordered prefix rules into interfaces, routing, OSPF, BGP, static routes, VLANs, ACLs, NAT, logging, SNMP, NTP, AAA, line/VTY access, and other; severity from a documented category map (access control and BGP high; routing/interfaces/VLAN/SNMP medium; logging/NTP/other low) plus a shutdown-toggle escalation on interfaces.
- Every change carries hostname, category, severity, summary, recommendation, masked added/removed lines, and a raw diff reference (the section header).
- Secret masking at diff-extraction time: any line containing password, secret, key, community, token, or credential (word-boundary, case-insensitive) is replaced entirely before models, reports, or console output exist; classification uses only the first two command tokens internally.
- Added `founderos atlas config-diff <previous> <current>` and `founderos atlas config-diff --latest <hostname>` (compares the two most recent history records that collected that device's configuration), writing `config_change_report.json` and `config_change_report.md`.
- Dashboard shows a Configuration Changes card (devices changed, high/medium/low counts) plus an Open Config Changes quick action when a report exists.
- Added 22 tests covering identical configs, interface/OSPF/BGP/ACL/static-route changes, shutdown escalation, SNMP community masking, password/secret masking, mask term coverage, severity classification, VTY changes, JSON and Markdown generation, determinism, path-mode CLI, --latest history comparison, insufficient-history and usage errors, help listing, and dashboard integration.
- Added no AI, remediation, rollback, config push, compliance engine, vendor-specific deep parser, database, or scheduler.

### EPIC-002 / PR-025 - Atlas Historical Timeline & Network Memory

- Added `founderos_atlas/history/`: every successful discovery is automatically preserved under `.atlas/history/<timestamp>/` with full copies of the snapshot, viewer, Morning Brief, dashboard, collected configurations, and a self-describing `discovery_metadata.json`.
- Metadata records start/end time, duration, device and relationship counts, warnings, failed hosts, configuration collection status, Morning Brief quality score, network status, snapshot ID, and discovery schema version.
- Records are never overwritten (same-second collisions get numeric suffixes); corrupt records load as reported issues without breaking the rest of history; no automatic pruning by design.
- The history layer is the only place Atlas reads the system clock, via an injectable clock; the deterministic discovery core remains clock-free.
- Added `founderos atlas history` listing every preserved discovery (time, devices, status, duration, folder) and `founderos atlas timeline` generating `timeline.md`: day-grouped entries with device deltas, status, configuration collection, failures, and change intelligence computed between consecutive stored snapshots.
- Dashboard integration: last discovery time now comes from history, a Recent Discoveries card lists the last five runs, and Open History / Open Timeline quick actions link the memory.
- Historical topology viewing: each record carries its own `atlas_topology.html`; the current topology remains the default viewer.
- The repository is artifact-oriented for future extensibility (configuration diff, incident replay, historical playback, AI reasoning) — new capabilities read record directories without storage redesign.
- Added 15 tests covering history creation, timestamp uniqueness, newest-first loading, missing history, corrupt history, metadata round-trips, folder naming, timeline generation/empty/determinism, the history and timeline CLIs, automatic preservation on discover (fixed clocks), multi-run survival, and dashboard history integration.
- Added no database, Git, AI, scheduler, automatic pruning, or configuration diff.

### EPIC-002 / PR-024 - Atlas Executive Dashboard

- Added `founderos_atlas/dashboard/`: a deterministic operational summary computed from existing artifacts (snapshot, viewer, Morning Brief, change report, configurations) — an executive landing page, not a monitoring system.
- Dashboard sections: Atlas / Enterprise Network Intelligence header with last discovery time; network status banner (Healthy / Warning / Critical, plus Unknown before the first discovery) with a one-line reason; summary tiles (devices, relationships, discovery success, configurations collected, recent changes); recent changes with severity coloring; recent activity; and quick-action links to every artifact.
- Deterministic status logic: Critical on any high-severity change; Warning on changes, failed discovery hosts, or reconciliation warnings; Healthy otherwise.
- Rendering reuses the template-substitution style of the topology viewer: responsive, professional, HTML-escaped, self-contained — no JavaScript at all, no frameworks, no CDN, no backend, no database, no authentication.
- Added `founderos atlas dashboard` generating `dashboard.html` and opening the browser; missing artifacts degrade to "—" tiles and disabled quick actions, and an empty workspace still renders a valid dashboard.
- `founderos atlas discover` automatically regenerates the dashboard after every successful discovery (best effort — a dashboard failure never fails a successful discovery); quick-action links are relative to the dashboard's directory.
- Added 12 tests covering full-workspace summaries, missing artifacts, empty network snapshots, no-changes reports, critical status, HTML generation (including script-free and no-unreplaced-token checks), disabled actions, determinism, the dashboard CLI with and without artifacts, automatic regeneration on discover, and help listing.
- Added no JavaScript frameworks, AI, authentication, backend server, or database.

### EPIC-002 / PR-023 - Read-only Configuration Collection Foundation

- Added `founderos_atlas/config/`: read-only collection of `show running-config` (required) plus best-effort `show startup-config`, `show inventory`, `show license summary`, and `show module` — collection and line-ending normalization only, no analysis or comparison.
- Unsupported, denied, empty, or failed optional commands degrade to per-command statuses and warnings; a lost session skips remaining commands instead of retrying; only a running-config failure raises.
- Added immutable `ConfigurationArtifact` with provenance metadata: hostname, vendor, platform, OS, management IP, collection time (caller-supplied, never the system clock), full command list with statuses, collection status, warnings, line count, and a SHA-256 of the running configuration.
- Added artifact delivery: `running_config.txt`, `configuration_metadata.json` (provenance only — never configuration content), and collected optional outputs, written per device under `configs/<hostname>/`.
- Extended `founderos atlas discover` with a `Collect running configuration? [y/N]` prompt after discovery; on yes, every discovered device is collected over a fresh read-only session and per-device failures never abort the rest.
- Security: configuration content never reaches the console or logs; the `configs/` directory is gitignored; all commands pass the existing read-only `show` allowlist with no configuration mode and no writes.
- Added 12 mocked-transport tests covering successful collection, unsupported commands, denied startup-config, required-failure semantics, optional-disable, read-only command enforcement, metadata generation (including no-content contract), determinism, artifact files, and the CLI confirm/decline/per-device-failure flows.
- Added no diff, AI, compliance, backup scheduler, Git integration, or GUI redesign.

### EPIC-002 / PR-022 - Change Intelligence Foundation

- Added `founderos_atlas/change/`: deterministic topology and inventory change detection between two `TopologySnapshot` values (objects or `topology_snapshot.json` dicts) — not configuration diff.
- Detected changes: new devices (low), removed devices (high), hostname renames (medium, matched by serial/IP/device-ID so renames are never remove-plus-add), management IP (medium), platform (high), OS version (medium), interface count (low), lost neighbors (medium), gained neighbors (low), and discovery failures (medium, recorded via `failed_hosts` snapshot metadata).
- Every `Change` carries category, severity, description, and recommendation; reports sort deterministically by severity/category/subject and compare byte-identically.
- Neighbor comparison operates on undirected logical links (renames translated first), so directional CDP pairs and renames never produce false neighbor churn; links involving new/removed devices are suppressed in favor of the device-level change.
- Added `founderos atlas compare <previous.json> <current.json>` printing a severity summary and writing `change_report.json` and `change_report.md`.
- Morning Brief with a previous snapshot now embeds the change report in metadata, folds change recommendations into the brief, and renders a Change Intelligence markdown section — the `MorningBrief` schema is unchanged.
- Topology viewer optionally highlights new (green), changed (orange), and removed (red ghost) devices when a change report is supplied; rendering is unchanged without one.
- Added 25 tests covering identical snapshots, each change type, rename semantics, no false positives, logical-link dedupe, JSON/Markdown generation, determinism, Morning Brief integration and journey evaluation, viewer highlighting, and the compare CLI.
- Added no running-config diff, AI, GUI redesign, persistence database, SNMP, or NETCONF.

### EPIC-002 / PR-021.1 - Canonical Device Identity & Relationship Reconciliation

- Added a vendor-neutral identity package (`founderos_atlas/identity/`): `DeviceIdentity` (all observed identifiers), `CanonicalDevice` (one merged identity with aliases and discovery history), and `IdentityResolver` with union-find clustering.
- Added configurable, ordered `MatchRule` predicates — exact serial number, shared management IP, and hostname matching (normalized equality plus bare-name == FQDN first label) — extensible for future vendors via `ExtraIdentifierMatch` (chassis ID, system MAC, UUID) without editing existing rules.
- Added hostname normalization for matching only (`R1`, `r1`, `R1.`, `R1.atlas.local` resolve together); display preserves original casing and originals are never destroyed — they become aliases and `observed_*` metadata.
- Wired identity resolution into live multi-hop discovery: neighbor FQDN references now resolve onto discovered devices before reconciliation, so each physical device appears exactly once.
- Collapsed directional neighbor observations (`R1 -> SW1`, `SW1 -> R1`) into one displayed connection in the topology viewer with both interface ends; the versioned `TopologySnapshot` contract keeps directed observations unchanged.
- Viewer displays canonical short hostnames, shows aliases in the node details panel, and includes aliases in search; distinct devices that would share a short label keep their full names (no false merges).
- Added 17 tests covering hostname/FQDN merge, case differences, duplicate-edge collapse, alias preservation, no false merges across domains and similar names, management-IP precedence, future vendor rule extension, determinism, and the end-to-end CML scenario (two devices, one relationship).
- Added no GUI redesign, AI, database, SNMP, NETCONF, vendor-specific hacks, or CML-specific logic; fixture demo behavior is unchanged.

### EPIC-002 / PR-021 - Atlas Multi-hop Discovery Foundation

- Added `discovery/multihop.py`: deterministic breadth-first CDP neighbor traversal from one seed, speaking only through injected `DeviceTransport` factories with the same read-only guarantees.
- Enforced conservative safety limits: default max depth 1, default max devices 10, at most one contact per host, identity-based deduplication of devices reachable via multiple addresses, and no infinite loops.
- Made neighbor failures non-fatal: unreachable or unparseable neighbors are recorded as failed visits and traversal continues; only the seed device is required to succeed.
- Added `run_multihop_discovery` composing traversal with the existing `TopologyReconciler`, `TopologySnapshot`, renderer, and Morning Brief Journey.
- Extended `founderos atlas discover` with optional max depth / max devices prompts (Enter accepts defaults) and a Discovery Progress report showing connected, skipped, and failed devices with reasons, plus final counts and artifact paths.
- Neighbors without an advertised management IP are reported once and skipped; credentials are shared for the run, never stored, and never appear in progress output.
- Added 18 mocked-transport tests covering seed discovery, neighbor traversal, duplicate avoidance, depth/device limits, unreachable neighbors, reconciliation use, artifact generation, determinism, read-only command enforcement, and CLI limit validation.
- Added no SNMP, NETCONF, RESTCONF, GUI, database, AI, credential vault, per-device credentials, scheduling, or CML-specific logic.

### EPIC-002 / PR-020 - Live Discovery Output Pipeline

- Completed the `founderos atlas discover` product pipeline: SSH collection → DiscoveryEngine → TopologyGraph → TopologySnapshot → interactive HTML topology → Morning Brief, reusing every existing component with no business logic in the CLI.
- Added `topology_snapshot.json` delivery via the existing `TopologySnapshotExporter` alongside `atlas_topology.html` and `morning_brief.md`.
- Expanded the CLI report with hostname, platform, management IP, interface count, neighbor count, and all three artifact paths.
- Made zero-neighbor discovery a first-class outcome: prints "No neighbors discovered yet" and still delivers a valid one-device topology, snapshot, and brief.
- Documented the Live Discovery Workflow, expected generated files, CML/physical device equivalence, and troubleshooting in `apps/atlas/README.md`.
- Added mocked-transport tests for snapshot/HTML/brief generation, zero-neighbor success, deterministic output, and network isolation.
- Added no multi-hop discovery, SNMP, NETCONF, GUI, persistence, database, AI, or configuration changes.

### EPIC-002 / PR-019.1 - Global Live Discovery Robustness

- Added Cisco IOSv/virtual-platform `show version` support (banner, revision-line, and processor-line platform patterns) and derived `os_name` (IOS/IOS-XE) from the software banner.
- Made CDP and interface data gracefully optional: zero CDP neighbors is a valid result, unparsed interfaces produce a warning instead of a crash, and adapters can declare `optional_commands`.
- Added deterministic identity fallback: when hostname or management IP cannot be parsed, the connection address (`management_ip_hint`) anchors `device_id`, unknown fields are recorded as `unknown`, and every fallback is captured as a warning in `DiscoveryResult.metadata`.
- Enriched `DiscoveryParseError` with adapter name, command key, missing field, a sanitized ≤300-char output preview (secrets redacted), and parser-mismatch guidance, while remaining backward compatible.
- Added best-effort `terminal length 0` session preparation to the SSH transport; unsupported devices continue safely, raw output is preserved exactly, and no secrets appear in logs or errors.
- Re-parented parsed neighbors onto the resolved device identity in the Discovery Engine for consistency with identity fallback.
- Added 14 robustness tests covering IOSv parsing, zero-neighbor discovery, platform/hostname fallback warnings, diagnostic content, preview truncation, secret redaction, collector/adapter key alignment, and tolerant session preparation.
- Added no CML-specific, physical-device-specific, or FounderOS platform changes; transport, adapter, engine, and topology layers remain separate.

### EPIC-002 / PR-019 - Atlas Real Device Discovery over Read-Only SSH

- Added a vendor-neutral `DeviceTransport` contract with `connect`, `disconnect`, `execute`, and `execute_many`, plus context-manager lifecycle.
- Added a Netmiko-backed `SSHDeviceTransport` for any reachable Cisco IOS/IOS-XE device; simulators (CML, EVE-NG, GNS3) are treated as ordinary SSH endpoints with no simulator-specific logic.
- Enforced a read-only architecture: only `show` commands pass the local allowlist, the transport never enters configuration mode, and no enable escalation occurs.
- Added `DeviceCredentials` with the password excluded from repr; passwords are never logged, persisted, or echoed in errors or CLI output.
- Added typed, user-friendly transport failures for authentication, timeout, SSH unavailability, unsupported platform, permission denial, and lost connections, classified without importing Netmiko.
- Added `run_live_discovery` composing transport collection with the unchanged DiscoveryEngine, TopologyReconciler, and TopologySnapshot.
- Added `founderos atlas discover` prompting for management IP, username, and hidden password, then delivering the topology viewer HTML, Morning Brief, and browser launch.
- Made Netmiko an optional lazily-imported dependency (`pip install founderos-runtime[ssh]`); all automated tests run against mocks with no live devices.
- Added no SNMP, NETCONF, RESTCONF, simulator APIs, persistence, credential storage, multi-hop discovery, or configuration commands.

### EPIC-002 / PR-018 - Atlas Morning Brief Journey

- Added Atlas's first operational utility Workflow and immutable `MorningBrief` Artifact model.
- Added deterministic current/previous Snapshot comparison, status, warning/conflict evidence, recommendations, and Markdown rendering.
- Extended `JourneyRunner` with exact, injected deterministic builders for declared `artifact_creation` steps while preserving planning, validation, authorization, ordering, Evaluation, and result ownership.
- Added a declarative Morning Brief Workflow, Artifact schemas, and deterministic quality rubric.
- Added `founderos atlas morning-brief` to run fixture snapshots through FounderOS Journey infrastructure and deliver `morning_brief.md`.
- Added 11 acceptance tests covering current-only operation, comparison, recommendations, Markdown, Workspace loading, Journey execution, Evaluation, schema conformance, determinism, CLI delivery, and network isolation.
- Added no AI, LLM, live network access, persistence, scheduling, email, notification, GUI, or Project state mutation.

### EPIC-001 / PR-017 - Atlas Interactive Topology Viewer

- Added a pure deterministic `TopologySnapshot` to Cytoscape element and standalone HTML renderer.
- Added a responsive plain-HTML viewer with automatic layout, pan, zoom, fit, vendor colors, hover tooltips, click details, and search highlighting.
- Added `founderos atlas demo topology` to reuse fixture discovery, reconciliation, and Snapshot creation before writing `atlas_topology.html` and opening the default browser.
- Kept observed remote neighbors as explicitly lightweight visualization nodes rather than fabricating discovered device records.
- Added focused renderer and CLI tests covering conversion, HTML behavior, determinism, CDN isolation, network isolation, output delivery, and browser launch injection.
- Added no SSH, SNMP, persistence, database, AI, authentication, real-time update, topology editing, or GUI framework.

### EPIC-001 / PR-016 - Atlas Topology Snapshot Contract

- Added immutable content-addressed TopologySnapshot creation from reconciled TopologyGraph values.
- Included canonical devices/interfaces, directed edges, reconciliation warnings, optional deterministic timestamps, counts, and versioned metadata.
- Added pure defensive dictionary, stable JSON, and human-readable Markdown exports.
- Replaced the preliminary topology schema with a complete versioned Snapshot contract and aligned the topology quality rubric.
- Extended the Atlas CLI demo with snapshot ID, device, edge, warning, and schema-version summary.
- Added 12 tests covering construction, content, warnings, defensive exports, JSON/Markdown, timestamps, ordering, schema validation, content addressing, and no file writes.
- Added no persistence, database, SSH, SNMP, GUI, AI, live discovery, or graph database.

### EPIC-001 / PR-015 - Atlas Multi-Device Topology Reconciliation

- Added `TopologyReconciler` for deterministic merging of multiple DiscoveryResult observations.
- Extended TopologyGraph with identity-aware result/graph merge, device and edge counts, identity lookup, interface retention, structured warnings, and reconciliation summaries.
- Defined hostname, management-IP, serial-number, and explicit-ID matching priority with stable canonical selection.
- Preserved unique interfaces, metadata, and neighbor observations while deduplicating devices and edges.
- Added deterministic conflict warnings instead of silent overwrite.
- Extended the Atlas CLI demo with before/after reconciliation counts, duplicate removal, warnings, and merged topology.
- Added 12 tests covering identity matching, preservation, conflicts, graph merge, summary correctness, determinism, duplicate removal, and fixture-only operation.
- Added no SSH, SNMP, live discovery, persistence, graph database, GUI, AI, or cloud discovery.

### PR-014.1 - Atlas Discovery CLI Demo

- Added `founderos atlas demo discovery` as a thin console demonstration over the existing fixture-only Atlas Discovery Engine.
- Added deterministic plain-text rendering for normalized device, interface, neighbor, topology, and summary information without exposing Python representations.
- Added one CLI integration test covering successful exit, expected report text, and network isolation.
- Added no parser changes, SSH, SNMP, credentials, persistence, AI Provider, API, GUI, or device mutation.

### EPIC-001 / PR-014 - Atlas Discovery Engine Foundation

- Added Atlas as a first-party FounderOS networking App package while retaining both names as internal codenames.
- Added immutable vendor-neutral Device, Interface, Neighbor, Fact, and DiscoveryResult models plus a transport-free DiscoveryAdapter contract.
- Added a deterministic Cisco IOS reference parser for checked-in `show version`, `show ip interface brief`, and `show cdp neighbors detail` fixtures.
- Added an in-memory DiscoveryEngine and deterministic TopologyGraph with idempotent identical duplicates and explicit conflict rejection.
- Added valid Atlas App, utility Workflow, Agent, Artifact schema, Evaluation Rubric, fixture, and documentation assets.
- Added 12 tests covering parsing, normalization, engine behavior, graph behavior, errors, manifest validation, network isolation, fixture-only inputs, and determinism.
- Added no SSH, SNMP, credentials, persistence, database, GUI, API, device mutation, real AI Provider, live multi-hop discovery, cloud discovery, logs, or change intelligence.

### PR-013 - FounderOS CLI Alpha

- Added a standard-library, plain-text public CLI package with `version`, `doctor`, `demo discovery`, and `help` commands.
- Kept planning, validation, authorization, Journey execution, Mock Provider behavior, and Evaluation in their existing runtime components; the CLI delegates once and only renders results.
- Preserved the established local Project CLI commands through an unchanged compatibility adapter while replacing the former single-module layout with a package.
- Added deterministic Doctor checks for runtime availability, bundled manifest loading, Evaluation, and Mock Provider availability.
- Added 10 tests covering commands, successful and failed demo behavior, deterministic output, exit codes, rendering, network isolation, and runtime/file non-mutation.
- Added no interactive prompts, persistence for the Alpha demo, real AI, configuration system, plugins, marketplace, authentication, Web UI, or Kernel mutation.

### PR-012 - Discovery Vertical Slice Foundation

- Added a complete first-party Discovery example package containing Agent, Workflow, App, Evaluation Rubric, input, schema, expected-output, and Mock Provider fixture assets.
- Added a small in-memory demo helper that composes Workspace, Planner, Plan Validation, Authorization, Journey Runner, Mock Provider, and the declared Evaluation Rubric.
- Extended Journey Runner with optional caller-supplied input Artifacts and exact injected rubric resolution while preserving its deterministic default behavior.
- Added 12 tests covering package loading, planning, validation, authorization, execution, fixture output, rubric assessment, result contents, determinism, network isolation, and persistence/runtime non-mutation.
- Added no CLI, real Provider, persistence, human Approval execution, Web UI, authentication, marketplace, Event recording, or Project/Kernel mutation.

### PR-011 - Evaluation Rubric Manifest and Loader Foundation

- Added a strict versioned Evaluation Rubric schema and deterministic Opportunity Report example.
- Extended the stateless Manifest Loader with explicit Evaluation Rubric loading and existing typed validation errors.
- Added immutable EvaluationRubric translation into existing EvaluationRule, EvaluationRequest, and EvaluationRunner contracts.
- Added 11 tests covering schema failures, loading, valid and invalid Artifact evaluation, deterministic scoring, Provider isolation, and runtime non-mutation.
- Added no Journey execution changes, human Approval, persistence, CLI, real Provider, network access, or runtime state mutation.

### PR-010 - Plan Validation and Authorization Foundation

- Added deterministic PlanValidator and immutable ValidationReport contracts covering Workflow, Agent, Artifact, duplicate-ID, dependency-cycle/order, and Evaluation-checkpoint integrity.
- Added a pure AuthorizationEngine with missing-validation denial, unknown-capability denial, high-risk Approval-gate requirements, and safe-plan allowance.
- Integrated both gates into JourneyRunner before any Provider or Evaluation step; denied journeys return descriptive immutable results and perform no work.
- Added 15 focused tests plus preserved all existing Journey behavior.
- Added no human Approval, persistence, CLI, real Provider, network call, runtime Event, or Project/Kernel mutation.

### PR-009 - Founder Journey Runner Foundation

- Added an in-memory deterministic Journey Runner that consumes one Workspace Planner Execution Plan without replanning.
- Added immutable JourneyResult values containing completed/skipped steps, Evaluation results, generated Artifacts, ordered logs, and execution metadata.
- Added sequential Mock Provider Agent-task execution and deterministic Evaluation checkpoints with critical-failure stopping.
- Explicitly skipped Approval, transition-request, and Activity execution rather than claiming unavailable authority or side effects.
- Added 10 tests covering Discovery orchestration, Provider calls, Evaluation success/failure, unknown and empty plans, determinism, summaries, multiple Agent steps, Artifact results, and Workspace non-mutation.
- Added no persistence, CLI, real Provider, human interaction, asynchronous execution, Event recording, or Project/Kernel state mutation.

### PR-008 - Planner Foundation

- Added a read-only Workspace Planner that produces immutable deterministic Execution Plans from validated Workflow manifests.
- Added exact Agent and Artifact resolution, Artifact-dependency topological ordering, cycle detection, and descriptive typed planning failures.
- Added deterministic Evaluation and Approval checkpoint insertion while preserving transition intent as a non-authoritative request.
- Preserved the existing state-aware lifecycle Planner for CLI and vertical-slice compatibility under an explicit internal module.
- Added 10 tests covering plan generation, missing references, cycles, checkpoints, determinism, summaries, invalid definitions, and non-mutation.
- Added no Workflow execution, Provider or Tool calls, Approval execution, persistence, CLI changes, or Kernel state mutation.

### PR-007 - Evaluation Contract and Runner Foundation

- Added immutable EvaluationRule, EvaluationRequest, EvaluationFinding, and EvaluationResult contracts with explicit severity and rule-type enums.
- Added a pure deterministic Evaluation Runner with non-empty content, expected-schema, required-field, schema, minimum-length, regex, and injected custom-rule evaluation.
- Defined unweighted six-decimal scoring, configurable minimum score, and hard blocking for failed error/critical findings.
- Added typed configuration, request, and custom-execution failures with no generic runtime mutation behavior.
- Added 12 tests covering successful assessment, missing fields, empty content, schema mismatch, length, regex, custom rules, deterministic ordering/scoring, multiple findings, critical blocking, invalid configuration, and empty rule lists.
- Kept assessment results separate from persisted runtime Evaluation records and added no Approval, Planner, Workflow/Provider/Tool execution, CLI, persistence, Event, or Kernel mutation.

### PR-006 - Mock Provider Foundation

- Added immutable `ProviderRequest`, `ProviderResponse`, `ProviderStatus`, and structured `ProviderError` contracts.
- Added a deterministic offline Mock Provider with canonical request fingerprints, correlation/idempotency metadata, fallback output, strict JSON fixtures, simulated failures, and expected-output schema validation.
- Added typed request, fixture, and missing-fixture errors with no real Provider SDK, network access, API keys, or external dependency.
- Added 11 tests covering deterministic output, repeated requests, fixtures, missing fixtures, simulated errors, Provider metadata, network isolation, runtime non-mutation, invalid requests, output-schema failures, and immutability.
- Kept Provider behavior disconnected from Workspace, Apps, Workflows, Agents, Activities, authorization, Kernel services, persistence, CLI, and runtime state.

### PR-005 - Workspace Foundation

- Added a read-only in-memory Workspace that discovers Agent, Workflow, and App YAML beneath bounded project roots and delegates validation to PR-004.
- Added deterministic duplicate-ID, exact-reference, runtime/Kernel compatibility, App dependency compatibility, and circular dependency checks.
- Added sorted defensive `apps`, `workflows`, `agents`, `get_*`, and `summary` query APIs with no registration or mutation surface.
- Added typed discovery, duplicate, missing-reference, compatibility, dependency-cycle, and query errors.
- Added 10 tests plus duplicate-kind subtests covering empty, single-App, multi-App, duplicates, missing references, compatibility, queries, summaries, defensive results, and dependency cycles.
- Added no Planner, registry, execution, Provider, Tool, authorization, memory, CLI, persistence, state transition, or Kernel integration.

### PR-004 - Manifest Loader Foundation

- Added a stateless `founderos_runtime.manifest_loader` package with explicit Agent, Workflow, and App loading APIs.
- Added safe YAML parsing, per-kind schema selection, Draft 2020-12 validation, and established Workflow/App semantic validation.
- Added typed missing-file, read, malformed-YAML, invalid-schema, and validation exceptions carrying deterministic `file`, `field`, and `reason` details.
- Added 13 tests covering valid manifests, missing files, malformed YAML/UTF-8, invalid schemas, structural failures, unknown/missing fields, error messages, semantic regressions, deterministic selection, and no caching.
- Promoted PyYAML from development-only to a runtime dependency because manifest parsing is now executable behavior.
- Added no discovery, registry, resolution, installation, execution, Provider, Tool, CLI, State Machine, persistence, or Kernel integration.

### PR-003 - App Package Manifest Schema Foundation

- Added a self-contained JSON Schema Draft 2020-12 App Package Manifest contract expressed as YAML.
- Added a valid Discovery App example indexing the Discovery Workflow, Product Manager and Market Research Agents, Opportunity Report schema, prompt pack, Evaluation rule, policy requirement, deterministic fixture, and documentation.
- Added namespaced package identity, Semantic Versioning, canonical runtime/dependency ranges, first-party publisher metadata, content digest shape, safe package-relative paths, and immutable exact definition references.
- Added deterministic structural and semantic tests for required fields, identity, versions, maturity, non-empty Workflow/Agent indexes, duplicate Workflow IDs, runtime compatibility, dependency format, and prohibited execution/runtime-authority fields.
- Kept the App contract outside the active runtime registry; no loader, registry, marketplace, plugin installation, Workflow execution, Provider, Tool, CLI, or runtime behavior changed.

### PR-002 - Workflow Manifest Schema Foundation

- Added a self-contained JSON Schema Draft 2020-12 Workflow Manifest contract expressed as YAML.
- Added a valid conceptual Discovery Workflow with exact Agent references, Artifact declarations, ordered steps, Evaluation and Approval requirements, transition intent, recovery, and compatibility bounds.
- Structurally separated lifecycle Workflows, which require transition intent, from utility Workflows, which require null exit state and transition intent.
- Added deterministic structural and semantic tests for required fields, canonical IDs, Semantic Versioning, enums, step types, lifecycle/utility rules, and step-to-Agent reference integrity.
- Kept the new schema outside the active runtime registry; no Workflow loader, registry, execution engine, Planner, CLI, Discovery implementation, persistence, or runtime behavior changed.

### PR-001 - Agent Manifest Schema Foundation

- Added a self-contained JSON Schema Draft 2020-12 Agent Manifest contract expressed as YAML.
- Added a valid Product Manager manifest with explicit capabilities, Artifact ports, constraints, Tool-category ceiling, Provider-neutral preferences, Evaluation, handoff, status, and maturity.
- Added deterministic schema tests for required fields, canonical IDs, Semantic Versioning, maturity, Tool categories, capabilities, prohibited runtime/prompt fields, and the example.
- Added PyYAML only to development dependencies; the runtime dependency set and runtime contract loader are unchanged.
- Documented the stateless Agent boundary and its relationships to Apps, Workflows, Providers, Tools, authorization, memory, and the Kernel.

### Milestone 12A - FounderOS v0.2 Architecture Review Board

- Added a formal five-perspective architecture review of the draft FounderOS v0.2 Blueprint.
- Recommended proceeding only after resolving App/Workflow semantics, authorization order, durable execution boundaries, AI safety contracts, and the platform-first milestone sequence.
- Proposed a narrower v0.2 scope centered on first-party App packaging and one package-defined Validation vertical slice.

### Milestone 12B - Blueprint Revision and Architecture Decisions

- Revised the v0.2 Blueprint so App is packaging, Workflow remains execution, and the Kernel remains the sole runtime mutation authority.
- Replaced independent “OS” service implications with a modular-monolith dependency model and explicit outbound ports.
- Defined lifecycle and utility Workflow state authority, first-party App package boundaries, compatibility direction, and v0.2 non-goals.
- Added authorization, durable activity/effect, App package, fake structured-generation Provider, and Validation vertical-slice implementation gates.
- Reconciled roadmap, sprint, project context, README, and architecture decisions around Milestone 12C as the next step.

### Milestone 12C - Authorization Policy Foundation

- Defined runtime authorization concepts, supported Actor/Action/Resource vocabularies, deterministic decision flow, failure semantics, and future RBAC/enterprise compatibility.
- Added placeholder Draft 2020-12 schemas for AuthorizationRequest, AuthorizationDecision, PolicyRule, and AuthorizationPolicy without registering or enforcing them in the runtime.
- Specified a pure PolicyEngine interface using default-deny and deny-overrides semantics with exact Policy versions.
- Added diagrams for command, trust-boundary, and future outbound-execution flows.
- Added ADR-001 establishing that authorization precedes protected mutation while the Kernel and State Machine retain sole mutation authority.
- Clarified that authorization, authentication, and human Approval are separate concerns and that Milestone 12C changes no runtime behavior.

### RFC-0001 - Durable Activity and Side-Effect Contracts

- Defined durable Activity intent, result, lifecycle record, categories, statuses, attempts, policies, and audit facts for all future external operations.
- Defined effectively-once idempotency, deterministic retry, timeout, lease, cancellation, ambiguous-outcome reconciliation, and separate compensation semantics.
- Added placeholder ActivityExecutor, ActivityRegistry, ActivityService, ActivityPolicyEvaluator, and ActivityAuditReader interfaces without runtime implementation.
- Added seven non-loaded Draft 2020-12 Activity schemas and reserved authoritative Activity Event types.
- Added ADR-002 requiring external execution outside Kernel transactions and prohibiting executor repository/Event mutation.
- Updated the v0.2 Blueprint, runtime boundaries, observability, roadmap, sprint, project context, decisions, and README without adding any executor, Provider, Tool, or side effect.

### Milestone 11 - Developer Experience and Test Stability

- Added official PowerShell and POSIX test scripts with per-test progress and slow-test diagnostics.
- Added a `dev` dependency group containing pytest and documented editable developer installation.
- Diagnosed a protected, non-inheriting ACL on `.pytest_cache` as the cause of Windows cache access failures and reset it to inherited workspace permissions.
- Added Windows troubleshooting guidance and a policy-independent official test command.
- Verified that the reported apparent hang was the quiet 80–90 second suite run, not a surviving thread, subprocess, or shutdown deadlock.

### Milestone 11.1 - Developer Experience Bug Fix

- Removed the alternate pytest cache-path workaround after identifying the filesystem ACL root cause.
- Restored pytest's standard `.pytest_cache` behavior and documented exact ACL inspection and repair commands.
- Verified that the exact `python -m pytest -q` command returns immediately after the passing summary without warnings or interruption.

### Milestone 11.2 - Windows Stale-Lock Probe Fix

- Replaced POSIX-style `os.kill(pid, 0)` process probing on Windows with a non-signalling Win32 process-handle query.
- Guaranteed that the Windows process handle is closed after every successful probe.
- Made access-denied and indeterminate process checks fail closed so stale-lock recovery cannot remove a potentially live owner's lock.
- Added a Windows regression test proving stale-lock inspection never calls `os.kill`.

### Added

- Added deterministic Discovery Workflow v1 with no model, web, or external API calls.
- Added the Opportunity Report content contract and deterministic six-factor scoring/ranking.
- Added Discovery runs, quality Evaluation, human Approval, selection Decision, and guarded transitions to `OPPORTUNITY_SELECTED`.
- Added `founderos discovery` and `founderos approve-opportunity` with local JSON, correlation, persistence, audit, and idempotency.
- Added 11 Discovery tests covering prerequisites, scoring, approval gating, planner behavior, CLI, audit, redaction, idempotency, and replay.

- Added read-only `RuntimeDiagnostics` summaries for Project state, Events, WorkflowRuns, AgentRuns, Approvals, Evaluations, Transitions, Artifacts, and persistence health.
- Added `founderos audit`, `founderos runs`, and `founderos transitions` commands.
- Added one root command correlation across each CLI mutation, application call, runtime records, and child Events.
- Added approval-to-transition-to-Artifact traceability, ordered command summaries, operation timing, and audit consistency checks.
- Added recursive sensitive-field redaction and explicit `--include-sensitive` opt-in for Founder Brief content.
- Added seven diagnostics tests covering correlation, ordering, traceability, redaction, recovery consistency, completeness, and non-mutation.

- Added public repository import/export ports so local persistence no longer hydrates through private insertion methods.
- Added reusable Artifact, Evaluation, and Approval lifecycle services; existing WorkflowRun and AgentRun services remain the run boundaries.
- Added persistence format v2 with a restart-safe command-result journal and CLI `--idempotency-key` support for `new`, `founder-brief`, and `approve`.
- Added lock inspection and guarded stale-lock removal requiring an exact PID, a dead owner, and a minimum age.
- Added write-phase failure injection and eight service-boundary tests covering ports, lifecycle delegation, idempotency, lock policy, and recovery paths.

- Added exclusive local writer locks and optimistic store revisions to reject concurrent and stale writes.
- Added validated pre-write backups and explicit `founderos recover` restoration.
- Added `founderos health` for schema, Event replay, content digest, lock, format, and backup checks.
- Added an explicit version-to-version migration registry with v0-to-v1 compatibility and future-version rejection.
- Added 10 persistence-hardening tests plus CLI health coverage for corruption, missing files, stale writes, locks, backup restore, replay mismatch, and migrations.

- Added the standard-library `founderos` CLI with `new`, `status`, `plan`, `founder-brief`, `approve`, `decisions`, and `events` commands.
- Added a thin application facade that delegates planning and mutations to existing runtime services.
- Added validated local persistence using `project-state.json`, ordered `events.jsonl`, and immutable Artifact JSON files under `.founderos/`.
- Added nine CLI acceptance tests covering restart-style reloads, runtime guard enforcement, ordered Events, and the complete Founder Brief path.

- Added the first executable Founder Setup vertical slice: project start/resume, structured Founder Brief production, schema evaluation, human approval, guarded completion, and replay verification.
- Added `founder-brief-content.schema.json`, immutable canonical-JSON content storage, Founder Setup Agent/Workflow definitions, and six end-to-end tests.
- Added approved artifact references to the Project aggregate when a guarded transition applies.

- Added immutable ExecutionContext and ExecutionPlan read models.
- Added a deterministic Runtime Planner composed of ArtifactPlanner, WorkflowSelector, and AgentRouter.
- Added planning rules for all 22 known lifecycle states while reusing State Machine routes and guard requirements.
- Added missing-artifact blocking, workflow recommendations, agent-role routing, allowed transitions, quality-gate summaries, and next-state candidates.
- Added 13 planner tests covering required early lifecycle routes, approved-artifact filtering, plan completeness, context construction, unknown states, non-mutation, determinism, and rule/State Machine consistency.

- Added the Python 3.11+ `founderos_runtime` package with `jsonschema` 4.x as its only runtime dependency.
- Added a Draft 2020-12 contract registry with local reference resolution and RFC 3339 format enforcement.
- Added defensive in-memory repositories for Project, Artifact, Decision, WorkflowRun, AgentRun, Event, Approval, Evaluation, and Transition records, plus Agent and Workflow definitions.
- Added Project State creation/update operations with optimistic revision checks and atomic Event persistence.
- Added guarded State Machine transitions with exact evidence resolution, human Approval checks, rejection outcomes, idempotent correlation handling, and rollback on commit failure.
- Added ordered Event streams and deterministic Project event replay.
- Added basic WorkflowRun and AgentRun lifecycle services with bounded retry exhaustion behavior.
- Added 19 automated tests covering all 14 contract acceptance scenarios, schema loading, transaction rollback, revision conflicts, ordered Events, and defensive repository reads.

- Added JSON Schema Draft 2020-12 contracts under `runtime/contracts/` for Agent, Artifact, Workflow, State, Decision, Project, WorkflowRun, AgentRun, Transition, Evaluation, Approval, and Event.
- Added canonical ID, version, revision, timestamp, actor, status, and typed-reference conventions.
- Added transition guard ordering, complete allowed routes, atomic mutation rules, rejection behavior, and recovery semantics.
- Added persistence ownership, state-mutation boundaries, event ordering, concurrency, and artifact-content boundaries.
- Added 14 contract-level acceptance scenarios for structural, referential, transactional, recovery, replay, and idempotency behavior.

### Changed

- Established `.ai/` as the official location for AI governance and onboarding documents.
- Corrected governance document references to use `.ai/` paths.
- Reconciled project status across README, project context, roadmap, sprint, and decisions.
- Added a thin `runtime/master-orchestrator.md` specification aligned with the architecture and state catalogue.
- Marked empty Markdown scaffolds as planned placeholders instead of implied implementations.
- Set executable runtime contracts as the next milestone.
- Replaced runtime component placeholders with contract-level Project State, Workflow Engine, Agent Registry, Artifact Registry, Decision Engine, and Knowledge Base specifications.
- Expanded the State Machine from a state list into guarded transition and recovery contracts.
- Updated the Master Orchestrator to depend on the completed contract specifications while remaining unimplemented.
- Marked Executable Runtime Contracts complete and Runtime Foundation as the next milestone.
- Marked Runtime Foundation complete and First Executable Vertical Slice as the next milestone.
- Clarified that `Project.last_event_sequence` tracks the latest aggregate-mutating Event reflected by the Project snapshot; the Event repository owns the complete audit-stream sequence.
- Marked the Runtime Planner Engine complete and moved the first Founder Brief vertical slice to Milestone 5.

## v0.1-alpha

- Created initial FounderOS repository structure
- Added runtime, agents, prompts, templates, domains, examples, architecture and roadmap folders
