# Atlas

## Purpose

Atlas is the first flagship first-party networking App built on the FounderOS platform. Both names remain internal codenames. FounderOS supplies platform planning, Journey execution, validation, authorization, Evaluation, Artifact, and deterministic Workflow boundaries; Atlas owns networking models, adapters, normalized facts, and topology behavior.

## PR-014 Scope

This package demonstrates deterministic network discovery from checked-in Cisco IOS command-output fixtures. It includes declarative App, utility Workflow, Agent, Artifact schema, Evaluation Rubric, and fixture assets. The Python implementation parses only caller-supplied text and operates entirely in memory.

Atlas is vendor-neutral by design. Cisco IOS is the first reference adapter because it provides concrete acceptance data, not because Cisco is the product boundary.

## Inputs and Outputs

Input is a mapping containing `show version`, `show ip interface brief`, and `show cdp neighbors detail` text. Output is a vendor-neutral `DiscoveryResult` containing one device, interfaces, neighbors, and provenance facts. `TopologyGraph` projects results into nodes and edges.

## Boundaries

There is no SSH, SNMP, credential handling, device mutation, persistence, database, real AI Provider, API, GUI, live multi-hop discovery, cloud discovery, log ingestion, or change intelligence. Real device collection must later use authorized durable Activity/transport boundaries; it must not be added to parsers.

## Running the Atlas Discovery Demo

Install FounderOS in editable mode, then run:

```powershell
founderos atlas demo discovery
```

The command reads only the bundled Cisco IOS fixture files, invokes the existing `DiscoveryEngine`, creates a second deterministic mock observation, reconciles both observations into an in-memory `TopologyGraph`, and prints normalized device and topology facts. It performs no network access, credential handling, persistence, device mutation, or AI call.

## Topology Reconciliation

`TopologyReconciler` merges multiple `DiscoveryResult` observations into one coherent graph. Device identity matching is deterministic and follows this priority: hostname, management IP, serial number when present, then explicit device ID. Results are sorted before merge so input order cannot choose a different canonical device.

Reconciliation preserves normalized interfaces, device metadata, and all unique neighbor observations. Identical devices and relationships are idempotent. If matching observations disagree about a device, interface, or metadata value, Atlas keeps the deterministic canonical value and records a structured warning; it never silently overwrites the conflict.

`TopologyGraph` now supports `merge_discovery_result()`, `merge_graph()`, `device_count()`, `edge_count()`, `find_device()`, `interfaces()`, `neighbors()`, `warnings()`, and an expanded `summary()`.

## Topology Snapshot Contract

`TopologySnapshot.from_graph()` converts the current reconciled graph into an immutable, versioned Artifact-shaped value. It contains canonical devices and their interfaces, directed edges, reconciliation warnings, device/edge counts, and deterministic metadata.

Snapshot IDs are SHA-256 content addresses over canonical snapshot content. `created_at` is optional and never reads the system clock; callers may supply a deterministic timestamp when their workflow owns one. `TopologySnapshotExporter` returns defensive dictionaries, canonical formatted JSON, or human-readable Markdown entirely in memory.

The contract is described by `manifests/schemas/topology-snapshot.schema.json`, and the Atlas topology rubric now evaluates its `devices`, `edges`, and `warnings` collections.

## Topology Viewer Demo

Run the interactive viewer from an editable installation:

```powershell
founderos atlas demo topology
```

The command reuses the fixture-only Discovery Engine, reconciliation, and snapshot pipeline. It writes `atlas_topology.html` in the current directory and asks the default browser to open it. The page supports pan, zoom, fit, deterministic node and edge rendering, vendor colors, hover details, click-through device information, and search highlighting.

The renderer is a pure Snapshot-to-HTML adapter. It does not discover devices, mutate the graph, persist topology state, or make a Python network request. The generated page loads the pinned Cytoscape.js browser library from a CDN, so first-time interactive viewing requires browser access to that single asset.

## Morning Brief Journey

Run Atlas's first operational FounderOS Journey:

