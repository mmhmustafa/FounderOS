# Atlas Operational State Intelligence

Detects operational changes in the running network between discoveries —
even when the saved configuration has not changed. This is the third change
dimension, alongside topology change intelligence and configuration change
intelligence:

| Layer | Answers |
| --- | --- |
| Topology change intelligence | Devices and relationships added / removed / renamed |
| Configuration change intelligence | What changed in `running-config` |
| **Operational state intelligence** | What changed in the live interface state |

## What is detected

Interface state already lives inside every `TopologySnapshot` (collected
from `show ip interface brief`: name, admin status, protocol status, IP
address, description), so no extra collection is required. Devices are
matched across snapshots by hostname; interfaces by name.

| Change | Severity |
| --- | --- |
| Interface status up → down | High |
| Interface line protocol up → down (reported separately from admin shutdown) | High |
| Interface status up → administratively down (admin shutdown) | Medium |
| IP address change | Medium |
| Interface removed | Medium |
| Interface status/protocol recovered (→ up) | Low |
| New interface detected | Low |

A status-down change recommends checking cable, remote device, interface
errors, and spanning-tree; a protocol-down change points at line protocol,
keepalives, and layer-2 connectivity — the two are reported separately so a
physical fault is not confused with an intentional shutdown.

## Usage

```
founderos atlas state-diff <previous_snapshot.json> <current_snapshot.json>
founderos atlas state-diff --latest
```

The `--latest` form compares the two most recent discoveries in
`.atlas/history/`. Both write `state_change_report.json` and
`state_change_report.md` and print a severity summary. Operational state
comparison also runs automatically inside `founderos atlas discover` when a
previous baseline exists — no manual command is required.

## Integration

- **Dashboard** — an Operational Changes card shows Healthy or Attention
  Required with severity counts, plus an Open Operational Changes action.
- **Morning Brief** — when operational changes exist, network status becomes
  Attention Required and the brief reports "N interface(s) down" in Today's
  Summary and an Operational Changes section, distinct from topology and
  configuration changes.

## Current health vs. historical events

Each change carries an **event type** that separates *what happened* from
*whether it is still a problem*:

| Event | Meaning | Active issue? |
| --- | --- | --- |
| `failure` | Interface/protocol went down | Yes |
| `degradation` | Admin shutdown, or interface removed | Yes |
| `recovery` | Interface/protocol came back up | No |
| `informational` | New interface, IP address change | No |

`StateChangeReport` exposes three distinct views:

- **Historical events** — every change (`changes`), preserved for the timeline.
- **Active issues** — `active_issues`: only failures and degradations that
  represent a currently unresolved condition.
- **Current health** — `current_health`: `Healthy` when there are no active
  issues, else `Attention Required` (or `Critical` if an active issue is
  high-severity).

This is why a recovered interface no longer keeps Atlas in Warning: the
recovery is kept in history, but current health is driven by active issues
only. Health is never determined merely by the count of past changes.

## Design notes

Operational state is deliberately owned here, not by the topology change
detector: an interface going down is not a topology change (the device and
its relationships are unchanged) and not a configuration change (the config
is identical). Keeping it separate is what lets a Morning Brief honestly say
"1 interface down · no topology changes · no configuration changes".
