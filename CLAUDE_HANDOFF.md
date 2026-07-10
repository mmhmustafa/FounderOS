# CLAUDE_HANDOFF.md — FounderOS / Atlas Project Handoff

**Written:** 2026-07-10, immediately after PR-031 completion.
**Purpose:** Allow a completely fresh Claude Code session to continue development safely with no access to the prior conversation.
**Ground rule for the next session: repository reality is the source of truth.** Everything below was verified against the actual repository on the date above unless explicitly marked **Unverified** or **Environment-specific**.

---

## IMPORTANT CURRENT STOPPING POINT

**PR-031 (Atlas GUI Application Shell) has been completed and verified — but it is deliberately UNCOMMITTED.**

Verified by direct inspection on 2026-07-10:

- `git log` HEAD is `bc1123d` — "PR-030.1: Stabilize credentials, health status, and config diff noise". PR-030 (`22d5342`) and PR-030.1 (`bc1123d`) **are committed**.
- `git status` shows the entire PR-031 change set **uncommitted in the working tree**:
  - Modified (tracked): `CHANGELOG.md`, `apps/atlas/README.md`, `pyproject.toml`, `src/founderos_runtime/cli/commands.py`, `src/founderos_runtime/cli/main.py`, `src/founderos_runtime/cli/render.py`
  - Untracked (new): `src/founderos_atlas/web/` (full package: app.py, routes.py, models.py, README.md, 10 templates, static css/js), `tests/test_web_app.py`
- The full test suite passes with PR-031 in the tree (see §11 for exact numbers).
- The owner (user) explicitly instructed: **"Do not commit or tag automatically. I will test manually first."** This applies to PR-031. Do **not** commit until the owner explicitly asks.
- A deliverables zip (`deliverables/pr-031-web-gui-shell-package.zip`) was produced; `deliverables/` is gitignored (local-only).

---

## 1. PROJECT OVERVIEW

### What FounderOS is
FounderOS (`src/founderos_runtime/`) is a domain-agnostic workflow runtime: manifest-driven journeys, a planner, validation, authorization, evaluation rubrics, and a deterministic mock provider. It predates Atlas and hosts the shared CLI entry point (`founderos`). Package name `founderos-runtime`, version `0.3.0a1` (pyproject.toml), CLI banner "FounderOS v0.3 Alpha".

### What Atlas is
Atlas (`src/founderos_atlas/`) is the first real product built on FounderOS: an **Enterprise Network Intelligence Platform**. It discovers Cisco network devices over read-only SSH, builds topology, detects topology/configuration/operational-state changes over time, preserves history, generates executive dashboards and morning briefs, and structures incident investigations. As of PR-031 it has a local web GUI.

### Product vision & customer problem (verified against apps/atlas/README.md)
- **Persona:** network engineers / network operations teams.
- **Core pain:** understanding what is on the network, how it is connected, and **what changed** — across topology, configuration, and operational state — without manual CLI archaeology.
- **Current capability:** single-command discovery (`founderos atlas discover`) runs a unified 9-step pipeline producing topology viewer, snapshot, morning brief, dashboard, change/config/state reports, and preserved history; saved profiles remove repetitive credential entry; a local GUI (PR-031) exposes all of it in a browser.
- **Near-term direction (from CHANGELOG/README trajectory):** GUI maturity, multi-profile workflows, live-lab robustness.
- **Longer-term (Unverified — conversation context only):** AI-assisted diagnostics/troubleshooting, multi-vendor support, reconciliation against intended state.

### Architecture at a glance (all implemented today unless noted)

| Layer | Location | Notes |
|---|---|---|
| CLI | `src/founderos_runtime/cli/` (`main.py` routing, `commands.py` logic, `render.py` text output) | Argument routing is hand-rolled (no argparse). Every side effect is injectable for tests. |
| Discovery engine | `src/founderos_atlas/discovery/`, `transport/` | Multi-hop CDP discovery from one seed; netmiko SSH transport behind an abstraction; `[ssh]` extra. |
| Identity | `src/founderos_atlas/identity/` | Canonical device identity + relationship reconciliation (dedupes devices seen via multiple IPs/names). |
| Topology | `src/founderos_atlas/topology/`, `visualization/` | Graph, content-addressed `TopologySnapshot`, Cytoscape HTML viewer. |
| Intelligence | `change/` (topology diff), `config_intelligence/` (config diff + dynamic-metadata filter), `state/` (operational events + current-health), `incidents/` | Deterministic, pure-Python diff engines. |
| Journeys | `journeys/` | Morning brief generation + evaluation. |
| History | `history/` | `HistoryRepository` at `.atlas/history` (CWD-relative), archives every discovery run's artifacts. |
| Workspace | `workspace/` (PR-030) | Saved discovery profiles + secure credential storage (OS keyring). Profiles at `~/.atlas/workspace/profiles.json`. |
| Web GUI | `web/` (PR-031, **uncommitted**) | Flask app factory, 9 routes/8 pages, loopback-only, in-process service calls. `[web]` extra. |
| Dashboard | `dashboard/` | Executive summary HTML from all artifact JSONs. |
| Tests | `tests/` (40 files) | unittest style, run via pytest; heavy use of fakes (`ScriptedNetwork`, `InMemoryCredentialProvider`, injected clocks). Fully hermetic — no network, no real keyring, no system clock in assertions. |