```powershell
founderos atlas morning-brief
```

The command loads deterministic fixture snapshots, then invokes the declared utility Workflow through FounderOS Workspace, Planner, plan validation, authorization, Journey Runner, and Evaluation boundaries. It prints an operational summary and writes `morning_brief.md` in the current directory.

`MorningBrief` contains overall status, deterministic generation time, topology counts, new/removed/changed devices, warnings, reconciliation conflicts, recommendations, and source Snapshot metadata. The current Snapshot is required; a previous Snapshot is optional. When no timestamp is supplied by the caller or Snapshot, the Artifact records `unrecorded` rather than reading the system clock.

The Journey performs no AI call, network access, Project state transition, persistence, scheduling, email, notification, or GUI operation. Markdown file delivery belongs to the CLI, not the Journey.

## Live Discovery Workflow

Discover a real, reachable Cisco IOS/IOS-XE device over read-only SSH:

```powershell
pip install founderos-runtime[ssh]
founderos atlas discover
```

The command prompts for the seed management IP, username, password (hidden,
never stored or logged), and optional traversal limits — max depth (default
1) and max devices (default 10; press Enter to accept defaults) — then runs
the complete unified pipeline with step-by-step progress ([1/9]…[9/9]):

```
Discovery (SSH collection → parsers → multi-hop traversal → reconciliation)
→ Configuration collection (prompted once)
→ Load previous baseline from .atlas/history (automatic)
→ Topology comparison → change_report.json / change_report.md
→ Configuration comparison → config_change_report.json / config_change_report.md
→ Topology viewer (change-highlighted, enriched node details) + snapshot
→ Morning Brief (baselined, with Today's Summary and run timing)
→ Archive everything into history
→ Dashboard refresh
```

No manual `compare`, `config-diff`, `dashboard`, or `history` invocation is
needed after discovery — those commands remain available for on-demand use.
Change reports are only written when a baseline exists; Atlas never invents
a comparison.

Multi-hop discovery is deliberately controlled: each host is contacted at
most once, devices reachable via multiple addresses are deduplicated by
identity, an unreachable neighbor is recorded as failed and skipped rather
than aborting the run, and traversal stops at the depth/device limits. Only
the seed device is required to succeed.

### Canonical device identity

Real networks name the same device differently per source — `R1` in
`show version`, `R1.atlas.local` over CDP. The identity resolver
(`src/founderos_atlas/identity/`, see its README) clusters observations and
references with configurable, vendor-neutral matching rules (serial number,
management IP, hostname/FQDN), so each physical device appears exactly once,
displayed by its canonical short name. The two directional CDP observations
of one link render as a single connection in the viewer, and all original
names remain available as aliases in the node details panel.

The transport is read-only by architecture: only `show` commands pass the
local allowlist, configuration mode is never entered, and `terminal length 0`
session preparation is best-effort (devices without it still work).

### Expected files generated

All files are written to the current directory:

| File | Content |
| --- | --- |
| `atlas_topology.html` | Interactive topology viewer (pan, zoom, search) |
| `topology_snapshot.json` | Canonical content-addressed `TopologySnapshot` |
| `morning_brief.md` | Evaluated operational Morning Brief |

A device with zero CDP neighbors is a valid result: the CLI prints
`No neighbors discovered yet` and still produces a one-device topology,
snapshot, and brief.

### Configuration collection

After a successful discovery, Atlas asks `Collect running configuration?
[y/N]`. On `y`, every discovered device is collected over a fresh read-only
session (`show running-config` required; startup-config, inventory, license,
and module best-effort) and written to `configs/<hostname>/` as
`running_config.txt` plus `configuration_metadata.json` (provenance only —
never configuration content). Unsupported commands degrade to warnings, and
a per-device failure never aborts the rest. Collected configurations are
sensitive material: the CLI prints only statuses and paths, and `configs/`
is gitignored. See `src/founderos_atlas/config/README.md` for the read-only
and security design.

### CML / physical device note

