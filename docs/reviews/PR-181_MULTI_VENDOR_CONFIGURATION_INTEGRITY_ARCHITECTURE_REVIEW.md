# PR-181 — Multi-Vendor Configuration Collection Integrity
## Architecture / Adversarial Review Before Implementation

**Role:** Senior Network Automation Architect · Multi-Vendor Network Engineer ·
Evidence Integrity Reviewer · Product Reliability Engineer · adversarial correctness reviewer.

**Status:** ARCHITECTURE + IMPLEMENTATION PLAN. **No code was modified. Nothing was committed.
Nothing was pushed.**

**Baseline:** HEAD `86240a9`, branch `main`, clean working tree. Suite at baseline:
3285 passed · 2 skipped · 933 subtests · 0 failed.

---

## 1. Executive diagnosis

Atlas can store a device's command-refusal text as its running configuration, mark the collection
complete, and let Policy reason over that text as though it were real configuration. This was
reproduced end to end on Juniper Junos in the External Beta Readiness Re-Audit and is reproduced
again here.

**The root cause is not that the collector picks the wrong command. It is that Atlas has no test for
"is this a configuration?" anywhere in the product.** Every existing gate asks the opposite,
weaker question — "does this text look like a refusal I recognise?" — and answers it with a
hand-maintained list of Cisco phrasings. Anything that is not recognised as a refusal is treated as
a configuration by default.

Three facts, each measured at HEAD, define the shape of the repair:

1. **The knowledge already exists and is already reachable.** Eight drivers declare
   `CommandSpec(caps.CONFIGURATION, …)` with the correct per-platform command. Seven override
   `rejects()` with their own refusal grammar, and that grammar catches **11 of 11** platform
   refusal transcripts where the transport's marker list catches 5. The collector can re-resolve the
   exact driver from data it already receives — `device.metadata["platform_driver"]["platform_id"]`
   → `registry.driver_for(...)` — with **zero new plumbing**.
2. **Refusal-grammar matching cannot be the acceptance test.** It is position-anchored, so it fails
   in *both* directions: a >200-character login banner in front of a genuine refusal defeats every
   classifier in the repository, and a valid configuration whose first 120 characters contain
   "invalid input detected" is rejected as a refusal. Both were reproduced.
3. **The repository's own configuration corpus cannot prove safety.** No line in any valid
   configuration in this repo contains "invalid", "error", "denied" or "unknown command". A rule
   that passes on this corpus has been tested against nothing.

**The correct repair inverts the question.** Configuration is stored only when the resolved driver
can positively confirm the reply *is* a configuration. Refusal grammar is demoted from *decider* to
*explainer* — it says why a reply was rejected, never that a reply is acceptable.

This review proposes that architecture, attacks it with seven independent adversarial passes, and
then **amends it substantially**: the adversarial pass found 61 breaches, 19 of them fatal, and
killed three of the six layers in the first draft. §20 records every amendment. §26 is the final
approved plan.

**PR-181 is safe to implement as amended.** It is not safe to implement as first drafted.

---

## 2. Reproduction of the beta blocker

At HEAD `86240a9`, using the repository's own Junos transcript
(`tests/platform_fixtures/junos.py:89`) and the repository's own collection harness
(`tests/test_config_collection.py` `make_collection`):

```
artifact.status          = 'complete'
artifact.warnings        = ()
artifact.running_config  = '           ^\nunknown command.\n'
command outcomes         = [('show running-config', 'collected'),
                            ('show startup-config', 'collected'),
                            ('show inventory', 'collected'),
                            ('show license summary', 'collected'),
                            ('show module', 'collected')]
```

On disk:

```
running_config.txt          = '           ^\nunknown command.\n'
metadata.collection_status  = 'complete'
metadata.warnings           = []
```

In Enterprise Memory:

```
_status_for('           ^\nunknown command.\n') -> 'collected'
_status_for('% Unknown command')                -> 'unavailable'
_status_for('% Invalid input detected')         -> 'unavailable'
```

Reaching Policy — with an advancing clock, which is what a real run has, since discovery of an
estate completes seconds before configuration collection begins:

```
captured_at=2026-08-14T09:10:11+00:00  bytes=   30  first line: '^'
captured_at=2026-08-14T09:10:08+00:00  bytes=  515  first line: 'set version 21.4R3.15'

POLICY summary: running configuration (30 bytes, MX204)
POLICY text   : '           ^\nunknown command.'
  refusal wins? -> True
```

The Junos driver had already collected the real configuration during discovery via
`show configuration | display set`. The post-discovery collector's refusal snapshot is **newer**, so
`MemoryEvidenceProvider._pick_snapshot` selects it. Atlas hands its compliance engine thirty bytes
of error text labelled *"running configuration (30 bytes, MX204)"*.

And the run reports success: `_configuration_history` (`commands.py:1673-1691`) counts any
non-`failed` entry toward `configured_device_count` and reports `CONFIG_COLLECTED`.

---

## 3. Current configuration collection architecture

Atlas has **two** configuration paths, built 22 PRs apart for different consumers, never reconciled.

### Path 1 — the discovery evidence sink (PR-045)

A zero-cost side effect of discovery. `EvidenceSink.capture` (`enterprise_memory/sink.py`) scoops
the driver's own `raw_outputs` and writes Enterprise Memory evidence rows plus
`ConfigurationSnapshot`s. It is the **only** configuration feed for the Policy engine, CORTEX
reasoning and the Evidence Explorer.

### Path 2 — the post-discovery collector (PR-023 + PR-044)

Opens a **second** SSH session per device, sends a hardcoded `show running-config` plus four
hardcoded Cisco optional commands, and produces three things path 1 cannot:

- `configs/<host>/running_config.txt` on disk, read directly by **nine** consumers that know nothing
  about either store (dashboard, federation, incidents, path-intelligence ×2, prediction, pipeline,
  web routes, CLI);
- the versioned, deduplicated `ConfigMemoryStore` that `/configuration` and `/timeline` render;
- the per-run `config_change_report`.

Both then write to Enterprise Memory, so on a standard-tier device a single discovery session writes
the running config **twice** — and because path 2 normalises line endings while path 1 stores driver
bytes verbatim, the two blobs usually differ and the same-session dedup key does not collapse them.

`config/collector.py` has **one commit in its entire history** — `3f4ce86 PR-023` — and has never
been updated for the multi-platform driver work that followed.

### The four independent judges of "is this a refusal?"

| # | Location | Grammar | Catches (of 13 platform transcripts) |
|---|---|---|---|
| 1 | `transport/ssh.py:43` `_UNSUPPORTED_MARKERS` | 2 Cisco phrasings | 5 |
| 2 | `platforms/production.py:77-103` `rejects()`/`denied()` defaults | Cisco family | — |
| 3 | 7 per-driver `rejects()` overrides | per-platform | **11 of 11 tested** |
| 4 | `enterprise_memory/sink.py:108-115` `_status_for` | same 2 Cisco phrasings | 5 |

Plus `PlatformDriver.classify_output` (legacy), two AtlasLab overrides, `console/probe.py`, and
`web/failures.py` (exception-type based). **Nine judges. No shared contract.**

And `config/collector.py` has **no refusal grammar at all** — its only rejection is emptiness.

---

## 4. Why discovery gets this right and configuration collection does not

Discovery asks the driver. Configuration collection does not.

`ProductionDriver._collect` (`production.py:185-248`) runs each `CommandSpec`, applies the driver's
own `denied()` then `rejects()`, walks the ordered fallback ladder, and emits a typed
`CapabilityReport` with `status ∈ {supported, supported-with-limitations, unsupported,
not-attempted, failed}` plus `command_used` and `commands_attempted`.

That report is already stamped into canonical device metadata:

```
{'capability': 'configuration', 'command_used': 'show configuration | display set',
 'commands_attempted': ('show configuration | display set',), 'detail': '', 'status': 'supported'}
```

`config/collector.py` receives that same `DiscoveryResult` and **never reads `device.metadata` at
all**. It reads seven scalar fields and sends Cisco's command.

