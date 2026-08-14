# External Beta Readiness — Final Re-Audit

**Role:** independent Enterprise Network Product Reviewer · External Beta Gatekeeper ·
Product Reliability Architect · Security Reviewer · Enterprise UX Reviewer ·
Supportability Reviewer · skeptical Network Operations Manager.

**Mandate:** re-run PR-175 against the product as it exists today and decide one thing —
can we responsibly hand this build to 5–10 external network engineers tomorrow?

**Audit-only.** No code was modified. Nothing was committed. Nothing was pushed.

---

## 1. Scope, method, and what this audit is not

### 1.1 The question being answered

> Can we responsibly hand this build to 5–10 external network engineers tomorrow —
> engineers who did not build Atlas, who will run it against labs and controlled
> networks, who may hit bad credentials, unsupported devices, partial discovery and
> stale data, and who will contact us when something breaks?

This is **not** "is Atlas finished", "is Atlas production-ready", or "is Atlas perfect".
A beta build is allowed to be incomplete, rough, and narrow. It is not allowed to be
**silently wrong**.

### 1.2 Method

Every finding in this document was **re-measured at the current HEAD**. Documentation
was used only to reconstruct what PR-175 claimed — never to score whether it is still
true. The evidence rule applied throughout:

- A finding counts as **closed** only if current HEAD proves it closed.
- A finding counts as **open** only if current HEAD reproduces it.
- Anything I could not reproduce or disprove is recorded as **unverified**, not guessed.

Instruments used:

| Instrument | Used for |
|---|---|
| Flask test client against `create_app()` | synchronous server render timing, page text, HTTP contract, role/authz forcing |
| Direct execution of product modules (`collect_configuration`, `EvidenceSink`, `EnterpriseMemoryStore`, `MemoryEvidenceProvider`) | end-to-end behaviour reproduction with the repo's own vendor fixtures |
| Browser pane (`javascript_tool`, hidden iframes, `resize_window`) | layout overflow, focusables, accessible names, contrast, coarse-pointer hit areas |
| `pytest tests -q` | full suite |
| Purpose-built scratch workspaces | fresh-install first-run, small estate, live 15-profile/85-device estate, three role identities |

### 1.3 Deliberate limits

- No destructive security exploitation. This is product validation, not penetration testing.
- No changes to the repository, the workspace estate, or any stored artifact.
- Where a claim from a prior review could not be reproduced, it is reported as
  **refuted**, not repeated.

### 1.4 A note on the previous audit round

Eight independent audit passes were run over this build. Seven completed; one
(the "novel findings" dimension) died mid-run with a connection error and produced
nothing. **That dimension is therefore uncovered by the fan-out**, and I covered it
directly myself in §22. Two escalations raised by the fan-out were **refuted** on
re-measurement and are recorded as refuted in §26 rather than carried as findings.

---

## 2. Build under audit

| Fact | Value |
|---|---|
| HEAD | `86240a9` — *docs(atlas): PR-180 architecture review + implementation handover* |
| Branch | `main` |
| Working tree | clean (`git status --porcelain` empty) |
| Product identity shown in-app | `FounderOS Atlas 0.3.0a1 · Beta` |
| Platform | Windows 10 Pro 19045, Python venv at `./.venv` |
| Full suite at HEAD | **3285 passed · 2 skipped · 933 subtests · 0 failed** (955.98 s) |

Test worlds used:

| World | Shape | Purpose |
|---|---|---|
| fresh temp workspace | zero profiles, zero discovery | first-run / first-30-minutes |
| `atlas-pr1782` | small estate, 3 identities | operator workflows, search, roles |
| `atlas-pr179` | password mode, viewer / investigator / operator | authorization forcing |
| repo `.atlas/profiles` | 15 profiles, 85 devices | performance under real load |
| repo vendor fixtures | 10 platform transcripts | multi-vendor behaviour |

---

## 3. PR-175 reconstructed, finding by finding

PR-175 (`docs/reviews/PR-175_EXTERNAL_BETA_READINESS_REVIEW.md`) scored **72/100** across
nine weighted dimensions and defined a **17-criterion beta gate** (G1–G17: 7 pass,
6 fail, 2 unverified, 2 partial). It raised a top-10 issue list with one BLOCKER, and
proposed a five-PR plan (PR-176/177/178 MUST, PR-179/180 SHOULD).

Its top-10, as written:

| # | Severity | Finding as stated in PR-175 |
|---|---|---|
| 1 | **BLOCKER** | Policy page cold render ≈ 10 s on the live estate — Atlas appears hung |
| 2 | HIGH | 24 navigation destinations on a workspace with nothing in it |
| 3 | HIGH | "Playground" exposed in primary navigation as if it were a product area |
| 4 | HIGH | Pages open with prose paragraphs instead of the answer |
| 5 | HIGH | Zero-states assert facts ("0 changes") that Atlas has not established |
| 6 | HIGH | Discovery's primary action is a sample/console, not "create a real profile" |
| 7 | MEDIUM | Unknown and healthy are visually indistinguishable |
| 8 | MEDIUM | Dense tables have no per-row action affordance |
| 9 | MEDIUM | No product version or build identity anywhere in the UI |
| 10 | MEDIUM | Keyboard depth — hundreds of focusable elements before content |

---

## 4. PR-175 finding-by-finding re-measurement

Each row below is my own measurement at HEAD `86240a9`. No row is scored from documentation.

