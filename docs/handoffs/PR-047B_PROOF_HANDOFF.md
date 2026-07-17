# PR-047B — Operator Evidence Explorer (PROOF)

**Status:** implemented, tested, validated on the live lab. **Not committed.**
**Regression:** 1453 passed, 1 skipped, 105 subtests (was 1412 — +41 new, none broken).

---

## What was wrong

The Evidence page was a storage dashboard. Its six headline tiles were unique
blobs, deduplicated observations, stored bytes, and three record counts — every
number true, and not one of them a question a network engineer asks.

The deeper problem was not the tiles. It was that **every link into Evidence
landed on the front door**: `policy.html` and `timeline.html` each had a link
that said "Evidence" and pointed at `/memory`. So when Atlas told an operator a
device failed a policy and they asked *why*, Atlas handed them a page of
counters and let them go hunting. The drill-down beneath it was well built and
complete — and nothing outside it pointed in.

Evidence is not a destination. It is the answer to a question asked somewhere
else. This PR rebuilds it as that.

---

## 1. Before / after

**Before** — the page led with storage:

```
DISCOVERY SESSIONS 1 | DEVICES REMEMBERED 9 | EVIDENCE RECORDS 63
CONFIGURATION SNAPSHOTS 9 | UNIQUE BLOBS STORED 51 | DEDUPLICATED 12 (information)
```

**After** — the page leads with collection (live lab, real numbers):

```
Evidence Collection — Fresh lab
  Devices reached            29
  Devices authenticated      29 / 29
  Configurations collected   29 / 29
  Commands attempted        203
  Collected successfully    174
  Empty responses            29
  Unsupported commands        0
  Failed collections          0
  Collection completeness   100%

  An empty response is not a failure — the command ran and the device had
  nothing to report. Completeness counts it as collected.
```

Storage internals are **not deleted**: they are in `Enterprise Memory — System
Details`, collapsed, at the foot of the page, where an administrator can still
read them.

> **Screenshots could not be captured.** The browser pane's screenshot action
> timed out repeatedly (no console errors; the page renders and responds — DOM
> reads, text extraction and JS all executed fine against it). Every "after"
> figure in this document is real output read from the running lab, not a
> mock-up. Pixel captures are outstanding.

---

## 2. Operational summary (Part 2)

Derived in `web/evidence_view.py::collection_summary` from records Enterprise
Memory already keeps. The session row supplies what only the run knows (devices
reached, authenticated); the records supply everything about what came back.

**Completeness** = `(attempted − failed − unsupported) / attempted`. An **empty**
response counts as complete: Atlas asked, the device answered, the answer was
"nothing". Counting it against completeness would mean the lab — where LLDP is
simply not running — could never reach 100%, and the page would nag forever
about a network with nothing wrong with it. Zero attempts returns **Unknown**,
never 0% or 100%; a percentage of no attempts is not a measurement.

---

## 3. Evidence Explorer (Part 3)

`Discovery Session → Canonical Device → Command → Raw output / Normalized facts
/ Used by Atlas`.

Devices are grouped by `device_id`, the canonical identity memory already
assigns, so a device reached at two addresses appears once. Verified live: **29
device rows, 29 unique, zero duplicates.**

### Collection statuses — what is real, and what is not

The spec lists six statuses. **Three exist in practice.** `sink.py:100-106`
classifies every output as `collected`, `empty`, or `unavailable`, and nothing
in discovery ever sets `error`. "Timed out" and "skipped" have no stored
representation at all — a command that never returns is never recorded, so
there is nothing to render.

| Spec status | Stored as | Shown as | Real? |
|---|---|---|---|
| Collected | `collected` | Collected | yes — 174 in the lab |
| Empty | `empty` | Empty | yes — 29 in the lab |
| Unsupported | `unavailable` | Unsupported | yes — reachable, 0 in this lab |
| Failed | `error` | Failed | **renders, but discovery never produces it** |
| Timed Out | — | — | **no representation; not implemented** |
| Skipped | — | — | **no representation; not implemented** |

"Failed collections: 0" on the live lab is therefore true but weak: it is 0
because transport-level failures never reach memory at all, not because nothing
can fail. See *Limitations*.

---

## 4. Raw evidence (Part 4)

Masked by default via memory's existing `view_*` path; **Copy Output** copies
what is on screen (the masked text — the raw bytes are a download, never a
clipboard accident); **Download Output — raw** serves the exact bytes to the
local operator and is audited. The command names the page, not the content
hash — the hash is under System Details.

