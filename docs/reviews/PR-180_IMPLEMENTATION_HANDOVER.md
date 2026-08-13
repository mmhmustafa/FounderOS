# PR-180 IMPLEMENTATION HANDOVER — Beta Hygiene

Implements the FINAL APPROVED IMPLEMENTATION PLAN (§30 of
`PR-180_BETA_HYGIENE_ARCHITECTURE_REVIEW.md`). **Not pushed** —
awaiting review under the current workflow.

## 1. Executive result

Atlas is now identifiable (one quiet product-identity line for every
identified operator, a build identifier that is printed only when
provable), supportable (a diagnostics artifact under an exact-key-set
allowlist that can finally say which workspace and what the last
discovery did), safe to report (the bulk internal failure and the
job deep link both hand over resolvable identifiers; user-correctable
errors stopped handing over noise), clear to operate (the topology
legend is reachable at the default level, the unresolved-peer count
tells the truth about what is drawn, startup states where results
live and how to recover), and freer of developer residue (no Python
class names in operator copy, no dev-build vocabulary in the chrome,
no dead 403 links in failure banners) — while exposing strictly LESS
information than before: the diagnostics artifact dropped its
spread-borne fields, proxy addresses became a count, and 400/404/429
pages dropped their irrelevant correlation ids.

## 2–5. State

- **Starting HEAD:** `bd50303` (clean tree + the untracked architecture review).
- **Final HEAD:** the docs commit carrying the architecture review and
  this handover — the last commit on the branch.
- **Working tree:** clean after the docs commit.
- **Commits (oldest first):**

| Commit | Step |
|---|---|
| `e9e49b2` | Step 0 — diagnostics allowlist + frozen build identity (guard rails) |
| `18de010` | Step 1 — build identity printed only when provable; seam; CLI suffix |
| `ffd796f` | Step 2 — one line of product identity; posture rewording; jump-link gate |
| `c4cf77e` | Step 3 — diagnostics _notice, fingerprints, last_discovery, platform |
| `9cc0283` | Step 4 — bulk failure id + /discovery?job= + correlation rule |
| `0cfcae2` | Step 5 — startup truth |
| `684d35b` | Step 6 — comprehension and reach |
| `7334b9a` | Step 7 — copy corrections |
| `9bcce27` | Step 8 finding — alpha-CLI version pin accepts both lawful identity states |
| (docs)   | architecture review + this handover |

## 6. Files changed

Source: `release.py`, `web/app.py`, `web/routes.py`, `web/security.py`,
`web/system_info.py`, `web/observability.py` (untouched — pinned),
`web/schedule_routes.py`, `scheduling.py`, `workspace/update_info.py`,
`visualization/renderer.py`, `visualization/templates/topology.html`,
`founderos_runtime/cli/commands.py`; templates: `base.html`,
`settings.html`, `system_update.html`, `error.html`, `topology.html`,
`_topology_facts.html`, `_device_actions.html`, `_degraded.html`,
`changes.html`, `policy.html`, `policy_result.html`, `timeline.html`,
`audit.html`, `configuration.html`, `configuration_device.html`,
`evidence_index.html`, `evidence_resolution_center.html`,
`advisor.html`, `compass_plan.html`, `credentials.html`, `users.html`,
`console_index.html`; `static/atlas.css`. Tests: five new files
(`test_diagnostics_contract`, `test_product_identity`,
`test_reportable_failures`, `test_beta_comprehension`,
`test_copy_honesty`) plus additions to `test_release_trust` and
`test_web_app`.

## 7. Step-0 guardrails

`build_commit()` is `@lru_cache(maxsize=1)`; `register_observability`
primes it during `create_app`, before any request, so the frozen value
describes the bytes the process loaded — a priming-order test fails
loudly if either half is ever removed. `/settings` and
`diagnostics.json` spawn **zero** subprocesses after startup (pinned;
previously two uncached ~47 ms `git rev-parse` calls per `/settings`
render). The diagnostics payload is an explicit literal allowlist —
no `**spread`, no `__dict__` — with an exact-key-set test that failed
the build the very first time a new field (`prerelease`) touched
`collect_system_information`, which is precisely the workflow it
exists to force.

## 8–11. Build identity trust