| # | PR-175 finding | Re-measured result | Verdict |
|---|---|---|---|
| 1 | Policy cold ≈ 10 s | Policy cold **681.9 ms**, warm **113 ms** on the same live 15-profile / 85-device estate. Prior measurement of the same page on the same estate: **9,975 ms**. Fresh workspace: every page ≤ **5.8 ms**. Small estate: every page ≤ **586 ms** cold. | **CLOSED** |
| 2 | 24 nav destinations on an empty workspace | Fresh workspace now offers **3** destinations; the rest reveal after discovery succeeds. | **CLOSED** |
| 3 | Playground in primary nav | Not present in the rendered sidebar on any world. (The `NavItem` definition still exists at `src/founderos_atlas/web/models.py:109` but is filtered out of both render sites.) | **CLOSED** |
| 4 | Pages open with prose | Upfront word count before the answer measured at **2–9 words** per page. | **CLOSED** |
| 5 | Zero-states assert unestablished facts | 33/33 honesty injections passed, including zero-state framing on Policy, Changes, Timeline, Paths, Predict, Topology, Evidence. | **CLOSED** |
| 6 | Discovery primary action is a sample | Primary action is now **"Add discovery profile"**. No "(sample)" and no "Execution Console" primary. | **CLOSED** |
| 7 | Unknown vs healthy indistinguishable | Unknown renders as slate `rgb(100,116,139)`, contrast **4.76:1**, visually and semantically distinct from healthy. All status tones ≥ **4.51:1** (AA). | **CLOSED** |
| 8 | No per-row action affordance | Row action groups present on Evidence, Configuration, Changes, Policy, with permission gating. | **CLOSED** |
| 9 | No version or build identity | `FounderOS Atlas 0.3.0a1 · Beta` on **every** page; diagnostics carry build identity with dirty/foreign-build suppression. | **CLOSED** |
| 10 | Keyboard depth | Changes: **564 → 163** focusable elements. Policy: still **536–756**. Improved, not resolved. | **PARTIAL** |

**Result: 9 of 10 PR-175 findings closed at HEAD; 1 partial. The single PR-175 BLOCKER is closed.**

---

## 5. Score from zero — dimension by dimension

Scored fresh, not as `72 + delta`. Weights are stated so the arithmetic is auditable.

### 5.1 First-run experience — 12 / 15

**What I measured.** On a genuinely empty workspace: Home renders in ≤ 5.8 ms, states what
Atlas is in 2–9 words before the first control, offers exactly **3** destinations, and its
primary action is **"Add discovery profile"**. `/discovery/wizard` is reachable and states
that drafts never contain credential material. Topology, Evidence and Policy all render
honest zero-states rather than asserting counts. Startup emits a real recovery command and
canonical error text. The Beta identity line is present before anything else.

**What costs points.** There is no packaged installer — an external tester must create a
Python virtual environment and install the project themselves. There is no demonstration
dataset, so a tester whose first discovery fails has no way to see what a populated Atlas
looks like, and therefore no way to tell "Atlas is broken" from "my lab is unreachable".

### 5.2 Information architecture and wayfinding — 11 / 15

**What I measured.** Guided navigation collapses to 3 destinations pre-discovery and
reveals the rest on first success. `Ctrl+K` returns grouped results — devices, interfaces,
profiles, policies — each with a working deep link. PRISM has a front door rather than
being reachable only from settings.

**What costs points.** Policy still presents **536–756** focusable elements, so keyboard and
screen-reader users traverse a long path to the answer. `/search?q=…` is a 404: search is
`/api/search` consumed by the palette. That is a deliberate design, but a tester who types
a search URL gets a bare 404 rather than a pointer to `Ctrl+K`.

### 5.3 Visual hierarchy and density — 11 / 15

**What I measured.** Shared answer-band, measurement and basis components are adopted
across Policy, Changes, Timeline, Evidence, Configuration and Home. Filter chips replace
free-form filter prose. Changes dropped from 564 to 163 focusable elements.

**What costs points.** Policy remains the densest page in the product and did not receive
the same reduction. Dense tables are legible but still ask a lot of a first-time reader.

### 5.4 Honesty and trust — 11 / 20

This is the dimension the product exists to win, and it is the dimension that decides
this audit.

**What I measured as correct — 33 of 33 honesty injections passed:**

- Discovery failures are **typed**, not collapsed: credential refusal, unreachable
  address, unsupported platform and silent address are four different reported facts.
- Last-known-good topology is preserved across a failed run, behind a freshness banner
  whose staleness count increments per failure and clears on the next success.
- Partial discovery, zero discovery and a fully silent sweep each produce distinct,
  accurate copy — a /24 sweep that finds nothing does not report 245 "failures".
- Degraded storage renders as a degraded page with a stated unreadable-file count,
  never as a 500 and never as a quietly narrowed table presented as complete.
- Write-blocking leaves stored bytes untouched and says so.
- Job deep links resolve to the job they name.
- Diagnostics carry no filesystem paths, account names, hostnames or device addresses —
  only fingerprints, correlation ids and canonical status values.
- A dirty or foreign build hash suppresses the build-identity claim rather than
  asserting a provenance Atlas cannot prove.

**What costs nine points.** Configuration collection fabricates configurations, and Policy
then fabricates compliance verdicts from them, silently, on the majority of the platforms
Atlas advertises. Full reproduction in **§23**. This is not a rough edge in the honesty
model; it is the honesty model failing at the one place where a network engineer will
believe Atlas without checking.

### 5.5 Perceived performance — 9 / 10

Policy cold **681.9 ms** / warm **113 ms** on the live estate. Live-estate Home: **1,438 ms**
first-in-process, then **164 ms** and **178 ms**. Fresh workspace: every page ≤ **5.8 ms**.
Small estate: every page ≤ **586 ms** cold. The point withheld is the first-in-process
1,438 ms Home render — the first page a tester ever loads on a large estate is still the
slowest one they will see.

### 5.6 Empty and degraded states — 9 / 10

Every zero-state measured describes what Atlas has and has not established rather than
asserting a count. Unreadable stored files are counted and surfaced. Malformed input
produces 400 and unauthorized action produces 403, both rendered, neither a 500.

### 5.7 Accessibility foundations — 5 / 5

**0 of 759** focusable controls lack an accessible name. Skip link present. **8** landmark
regions. Every status tone ≥ **4.51:1**, meeting AA.

### 5.8 Responsive and touch — 4 / 5

**Zero** horizontal overflow at 375 px, 768 px and 1920 px. Under emulated coarse pointer,
hit areas measure: checkboxes **30×30**, chips **27**, column controls **30**, inbox **28**.
All clear the WCAG 2.2 AA minimum of 24 px; none reach the 32 px bar PR-175 set.

### 5.9 Cross-page consistency — 4 / 5

Version and Beta chrome on every page; one shared component vocabulary; one canonical error
vocabulary. Policy's density is the visible inconsistency against the rest of the product.

---

## 6. Score summary