**Partially implemented:** GUI discovery is synchronous/blocking (no async jobs or live progress). Profile-scoped data isolation does **not** exist (see §7 — the most important known issue).
**Planned, NOT implemented:** async discovery jobs, AI features, multi-vendor (non-Cisco) parsing, auth on the GUI, Vault/AWS/Azure credential providers (the `CredentialProvider` ABC is the extension point).

---

## 2. PRODUCT VISION AND CORE CUSTOMER PROBLEM

Covered in §1. Key verified additions:

- `apps/atlas/README.md` is the product-facing document: quick start, the 9-step pipeline description, profile commands, security posture, web GUI usage.
- The platform/product boundary is deliberate: **FounderOS stays domain-agnostic; everything network-specific lives in `founderos_atlas`.** `tests/test_service_boundaries.py` guards aspects of this.
- Security is a first-class requirement (PR-030 spec, verbatim): passwords must never appear in plain-text JSON/YAML/SQLite/logs/reports/history/snapshots/dashboards/command output, and there must be **no plaintext credential fallback**. This is enforced in code and regression-tested.

---

## 3. CURRENT DEVELOPMENT STATE

**Completed and committed (PR-019 → PR-030.1):** SSH transport; parser robustness; live-discovery output pipeline; multi-hop CDP discovery; canonical identity; topology change intelligence; read-only config collection; executive dashboard; history/timeline; config intelligence (classified config diffs); incident investigation; unified 9-step pipeline; operational state intelligence; workspace profiles + secure credentials (PR-030); alpha stabilization (PR-030.1: `[credentials]` extra packaging, health-vs-history event semantics, dynamic Cisco config-metadata filtering).

**Completed but UNCOMMITTED (PR-031):** the web GUI shell — see §9 and the stopping-point section.

**Currently functional:** everything in the CLI help output (§10) plus the GUI. Full suite green.

**Known blockers:** none for development. Manual CML validation of PR-030/030.1/031 by the owner is the gate for committing PR-031.

**Known limitations / bugs / debt:** see §14. Headline items:
1. **No per-profile data isolation** — discovery artifacts and history are shared across all profiles (§7). *Confirmed by code.*
2. GUI discovery blocks the HTTP request until the 9-step pipeline finishes. *Confirmed by code.*
3. Topology viewer loads Cytoscape from a CDN (needs internet on first load). *Confirmed by code (visualization template).*
4. No auth / no CSRF on the GUI (acceptable for loopback single-user alpha; documented). *Confirmed by code.*

---

## 4. RECENT PR / WORK-PACKAGE HISTORY

Reconstructed from `git log` (all verified):

```
bc1123d PR-030.1: Stabilize credentials, health status, and config diff noise
22d5342 PR-030: Add workspace profiles and secure credential storage
0e3ac9c PR-029: Add operational state intelligence
cc89461 PR-028: Unify discovery into one automatic pipeline
c69997f PR-027: Add incident investigation journey foundation
82ce873 PR-026: Add configuration intelligence foundation
3f284a5 PR-025: Add historical timeline and network memory
9f6f1b2 PR-024: Add Atlas executive dashboard
3f4ce86 PR-023: Add read-only configuration collection foundation
b96974b PR-022: Add change intelligence between topology snapshots
594104b PR-021.1: Add canonical device identity and relationship reconciliation
72dc547 PR-021: Add controlled multi-hop CDP discovery from one seed
9e71156 chore: Stop tracking generated Atlas CLI artifacts
c5e9f74 PR-020: Complete live discovery output pipeline
e537ed8 PR-019.1: Harden live discovery parsing, diagnostics, and fallbacks
```

Commit convention: `PR-0XX: <imperative summary>` + bullet body + `Co-Authored-By: Claude <model> <noreply@anthropic.com>`.

### PR-030 — Workspace & Saved Discovery Profiles (committed `22d5342`)
- **Goal:** stop re-typing IP/username/password for every discovery; store profiles persistently and credentials securely.
- **Implementation:** new `src/founderos_atlas/workspace/` package — `models.py` (`DiscoveryProfile` frozen dataclass, **no password field**, only `credential_ref` of form `atlas-profile:<slug>`), `credentials.py` (`CredentialProvider` ABC; `KeyringCredentialProvider` with lazy `keyring` import; `InMemoryCredentialProvider` for tests; `resolve_credential_provider()`; **deliberately no plaintext file provider** — unavailable store raises `CredentialStoreUnavailableError`), `repository.py` (JSON at `atlas_home()/workspace/profiles.json`; `atlas_home()` = `$ATLAS_HOME` or `~/.atlas`), `service.py` (`ProfileService`: add/update/delete/get/list, `resolve_discovery_inputs`, `record_discovery`; saves secret before metadata, rolls back on failure), `exceptions.py`.
- **CLI:** `founderos atlas profile add|list|show|update|delete`; `founderos atlas discover --profile <name>` (skips all prompts).
- **Tests:** `tests/test_workspace_profiles.py` (28 tests incl. security regressions and an `UnavailableCredentialProvider` fake so tests pass with or without keyring installed).
- Optional dependency: `[credentials]` extra → `keyring>=24,<26`.

