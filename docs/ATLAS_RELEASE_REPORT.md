# FounderOS Atlas 0.3.0a1 release report

Updated: 2026-07-26. Authoritative version source:
`src/founderos_atlas/release.py`. Package metadata, CLI, Settings,
diagnostics, update information, backups, evidence provenance, policy/reasoning
results, and startup logs use that identity. Workspace schema target: v1.

## Post-PR-154 completion and independent audit

PR-155 through PR-162 add topology stabilization, guided evidence/identity
resolution, policy intent and governance, an operational Action Center,
Network Time Travel, unified investigation cases, durable scheduled
operations, and vendor-neutral operational telemetry adapters.

Final integrated verification: **2,449 passed, 2 intentional skips, and 472
subtests passed**. The complete suite was repeated after correcting 14
cross-feature topology/theme contracts found by the first integration run.
Source compilation, documentation/link/UTF-8 checks, dependency auditing,
SBOM generation, wheel build, isolated install, version/import smoke testing,
and live-browser inspection also passed.

The wheel built and installed as `founderos-runtime==0.3.0a1`; installed
metadata, runtime, Settings, diagnostics, CLI, backups, and logs reuse the same
authoritative version. The CycloneDX SBOM contains 80 locked components.

On the operator's real 19-site evidence set, the Enterprise Policy cold render
was reduced from 114.5 seconds to 27.4 seconds by eliminating a duplicate
enterprise-graph build and gathering each device's evidence once per evaluation
pass. The same-process cached render is 0.32 seconds. The cold evaluation
remains evidence-size dependent and is an explicit performance boundary for a
future durable derived-report cache.

The only dependency finding is Paramiko 4.0.0 / PYSEC-2026-2858. It is not
silently suppressed: the reviewed exception expires 2026-10-18 and Atlas
disables `ssh-rsa`/SHA-1 across its SSH paths while Netmiko remains incompatible
with Paramiko 5.

One accepted architectural limitation remains: workspace state JSON and the
dedicated audit JSONL are individually atomic and process-locked, but not one
cross-file transaction. A host crash between those writes can leave a state
change without its local audit event. A transactional workspace journal owns
that future boundary.

## Earlier 18 July release baseline

The 18 July baseline passed **1,745 tests, 1 skipped test, and 436 subtests**.
The final release/SSH-control gate at that time passed another 110 tests and 44
subtests with one intentional skip.

## What this release completes

One evidence-backed operational lifecycle connecting every surface:

    discovery/policy signal → incident case → evidence & topology
    investigation → path analysis → prediction → Compass plan →
    review → approval → schedule → pre-checks → execution
    checkpoints → post-checks → completion or rollback → audit

`tests/test_lifecycle_e2e.py::LifecycleEndToEndTests::test_signal_to_audited_completion`
demonstrates the entire chain against discovered evidence, asserting the
audit log carries every stage and the CAB export tells the whole story.

### Incidents
- Incident **cases** (`incidents/records.py`): severity, status
  (open/acknowledged/resolved/suppressed), owner, notes, links, catalog
  revision; every action audited; assignment notifies the owner's inbox.
- Enterprise scope is not a dead end: the run form selects the
  observation point inline; the enterprise case list spans all scopes.
- Case page separates **observed facts** (the deterministic report's
  evidence, each statement naming its artifact) from **inferred root
  cause** (a ranked hypothesis with confidence), shows the audited case
  timeline, and carries the case into paths/predict/Compass so their
  results link back automatically.

### Advisor
- Citations deep-link to exact evidence/configuration where held; the
  answer names its scope and time; missing evidence is stated under
  "What Atlas Cannot See", never implied (tests:
  `test_advisor.AdvisorHonestyTests`).
- Answer feedback (helpful / not, with note) recorded and audited;
  conversations rename/delete/export; loading state on ask; errors
  flash with the question preserved for retry.

