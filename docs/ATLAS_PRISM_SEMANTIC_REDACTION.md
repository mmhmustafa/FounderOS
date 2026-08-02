# PRISM Semantic Redaction — preserve meaning, protect identity (PR-166.2)

Blind redaction protects an identifier by destroying it:

> Atlas found no BGP peering between `[redacted:hostname-2]` and `[redacted:hostname-1]`.

Secure, and useless. The operator cannot tell which devices are being discussed, so the explanation
they asked for tells them nothing. **Semantic redaction** replaces the identifier with a *meaningful
alias* built from metadata Atlas already holds:

> Atlas found no BGP peering between the **Mumbai Core Router** and the **Hyderabad Border Firewall**.

Same protection. The provider still never learns a hostname.

## The three views of one answer

The heart of this change is that **three different things are no longer the same thing**:

```
┌────────────────────────┐
│  ATLAS EVIDENCE        │  chennai-regional-core, 172.20.20.54,
│  (stored, unchanged)   │  snmp community S3cr3tValue, site chennai
└───────────┬────────────┘
            │  Semantic Redaction Engine
            │  · mandatory tier: credentials, keys, tokens → REMOVED (always)
            │  · alias book: hostnames → descriptive aliases Atlas can justify
            │  · per-field policy: preserve / alias / mask / remove
            ▼
┌────────────────────────┐
│  AI PROVIDER PAYLOAD   │  "BGP between Chennai Core Router and Chennai Edge
│  (leaves Atlas)        │   Router is down. Management [redacted:ip-1].
└───────────┬────────────┘   snmp-server community [redacted:snmp-community-1]"
            │  provider generates prose about the aliases
            ▼
┌────────────────────────┐
│  PRISM EXPLANATION     │  "the Chennai Core Router is reporting trouble…"
│  (alias text)          │
└───────────┬────────────┘
            │  Operator presentation — RBAC-gated, server-side alias map
            ▼
┌────────────────────────┐
│  ATLAS OPERATOR VIEW   │  the Chennai Core Router (hostname protected during
│  (never leaves Atlas)  │  AI processing) ── links to /devices/ent:chennai-…
└────────────────────────┘
```

The alias map is a **server-side artifact**. It is never sent to a provider, never written to the
usage ledger, and never included in an API response body except as the RBAC allows.

## Part 1 — Aliases are built, never invented

`prism/semantic.py` assembles an alias from three things Atlas already knows:

| Component | Source | Example |
|---|---|---|
| Site | the device's **assigned site**; failing that, the location in its own hostname (labelled as the weaker basis) | `chennai` |
| Role | a role word present in the device's **own hostname** | `core`, `edge`, `border`, `dist`, `access`, `spine`, `leaf`, … |
| Device kind | **Atlas's own role classifier** (`platforms/classify.py`), which is deterministic and evidence-based | `Router` from *"router platform model 'ISR4451'"* |

Every alias carries the **basis** it was built from, and the Playground and the transparency panel
show it:

```
chennai-regional-core → "Chennai Core Router"
  built from: assigned site, role word in the hostname, FRRouting routing platform
```

Atlas's role classifier is preferred over anything read out of a name, because it is evidence.
Its own rule — *"Hostnames are never evidence"* — is why the device **kind** comes from the platform
and the device **role word** is labelled separately as a hostname reading.

### When Atlas knows nothing

An alias is never padded out with a plausible role:

```
zz11 → "Device 4"          basis: (none)
```

and the transparency record says why: *"Atlas held no descriptive metadata for this object, so a
generic alias was used rather than inventing one."*

**No alias is ever minted for a name Atlas has not discovered.** There would be no metadata to build
one from, so such a value falls through to the ordinary masking rules.

## Part 2 — Consistency is mandatory

Within one explanation, one device has exactly one alias, and no two devices share one:

- Repeated references collapse to the same alias — *"Check the Mumbai Core Router… then the Mumbai
  Core Router again"* is the same machine, and the model can reason about it as such.
- Two devices that would describe identically are disambiguated: `Mumbai Core Router` and
  `Mumbai Core Router 2`. **Device A never becomes Device C.**
- The alias book is shared across every variable in one call, so the finding, the confidence and the
  limitations all name the same device the same way.
