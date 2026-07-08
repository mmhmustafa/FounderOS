# Atlas Configuration Intelligence

Classified, secret-masked comparison of two device configurations — not a
raw diff. Atlas answers *what kind* of configuration change happened and
*how much it matters*, not just which lines differ.

## How it works

1. **Section-aware diff** (`diff.py`) — configurations parse into top-level
   sections (an unindented line plus its indented children: `interface
   GigabitEthernet0/1`, `router ospf 1`; global one-liners like
   `ip route …` are single-line sections). Sections are compared
   individually, so every change stays attached to the construct it
   belongs to.
2. **Classification** (`classifier.py`) — ordered prefix rules map each
   changed section to a category; a documented category map assigns
   severity. Rules are data tables, not code branches.
3. **Reports** (`report.py`) — deterministic JSON and Markdown with a
   severity summary and per-change detail (category, summary,
   recommendation, masked added/removed lines).

## Categories and severity

| Severity | Categories |
| --- | --- |
| High | acls, nat, aaa, line-access, bgp — access control and wide-reach routing |
| Medium | ospf, routing, static-routes, interfaces, vlans, snmp |
| Low | logging, ntp, other |

One escalation rule: an interface change that adds or removes
`shutdown` / `no shutdown` is High — port state flips are outage-shaped.

Every change carries: hostname, category, severity, summary,
recommendation, masked added/removed lines, and a raw diff reference (the
section header).

## Secret masking

Masking happens **at diff-extraction time**, before any model object,
report, or console output ever holds the content. Any line containing one
of these terms (word-boundary, case-insensitive) is replaced entirely:

`password` · `secret` · `key` · `community` · `token` · `credential`

The masked form preserves indentation and names only the triggering term:
`<masked: line contains 'secret'>`. Over-masking is accepted by design —
a masked `crypto key` line is a smaller cost than a leaked one. Section
headers are masked too; classification uses only the first two command
tokens internally and never emits them.

## CLI

```
founderos atlas config-diff <previous_config> <current_config>
founderos atlas config-diff --latest <hostname>
```

The first form compares two files (the device name is taken from the
current file's parent directory, matching `configs/<hostname>/` layout).
The `--latest` form finds the two most recent discoveries in
`.atlas/history/` that collected a configuration for that hostname and
compares them. Both write `config_change_report.json` and
`config_change_report.md` and print a severity summary.

## Dashboard

When `config_change_report.json` exists, the dashboard shows a
Configuration Changes card: devices changed and high/medium/low counts,
plus an Open Config Changes quick action.

## Non-goals honored

No AI, remediation, rollback, config push, compliance engine,
vendor-specific deep parsing, database, or scheduler.
