# Atlas Incident Investigation

A deterministic investigation journey — **not AI, not root-cause
automation**. It helps a network engineer structure an incident
investigation using facts Atlas already holds, and it is honest when
evidence is missing.

## How it works

1. **Device matching** — hostnames, identity aliases, and management IPs
   named in the incident text are matched against the current topology
   snapshot. "R1 lost connectivity to SW1" resolves both devices;
   "10.0.0.2 unreachable" resolves by address.
2. **Evidence assembly** — topology context (device facts and logical
   links), possible related changes (entries from `change_report.json`
   and `config_change_report.json` touching the affected devices),
   configuration context (latest config change summary, collected
   configurations), and history depth. Every statement carries its
   source artifact.
3. **Investigation steps** — a fixed base sequence plus keyword-driven
   additions from tables: VLAN numbers (`verify VLAN 10 exists`,
   `check trunks carry VLAN 10`), internet/gateway (default route),
   slowness (interface errors/utilization), lost/down/unreachable
   (physical links and adjacencies). Steps become recommendations,
   deduplicated deterministically.

## Honesty rules

- Missing `change_report.json` → the report states exactly:
  **"Topology change evidence is not available."**
- Missing `config_change_report.json` → **"Configuration change evidence
  is not available."**
- No snapshot → stated, and confidence drops.
- Facts are never invented: every evidence item names its source, and
  the limitations section always records that no live device access
  occurred.

## Confidence (deterministic)

| Confidence | Condition |
| --- | --- |
| Low | No topology snapshot, or no named device matched it |
| Medium | Devices matched, but topology or configuration change evidence is missing |
| High | Devices matched and both change reports are available |

## Outputs

`incident_report.md` and `incident_report.json`, each containing:
incident ID (content-addressed, deterministic), title, description,
generated time, affected devices, possible related changes, topology
context, configuration context, investigation steps, evidence with
sources, confidence, recommendations, and limitations.

## CLI

```
founderos atlas investigate
Incident title: VLAN 10 outage
Incident description: VLAN 10 cannot access internet via R1
```

The dashboard shows a Recent Incident Investigation card (title,
generated time, confidence) with an Open Incident Report action when a
report exists.

## Non-goals honored

No AI, no live troubleshooting commands, no packet capture, no
remediation, no config push, no ticketing integration, no database.