| Dimension | Weight | Score |
|---|---:|---:|
| First-run experience | 15 | **12** |
| Information architecture and wayfinding | 15 | **11** |
| Visual hierarchy and density | 15 | **11** |
| Honesty and trust | 20 | **11** |
| Perceived performance | 10 | **9** |
| Empty and degraded states | 10 | **9** |
| Accessibility foundations | 5 | **5** |
| Responsive and touch | 5 | **4** |
| Cross-page consistency | 5 | **4** |
| **Total** | **100** | **76** |

**PR-175: 72/100. Today: 76/100.**

The four-point gain understates the work and overstates the health, and both distortions
should be named:

- Eight of nine dimensions improved, several substantially. The PR-175 BLOCKER is closed
  and 9 of its 10 findings are closed.
- Honesty and trust — the heaviest dimension — went **down**, because this audit tested
  something PR-175 never tested: what Atlas does when the device is not Cisco. The defect
  is not a regression. It predates PR-175 and was simply never found.

A rising score with a falling honesty dimension is exactly the shape you would expect from
a product that has been polished thoroughly and probed narrowly.

---

## 7. The first 30 minutes

Simulated on a genuinely empty workspace, in order, as a tester who has never seen Atlas.

| Minute | What the tester tries | What happens |
|---|---|---|
| 0 | Starts Atlas | Startup prints real, runnable recovery guidance and canonical error text; binds **127.0.0.1 only** |
| 1 | Opens Home | Renders in ≤ 5.8 ms; identifies itself as `FounderOS Atlas 0.3.0a1 · Beta` |
| 2 | "What is this?" | Answer in 2–9 words before the first control |
| 3 | "What do I do first?" | Single primary action: **Add discovery profile** |
| 4 | Looks at the nav | **3** destinations — not 24 |
| 6 | Opens the wizard | Reachable; states drafts never contain credential material |
| 10 | Enters credentials | Resolved server-side; never written into a draft |
| 15 | Runs discovery against a lab | Typed outcomes: reached / refused credentials / unreachable / unsupported / silent |
| 20 | Discovery partly fails | Partial result reported honestly with counts that match reality |
| 22 | Opens Topology before success | Honest zero-state, not an empty canvas implying an empty network |
| 25 | Opens Evidence and Policy | Honest zero-states; no asserted counts |
| 28 | Wants to report something | Job deep link + `/settings/diagnostics.json`, which contains no paths, hostnames or addresses |

**Two friction points a tester will hit in the first 30 minutes and should be warned about
in advance:** there is no installer (they must build a venv), and there is no demo dataset
(a failed first discovery leaves them unable to distinguish a broken Atlas from an
unreachable lab).

---

## 8. Discovery reality check

Measured by injection against the real discovery path, not by reading tests.

| Scenario | Behaviour at HEAD | Verdict |
|---|---|---|
| Bad credentials | Reported as credential refusal, counted separately from unreachable | PASS |
| Unreachable address | TCP reachability probe screens it; reported as unreachable | PASS |
| Silent /24 sweep | Reported as addresses-without-device, **not** as failures | PASS |
| Unsupported platform | Counted as `unsupported_platforms`, separate from failure | PASS |
| Partial success | Reported as answered-but-not-collected, with matching counts | PASS |
| Mid-run connection loss | Remaining optional commands marked skipped-after-connection-lost, with warnings | PASS |
| Re-run after failure | Last-known-good preserved; freshness banner counts staleness; clears on success | PASS |
| Job identity | Deep link resolves to the correct job; correlation ids stable | PASS |
| **Configuration collection on a non-Cisco device** | **Refusal text stored as the running configuration, labelled complete, zero warnings** | **FAIL — see §23** |

Discovery's *reporting* is honest and well-built. Discovery's *configuration collection
stage* is not.

---

## 9. The multi-vendor claim

Atlas shows this list to the tester in its own discovery wizard, under
**"Supported platforms"** (`registry.supported_platforms()`, rendered at
`discovery_wizard.html:115`):

> Cisco IOS-XE, Cisco IOS / IOS-XE, Cisco NX-OS, Arista EOS, Juniper Junos, Fortinet
> FortiOS, Palo Alto PAN-OS, Aruba CX, Cisco Wireless LAN Controller, F5 BIG-IP,
> Citrix ADC, A10 ACOS, FRRouting, AtlasLab firewall, AtlasLab switch

**Fifteen platforms, claimed in-product, to the tester's face.**

Discovery genuinely honours that claim: each driver carries its own command plan, its own
parser, and its own correct configuration command — the Junos driver knows the config
lives behind `show configuration | display set`, and the evidence sink knows that command
IS a running configuration.

**Configuration collection does not.** `src/founderos_atlas/config/collector.py:34` hardcodes
`RUNNING_CONFIG_COMMAND = "show running-config"` and line 69 sends it with **no platform
branch at all**. Line 75 rejects only *empty* output. Any non-empty reply — including the
device saying it does not understand the question — becomes `STATUS_COLLECTED`.

The only safety net is a marker list in the transport layer,
`src/founderos_atlas/transport/ssh.py:43`:

```python
_UNSUPPORTED_MARKERS = ("invalid input detected", "% unknown command")
```

Two Cisco phrasings. Measured against the repo's own vendor refusal transcripts:

| Platform | Refusal transcript (repo fixture) | Transport raises? | Evidence status assigned |
|---|---|:---:|---|
| Cisco IOS-XE | `% Invalid input detected at '^' marker.` | **yes** | `unavailable` |
| A10 ACOS | `% Invalid input detected at '^' marker.` | **yes** | `unavailable` |
| Aruba CX | `% Unknown command.` | **yes** | `unavailable` |
| Arista EOS | `% Invalid input` | no | `unavailable` |
| Cisco NX-OS | `% Invalid command at '^' marker.` | no | **`collected`** |
| Juniper Junos | `           ^`<br>`unknown command.` | no | **`collected`** |
| Palo Alto PAN-OS | `Unknown command: garbage` / `Invalid syntax.` | no | **`collected`** |
| Fortinet FortiOS | `Command fail. Return code -61` | no | **`collected`** |
| Citrix ADC | `ERROR: No such command` | no | **`collected`** |
| F5 BIG-IP | `Syntax Error: unexpected argument "garbage"` | no | **`collected`** |
| Cisco WLC | `Incorrect usage.  Use the '?' or <TAB> key to list commands.` | no | **`collected`** |

