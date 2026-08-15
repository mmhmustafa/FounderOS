# PR-181 — Multi-Vendor Configuration Collection Integrity
## Implementation Handover

**Status: implemented, validated, committed locally. NOT PUSHED — awaiting review.**

---

### 1. Executive result

The External Beta Readiness engineering blocker is closed. Atlas can no longer store,
promote, diff, download, or reason over a device reply as running configuration unless it
has positively established that the reply IS a configuration. The exact §2 reproduction —
a Junos refusal becoming a `complete` artifact with zero warnings, written to disk and
reasoned over by Policy — now ends in an honest `unsupported` artifact with an empty
`running_config`, a refused disk write, and Junos's own commands on the wire.

All nine steps of the adversarially approved architecture (§26 of the review) were
implemented in order, each committed green. No intermediate commit stored more invalid
configuration than HEAD `86240a9`.

### 2. Starting HEAD

`86240a9` — *docs(atlas): PR-180 architecture review + implementation handover* — clean
tree (two untracked review documents, preserved and committed in Step 1).

### 3. Final local HEAD

`9eb792b` — *perf(atlas): PR-181 - cache the derived configuration-command set*

### 4. Commit list (nine logical stages, §26 order)

| Commit | Stage |
|---|---|
| `8be6ad7` | Step 1 — guard rails (T16/T19/required=False) + the two review documents |
| `ff71012` | Step 2 — artifact model with honest non-collected outcomes |
| `ddde70e` | Step 3 — positive classifier, `is_configuration()`, fingerprint anchor |
| `10b7905` | Step 4 — configuration declarations for FRR / classic IOS / AtlasLab switch |
| `f799ee3` | Step 5 — driver-owned collector + beta-blocker checkpoint |
| `cbb07f9` | Step 6 — storage honesty (sink, provenance, real commands) |
| `48813a3` | Step 7 — selection + Policy safety (filtered accessor, superseded provenance, download gate) |
| `a3d4df3` | Step 8 — pipeline floor (verdict-keyed) |
| `9eb792b` | Step 9 (perf) — cache the derived command set found hot during validation |

One consolidation: the two audit/architecture documents ride with the Step 1 commit
rather than a separate docs commit, because Step 1's tests implement those documents'
requirements and are unreadable without them.

### 5. Working-tree state

Clean at handover (`git status --porcelain` empty).

### 6. Files changed

33 files: +4,569 / −84. Source: `config/` (collector rewritten, models extended,
classify.py new, storage gate), `platforms/` (base accessor, production contract, seven
driver files), `enterprise_memory/` (sink, store, models, retrieval, fingerprint),
`reasoning/providers.py`, `web/` (routes, evidence_view, evidence_resolution_routes, one
template), `config_memory/extract.py`, `pipeline.py`, `founderos_runtime/cli/`
(commands, render). Tests: `test_configuration_integrity.py` (new, 937 lines),
`test_configuration_classify.py` (new, 268 lines), `test_config_collection.py` (pins
updated to the honest contract).

### 7. Exact original blocker reproduction — BEFORE (measured at `86240a9` this session)

```
artifact.status          = 'complete'
artifact.warnings        = ()
artifact.running_config  = '           ^\nunknown command.\n'
command outcomes         = all five Cisco commands 'collected'
running_config.txt       = the refusal, on disk
metadata.collection_status = 'complete', warnings []
_status_for(refusal)     -> 'collected'
```

### 8. Exact result — AFTER (measured at `9eb792b`)

```
Legacy path (no driver metadata):
   artifact.status         = 'unsupported'   collected = False
   artifact.running_config = ''
   artifact.detail         = 'R1 rejected every configuration command form'
   write_configuration_artifacts -> ValueError; no running_config.txt on disk

Driver path (registry-resolved Junos device):
   commands sent = ['set cli screen-length 0', 'set cli screen-width 0',
                    'show configuration | display set', 'show configuration']
   artifact.status = 'unsupported', running_config = ''
   -- never 'show running-config', never a stored refusal

Valid Junos configuration through the same path:
   command_used = 'show configuration | display set'
   status 'complete', first line 'set version 21.4R3.15'
```

### 9. Final positive-acceptance contract