The CLI itself proves the metadata is in scope: four lines below the collector call it does
`driver_meta = (result.device.metadata or {}).get("platform_driver")` to stamp Enterprise Memory
(`commands.py:1916-1919`).

**The repair is not new architecture. It is connecting one component to knowledge the component
next to it already has.**

---

## 5. Supported-platform matrix (reconstructed from current code)

All 15 advertised platforms map to 15 distinct driver classes in `default_registry()`.
12 are `ProductionDriver` (all `maturity=EXPERIMENTAL`); 3 are legacy `PlatformDriver`.

| # | Platform (as advertised) | Driver | Kind | Configuration command | Tier | `rejects()` own? |
|---|---|---|---|---|---|---|
| 1 | Cisco IOS-XE | `CiscoIOSXEDriver` | Production | `show running-config` | standard | no (Cisco default) |
| 2 | Cisco IOS / IOS-XE | `CiscoIOSDriver` | **Legacy** | **none declared** | — | **no `rejects()`** |
| 3 | Cisco NX-OS | `CiscoNXOSDriver` | Production | `show running-config` | standard | no (Cisco default) |
| 4 | Arista EOS | `AristaEOSDriver` | Production | `show running-config` | standard | no (Cisco default) |
| 5 | Juniper Junos | `JunosDriver` | Production | `show configuration \| display set` → `show configuration` | standard | **yes** |
| 6 | Fortinet FortiOS | `FortiOSDriver` | Production | `show` | **deep** | **yes** |
| 7 | Palo Alto PAN-OS | `PanOsDriver` | Production | `show config running` | **deep** | **yes** |
| 8 | Aruba CX | `ArubaCXDriver` | Production | `show running-config` | **deep** | yes (Cisco grammar) |
| 9 | Cisco WLC | `CiscoWlcDriver` | Production | `show run-config commands` | **deep** | **yes** |
| 10 | F5 BIG-IP | `F5BigIpDriver` | Production | **none declared** | — | yes |
| 11 | Citrix ADC | `CitrixAdcDriver` | Production | **none declared** | — | yes |
| 12 | A10 ACOS | `A10AcosDriver` | Production | **none declared** | — | no (Cisco default) |
| 13 | FRRouting | `FRRoutingDriver` | **Legacy** | **none declared** | — | **no `rejects()`** |
| 14 | AtlasLab firewall | `AtlasLabFirewallDriver` | **Legacy** | `show running-config` (legacy `CapabilitySpec`) | — | **no `rejects()`** |
| 15 | AtlasLab switch | `AtlasLabSwitchDriver` | **Legacy** | **none declared** | — | **no `rejects()`** |

**Eight** `CommandSpec(caps.CONFIGURATION, …)` declarations, not nine — my own initial count was one
too high; the ninth is `AtlasLabFirewallDriver`'s legacy `CapabilitySpec` on a different code path.

### The tier fact that changes everything

The pipeline **never passes `tier=`** (`multihop.py:83-85`), so discovery runs at `TIER_STANDARD`
and `tier_includes('standard', 'deep') == False`. The four TIER_DEEP CONFIGURATION specs are
**never attempted** during discovery — they report `NOT_ATTEMPTED`. Proved at runtime: an Aruba CX
discovery at the default tier never sends `show running-config`.

### Refusal grammar coverage, measured

| Platform | Transport markers raise? | `driver.rejects()` | `sink._status_for` |
|---|:---:|:---:|---|
| Cisco IOS-XE | yes | **True** | unavailable |
| Cisco NX-OS | no | **True** | *collected* |
| Arista EOS | no | **True** | unavailable |
| Juniper Junos | no | **True** | *collected* |
| Fortinet FortiOS | no | **True** | *collected* |
| Palo Alto PAN-OS | no | **True** | *collected* |
| Aruba CX | yes | **True** | unavailable |
| Cisco WLC | no | **True** | *collected* |
| F5 BIG-IP | no | **True** | *collected* |
| Citrix ADC | no | **True** | *collected* |
| A10 ACOS | yes | **True** | unavailable |

`driver.rejects()` is **strictly more capable than every other judge in the repository** — 11/11
against 5/13. That is the case for making it the authority. §7 explains why it still cannot be the
*acceptance* test.

### What the live estate actually runs

| Platform | Configuration snapshots | Devices with a stored config |
|---|---:|---:|
| FRRouting | 968 (67.7%) | 86 (79%) |
| AtlasLab firewall | 462 (32.3%) | 23 (21%) |
| everything else | 0 | 0 |

**FRRouting declares no configuration capability, and it is two-thirds of the installed base.**
This single measurement destroyed the first draft of Layer 1 (§19.1).

---

## 6. Canonical source of platform command knowledge

**One source of truth: the resolved platform driver.**

The seam already exists end to end and was proved with zero new plumbing:

```
STEP 1  registry.detect(probe)                    -> JunosDriver, platform_id='junos'
STEP 2  driver.discover(...)                      -> device.metadata['platform_driver']
                                                     = {'platform_id': 'junos', 'driver': 'JunosDriver'}
STEP 3  registry.driver_for('junos')              -> JunosDriver   (same class: True)
STEP 4  driver.command_plan() -> CONFIGURATION    -> ('show configuration | display set',
                                                      'show configuration')
STEP 5  driver.rejects(refusal) -> True           driver.rejects(real config) -> False
```

`PlatformRegistry.driver_for(platform_id)` already exists for the operator-override path
(`registry.py:61-67`) and is already used this way at `routes.py:1921`. It returns `None` rather
than raising on an unknown id, so resolution degrades safely.

**Three literal command vocabularies retire in favour of the declaration:**

| Location | Entries | Missing |
|---|---:|---|
| `config/collector.py:34` `RUNNING_CONFIG_COMMAND` | 1 | everything non-Cisco |
| `enterprise_memory/sink.py:29-40` `_RUNNING_CONFIG_COMMANDS` | 5 | `show run-config commands`, `show`, `show config running` |
| `web/evidence_view.py:356-358` `_TRACEABLE_COMMANDS` | 3 (Cisco only) | both Junos forms |

**Performance:** `default_registry()` costs 0.037 ms per call (0.099 ms first, module import
dominated) and `driver_for()` costs 0.0013 ms. For an 85-device estate that is **3.14 ms total** —
no PR-176-style amplification. It returns a fresh object per call, so the implementation hoists one
`default_registry()` out of the per-device loop.

---

## 7. Command-result classification design

### 7.1 Why refusal grammar cannot be the acceptance test

Every existing classifier matches refusal phrasings inside a bounded character prefix. That is
correct for the short operational output it was designed for, and wrong for a multi-kilobyte
document. Measured, in both directions:

**Fails open.** A `>200`-character login banner in front of a genuine refusal is accepted as valid by
the transport markers, the ProductionDriver default, `JunosDriver.rejects()` and `sink._status_for`
— *all four*. The banner pushes the refusal past every position window.

**Fails closed.** A valid IOS configuration with `invalid input detected` in an early interface
description is rejected by the transport markers, `sink._status_for` and `base.classify_output`.
Move the same phrase past 3,000 characters and the ProductionDriver default accepts it. The verdict
depends on *where the phrase sits*, not on what the document is.

**And the corpus cannot tell us we are safe.** Across 83 real captured configurations in this
repository, zero contain "invalid", "error", "denied" or "unknown command". A clean score on this
corpus is not evidence; it is an absence of test.

### 7.2 The inversion

> **A reply becomes a configuration only when the resolved driver can positively confirm it is one.
> Refusal grammar explains a rejection; it never authorises an acceptance.**

This is what the PR mandate asks for ("ambiguity must fail closed") and what the current code gets
exactly backwards — today the final decision is an unconditional *accept*.

### 7.3 The classifier