Two distinctions matter for severity, and I want both stated precisely rather than
inflated:

- On **NX-OS, EOS, Aruba CX and FRRouting**, `show running-config` is a *real* command.
  The unrecognised refusal grammar only mislabels *optional* commands, storing a
  refusal as e.g. `show_license_summary.txt`. That is wrong but low-consequence.
- On **Juniper Junos, Palo Alto PAN-OS, Fortinet FortiOS, F5 BIG-IP, Citrix ADC and
  Cisco WLC**, `show running-config` is **not a valid command at all**, and their refusal
  is not recognised. For these six, the *running configuration itself* is fabricated.

**Six of the fifteen platforms Atlas advertises will have their configurations fabricated
if a tester enables configuration collection.**

---

## 10. Trust and data honesty — "try to make Atlas lie"

I attacked this dimension directly. Thirty-three injections; Atlas told the truth in
thirty-three of them.

| Attack | Outcome |
|---|---|
| Kill discovery mid-run, reload every page | Last-known-good served behind an explicit freshness banner; nothing presented as current |
| Fail discovery repeatedly | Staleness count increments per failure, clears on the next success |
| Corrupt stored annotation files | Page renders degraded with a stated unreadable count; no 500; no silent narrowing |
| Make the workspace read-only | Write attempts blocked, stored bytes untouched, the block stated |
| Sweep a subnet with nothing on it | Reported as addresses-without-device, not as failures |
| Discover zero devices | Zero-state describes what was attempted; no fabricated counts |
| Present a foreign / dirty build hash | Build-identity claim suppressed rather than asserted |
| Ask diagnostics to leak | No paths, account names, hostnames, device addresses, site names or profile display names |
| Force a job deep link to the wrong job | Resolves correctly or refuses; never silently substitutes |
| **Answer discovery from a device that does not speak Cisco** | **Atlas lies. It reports a configuration it never collected, marks it complete, counts it, stores it, and reasons over it.** |

Thirty-three of thirty-four. The one that fails is the one that matters most, because it
is the only one where Atlas does not merely omit or degrade — it **asserts something false
with full confidence and no warning**.

---

## 11. Performance

| Surface | Estate | Cold | Warm |
|---|---|---:|---:|
| Policy | live (15 profiles / 85 devices) | **681.9 ms** | **113 ms** |
| Home | live | 1,438 ms (first in-process) | 164 ms / 178 ms |
| all pages | fresh workspace | ≤ **5.8 ms** | — |
| all pages | small estate | ≤ **586 ms** | — |

PR-175 measured the same Policy page on the same estate at **9,975 ms**. That is a
**14.6× improvement** and it closes PR-175's only BLOCKER. Nothing in the current build
renders slowly enough to read as hung.

**Not a beta blocker.** The 1,438 ms first-in-process Home render is worth telling testers
about so they do not mistake first-load warm-up for a hang.

---

## 12. Topology

| Property | Measured |
|---|---|
| Zoom step | exactly **1.148×** per notch |
| Zoom range | ~30 notches across **0.05 → 3.0** |
| Legend | native `<details>`, works without JavaScript |
| Unresolved peers | explicit note distinguishing proven links from reported adjacencies |
| Definitions | canonical definitions reachable behind `?support=1` |
| Stale data | last-known-good behind an explicit freshness banner with a staleness count |
| Relationship honesty | physical links / routing adjacencies / protocol peers / unresolved kept separate |

Topology behaves correctly and, importantly, does not present a routing adjacency as a
cable. No findings.

---

## 13. Operator workflows

Run against a populated estate as a real operator would.

| Task | Route | Result |
|---|---|---|
| Which devices are failing policy? | `/policy?status=fail` | 200, filtered answer |
| What changed in a scope? | `/changes?scope=…` | 200, scoped answer |
| What happened yesterday? | `/timeline` | 200, grouped by day |
| Show me exactly what Atlas observed | `/evidence` | 200, raw evidence with provenance |
| Why can't A reach B? | `/paths` | 200, honest about what is and is not established |
| Find BGP evidence | `Ctrl+K` → `/api/search` | grouped results with deep links |
| Find a device by name | `Ctrl+K` → `/api/search` | devices / interfaces / profiles / policies, deep-linked |
| Annotate a change | `/changes` row action | works; permission-gated |
| Annotate many changes | `/changes/bulk` | works; correlation-grouped in Timeline and audit |

One friction point: `/search?q=…` returns **404**. Search lives at `/api/search` behind the
`Ctrl+K` palette by design, so this is not a defect — but the 404 gives a tester no hint
that `Ctrl+K` is the door. Worth one line in the tester notes.

---

## 14. Role and authorization behaviour

Three identities on a password-mode workspace: **viewer**, **investigator**, **operator**.

| Check | Result |
|---|---|
| Viewer sees bulk controls | **No** |
| Viewer sees row action controls | **No** |
| Viewer forces a POST anyway | **403** |
| Operator sees bulk / row controls | **No** |
| Operator forces a POST anyway | **403** |
| Investigator gets the change workflow | **Yes**, end to end |
| Dead controls (visible but non-functional for the role) | **Zero** |

Authorization is enforced server-side, not by hiding buttons, and the UI does not offer a
control the identity cannot use. No findings.

---

## 15. Accessibility and responsive

| Check | Result |
|---|---|
| Focusable controls without an accessible name | **0 of 759** |
| Skip link | present |
| Landmark regions | 8 |
| Status tone contrast | all ≥ **4.51:1** (AA); unknown = slate `rgb(100,116,139)`, **4.76:1** |
| Horizontal overflow at 375 / 768 / 1920 px | **zero** at all three |
| Touch targets under emulated coarse pointer | checkbox **30×30**, chip **27**, column control **30**, inbox **28** |
| Keyboard depth | Changes **163**; Policy **536–756** |

Two open items, both **LOW**: touch targets clear the WCAG 2.2 AA 24 px minimum but not the
32 px bar PR-175 set for itself, and Policy's keyboard depth is unchanged.

*Method note:* coarse-pointer emulation requires an actual mobile-preset viewport. Merely
narrowing a desktop window does not activate `@media (pointer: coarse)` and will report
desktop hit areas.

---