### PR-030.1 — Alpha Stabilization (committed `bc1123d`)
Three fixes:
1. **Packaging:** stale egg-info made `pip install "founderos-runtime[credentials]"` warn the extra didn't exist; regenerated metadata; test reads pyproject extras via tomllib (`tests/test_alpha_stabilization.py`).
2. **Health vs history:** introduced event semantics in `src/founderos_atlas/state/` — `EVENT_FAILURE / EVENT_DEGRADATION / EVENT_RECOVERY / EVENT_INFORMATIONAL` on `StateChange`; `StateChangeReport.active_issues`, `recoveries`, `current_health` (Healthy / Attention Required / Critical) computed from **active issues only**, never from historical event counts. A recovered interface returns Atlas to Healthy while events remain in history. Dashboard (`dashboard/summary.py`) and morning brief (`journeys/morning_brief.py`, `artifacts.py`) updated.
3. **Config diff noise:** `config_intelligence/diff.py` gained `CISCO_DYNAMIC_METADATA_PATTERNS` / `is_dynamic_metadata()` filtering `Current configuration : N bytes`, `! Last configuration change at …`, `! NVRAM config last updated…`, `! Time: …`, `Building configuration...` so cosmetic churn never appears as a config change.
- Tests: `tests/test_alpha_stabilization.py` (14 tests).

### PR-031 — GUI Application Shell (**uncommitted**, verified complete in working tree)
See §9 for full detail. Summary: `founderos atlas web` starts a loopback-only Flask GUI with 8 pages that reuses backend services in-process (never a subprocess); 13 new tests in `tests/test_web_app.py`; `[web]` extra → `flask>=3,<4`.

Earlier PRs (019–029) are stable, committed, and self-describing via commit messages, CHANGELOG.md, and tests. Do not rework them casually.

---

## 5. ATLAS NETWORK DISCOVERY ARCHITECTURE

### The unified 9-step pipeline (implemented in `atlas_discover_command`, `src/founderos_runtime/cli/commands.py`)
One command produces everything. Progress lines are `[N/9] <label> ... ok|skipped`. Steps: (1) connect/authenticate to seed, (2) multi-hop discovery, (3) identity reconciliation + snapshot, (4) optional configuration collection, (5) compare against previous baseline — topology changes AND operational state events, (6) morning brief, (7) topology viewer HTML, (8) executive dashboard, (9) preserve history.

### Data flow (actual names)
```
User: founderos atlas discover [--profile <name>]
 └─ cli/main.py → _parse_profile_flag → atlas_discover_command(...)
     ├─ Profile path: ProfileService.resolve_discovery_inputs(name)
     │    → ResolvedDiscoveryInputs (ip, username, password from keyring, depth, limits)
     │    → prints "Using profile: <name>", skips ALL prompts
     ├─ Prompt path (no --profile): interactive prompts for IP/username/password
     ├─ Transport: transport_factory(ConnectionDetails) → netmiko-backed SSH session
     │    (src/founderos_atlas/transport/; read-only show commands only)
     ├─ Multi-hop engine (src/founderos_atlas/discovery/): BFS from seed via CDP
     │    neighbors ("show cdp neighbors detail"), bounded by max_depth/max_devices;
     │    per-device: hostname, version, interfaces, IPs; failures recorded per host,
     │    never abort the whole run (DiscoveryReport.failed)
     ├─ Identity (src/founderos_atlas/identity/): canonical device identity merges
     │    duplicate sightings (same device via multiple IPs/names)
     ├─ TopologySnapshot (content-addressed, src/founderos_atlas/topology/):
     │    written to topology_snapshot.json
     ├─ Step 5: load_previous_baseline(history_root) → ChangeDetector (topology) +
     │    state detector (interface events) → change_report.* / state_change_report.*
     ├─ Brief/viewer/dashboard → morning_brief.md, atlas_topology.html, dashboard.html
     └─ Step 9: _record_history → HistoryRepository(history_root).save_discovery(...)
          archives all artifacts under .atlas/history/<record-id>/;
          if a profile was used → ProfileService.record_discovery(name, completed_at)
          updates the profile's last_discovery timestamp (best-effort)
```

### Key behaviors (all confirmed by code/tests)
- **Vendor support:** Cisco IOS/IOS-XE only. CDP is the neighbor protocol (no LLDP parsing today). Parsers hardened against real-device output variance (PR-019.1).
- **Auth failure:** connection/auth failure on the seed is a clean CLI error; failures on non-seed devices are recorded in the report and the run continues.
- **Duplicate devices:** identity reconciliation (PR-021.1) canonicalizes device_id vs hostname vs IP.
- **Rediscovery:** every run overwrites the fixed-name current artifacts and appends a new immutable history record. Step 5 diffs against the *previous baseline in the shared history* — see §7 for the multi-profile consequence.
- **Determinism:** no direct system-clock use in core logic; time comes from an injectable `Clock = Callable[[], datetime]`. Tests inject fixed clocks.
- **SSH is optional:** netmiko is behind the `[ssh]` extra with a lazy import and a clear error if missing. Fixture/demo commands need no network at all.