### Path investigation
- Giant selects replaced by an accessible async **entity picker**
  (combobox role, keyboard navigation, recents, server-side
  re-validation) backed by `/api/entities`.
- Declared VRF/source/protocol/port intent rides with the stored
  investigation and is reported honestly: topology and state are
  evaluated; ACL/firewall policy is explicitly NOT (listed under what
  Atlas cannot see).
- Investigations run from an incident link back to it; saved
  investigations compare over time on `/paths/compare`.

### Prediction
- Device-dependent interfaces come from `/api/device-interfaces` when
  the device is picked — nothing preloaded into the DOM; the API detail
  carries the same evidence context the old dropdown had (state,
  address, SVI badge, neighbor, management role).
- Change templates cover the engine's modeled types (shutdown-interface,
  reboot-device); unmodeled types go through Compass, which states
  unknowns instead of pretending. Targets are validated against the
  current snapshot; freshness is part of the prediction's confidence.
- Every prediction saves a scenario (risk/confidence/blast radius),
  comparable and addable to Compass in one click, linked to its incident.

### Compass
- Full lifecycle: Draft → Analysed → In Review → Approved → Scheduled →
  Running → Completed / Failed → Rolled Back, plus Cancelled — each
  transition validated server-side and audited; any edit returns to
  draft so decisions cover exactly what was reviewed.
- Readiness: rollback plan, success criteria, reviewers, pre/post
  checks, maintenance-window constraints; submit-for-review is blocked
  until the gaps list is empty.
- Ordering: keyboard-accessible reorder with dependency validation,
  per-change dependencies and concurrency groups; a proportional window
  timeline (Gantt) by estimated duration.
- Execution: Atlas does not push device configuration, so Running is
  tracked through explicit attributed checkpoints per change and per
  check — that record is the resulting evidence; it feeds the audit
  log and annotates the linked incident on every terminal transition.
- CAB-ready markdown export (`/compass/<id>/cab.md`) with plan, risks,
  checks, decision, and execution record. RBAC (plans.edit /
  plans.approve) and optimistic concurrency enforced throughout.

## Quality gates (all automated, all failing the build on violation)

| Gate | Where |
| --- | --- |
| Primary routes never 404/500 (3 scopes each) | `test_lifecycle_e2e.QualityGateTests` |
| No rendered tracebacks/jinja errors | same |
| Every referenced /static asset resolves | same |
| Wide tables wrapped in labelled scroll regions | same |
| No empty (unlabelled) buttons on lifecycle pages | same |
| Lifecycle records survive server restart | same |
| Filtered URLs reproduce state in a fresh client | same |
| Authorization on every endpoint, default-deny | `test_production_security` |
| CSRF / sessions / conflicts / undo / audit | `test_production_security`, `test_resilience_and_conflicts` |
| Secrets never in HTML/logs/exports/audit/backup | `test_production_security` |
| Migration from legacy data + backup/restore | `test_resilience_and_conflicts` |
| Large datasets (3000 policy / 5000 changes / 10000 events) under time budget | `test_investigation_scale` |
| Advisor honesty against unsupported/stale claims | `test_advisor.AdvisorHonestyTests` |

## Browser verification (this release's sweep)

- Live Settings/System Information inspection verified the authoritative
  version, build commit, schema, effective local auth and credential provider,
  application bind, TLS/HSTS state, trusted proxies, session policy, worker
  state, logging, retention, and update-provider state. `/system` redirects to
  `/settings#system-information`, and the browser console had no warnings or
  errors. The sweep found and corrected one stale OS-keyring-specific backup
  sentence so the UI now accurately covers every credential provider.

- Live walk in local mode: incident opened from the enterprise page,
  case actions, path picker (typed "core" → 6 async matches, combobox
  semantics), dependent interface picker (device pick → 7 interfaces
  with live state), zero console errors on every page visited.