`classify_configuration_reply(driver, reply)` in `src/founderos_atlas/config/classify.py`,
ordering load-bearing: (1) empty/whitespace → `EMPTY`; (2) `driver.is_configuration(reply)`
→ `COLLECTED`; (3) denial grammar per probe region → `DENIED`; (4) refusal grammar per
probe region → `UNSUPPORTED`; (5) otherwise → `UNRECOGNISED` (fail closed). Probe regions:
each of the first three and last three non-blank lines individually, the joined tail, and
the whole reply. **No line-count or byte-count acceptance heuristic exists.** "Not a
recognised error" is nowhere a path to `COLLECTED`.

### 10. `is_configuration()` contract

Added beside `rejects()`/`denied()` on `ProductionDriver` with a shared structural default
(fingerprint hostname/stanza counts, then extracted facts). The shared default's known
false positive — `show ip interface brief`'s header row counting as an interface stanza —
was closed by anchoring `_INTERFACE` to whole-line stanza openers in both
`enterprise_memory/fingerprint.py` and `config_memory/extract.py`, with regression pins.

### 11. Per-driver recognisers

| Driver | Recogniser |
|---|---|
| Junos | majority `set `/`deactivate `/`delete ` lines, or brace-structured hierarchy |
| PAN-OS | majority `set ` lines (set-format) or brace hierarchy |
| FortiOS | at least one `config <scope>` opener plus an `end` closer |
| Cisco WLC | majority of lines opening with WLC command verbs (`config `, `interface `, `wlan `, `802.11`, …) |
| everyone else | shared structural default |

Each is pinned against its platform's own configuration fixture AND its own refusal
fixture (T17), and all 11 platform refusal transcripts were run against all 15 drivers:
zero wrong-driver combinations classify `COLLECTED` — mis-resolution degrades fail-closed.

### 12. Driver-owned command selection

The collector resolves the driver from
`device.metadata["platform_driver"]["platform_id"]` via `registry.driver_for(...)` —
resolution happens in the CLI **before any transport is opened**, with one registry
hoisted per run. The command ladder is the driver's `configuration_commands()`
declaration; Junos's two-form fallback is exercised (both forms observed on the wire in
the checkpoint). The transport's text-marker raises are treated as one refused rung, not
the end of the ladder.

### 13. Legacy / no-declaration behaviour

Missing or unresolvable platform metadata is **never** proof a device lacks configuration
support: the collector falls back to the legacy `show running-config` and the positive
classifier judges the reply. By contrast, a **ProductionDriver that authors a command plan
and omits CONFIGURATION** (F5 BIG-IP, Citrix ADC, A10 ACOS) has declared its position:
unsupported-by-declaration, no command sent, no second SSH session opened, honest artifact
stating "declares no configuration collection command".

### 14. FRRouting / classic IOS / AtlasLab regression result

The 79% regression the first-draft architecture would have shipped does not exist here:
FRR, classic IOS and the AtlasLab switch declare `show running-config` via the
collector-facing accessor (discovery plans, costs and evidence shapes untouched). T19
pins FRR and classic IOS collection; **T16 re-collects every `running_config.txt` in the
live estate (live + history copies) through the new collector and classifier — zero
rejected** in both forms.

### 15. `session_setup` behaviour

The collector runs the resolved driver's declared `session_setup` before the
configuration ladder (Junos screen-length, PAN-OS pager-off + set-format, WLC paging
disable), tolerating per-command refusal exactly as discovery does, aborting honestly
(`failed`) if the session dies during setup. Every setup command passes the read-only
allowlist (verified across all drivers).

### 16. FortiOS / Aruba CX pager limitation