```
classify_configuration_reply(driver, reply) -> verdict:

    if reply is empty or whitespace-only:
        return EMPTY

    # POSITIVE TEST FIRST. A document carrying configuration structure is a
    # configuration even if a description or banner inside it quotes refusal
    # grammar. A document without structure is not a configuration however long.
    if driver.is_configuration(reply):
        return COLLECTED

    # Refusal grammar now only EXPLAINS the rejection. Probed per line over the
    # first three and last three non-blank lines and over the whole reply, so a
    # login banner cannot push a refusal out of the window.
    if any(driver.denied(part) for part in probe_regions(reply)):
        return DENIED
    if any(driver.rejects(part) for part in probe_regions(reply)):
        return UNSUPPORTED

    return UNRECOGNISED        # fail closed, with the reason recorded
```

- **No magic number.** The first draft used `MIN_DOCUMENT_LINES = 5`; it was deleted (§20.2).
- `probe_regions(reply)` yields each of the first three and last three non-blank lines
  *individually*, plus the joined tail, plus the whole reply. Probing per line rather than joined
  closes the banner hole on every driver: measured **0 fail-open across all 63 banner cases**
  (9 drivers × banner lengths 0–6) versus 24 for the joined-tail form.
- Ordering is load-bearing. Positive-test-first measured **0/45 fail-open** on refusal transcripts
  *and* fewer fail-closed cases than refusal-first, because a refusal transcript has no structural
  evidence to find.

### 7.4 `is_configuration()` — a new driver contract point

Added next to `rejects()` and `denied()` on `ProductionDriver`, with a shared structural default and
per-driver overrides.

**Default (shared):** the reply carries configuration structure — `fingerprint(reply)` yields a
hostname or a non-zero structural count, or `extract_facts(reply)` yields any fact.

**This default is not sufficient alone**, and both gaps were measured:

| Reply | Shared default verdict | Problem |
|---|---|---|
| Real IOS-XE / Junos / PAN-OS / Aruba / WLC configuration | proven | correct |
| **Real FortiOS configuration** (`config … set … end`) | **not proven** | fails closed — `fingerprint`/`extract_facts` are Cisco/FRR-shaped |
| **`show ip interface brief` output** | **proven** | **fails OPEN** — `_INTERFACE = ^\s*interface\s+(\S+)` matches the table header row |
| Junos refusal | not proven | correct |
| PAN-OS refusal | not proven | correct |

Therefore, in the same change:

1. **Override `is_configuration()`** on FortiOS (`config …`/`end` block structure), PAN-OS, Junos
   (`set ` statements) and Cisco WLC. Every driver that owns a configuration command owns its
   recogniser.
2. **Fix `fingerprint._INTERFACE`** to require a stanza opener rather than matching a column header,
   or require two distinct kinds of structural evidence before the shared default returns true.

Without (1) the design's single-source-of-truth principle silently reverts to a shared Cisco-shaped
heuristic for exactly the platforms PR-181 exists to support. Without (2) the acceptance gate has a
known fail-open.

### 7.5 Verdict vocabulary

Atlas's existing vocabulary is reused. `EMPTY`, `DENIED`, `UNSUPPORTED`, `COLLECTED` already exist
as `config/models.py` `STATUS_*`. `UNRECOGNISED` is the one addition, and it is required: "the
device replied with something this driver cannot confirm is a configuration" is a distinct fact from
all four. It maps to the Enterprise Memory `unavailable` family for storage.

---

## 8. Fail-closed invariant

> **If Atlas cannot establish that returned text is a configuration, it does not store it as one.**

Concretely:

| Situation | Verdict | Stored as configuration? | Raw evidence kept? |
|---|---|:---:|:---:|
| Driver confirms the reply is a configuration | `COLLECTED` | yes | yes |
| Device refused (any grammar, any position) | `UNSUPPORTED` | **no** | yes |
| Device denied on privilege | `DENIED` | **no** | yes |
| Device answered with nothing | `EMPTY` | **no** | yes |
| Driver cannot confirm the reply is a configuration | `UNRECOGNISED` | **no** | yes |
| Transport broke mid-command | `FAILED` | **no** | no (nothing was received) |

The forensic record survives in every case: the raw evidence row is written with its honest status,
so an operator can always see *what the device actually said*. Only promotion to a
**configuration** is gated.

---

## 9. Snapshot-selection invariant

> **Known-invalid, failed, unsupported or unverified configuration evidence must never displace a
> valid configuration snapshot — and using an older valid snapshot must be visible, not silent.**

Today, no selector filters on anything. `ConfigurationSnapshot.collection_status` exists,
round-trips through `to_dict`/`from_dict`, back-fills, and is accepted by `store_configuration` —
and **both production call sites omit it**, so the `COLLECTION_OK` default always wins. Zero tests
pin it. It is fully plumbed, inert data: **no schema migration is required to start using it.**

Three problems must be solved together:

**(a) The enforcement point.** A filter inside `MemoryEvidenceProvider` alone is bypassed by the
Evidence page, evidence-resolution routes, the search index, the advisor and the CLI session
counter. But filtering inside `configuration_snapshots()` makes the store lie about its own
contents and destroys the forensic record §8 promises to keep.

**Resolution:** add `EnterpriseMemoryStore.collected_configuration_snapshots(*, device_id=None)` as
the *only* method selectors call. `configuration_snapshots()` stays honest and unfiltered. A test
greps `src/` to assert no selector calls the unfiltered method.

**(b) The predicate.** `collection_status == COLLECTION_OK` is unsafe on its own because
`models.py:348` back-fills absent/None/`''` to `'collected'` — so all 1430 historical rows read as
verified when none of them were. **Recommendation:** keep the back-fill (it preserves history) and
add a `verified_by` provenance field written only by the new path. Filtering is on status;
verification is on provenance; the UI states that pre-PR-181 snapshots carry no verification.

**(c) The tie-break.** `captured_at` is second-resolution and the two existing selectors disagree on
ties — `_pick_snapshot` takes the **first**-written, `latest_configuration` takes the **last**. The
first draft proposed `(captured_at, snapshot_id)`; that is wrong, because `snapshot_id` is
`"atlas-snapshot:" + sha256(content)` — arbitrary with respect to recency and **not unique**
(668 of 1430 live rows share one). **Resolution:** widen `captured_at` to microsecond precision at
`store.py:159` (`_now` currently uses `timespec="seconds"`) and use a single shared ordering helper.

**(d) The honesty requirement.** When Policy uses an older valid snapshot because a newer collection
failed, that must be stated. This needs plumbing, not copy:
`MemoryEvidenceProvider._config_evidence` looks up the newest evidence row for a configuration
command on that device and, when it is newer than the chosen snapshot, stamps the Evidence with a
superseded-attempt marker that reaches the Policy basis line. Without this, PR-181 replaces
"confidently wrong" with "silently stale" — which the PR mandate explicitly forbids.

---

## 10. Policy safety invariant

The full path, with the gate at every point invalid data could enter:

```
device
  → command            GATE 1: driver-declared CONFIGURATION command (§6)
  → transport          (unchanged in PR-181 — see §20.1)
  → collector          GATE 2: classify_configuration_reply (§7)
  → artifact           GATE 3: no artifact unless COLLECTED (§11)
  → disk               GATE 4: no running_config.txt unless COLLECTED
  → Enterprise Memory  GATE 5: no ConfigurationSnapshot unless COLLECTED; status always explicit
  → evidence provider  GATE 6: collected_configuration_snapshots() only (§9a)
  → snapshot selection GATE 7: shared ordering helper, microsecond captured_at (§9c)
  → Policy             GATE 8: superseded-attempt provenance (§9d)
```

**Two doors must be closed explicitly**, both found by the adversarial pass:

- `/evidence/device/<id>/config/<sha>/download` (`routes.py:2854-2871`) calls
  `download_configuration(sha)` straight into `blob_text` — it never resolves a snapshot, so it
  bypasses every filter. It must resolve the sha to a `COLLECTION_OK` snapshot for that device or
  404. Same for `retrieval.view_configuration`.
- The `/policy` report cache key (`routes.py:2919-2931`) does not include `snapshots.json`, so any
  status change is invisible to Policy's 4-entry LRU until something else invalidates it.

