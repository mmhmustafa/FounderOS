# PR-A2a — Third-Party Compliance Surface
## Implementation Handover

**Status: implemented, validated, committed locally. NOT PUSHED — awaiting review.**

Stage A2a of the PR-A2 architecture review only. The Atlas-owned LICENSE is untouched. No
evaluation grant, no proprietary metadata, no effective date, no packaging. A2b not started.

---

### 1. Executive result

The mechanical third-party compliance surface is complete: a machine-readable, SPDX-semantic
licence policy covering all 60 runtime members; a gate that parses expressions rather than
matching substrings; a deterministic 260 KB `THIRD-PARTY-NOTICES.txt` generated from the
runtime manifest and recorded evidence; exact-version corresponding source for the three
weak-copyleft components stored and hash-pinned; the CI interlock widened to all three
generated artifacts; repository documentation reconciled to the A2a truth; both obsolete
source-snapshot ZIPs removed from HEAD. 78 new tests. All 38 adversarial attacks fail.
Full suite green with zero failures.

### 2. Starting HEAD

`4d97e50` — equal to `origin/main`, verified by fetch; both tracked artifacts regenerated
clean before any change; A0/A1 foundation baseline 34/34; full-suite baseline **measured
live** at this HEAD: **3379 passed / 2 skipped / 1130 subtests / 0 failed** (14:40).

### 3. Final code HEAD

`e5bf452`. (The commit adding this handover follows it; no code or artifacts change after
`e5bf452`.)

### 4. Commit list

| Commit | Content |
|---|---|
| `358fe8f` | licence policy + SPDX gate + canonical texts + corresponding-source archives + `.gitattributes` binary rule |
| `df43487` | notices generator + generated `THIRD-PARTY-NOTICES.txt` |
| `fd08bcc` | CI interlock + `MANIFEST.in` carriage + `license-expression` declared in dev extra + regenerated manifest |
| `265c436` | README + strategy-doc reconciliation + ZIP removal from HEAD |
| `e5bf452` | the 78-test licensing compliance matrix |

Each commit is independently green by construction: the gate ships with the policy and
archives it checks; the notices ship with their generator; the pyproject dev-extra change
ships with the manifest it regenerates.

### 5. Working-tree state

Clean apart from the five untracked review documents (the four pre-existing ones plus this
handover before its commit). **Local commits ahead of `origin/main`: 5** (6 with this
handover). Nothing pushed. No dev server was started at any point in this task.

### 6. Files added

`compliance/license-policy.json` · `compliance/vendored-assets.json` ·
`compliance/licenses/{Apache-2.0,BSD-3-Clause,LGPL-2.1,LLVM-exception,MIT,MPL-2.0,Unicode-3.0}.txt` ·
`compliance/third-party-source/{paramiko-4.0.0,scp-0.15.0,fqdn-1.5.1}.tar.gz` ·
`scripts/check_licenses.py` · `scripts/generate_third_party_notices.py` ·
`THIRD-PARTY-NOTICES.txt` (generated, tracked) · `tests/test_licensing_compliance.py`.

### 7. Files modified

`.gitattributes` (binary override for the source archives) · `.github/workflows/security.yml`
(gate + notices + widened diff) · `MANIFEST.in` (`include THIRD-PARTY-NOTICES.txt` + updated
comment) · `pyproject.toml` (dev extra only: `license-expression>=30,<31`) ·
`compliance/runtime-manifest.json` (regenerated; one line — `license-expression`
`direct: false→true` in the dev section) · `README.md` (§License) ·
`docs/strategy/PRODUCT_REVIEW_ZERO.md` (non-authoritative marker on the licensing section).
`sbom.cdx.json` regenerated with **zero** byte change (the runtime closure is untouched).

### 8. Files removed

`pr-046-cortex.zip` and `_zip/pr-046-cortex.zip` — `git rm --cached` at HEAD (§35).

### 9. Runtime dependency counts