- Horizontal overflow measured at 375/768/1600 px across 12 pages:
  one defect found (compare-form selects at 375 px) and fixed
  (`.filter-bar` max-width rule); re-measured clean.
- QA artifacts created during the sweep were suppressed with an audited
  reason, not deleted.

## Migrations and compatibility

- New workspace records (additive, no migration required):
  `incidents.json`; per-scope `prediction_scenarios.json`; plan records
  gain lifecycle fields with tolerant `from_dict` defaults — existing
  plans load unchanged as drafts of the extended model.
- The legacy direct-approval path (analysed → approved) still works;
  the review path (analysed → in-review → approved) is the full flow.

## Security assumptions

Unchanged from `ATLAS_PRODUCTION_DEPLOYMENT.md`: server host trusted,
browsers untrusted, proxy trusted only with its secret, device output is
untrusted input. New endpoints are all in the default-deny authorization
table (completeness is a failing test).

## Genuine external limitations (not unfinished work)

- **Automated visual-regression and in-CI browser console capture**
  need a screenshot/browser-automation toolchain (e.g. Playwright) that
  this repository does not vendor; the equivalent risks are covered by
  the DOM-level gates above and the manual sweep. This is the one gap
  that requires an external dependency.
- **Live device execution**: Atlas deliberately does not push
configuration; Compass execution is checkpoint-tracked by design (the
console provides interactive access under its own audit). The packet
trace's "Validate live" is the one command Atlas runs on an
operator's explicit request — a traceroute, and a TCP connect when
the trace declared a port — built from a validated address and port,
gated `console.use`, and audited like a console connection.
- **Probes are CLI-bound, per platform**: a device's SSH session is
  usually its CLI, not a shell (FRR answers in vtysh exactly as a
  Cisco answers in IOS), so each probe is only the command that CLI
  accepts. Where a routing CLI cannot open a socket, the service
  check reports `unsupported` rather than probing from another
  vantage point and presenting it as the same evidence. A probe that
  outlives its deadline returns the hops it did observe, marked cut
  short, instead of discarding them.
- **L4 policy evaluation** (ACL/firewall for protocol/port intent):
  IOS access-list rules and their interface bindings are now parsed
  from captured running configurations and evaluated per hop against
  the declared intent, with three-valued honesty (match / no-match /
  cannot-decide) and config-line citations. Hops without captured
  configuration, unparsed ACLs, and rules whose addresses or
  qualifiers declared intent cannot settle are reported, never
  guessed. An enforced **firewall chain** captured by discovery is now
  evaluated at its hop too, with the same three-valued honesty: first
  terminal match wins, `LOG` is not a verdict, a reply-only
  (`ESTABLISHED`/`RELATED`) rule cannot admit the first packet of a
  flow, and an unmatched packet meets the chain's default policy.
  Zone-based vendor policy (FortiOS/PAN-OS `SecurityPolicy` evidence)
  is not yet joined to the walk.

## Release-trust hardening

- System Information reports effective auth mode, credential provider and
  availability, TLS/HSTS, application bind and proxy visibility boundary,
  trusted proxies, session policy, one-process worker model/status, schema,
  build commit, logging, retention, and update-provider state.
- All submitted `next` targets use one fail-closed same-origin validator.
- `constraints.txt` is the reviewed exact lock and `sbom.cdx.json` is the
  CycloneDX inventory. CI audits dependencies and rejects unapproved or expired
  findings.
- Paramiko PYSEC-2026-2858 is explicit, expires 2026-10-18, and is mitigated by
  disabling `ssh-rsa`/SHA-1 on every Atlas SSH path pending Netmiko support for
  Paramiko 5.
- `LICENSE` explicitly records that licensing is an owner/legal decision; no
  distribution permission is invented.
- **Streaming Advisor answers**: answers are synchronous single
  responses by architecture (deterministic orchestration, no token
  stream); the UI provides an explicit in-progress state instead.