Both platforms declare no session command that can disable pagination and no permitted
form exists under the read-only transport (`config system console` would enter a
configuration scope). A pager-truncated reply can pass a structural test at 20% of the
true content, so **collection is not attempted** for these two platforms: the artifact
states the limitation ("output pagination cannot be disabled over Atlas's read-only
transport… no command was sent"), no transport is opened, and the containment is pinned
(T6). This is deliberate risk containment, recorded as a limitation of Atlas — not a
claim about the platforms. It lifts when netmiko device-type plumbing lands (out of
scope by mandate).

### 17. Artifact status model

`ConfigurationArtifact` carries the five honest non-collected outcomes — `unsupported`,
`denied`, `unrecognised`, `empty`, `failed` — reusing the existing command-outcome
vocabulary (`unrecognised` is the single approved addition; no fifth status system).
A non-collected artifact carries `command_used`, `detail`, `raw_reply` (forensic, never in
metadata) and **refuses to carry configuration content**; metadata reports sha `None` and
zero lines. `cli/render.py` prints reasons (`[unsupported] SW1 - …`), never a fake
artifact arrow; `_configuration_history` counts only `complete`/`partial` (T14); the web
job cannot announce a collection that will not happen because the decision now precedes
the transport.

### 18. Storage gate

Nothing becomes a configuration unless `COLLECTED`: `write_configuration_artifacts`
raises for non-collected artifacts (no `running_config.txt`), `ConfigMemoryStore.record`
and both Enterprise Memory writers are reached only on the collected branch, and the
sink writes a `ConfigurationSnapshot` only for a command the driver declares as its
configuration command **and** whose content the positive check confirms. Refused and
unconfirmable attempts persist as raw evidence with honest non-collected status — the
forensic record always survives.

### 19. `verified_by` provenance

`ConfigurationSnapshot` gains optional, backward-compatible `command` and `verified_by`
fields. New writes record both (`pr181:driver-recogniser driver=JunosDriver`,
`pr181:structural-default`, `pr181:collector-classifier …`). **No historical record is
reinterpreted as verified** — the absence of `verified_by` on pre-PR-181 rows is itself
the honest signal, and it surfaces in the Policy evidence payload.

### 20. Historical-data treatment

No migration. No deletion. No rewriting. No content-heuristic quarantine — the review
disproved its own proposed discriminator with a real three-line Junos configuration, so
nothing here guesses about stored content. Historical snapshots keep their historical
semantics and back-fill behaviour; prospective correctness comes entirely from the write
gates and the read path, which also protects CLI-only users who never run the web
migration ladder.

### 21. Filtered snapshot selector

`EnterpriseMemoryStore.collected_configuration_snapshots()` is the accessor every chooser
uses; `configuration_snapshots()` stays honest and unfiltered for forensics. Converted:
`MemoryEvidenceProvider._pick_snapshot`, `DeviceMemory.latest_configuration`,
`retrieval.session_devices`, the session Evidence page, the resolution-centre routes, and
the CLI session configuration counter. A grep-contract test (T27) pins the complete list
of files allowed to touch the raw accessor (`store.py`, `retrieval.py`).

### 22. Same-second ordering

`captured_at` now carries microsecond precision (`store._now`), and one shared key —
`snapshot_order_key` in `enterprise_memory/models.py` — orders every selector
(`captured_at`, then `discovery_session`, then `snapshot_id` as a deterministic — never
chronological — tie-break). T28 pins that `_pick_snapshot`, `latest_configuration` and the
collected timeline agree on forced same-instant ties. `snapshot_id` alone was rejected as
a recency signal: it is a content hash, and 668 of 1430 live rows share one.

### 23. Superseded-attempt Policy provenance

When Policy reasons over an older verified snapshot because a **newer** collection attempt
was refused / denied / unrecognised, the evidence summary states it — *"a newer collection
attempt at <t> was not collected (<status>) — this is the most recent VERIFIED
configuration"* — and the payload carries `superseded_attempt` with timestamp, command and
status. Verified end to end through the provider (live validation item 6). Confidently
wrong was not traded for silently stale.

### 24. Download / view bypass closure

`/evidence/device/<id>/config/<sha>/download` resolves the sha to an eligible snapshot
**for that device** or 404s. Verified live: verified snapshot → 200; refusal blob → 404;
cross-device sha → 404 (T26). `view_configuration`'s only caller is the provider, which
now sees only eligible snapshots; `download_configuration`'s only caller is the gated
route.

### 25. Policy-cache change

`enterprise-memory/snapshots.json` joined the Policy report cache key, so a snapshot
status/provenance change invalidates the cached verdicts.

### 26. Evidence three-state presentation

Device rows and the Evidence table render **Collected** / **Attempted, not collected** /
**Not collected**, the second derived from honest evidence rows for driver-declared
configuration commands. Verified live: a session of verified collections shows the badge;
a session of refusals shows "Attempted, not collected" (live validation item 7).

### 27. Pipeline floor

Configuration comparison admits only devices whose **current run** produced a verified
collection — keyed on the collection verdict (`complete`/`partial`), explicitly not on
parsed-fact counts (valid PAN-OS/FortiOS configurations parse to zero `ConfigFacts`).
`ConfigFacts.warnings` is populated as information only. The previous filter
(`status != "failed"`) would have admitted reason-strings as directory paths.

### 28. Before/after fabricated-change sweep

85 real baseline configurations from the live estate; every device answering its
configuration command with a refusal:

| | changes fabricated | high severity | health effect |
|---|---:|---:|---|
| BEFORE-equivalent (refusal diffed against baselines) | **2,153** | 20 | measured 100 → 87 in the review |
| AFTER (verdict floor) | **0** | 0 | none — zero devices enter comparison |

### 29. All-15-platform matrix result

| Platform | Command(s) | Pinned outcome |
|---|---|---|
| Cisco IOS-XE | `show running-config` | driver command + positive classifier |
| Cisco IOS (classic) | `show running-config` | driver command + positive classifier |
| Cisco NX-OS | `show running-config` | driver command + positive classifier |
| Arista EOS | `show running-config` | driver command + positive classifier |
| Juniper Junos | `show configuration \| display set` → `show configuration` | driver command + positive classifier |
| Fortinet FortiOS | `show` | **CONTAINED** — not attempted; pager limitation stated |
| Palo Alto PAN-OS | `show config running` | driver command + positive classifier |
| Aruba CX | `show running-config` | **CONTAINED** — not attempted; pager limitation stated |
| Cisco WLC | `show run-config commands` | driver command + positive classifier |
| F5 BIG-IP | *(none)* | unsupported by declaration; nothing sent |
| Citrix ADC | *(none)* | unsupported by declaration; nothing sent |
| A10 ACOS | *(none)* | unsupported by declaration; nothing sent |
| FRRouting | `show running-config` | driver command + positive classifier |
| AtlasLab firewall | `show running-config` | driver command + positive classifier |
| AtlasLab switch | `show running-config` | driver command + positive classifier |

No platform falls through to "anything non-empty = configuration". The declaration matrix
itself is pinned as an exact 15-row equality test.

### 30. T1–T28 result

All implemented, none weakened, all green in the final suite. T1/T16: byte-compatibility
proven against every real collected configuration on this machine, through both the
collector and the classifier. T4: the beta blocker, pinned end to end from a
registry-discovered Junos device. T20: refusal behind a six-line banner is `unsupported`
on **every** config-capable platform. T23: `show version`, `show ip interface brief`, an
SSH banner and a shell error block in the configuration slot are never `COLLECTED`. T27:
the grep contract. T28: same-instant ordering agreement.

### 31. Full-suite result

Final run at `9eb792b`:

```
3345 passed, 2 skipped, 1130 subtests passed, 0 failed
```

(Baseline at `86240a9`, re-confirmed this session before any change: 3285 passed,
2 skipped, 933 subtests, 0 failed. PR-181 adds 60 tests and 197 subtests.)

One prior full run had a single failure in
`test_production_security.py::test_failed_logins_are_audited_and_rate_limited`. It was
investigated, not dismissed: the fixed-window rate limiter keys on
`int(time.monotonic() // 60)`, and seven rapid attempts that straddle a window boundary
split 4+3 — neither side reaches the limit of 5, so no 429 is possible. The mechanism was
reproduced deterministically with injected timestamps; the test passes in isolation, with
its whole file, and in the final full run; neither the limiter, `security.py`, nor the
test changed in PR-181 (empty diff against `86240a9`). Pre-existing wall-clock flake,
noted as a residual.

### 32. Policy performance result

Measured on the live 15-profile / 85-device estate at the final commit, idle machine
(interim measurements taken while the full suite consumed the machine ran ~300 ms higher
cold; this is the clean, definitive run):

| Surface | PR-180 baseline | PR-181 final |
|---|---:|---:|
| Home (first in process) | 1,438 ms | **564.5 ms** |
| Policy cold (after Home) | 681.9 ms | **557.4 ms** |
| Policy warm | 113 ms | **26.1 ms** |

Every surface is at or better than baseline. Hot-path costs measured directly: driver
resolution 0.002 ms/device, classification of the largest live configuration
1.2 ms/device (~104 ms per 85-device *collection*, not per render),
`known_configuration_commands()` cached after its first 0.9 ms derivation (found hot
during validation — it had been consulted per device in Policy's superseded-attempt
check; the cache is the `9eb792b` commit). No PR-176-style amplification: one registry
per run, one derivation per process.

### 33. Adversarial validation

The complete adversarial matrix from the review runs green: leading whitespace,
mixed-case refusals, refusal behind a six-line banner (all platforms), refusal at the top
of a usage block, privilege denial bare and behind a banner, valid configurations quoting
refusal words in descriptions/banners/login messages, empty and whitespace-only replies,
`show version` / `show ip interface brief` / SSH banner / shell error block in the config
slot, the wrong-platform 11×15 cross-product (zero `COLLECTED`), unknown platform,
transport lost mid-command (`failed`, nothing stored), stale-valid + newer-failed
(provenance stated), same-second snapshots, and restart persistence of failure provenance.

### 34. Deviations from the architecture, and why

1. **Legacy configuration declarations live in a collector-facing accessor**
   (`configuration_commands()` on the drivers), not in the legacy discovery
   `collection_plan()`. Adding them to the discovery plan would have changed discovery
   cost, raw-output shape and session evidence counts for every FRR/IOS/AtlasLab-switch
   device — a behaviour change §26 Step 4 did not ask for. The accessor derives from the
   collection plan where one declares configuration (the AtlasLab firewall answers with
   no new code), so the driver remains the single source of truth.
2. **`platforms/base.py` gained the accessor default.** The out-of-scope list names
   `classify_output` specifically; `classify_output` is untouched (verified by diff). The
   base accessor was the minimal way to give all four legacy drivers one contract.
3. **Two files beyond the review's §21 list changed:**
   `web/evidence_resolution_routes.py` (one selector conversion the review's own §9a
   analysis required) and `web/templates/evidence_index.html` (the third state's
   rendering, which §20.6 mandated). Both are within the architecture's stated intent.
4. **The sink retains a legacy spelling set for driverless callers** — gated behind the
   positive structural check, so it can no longer promote anything unverified. Removing
   it entirely would have broken every legacy capture caller for zero safety gain; the
   architecture's requirement ("the driver report is the source of truth" on the driver
   path, "do not replace with another global vendor list") is honoured: the set is a
   fallback for callers without a driver, not an authority over one.