Unchanged by A2a, reverified from the regenerated manifest: **60** runtime union
(58 win32 / 58 linux / 56 darwin), 55 lock-pinned, 5 honest not-locked leaves, 26 dev-only,
1 unassigned (`setuptools`). The dev extra addition changed no closure membership.

### 10. RED / AMBER / UNKNOWN / GREEN state

| Band | Count | Detail |
|---|---:|---|
| RED (GPL/AGPL) | **0** | reverified across every declared surface of all 60 members; now also structurally impossible under the gate (§12) |
| AMBER (reviewed weak-copyleft) | **3** | paramiko LGPL-2.1-only · scp LGPL-2.1-or-later · fqdn MPL-2.0 — all with recorded treatment, texts and corresponding source |
| Evidence exceptions | 4 | pyserial, isoduration, rfc3987-syntax, fqdn-sdist gap — all explicit, none silent |
| GREEN | remainder | concluded and evidence-recorded per component |

### 11. Licence-policy architecture

`compliance/license-policy.json` (schema_version 1.0): `spdx` (allowed families / allowed
exceptions / reviewed weak-copyleft / forbidden runtime families, matched as **parsed SPDX
symbols, never substrings**) · `components` (a reviewed conclusion + evidence basis for every
one of the 60 members) · `reviewed_components` (the AMBER three: version + licence + mechanism
+ evidence + canonical text + source archive + sha256 + provenance + attribution) ·
`elections` (7) · `conjunctions` (3) · `evidence_exceptions` (4) · `nested_resolutions` (5) ·
`canonical_texts` (7) · `not_locked_leaves` (5) · `a2b_requirements` · `prb_distribution_contract`.
Vocabulary note: the mandate's PERMISSIVE/REVIEWED/FORBIDDEN/UNRESOLVED categories map to
`allowed_families` / `reviewed_weak_copyleft` / `forbidden_runtime_families` / gate-reported
`unresolved` respectively — explicit classification is the behaviour, as instructed.

### 12. SPDX implementation

`scripts/check_licenses.py` parses every expression with `license-expression` 30.4.4
(dev-only; now a declared dev root). Semantics, all test-pinned: **OR requires a recorded
election** and is never treated as AND; **AND preserves every obligation** — `MIT AND
GPL-2.0-only` fails despite the permissive arm; **WITH carries the exception** and unknown
exceptions fail; parentheses are honoured via real boolean algebra — an election is valid iff
`(elected AND original).simplify() == elected.simplify()`, so a conjunctive arm can never be
elected away; unparseable or unknown symbols are **unresolved → fail**, never pass. The
measured trap passes correctly: `Apache-2.0 OR GPL-2.0-only` (cryptography's `self_cell`)
passes **only** because the Apache-2.0 arm is elected on the record — with the election
removed, the gate fails (test-pinned).

### 13. Original-expression vs election handling

Elections are separate records: each carries the original `expression`, the `elected` arm, a
rationale, and the exact component instances (name + version + within) it covers. The notices
print the original expression *and* the election
(`self_cell 1.2.2 — Apache-2.0 OR GPL-2.0-only [elected: Apache-2.0 per ELECT-SELF-CELL]`).
No GPL text was deleted from any evidence. Test-pinned: every election's `expression` differs
from its `elected`.

### 14. pyserial treatment

Metadata declares bare `BSD`; the distribution ships **no licence file** (manifest observation
`no-license-file-shipped`). **New evidence found during implementation: 25 in-package source
files carry `SPDX-License-Identifier: BSD-3-Clause` headers** — the variant question is
resolved by pyserial's own source. Recorded as `EXC-PYSERIAL` (concluded BSD-3-Clause,
attribution Chris Liechti, canonical text supplied, legal sign-off noted). The gate fails if
pyserial ever starts shipping licence evidence (stale-exception check, test-pinned).

### 15. isoduration treatment

Metadata is literal `UNKNOWN`; the bundled dist-info text is ISC and the classifier agrees.
`EXC-ISODURATION`: bundled text authoritative over the metadata field. The gate fails if
either observation disappears. Test-pinned.

