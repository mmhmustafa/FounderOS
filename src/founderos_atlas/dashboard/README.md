# Atlas Executive Dashboard

A professional operational summary of the current Atlas network state —
**not** a monitoring dashboard. It reads the artifacts previous Atlas runs
produced and renders one static, self-contained `dashboard.html`.

## Sections

| Section | Content |
| --- | --- |
| Header | Atlas · Enterprise Network Intelligence · last discovery time |
| Network Status | Healthy / Warning / Critical (Unknown before first discovery) with a one-line reason |
| Summary tiles | Devices, Relationships, Discovery Success, Configurations Collected, Recent Changes |
| Recent Changes | Top entries from the latest change report, severity-colored |
| Recent Activity | What Atlas has produced (topology, brief, change report, configurations) |
| Quick Actions | Links to the topology viewer, Morning Brief, change report, configurations, and snapshot |

## Status logic (deterministic)

- **Unknown** — no topology snapshot exists yet
- **Critical** — the change report contains high-severity changes
- **Warning** — changes detected, hosts failed discovery, or reconciliation warnings exist
- **Healthy** — none of the above

## Data sources

All local artifact files; nothing live, nothing remote:

`topology_snapshot.json` · `change_report.json` / `change_report.md` ·
`morning_brief.md` · `atlas_topology.html` · `configs/<hostname>/`

Missing artifacts degrade gracefully: tiles show `—`, quick actions render
as "not yet generated", and an empty workspace produces a valid dashboard
inviting the first `founderos atlas discover`.

## Rendering

Same pattern as the topology viewer: an HTML template with token
substitution, all values HTML-escaped. No JavaScript frameworks — this page
contains **no script at all** — no CDN, no backend server, no database, no
authentication. Quick-action links are relative to the dashboard's own
directory so the page works wherever the artifact set lives.

## Usage

```
founderos atlas dashboard
```

generates `dashboard.html` in the current directory and opens the browser.
`founderos atlas discover` also regenerates the dashboard automatically
after every successful discovery.