Atlas treats Cisco Modeling Labs, EVE-NG, GNS3, and physical hardware
identically: each is just a reachable SSH endpoint. No simulator API is
called and no simulator-specific logic exists. Point `founderos atlas
discover` at any management IP that answers SSH with Cisco IOS/IOS-XE
credentials — including CML node management addresses.

### Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `Netmiko is required for live SSH discovery` | Install the transport extra: `pip install founderos-runtime[ssh]` |
| `Authentication failed for <ip>` | Verify the username/password; check the VTY login method (`login local` vs AAA) |
| `Connection to <ip> timed out` | Device unreachable: verify the management IP, routing/VPN path, and that SSH is enabled (`ip ssh version 2`, `transport input ssh`) |
| `SSH is unavailable on <ip>` | SSH refused: the device may only allow telnet, or a firewall blocks port 22 |
| `Device <ip> denied 'show ...'` | The account privilege level cannot run the command; use a level with `show` access |
| `Device <ip> did not recognize 'show ...'` | Probably not a Cisco IOS/IOS-XE device; other platforms need their own adapter |
| Parse error mentioning `adapter: CiscoIOSAdapter` | The device output shape is new to the parser. The error includes the command, missing field, and a sanitized output preview — capture the full command output and extend the adapter |
| `No neighbors discovered yet` | Not an error: CDP is disabled or the device genuinely has no CDP neighbors (`show cdp` to confirm) |
| `[failed] <ip> - ...` in Discovery Progress | A CDP neighbor was unreachable or rejected the shared credentials; the rest of the discovery continued. Verify SSH reachability and that the same credentials work on that device |
| Neighbor skipped with `no management IP advertised over CDP` | The neighbor does not advertise an address Atlas can connect to; discover it directly by its management IP |
| Unknown platform/os fields with warnings | Identity fallback engaged; discovery still completes and warnings list what could not be parsed |

## Change Intelligence

Compare any two topology snapshots into a classified, deterministic change
report — topology and inventory change detection, not configuration diff:

```powershell
founderos atlas compare previous_snapshot.json current_snapshot.json
```

The command prints a severity summary and writes `change_report.json` and
`change_report.md` in the current directory. Detected changes cover new and
removed devices, hostname renames (matched by serial/IP so a rename is never
misreported as remove-plus-add), management IP, platform, and OS version
changes, interface count changes, lost/gained neighbor adjacencies, and
discovery failures recorded by the run. Every change carries a category,
severity, description, and recommendation.

When `founderos atlas morning-brief` (or the Morning Brief Journey) receives
a previous snapshot, the brief automatically embeds the change report: a
Change Intelligence section with a severity summary, each detected change,
and its recommendation. The topology viewer can additionally highlight new
(green), changed (orange), and removed (red) devices when a comparison is
supplied to the renderer. See `src/founderos_atlas/change/README.md`.

## Executive Dashboard

Generate the Atlas operational summary — a professional landing page over
everything Atlas has produced, not a monitoring dashboard:

```powershell
founderos atlas dashboard
```

The command writes a static, script-free `dashboard.html` in the current
directory and opens the browser. It shows network status (Healthy / Warning
/ Critical, or Unknown before the first discovery), summary tiles (devices,
relationships, discovery success, configurations collected, recent
changes), the latest change highlights, recent activity, and quick-action
links to the topology viewer, Morning Brief, change report, configurations,
and snapshot. Missing artifacts degrade gracefully to "not yet generated".

`founderos atlas discover` regenerates the dashboard automatically after
every successful discovery. See `src/founderos_atlas/dashboard/README.md`.

## Historical Timeline & Network Memory

Every successful `founderos atlas discover` is automatically preserved
under `.atlas/history/<timestamp>/` — the topology snapshot, interactive
viewer, Morning Brief, dashboard, collected configurations, and a
self-describing `discovery_metadata.json` (start/end time, duration,
device and relationship counts, warnings, failures, configuration status,
quality score, discovery version). Records are never overwritten; a
same-second collision gets a numeric suffix, and corrupt records are
reported without breaking the rest of history.