An identifier is returned **only** when `git describe --always
--dirty` carries no dirty suffix AND `release.py` itself is tracked by
the repository found two levels up. **Dirty tree → None** (pinned).
**Foreign parent repository → None** (pinned). **Non-git / absent git
→ None, never raises** (pinned). Resolution seam: `ATLAS_BUILD_ID`
env var → generated `founderos_atlas._build_id` module → trusted git →
None — the seam ships, packaging-time injection does not. Both
rendering templates share the one causeless fallback, "not available
in this build". Live observation: with the repository's tag, describe
yields `v0.3.0-alpha1-58-g<hash>` — a *more* descriptive identifier
than the old bare hash, still git-provable (recorded as deviation D6).
`founderos version` appends ` (build <id>)` only when provable;
`founderos help` never does (both pinned).

## 12. Version / Beta surfaces

One line — `FounderOS Atlas 0.3.0a1 · Beta` — at the foot of every
page's `<main>` for every **identified** principal (context-processor
guard on `g.principal`): verified live for a network-operator on a
password-mode world, on error pages, and absent byte-for-byte from the
login screen. The Beta token also joins the two existing version lines
(admin Settings card, update page). Pre-release detection is an
anchored PEP 440 test (`is_prerelease()`, pinned over nine version
shapes including `0.3.0.dev1` and `1.0.0+build.5`). The commit hash
never enters shared chrome (pinned). The sidebar posture line reads
`Single-operator access · loopback only`; the Settings jump link
renders only for roles that receive its anchor (pinned both ways).

## 13–15. Diagnostics contract

**Exact key set (28 keys, test-pinned):** `_notice`, `product`,
`version`, `display_version`, `prerelease`, `build_commit`,
`workspace_schema_version`, `workspace_schema_target`,
`workspace_fingerprint`, `active_scope_fingerprint`,
`active_scope_kind`, `last_discovery`,
`failed_attempts_since_success`, `host_platform`,
`authentication_mode`, `credential_provider`,
`credential_provider_available`, `tls_enabled`, `hsts_enabled`,
`trusted_proxy_count`, `session_mode`, `logging_level`,
`retention_policy`, `update_provider`, `python`, `profile_count`,
`preferences` (six named fields, `updated_at` deliberately omitted),
`generated_at`.

**Explicitly excluded** (dropped from the pre-PR-180 artifact or
banned): every filesystem path (workspace/output/history/log), `bind`
+ observation, trusted-proxy **addresses** (now a count), the
credential provider's Python class name, `session_expiry`,
worker/schedule internals including `schedule_worker_last_error`'s
foreign text, all telemetry fields, `preferences.__dict__`, and — by
grep-pinned prohibition — platform node/uname, socket hostname and OS
login-name lookups. `last_discovery` is literal construction
`{status, finished_at, profile_fingerprint}`; pinned that the same
job record's profile id, display name and management address do NOT
appear anywhere in the artifact.

## 16. Fingerprints

`sha256(value)[:12]` over the resolved workspace root / scope id /
profile id. Pinned: 12 lowercase hex; stable across exports from one
workspace; different across workspaces; not a substring of the path.
`active_scope_kind` ∈ {enterprise, profile, default}.

## 17. Correlation-id behaviour

The §8 rule (show iff internal-class AND resolvable) applied to the
identified sites only: the bulk internal failure now logs
`bulk change action failed correlation=<id>` with `exc_info` and
flashes "…Quote <id> when reporting this." with the id interpolated
at flash time; 400/404 pages and the 429 deny hide the id; 500 keeps
it. The flag is inverted (`hide_correlation`) so future call sites
fail toward showing a resolvable id. `JsonLineFormatter`'s
class-name-only property is now test-pinned — the guarantee that
logging the detail cannot leak it. JSON API error payloads keep their
ids (machine data; noted, unchanged).

## 18. /discovery?job=

Validated against `^[0-9a-f]{12}$` (the manager's own id shape;
anything else never reaches it). Valid → exactly that job (verified
live against a real persisted older failed job while a newer success
existed — no substitution). Well-formed unknown → "That discovery run
is no longer in this Atlas's job history." and **no** job panel.
Malformed → treated as absent. All three pinned and live-verified.

## 19. Startup changes