### Default artifact destinations (CWD-relative; confirmed in commands.py defaults)
`atlas_topology.html`, `topology_snapshot.json`, `morning_brief.md`, `dashboard.html`, `change_report.{json,md}`, `config_change_report.{json,md}`, `state_change_report.{json,md}`, `timeline.md`, `incident_report.{json,md}`, `configs/` (collected device configs), `.atlas/history/` (history root). All overridable via keyword arguments (used by tests and the web GUI).

---

## 6. WORKSPACE PROFILES

A **DiscoveryProfile** = named, reusable discovery configuration: `profile_id`, `name`, `site` (optional), `management_ip` (validated with `ipaddress.ip_address`), `username`, `credential_ref` (`atlas-profile:<slug>` — never the password), `max_depth` (0–4096), `max_devices` (1–4096), `collect_configuration`, `created_at`/`updated_at`/`last_discovery` timestamps.

- **Storage:** JSON at `~/.atlas/workspace/profiles.json` (override root with env `ATLAS_HOME`). Corrupt JSON → `WorkspaceCorruptedError`.
- **Credentials:** stored in the OS keyring (service name `founderos-atlas`) via `KeyringCredentialProvider`; requires `pip install "founderos-runtime[credentials]"`. If no secure store is available, profile creation **fails** (`CredentialStoreUnavailableError`) — there is no plaintext fallback, by design. `ProfileService.add_profile` saves the secret first and rolls back the secret if metadata persistence fails. `delete_profile` deletes the credential too.
- **Multiple profiles:** coexist in the same profiles.json; names are unique (case-insensitive slug via `normalize_name`); `DuplicateProfileError` on collision.

### Exact CLI commands (verified against `cli/main.py` routing and help output)
```
founderos atlas profile add        # interactive prompts; password via masked getpass
founderos atlas profile list       # table: NAME SITE MANAGEMENT IP USERNAME LAST DISCOVERY
founderos atlas profile show <name>
founderos atlas profile update <name>
founderos atlas profile delete <name>
founderos atlas discover --profile "<name>"   # zero prompts; prints "Using profile: <name>"
```
Rendered output always shows `Password: stored securely (never displayed)`.

### GUI behavior (PR-031)
`/profiles` list, `/profiles/new` + POST `/profiles` create, `/profiles/<name>/edit` + POST `/profiles/<name>` update (password field never pre-filled; blank = keep current), POST `/profiles/<name>/delete`. Discovery page offers a profile dropdown only — no IP/credential fields exist in the GUI at all.

### Current limitations
- Profiles are global to the machine user (`~/.atlas`), not per-project — while artifacts/history are CWD-relative. This asymmetry feeds the §7 issue.
- No profile export/import; no per-profile output/history scoping (§7).

---

## 7. MULTI-PROFILE / MULTI-LAB DISCOVERY BEHAVIOR ⚠️ (most important known issue)

**Observed behavior (reported from live lab use — Environment-specific / runtime observation):** discovering one profile appears to replace/remove devices previously discovered under another profile.

**Code-level determination (Confirmed by code, 2026-07-10):**

1. **Devices are not globally stored in any database.** The "current network" is exactly the latest `topology_snapshot.json` (plus sibling artifacts) at fixed CWD-relative paths. Every discovery run — regardless of which profile ran it — **overwrites the same files**. The GUI dashboard/topology pages read those same fixed paths (`web/routes.py` uses a single `ATLAS_OUTPUT_DIR`). So after discovering Lab B, Lab A's devices are gone from every "current" view. This is overwrite-by-design meeting multi-profile reality — not data corruption.
2. **History is shared and profile-blind.** `HistoryRepository` lives at one `.atlas/history` root; `save_discovery(...)` (see `_record_history` in `cli/commands.py`) records timestamps, counts, status, artifacts — **but no profile name/id field exists in history records** (verified: no `profile` reference anywhere in `src/founderos_atlas/history/`). Past runs of both labs are preserved but indistinguishable.
3. **Cross-profile false changes.** Step 5 diffs the new snapshot against `load_previous_baseline(history_root)` — the previous run *whatever profile produced it*. Discovering Lab B right after Lab A yields a change report full of spurious "devices removed / devices added" and operational events. This also pollutes `current_health`.
4. **Scoping summary:** profiles are scoped per-user (`~/.atlas/workspace`); artifacts + history are scoped per-CWD; **nothing is scoped per-profile.**

**Not fixed as part of this handoff (per instruction).** Likely files for the fix: `cli/commands.py` (derive per-profile output/history roots), `history/repository.py` + history models (record profile identity), `workspace/service.py` (expose per-profile paths), `web/app.py`/`routes.py` (profile-aware artifact serving), `dashboard/summary.py`. **This should be the next PR** (see §16). Current workaround: run each lab's discovery from a different working directory.

**No test covers cross-profile isolation** — the gap is real and untested (Confirmed by absence of such a test).

