# Atlas Web GUI (local alpha)

The first browser interface for Atlas. It is a **local, single-user alpha
GUI** — not a production or multi-user web deployment. It binds to
`127.0.0.1` only, has no authentication, and runs the same in-process Atlas
backend services the CLI uses. It never shells out to a CLI subprocess.

## Run it

```
pip install founderos-runtime[web]
founderos atlas web
```

```
Atlas web UI running at:
http://127.0.0.1:8765
```

The browser opens automatically. The interactive CLI (`founderos atlas
discover`, `founderos atlas profile …`) continues to work unchanged.

## Architecture

```
founderos_atlas/web/
  app.py        create_app() Flask factory; injectable services + local bind
  routes.py     thin HTTP handlers → existing backend services (no logic)
  models.py     view-model helpers that shape service data for templates
  templates/    base shell + 8 pages (Jinja2)
  static/       atlas.css, atlas.js (no JS framework)
```

The app factory takes injectable dependencies (`profile_service`,
`output_dir`, `history_root`, `transport_factory`, `clock`) so the whole GUI
— including a real discovery run — is testable against a scripted network
with deterministic timestamps.

## Backend reuse (no duplicated logic)

| GUI action | Backend service |
| --- | --- |
| List / add / edit / delete profiles | `workspace.ProfileService` |
| Run discovery | `atlas_discover_command(profile=…)` (in-process) |
| Dashboard summary | `dashboard.build_dashboard_summary` |
| History | `history.HistoryRepository` |
| Change / config / operational summaries | the generated report JSON |
| Incident investigation | `incidents.IncidentInvestigator` |
| Credential status | `workspace.resolve_credential_provider` |

## Pages / routes

| Route | Page |
| --- | --- |
| `GET /` | Dashboard |
| `GET /discovery`, `POST /discovery/run` | Run discovery from a saved profile |
| `GET /profiles` | List profiles |
| `GET /profiles/new`, `POST /profiles` | Add profile |
| `GET /profiles/<name>/edit`, `POST /profiles/<name>` | Edit profile |
| `POST /profiles/<name>/delete` | Delete profile |
| `GET /topology` | Embedded topology viewer |
| `GET /history` | Discovery history |
| `GET /changes` | Topology / config / operational summaries |
| `GET /incidents`, `POST /incidents/run` | Incident investigation |
| `GET /settings` | Workspace path, credential status, version |
| `GET /artifacts/<name>` | Serve generated artifacts (viewer, reports) |

## Security

- Binds to `127.0.0.1` by default; never `0.0.0.0`.
- No authentication (local single user) — documented as alpha, not for
  production or multi-user deployment.
- Passwords are never rendered in HTML, never returned in responses, and
  never logged. Profiles carry only a credential reference; the secret lives
  in the OS keyring.
- Password form fields are `type="password"` and are never pre-filled on
  edit.

## Network scopes (PR-031A)

Every data page (Dashboard, Topology, History, Changes, Incidents) carries a
Network selector in the header:

- **A saved profile** — shows only that profile's isolated workspace
  (`<output>/.atlas/profiles/<profile_id>/`).
- **All Networks** — aggregates the latest successful state of every
  *active* scope (combined counts, per-network cards, merged device
  inventory and history). Aggregation never compares one network against
  another, and never deduplicates devices by hostname/IP across profiles.
- **Local workspace** — the classic unscoped layout produced by profile-less
  CLI discovery; the option appears only when such data exists. Once any
  profile has completed a scoped discovery, this scope becomes a legacy
  archive: it is excluded from All Networks aggregation (no duplicate
  devices, inflated counts, or stale health), relabelled "Local workspace
  (legacy)", and remains fully viewable by selecting it directly
  (`active_scopes()` in `workspace/scopes.py` implements the policy).

The selection is passed as `?scope=<id>`, stored in the Flask session, and
shown in every page title. Running a discovery switches the session scope to
that profile. Incident investigations require a specific network scope and
read/write only that scope's artifacts.

## Network viewer presentation

`GET /topology` uses the full available content width and presents the graph
before its supporting inventory and evidence tables. The embedded viewer keeps
the graph wide on smaller screens by turning its details pane into a
toggleable overlay; tables remain complete and scroll horizontally when the
viewport is narrow.

Generated topology HTML carries a content-derived visual-style marker. When a
current profile or Enterprise viewer predates the installed template/stencil
contract, the route regenerates only `atlas_topology.html` from the adjacent
`topology_snapshot.json` using an atomic replace. It does not run discovery,
rewrite the snapshot, or traverse/change any history directory. If the current
snapshot cannot be read, the existing viewer remains in place and the page
continues to load. Current-viewer URLs also carry that style version as a query
parameter so the iframe cannot reuse a visually stale browser-cache entry after
the artifact has been refreshed.

## Discovery jobs (PR-032)

The Discover page runs the real pipeline asynchronously through an
in-process job manager (`jobs.py`):

- `POST /api/discovery/jobs` (`profile=<name>`) → `202` with the job, or
  `409` with the already-running job for that profile, or `400` when no
  profile is named (All Networks is a view — discovery targets one profile).
- `GET /api/discovery/jobs/<job_id>` → current status; the page polls every
  1.5 s. `GET /api/discovery/jobs` lists recent jobs.

**Shared service.** The manager's runner executes `atlas_discover_command`
— the exact function the CLI uses — in-process, wired to the app's injected
profile service, transport factory, and scoped output paths. Credentials
are resolved server-side; job payloads carry only profile identity and safe
metadata (a test asserts no password or credential reference ever appears
in an API response or the persisted job file).

**Progress semantics.** Seven user-facing stages mapped from real activity:
transport connections (current device, devices contacted) and the
pipeline's own `[N/9]` lines. Percentage is stage-based and labelled
`progress_basis: "stages"`; per-device totals are unknown during recursive
discovery, so Atlas never invents them. `current_depth` is null until the
engine reports it.

**Concurrency.** One discovery executes at a time (global run lock);
duplicate same-profile requests return the existing job. Different profiles
queue. Local-alpha limitation, chosen for correctness.

**Restart behavior.** Job history persists to `<output>/.atlas/jobs.json`.
Browser refresh/navigation never affects a run (the page re-attaches).
In-process jobs do not survive a server restart: on startup, persisted
queued/running jobs are marked `interrupted` with an honest message.

## Topology curation API

The Network viewer is read-only until the operator enables Edit topology.
Device-to-site changes require confirmation, a reason, and the current
override revision. The API returns `409` for stale revisions, exposes the
underlying inference alongside the override, and supports both return-to-
automatic and undo. Site type changes are explicit; WAN, Internet, cloud, and
ordinary sites never depend on graph degree or the absence of evidence.

Current profile and Enterprise viewers are regenerated after a successful
curation operation. Discovery snapshots and historical viewers are not
rewritten. This is a local single-operator application boundary; the audit
records the local operator identity and mutation reason.

**Fallback.** Without JavaScript the form posts to `/discovery/run`, which
runs synchronously through the same job manager — one execution path.