`founderos atlas web --port N` is the recovery command everywhere it
is offered (the old bare `atlas` produced "command not found" at the
exact moment recovery was needed). `create_app` failures catch
`Exception` (a `ValueError` previously escaped as a raw traceback)
and the terminal gets canonical copy while `logger.exception` gets
the detail — pinned with a poisoned `OSError` whose filename reaches
neither message. Bind failures name `errno` (a number) and the real
command. Startup prints `Results are stored in: <output dir>` and
`Press Ctrl+C to stop Atlas.`; the path is approved for the terminal
and admin Settings only, and a comment marks that boundary. The
framework's development-server warning is **kept** — it is true.

## 20. Topology changes

Legend: a `<details>` — closed (reachable) at `simple`, open
otherwise; the `display:none` rule is gone (verified in a
freshly-rendered artifact). Unresolved peers: the state is derived
from the LIVE layer checkbox inside `apply()` and stated beside the
switch; the header's term carries its canonical
`topology/vocabulary.py` definition, injected by the renderer and set
via property assignment (innerHTML remains forbidden). Canonical
count definitions: one accessible "Canonical definitions" disclosure;
the hover-instruction sentence is gone. Site filter: `aria-current`.
The PR-179 freshness banner is preserved (live-verified).

## 21. Accessibility changes

`_device_actions.html`: SSH-unavailable reason, certificate warning
and the disabled Web button's reason all ride `visually-hidden` spans
(a `disabled` control is untabbable, so `title` could never fire).
`role="button"` removed from **seven** `<summary>` elements (audit
predicted one — deviation D1), sweep-pinned. Ctrl+K: the active
result row gains an inset accent bar (measured live:
`rgb(37,99,235) 3px inset`), and the search input regains a
focus-visible indicator.

## 22. Touch changes

Two additions to the existing `@media (pointer: coarse)` block using
the existing `--control-height-sm` token: `.grid input[type=checkbox]`
and `.chip-remove`. Verified under **real coarse-pointer emulation**
(mobile preset; `matchMedia('(pointer: coarse)')` true): the bulk
row-select and select-all checkboxes render **30×30** (from 13×13).
Desktop density untouched; the dead checkbox-sibling selector removed.

## 23. Copy / honesty changes

Restore names what it replaces (categories: accounts with password
hashes, audit log, annotations, incidents, profiles, policy
exceptions, schedules) plus snapshot-first and restart-required —
before the click. Backup blurb names the password-hash inclusion.
The retention contradiction is gone. The Credentials page uses
`provider_display_name` (an in-memory provider now says
"non-persistent" where a tester saves passwords). Three schedule
messages and the worker's `last_error` drop their exception-class
suffixes. Console Disconnect names whose session dies and where.

## 24. Privacy adversarial results

All twenty attacks run; none survive. Highlights: the diagnostics
artifact contains no path, username, hostname, device address, or
profile/site/network name (pinned against the very fixture values
that ARE in the job file it reads); a future dataclass field cannot
enter it (exact-key-set); dirty/foreign/non-git builds print nothing
rather than a lie; the cached identity cannot change under a running
process; every shown id is resolvable and every unresolvable context
shows none; no startup error carries a filename; topology essential
meaning is reachable without hover; the legend is reachable at
simple; Ctrl+K selection is not colour-only; coarse checkboxes are
30×30; and the PR-179 failure/freshness wording renders byte-alike
(live) with every PR-179 test file green.

## 25. Browser validation