**One residual, stated plainly:** Policy's *change* inputs are file-backed, not snapshot-backed
(§11). Gates 5–8 protect the compliance verdict; they do not protect the change report.

---

## 11. Configuration-history implications

The first draft aimed this layer at the wrong store. The adversarial pass proved where fabricated
change events actually come from.

**Measured on the live estate:** interposing one refusal produced **2,517 fabricated changes across
85 devices** (28 high-severity), driving the Enterprise Intelligence health score from **100 to 87**
with factors `high-severity-configuration-changes -8` and `configuration-drift -6`.

That churn comes from `config_intelligence.compare_configurations` via
`pipeline._compare_configurations` — reading `configs/<host>/running_config.txt` from disk — **not**
from `config_memory.semantic_diff`.

Consequences that must be designed for:

- **Fabricated churn is archived.** `intelligence_report.json` lands inside `history/<record>/` and
  is read back as the trend baseline, so the first healthy run after a fabrication reports a
  fabricated *improvement* ("configuration changes fell from 2517 to 0"). History is immutable by
  posture, so PR-181 cannot correct it.
- **A refusal as the first stored version becomes the baseline** (`timeline.py:48-65`), and the
  device's real configuration then arrives as a change with 11 high-severity ADDED events.
- **`ConfigFacts.warnings` is a declared, never-populated field** — the ready-made channel for "this
  text parsed to nothing".
- **`/changes` is structurally blind.** `change/explorer.py:88` reads `config_report["changes"]`;
  `pipeline.py:144-152` writes only `reports[].changes`. Measured: **0 of 52 live report files**
  carry the key, so `unified_rows` produces zero configuration rows — while `routes.py:5192` asserts
  configuration *was* compared, from file existence alone.

**Design position.** The correct floor is *upstream of the differ*: if the current run did not
collect a verified configuration for a device, `pipeline._compare_configurations` must skip that
device rather than diff a refusal against a good baseline. Gate 4 (§10) makes this mostly automatic
— the artifact is not written — but the guard is stated explicitly because a *pre-existing* refusal
file on disk survives the fix.

**A floor keyed on "parsed facts are empty" is unsafe and is rejected**: a real PAN-OS configuration
and a real FortiOS configuration both parse to zero `ConfigFacts`. Such a floor would permanently
suppress *real* change events on exactly the platforms PR-181 enables.

**The `/changes` key mismatch is named as OUT OF SCOPE with its measurement** (§22), because fixing
it in this PR would expose `/changes`, its annotations, acknowledgements, assignments, suppressions
and audit trail to the fabrication surface in the same change.

---

## 12. Historical bad-snapshot analysis

**Can a historical fabricated snapshot be reliably identified from stored data alone? No — not
safely.**

The first draft proposed a discriminator: `fingerprint.hostname is null` **AND** all nine structural
counts are 0 **AND** `line_count ≤ 5`. It scored 0 false positives across 1430 live snapshots.

**That score is an artefact of the corpus, and I disproved the rule myself.** A minimal but entirely
legitimate Junos configuration —

```
set system host-name stub-01
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30
set system services ssh
```

— produces `hostname=None`, all structural counts zero, `line_count=3`, and is therefore
**quarantined as fabricated**. The discriminator is Cisco-shaped; the live estate contains only
FRRouting and AtlasLab devices, so it has never met a platform that would break it.

**Decision: PR-181 performs no content-guessing migration.**

- Historical snapshots are **not** rewritten, marked or deleted.
- Prospective correctness comes entirely from the read path (§9) and the write gates (§10), which
  work for CLI-only users who never run the web app's migration ladder.
- Snapshots recorded before PR-181 carry no `verified_by` provenance, and the UI says so.

Two corroborating signals are recorded for a *future* PR if quarantine is ever wanted, both
content-independent and platform-neutral: one `config_sha256` mapping to many `device_id`s inside a
profile (a refusal is device-independent; measured cross-device sharing in the live estate is
exactly 0), and byte size as a coarse pre-filter only.

**Live estate status: clean.** 1430 snapshots, 11433 evidence records, 6564 blobs, 746
config-memory blobs, 1947 `running_config.txt` files — **zero** fabricated snapshots. The migration
problem is theoretical for this estate. It is theoretical *because* this estate only ever ran
FRRouting and AtlasLab devices, whose configuration command the hardcoded `show running-config`
happens to satisfy.

---

## 13. Operator-facing outcome semantics

Five situations Atlas must distinguish, and what it may claim in each:

| # | Situation | Verdict | What the operator is told |
|---|---|---|---|
| A | Collection supported and succeeded | `COLLECTED` | "Configuration collected via `<command>`" — the command actually used |
| B | Platform discovered, configuration not collectible | `UNSUPPORTED` | "`<Platform>` refused `<command>`. Atlas did not record a configuration for this device." |
| C | Command supported, privilege insufficient | `DENIED` | "`<command>` was denied on `<host>`; the account lacks privilege." Distinct from B — the operator's action is different. |
| D | Device returned an unrecognised response | `UNRECOGNISED` | "The device replied with N bytes that Atlas could not confirm is a configuration." States the byte and line count and the command. |
| E | Connection dropped during collection | `FAILED` | "Collection failed on `<host>`: `<transport error>`." A fact about the attempt, not the platform. |

**Atlas must not claim specificity it cannot establish.** For a legacy driver with no `denied()`
channel, C is not distinguishable from B and must not be asserted — the honest verdict is B with the
detail naming what the device actually said.

**A blocking implementation constraint.** `ConfigurationArtifact.__post_init__`
(`config/models.py:75-78`) requires a non-empty `running_config` and restricts `status` to
`complete`/`partial`. There is **no artifact any of B/C/D/E can inhabit**, so the only exit from
`collect_configuration` today is a raise — which `commands.py:1942-1943` turns into
`(hostname, "failed", …)` and `render.py:188-189` prints as `[failed]`. **Without extending the
model, "the platform declares no configuration command" is presented identically to an
authentication failure.** §26 Step 2 addresses this first, because every operator-honesty promise in
this table depends on it.

**Four status vocabularies already exist** and PR-181 must not add a fifth:

| Vocabulary | Values | Location |
|---|---|---|
| Command outcome | collected, unsupported, denied, failed, empty | `config/models.py:12-16` |
| Artifact | complete, partial — *serialised as `collection_status`* | `config/models.py:18-19, :106` |
| Enterprise Memory | collected (`COLLECTION_OK`), empty, unavailable | `enterprise_memory/models.py:65` |
| History record | not_requested, collected, partial, failed | `history/models.py:13-21` |

Two distinct fields are both named `collection_status` with disjoint value sets. That is the same
defect class as the existing `routes.py:5076` bug where `status == "ok"` is compared against a
constant whose value is `"collected"`, tallying every successful record as failed.

---

## 14. Backward-compatibility analysis

| Concern | Position |
|---|---|
| Existing stored snapshots | Untouched. No migration, no marking, no deletion (§12). |
| `collection_status` back-fill | Preserved. Absent → `collected`, as today. Verification is carried by a new `verified_by` provenance field, not by changing history's status. |
| `configs/<host>/running_config.txt` | Existing files untouched. New files written only for `COLLECTED`. |
| `history/<record>/configs/` | Immutable by posture. Not rewritten. Explicitly stated as a residual (§23). |
| ConfigMemoryStore | No schema change. Guarded at its single production call site (`commands.py:1896`), which sits inside the `collect_configuration` try block — verified sufficient. `/configuration` remains unprotected for *pre-existing* versions; stated as a residual. |
| CLI-only users | Fully protected. The guarantee is the read path and the write gates, neither of which depends on the web app's migration ladder. |
| Cisco IOS/IOS-XE behaviour | Byte-compatible for every valid configuration. The command is unchanged; the classifier accepts every one of the 3,029 live `running_config.txt` files and all 7 fixture configurations. |