### 16. rfc3987-syntax treatment

`License-Expression: MIT` + bundled MIT text vs a stale `Apache Software License` classifier.
`EXC-RFC3987-SYNTAX`: concluded MIT from the two agreeing surfaces; the discrepancy is
recorded, not hidden, and does **not** fail the build (two permissive surfaces disagreeing is
not a defect); the gate fails as *stale* if the classifier is ever fixed upstream. Test-pinned.

### 17. Nested / static / native graph

Unit of accounting: the distributed component. All six classes live: plain distributions;
nested in-package texts (netmiko `_telnetlib` PSF-2.0 — a live obligation today; werkzeug
Silk icons); static linkage (both cryptography SBOMs + rpds-py's SBOM); vendored JS bundles;
short-notice-only packages (scp 727 B, ntc_templates 601 B — canonical full text supplied and
the notice says so); the packaging-time class as an explicit NOT POPULATED placeholder.

### 18. Cryptography / OpenSSL findings

Both bundled SBOMs are read — the design reads **every** `dist-info/sboms/*.json`, never "the
first". OpenSSL **4.0.1** (statically linked, `no-shared` build flags, sha256 recorded in the
SBOM) carries **no licence field** in its SBOM entry; resolved as `NEST-OPENSSL` →
Apache-2.0, verified against the upstream `openssl-4.0.1` tag's `LICENSE.txt` during
implementation. Removing the resolution fails the gate (test-pinned). The Rust `openssl`
0.10.81 bindings crate is represented separately from the C library.

### 19. Rust crate findings

39 crates (cryptography) + 17 (rpds-py), every one in the notices with version and
expression: 37 instances under the MIT elections, 7 under Apache-OR-BSD (elected Apache-2.0
for consistency with the parent), `self_cell` under its own election, `target-lexicon` with
the LLVM-exception carried, `unicode-ident` with the Unicode-3.0 conjunction preserved and
its canonical text in the appendix.

### 20. PyNaCl / libsodium findings

The doubly-nested `licenses/licenses/LICENSE.libsodium.txt` (ISC) is preserved un-flattened,
recorded as `NEST-LIBSODIUM`, and appears in the notices with its evidence path.

### 21. Vendored frontend findings

`compliance/vendored-assets.json` records all six files under `static/vendor/`: Cytoscape.js
**3.29.2** (version recoverable and pinned), xterm.js/xterm.css (**version not determinable —
stated, not invented**), xterm-addon-fit (no adjacent licence file; covered by the xterm.js
monorepo MIT text, recorded explicitly). A vendored file with no evidence entry fails the
gate (test-pinned). **No font files ship and no `@font-face` exists** (test-pinned).

### 22–25. Paramiko / SCP LGPL mechanism and corresponding source

**Mechanism (both):** LGPL-2.1 §6(a) — complete corresponding source stored in-repo and
shipped beside any distribution, plus §6(d) at the distribution location; components stay
separately identifiable, replaceable pure-Python packages. The wording of the licence-side
affirmative permission is **A2b's** (`A2B-REQ-1`) — deliberately NOT written into LICENSE
here (§37).

| | paramiko | scp |
|---|---|---|
| Version pinned | 4.0.0 | 0.15.0 |
| Licence | LGPL-2.1-only (declared in the deprecated bare form) | LGPL-2.1-or-later |
| Shipped text | full 504-line LGPL-2.1 | 727-byte short notice → canonical full text supplied |
| Archive | `paramiko-4.0.0.tar.gz`, sha256 `6a25f07b…d69f` | `scp-0.15.0.tar.gz`, sha256 `f1b22e99…83f` |
| Provenance | PyPI sdist via `pip download --no-deps --no-binary :all:` | same |
| Atlas modifies | **no** (test: no import, no vendored copy) | **no** |
| Necessity | direct SSH dependency | **remeasured live**: `import netmiko` → `'scp' in sys.modules` is True; unconditional top-level chain `netmiko/__init__.py:46 → scp_handler.py:16` — test-pinned |