Large output: rendering is capped at 2000 lines with an explicit
"showing the first N of M lines" notice and the whole thing one click away. The
cap is on rendering only, never on what Atlas stored. (Largest output in the
lab today is 140 lines, so the cap does not trigger; it exists for a
40,000-line configuration.)

---

## 5. Normalized facts (Part 5)

No parsers were added. The page shows only what Atlas already stored: the
collector's provenance, plus the snapshot engine's existing fingerprint.

The fingerprint holds **counts, not inventories** — it is deliberately "a cheap
structural shape … no parsing" (`fingerprint.py:50`). So the labels say "BGP
neighbours: 3", not "BGP peers", because naming a count after the list it is not
would promise a drill-down that does not exist. A count of zero is shown ("Access
lists: 0" is a fact); a missing key is silence. Where nothing exists: *"No
normalized facts were produced from this evidence."*

The spec's list mentioned Router IDs, interface addresses, OSPF neighbours and
routes as facts. **Those are not stored** — the fingerprint has no `router_id`
or `interface_addresses` field. They are not shown.

---

## 6. Used by Atlas (Part 6) — the point of the PR

For the **running configuration**, this is exact and traced end to end:

- the sink stores that output twice from the same text — once as evidence, once
  as a configuration snapshot — so the two **share a content address**
  (verified on the lab: evidence `811be4512c1e9e39` == snapshot
  `811be4512c1e9e39`);
- the policy provider cites that snapshot's sha in the `Evidence` it hands
  CORTEX (`providers.py:107-137`);
- `ReasoningResult.evidence_used` keeps the whole `Evidence` object.

That unbroken chain of content addresses — not a name match, not a device match
— is what lets the page say which findings rest on which bytes. Live, on core1:

```
Used By Atlas
  Policy: Hostname Configured — Passed        Policy: NTP Configured — Failed
  Policy: BGP Router ID Present — Passed      Policy: AAA Present — Failed
  Policy: OSPF Router ID Present — Passed     Policy: SNMP Configured — Failed
  Policy: Logging Configured — Passed         Policy: Domain Name Configured — Failed
  Policy: Loopback Interface Present — Passed Policy: Password Encryption Enabled — Failed
  Policy: Unused Interfaces Shut Down — Passed
  Configuration: Configuration history — this output IS this device's snapshot
```

For **every other command** (`show version`, LLDP, routes) nothing links a
topology relationship back to a record, so the page says so:

> "Atlas has stored this evidence, but result-level usage tracking is not
> available yet for this kind of evidence."

`tracked=False` ("we don't record that") is kept distinct from an empty finding
list ("nothing uses this"). Blurring them would make the audit trail itself
untrustworthy — a wrong citation is worse than none.

Policies are evaluated only for traceable evidence and only for that one
device, so page cost does not grow with the network (record page: **0.147s**,
including 12 policy evaluations).

---

## 7. Filtering (Part 7)

Server-side, by session / device / platform / command / status / source, plus a
text search across device, IP, command, platform and version. No new search
engine. Filter options are derived from the selected session's own records, so a
filter can never offer a value that returns nothing.

**The filter narrows the table; it never touches the summary.** A filtered view
that re-scored completeness would let an operator narrow to one device and read
its number as the network's.

---

## 8. Bundles (Part 8) — both paths implemented

```
evidence-session-2026-07-15_14-58-05.zip   (204 entries, 110 KB, 29 devices)
  session-summary.json
  core1/
    show-running-config.txt   show-version.txt   show-ip-route.txt  …
    evidence-metadata.json
  edge1/ …
```

- **Masked by default.** A bundle is the easiest artefact in Atlas to forward to
  someone, so the default is the safe one, and the manifest records it.
- **Raw is explicit**, labelled `-raw.zip`, declared inside the manifest
  (`"masked": false`, `"disclosure": "RAW EXPORT — outputs are unmasked…"`), and
  audited.
- **Filenames are allowlisted, not escaped**: `../../etc/passwd` → `etc-passwd`.
  Two devices sharing a hostname get distinct directories.
- **Deterministic**: fixed member timestamps, so unchanged evidence bundles to
  identical bytes.
- An **empty** command has no file but keeps its metadata record — omitting it
  would let a reader conclude Atlas never ran it.

---

## 9. Device actions (Part 9)

Reused, not reimplemented: the page imports the `device_actions` macro and calls
`device_target()` / `web_access()`. No action logic exists in the Evidence page.
Verified live on core1: SSH → `/console/frr:core1`, Configuration →
`/configuration/frr:core1`, Investigate → `/paths?device=core1`, and a greyed
"Web unavailable" carrying its reason.

---

## 10. Empty and failure states (Part 10)

- No sessions → *"No evidence has been collected yet. Run Discovery to begin."*
- No evidence for a device → *"Atlas discovered this device but did not collect
  command evidence."*
- Empty response → *"The command executed successfully but returned no output."*
  and the row offers "no output" rather than a dead View link.
- Failed → the reason, plus Retry Discovery / Open SSH / View Device.
- One session only → *"there is nothing to compare against yet"*, linking to
  Discovery and Changes. This is the most useful thing the page can say when
  it is new, and it explains why Changes is empty.

No stack traces. `?page=banana` is treated as a typo, not a 500.

---

## 11. Performance (Part 11)

Listings are built from the records index alone — **no blob is read to render a
table**. Proven by sabotage rather than assertion: a test replaces
`view_evidence` with a recorder and fails if any listing calls it, then confirms
opening one record calls it exactly once.

Live timings (29 devices, 203 records):

| Page | Time |
|---|---|
| `/evidence` | 0.073s |
| `/evidence?session=…` | 0.111s |
| `/evidence/device/frr:core1` | 0.075s |
| record page (1 blob + 12 policies) | 0.147s |

Command records paginate at 50/page. Output is loaded only when an operator
opens an item.

---

## 12. System details (Part 12)

`Enterprise Memory — System Details`, collapsed, holding sessions, devices,
records, snapshots, unique blobs, duplicates suppressed and stored bytes.

**This conflicted with an accepted PR-047A decision** and its test
(`test_the_ui_does_not_name_internal_layers_at_the_operator`: the page is
Evidence; the layer behind it is Enterprise Memory; the operator is never sent
looking for the latter). Part 12 explicitly names the section "Enterprise
Memory — System Details". I implemented the newer instruction and **narrowed the
test rather than deleting it**: the rule is now about placement — the operator's
page must not name the layer, the administrator's drawer may. If you want the
older rule back, that test is where to say so.

---

## 13. Tests

`tests/test_evidence_explorer.py` — 41 new tests. Plus three migrated GUI tests
in `tests/test_enterprise_memory.py` and four updated PR-047A guards.

**Two tests were passing for the wrong reason and are now real:**

1. `test_no_memory_page_leaks_a_password` — `/memory` is now a 302, and a
   redirect's empty body satisfies "contains no secret" without ever rendering
   the page. It now follows redirects and asserts a page was actually built.
2. **The bundle secret assertions were vacuous.** A zip is DEFLATE-compressed,
   so `assertNotIn(b"SUPERSECRET", response.data)` passes whether or not the
   secret is in the archive. Every bundle assertion now decompresses each member
   and searches that. The route-level check had no other assertion protecting
   it, so it was checking nothing at all.

**Mutation-proven** — each guard was broken on purpose and the suite caught all
seven:

| Mutation | Caught by |
|---|---|
| an empty response counted as a FAILURE | `test_an_empty_response_is_not_a_failure` |
| a FAILED command counted as collected | `test_a_failure_is_never_reported_as_collected` |
| used-by matching on device, not content address | `test_a_policy_finding_is_reported_only_when_it_cites_this_evidence` |
| the default bundle serving RAW output | `test_a_default_bundle_masks_every_secret` |
| bundle names escaped instead of allowlisted | `test_a_name_cannot_escape_the_bundle` |
| the record page rendering RAW output | `test_a_record_page_masks_output_and_offers_the_raw_download` |
| a listing eagerly reading every blob | `test_a_listing_page_never_reads_a_blob` |

---

## 14. Manual validation (live lab, 29 FRR devices)

| # | Step | Result |
|---|---|---|
| 1 | Timeline → Evidence | pass |
| 2 | Select latest session | pass (Fresh lab, 15:10:11) |
| 3 | Canonical devices shown exactly once | pass — 29 rows, 29 unique, 0 duplicates |
| 4 | Open core1 | pass |
| 5 | Commands and statuses | pass — 12/14 collected, 2 empty |
| 6 | Open `show running-config` | pass |
| 7 | Masked output / facts / usage | pass — 11 policy findings + config link |
| 8 | Download one command output | pass — `show-running-config-a357fe6971.txt`, 1788 B |
| 9 | Download a device bundle | pass — `evidence-device-frr-core1.zip`, 8362 B |
| 10 | No secrets in page HTML or normal bundle | **inconclusive on the lab** — see below |
| 11 | Empty LLDP shown as Empty, not Failed | pass — `badge-info`, "Empty", no View link |
| 12 | Device actions open the correct canonical device | pass |
| 13 | Responsive; does not preload blobs | pass — see §11 |

**Step 10 is inconclusive against the live lab, and this matters.** The FRR
configurations contain **no password or secret lines at all** — the scan found 0
secret-bearing lines *and* 0 masked markers. The lab cannot prove masking works
because it has nothing to mask. Masking is proven instead by
`tests/test_evidence_explorer.py`, which uses a fixture configuration containing
real `SUPERSECRET` / `HUNTER2` lines, and by the mutation run above. Do not read
"no secrets leaked on the lab" as evidence of anything.

---

## 15. Limitations

1. **"Failed collections" is structurally always 0.** `COLLECTION_ERROR` exists
   in the vocabulary but nothing in discovery sets it; a transport-level failure
   never reaches memory, so it cannot be counted. The metric renders and the
   status displays correctly if a record ever carries it. Making it meaningful
   is a discovery-side change (record the attempt, not just the result) and was
   out of scope here.
2. **"Timed Out" and "Skipped" are not implemented** — no stored representation.
   Not shown rather than faked.
3. **Used-by covers configuration evidence only.** `show version`, LLDP, routes
   and the rest feed the topology through parsers that keep no reference back to
   the record. Extending this means carrying the evidence id through discovery's
   parse step — a real change to the discovery pipeline, not a UI one.
4. **Topology / Prediction / Investigation / Advisor / Mission are never named
   as consumers**, because no result-level provenance links them to a record.
   The spec listed them; inventing those links was the one thing worse than
   omitting them.
5. **The reverse direction is not built.** Policy still links to `/evidence`
   generally, not to the exact record behind each verdict. The data now exists
   to do it (each `PolicyEvaluation.result.evidence_used` carries the sha) —
   this PR built the destination; the deep link from each finding is the natural
   next PR, and is what makes the whole thing pay off.
6. **Screenshots not captured** (browser pane limitation — see §1).
7. **Reprocessing remains unimplemented.** The page says raw evidence is kept so
   a future parser can reprocess history; `reprocess` appears in the codebase
   only in docstrings. The claim is about the storage guarantee, which is true.
   No action promises the capability.

---

## 16. Files

**New**
- `src/founderos_atlas/web/evidence_view.py` — all derivation (statuses,
  summary, grouping, used-by, facts). Pure, testable, no I/O.
- `src/founderos_atlas/web/evidence_bundle.py` — bundle service.
- `src/founderos_atlas/web/templates/evidence_{index,device,record}.html`
- `tests/test_evidence_explorer.py`

**Changed**
- `web/routes.py` — Explorer routes + `/memory` compatibility redirects.
- `web/models.py` — Timeline nav reordered; Evidence → `/evidence`.
- `web/static/atlas.css` — badge tones, output block.
- `web/static/atlas-device-actions.js` — Copy Output, reusing the existing copy
  plumbing (one implementation, three buttons).
- `templates/policy.html`, `templates/timeline.html` — Evidence links repointed.
- `tests/test_enterprise_memory.py`, `tests/test_product_focus.py` — migrated.

**Removed** (superseded, unreferenced)
- `templates/memory_{index,session,device,evidence}.html`

**Untouched, as mandated:** Enterprise Memory, CORTEX, the reasoning kernel, the
policy engine, the blob store, discovery.

Every pre-PROOF URL still resolves:

| Old | New |
|---|---|
| `/memory` | → `/evidence` |
| `/memory/session/<id>` | → `/evidence?session=<id>` |
| `/memory/device/<id>` | → `/evidence/device/<id>` |
| `/memory/device/<id>/evidence/<sha>` | → `/evidence/device/<id>/record/<sha>` |
| `/memory/device/<id>/evidence/<sha>/download` | → `…/record/<sha>/download` |
| `/memory/device/<id>/config/<sha>/download` | → `…/config/<sha>/download` |