**The one behaviour change that must be called out, not discovered:** three shipped drivers'
configuration commands are absent from `sink.py`'s hardcoded vocabulary, so Cisco WLC, FortiOS and
PAN-OS have **never** produced a configuration snapshot. Making the sink driver-aware will *start*
producing snapshots for them, moving their Policy verdicts from `missing-evidence` to real
judgements. That is the correct outcome and it is a visible change in what Policy reports.

---

## 15. Performance implications

| Measurement | Result |
|---|---|
| `default_registry()` first call | 0.099 ms (15 driver module imports) |
| `default_registry()` per subsequent call | 0.037 ms |
| 85-device estate, naive per-device call | **3.14 ms total** |
| `driver_for()` per call | 0.0013 ms |

No amplification risk. The implementation still hoists one `default_registry()` call out of the
per-device loop, because the function returns a fresh object each time.

The classifier adds one `fingerprint()` pass plus at most seven short grammar probes per device.
`fingerprint()` is a fixed set of pre-compiled regexes over the config text and is already computed
on every `store_configuration` call today, so the marginal cost is one additional pass over text
Atlas is already reading.

**The Policy path gets strictly faster**, not slower: `collected_configuration_snapshots()` filters
rows before the timeline sort.

**Required after implementation:** re-measure Policy cold/warm on the live estate against the
PR-180 baseline of 681.9 ms / 113 ms, and confirm no regression in the full-suite wall time.

---

## 16. Security and trust implications

| Property | Effect |
|---|---|
| Read-only posture | **Unchanged and verified.** All 8 driver configuration commands and all declared `session_setup` commands pass `ensure_read_only`. No new command class is introduced. |
| Secret handling | Unchanged. Configuration content still never enters metadata; views stay masked, downloads stay explicit. |
| Bind address / outbound | Untouched. |
| Evidence integrity | **Improved.** A refusal can no longer be presented as a device's configuration, downloaded as one, or reasoned over as one. |
| New attack surface | None. No new input is parsed from an untrusted source that was not already being parsed. |
| Trust regression risk | **The stale-config path (§9d).** Replacing "confidently wrong" with "silently stale" would be a lateral move, not a fix. The superseded-attempt provenance is a correctness requirement, not a nicety. |

---

## 17. Test matrix

The mandated tests T1–T18, with the design decision each one pins.

| ID | Test | Pins |
|---|---|---|
| T1 | Cisco IOS-XE valid running configuration remains `COLLECTED`, byte-identical artifact | no regression on the majority platform |
| T2 | Cisco command refusal is `UNSUPPORTED`, never stored | refusal handling survives the classifier rewrite |
| T3 | Junos uses `show configuration \| display set` from the driver, not `show running-config` | driver-owned command selection |
| T4 | Junos refusal never becomes `running_config.txt` with `collected` status | the beta blocker itself |
| T5 | PAN-OS equivalent (`show config running`) | TIER_DEEP escalation + driver command |
| T6 | FortiOS equivalent (`show`) | the bare-word command and its `is_configuration()` override |
| T7 | F5 BIG-IP: no CONFIGURATION declaration → honest unsupported outcome, no command sent | undeclared-platform semantics |
| T8 | Citrix ADC equivalent | same |
| T9 | Cisco WLC equivalent (`show run-config commands`) | sink vocabulary gap closes |
| T10 | An unsupported *optional* command cannot poison the running config or flip the artifact to `complete` | the optional-command hole |
| T11 | A valid discovery-path configuration is not displaced by a later failed collection attempt | §9 selection invariant |
| T12 | Policy never receives failed/unsupported/unrecognised configuration text | §10 |
| T13 | Configuration history does not interpret refusal text as a change | §11 |
| T14 | Collection summary counts unsupported/failed/unrecognised as **not** collected | `_configuration_history` correction |
| T15 | Failure and unsupported provenance survives a restart | persistence of the verdict |
| T16 | Cisco existing behaviour remains byte-compatible where correct | the 3,029-file live corpus classifies `COLLECTED` |
| T17 | Every advertised platform fixture has an explicit expected configuration-collection outcome | no platform left unpinned |
| T18 | An unknown or unclassifiable response fails closed as `UNRECOGNISED` | §8 |

**Additional tests the adversarial pass made mandatory:**

| ID | Test |
|---|---|
| T19 | FRRouting, classic Cisco IOS and AtlasLab switch still collect configuration after the change (the 79% regression guard) |
| T20 | A refusal behind a 6-line login banner is `UNSUPPORTED` on **every** config-capable driver |
| T21 | A privilege denial behind a login banner is `DENIED` on Cisco IOS-XE, not `COLLECTED` |
| T22 | A refusal followed by a usage/help block is `UNSUPPORTED` (refusal at the top, not the tail) |
| T23 | `show version` and `show ip interface brief` landing in the configuration slot are **not** `COLLECTED` |
| T24 | A valid configuration with a trailing `banner motd` containing refusal grammar is `COLLECTED` |
| T25 | A real FortiOS configuration is `COLLECTED` (the `is_configuration()` override) |
| T26 | The configuration download route 404s for a non-OK snapshot |
| T27 | A grep test: no selector calls the unfiltered `configuration_snapshots()` |
| T28 | Two snapshots written in the same second order identically in every selector |

---

## 18. Adversarial cases

Every case in the PR mandate, plus those the attack surfaced, with the design's answer.

| Case | Verdict under the amended design | Basis |
|---|---|---|
| Refusal with leading whitespace | `UNSUPPORTED` | driver grammar strips and casefolds |
| Mixed-case error | `UNSUPPORTED` | grammars casefold |
| Error after a valid-looking first line | `UNSUPPORTED` | per-line probing over first-3 and last-3 |
| Valid config containing "error" / "invalid" | `COLLECTED` | positive test runs first |
| Empty output | `EMPTY` | explicit branch |
| Whitespace-only output | `EMPTY` | explicit branch |
| Truncated output (pager left on) | **see §19.2 — the sharpest residual** | |
| CLI banner followed by refusal | `UNSUPPORTED` | per-line probing (0/63 fail-open measured) |
| Privilege-denied response | `DENIED` | `denied()` probed per line |
| Privilege denial behind a banner | `DENIED` | per-line probing; joined-tail form failed this |
| Timeout after partial output | `FAILED` | transport exception, unchanged |
| Correct config command on the wrong platform | `UNRECOGNISED` or `UNSUPPORTED` | measured: all 81 wrong-driver combinations fail **closed**, none `COLLECTED` |
| Platform unknown / no `platform_driver` | legacy default command + classifier | §20.1 — *not* "send nothing" |
| Stale valid snapshot + new failed collection | old snapshot used, **superseded-attempt provenance shown** | §9d |
| Stale valid snapshot + new unsupported collection | same | §9d |
| Two snapshots in the same timestamp second | deterministic, identical across all selectors | microsecond `captured_at` |
| Restart after failed collection | verdict persisted in the evidence row | T15 |
| Refusal at the top followed by a usage block | `UNSUPPORTED` | per-line probing over first-3 |
| `show version` in the configuration slot | `UNRECOGNISED` | positive test, once `_INTERFACE` is anchored |
| Refusal spread over more than 3 lines | `UNSUPPORTED` | whole-reply probe retained |

---

## 19. Findings from adversarial review

Seven independent adversarial passes attacked the v1 design across six surfaces plus a completeness
critic. **61 breaches; 19 fatal.** The five that changed the architecture:

### 19.1 FATAL, fails closed — Layer 1 would have switched off collection for 79% of the installed base

The v1 rule "no CONFIGURATION declaration → send nothing" terminates configuration collection for
FRRouting, classic Cisco IOS and the AtlasLab switch. Measured on the live estate:

```
live configuration snapshots by platform: {'AtlasLab firewall': 462, 'FRRouting': 968}  total 1430
  frr             declares configuration? False
  cisco-ios       declares configuration? False
  atlaslab-switch declares configuration? False
```