## 16. Supportability

The thing that decides whether a tester's bug report is actionable.

| Capability | State |
|---|---|
| Product + build identity visible | `FounderOS Atlas 0.3.0a1 · Beta` on every page |
| Build provenance | present; **suppressed** when the tree is dirty or the hash is foreign |
| Support artifact | `/settings/diagnostics.json`, allowlisted key set, pinned by test |
| Privacy of that artifact | no paths, account names, hostnames, device addresses, site or profile display names |
| Failure identity | typed failures with stable correlation ids |
| Job traceability | `/discovery?job=…` deep links |
| Last discovery facts | present in diagnostics |
| Startup errors | canonical text plus a real, runnable recovery command |

Supportability is genuinely strong and is the clearest evidence that PR-179 and PR-180 did
what they set out to do. If a tester sends us a diagnostics blob and a correlation id, we
can act on it without asking them for their network topology.

---

## 17. Destructive actions and data safety

| Check | Result |
|---|---|
| Actions that write to devices | **None.** Transport is read-only, exec mode only; non-`show` commands are rejected before the wire |
| Enable mode / configuration mode | Never entered |
| Deletion of stored artifacts | Requires explicit operator action; confirm pages present |
| Read-only workspace | Writes blocked, stored bytes untouched, block stated |
| Credential handling | Resolved server-side; never written into drafts; never in artifacts |
| Bind address | **127.0.0.1 only**; `0.0.0.0` explicitly rejected in `commands.py:1526` |

No findings. Atlas cannot damage a tester's network, which is the single most important
property for a build going to strangers' labs.

---

## 18. Deferred items from PR-176 – PR-180

| Item | Deferred in | State at HEAD | Severity |
|---|---|---|---|
| Policy keyboard depth | PR-177 | Still 536–756 focusable | LOW |
| Touch targets to 32 px | PR-180 | 27–30 px (AA-compliant, below own bar) | LOW |
| Playground `NavItem` definition | PR-177 | Still defined at `models.py:109`, filtered from both render sites | LOW (dead code) |
| Home first-in-process render | PR-176 | 1,438 ms on a large estate | LOW |
| Deferred/lazy page loading | PR-176 | Measured, then deliberately not implemented — memoisation was sufficient | Correctly closed |

Nothing deferred rises above LOW. **No deferred item is a beta blocker.**

---

## 19. Security and privacy — adversarial pass

Non-destructive, local test environment only.

| Probe | Result |
|---|---|
| Does Atlas bind beyond loopback? | No — `127.0.0.1` fixed; `0.0.0.0` explicitly refused |
| Does Atlas phone home? | No. The only outbound HTTP is PRISM (`prism/providers.py`), which is **disabled by default** (`config.py:99 enabled: bool = False`) and points at operator-configured providers |
| Are credentials ever persisted to artifacts? | No — resolved server-side, never in drafts, never in metadata |
| Does configuration metadata leak configuration content? | No — provenance and a SHA-256 only; pinned by test |
| Does the support artifact leak identity? | No — allowlisted keys, fingerprints and correlation ids only |
| Are configuration views masked? | Yes — view is masked, download is raw and explicit |
| Can a viewer/operator escalate by forcing a POST? | No — 403 |
| Is TLS verification defeatable silently? | Only via an explicit PRISM `verify_tls` opt-out |
| **Is the source licensed for the people receiving it?** | **No — see §23.2** |

---

## 20. Regression sweep — 20 items

| # | Item | Result |
|---:|---|---|
| 1 | Home renders on a fresh workspace | PASS |
| 2 | Fresh workspace offers 3 destinations | PASS |
| 3 | Version + Beta chrome on every page | PASS |
| 4 | `Ctrl+K` groups results and deep-links correctly | PASS |
| 5 | Discovery primary action is "Add discovery profile" | PASS |
| 6 | Wizard reachable; drafts hold no credential material | PASS |
| 7 | Topology zero-state honest | PASS |
| 8 | Evidence zero-state honest | PASS |
| 9 | Policy zero-state honest | PASS |
| 10 | Policy cold render < 1 s on the live estate | PASS (681.9 ms) |
| 11 | Home warm render < 250 ms on the live estate | PASS (164 / 178 ms) |
| 12 | Zero horizontal overflow at 375 / 768 / 1920 px | PASS |
| 13 | Zero unnamed focusable controls | PASS (0 of 759) |
| 14 | Skip link + landmarks | PASS (8) |
| 15 | All status tones ≥ 4.5:1 | PASS (min 4.51) |
| 16 | Viewer/operator get no privileged controls; forced POST → 403 | PASS |
| 17 | Topology legend, definitions, unresolved-peer note | PASS |
| 18 | Freshness banner increments on failure, clears on success | PASS |
| 19 | Degraded storage renders without a 500 | PASS |
| 20 | **Configuration collection refuses to fabricate a config** | **FAIL** |

Two items outside the twenty, recorded rather than hidden: touch targets are 27–30 px
(AA-compliant, below the 32 px bar PR-175 set), and Policy keyboard depth is unchanged.

---

## 21. Full test suite

```
3285 passed, 2 skipped, 1 warning, 933 subtests passed in 955.98s (0:15:55)
```

Zero failures. This matches the PR-180 handover baseline exactly, so nothing regressed.

**And this is the most important sentence in this section:** the suite is green **and** the
build fabricates configurations for six advertised platforms. The suite proves the code
does what its authors intended. It does not prove the intention was right. `test_config_collection.py`
covers Cisco refusal grammar thoroughly (`test_required_running_config_failure_raises`
passes) and never asks what a Junos device would say. A green suite is not evidence of
beta readiness; it is evidence of internal consistency.

---

## 22. New findings — not present in PR-175

The fan-out agent assigned to this dimension died mid-run, so I covered it directly.