```powershell
founderos atlas history    # list every preserved discovery
founderos atlas timeline   # generate timeline.md: day-grouped story with
                           # change intelligence between consecutive runs
```

Open any record's `atlas_topology.html` to view that discovery's topology;
the current topology remains the default viewer. The dashboard shows the
last discovery time, the last five discoveries, and links to history and
the timeline. The history layer is the only place Atlas reads the system
clock (injectable for tests); the deterministic discovery core remains
clock-free. There is no automatic pruning — retention is an operator
decision. See `src/founderos_atlas/history/README.md` for the repository
design and future extensibility (configuration diff, incident replay,
historical playback, AI reasoning).

## Configuration Intelligence

Compare two collected configurations into a classified, secret-masked
change report — not a raw diff:

```powershell
founderos atlas config-diff configs\R1\old.txt configs\R1\running_config.txt
founderos atlas config-diff --latest R1
```

The `--latest` form compares the two most recent discoveries in
`.atlas/history/` that collected a configuration for that hostname. Both
forms write `config_change_report.json` and `config_change_report.md` and
print a severity summary. Changes are section-aware (interfaces, OSPF,
BGP, routing, static routes, VLANs, ACLs, NAT, logging, SNMP, NTP, AAA,
line/VTY, other) with severity and a recommendation per change. Any line
containing `password`, `secret`, `key`, `community`, `token`, or
`credential` is masked before it ever reaches a report. The dashboard
shows a Configuration Changes card when a report exists. See
`src/founderos_atlas/config_intelligence/README.md`.

## Incident Investigation

Structure an incident investigation from evidence Atlas already holds —
deterministic, honest, and never inventive:

```powershell
founderos atlas investigate
Incident title: VLAN 10 outage
Incident description: VLAN 10 cannot access internet via R1
```

Devices named in the description (hostnames, identity aliases, or
management IPs) are matched against the current topology; topology links,
change-report entries, and configuration-change entries touching those
devices become sourced evidence; keyword-driven investigation steps (VLAN,
gateway, slowness, connectivity) become recommendations. Missing artifacts
are stated exactly ("Topology change evidence is not available." /
"Configuration change evidence is not available.") and confidence is
scored deterministically (low / medium / high). Writes
`incident_report.md` and `incident_report.json`; the dashboard shows a
Recent Incident Investigation card with a link. See
`src/founderos_atlas/incidents/README.md`.

## Web GUI (local alpha)

Normal users can drive Atlas from a browser instead of the CLI:

```powershell
pip install -e ".[web,credentials]"
founderos atlas web
```

```
Atlas web UI running at:
http://127.0.0.1:8765
```

The browser opens automatically to a professional shell — a left sidebar
(Dashboard, Discover, Profiles, Topology, History, Changes, Incidents,
Settings) and an "Atlas · Enterprise Network Intelligence" header. Create or
select a saved profile, click **Run Discovery**, and view the topology,
dashboard, history, and change reports. The GUI calls the same in-process
backend services as the CLI (never a subprocess) and stores no passwords in
HTML, responses, or logs.

**Multiple networks.** A Network selector in the header switches the
Dashboard, Topology, History, Changes, and Incidents pages between:

