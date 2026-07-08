# Atlas Change Intelligence

Deterministic comparison of two `TopologySnapshot` values into a classified,
actionable Change Report. This is topology and inventory change detection —
**not** configuration diff.

## What it answers

"What changed?" — the question a network manager actually wakes up with:

| Detected | Category | Severity |
| --- | --- | --- |
| Device discovered for the first time | `device` | Low |
| Device no longer discovered | `device` | High |
| Hostname change (rename, not remove+add) | `hostname` | Medium |
| Management IP change | `management-ip` | Medium |
| Platform change (hardware swap) | `platform` | High |
| OS version change | `os-version` | Medium |
| Interface count change | `interface` | Low |
| Lost neighbor adjacency | `neighbor` | Medium |
| New neighbor adjacency | `neighbor` | Low |
| Discovery failure recorded in the run | `discovery` | Medium |

Every `Change` carries category, severity, description, recommendation,
subject, and previous/current values where applicable. Reports are sorted
deterministically (severity, category, subject) and content-stable: two
comparisons of the same snapshots produce byte-identical output.

## Identity-aware matching

Devices are paired across snapshots by hostname, then serial number, then
management IP, then device ID. A renamed device is therefore reported as
one `hostname` change — never as one removal plus one arrival — and its
links are translated to the new name before neighbor comparison, so a
rename produces zero false neighbor churn.

Neighbor comparison works on undirected logical links (the same model the
topology viewer displays), so the two directional CDP observations of one
cable never double-report. Links involving devices already reported as new
or removed are suppressed — the device-level change is the story.

## Usage

```python
from founderos_atlas.change import ChangeDetector, render_change_report_markdown

report = ChangeDetector().compare(previous_snapshot, current_snapshot)
print(render_change_report_markdown(report))
```

Inputs may be `TopologySnapshot` values or plain dicts loaded from
`topology_snapshot.json` files.

From the CLI:

```
founderos atlas compare previous_snapshot.json current_snapshot.json
```

writes `change_report.json` and `change_report.md` and prints a severity
summary.

## Morning Brief integration

When `build_morning_brief` receives a previous snapshot it embeds the full
change report in the brief's metadata, folds change recommendations into
the brief's recommendations, and renders a **Change Intelligence** section
(severity summary plus each change and its recommendation) in the Markdown
artifact. The `MorningBrief` schema is unchanged — change data rides in the
free-form `metadata` field.

## Viewer highlighting

`TopologyRenderer(snapshot, change_report=...)` marks nodes when a
comparison exists: new devices green, changed devices orange, and removed
devices as red dashed ghost nodes. Without a report the viewer renders
exactly as before.