| # | Severity | Finding | Evidence |
|---|---|---|---|
| N1 | **BLOCKER** | Configuration collection fabricates configurations on 6 of 15 advertised platforms; Policy then fabricates compliance verdicts from them | §23.1 — reproduced end to end |
| N2 | **BLOCKER** (non-engineering) | `LICENSE` states no license is selected and no permission should be inferred, while the beta hands the full source tree to 5–10 external engineers | §23.2 |
| N3 | MEDIUM | Vendor refusal grammars mislabel *optional* command outcomes as `collected` on NX-OS, EOS and others — wrong evidence status, low consequence | §9 table |
| N4 | LOW | No packaged installer; testers must build a Python venv | §7 |
| N5 | LOW | No demonstration dataset; a tester whose first discovery fails cannot distinguish a broken Atlas from an unreachable lab | §7 |
| N6 | LOW | `/search?q=…` 404s with no pointer to `Ctrl+K` | §13 |
| N7 | LOW | Dead `Playground` `NavItem` still defined at `models.py:109` | §18 |

---

## 23. The blockers, in full

### 23.1 BLOCKER-1 — Atlas stores a device's refusal as its configuration, calls it complete, and reasons over it

**Reproduced end to end at HEAD `86240a9`, using the repository's own Junos transcript
(`tests/platform_fixtures/junos.py:89`) and the repository's own collection harness.**

**Step 1 — the collector accepts the refusal.**

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

Contrast — the *same* situation on a Cisco device, whose refusal grammar the transport
does recognise:

```
ConfigurationCollectionError: Could not collect the running configuration from R1:
Device 10.0.0.1 did not recognize 'show running-config'.
The platform does not support this command dialect.
```

So the honest path exists. It is simply unreachable for any vendor whose refusal is not
phrased the way Cisco phrases it.

**Step 2 — it reaches disk as the device's configuration.**

```
running_config.txt          = '           ^\nunknown command.\n'
metadata.collection_status  = 'complete'
metadata.warnings           = []
```

**Step 3 — Enterprise Memory records it as a good collection.**

```
_status_for('           ^\nunknown command.\n') -> 'collected'
_status_for('% Unknown command')                -> 'unavailable'
_status_for('% Invalid input detected')         -> 'unavailable'
```

**Step 4 — it displaces the real configuration for Policy.**

The Junos driver *does* collect the real configuration during discovery, via
`show configuration | display set`, and the evidence sink correctly recognises that
command as a running configuration. So one discovery run writes **two** configuration
snapshots for the same device: the real one (during discovery) and the refusal (during
the collection stage that follows).

`MemoryEvidenceProvider._pick_snapshot` selects the **newest**. In a real run, discovery
of an estate completes seconds before configuration collection begins, so the refusal is
newer. Reproduced with an advancing clock:

```
captured_at=2026-08-14T09:10:11+00:00  bytes=   30  first line: '^'
captured_at=2026-08-14T09:10:08+00:00  bytes=  515  first line: 'set version 21.4R3.15'

POLICY summary: running configuration (30 bytes, MX204)
POLICY text   : '           ^\nunknown command.'
  refusal wins? -> True
```

Atlas hands its compliance engine **thirty bytes of error text**, labelled
*"running configuration (30 bytes, MX204)"*, and the engine returns confident verdicts
with a config snippet as evidence.

*(When both writes land inside the same clock second, a stable sort happens to keep the
real configuration first. That is not a mitigation — it is nondeterminism. The outcome
depends on how long discovery took.)*

**Step 5 — the run reports success.** `_configuration_history` counts any non-`failed`
entry toward `configured_device_count`, and reports `CONFIG_COLLECTED` when every entry is
`complete`. The tester is told Atlas collected the configuration.

**Blast radius.** Six of the fifteen platforms Atlas advertises in its own wizard —
**Juniper Junos, Palo Alto PAN-OS, Fortinet FortiOS, F5 BIG-IP, Citrix ADC, Cisco WLC** —
because for these, `show running-config` is not a valid command *and* their refusal
grammar is unrecognised.

**Root cause, precisely.** Two gaps, both small:
1. `config/collector.py:34,69` sends one hardcoded Cisco command with no platform branch,
   and `:75` rejects only *empty* output — never *invalid* output.
2. `transport/ssh.py:43` recognises exactly two Cisco refusal phrasings, and
   `enterprise_memory/sink.py:108-115` recognises the same two.

**Why this is a BLOCKER and not a documented limitation.** The user's beta scenario
explicitly anticipates testers hitting "unsupported devices". Every other unsupported-device
path in this product handles that honestly — discovery types it, counts it, names it. This
one path converts an unsupported device into a **silent false assertion about a customer's
network**. A tester will not report it, because nothing looks broken. They will either
believe a fabricated compliance verdict, or discover the fabrication themselves and lose
confidence in every other number Atlas showed them — including the thirty-three that are
correct.

**Mitigating fact, stated fairly:** `collect_configuration` defaults to **`False`**
(`workspace/models.py:64`). A tester must tick a checkbox to reach this path. This
narrows exposure; it does not remove it, because the checkbox is presented as an
ordinary feature next to a wizard that advertises fifteen platforms.

**What closing it requires** (recommendation only — no code was changed): treat a
running-config reply that the platform driver does not recognise as valid configuration
as `unsupported`, not `collected`; and let the collector ask the resolved driver for its
configuration command instead of hardcoding Cisco's. Both are small, and the honest
failure path they need already exists and is already tested.

### 23.2 BLOCKER-2 — the source has no license, and the beta ships the source

`LICENSE` at HEAD reads, verbatim:

> LICENSE NOT YET SELECTED
>
> FounderOS Atlas product ownership and distribution terms require an explicit
> owner/legal decision. Engineering has deliberately not invented an open-source or
> proprietary license. No permission to copy, modify, redistribute, sublicense, or sell
> this software should be inferred from the presence of this repository.

Engineering was right not to invent one. But with no packaged installer, testers receive
the **repository**, and this notice tells them they have no permission to use it.

This is **not an engineering defect** and needs no code. It needs one decision recorded by
the authorized owner — a beta license, an evaluation agreement, or a short written grant
naming the testers and the term. It dissolves entirely if testers instead receive a
packaged build under a short beta agreement.

I am classifying it as a blocker because handing unlicensed source to five to ten external
parties should not happen, and because it costs a decision rather than a sprint.

---

## 24. Beta limitations — what testers must be told

If the blockers in §23 are closed, this is the document that ships with the build.

**Atlas 0.3.0a1 is a beta. It is read-only against your network.** It never enters enable
or configuration mode, never sends a non-`show` command, and binds only to `127.0.0.1`.