**968 of 1430 snapshots (67.7%) and 86 of 109 devices (79%)** are FRRouting, which answers
`show running-config` perfectly well today via vtysh — `frr.py:72` even defines
`SHOW_RUNNING = "show running-config"` and reads it back at `frr.py:131` — and simply never declares
it. `CiscoIOSDriver.matches()` accepts any "Cisco IOS Software" banner, i.e. every non-XE Cisco
device in existence.

v1 put "adding CONFIGURATION specs to legacy drivers" **out of scope**, so it would have shipped the
regression.

### 19.2 FATAL, fails open — the collector never runs the driver's `session_setup`

`config/collector.py:67-69` does `with transport:` then `execute(...)`. There is no `session_setup`
loop, and the collector's transport is built with the default netmiko personality, so it sends
`terminal length 0` to everything. PAN-OS never receives `set cli pager off`; Junos never receives
`set cli screen-length 0`; the WLC never receives `config paging disable`.

With the pager on, the reply is the first screen only. Taking a real 60-line FRR configuration from
the live estate and truncating it the way a pager truncates: **the classifier returns `COLLECTED` at
20% of the true content** (274 of 1327 bytes), and the real `semantic_diff` then manufactures 12
change events including three `bgp-neighbor-removed(high)` and `bgp-as-changed(high)`.

**And "just run `session_setup`" does not fix it.** FortiOS and Aruba CX both declare
`session_setup = ()`, and no permitted pager-off command exists for them: `ensure_read_only` rejects
`config system console`, `no page` and `no pager`. FortiOS's own code comment says netmiko's
`fortinet` personality handles paging — a personality the transport never applies, because
`netmiko_device_type` is read by nothing in the repository and `fortinet` is not in
`SUPPORTED_DEVICE_TYPES`.

### 19.3 FATAL, fails open — the v1 classifier accepted anything it did not recognise as a refusal

Four independent proofs:

- **A multi-line login banner defeats the tail-3 test on 4 of 9 drivers.** Measured sweep: Arista
  EOS, FortiOS, Aruba CX and Cisco WLC all go `UNSUPPORTED → UNRECOGNISED → COLLECTED` as the banner
  grows from 0 to 6 lines — because the four prefix-anchored grammars stop matching once the refusal
  is not at offset 0 of the joined tail.
- **A privilege denial behind a banner becomes a stored running configuration on Cisco IOS-XE.**
  `% Authorization failed.` only matches the `startswith` branch; four banner lines push it off
  offset 0. `N=4 COLLECTED`.
- **On any reply of 5+ lines, whole-reply `rejects()` never ran** — so a refusal at the *top*
  followed by a usage block was invisible on all 9 drivers. 24 of 45 constructed refusal cases were
  `COLLECTED`.
- **`COLLECTED` was the unconditional default.** `show version` output, `show ip interface brief`
  output, an MOTD banner alone, a Linux shell error block and an SSH login banner alone were all
  certified as configurations.

### 19.4 FATAL, fails open — Layer 5 was aimed at the wrong store

The fabricating differ is `config_intelligence.compare_configurations` via
`pipeline._compare_configurations` (file-backed), **not** `config_memory.semantic_diff`. Estate
sweep: **2,517 fabricated changes across 85 devices**, 28 high-severity, health score 100 → 87.
The fabricated churn is then archived into an immutable `history/<record>/` and read back as the
trend baseline, so the next healthy run reports a fabricated *improvement*.

And the proposed floor — "suppress change events when parsed facts are empty" — would have
permanently suppressed **real** change events for PAN-OS and FortiOS, whose valid configurations
parse to zero `ConfigFacts`.

### 19.5 FATAL, fails closed — the Layer 6 discriminator quarantines real customer data

I disproved my own rule. A three-line, entirely legitimate Junos configuration satisfies all three
conditions (`hostname` null, all structural counts 0, `line_count ≤ 5`) and is
**flagged as fabricated**. The 0-false-positive score came from an estate containing only FRRouting
and AtlasLab devices.

### 19.6 Serious findings that shaped the plan without killing a layer

- `ConfigurationArtifact` has no state any new verdict can inhabit, so "unsupported by declaration"
  prints as `[failed]`, identical to an auth failure.
- The configuration **download route** bypasses every filter.
- The `collection_status == COLLECTION_OK` predicate inherits a back-fill that manufactures OK from
  three distinct unknowns.
- `snapshot_id` is a content hash — not a chronological tie-break, and not unique (668/1430 rows
  share one).
- Store-level filtering makes the store lie about its own contents and destroys the forensic record.
- Layer 0 deletes two permission phrasings (`command authorization failed`,
  `% this command is not authorized`) that **no driver grammar covers**.
- `credentials/connection_test.py` — absent from v1's file list — turns an unauthorized account into
  "Authenticated and the device returned its identity" once the transport stops raising.
- Legacy `PlatformDriver.classify_output` **inverts** denials: `% Permission denied` becomes
  `not-configured`, `Command authorization failed.` becomes `collected`.
- `configuration_metadata.json` sits beside every `running_config.txt` carrying exactly the status
  the nine filesystem consumers need — and has **zero readers** in `src/`.
- The collector opens a full second SSH session to every device *before* deciding whether to send
  anything, and the web job announces "Collecting configuration from `<host>`" for each.

### 19.7 Confirmed defences — attacks that failed

- The **writer list is complete**: `store_configuration` has exactly two production call sites and
  `ConfigurationSnapshot` is constructed in exactly two places. No back door.
- **Driver mis-resolution degrades fail-closed.** All 81 wrong-driver × refusal combinations produce
  `UNSUPPORTED` or `UNRECOGNISED` — never `COLLECTED`.
- **The read-only allowlist holds** for all 8 driver configuration commands and every declared
  `session_setup` command.
- **PRISM is not a bypass**; the search index is not a bypass of `configuration_snapshots()`; the
  store's memoisation cannot serve a stale unfiltered view around a filter.
- **The `ConfigMemoryStore.record()` guard is positionally sufficient** — one production caller,
  inside the `collect_configuration` try block.
- **The live corpus never trips the classifier**: all 3,029 `running_config.txt` files and all 7
  fixture configurations classify as `COLLECTED`. No fail-closed regression on existing data.
- **Every CONFIGURATION spec is `required=False`**, so the driver's required-capability escape
  cannot abort the collection loop. (If any implementer marks one `required=True`, one device's
  transport fault ends collection for the whole run.)

---

## 20. Amendments made after adversarial review

### 20.1 Layer 0 is REMOVED from PR-181

v1 proposed that the transport stop raising on device output text. The rationale was sound — a
transport raise converts `UNSUPPORTED` into `FAILED`, prevents the driver grammar from running, and
abandons the `CommandSpec` fallback ladder. But the attack established the true cost:

- The collector's `_collect_optional` is built **entirely** on those exceptions
  (`UnsupportedPlatformError → STATUS_UNSUPPORTED`, `PermissionDeniedError → STATUS_DENIED`).
  Removing them turns every optional-command refusal into `STATUS_COLLECTED`, flips the artifact
  from `partial` to `complete`, and writes refusal text to disk. **Atlas would store more garbage
  than it does today.**
- Two permission phrasings are covered by **no** driver grammar.
- `credentials/connection_test.py` silently reports an unauthorized account as authenticated.
- Legacy `classify_output` inverts denials.
- 8 existing tests break, 6 of which are the only behavioural pins on the statuses being removed.

**Measured benefit of keeping the raise:** only Junos declares a multi-command ladder, and the Junos
refusal does not match the Cisco markers — so the ladder Layer 0 protects is inert in practice. The
residual cost of *not* doing Layer 0 is one cosmetic mislabel (`FAILED` where `UNSUPPORTED` is
truer) on Cisco-marker refusals.

**Decision: defer to a separate PR.** PR-181 keeps the transport unchanged. This removes the single
largest fail-open risk in the plan and roughly halves its blast radius.

### 20.2 Layer 2 is rewritten — the question is inverted