- An inserted alias is **protected from later rules**. Without that, aliasing `mumbai-core-01` to
  "Mumbai Core Router" and then applying the site rule for `mumbai` produced
  `[redacted:hostname-2] Core Router`.

## Part 3 / 7 — Privacy profiles and the per-field policy

Three profiles, each an action per field. Actions: **Preserve** · **Semantic alias** · **Mask** ·
**Remove**.

| Field | Internal | Cloud (default) | High security |
|---|---|---|---|
| Hostnames | Preserve | **Alias** | **Alias** |
| Device names | Preserve | **Alias** | **Alias** |
| Site names | Preserve | Preserve | **Alias** |
| IP addresses | Preserve | Mask | **Alias** |
| MAC addresses | Preserve | Mask | **Alias** |
| VRFs | Preserve | **Alias** | **Alias** |
| VLANs | Preserve | Preserve | **Alias** |
| Usernames | Mask | Remove | **Alias** |
| Application names | Preserve | Preserve | **Alias** |
| Serial numbers | Mask | Remove | Remove |
| Platform names | Preserve | Preserve | **Alias** |
| **Credentials, keys, tokens, SNMP communities** | **Removed** | **Removed** | **Removed** |

The last row has **no setting**. Secrets are not a governed field: there is no profile, no override
and no form control that can preserve one. That is structural, not a default.

### Mask and Remove are genuinely different

- **Mask** emits a *stable, numbered* placeholder: `10.20.30.40` is `[redacted:ip-1]` every time it
  appears, so the model can still reason about "the same device" without learning its address.
- **Remove** emits an *unnumbered* token: every username becomes `[removed:username]`, so two
  different users and a repeated mention are indistinguishable.

A policy that says "Remove" and then emits `[redacted:username-1]` twice has not removed the user —
it has pseudonymised them. Under Cloud, `Contact user: dpatel and user: rmehta about user: dpatel`
becomes three identical `[removed:username]` tokens, and the audit counts three removals, not three
masks.

Administrators can override any field individually (Administration → PRISM → Privacy profile). An
override that matches the chosen profile's own action is not stored, so switching profiles is never
silently undone by a stale override.

### Site names under High security

A site's only metadata *is* its name, so there is nothing to build a *different* meaningful alias
from. High security gives it a positional alias — `Site 1` — and the **device** aliases quote that
rather than the real name:

```
mumbai              → "Site 1"
edge-mumbai-core-01 → "Site 1 Core Router"
```

The relationship survives (two devices at Site 1 are co-located) without disclosing where that is.
Without this, a device alias of "Mumbai Core Router" would have leaked the very site name the
profile had just protected.

## Parts 8 and 9 — Local and cloud

Cloud providers default to semantic aliasing. A local model **may** preserve hostnames — and that is
an administrator's explicit choice, not something Atlas infers:

> **The default is the stronger profile, even for a local provider.** A "local" endpoint may be a
> proxy to a cloud model, or a service shared beyond this team. Choosing Internal, or choosing
> *"Match the provider"*, is a decision an administrator makes and can be held to.

Under every profile, including Internal, passwords, private keys, SNMP communities and API keys are
removed before anything leaves Atlas.

## Part 5 — What the operator is told

Before asking for an explanation, the Advisor panel states the profile in force and what it does.
After, it states what actually happened:

> Privacy profile "Cloud (default)": 2 name(s) replaced by a descriptive alias; 1 value(s) masked;
> 1 value(s) removed. Aliases exist only for AI processing — Atlas holds the original evidence
> unchanged.

## Part 5.1 — The authorised operator's view

The provider received bare alias text. The operator reads the same words, annotated and linked:

> In plain terms: the [**Chennai Core Router**](#) (hostname protected during AI processing) is
> reporting trouble. Its session with the [**Chennai Edge Router**](#) (hostname protected during AI
> processing) keeps dropping.

- The alias links to the real Atlas object — `/devices/ent:chennai-regional-core:172.20.20.54`.
- The annotation appears on the **first mention only**; later mentions keep the link, the styling and
  a tooltip. Repeating the parenthetical after every occurrence buried the sentence it explained.
- Segments are built as **DOM nodes, never innerHTML**, so a model's output can never become markup.

### The RBAC, stated exactly

The presentation layer **never decides** who may see what. The route computes two flags from the
authenticated principal's existing permissions and the presentation layer only honours them:

| Flag | Permission | Effect |
|---|---|---|
| `can_view` | `PAGES_VIEW` — what the device page itself requires | the alias becomes a link |
| `can_reveal` | `EVIDENCE_VIEW` | the original name appears in the tooltip and the legend |

- Without `can_view`, the alias renders as plain emphasis with **no href**. The page must never imply
  a destination the RBAC would refuse.
- Without `can_reveal`, the original name is **absent from the payload entirely** — not hidden by
  CSS, not present-but-unrendered. `PresentedSegment.to_dict()` omits the key.
- An unauthenticated principal gets neither.

This can never widen access: both flags name permissions the user would need anyway to read the same
value on the page it came from.

### An alias Atlas never issued is never linked

Matching is against the alias book, not against text that *looks* like an alias. A model that invents
"the Kolkata Spine Router" produces no link and no claim of identity.

Only the aliases that **actually appeared in the outgoing text** are used for matching — an alias the
provider never received cannot be in its answer, so matching against the whole estate would only
create opportunities to mislabel.

## Part 5.2 — "Why was this protected?"

Every alias carries a transparency record:

| Field | Example |
|---|---|
| Privacy profile | Cloud (default) |
| Redaction rule applied | Hostnames → Semantic alias |
| Original object type | device |
| Built from | assigned site, role word in the hostname, router platform model 'ISR4451' |
| Does Atlas still hold the original? | Yes — *"redaction applies to the copy sent for explanation, never to the record"* |
| Did the provider receive it? | *"The provider received the alias only — never the original value."* |

The record itself **never contains the original value**. It explains the protection; it is not a back
door around it. The original is added separately by a caller that has checked `can_reveal`.

## Part 6 — The Playground shows all four stages

Administration → PRISM Playground now renders, in order:

1. **Original evidence** — untouched.
2. **Semantic alias preview** — every alias minted, its rule, and the metadata it came from.
3. **Data sent to the provider** — the exact payload.
4. **Generated explanation** — as an authorised operator sees it, links and all.

Verified on the lab estate:

| Stage | Content |
|---|---|
| 1 | `BGP between chennai-regional-core and chennai-regional-edge is down. Management 172.20.20.54. snmp-server community S3cr3tValue.` |
| 2 | `chennai-regional-core → Chennai Core Router` · Hostnames → Semantic alias · *assigned site, role word in the hostname, FRRouting routing platform* |
| 3 | `BGP between Chennai Core Router and Chennai Edge Router is down. Management [redacted:ip-1]. snmp-server community [redacted:snmp-community-1]` |
| 4 | the Chennai Core Router (hostname protected during AI processing) → `/devices/ent:chennai-regional-core:172.20.20.54` |

## Part 10 — The audit record

Each usage record now carries the privacy posture and how much it changed:

```json
{"privacy_profile": "cloud", "semantic_alias_count": 2,
 "masked_field_count": 1, "removed_field_count": 1,
 "redaction_rules": ["hostnames", "ip-addresses", "mac-addresses", "usernames"]}
```

**Counts only.** A removed secret is never recorded — not its value, not its label position. An audit
trail is not a place to store what was removed.

## Migration: an upgrade never changes a privacy posture

| Stored document | Result |
|---|---|
| has an explicit `privacy_profile` | that profile |
| has `redaction_rules` but no profile (pre-PR-166.2) | **its own rules stay in force**, rendered as the equivalent per-field policy under the label *"Custom (rules configured before profiles)"* |
| has neither (new install) | Cloud |

Blind masking *is* accurately describable as per-field "Mask", so an existing configuration is shown
truthfully rather than being upgraded to a posture nobody chose.

## Invariants worth stating outright

These are enforced in code and pinned by tests, because each was violated at least once during
development:

1. **An alias never contains the value it protects.** A device whose hostname is also its site name
   built the alias "Mumbai Router" out of the site — disclosing the hostname it was replacing. When
   "protect this hostname" and "preserve that site name" collide, protection wins and the alias goes
   generic.
2. **Protection beats preservation on a shared key.** One value can be both a site and a hostname.
   The entry that protects it replaces the one that preserves it — never the other way round.
3. **Every pass gets the same alias book.** A second redaction pass without it re-reads its own
   output.
4. **A book belongs to the profile that will use it.** Under an Internal book every entry is
   Preserve, so `known_names_for()` correctly returns *nothing* — hand that to a Cloud service and it
   has no known names left at all.
5. **A removed value has no identity to link to.** Removals are deliberately identical, so they are
   never presented as a named object; nor is any alias claimed by more than one original.

## Defects this work found

The Cloud profile promises site names are preserved. They were not: the Advisor route hands PRISM
every name Atlas knows — device hostnames, **site names** and contribution profile names — and the
generic hostname rule masked all of them, so the real payload read `site: [redacted:hostname-2]`.

`semantic.known_names_for()` now reconciles the caller's list with the alias book: a name the profile
preserves is dropped from it, and everything the book protects is added as a safety net. Pinned by a
regression test, and confirmed against the live payload — `site: chennai` now survives under Cloud
and becomes `site: Site 1` under High security.

### …and six more, from an adversarial audit of this PR

Four independent reviewers (leak paths, RBAC, alias correctness, configuration/migration) raised 28
claims; 19 were refuted on the code and 9 survived, of which 3 were the same root cause. All were
reproduced before being fixed:

| # | Defect | Effect |
|---|---|---|
| 1 | The **translation** capability made a second provider call without the alias book | `"the Mumbai Core Router at site Mumbai"` came back as `"the [redacted:hostname-1] Core Router at site [redacted:hostname-1]"` — alias broken, preserved site masked, and two distinct objects collapsed onto one placeholder |
| 2 | Playground **compare-two** shared one book across both sides | Under *match the provider*, a cloud side B ran with an Internal book, `known_names_for()` correctly returned nothing, and bare hostnames went out **in the clear** |
| 3 | A device whose **hostname is also its site name** was swallowed by the site entry | The real hostname was sent verbatim — and then dropped from the generic rules as "preserved". A regression against the blind redaction this replaced |
| 4 | **Removed** values share one token, and presentation attributed them | Disclosed the *wrong* device's real hostname to the operator |
| 5 | Choosing a **different privacy profile** in settings was silently cancelled | The per-field radios, rendered from the old profile, were stored as overrides against the new one — so the primary privacy control did nothing |
| 6 | The read-only settings view read the **vestigial rule list** | Overstated protection to exactly the operators who cannot change it |

Defect 5 also applies when the *provider* changes under "match the provider", so the form records the
**resolved** profile it rendered and discards the radios whenever the save lands on a different one.

## Deliberate limitations

- **A translated explanation carries no links.** Translation is a separate PRISM capability applied
  to text that already contains aliases; a translated alias no longer matches the book. The
  explanation is shown without links rather than linking the wrong device.
- **The mandatory tier still consumes trailing punctuation.** `community S3cr3tValue.` redacts the
  full stop with the value. That is deliberate: a password could genuinely end in `.`, and leaking one
  character of a secret to improve typography is the wrong trade. (The *username* rule was fixed the
  other way — a name is not punctuation, and `Contact user: dpatel. Then escalate.` was coming back
  as one welded sentence.)
- **Contribution profile names are masked, not preserved**, even under Cloud where site names
  survive. They are Atlas-internal labels and carry no operational meaning, and they are often the
  customer's own business-unit name.
- **VRFs, VLANs, applications, serials and platforms are governed but not pattern-matched.** Their
  policy applies through the alias book; there is no generic regex that can find a VRF name in free
  prose, and Atlas will not guess at one.
- **Aliases are per-request, not persisted.** "Mumbai Core Router" is stable within one explanation,
  not across sessions — a stored conversation shows the alias it was generated with.

## Where the code lives

| Module | Responsibility |
|---|---|
| `prism/semantic.py` | fields, actions, the three profiles, alias construction, `AliasBook`, `known_names_for()` |
| `prism/redaction.py` | the alias-aware pass (`redact(..., aliases=book)`); the mandatory tier, unchanged |
| `prism/presentation.py` | operator segments, the transparency record, the alias legend, RBAC honouring |
| `prism/config.py` | `privacy_profile`, `field_overrides`, `active_profile()`, legacy migration |
| `prism/service.py` | one policy, one book, one report per call; audit counts |
| `advisor/explanation.py` | `explain(..., aliases=, can_view=, can_reveal=)` and the presented segments |
| `web/routes.py` | `_alias_book()`, `_alias_visibility()`, the settings form, the Playground stages |

`redact()` without an alias book behaves exactly as it did before this PR — the change is additive,
and a test pins that.