**What Atlas does well today**
- Multi-vendor discovery across 15 platform drivers
- Honest failure reporting: credential refusal, unreachable address, unsupported platform
  and silent address are four different reported facts
- Last-known-good data preserved across failed runs, behind an explicit staleness banner
- Evidence with provenance; configuration views masked, downloads explicit
- Role-based authorization enforced server-side

**Known limitations you will meet**
1. **Configuration collection is Cisco-dialect only.** *(Must be listed here only if
   shipped unfixed — see §23.1 for why I recommend fixing instead.)*
2. **No installer.** You will create a Python virtual environment and install the project.
3. **No demonstration data.** If your first discovery fails you will see empty pages;
   that means "nothing collected yet", not "Atlas is broken".
4. **First page load on a large estate takes ~1.4 s.** Subsequent loads are ~170 ms.
   That first load is warm-up, not a hang.
5. **Search lives behind `Ctrl+K`.** A `/search?q=…` URL returns 404.
6. **Policy is the densest page** and is a long keyboard traverse.
7. **Touch targets are 27–30 px** — usable, below our own 32 px target.

**How to report a problem**
Send the correlation id shown with the failure, plus `/settings/diagnostics.json`. That
file contains no filesystem paths, account names, hostnames, device addresses, site names
or profile display names — it is safe to send.

**What we are explicitly asking you to try to break:** discovery against devices we do not
expect, credentials that should fail, networks that are partly unreachable, and any number
Atlas shows you that you can prove wrong.

---

## 25. The 17-criterion beta gate, re-scored

| ID | Criterion | PR-175 | Now | Evidence |
|---|---|---|---|---|
| G1 | No page reads as hung | FAIL | **PASS** | Policy 681.9 ms cold |
| G2 | Empty workspace offers a small number of destinations | FAIL | **PASS** | 3 destinations |
| G3 | No internal/developer surface exposed as product | FAIL | **PASS** | 3 hits, all legitimate: DEBUG log-level option, bind address, PRISM settings linking to Playground |
| G4 | Discovery's primary action creates a real profile | FAIL | **PASS** | "Add discovery profile" |
| G5 | Product framing before controls | partial | **PASS** | 2–9 upfront words |
| G6 | Version and build identity visible | FAIL | **PASS** | `0.3.0a1 · Beta` every page |
| G7 | Unknown distinguishable from healthy | unverified | **PASS** | slate 4.76:1 |
| G8 | All status tones meet AA | unverified | **PASS** | min 4.51:1 |
| G9 | Zero-states honest | FAIL | **PASS** | 20/20 |
| G10 | No horizontal overflow | PASS | **PASS** | 375 / 768 / 1920 |
| G11 | Every focusable control has an accessible name | PASS | **PASS** | 0 of 759 unnamed |
| G12 | Failures are typed, not collapsed | PASS | **PASS** | §8 |
| G13 | Stale data never presented as current | PASS | **PASS** | freshness banner |
| G14 | Support artifact carries no identifying data | PASS | **PASS** | allowlisted keys |
| G15 | Authorization enforced server-side | PASS | **PASS** | 403 on forced POST |
| G16 | Touch targets ≥ 32 px | partial | **PARTIAL** | 27–30 px (AA-compliant) |
| G17 | Skip link and landmarks | PASS | **PASS** | skip link + 8 landmarks |
| — | *(implicit)* Atlas never asserts data it did not collect | not tested | **FAIL** | §23.1 |

**16 pass · 1 partial · 0 fail** against the original seventeen — a gate PR-175 would have
called ready. The failure is against a criterion PR-175 never wrote down, because it never
occurred to anyone that Atlas might invent a configuration.

---

## 26. Severity ledger

| Severity | ID | Finding |
|---|---|---|
| **BLOCKER** | N1 | Configuration collection fabricates configurations on 6 of 15 advertised platforms; Policy fabricates verdicts from them (§23.1) |
| **BLOCKER** | N2 | No license selected, while the beta distributes the source tree (§23.2) |
| MEDIUM | N3 | Unrecognised vendor refusal grammars mislabel *optional* command outcomes as `collected` |
| LOW | #10 | Policy keyboard depth 536–756 focusable |
| LOW | G16 | Touch targets 27–30 px — AA-compliant, below our own 32 px bar |
| LOW | N4 | No packaged installer |
| LOW | N5 | No demonstration dataset |
| LOW | N6 | `/search?q=…` 404s with no pointer to `Ctrl+K` |
| LOW | N7 | Dead `Playground` `NavItem` at `models.py:109` |
| LOW | — | Home first-in-process render 1,438 ms on a large estate |

**Refuted — raised during the audit, disproved on re-measurement, and recorded here so
they are not repeated as fact:**

- *"NX-OS / EOS switches are dropped from discovery entirely."* **Refuted.** The driver
  fallback chains do run; those platforms' refusal grammars simply fail to match the
  transport's markers, which affects *labelling*, not *discovery*.
- *"Transport preemption has a large blast radius."* **Refuted.** The measured effect is
  two optional IOS-XE capabilities labelled `failed` instead of `unsupported`.

---

## 27. Mandatory skeptical second pass — arguing the opposite

I am required to argue against my own conclusion. Here is the strongest case for shipping,
made honestly.

**The case for GO WITH DOCUMENTED LIMITATIONS:**

1. Configuration collection defaults to **off**. A tester must deliberately enable it.
2. Testers are **network engineers**. Shown a 30-byte "configuration" reading
   `^ unknown command.`, most would spot it in seconds.
3. Beta labelling is unambiguous — `0.3.0a1 · Beta` on every page.
4. Everything else is genuinely ready: 16/17 gate criteria, 3285 green tests, a 14.6×
   performance fix, 33/34 honesty injections, clean authorization, clean accessibility,
   a read-only transport that cannot damage anyone's network.
5. Most lab estates are Cisco-heavy. Some testers will never reach the defect.
6. Blocking a beta over one opt-in path is disproportionate, and the fix is small enough to
   land as a fast follow during the beta.
7. A beta exists precisely to find defects like this. Shipping and learning is a legitimate
   strategy.

**Why I do not accept it:**