### 35. Known residuals

1. **FortiOS / Aruba CX configuration collection is contained** until device-type
   plumbing exists (§16). Stated in the artifact detail, pinned by test.
2. **Historical artifacts are frozen fabrication-free on this estate** (zero refusal
   files measured), but `history/<record>/` copies and archived
   `intelligence_report.json` trend baselines from any *other* pre-PR-181 workspace
   cannot be corrected — history is immutable by posture. A recovery run after a past
   fabrication will report one misleading "improving" churn trend.
3. **A pre-existing refusal file used as a *baseline*** (history side) would still diff
   against a newly verified collection — content-guessing on historical files is
   forbidden, so this is accepted and documented. Zero such files exist on this estate.
4. **The `/changes` `config_report["changes"]` key mismatch is untouched by mandate** —
   0 of 52 live report files carry the key; 34 real configuration changes remain
   invisible on `/changes`. Deliberately out of scope (fixing it here would expose the
   annotation/audit surfaces to the fabrication vector in the same change).
5. **The `routes.py:5076` `"ok"` vs `"collected"` counter bug is untouched by mandate.**
6. **`configuration_metadata.json` still has no readers**; `running_config.txt` files
   for devices whose collection later becomes unsupported simply stop being rewritten.
   The nine direct filesystem consumers see the last verified collection.