The paramiko policy pin and `security/vulnerability-exceptions.json` (expires **2026-10-18**)
are cross-checked by the gate: a version bump that touches one file but not the other fails.

### 26–27. FQDN MPL mechanism and corresponding source

MPL-2.0 §3.1/§3.2(a): Source Code Form availability. fqdn 1.5.1 pinned; full 373-line MPL-2.0
canonical text stored; `fqdn-1.5.1.tar.gz` (sha256 `105ed367…89f`) stored — with one measured
oddity recorded as `EXC-FQDN-SDIST-NO-LICENCE-FILE`: **the upstream sdist itself ships no
licence file** (a packaging gap in fqdn 1.5.1); the MPL text is evidenced by the installed
wheel's dist-info. Atlas modifies no MPL-covered file (no import, no vendored copy, no
monkeypatching — measured), so exact upstream source satisfies the obligation and **no
Atlas-owned source becomes MPL-covered by distribution** — an engineering fact about file-level
scope, not a broader legal claim. PR-B requirement `PRB-REQ-3`: ship fqdn in Source Code Form
(unfrozen `.py`), which satisfies §3.2(a) by construction.

### 28. THIRD-PARTY-NOTICES architecture

Four sections + appendix: (1) the 55 locked runtime members, PEP 503-sorted, each with
concluded licence, declared-vs-concluded note, election/exception references, weak-copyleft
treatment blocks, shipped texts inline (deduplicated against canonical texts by byte
equality — paramiko's LGPL and fqdn's MPL reference the appendix instead of printing 26 KB
twice), and per-member nested/SBOM blocks; (2) vendored assets with honest versions;
(3) the five not-locked leaves **declared rather than omitted**; (4) the NOT POPULATED
packaging placeholder; appendix of the seven canonical texts. Readable prose, not a JSON dump.

### 29. Notice determinism results

| Check | Result |
|---|---|
| Two consecutive generations | byte-identical (live + test-pinned) |
| Tracked vs regenerated | byte-identical (test = the CI interlock in one assert) |
| Fresh `core.autocrlf=true` clone at `e5bf452` | **all three artifacts** (manifest, SBOM, notices) regenerate byte-identical; gate passes inside the clone |
| CR bytes | 0; trailing LF present |
| Clock/timestamps | none — the generator imports no clock (test-pinned) |
| Falsified tracked notices (live attack) | regeneration restores truthful bytes; `git diff` catches the mutation |

### 30. Ambient-venv attack result

The venv contains **91** distributions; the runtime closure is 60; a naive site-packages scan
would leak 36 non-runtime distributions including `pillow` (whose own SBOM declares a
GPL-3.0-or-later `libimagequant`). The notices universe is parsed from the generated file and
asserted equal to the locked closure — `pillow`, `cairosvg`, `build`, `pytest`, `pip-audit`
appear nowhere (test-pinned). No simulated install was needed: the contaminated environment
**already exists** and is excluded by construction.

### 31. Root-LICENSE collision result

netmiko and ntc_templates both record `rejected_root_paths` in the manifest; every attributed
evidence path contains a directory separator; the generator renders no root-level path
(test-pinned). The affirmatively-wrong-notice failure mode of the original review remains
structurally impossible.

### 32. CI interlock

`security.yml`: `check_licenses.py` runs **before** notices regeneration (a policy violation
reports as itself, not as a diff), then
`git diff --exit-code -- sbom.cdx.json compliance/runtime-manifest.json THIRD-PARTY-NOTICES.txt`.
A clean checkout with the locked environment verifies manifest, SBOM, policy/evidence,
notices and source material with no developer-machine state. Vulnerability auditing is
untouched — `audit_dependencies.py` keeps its deliberate whole-lock scope.

### 33. MANIFEST.in changes