**Lab names:** "Hyderabad Lab" exists in the repo only as a documentation/test fixture name (apps/atlas/README.md examples, tests/test_web_app.py, tests/test_workspace_profiles.py, profile_form.html placeholder, workspace/README.md). "Secunderabad Lab" appears **nowhere in the repository** — Environment-specific / Unverified from repository.

---

## 8. CML / NETWORK LAB ENVIRONMENT

Everything in this section is **Environment-specific / Unverified from repository** unless noted. The product must never hardcode these.

- The owner tests against **Cisco Modeling Labs (CML)** with Cisco IOS/IOS-XE devices, reachable over SSH from the Windows dev machine.
- At least two labs/profiles have been used in testing (names like "Hyderabad Lab" / "Secunderabad Lab"). The multi-lab usage is what surfaced the §7 isolation issue.
- Product assumptions that ARE verified in code: SSH reachability to a seed management IP; username/password auth; devices answer `show version`, `show ip interface brief`, `show cdp neighbors detail`, `show running-config` (config collection); CDP enabled for neighbor discovery; read-only posture (no config-changing commands are ever sent — grep the transport/discovery modules to confirm; also stated in apps/atlas/README.md).
- Netmiko (`[ssh]` extra) is installed in the dev venv; one test skips when netmiko IS installed (the "netmiko missing" error-path test) — that is the suite's 1 skip.

---

## 9. CURRENT WEB GUI STATUS (PR-031 — uncommitted)

- **Stack:** Flask 3 (server-rendered Jinja templates) + hand-written CSS/JS (`static/atlas.css`, `atlas.js` — no framework, no build step, no CDN for the GUI shell itself). Optional `[web]` extra (`flask>=3,<4`); lazy import with a helpful error if Flask is missing.
- **Start:** `founderos atlas web` → prints `Atlas web UI running at:` / `http://127.0.0.1:8765`, opens the browser, serves on loopback. `atlas_web_command` in `cli/commands.py`; host is fixed to `127.0.0.1` (`DEFAULT_HOST`/`DEFAULT_PORT` in `web/app.py`); never `0.0.0.0`.
- **Architecture:** app factory `create_app(*, profile_service, output_dir, history_root, transport_factory, clock, workspace_root)` — every dependency injectable, enabling full-stack tests via Flask's test client including a real scripted-network discovery run. Routes (`web/routes.py`) are thin adapters over the same backend services the CLI uses, **in-process** — a test asserts the web package contains no `subprocess`/`Popen`/`os.system`. View-model shaping in `web/models.py` (`profile_row()` never includes a password). Config keys: `ATLAS_PROFILE_SERVICE`, `ATLAS_OUTPUT_DIR`, `ATLAS_HISTORY_ROOT`, `ATLAS_WORKSPACE_ROOT`, `ATLAS_TRANSPORT_FACTORY`, `ATLAS_CLOCK`, `ATLAS_HOST`.
- **Routes:** `GET /` (dashboard summary via `build_dashboard_summary`), `GET/POST /profiles`, `GET /profiles/new`, `GET /profiles/<name>/edit`, `POST /profiles/<name>`, `POST /profiles/<name>/delete`, `GET /discovery`, `POST /discovery/run` (runs `atlas_discover_command(profile=…)` in-process, shows result card + collapsible `[1/9]…[9/9]` log), `GET /topology` (iframe over `/artifacts/atlas_topology.html`), `GET /history` (`HistoryRepository`), `GET /changes` (topology/config/state summaries), `GET /incidents` + `POST /incidents/run` (`IncidentInvestigator`), `GET /settings` (workspace paths, credential provider + availability, bind host, version), `GET /artifacts/<path>` (read-only `send_from_directory` from the output dir).
- **What a user can actually do today:** view the dashboard; create/edit/delete profiles (masked password, never pre-filled); run discovery from a saved profile with zero credential entry; view topology viewer, history, change summaries; generate incident investigations; check settings. All pages render gracefully with an empty/missing workspace.
- **Error/loading:** flash messages for validation/service errors; the Run Discovery button disables on submit (atlas.js); discovery **blocks the request** until the pipeline completes — no progress streaming yet.
- **Known GUI limitations (confirmed):** Flask dev server, single-user, no auth/CSRF (loopback alpha, documented in `web/README.md`); synchronous discovery; artifacts read from one CWD-relative output dir (→ §7); topology iframe's Cytoscape viewer needs internet on first load; `app.secret_key` is a hardcoded constant used only for flash messages.

---

## 10. CURRENT CLI COMMANDS

Verified by running `founderos help` (via `main()`) on 2026-07-10. Entry point: `founderos` (console script) → `founderos_runtime.cli.main`.

```
founderos version                     # "FounderOS v0.3 Alpha"
founderos doctor                      # check deterministic demo dependencies
founderos demo discovery              # in-memory Discovery vertical slice (platform demo)
founderos atlas demo discovery        # fixture-only Atlas discovery (no network)
founderos atlas demo topology         # generate + open topology viewer from fixtures
founderos atlas morning-brief         # evaluated operational brief
founderos atlas web                   # start local GUI at http://127.0.0.1:8765
founderos atlas discover              # interactive live discovery (prompts for IP/user/password)
founderos atlas discover --profile <name>   # zero-prompt discovery from a saved profile
founderos atlas profile add|list|show|update|delete
founderos atlas compare <previous.json> <current.json>   # topology change report
founderos atlas dashboard             # regenerate executive dashboard
founderos atlas history               # list every preserved discovery
founderos atlas timeline              # generate timeline.md
founderos atlas config-diff <previous> <current>
founderos atlas config-diff --latest <hostname>   # diff last two collected configs
founderos atlas state-diff <previous.json> <current.json>
founderos atlas state-diff --latest   # interface-state diff of last two snapshots
founderos atlas investigate           # structured incident investigation from artifacts
founderos help
```

