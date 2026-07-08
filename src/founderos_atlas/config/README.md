# Atlas Configuration Collection

Read-only collection of device configuration from discovered Cisco devices.
Collection and normalization only — no analysis, no comparison, no diff.
This is the foundation for future configuration diff, incident
investigation, compliance, and AI explanation capabilities.

## What is collected

| Command | Role |
| --- | --- |
| `show running-config` | Required — collection fails without it |
| `show startup-config` | Optional, best effort |
| `show inventory` | Optional, best effort |
| `show license summary` | Optional, best effort |
| `show module` | Optional, best effort |

Optional commands degrade gracefully: an unsupported command
(`% Invalid input`), a privilege denial, or a lost session becomes a
recorded warning and a per-command status — never a collection failure.
If the session drops mid-collection, remaining commands are skipped and
recorded rather than retried.

Normalization is line endings only (`\r\n` → `\n`, trailing newline).
Configuration content is never altered, truncated, or filtered.

## Read-only design

Every collection command is a plain `show` that passes the transport's
read-only allowlist (`ensure_read_only`). The transport never enters
configuration mode, never calls `enable()`, and never issues `write`,
`copy`, or `reload`. Collection cannot change device state by construction.

## Artifacts

`write_configuration_artifacts(artifact, directory)` writes:

| File | Content |
| --- | --- |
| `running_config.txt` | The normalized running configuration |
| `configuration_metadata.json` | Provenance only — never configuration content |
| `show_startup-config.txt`, `show_inventory.txt`, … | Collected optional outputs |

Metadata records hostname, vendor, platform, OS, management IP, collection
time, the full command list with per-command status, collection status
(`complete`/`partial`), warnings, line count, and a SHA-256 of the running
configuration — enough to verify integrity without exposing content.

Collection time is caller-supplied and recorded as `unrecorded` otherwise;
Atlas never reads the system clock (deterministic by design).

## Security

- **Configuration artifacts are sensitive material** (credential hashes,
  SNMP communities, pre-shared keys). Atlas never logs or prints
  configuration content — the CLI reports only status and file paths —
  and never transmits it anywhere; files are written locally only.
- The default `configs/` output directory is gitignored so collected
  configurations are never committed by accident.
- `configuration_metadata.json` contains provenance only, by contract.
- No credentials are stored; the collection session uses the same
  ephemeral credentials as discovery.

## CLI

After a successful `founderos atlas discover`, Atlas asks:

```
Collect running configuration? [y/N]
```

On `y`, every successfully discovered device is collected over a fresh
read-only session and written to `configs/<hostname>/`. Per-device failures
are reported and never abort the rest of the collection.
