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

## Next Step

Extract a reusable deterministic Topology Change Set contract for richer operational journeys before considering persistence or live transport.