Notes: `atlas discover` needs `[ssh]` (netmiko) and a reachable device; `--profile` needs `[credentials]` (keyring); `atlas web` needs `[web]` (flask). Demo/fixture commands need nothing extra. Install for development: `pip install -e ".[ssh,credentials,web,dev]"`.

---

## 11. CURRENT TEST STATUS

- **Command:** `.venv/Scripts/python -m pytest tests/ -q` (Windows venv, Python 3.14).
- **Result on 2026-07-10 (with uncommitted PR-031 in the tree): 557 passed, 1 skipped, 105 subtests passed** in 121.25s (~2 min).
- The 1 skip is environment-conditional: a "netmiko not installed" error-path test that skips because netmiko IS installed in this venv.
- No failures, no xfail/xpass. Warnings: none significant (occasional git CRLF warnings are from git, not pytest).
- Suite is hermetic: scripted fakes for the network (`ScriptedNetwork`/`device_outputs` in tests/test_multihop_discovery.py, `FakeConnection` in tests/test_atlas_transport.py), `InMemoryCredentialProvider` + `UnavailableCredentialProvider` for credentials, injected fixed clocks, temp dirs for all artifacts. Tests must pass with or without keyring/flask/netmiko installed (keyring-sensitivity was a real bug fixed after PR-030).

---

## 12. CURRENT GIT STATE (as of 2026-07-10)

- **Branch:** `main` (also the PR/default branch). No remotes configured for pushing observed in workflow — work is committed locally.
- **HEAD:** `bc1123d` — "PR-030.1: Stabilize credentials, health status, and config diff noise".
- **Working tree: NOT clean — intentionally.** Uncommitted PR-031:
  - Modified: `CHANGELOG.md`, `apps/atlas/README.md`, `pyproject.toml`, `src/founderos_runtime/cli/{commands,main,render}.py`
  - Untracked: `src/founderos_atlas/web/` (17 source files + __pycache__), `tests/test_web_app.py`
  - `CLAUDE_HANDOFF.md` (this file) is also untracked.
- `deliverables/` and generated artifacts are gitignored.
- **Do not commit anything unless the owner explicitly asks.** When asked, the expected shape is a single `PR-031: …` commit in the established style.

---

## 13. IMPORTANT ARCHITECTURAL DECISIONS (preserve these)

1. **Platform/product split:** FounderOS (`founderos_runtime`) stays domain-agnostic; all network logic in `founderos_atlas`. Guarded by `tests/test_service_boundaries.py`.
2. **Deterministic core:** no system clock in business logic — time is an injectable `Clock`. No randomness in outputs. Snapshots are content-addressed and re-validated (`TopologySnapshot.from_dict`).
3. **Injectable everything:** `main()` and commands accept factories/paths/readers (`atlas_transport_factory`, `atlas_input_reader`, `atlas_password_reader`, `atlas_clock`, `atlas_profile_service`, `atlas_web_server_runner`, `atlas_browser_opener`, per-artifact `*_output` paths). This is what makes the suite hermetic. **Every new side effect must follow this pattern.**
4. **Credential security is non-negotiable:** no plaintext storage or fallback, ever; passwords never in JSON/logs/reports/history/HTML/CLI output; `DiscoveryProfile` has no password field — only `credential_ref`. New credential backends implement the `CredentialProvider` ABC.
5. **GUI never shells out:** web routes call services in-process; a test enforces no subprocess usage. Keep GUI thin — business logic belongs in services.
6. **Local-only GUI:** bind `127.0.0.1` only; never `0.0.0.0`.
7. **Read-only network posture:** discovery/config collection send only `show` commands.
8. **Graceful degradation:** optional deps (`ssh`/`credentials`/`web`) are lazy-imported with actionable install messages; per-device failures never abort a run; history persistence is best-effort and never fails a successful discovery.
9. **Event semantics (PR-030.1):** `current_health` derives from active issues only; history counts must never make a healthy network look degraded. Don't regress this.
10. **Testing philosophy:** unittest-style tests run under pytest; fakes over mocks; fixed clocks; temp dirs; environment-independence (pass with or without optional deps installed).
11. **Backward compatibility:** e.g. `StateChangeReport.status` kept as an alias of `current_health`. Existing CLI flows must keep working when features are added (PR-031 changed no CLI behavior).
12. **Data isolation expectation (aspirational, NOT yet implemented):** users expect per-profile/lab separation of discovered data. Current shared-artifact behavior is the known gap (§7).

---

## 14. KNOWN ISSUES AND TECHNICAL DEBT

