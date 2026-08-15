# PR-A2b — Atlas Proprietary Controlled-Beta Licence
## Implementation Handover

**Status: implemented, validated, committed locally. NOT PUSHED — awaiting review.**

Stage A2b of the PR-A2 architecture review, implemented per §35 of the PR-A2b final review.
Atlas now has a licence. PR-B has not started.

---

### 1. Executive result

The placeholder is gone. `LICENSE` carries the approved proprietary controlled-beta terms —
verbatim from the reviewed §30 text, with only the owner's contact filled in — effective
15 August 2026, owned by Mohammed Mustafa Hussain as an individual. An invited tester now has
an actual grant; nobody else does. `A2B-REQ-1/2/3` are all satisfied and recorded as such.
**58 adversarial attacks defeated. Full suite 3512 / 2 skipped / 1130 subtests / 0 failed.**

### 2. Commits

| Commit | Content |
|---|---|
| `6d6f5d3` | `LICENSE` + PEP 639 metadata + README reconciliation + A2b policy state + six flipped guards + the new licence tests |
| *(this document)* | handover |

The first commit is deliberately atomic: the guards assert the pre-A2b state and fail the moment
`LICENSE` changes, so splitting them would produce a knowingly red intermediate commit.

### 3. Final HEAD

`6d6f5d3` at the time of writing; the handover commit follows it. No code, metadata or generated
artifact changes after `6d6f5d3`.

### 4. Files changed

**Modified (6):** `LICENSE` (448 B placeholder → 12,339 B licence) · `pyproject.toml`
(`[project]` metadata only) · `README.md` (§License first paragraph) ·
`compliance/license-policy.json` (`a2b_requirements` only) ·
`tests/test_compliance_foundation.py` (one guard) · `tests/test_licensing_compliance.py`
(five guards).

**Created (1):** `tests/test_atlas_license.py` — 55 tests.

**Regenerated:** `THIRD-PARTY-NOTICES.txt`, `compliance/runtime-manifest.json`, `sbom.cdx.json` —
all three **byte-identical** to their committed state (A2b changes no dependency and no
evidence), so none appears in the diff.

**Untouched, verified by `git diff --name-only`:** all of `src/` (**0 files**) ·
`constraints.txt` · `compliance/licenses/**` · `compliance/third-party-source/**` ·
`scripts/**` · `.github/**` · `MANIFEST.in` · `.gitattributes` · git history.

### 5. Final licence identity

| Field | Value |
|---|---|
| Title | FounderOS Atlas — Proprietary Controlled Beta Licence |
| Copyright line | `Copyright (c) 2026 Mohammed Mustafa Hussain. All rights reserved.` |
| SPDX identifier (in the text) | `SPDX-License-Identifier: LicenseRef-FounderOS-Atlas-Beta` |
| Effective date | **15 August 2026** — twice (header and §19), no other date form present |
| Licensor | Mohammed Mustafa Hussain, an individual |
| Contact | `mmhmustafa@gmail.com` — **exactly once** in `LICENSE`, plus `authors.email` |
| Shape | 19 sections, 303 lines, LF, no bracketed placeholder anywhere |

No company, no legal entity, no parentage — asserted across `LICENSE`, `pyproject.toml` and
`README.md`.

### 6. A2B-REQ status

| Requirement | Status | Discharged by |
|---|---|---|
| **A2B-REQ-1** — affirmative permission to modify for own use and reverse engineer to debug those modifications | **SATISFIED** | `LICENSE` §7: grants both with the "to the extent … requires" qualifier, overrides §§6(d), 6(e) and 8, is **not revocable for a copy already supplied**, and survives termination |
| **A2B-REQ-2** — every Atlas-owned restriction scoped, and no limit on third-party rights | **SATISFIED** | `LICENSE` §§2, 3, 6, 8, 15: all five restriction clauses name the Atlas-Owned Material, §3 gives third-party licences precedence, §15's deletion duty excludes Third-Party Components |
| **A2B-REQ-3** — owner-supplied effective date, no placeholder | **SATISFIED** | `LICENSE` header and §19: 15 August 2026 |

Recorded machine-readably in `compliance/license-policy.json`; `prb_distribution_contract`
remains `PR-B NOT STARTED`, untouched.

### 7. PEP 639 metadata actually emitted by a built artifact

Not asserted from the source — **read out of a real wheel built from this commit**:

```
Metadata-Version: 2.4
Author-email: Mohammed Mustafa Hussain <mmhmustafa@gmail.com>
License-Expression: LicenseRef-FounderOS-Atlas-Beta
License-File: LICENSE
License-File: THIRD-PARTY-NOTICES.txt
```

No licence classifier of any kind. Both files land under `dist-info/licenses/`:
`LICENSE` 12,339 bytes, `THIRD-PARTY-NOTICES.txt` 260,117 bytes. The expression canonicalises to
itself under `packaging.licenses` and is a `LicenseRef-`, not a standard SPDX identifier.

### 8. Third-party notices regeneration

Regenerated with the A2a mechanism in the implementation commit. **260,117 bytes, SHA-256
`1101560b…0be5`, byte-identical across consecutive runs and identical to the previously tracked
bytes** — expected, because A2b touches no dependency, no evidence and no policy input the
generator consumes. `git diff --exit-code` clean over all three generated artifacts, before and
after the commit. Nothing was hand-edited.

### 9. sdist contents

Built in an isolated temporary directory: 603 entries.

| Item | Result |
|---|---|
| `LICENSE` | present, **12,339 bytes** |
| `THIRD-PARTY-NOTICES.txt` | present, **260,117 bytes** |
| `compliance/license-policy.json` | present, 35,816 bytes |
| `compliance/third-party-source/*.tar.gz` | 3 archives |
| `*.zip` | **none** |
| `tests/` | **none** |

### 10. Runtime closure before / after

**Identical.** 60 runtime union (58 win32 / 58 linux / 56 darwin), 55 lock-pinned, 5 not-locked
leaves, 26 development-only, 1 unassigned. A2b changed no dependency; `constraints.txt` was not
touched and the runtime dependency list in `pyproject.toml` is unchanged.

### 11. RED / AMBER / UNKNOWN / GREEN

| Band | Count | Members |
|---|---:|---|
| **RED (GPL/AGPL)** | **0** | — |
| AMBER (reviewed weak-copyleft) | 3 | `fqdn` MPL-2.0 · `paramiko` LGPL-2.1-only · `scp` LGPL-2.1-or-later |
| Evidence exceptions | 4 | pyserial · isoduration · rfc3987-syntax · fqdn sdist gap |
| GREEN | remainder | unchanged from A2a |

### 12. GPL / AGPL result

**Zero.** Re-scanned across every declared surface of all 60 runtime members after the change.
The A2a gate — which enforces this structurally with a real SPDX parser — passes: 60 members,
7 elections, 4 evidence exceptions, 3 reviewed components.

### 13. Adversarial attacks and outcomes

**58 checks across 20 attack families, all defeated**, re-run against the committed state:

| Family | Outcome |
|---|---|
| A. Uninvited user receiving a grant | grant conditioned on invitation; uninvited expressly get nothing; exactly one operative granting verb |
| B. Atlas-Owned vs Third-Party scoping | all 5 restriction clauses name Atlas-Owned Material; deletion duty and access bar both scoped |
| C. Tester / client-network outputs | outputs cover networks run against "for someone else"; client sharing permitted; client engagement expressly not a service bureau |
| D. Reports embedding Atlas template/viewer code | definition covers it; §9 expressly permits sharing it |
| E/F. LGPL permissions vs termination | both permissions present; override 6(d)/6(e)/8; non-revocable for supplied copies; §7 survives; modified copy exempt from deletion |
| G. Termination deleting third-party components or outputs | both expressly exempt |
| H. Absolute RE prohibition reappearing | none; applicable-law boundary present |
| I. Notice preservation conflicting with §7 | 6(e) overridden, third-party notices still required intact |
| J. Source availability vs notices | licence routes through the Licensor; no overclaim about the notices file; notices still declare the no-evidence leaves |
| K. Feedback grabbing data | narrow to Atlas; no rights in data/outputs; no assignment language; data-stripping instruction present |
| L. External-AI clause as a permission | descriptive only, off by default, licensor not a party and receives nothing; no consent verb; no telemetry |
| M. NDA / indirect confidentiality | explicit no-NDA clause; no secrecy duty; criticism expressly allowed |
| N. Fictional entity / parentage | no company forms; no parentage in licence, metadata or README |
| O. False trademark registration | no ®, no registration claim |
| P. Licence key / DRM / phone-home / expiry | all five terms confined to §5's negative list; no DRM, no entitlement |
| Q. False standard SPDX identifier | LicenseRef in both places, canonicalises unchanged, no OSI classifier, not bare "Proprietary" |
| R. README contradicting the licence | states proprietary + controlled beta under LICENSE; stale claim gone; no release overclaim |
| S. Contact placeholder / email placement | no bracketed placeholder; email exactly once in LICENSE and once in metadata; absent from README, notices and policy |
| T. Policy state | A2b IMPLEMENTED, all three SATISFIED, PR-B contract untouched |