- one saved profile (that network's own data only),
- **All Networks** — the latest successful state of every active network
  combined (total counts, per-network status cards, merged device inventory
  and history), and
- **Local workspace** — data produced by profile-less CLI discovery in the
  current directory, shown only when such data exists.

**Legacy-data policy.** Once at least one profile has completed a scoped
discovery, the Local workspace is treated as a legacy archive: it drops out
of All Networks aggregation (no duplicate devices, inflated counts, or
stale health), the selector labels it "Local workspace (legacy)", and its
data remains fully intact and viewable by selecting it directly. While no
profile has discovered yet, the Local workspace continues to power All
Networks exactly as before, so pre-profile installations lose nothing.

The All Networks topology page is deliberately a **combined device
inventory plus per-network interactive viewers** — networks keep separate
graphs because hostnames may repeat across sites; a single federated
cross-network graph is future work. Devices are never deduplicated by
hostname or IP across profiles: two sites may legitimately reuse RFC1918
addresses and hostnames.

The selection persists while you browse and is always visible in the page
title. Running a discovery automatically focuses the GUI on that profile's
network.

**GUI-driven discovery (PR-032).** The Discover page runs real discoveries
end to end: pick a network (with All Networks active you choose explicitly —
Atlas never picks a profile for you), click **Run Discovery**, and the run
executes in the background while you keep using the GUI. Progress is real:
seven stages driven by actual pipeline activity, the device currently being
contacted, and the number of devices discovered — percentages are
stage-based and labelled as such, never simulated. On completion the page
shows devices, relationships, configurations, and duration with one-click
links to that network's Topology, Changes, and Dashboard, all freshly
up to date without restarting the server. Failures appear as plain-language
guidance (wrong credentials → which profile to fix; unreachable device →
what to check); technical detail stays in the job log. A second click while
a network is already discovering re-attaches to the running job instead of
starting a duplicate; discovery execution is serialized in this local
alpha. Refreshing or closing the browser never cancels a run; if the Atlas
server itself restarts mid-run, the job is marked *interrupted* rather than
left running forever. The GUI and CLI execute the same discovery pipeline —
credentials are resolved server-side from the secure store and never reach
the browser.

This is a **local, single-user alpha GUI**: it binds to `127.0.0.1` only,
has no authentication, and is not a production or multi-user web deployment.
The interactive CLI continues to work unchanged. See
`src/founderos_atlas/web/README.md`.

## Saved Discovery Profiles

Save a discovery target and its settings once, then reuse them without
re-entering the IP, username, or password:

```powershell
pip install founderos-runtime[credentials]   # OS-native secure credential storage

founderos atlas profile add
  Profile name: Hyderabad Lab
  Site name [optional]: CML Lab
  Management IP: 192.168.1.12
  Username: atlas
  Password: (hidden, stored securely)
  Max depth [1]:
  Max devices [10]:
  Collect running configuration? [y/N]: y

founderos atlas profile list
founderos atlas profile show "Hyderabad Lab"
founderos atlas profile update "Hyderabad Lab"
founderos atlas profile delete "Hyderabad Lab"

founderos atlas discover --profile "Hyderabad Lab"
```

Install the credential extra from the repository checkout in editable mode
so the metadata resolves correctly:

```powershell
pip install -e ".[credentials]"
```

Profiles are stored under `~/.atlas/workspace/profiles.json` (override with
`ATLAS_HOME`). The password is **never** written there — only a credential
reference is saved; the secret lives in your OS keyring. Passwords are never
printed or included in any report, snapshot, dashboard, or history record.
`founderos atlas discover --profile <name>` loads everything from the
profile and runs the full unified pipeline unchanged. The interactive
`founderos atlas discover` (no profile) continues to work exactly as before.

This is the backend foundation for the Atlas GUI (PR-031): all logic lives
in a reusable `ProfileService`, which the GUI will call directly. See
`src/founderos_atlas/workspace/README.md`.

### Profile-scoped discovery isolation (PR-031A)

Each profile is an **independent discovery scope**. A discovery run for a
profile writes everything — the current topology snapshot, viewer, morning
brief, dashboard, change/config/state reports, collected configurations,
and the discovery history — into that profile's own workspace at
`<workdir>/.atlas/profiles/<profile_id>/`. Comparison baselines come only
from the same profile's previous run, so discovering one lab never marks
another lab's devices as removed, missing, or changed. Genuine changes
within one profile are still detected exactly as before.

The scope key is the profile's stable internal `profile_id`, not its
display name: renaming a profile (GUI edit form, or
`ProfileService.update_profile(new_name=...)`) keeps all of its history,
baselines, credentials, and reports.

Read-side CLI commands accept `--profile <name>` to address a profile's
scope:

```powershell
founderos atlas history   --profile "Hyderabad Lab"
founderos atlas timeline  --profile "Hyderabad Lab"
founderos atlas dashboard --profile "Hyderabad Lab"
founderos atlas investigate --profile "Hyderabad Lab"
founderos atlas config-diff --latest R1 --profile "Hyderabad Lab"
founderos atlas state-diff  --latest --profile "Hyderabad Lab"
```

**Backward compatibility.** Profile-less interactive discovery keeps the
classic layout (artifacts in the working directory, history in
`.atlas/history`) — this is the *default scope*, shown as "Local workspace"
in the GUI. History recorded before PR-031A stays there and is deliberately
never reassigned to a profile: Atlas cannot know which network produced it,
so guessing would corrupt history. Each profile's scope starts empty and
builds its own baseline from its first scoped discovery.

## Enterprise Discovery (PR-033)

A discovery profile is an **entry point and policy — not a site boundary**.
One discovery may legitimately cross sites (campus → WAN → branch) when
policy allows, while independent runs still never mark each other's devices
removed.

- **Seeds & boundaries.** A profile may carry additional seed devices plus a
  boundary policy: include/exclude ranges, do-not-follow hostname globs,
  followed protocols. Out-of-boundary neighbors are *recorded* with a
  structured reason (denied / observe-only) but never traversed — and never
  erased. Uncertainty never auto-traverses.
- **Credential sets.** The Credentials page manages named sets whose entries
  have a priority and a scope (vendor, platform, hostname patterns, IP
  ranges, sites). During discovery Atlas resolves a bounded, deterministic
  candidate list per device: a previously successful credential first; the
  profile's own credential first **on its seed devices**; on every other
  device the best-scoped matching entries (exact host > range/pattern >
  vendor/platform > site) before the generic profile credential, with
  unrestricted fallbacks last. Atlas stops at the first success, never
  retries a failed credential on the same device, and remembers only the
  *reference* that worked so the next run needs one attempt. Attempts are
  bounded to protect accounts from lockout; secrets stay in the OS keyring,
  never in files, provenance, or the GUI.
- **Sites.** Site assignment is evidence-based: explicit assignments are
  high-confidence; hostname conventions and profile hints assign with
  low/medium confidence; network ranges only corroborate — a subnet alone
  never forces a site, and Atlas honestly reports *unknown* or *ambiguous*.
  Define sites in `<workspace>/sites.json` (hostname patterns, ranges,
  explicit devices).
- **Enterprise topology.** Topology → All Networks shows canonical
  enterprise devices: multiple profiles observing the same physical device
  (matching serial numbers) appear as one row with full provenance — which
  networks observed it, which run, which credential reference worked — plus
  site and confidence, filterable by site including "unknown". Hostname or
  IP reuse across administrative domains is never falsely merged.
- **Per-profile baselines are untouched**: change detection still compares
  each profile only against its own previous run.

Migration: existing profiles work unchanged — the saved seed is seed #1 and
the saved credential is the first credential candidate. Nothing is
rewritten or discarded.

## Operational State Intelligence

Atlas detects operational changes in the running network between
discoveries — even when the saved configuration has not changed. This is
the third change dimension, alongside topology and configuration
intelligence: interface status up → down, line protocol up → down (reported
separately from an administrative shutdown), IP address changes, and new or
removed interfaces. Interface state already lives inside every topology
snapshot (`show ip interface brief`), so no extra collection is required.

```powershell
founderos atlas state-diff previous_snapshot.json current_snapshot.json
founderos atlas state-diff --latest
```

Both forms write `state_change_report.json` and `state_change_report.md`.
Operational comparison also runs automatically inside `founderos atlas
discover` when a baseline exists (pipeline step 5, "Comparing topology &
state"). When operational changes exist, the Morning Brief network status
becomes Attention Required and reports "N interface(s) down" — distinct
from topology and configuration changes — and the dashboard shows an
Operational Changes card. See `src/founderos_atlas/state/README.md`.

## Enterprise Intelligence (PR-034)

Every discovery now ends with Atlas reviewing the network the way a senior
engineer would, and writing its conclusions to
`intelligence_report.json`/`.md` (profile-scoped, archived in history):

- **Enterprise Health 0–100, explained.** Not a traffic light: a calculated
  score where every point is a named factor with evidence (interface
  failures −8 each, authentication failures −8, unreachable devices −6,
  topology/configuration changes, repeated instability, staleness; credits
  for recoveries and stability — all capped and documented). Confidence
  states how good the evidence is, and the trend compares against the
  previous run's archived score.
- **Top 5 priorities**, ranked by urgency, severity, risk, blast radius
  (real topology degree), recurrence, and confidence — never an
  undifferentiated event list.
- **Recommendations with likely cause and next step** — cross-signal: an
  interface failure on a device whose configuration also changed says
  "compare the configuration diff before investigating hardware".
- **Trends**: health trajectory, configuration churn, recurring
  instability, topology stability across recent discoveries.
- **Morning Brief v2** opens with Enterprise Health, Top Risks, Top
  Recommendations, Changes Since Yesterday, Biggest Improvement/Regression,
  and a Suggested Investigation. The dashboard and web GUI show the health
  tile, trend, priorities, and recommendations; All Networks lists health
  per network.

Everything is deterministic and rule-based — no AI. The JSON report is the
contract a future AI layer will consume (summary, evidence, risk,
confidence, recommendations) without recomputing anything.

## Root Cause Analysis (PR-035)

Atlas explains **why** — with evidence, never with AI. Every discovery
writes `root_cause_report.json`/`.md` (profile-scoped, archived in
history):

- observed problems (failed interfaces, vanished devices, devices that
  would not answer) each get **competing hypotheses** — configuration
  change, physical failure, deliberate shutdown, authentication issue,
  upstream isolation, expected maintenance — with supporting **and
  contradicting** evidence listed;
- **confidence is calculated, banded (very-high/high/medium/low), and
  never 100%** — the arithmetic is documented in the report;
- the **reasoning chain** follows the causal graph (configuration →
  interface → protocol → topology) and cites an evidence id in every
  sentence, so you can inspect exactly why Atlas concluded what it did;
- correlation only ever links evidence sharing a device, an interface, or
  a *real previous-topology adjacency* — unrelated events are never
  stitched together;
- **incidents automatically include the analysis**, the dashboard leads
  with *Most Likely Root Cause* when confidence is high, and the Morning
  Brief adds *Most Important Root Cause*;
- **historical replay**: the same engine re-analyzes any archived
  discovery's stored evidence and reproduces the stored explanation byte
  for byte — "what happened yesterday" is a query, not a memory.

## Predictive Change Intelligence (PR-036B)

Ask Atlas **"what happens if I make this change?"** before touching the
network. The **Predict** page takes a proposed interface shutdown (device,
interface, optional reason / maintenance window / requester) and answers
deterministically from the network's own evidence:

- predicted outcomes with likelihoods (expected / probable / possible);
- **blast radius** — devices, interfaces, sites that lose connectivity,
  plus the projected enterprise-health impact;
- **operational risk** (Low/Medium/High/Critical) from documented factors
  a CAB reviewer can add up — broken forwarding paths, unknown redundancy
  (**never assumed**), current enterprise health, historical instability;
- a **recommendation with the WHY**: CAB approval / investigate redundancy
  first / maintenance window / fresh discovery / proceed;
- **rollback**: complexity, prerequisites, honest irreversibility;
- **confidence** that grows with evidence and never reaches 100%, and an
  explicit list of what Atlas cannot see.

Predictions are **plane-aware** (PR-036C): every result evaluates the
Management, Control, Data, and Observability planes separately — so
shutting an SVI that owns the very address Atlas manages the device
through says **Management Plane: Lost** ("Vlan1 owns 10.10.10.2, the
management address Atlas uses; discovery, configuration collection, and
monitoring using this address may become unavailable") with the top
recommendation *"Do not proceed until an alternate management path is
verified"* — while honestly noting that physical links stay up and that
data-plane impact is Unknown without gateway evidence. Alternate
management paths count only when verified; candidates are never assumed
reachable. Each plane carries its own confidence.

The dashboard shows the latest prediction; the CAB-ready report lives in
`prediction_report.md` per network. Only interface shutdown is modeled in
this slice — other change types are registered architecture for future
PRs (see `ARCHITECTURE.md`).

## Path Intelligence (PR-037)

Ask Atlas the question every investigation starts with: **"why can't A
reach B?"** The **Paths** page takes a source and a destination device
and investigates end-to-end connectivity from evidence alone — no packet
simulation, no traceroute, no guessing:

- the **known path** is constructed from discovered topology (CDP/LLDP
  edges in the current snapshot); equal-cost alternatives are reported
  as **ambiguity with every candidate listed**, never guessed through;
- **every hop is validated** in order: device exists → management
  reachability → ingress/egress interfaces exist in the collected
  inventory → operational state (up / down / administratively down);
- the walk **stops at the first deterministic failure** and explains
  WHY with cited evidence — an administratively shut interface says "an
  operator disabled it", an operationally down link points at the
  physical layer, an unreachable device cites the discovery failure;
  hops after the failure are honestly marked *not evaluated*;
- the result reads as an **investigation story** — a numbered, expandable
  timeline (green Pass / yellow Warning / red Failure / grey Unknown)
  with per-hop evidence, confidence, link and management state;
- **evidence-based next actions** per failure type, what Atlas cannot
  see, and confidence capped below 100%.

Every investigation is recorded per network in
`path_investigations.json` (timestamp, profile, source, destination,
evidence, result, confidence — the complete result, so it can be
replayed later); the latest report lives in
`path_investigation_report.md`. Unknown devices, undiscovered
destinations, and incomplete topology are explained honestly and end in
a "run a fresh discovery" recommendation rather than a guess.

## Enterprise Federation (PR-037A)

**One enterprise, many observation points.** Discovery profiles remain
entry points (credentials, seeds, boundaries, schedules) with fully
isolated per-profile evidence — but they are not network boundaries.
After discovery, Atlas federates every profile's latest evidence into
one canonical Enterprise Graph, and **All Networks becomes the
enterprise scope**:

- **Enterprise Summary** (dashboard): canonical devices, observations,
  merged devices, cross-profile links, unknown boundaries, and every
  contributing profile with its evidence freshness.
- **Enterprise Topology**: ONE interactive viewer spanning every lab
  where evidence exists, plus the canonical inventory — merge badges,
  identity confidence, and full provenance on demand (which profile
  observed the device, when, in which run, via which address).
- **Merge decisions are explainable**: serial numbers always merge
  (95% identity confidence); hostname+IP merges only when profiles
  declare the same administrative domain (75%); a hostname alone or an
  IP alone **never** merges — real enterprises reuse both. If Atlas
  cannot prove two observations are the same object, they stay separate.
- **Unknown boundaries stay visible**: neighbors announced by CDP/LLDP
  but never discovered are listed as boundaries, never invented into
  the inventory — and a far-end *name* never attaches to another
  profile's device.
- **Enterprise Prediction and Enterprise Paths**: Predict and Paths now
  work at All Networks against the federated snapshot. Blast radii and
  path investigations cross profiles wherever strong identity evidence
  connects them (discover a shared WAN gateway from two labs and FLOW
  walks Hyderabad → gateway → Secunderabad). Stale or missing evidence
  lowers confidence honestly instead of refusing.

Federation happens after discovery and never modifies profile scopes;
enterprise artifacts live in `.atlas/enterprise/` and are regenerated
deterministically from profile evidence.

## Next Step

Extract a reusable deterministic Topology Change Set contract for richer operational journeys before considering persistence or live transport.