| # | Item | Classification |
|---|---|---|
| 1 | **Multi-profile data isolation missing** — artifacts and history are shared across profiles; latest run overwrites the "current" view; step-5 baseline diffs cross profiles producing false changes; history records carry no profile identity | Confirmed by code (+ runtime observation) |
| 2 | GUI discovery is synchronous — blocks the HTTP request for the whole pipeline; no progress streaming | Confirmed by code |
| 3 | No auth / no CSRF tokens on GUI forms (loopback single-user alpha) | Confirmed by code |
| 4 | Flask dev server used directly (not production-grade) | Confirmed by code |
| 5 | Topology viewer loads Cytoscape from a CDN — first load needs internet | Confirmed by code |
| 6 | `app.secret_key` is a hardcoded constant (flash-only; harmless on loopback, should be random later) | Confirmed by code |
| 7 | Artifacts/history are CWD-relative → running CLI/GUI from a different directory shows different data | Confirmed by code |
| 8 | Cisco-only, CDP-only neighbor discovery (no LLDP, no other vendors) | Confirmed by code |
| 9 | No test covers cross-profile isolation behavior | Confirmed by absence of test |
| 10 | History records lack profile metadata (blocks per-profile history UI) | Confirmed by code |
| 11 | `founderos_runtime/workspace` and `founderos_atlas/workspace` are different packages with the same name — potential confusion | Confirmed by code (naming debt) |
| 12 | Keyring behavior on machines without a secure store: profile creation intentionally fails (correct per spec, but may surprise users; error message points to the fix) | Confirmed by code + test |
| 13 | GUI has no device-list page (devices visible via topology viewer/dashboard only) | Confirmed by code |
| 14 | Possible auth/routing quirks in the owner's CML labs (exact details not in repo) | Environment-specific / Unverified |

---

## 15. EXACT CURRENT STOPPING POINT

- **Last completed PR:** PR-031 (GUI Application Shell). **Complete, verified, uncommitted.**
- **Last completed task:** producing the PR-031 deliverables zip (`deliverables/pr-031-web-gui-shell-package.zip`, local-only) and this handoff document.
- **Immediately before this handoff:** PR-031 was implemented and verified (all routes 200 via test client AND a live loopback server smoke; zero password leak across rendered pages; full suite green), the deliverables package was produced, then the owner asked for this handoff before any further work.
- **Test status:** 557 passed / 1 skipped / 105 subtests (see §11).
- **Git status:** HEAD `bc1123d` (PR-030.1); PR-031 change set uncommitted (see §12). PR-030, PR-030.1, PR-031 all await the owner's **manual CML validation**; PR-031 additionally awaits an explicit "commit" instruction.
- **Issue discovered after PR-031:** the multi-profile/multi-lab isolation behavior (§7), surfaced by the owner's use of two lab profiles.
- **Next logical step:** owner validates manually → owner asks to commit PR-031 → then the next PR (recommendation below).
- **Files most likely to change next:** `src/founderos_runtime/cli/commands.py`, `src/founderos_atlas/history/repository.py` (+ history models), `src/founderos_atlas/workspace/service.py`, `src/founderos_atlas/web/{app,routes}.py`, `src/founderos_atlas/dashboard/summary.py`, new tests.

---

## 16. NEXT RECOMMENDED PR / TASK

**PR-032 — Per-Profile Workspace Isolation** *(the PR-0XX naming convention is established; 032 is the natural next number).*

- **Problem:** discovering one profile overwrites the current artifacts of another and produces false cross-profile change reports; history cannot distinguish labs (§7). This is a correctness bug in the product's core promise ("what changed in MY network"), observed in real lab use.
- **Why next (over async GUI progress):** alpha correctness beats UX polish; every multi-lab user hits it immediately; it also unblocks per-profile history/dashboard views that the GUI will need anyway. (Async discovery progress — previously sketched as a PR-032 candidate — should become the following PR.)
- **User impact:** each profile keeps its own current topology/dashboard/history; switching profiles in the GUI switches the whole view; change reports only ever compare runs of the same profile.
- **Technical goal (suggested shape — validate before implementing):** derive per-profile roots (e.g. `<output>/profiles/<slug>/` and `.atlas/history/profiles/<slug>/`, or under `ATLAS_HOME`) when `--profile` / GUI profile is used; stamp profile identity into history records; make step-5 baseline lookup profile-scoped; GUI gains an active-profile context for dashboard/topology/history/changes/artifacts. Keep profile-less interactive discovery working unchanged (backward compatibility) — treat it as a "default" scope.
- **Acceptance criteria:** discovering profile B never alters profile A's current artifacts, history, or health; step-5 baseline comes only from the same profile; history rows show the profile; GUI views are profile-scoped; all existing tests still pass; profile-less flow unchanged.
- **Tests required:** two-profile isolation end-to-end (CLI and web); cross-profile false-change regression (discover A then B → B's change report shows no removals of A's devices); history profile-stamping; migration/compat for existing un-stamped history records.
- **Regression risks / must not break:** profile-less `atlas discover`; `--latest` commands (config-diff/state-diff) that walk history; dashboard artifact links; history archive format compatibility; the deterministic/injectable-path testing pattern; credential security invariants.

---

## 17. NEXT 5 PRIORITIES (ordered)