### 14. Full-suite counts and exact delta

| | Result |
|---|---|
| Baseline (approved review, at `a59bcd3`) | **3457** passed · 2 skipped · 1130 subtests · 0 failed |
| Final (at the implementation commit) | **3512** passed · 2 skipped · 1130 subtests · 0 failed (13:54) |
| **Delta** | **+55, all from `tests/test_atlas_license.py`** |

The delta is exactly the new file's test count — verified directly: the focused run of the three
compliance files returns 167 = 34 (foundation) + 78 (licensing compliance) + 55 (new). No
existing test was added or removed; the six flipped guards were rewritten in place, so they
contribute 0 to the delta. The single warning is the pre-existing duplicate-member zipfile
warning in `test_persistence_safety.py`, unrelated.

### 15. Deviations from the approved plan

**Two, both minor and both scope-preserving.**

1. **The licence text was extracted programmatically from §30 of the review rather than
   retyped**, with an assertion that the placeholder string was found before substitution. This
   was a deliberate choice to eliminate transcription drift; the committed text is the approved
   text byte-for-byte apart from the contact line.
2. **Six assertions in the new test file were rewritten during implementation** after they
   failed on first run. The failures were defects in *my tests*, not in the licence: they matched
   phrases against the hard-wrapped text and broke across line breaks. The fix was a `_flat()`
   whitespace-normalising helper so the assertions pin **meaning rather than line wrapping**, plus
   a clause-splitting rewrite of the restriction-scoping test so it reads whole clauses instead of
   physical lines. No licence wording was changed to make a test pass.

**No deviation from the approved licence text**, and no clause was redesigned. The professional-
review recommendations for §§7, 8, 9, 10, 13, 16 and 17 were left as recommendations.

### 16. Product source untouched

**Confirmed.** `git diff --name-only -- src/` returns **0 files** across the whole change. No
UI, no About page, no copyright line was added to any template — which also keeps LGPL-2.1 §6's
displayed-copyright conditional dormant, as §24 of the review required.

### 17. PR-B / packaging not started

**Confirmed.** No PyInstaller configuration, no spec file, no installer, no signing, no EXE, no
update mechanism, no licence keys, no activation, no DRM, no telemetry. Test-pinned:
`test_no_packaging_work_landed` asserts the absence of `*.spec`, `*.iss`, `*.nsi`, `*.wxs` and of
any packaging tool in `pyproject.toml`. `prb_distribution_contract` still reads
`PR-B NOT STARTED`.

### 18. Remaining legal-review recommendations

Unchanged by implementation, and none blocking:

| Clause | Item |
|---|---|
| `LICENSE` §7 | the LGPL affirmative permission and its interaction with §6 |
| §8 | reverse-engineering restriction |
| §9 | the tester-data / tester-output exception |
| §10 | authorised-network responsibility |
| §13 | trademark wording |
| §16 | warranty disclaimer |
| §17 | limitation of liability |

Plus the consequence of selecting **no governing law**: phrases like "to the extent permitted by
applicable law" resolve under whatever law a forum applies by default conflict-of-laws rules.
Engineering did not select one and will not.

**Engineering states no view on the enforceability of any clause in any jurisdiction.**

### 19. Ready to push?

**Yes.** The approved plan was followed, the two deviations are recorded above, all 58
adversarial checks are defeated, the closure and the generated artifacts are provably unchanged,
and the suite is green with the delta explained exactly.

### 20. Recommended next action

On approval: push `main` through the handover commit to `origin/main`. The repository's licensing
and third-party compliance work is then complete — A0 foundation, A1 GPL remedy, A2a compliance
surface, A2b licence — and **PR-B (Windows packaging) is unblocked**, inheriting the four
machine-readable requirements in `prb_distribution_contract` plus the rule that any new visible
ownership line must carry a visible third-party-notices reference. Until approval: nothing; the
tree is clean and nothing has been pushed.

---

*`src/` untouched. Dependencies unchanged. Nothing pushed. No dev servers running. PR-B not
started.*