7. **The rate-limit test flake** (§31) — pre-existing, mechanism proven, worth a
   deterministic-clock fix in a hygiene PR.

### 36–40. Explicit statements

36. **No unverified device reply is promoted to collected configuration.**
37. **No historical configuration content was deleted, rewritten, quarantined, or
    guessed.**
38. **The transport refusal-marker architecture was not changed** —
    `src/founderos_atlas/transport/ssh.py` has an empty diff against `86240a9`, and the
    transport remains read-only (verified: every command sent, including all
    `session_setup` forms, passes `ensure_read_only`; no non-`show`/setup command was
    added anywhere).
39. **The `/changes` key mismatch was not changed.**
40. **No packaging, licensing, signing, entitlement or update-delivery work was
    performed.** BLOCKER-2 (licensing) remains an owner decision.

### 41. Recommendation

**PR-181 is ready to push.** The blocker is demonstrably closed at the checkpoint and at
the end state; the full suite is green at the final commit; the 85-device fabrication
sweep is zero; every advertised platform has an explicit pinned outcome; the out-of-scope
surfaces are untouched by diff; and the honesty invariant holds at every layer the
adversarial review attacked. The residuals in §35 are documented limitations, none of
which permits an unverified reply to become truth.

### 42. Exact next action

On approval: `git push origin main` (nine commits, `8be6ad7..9eb792b`). Then re-run the
External Beta Readiness gate's BLOCKER-1 verdict — the engineering blocker no longer
reproduces — and put BLOCKER-2 (the license decision) in front of the owner, which is now
the only thing standing between Atlas and the controlled external beta.

---

*Implemented and validated at final local HEAD `9eb792b`. Not pushed.*