`include THIRD-PARTY-NOTICES.txt` (A2a sets no `license-files`; nothing else would carry it)
plus an updated comment. The pre-existing `graft compliance` already carries the licences and
archives; `global-exclude *.zip` still stands, which is exactly why the archives are `.tar.gz`.

### 34. sdist audit

Built the real sdist in-process (also a permanent test): notices (260 KB, non-empty) +
policy + vendored-assets + manifest + 7 canonical texts + **3 `.tar.gz` archives** all
travel; **no** `*.zip`, `tests/`, `.atlas/`, `configs/`, `enterprise-memory/`,
`deliverables/`. 604 entries.

### 35. ZIP removal result

Reconfirmed before acting: both files are the identical 15,125-byte blob (`1901be35…`), and
the only tracked mention is a `.gitignore` comment. Removed from HEAD with `git rm --cached`;
the on-disk copies fall under the existing `*.zip` ignore rule. **Removal from current HEAD
does not erase historical Git copies — history was deliberately not rewritten**, and the
distribution boundary remains PR-B's packaging allow-list. `git ls-files '*.zip'` is empty
(test-pinned, git-guarded).

### 36. README / strategy reconciliation

README §License states: compliance surface established; Atlas-owned terms pending A2b;
**external beta distribution not authorized**. No "commercially released", "production
ready" or "generally available" anywhere (test-pinned). PRODUCT_REVIEW_ZERO's open-core /
Apache-2.0 section carries a dated historical/non-authoritative marker pointing at LICENSE
and the PR-A2 review, positioned **before** the open-core sentence (test-pinned). The
`inbox.html` "Open source" UI button — the known substring false positive — is deliberately
untouched and pinned as such.

### 37. A2b non-prejudgment proof