Point 2 is the one that fails, and it fails hardest for the users we care most about. A
network engineer would spot the fake *configuration* if they opened the Configuration page
for that device. They will not spot the fake *policy verdict*, because Policy does not show
them thirty bytes of error text — it shows them a compliance result with a snippet, in a
list beside eighty-four devices whose results are real. The lie is laundered through the
one surface designed to be trusted without inspection.

Point 1 is real but weaker than it looks. The checkbox sits next to a wizard that names
Juniper Junos, PAN-OS and FortiOS as supported platforms. A tester who ticks it is acting
on Atlas's own claim.

Point 6 inverts the actual cost. The fix is small — which is an argument for **doing it
now**, not for shipping without it. A blocker that costs a day is the cheapest kind to
close before a beta and the most expensive kind to explain after one.

Point 7 misreads what betas find. Betas surface things testers *notice*. This defect is
specifically designed not to be noticed: status `complete`, zero warnings, counted as a
success. It will not come back as a bug report. It will come back — if at all — as a
quiet loss of trust.

And a documented limitation cannot carry this. Writing *"if you enable configuration
collection on a Juniper device, our compliance engine will produce meaningless verdicts
without telling you"* is not documenting a limitation. It is shipping a known-defective
feature with a warning label — the exact posture PR-180 was written to reject.

**One genuine concession to the opposing case:** if the owner decides to ship anyway, there
is a safe interim that requires no new engineering — **disable configuration collection for
this beta** (it is already off by default; remove or hard-disable the checkbox). Every other
capability remains available, the fabrication path becomes unreachable, and the beta can
start tomorrow. That is a legitimate route to GO. It is a product decision, not a review
finding, so I record it rather than choose it.

---

## 28. What would change the verdict

| If this changes | Verdict becomes |
|---|---|
| BLOCKER-1 fixed (driver-aware config command + unrecognised reply → `unsupported`) **and** BLOCKER-2 resolved (license decision recorded) | **GO — READY FOR CONTROLLED EXTERNAL BETA** |
| Configuration collection hard-disabled for the beta **and** BLOCKER-2 resolved | **GO WITH DOCUMENTED LIMITATIONS** — the limitation being "configuration collection is not in this beta", which is honest and complete |
| Only BLOCKER-2 resolved | **NO-GO** — unchanged |
| Neither resolved | **NO-GO** — unchanged |

BLOCKER-1 is a small, well-bounded change: the honest failure path already exists
(`ConfigurationCollectionError` with accurate text) and is already covered by tests. What is
missing is reaching it for non-Cisco dialects.

---

## 29. Coverage gaps and limits of this audit

Stated plainly so this document is not read as more complete than it is.

1. **No real hardware.** Every multi-vendor result comes from the repository's own vendor
   transcripts. Those transcripts are the product's own definition of vendor truth, so a
   defect against them is real — but a real MX204 may phrase its refusal differently again,
   which would widen, not narrow, §23.1.
2. **Junos was reproduced end to end; the other five affected platforms were established
   by grammar analysis** (§9 table) plus the shared root cause, not by five separate
   end-to-end runs.
3. **The "novel findings" fan-out agent died** and produced nothing. I covered that
   dimension directly in §22, but it did not receive independent adversarial fan-out.
4. **No sustained-load or concurrency testing.** Performance figures are single-user
   synchronous renders.
5. **No penetration testing**, by instruction.
6. **Windows only.** Not exercised on macOS or Linux.
7. **`/search` route absence was investigated before being reported** and is by design.

---

## 30. Verdict

# NO-GO — FIX SPECIFIC BLOCKERS FIRST

**Two blockers, both narrow, both closable quickly:**

1. **BLOCKER-1 (engineering, ~1 day):** Configuration collection stores a device's refusal
   text as its running configuration, labels it `complete` with zero warnings, counts it as
   collected, persists it, and lets Policy issue confident compliance verdicts from thirty
   bytes of error text — on six of the fifteen platforms Atlas advertises in its own wizard.
   Reproduced end to end at HEAD.

2. **BLOCKER-2 (owner decision, ~1 hour):** `LICENSE` states that no license is selected and
   no permission should be inferred, while the beta distributes the source tree to five to
   ten external engineers.

**Everything else is ready, and it is not close.** 16 of 17 gate criteria pass. The PR-175
BLOCKER is closed with a 14.6× improvement. 9 of PR-175's 10 findings are closed. 3285 tests
pass with zero failures. Thirty-three of thirty-four honesty injections pass. Authorization,
accessibility, responsive behaviour, supportability, and read-only device safety are all
clean. Nothing on the LOW list should delay anything.

This is not a NO-GO because Atlas is unfinished. Atlas is in good shape. It is a NO-GO
because of a single defect of a specific kind: **Atlas asserting, confidently and silently,
something it did not observe** — which is the one failure this product is supposed to be
incapable of.

---

## 31. Would I responsibly hand this build to 5–10 external network engineers tomorrow?

**Not tomorrow. Almost certainly the day after.**

If the estate were Cisco-only, my answer would be yes without hesitation. What stops me is
narrow and specific: a tester with a Juniper, Palo Alto, Fortinet, F5, Citrix or Cisco WLC
device in their lab who ticks "collect configuration" will be shown a configuration Atlas
never collected and compliance verdicts derived from it — with no warning, no partial
status, and a run summary that says the collection succeeded.

That is the one class of failure I cannot ask an external engineer to absorb. Every other
rough edge in this build is one a beta tester can *see*: a slow first load, a dense page, a
missing installer, a 404 on a URL they guessed. They will work around those and tell us
about them, which is what a beta is for. This one they cannot see. It arrives wearing the
costume of a correct answer, in the one part of the product built to be trusted without
inspection.

And the cost of that is not a bug report. It is the thing the last five PRs were spent
building: a network engineer's willingness to believe a number Atlas puts on a screen
without going and checking it on the device. Once a tester catches Atlas inventing a
configuration, every honest number in this build — and there are a great many of them —
becomes a number they will verify by hand. At which point Atlas is a slower way to run
`show` commands.

So: fix the collector, record the license decision, re-run the suite, and hand it over.
The distance between this build and a beta I would defend in front of ten strangers is
about a day of work — and I would rather spend that day than spend the beta explaining it.

---

*Audit performed at HEAD `86240a9` on a clean working tree. No code was modified. Nothing
was committed. Nothing was pushed.*