Three worlds (local first-run, password-mode injection world with
three roles, password-mode bulk world), at 375/768/1440/1920 plus a
**genuine coarse-pointer emulation pass** (a narrowed desktop window
does not activate touch rules — the review's own caveat, honoured).
Verified live: Settings card (version · Beta, described build
identifier, diagnostics notice, restore/retention/backup prose),
diagnostics.json (28 keys, `_notice` first, fingerprints, no path),
identity footer on every identified page incl. error pages and its
absence on login, non-admin Settings without the jump link, the job
deep link (valid/unknown/malformed against real persisted jobs), the
freshly-rendered topology artifact (legend details, live unresolved
note, canonical definition, zoom untouched), the freshness banner,
the gated integrity link as viewer vs admin, Ctrl+K indicator and
input focus rule, 404 without an id and with the footer, and zero
horizontal overflow at all four widths.

## 26. Performance validation

The only per-request cost PR-180 touches it REMOVED: `/settings` paid
two git subprocesses per render (measured ~47 ms each, 5 s timeout
worst case); both are now a startup-primed cache hit, pinned by a
no-subprocess test. Everything added to a normal render is constant
work (one context-processor dict, template conditionals). PR-176
budgets untouched.

## 27–28. Suite and tests

Full suite: **3285 passed, 2 skipped, 933 subtests passed, 0 failed**
(11:25; baseline before PR-180: 3219 passed, 2 skipped, 924 subtests —
**+66 tests, +9 subtests, no regressions**). Tests added: five new
files (`test_diagnostics_contract` 10, `test_product_identity` 8,
`test_reportable_failures` 8, `test_beta_comprehension` 13,
`test_copy_honesty` 11) plus twelve additions to `test_release_trust`
and three to `test_web_app`. Changed existing tests, each deliberate
and commented: the port-in-use pin tightened to
`founderos atlas web --port`; the local-posture pin updated to the new
wording; the alpha-CLI version pin re-shaped to accept both lawful
identity states (its exact-equality form was environment-dependent
under the trust rule — it passed on every dirty mid-implementation
tree and failed the moment the checkout became clean). No assertion
weakened: each replacement pins the same product contract or a
stricter one.

## 29. Deviations from architecture

- **D1** — `role="button"` on `<summary>`: audit said one instance;
  seven existed. Same one-attribute defect, same fix applied to all,
  sweep-pinned. (Scope: pure deletion, zero behaviour change.)
- **D2** — product identity uses a **context processor**, not a
  template global: the identified-principal guard is request state.
  Same surface, same output.
- **D3** — `_provider_name` was promoted to public
  `provider_display_name` with the private name kept as an alias for
  the internal caller (the review said promote; the alias avoids a
  needless second edit site).
- **D4** — Step 0's allowlist conversion also **narrowed** the
  artifact to the §6 contract (dropping spread-only fields like
  `bind`, proxy addresses, telemetry internals). The review's §6
  "Included/Excluded" lists authorize this; recorded because the
  artifact's key set changed before Step 3 added the new fields.
- **D5** — the port-in-use message's "another 'atlas web'" became
  "another Atlas" (the quoted command was the same nonexistent one
  the fix removes).
- **D6** — with the repo's tag present, the trusted identifier is
  `git describe`'s tag-relative form (`v0.3.0-alpha1-58-g<hash>`),
  not a bare short hash — more informative, equally provable;
  templates and CLI render it verbatim.

## 30. Deferred findings

Console **Disconnect ownership/authorization** — any operator with
console access can end another operator's session; copy now names the
impact but the authz question is deliberately not closed here (filed
as its own security finding). The **sample console** stays, correctly
self-labelled. **Log file**, log rotation, build-id injection at
package time, the `atlas` CLI alias, `output_dir` relocation, an
installed-build date: all packaging, all untouched. The repo-wide
correlation-id sweep beyond the two identified sites: recorded, not
performed.

## 31. Packaging-boundary confirmation

PR-180 shipped the product-side seams only: the version constant, the
`BUILD_ID` resolution order with an honest fallback, stable
diagnostics identity, startup messages. Nothing was built, signed,
installed, delivered or entitled.

## 32. Explicit statement

**No Windows packaging, signing, licensing, entitlement, update
delivery or persistent log-file work was performed.**

## 33. Explicit statement

**No filesystem path, username, hostname, device/management address
or operator-authored network/site/profile name was added to any
portable diagnostic artifact.** (The artifact carries strictly less
identifying data than before this PR.)

## 34. Explicit statement

**The existing topology zoom tuning was not changed** — and it is now
pinned as unchanged (`wheelSensitivity: 0.15`, `minZoom 0.05`,
`maxZoom 3`).

## 35. Recommendation

**Ready to push** once the reviewer approves: every step is an
independently green commit, the full suite is at zero failures, and
both adversarial and browser validation passed. 

## 36. Exact next recommended action

Review and push these commits; then run the **PR-175 Beta Readiness
Gate re-audit** as its own PR-181-style task — the full re-audit was
explicitly out of PR-180's scope and is the gate to external beta.