Hard gate, all test-pinned: LICENSE still begins `LICENSE NOT YET SELECTED`, contains no
effective date and no owner name; pyproject has **no** `license`, `license-files` or
`authors` key and no `LicenseRef-` anywhere; the Atlas-authored compliance surfaces contain
no grant language, governing law, arbitration, NDA, effective date, telemetry or
activation/key language (word-bounded patterns, scoped to generator-authored text because
third-party licence texts legitimately contain phrases like MPL's "Effective Date");
the policy's `a2b_requirements` records A2b as **NOT IMPLEMENTED** with the LGPL
affirmative-permission requirement (`A2B-REQ-1`) machine-readable and test-asserted.
The full A2a diff was also scanned adversarially (§40, attacks 30–38).

### 38. Focused test counts

`tests/test_licensing_compliance.py`: **78 passed**. With the A0/A1 foundation file:
**112 passed** (34 + 78), zero failures. The licence gate run inside the tests and live:
60 members / 7 elections / 4 exceptions / 3 reviewed components, zero problems.

### 39. Full-suite counts

Baseline at `4d97e50` (measured live this task): **3379 passed / 2 skipped / 1130 subtests /
0 failed** (14:40). Final at `e5bf452` (measured live, full run): **3457 passed / 2 skipped /
1130 subtests / 0 failed** (13:00) — the baseline plus exactly the 78 new licensing tests, no
regressions. The single warning is the pre-existing, deliberate duplicate-member zipfile test
in `test_persistence_safety.py`, unrelated.

### 40. Adversarial results — 38 of 38 fail (attacks defeated)

1–2 GPL/AGPL runtime injection → gate fails (test-pinned) · 3 `Apache-2.0 OR GPL-2.0-only`
injection → fails without an election, passes only with one (test) · 4 `MIT AND GPL-2.0-only`
→ fails, AND preserved (test) · 5 election removal → fails (test) · 6 nested SBOM removed →
fails (test) · 7 process-only-one-SBOM design → impossible: OpenSSL lives in the second SBOM
and is asserted present (test) · 8 OpenSSL evidence removed → fails (test) · 9 crate
attribution removed → CI diff + election coverage fails · 10 unrelated Pillow → **already
installed**, excluded by construction (live + test) · 11 dev-only licence-bearing packages →
certifi excluded (test) · 12 root-LICENSE collision → structurally impossible (test) ·
13–15 evidence-state changes for pyserial/isoduration/rfc3987-syntax → stale-exception
failures (tests) · 16–18 archive deletion → gate fails (live run recorded + tests) · 19 hash
skew → fails (test; clone gate re-verified real hashes) · 20 double generation → identical
(live + test) · 21 fresh clone → identical (live) · 22 `autocrlf=true` clone → identical, gate
green inside the clone (live) · 23 stale notices → caught; truthful bytes restored (live +
test) · 24–25 stale SBOM/manifest → A0 interlock unchanged and re-run (live in clone) ·
26 ambient certifi → excluded (test) · 27 ZIPs in sdist → excluded (test + live build) ·
28 `.atlas` in sdist → excluded (test + live) · 29 configs/private data → excluded (test +
live) · 30–38 diff-wide language scan for grant/governing-law/NDA/telemetry/AI-transmission/
effective-date/LicenseRef/PyInstaller/keys-DRM → **every hit reviewed and benign** (third-party
licence texts, the guard tests' own ban patterns, and descriptions of what was NOT done).

### 41. Deviations from architecture

1. **Commits 1 and 3 of the suggested six-way split were merged** (policy+gate+archives in
   one): the policy pins archive hashes, so separating them would create a non-green
   intermediate commit — the mandate prefers green commits over forced splits.
2. **`.gitattributes` binary override added** — a measured necessity the A2 review missed:
   `compliance/** text eol=lf` would have let git corrupt the `.tar.gz` bytes on checkout.
3. **`EXC-FQDN-SDIST-NO-LICENCE-FILE` added** — the upstream fqdn sdist ships no licence
   file; recorded rather than silently tolerated.
4. **pyserial's conclusion strengthened** by newly-found evidence (25 in-package SPDX
   headers), not just the canonical-text supply the review planned.
5. **Crate elections enumerate exact versions**, so a cryptography/rpds-py bump forces a
   re-review of the new SBOM contents rather than silently inheriting elections.
6. **Werkzeug's Silk icons** (CC-BY-2.5 OR CC-BY-3.0) gained an explicit election
   (`ELECT-SILK-ICONS` → CC-BY-3.0) — a real disjunction the review's §22 example set
   did not include.

### 42. Residual risks

- The five not-locked leaves remain unpinned and evidence-free (declared in notices §3 and
  policy); they must be resolved before any distribution that ships them (linux).
- The paramiko security exception expires **2026-10-18**; the netmiko-compatible paramiko 5
  upgrade will require updating both gates, the archive, and the canonical-text pin together
  (the gate enforces the coupling).
- Canonical-text dedupe is byte-equality; a distribution shipping a reformatted LGPL would
  inline rather than reference — cosmetic, not a correctness risk.
- `packaging`'s `licenses` module and `license-expression` are dev-tooling; a future major
  bump could change parse strictness — the lock pins both.

### 43. PR-B distribution requirements already established

Machine-readable in `prb_distribution_contract` and test-asserted: **PRB-REQ-1** paramiko/scp
remain separately identifiable, importable, replaceable pure-Python components (one-folder,
collected as plain `.py`; a frozen one-file layout is a compliance failure), with the
verification procedure spelled out (replace the component, prove the app uses the
replacement); **PRB-REQ-2** archives + notices copied beside the application; **PRB-REQ-3**
fqdn ships in Source Code Form; **PRB-REQ-4** CPython/PSF + PyInstaller bootloader notices
populated at packaging time (the notices file carries the NOT POPULATED section PR-B must
fill).

### 44. A2b requirements still outstanding

Machine-readable in `a2b_requirements`, status **NOT IMPLEMENTED**: **A2B-REQ-1** the Atlas
licence text must affirmatively permit modification for the tester's own use and reverse
engineering for debugging such modifications, to the extent third-party licences require
(LGPL-2.1 §6); **A2B-REQ-2** every Atlas-owned restriction textually scoped to Atlas-owned
material (LGPL §10, MPL §3.2(b)); **A2B-REQ-3** an owner-supplied effective date, no
shippable placeholder. Plus the owner/legal items from the PR-A2 review §37 (RE wording,
warranty, liability, authorised networks, tester-output exception, trademarks, third-party
services).

### 45. Ready to push?

**Yes.** All 48 mandated test-matrix items are covered, every adversarial attack fails, the
CI interlock reproduces from a fresh hostile-line-ending clone, the full suite is green with
zero failures, and nothing in the change prejudges A2b.

### 46. Recommended next action

On approval: push `main` through the handover commit to `origin/main`, then take **A2b to
the owner/legal decisions it is blocked on** (effective date; §6 affirmative-permission
wording; the §25 checklist) — the compliance machinery this stage built makes A2b a
text-drop plus metadata plus the placeholder-guard flip. Until approval: nothing; the tree
is clean and nothing has been pushed.

---

### Mandated explicit statements

1. **"PR-A2a did not modify the Atlas-owned LICENSE terms." — TRUE.** `LICENSE` is
   byte-identical to the pre-A2a state; it still begins `LICENSE NOT YET SELECTED`;
   test-pinned, and no commit in the list touches it.
2. **"PR-A2a does not grant permission to distribute Atlas." — TRUE.** No grant language
   exists in any Atlas-authored surface (diff-scanned, test-pinned); README states
   distribution is not authorized; the notices header states the file grants no rights in
   Atlas.
3. **"No Atlas-owned source disclosure obligation was introduced by PR-A2a." — TRUE.** The
   stored corresponding source is third-party source only (paramiko, scp, fqdn); LGPL §6
   requires the Library's source, not the application's; MPL-2.0 is file-level and Atlas
   modifies no covered file.
4. **"The current runtime closure contains no GPL or AGPL component requiring Atlas-owned
   source disclosure." — TRUE.** RED = 0 reverified across all 60 members and every nested
   SBOM; the only GPL symbol anywhere (`self_cell`'s unelected arm) sits in a disjunction
   whose Apache-2.0 arm is elected on the record.
5. **"Paramiko/SCP corresponding source material is tied to the exact distributed
   versions." — TRUE.** `paramiko-4.0.0.tar.gz` and `scp-0.15.0.tar.gz`, sha256-pinned in
   the policy, verified by the gate on every run, and the archives' top-level directories
   and members are test-asserted (`paramiko-4.0.0/paramiko/client.py`, `scp-0.15.0/scp.py`).
6. **"FQDN corresponding source/material is tied to the exact distributed version." —
   TRUE.** `fqdn-1.5.1.tar.gz`, sha256-pinned, contents test-asserted
   (`fqdn-1.5.1/fqdn/__init__.py`), with the upstream sdist's missing-licence-file gap
   recorded explicitly.
7. **"THIRD-PARTY-NOTICES is generated from the runtime compliance model rather than the
   ambient virtual environment." — TRUE.** The generator reads the manifest, policy and
   recorded evidence; the notices universe is test-asserted equal to the locked closure;
   36 ambient distributions including GPL-bearing `pillow` are excluded by construction.
8. **"PR-A2a did not perform Windows packaging." — TRUE.** No PyInstaller configuration, no
   spec files, no binaries, no signing; diff-scanned; the packaging section of the notices
   is an explicit NOT POPULATED placeholder.
9. **"PR-A2a did not add licence keys, activation, DRM, telemetry, or update delivery." —
   TRUE.** Diff-scanned with word-bounded patterns; every hit is a third-party licence text,
   a guard test's own pattern, or a description of what was not done.
10. **"PR-A2b remains required before external beta distribution is authorized." — TRUE.**
    Recorded in README, in the policy's `a2b_requirements` (status NOT IMPLEMENTED,
    test-asserted), and in this handover (§44).

---

*LICENSE unchanged. Nothing pushed. No dev servers running. Stage A2b not started.*