1. **PR-032: Per-profile workspace isolation** (§16) — correctness bug, alpha-blocking for multi-lab users.
2. **Async discovery jobs + live progress in the GUI** — background job runner + status polling turning the existing `progress` callback into a live `[1/9]…[9/9]` view; biggest UX gap on real multi-device CML runs.
3. **Device inventory view (GUI + CLI)** — a first-class device list from the current snapshot (per profile once #1 lands); today devices are only visible inside the topology viewer/dashboard.
4. **Offline topology viewer** — bundle/inline Cytoscape (or ship a vendored asset) so the viewer works with no internet; labs are often isolated.
5. **GUI hardening pass** — CSRF tokens, random secret key, optional simple auth toggle, and a production-server note — prerequisites for letting anyone but the owner run it.

(Avoid speculative feature creep: AI diagnostics, multi-vendor, and cloud credential backends are explicitly future work.)

---

## 18. FILE MAP FOR THE NEXT CLAUDE SESSION

| Path | Purpose / why you care |
|---|---|
| `src/founderos_runtime/cli/main.py` | CLI arg routing + all injectable dependency plumbing. Any new command/flag starts here. |
| `src/founderos_runtime/cli/commands.py` | All command logic incl. the 9-step `atlas_discover_command`, profile commands, `atlas_web_command`, `_record_history`. The center of gravity for PR-032. |
| `src/founderos_runtime/cli/render.py` | All human-readable CLI text (help, tables, reports). |
| `src/founderos_atlas/workspace/` | Profiles + credentials (models, credentials, repository, service, exceptions, README). Security invariants live here. |
| `src/founderos_atlas/web/` | **Uncommitted PR-031 GUI** — app.py (factory), routes.py (adapters), models.py (view models), templates/, static/, README.md. |
| `src/founderos_atlas/discovery/` + `transport/` | Multi-hop engine and SSH transport abstraction (netmiko behind `[ssh]`). |
| `src/founderos_atlas/topology/` + `identity/` + `visualization/` | Graph, content-addressed snapshots, canonical identity, HTML viewer. |
| `src/founderos_atlas/change/`, `config_intelligence/`, `state/` | Topology diff, config diff (+ dynamic-metadata filter), operational events + `current_health`. |
| `src/founderos_atlas/history/` | `HistoryRepository`, record storage — needs profile stamping in PR-032. |
| `src/founderos_atlas/dashboard/` + `journeys/` + `incidents/` | Executive dashboard, morning brief, incident investigator. |
| `tests/test_web_app.py` | 13 GUI tests (uncommitted) — the pattern for testing the GUI. |
| `tests/test_workspace_profiles.py` | 28 profile/credential tests incl. security regressions. |
| `tests/test_multihop_discovery.py` | `ScriptedNetwork` / `device_outputs` fakes — reuse for any discovery test. |
| `tests/test_alpha_stabilization.py`, `test_operational_state.py`, `test_unified_pipeline.py` | Event-semantics and pipeline contracts — don't regress the wording/health rules they pin. |
| `apps/atlas/README.md` | Product-facing docs: quick start, pipeline, profiles, GUI, security posture. Update with every user-visible change. |
| `CHANGELOG.md` | Per-PR changelog; updated every PR. |
| `pyproject.toml` | Extras: `ssh`, `credentials`, `web`, `dev`; package-data for web templates/static. |
| `docs/` (handoffs, reviews, rfcs) | Older platform-era docs (Milestone 12, v0.2 review, RFC-0001) — context, not current work instructions. |
| `deliverables/` (gitignored) | Per-PR zip packages for the owner (handover, sample output, test results, changed files). Convention: produce one per PR when asked ("zip pls"). |

---

## 19. FRESH SESSION STARTER PROMPT

Copy-paste this into a fresh Claude Code session:

```
Read CLAUDE_HANDOFF.md in the repository root completely before doing anything else.

Then, before any implementation work:

1. Inspect the actual repository structure (src/founderos_runtime, src/founderos_atlas, tests, apps/atlas).
2. Run: git status
3. Review recent history: git log --oneline -15
4. Inspect the latest completed PR (PR-031, the Atlas web GUI): src/founderos_atlas/web/ and tests/test_web_app.py. Note that PR-031 is intentionally UNCOMMITTED — do not commit it.
5. Run the full test suite: .venv/Scripts/python -m pytest tests/ -q
6. Compare what you find against CLAUDE_HANDOFF.md. Repository reality is the source of truth — if the repo and the handoff disagree, trust the repo.
7. Report any discrepancies you find between the handoff and the repository.
8. Then give me a brief summary covering:
   - What FounderOS and Atlas are
   - What has been completed (PR-019 through PR-031)
   - What PR-031 accomplished
   - The current architecture
   - Known issues (especially the multi-profile data isolation issue in section 7)
   - The exact current stopping point
   - The recommended next task (PR-032: per-profile workspace isolation)

Rules:
- Do NOT make major implementation changes until I approve the next task.
- Do NOT commit or tag anything unless I explicitly ask.
- Never store or display credentials in plaintext; preserve all security invariants in handoff section 13.
- Repository reality is the source of truth.
```