`MIN_DOCUMENT_LINES = 5` is **deleted**. It had zero margin against the repository's own 5-line
Cisco WLC fixture, and it counted lines rather than content — a PAN-OS configuration returned as one
line would have been rejected regardless of size.

Replaced with: **positive structural test first, refusal grammar as explanation only**, probed per
line over the first three and last three non-blank lines plus the whole reply. Measured: 0 fail-open
across 63 banner cases and 36 trailing-artefact cases, versus 24 for the v1 form; 0 fail-closed
across 3,029 live configurations.

### 20.3 Layer 1's no-declaration rule is inverted

"No declaration → send nothing" becomes **"no declaration → send the legacy default
`show running-config` and let the classifier judge the reply."** Refusing to send is a fail-closed
decision made on *metadata quality*, not on *device behaviour* — and on the measured estate it
silences 79% of devices that work today.

**And CONFIGURATION declarations for FRRouting, classic Cisco IOS and the AtlasLab switch move
IN SCOPE**, landing in the same change as the gate.

### 20.4 Layer 5 is rescoped to the file-backed differ

The floor moves to `pipeline._compare_configurations` — skip a device when the current run did not
collect a verified configuration — and is keyed on the **collection verdict**, never on parsed
facts. `ConfigFacts.warnings` is populated for information only; it suppresses nothing.

### 20.5 Layer 6 drops the migration entirely

No content-guessing, no marking, no deletion (§12). Prospective correctness only, which is also the
only thing that protects CLI-only users.

### 20.6 Layer 4 amendments

- Enforcement moves to a **new typed accessor** `collected_configuration_snapshots()`, leaving
  `configuration_snapshots()` honest and unfiltered.
- The tie-break becomes **microsecond `captured_at`**, not `(captured_at, snapshot_id)`.
- The **download route** and `view_configuration` are closed explicitly.
- `snapshots.json` joins the `/policy` cache key.
- `evidence_view.device_rows` gains a **third** configuration state — Collected /
  Attempted-and-refused / Not collected — so a refusal does not render as "never asked".

### 20.7 Newly in scope because they are load-bearing

- Extending `config/models.py` so B/C/D/E in §13 have an artifact to inhabit (**Step 2** of the
  plan — nothing else works without it).
- `is_configuration()` overrides on FortiOS, PAN-OS, Junos and Cisco WLC.
- Anchoring `fingerprint._INTERFACE` so `show ip interface brief` stops reading as a configuration.
- Running `driver.session_setup` in the collector's session, **and** dropping FortiOS and Aruba CX
  from the TIER_DEEP escalation until netmiko plumbing lands, because for those two no permitted
  pager-off command exists.

---

## 21. Files expected to change

| File | Change |
|---|---|
| `src/founderos_atlas/config/collector.py` | Driver resolution; driver-owned command with fallbacks; classifier; run `session_setup`; optional commands only for Cisco-family drivers |
| `src/founderos_atlas/config/models.py` | An artifact state for `UNSUPPORTED`/`DENIED`/`UNRECOGNISED`/`EMPTY` without a `running_config`; `UNRECOGNISED` status constant |
| `src/founderos_atlas/config/classify.py` *(new)* | `classify_configuration_reply()` and `probe_regions()` |
| `src/founderos_atlas/platforms/production.py` | `is_configuration()` contract point with the shared structural default |
| `src/founderos_atlas/platforms/drivers/fortios.py`, `panos.py`, `junos.py`, `cisco_wlc.py` | `is_configuration()` overrides |
| `src/founderos_atlas/platforms/drivers/frr.py`, `ios.py`, `atlaslab_switch.py` | Declare the configuration capability (the 79% regression guard) |
| `src/founderos_atlas/enterprise_memory/fingerprint.py` | Anchor `_INTERFACE` to a stanza opener |
| `src/founderos_atlas/enterprise_memory/sink.py` | Accept driver capability reports; write a snapshot only when `COLLECTED`; pass `collection_status` explicitly; retire `_RUNNING_CONFIG_COMMANDS` |
| `src/founderos_atlas/enterprise_memory/store.py` | `collected_configuration_snapshots()`; microsecond `captured_at`; `verified_by` provenance |
| `src/founderos_atlas/enterprise_memory/retrieval.py` | Selectors use the filtered accessor; close `view_configuration` |
| `src/founderos_atlas/enterprise_memory/models.py` | `verified_by` field on `ConfigurationSnapshot` |
| `src/founderos_atlas/reasoning/providers.py` | Filtered accessor; superseded-attempt provenance; real `command_used` |
| `src/founderos_atlas/web/evidence_view.py` | Third configuration state; retire `_TRACEABLE_COMMANDS` |
| `src/founderos_atlas/web/routes.py` | Close the config download route; add `snapshots.json` to the `/policy` cache key |
| `src/founderos_atlas/pipeline.py` | Skip comparison when the run did not collect a verified configuration |
| `src/founderos_runtime/cli/commands.py` | Resolve the driver before opening the transport; record the real command on the evidence row; `_configuration_history` counts the new verdicts correctly |
| `src/founderos_runtime/cli/render.py` | Stop printing `[failed]` for a declared-unsupported outcome |
| `tests/` | T1–T28 |

## 22. Files that should NOT change

| File / area | Why |
|---|---|
| `src/founderos_atlas/transport/ssh.py` | Layer 0 deferred (§20.1). Touching it is the single largest fail-open risk in this plan. |
| `SUPPORTED_DEVICE_TYPES` / `netmiko_device_type` plumbing | 7 of 11 driver values are not in the allowlist; widening it is a separate, larger change |
| `src/founderos_atlas/credentials/connection_test.py` | Only at risk from Layer 0, which is deferred |
| `src/founderos_atlas/platforms/base.py` `classify_output` | Legacy denial inversion is real but belongs with Layer 0 |
| `src/founderos_atlas/config_memory/` (schema) | No status field is added; the single call site is guarded instead |
| `src/founderos_atlas/change/explorer.py` | The `config_report["changes"]` key mismatch (0 of 52 live files carry the key; 34 real changes invisible) is **deliberately left alone** — fixing it would expose `/changes`, its annotations, acknowledgements, assignments, suppressions and audit trail to the fabrication surface in the same PR |
| `src/founderos_atlas/web/routes.py:5076` | The `"ok"` vs `"collected"` counter bug is pre-existing and separate |
| `history/<record>/` artifacts | Immutable by posture |
| Driver `tier` assignments | Not re-litigated here |
| Packaging, licensing, entitlement, update delivery, UI redesign, Policy keyboard cleanup, demo dataset, search redesign | Out of scope by mandate. **BLOCKER-2 (licensing) is an owner decision and remains separate.** |

---

## 23. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **Pager truncation certified as `COLLECTED`** (§19.2). Running `session_setup` fixes Junos, PAN-OS and WLC but **not** FortiOS or Aruba CX, for which no permitted pager-off command exists. | **High** | Drop FortiOS and Aruba CX from the TIER_DEEP escalation until netmiko plumbing lands. State the limitation. Do not ship "the collector runs `session_setup`" as a complete pager fix. |
| R2 | `is_configuration()` overrides are per-platform judgement calls that could false-positive on a platform's own error output. | Medium | Each override is pinned by T17 against that platform's own configuration *and* refusal fixture. |
| R3 | The 79% regression guard (§20.3) depends on new declarations for three legacy drivers being correct. | Medium | T19 asserts FRRouting, classic IOS and AtlasLab switch still collect. Run against the live estate before merge. |
| R4 | Silently-stale replaces confidently-wrong if §9d is dropped under time pressure. | **High** | §9d is a correctness requirement, not polish. It is Step 6 and is not deferrable. |
| R5 | Pre-existing `configs/<host>/running_config.txt` refusal files survive the fix and keep feeding nine filesystem consumers. | Medium | Live estate has zero. `configuration_metadata.json` already exists beside every file and has zero readers — wire it up, or state the gap explicitly. |
| R6 | Making the sink driver-aware starts producing snapshots for WLC / FortiOS / PAN-OS, changing their Policy verdicts from `missing-evidence` to real judgements. | Low | Correct outcome; call it out in the PR description so it is not read as a regression. |
| R7 | An implementer marks a CONFIGURATION spec `required=True`, so one transport fault ends collection for the whole run. | Low | Add an assertion test that every CONFIGURATION `CommandSpec` is `required=False`. |
| R8 | A fifth status vocabulary is introduced by accident. | Medium | §13 enumerates the four that exist. Review gate: no new status constants outside `config/models.py`. |

---

## 24. Rollback strategy

PR-181 is **additive at the data layer and reversible at the code layer**.

- **No stored data is rewritten, marked or deleted.** Rolling back the code leaves every existing
  workspace exactly as it was; there is no reverse migration to run.
- The one schema addition (`verified_by` on `ConfigurationSnapshot`) is an optional field that
  `from_dict` tolerates as absent, so a rolled-back build reads new snapshots without error.
- Microsecond `captured_at` is a widening — old second-resolution values remain valid ISO
  timestamps and sort correctly against new ones.
- **Per-step rollback:** the plan in §26 is ordered so every step is independently revertible, and
  no intermediate step leaves Atlas storing more garbage than HEAD. That property is checked
  explicitly at Steps 3 and 5.
- **Fast partial rollback:** if `is_configuration()` proves too strict in the field, reverting the
  single override for that platform restores the shared default without touching the classifier.

---

## 25. Definition of done

1. A refusal, denial, banner, truncation, wrong-command reply or unrecognised text **cannot** become
   a `ConfigurationArtifact`, a `running_config.txt`, a `ConfigMemoryStore` version, or a
   `ConfigurationSnapshot`.
2. Every configuration command sent is the one the resolved driver declares, and the command
   actually used travels with the stored evidence and snapshot.
3. Policy receives only snapshots explicitly recorded as collected, and states when it is reasoning
   over a snapshot older than the most recent attempt.
4. The five operator-facing outcomes in §13 are distinguishable in the UI and the CLI, and
   "unsupported by declaration" no longer prints as `[failed]`.
5. FRRouting, classic Cisco IOS and AtlasLab devices still collect configuration — verified against
   the live estate, not only against fixtures.
6. T1–T28 pass. Full suite green at or above the 3285/2/933/0 baseline.
7. Policy cold/warm on the live estate is at or better than 681.9 ms / 113 ms.
8. All 3,029 live `running_config.txt` files and all 7 fixture configurations classify as
   `COLLECTED` — zero fail-closed regression on existing data.
9. The PR description states the WLC/FortiOS/PAN-OS Policy verdict change (R6) and the FortiOS /
   Aruba CX pager limitation (R1) as known, deliberate outcomes.

---

## 26. FINAL APPROVED IMPLEMENTATION PLAN

Nine steps, each independently revertible, ordered so that **no intermediate commit stores more
garbage than HEAD**.

### Step 1 — Guard rails first (no behaviour change)
Add the tests that pin what must not regress: T16 (3,029 live configurations classify `COLLECTED`),
T19 (FRR / classic IOS / AtlasLab switch still collect), and the assertion that every CONFIGURATION
`CommandSpec` is `required=False`. Commit green.

### Step 2 — Extend `config/models.py`
Give B/C/D/E in §13 an artifact state that carries a verdict without a `running_config`. Relax
`__post_init__` for that state only. Wire `cli/render.py`, `_configuration_history` and the web job
stage so a declared-unsupported outcome stops printing `[failed]`.
**Nothing else in this plan works without this step.**

### Step 3 — The classifier, in isolation
Add `config/classify.py` with `classify_configuration_reply()` and `probe_regions()`. Add
`is_configuration()` to the `ProductionDriver` contract with the shared structural default. Anchor
`fingerprint._INTERFACE`. Add the four driver overrides. Land T18, T20–T25.
**Not yet wired into the collector** — this step is pure addition, so it cannot regress anything.

### Step 4 — Declare the missing configuration capabilities
FRRouting, classic Cisco IOS, AtlasLab switch. T19 must still pass and now means something.

### Step 5 — Wire the collector
Resolve the driver **before** opening the transport. Use the declared command with its fallbacks.
Run `driver.session_setup`. Apply the classifier to the required command **and to every optional
command**. Drop FortiOS and Aruba CX from the TIER_DEEP escalation (R1). Land T1–T10, T14, T17.
**Checkpoint: re-run the beta-blocker reproduction from §2 and confirm it no longer reproduces.**

### Step 6 — Storage honesty
Sink accepts driver capability reports; snapshot written only when `COLLECTED`; `collection_status`
always explicit; `verified_by` recorded; the real `command_used` on the evidence row; retire
`_RUNNING_CONFIG_COMMANDS` and `_TRACEABLE_COMMANDS`. Land T13, T15.

### Step 7 — Selection and Policy safety
`collected_configuration_snapshots()`; convert every selector; microsecond `captured_at`;
superseded-attempt provenance (§9d); close the download route and `view_configuration`; add
`snapshots.json` to the `/policy` cache key; third configuration state in `device_rows`. Land T11,
T12, T26–T28.

### Step 8 — Pipeline floor
`pipeline._compare_configurations` skips a device when the run did not collect a verified
configuration. Populate `ConfigFacts.warnings` for information only. Verify the 85-device sweep now
reports zero fabricated changes.

### Step 9 — Full validation and handover
Full suite. Policy cold/warm on the live estate against the PR-180 baseline. Browser check of
Evidence, Configuration and Policy in all three configuration states. Handover document recording
R1 and R6 as known, deliberate outcomes.

---

## Report back

**Root cause verified.** `config/collector.py:34,69` sends one hardcoded Cisco command with no
platform branch, and `:75` rejects only *empty* output — never *invalid* output. But the deeper
cause is that **Atlas has no positive test for "is this a configuration?" anywhere**; every gate
asks the weaker question "does this look like a refusal I recognise?", answered by four inconsistent
Cisco-shaped string lists, and accepts anything unrecognised.

**Can the existing driver architecture be reused? Yes — almost entirely.** The drivers already own
the correct per-platform command (8 declarations), the correct refusal grammar (11/11 vs the
transport's 5/13), and a typed per-capability verdict that is already stamped into device metadata.
`registry.driver_for(platform_id)` re-resolves the driver from data the collector already receives.
**Zero new plumbing.** What the drivers do *not* yet own is a positive configuration recogniser —
that is the one genuinely new contract point, and it belongs on the driver beside `rejects()`.

**The smallest correct repair** is Steps 2–7: extend the artifact model, add the inverted classifier
with a driver-owned positive test, declare the three missing capabilities, wire the collector, gate
storage, and filter selection. Steps 1, 8 and 9 are guard rails and validation.

**Surprises that changed the design:**
1. **FRRouting is 67.7% of the live estate and declares no configuration capability** — the first
   draft would have switched off collection for 79% of devices that work today.
2. **The collector never runs `session_setup`**, so a pager-truncated reply at 20% of true content
   classifies as a good configuration — and for FortiOS and Aruba CX **no permitted pager-off
   command exists at all**.
3. **Removing the transport's text-based raises makes things worse before it makes them better**,
   because the collector's optional-command path is built entirely on those exceptions. Layer 0 is
   deferred.
4. **The fabricating differ is file-backed**, not memory-backed: one refusal produced 2,517
   fabricated changes and moved the health score from 100 to 87.
5. **My own historical-quarantine discriminator flags a real three-line Junos configuration as
   fabricated.** The migration is dropped.

**Is PR-181 safe to implement? Yes — as amended in §20 and sequenced in §26.** It was not safe as
first drafted: 19 fatal breaches, three layers unsalvageable. As amended it is additive at the data
layer, reversible at the code layer, has no intermediate state worse than HEAD, and closes the beta
blocker at Step 5 with Steps 6–8 as defence in depth.

---

*Architecture review performed at HEAD `86240a9` on a clean working tree. No code was modified.
Nothing was committed. Nothing was pushed.*
