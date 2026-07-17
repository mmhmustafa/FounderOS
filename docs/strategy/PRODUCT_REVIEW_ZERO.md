# Atlas Product Review — Codename ZERO

**Prepared for:** the Atlas founders
**Prepared as:** CTO + Chief Product Officer strategic review
**Date:** 15 July 2026
**Status:** opinionated. Written to be argued with.

---

## 0. Evidence base, and what this review cannot tell you

A review that hides its assumptions is worth nothing, so:

**What I know well.** The codebase. I have read it deeply and built two of its
layers (CORTEX, SENTINEL). Every architectural claim below is grounded in code I
can point to.

**What I do not know.** Anything about your market. There have been **no customer
interviews, no pricing research, no win/loss data, no design partners**. Every
statement about who buys, what they pay, and why is *inference* from domain
knowledge, not evidence. I mark these **[INFERENCE]**. Treat them as hypotheses
to test, not findings.

That asymmetry — deep product knowledge, zero market knowledge — is itself the
most important fact in this review. It is also, precisely, the company's risk.

---

## 1. The finding that should reorganise your year

I went looking for the moat. Here is what ships:

```
src/founderos_atlas/platforms/drivers/
    frr.py      ← an open-source routing daemon, used in your containerlab
    ios.py      ← Cisco IOS

FUTURE_PLATFORMS = ('Cisco NX-OS', 'Junos', 'Arista EOS', 'FortiOS', 'PAN-OS')
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                    a tuple of strings. Not code. Aspirations.
```

Now compare the weight of the layers:

| Layer | Lines | What it is |
|---|---:|---|
| `reasoning/` (CORTEX) | 1,357 | how Atlas thinks |
| `prediction/` | 2,990 | what Atlas concludes |
| `path_intelligence/` | 1,579 | what Atlas concludes |
| **`platforms/` (drivers)** | **1,011** | **everything Atlas can actually talk to** |

**The reasoning layer is now larger than the layer that gathers the evidence it
reasons about.** Atlas can think brilliantly about networks it cannot connect
to. The architecture has outrun the evidence.

This is not a code-quality problem — the code is excellent. It is a **product
sequencing** problem, and it is the whole story:

> **Atlas is a world-class reasoning platform that speaks two dialects, one of
> which is a lab emulator. Its intelligence is Series-B quality. Its reach is
> pre-seed.**

Every recommendation in this document descends from that sentence.

---

## 2. Part 1 — What is Atlas?

### One sentence

> **Atlas discovers your network from a single IP address and tells you what it
> is, what changed, and what's wrong — and shows you the evidence behind every
> claim.**

Note what that sentence does *not* say: it does not say monitoring, dashboards,
AIOps, or observability. Those categories are full. This one is not.

### 30-second pitch

> Most enterprises cannot produce an accurate network diagram. The one on the
> wiki is three years old and was drawn by someone who left. Atlas fixes that.
> Give it one IP address and one read-only credential. It walks the network hop
> by hop, builds the topology from what the devices actually say, records every
> configuration, and checks it all against policy. Every single conclusion cites
> the exact command output it came from. No agents. No SNMP. No guessing — where
> Atlas doesn't know, it says Unknown.

### 2-minute pitch

The 30-second version, plus the three things that make it a company:

1. **The wedge is the unknown network.** Everyone else — NetBox, Forward,
   SolarWinds — starts from an inventory *you already have*. Atlas starts from
   one IP and *derives* the inventory. That inverts the onboarding problem. The
   people who feel this pain acutely: MSPs taking on a client, acquirers
   integrating a target, consultants auditing an estate, and the engineer who
   just inherited a brownfield nobody documented. **[INFERENCE]**

2. **The differentiator is evidence, in an era of hallucination.** Every AIOps
   vendor now ships a chatbot that will confidently invent a topology. Atlas is
   architecturally incapable of that: the reasoning engine is deterministic, the
   confidence cap is 0.95 (never certainty), and any conclusion without evidence
   is structurally forced to "Unknown." When AI arrives it will *narrate* results,
   never reach them. That is a defensible, auditable position — and it is a
   position competitors cannot retrofit, because it is an architecture, not a
   feature.

3. **The compounding asset is memory.** Atlas stores every raw device response,
   content-addressed and immutable. Today it answers "what is my network?"
   Tomorrow the same store answers "what did it look like in March?" and "what
   did that change break?" Competitors store metrics; Atlas stores *evidence*.
   Metrics expire. Evidence compounds.

### 10-minute demo story

The demo is a narrative with one peak. Today the peak is missing.

| # | Beat | Time | Status |
|---|---|---|---|
| 1 | "Here is a network nobody documented." Empty Atlas. One IP, one credential. | 0:30 | ✅ works |
| 2 | Run discovery. Watch it walk hop by hop, authenticating, finding neighbours. | 2:00 | ✅ works |
| 3 | The topology draws itself. **Nobody drew this.** It is derived from evidence. | 1:00 | ✅ works |
| 4 | Click a link: *"Why do you think core1 connects to edge1?"* → the OSPF neighbour output, the exact line, the session it came from. | 1:30 | ✅ works |
| 5 | Policy: 58% compliant, 45 findings. Click one → the config, the reason, the fix. | 1:30 | ✅ works |
| 6 | **"Someone changed core1 on Tuesday. Here's what it broke."** Config diff → BGP session reset → these services affected. | 2:00 | ❌ **does not exist** |
| 7 | Ask in English: *"is my network healthy?"* → plain answer, every claim clickable to its evidence. | 1:00 | ⚠️ partial |
| 8 | Export the whole thing as a report you can hand to an auditor. | 0:30 | ❌ **does not exist** |

**Beats 1–5 are genuinely impressive and they already work.** Beat 6 is the one
that closes deals, and it is the one you have not built — even though you own
every component it needs (configuration history + topology + reasoning). Beat 8
is what makes the demo *purchasable*.

---

## 3. Part 2 — Who buys Atlas?

All **[INFERENCE]**. Ranked by *how quickly they would say yes*, not by market size.

| Buyer | Their problem | Their pain | Value of Atlas | Willingness to pay |
|---|---|---|---|---|
| **MSPs / managed network providers** | Onboarding a new client's undocumented network takes 2–6 weeks of senior engineer time, per client | Acute, recurring, directly billable | Compresses onboarding to a day. Direct margin. | **Highest.** They can price it into the engagement. Per-tenant or per-assessment. |
| **Network consultants / auditors** | Every engagement starts with "what have I got?" | Acute, recurring | The deliverable *is* the report. | **High**, but small seats. Project pricing. |
| **M&A / IT integration teams** | Acquired a company; nobody knows its network | Acute, episodic, well-funded | Diligence and integration planning | **High per project**, low frequency. Lumpy. |
| **Enterprise network engineers** | Documentation rot; tribal knowledge; 3am blame | Chronic, tolerated | High value, but they've lived without it for 20 years | **Medium.** Champions, not budget owners. |
| **NOC teams** | Need to know what broke, now | Acute, constant | **Atlas is not yet an ops tool** (snapshot, not stream) | **Low today.** High *after* events/telemetry. |
| **Compliance / audit / risk** | Prove the network meets standard | Chronic, regulated, budgeted | Evidence-grade compliance is exactly their language | **Medium-high**, and *sticky*. Regulated industries pay for proof. |
| **Government / defence** | Air-gapped, must be local, must be auditable | Chronic | Local-only, read-only, no cloud, evidence-cited = unusually well-matched | **High**, brutal sales cycle. |
| **Financial / healthcare** | Regulated change control | Chronic | Change→impact evidence | **High**, but will demand everything in §11. |
| **Cloud teams** | Their network is APIs, not SSH | — | **Atlas cannot see their world at all** | **Zero today.** |

### The uncomfortable conclusion

Your best buyer is **not** the enterprise. It's the **MSP and the consultant** —
because for them, Atlas is *revenue*, not *insight*. Enterprises buy insight
grudgingly and cut it first in a downturn. Service providers buy anything that
reduces senior-engineer hours, and they buy it this quarter.

**Recommendation: aim v1 at MSPs and consultants. Let enterprise pull you in
later.** This changes what you build (reports, multi-tenant, fast onboarding)
and what you don't (deep NOC integration).

---

## 4. Part 3 — What problems does Atlas solve?

Ranked by value × frequency, not by how interesting they are to build.

| # | Problem | Business value | Eng. value | Status |
|---|---|---|---|---|
| 1 | **"I don't know what my network is."** | 🔴 Very high — blocks everything else | High | ✅ **Solved.** The strongest thing you have. |
| 2 | **"A change broke something and I don't know which."** 70–80% of outages are change-induced. | 🔴 Very high | High | ❌ **Not solved.** All parts exist, unconnected. **The single biggest gap.** |
| 3 | **"My documentation is a lie."** | 🟠 High | Medium | ✅ Solved (and self-maintaining, which is the trick). |
| 4 | **"Prove we're compliant."** | 🟠 High, budgeted, recurring | Medium | ✅ Solved as a framework; ❌ the packs that matter (CIS/STIG/vendor) don't exist. |
| 5 | **"What will happen if I change this?"** | 🟠 High | High | ⚠️ Partial (Prediction), unproven at real scale. |
| 6 | **"Why can't A reach B?"** | 🟠 High, daily | High | ⚠️ Partial (Paths). Forward Networks owns this ground. |
| 7 | **"What's wrong right now?"** | 🔴 Very high | Medium | ❌ **Not solved.** Atlas is a snapshot. No events, no stream, no alerts. |
| 8 | **"Onboard a new client/estate fast."** | 🟠 High (and *billable*) | Low — mostly packaging | ⚠️ The engine works; **there's no report to hand over**. |
| 9 | "Is the network secure/hardened?" | 🟡 Medium | Medium | ⚠️ Policy touches it; not a security product. |
| 10 | "Capacity / cost / performance" | 🟡 Medium | High | ❌ Not attempted (correctly — that's Kentik's). |

**Read the table honestly:** you have solved the problems of *knowing*, and none
of the problems of *operating*. That is a coherent product — it's just a
different product than "enterprise network management," and it should be sold as
one.

---

## 5. Part 4 — Module review

The product has **18 top-level nav items and zero users.** For calibration:
Datadog ships ~8. Linear ships 4. Eighteen is not a product; it's a menu of
engineering achievements.

| Module | Why it exists | Who / how often | Duplicates? | Verdict |
|---|---|---|---|---|
| **Discovery** | Get the evidence | Operator, at onboarding + periodically | — | ✅ **Keep. It is the crown jewel.** Fold Profiles into it. |
| **Topology** | Show what was found | Everyone, constantly | — | ✅ **Keep. This is the demo.** Merge Inventory + Device Details in. |
| **Device Details** | The device's truth | Engineers, constantly | It has no nav entry — it's a leaf | ✅ Keep as a leaf of Network. Console + Management become *actions here*, not nav items. |
| **Inventory** | What do I have | Managers, weekly | Overlaps Topology | 🔀 **Merge into Network** as a view toggle. |
| **Mission** | What's wrong now | Managers, daily | Overlaps Incidents | 🔀 **Merge with Incidents → "Health".** Also: its reasoning lives in `web/mission.py` — move it (CORTEX §1.4B). |
| **Incidents** | What broke | NOC | Overlaps Mission | 🔀 **Merge into Health.** Premature as a standalone. |
| **Advisor** | Ask in English | Engineers, occasionally | Overlaps Predict/Paths/Compass | 🔀 **Becomes "Ask" — the single question surface.** |
| **Prediction** | What if? | Engineers, before changes | Overlaps Compass heavily | 🔀 **Merge into Ask.** |
| **Investigation (Paths)** | Why can't A reach B? | Engineers, during incidents | Overlaps Predict | 🔀 **Merge into Ask.** |
| **Compass** | What should I change? | Unclear | **Yes — Prediction.** Your own architecture doc (§14.7) already questions whether it belongs. | 🔴 **DELETE.** It is a speculative module answering a question nobody asked, overlapping one that already exists. 1,151 lines of maintenance for a hypothesis. |
| **Memory** | Raw evidence history | Rarely — it's a debug view | Configuration / History / Changes | 🔀 **Merge into Timeline.** Keep the *store*; kill the *page*. |
| **Configuration** | Config versions | Engineers, weekly | Memory / Changes | 🔀 **Merge into Timeline.** |
| **History** | Past discoveries | Rarely | Memory / Changes | 🔀 **Merge into Timeline.** |
| **Changes** | What changed | Engineers, daily — **this is the valuable one** | Memory / Config / History | 🔀 **Merge into Timeline and make Timeline the home of the killer feature.** |
| **Policy** | Compliance | Compliance + engineers, monthly | — | ✅ **Keep.** Newest and cleanest. |
| **Console** | SSH to device | Engineers, constantly | Management | 🔀 **Not a nav item — a device action.** |
| **Management** | Open device web UI | Rarely | Console | 🔴 **Remove from nav.** Honestly: this is a bookmark, not a feature. Keep the resolver, drop the page. |
| **Search** | Find things | — | **It has no nav entry.** 968 lines that no user can reach. | 🔴 **Delete or surface.** Invisible code is pure debt. |
| **Credentials / Settings / Profiles** | Setup | Once | Each other | 🔀 **Merge into "Setup".** |
| **Federation / Workspace** | ? | No nav entry, ~2,300 lines | — | 🔴 **Justify or delete.** |

### The recommendation: 18 → 6

```
1. NETWORK    topology · inventory · device detail (console + web as actions)
2. HEALTH     mission + incidents + risks — "what's wrong now"
3. TIMELINE   memory + configuration + changes + history — "what changed, and what did it break"
4. POLICY     compliance
5. ASK        advisor + prediction + investigation — one question surface
6. SETUP      discovery + profiles + credentials + settings
```

Four pages of "the past" (Memory, Configuration, History, Changes) is not four
features. It is one feature — **Timeline** — implemented four times because four
PRs each needed a page. Same for the four analysis pages. This is the clearest,
cheapest, highest-leverage improvement available to you, and it requires
*deleting*, not building.

**Also delete:** ~3,300 lines of `search` + `federation` + `workspace` that no
user can reach. Code with no entry point is not an asset.

---

## 6. Part 5 — Platform review

| Layer | Strengths | Weaknesses | Scale | Debt / risk |
|---|---|---|---|---|
| **Discovery** | Genuinely differentiated. Seed→network derivation is the wedge. Read-only = low adoption friction. | **Two drivers.** SSH-only. No cloud, wireless, firewall. Untested against real IOS/NX-OS/Junos quirks (banners, pagination, TACACS, jump hosts, MFA). | Unproven >9 devices | 🔴 **Existential. This is the company's #1 risk.** |
| **Knowledge Graph** | Correlation + canonical identity is real engineering. 9-priority fusion is sophisticated. | Contract adopted by 2 of 7 consumers (CORTEX §1.4C). | JSON snapshot | 🟠 Partial adoption = three ways to read one graph. |
| **Memory** | Best-designed layer. Content-addressed, immutable, deduplicated, source-agnostic. Compounding asset. | JSON indices. No retention policy, no GC, no encryption at rest. | 🔴 **JSON files.** Fine at 9 devices; dead at 10,000. | 🟠 SQLite/Postgres behind the same API — cheap, deferred. |
| **Reasoning (CORTEX)** | Excellent. Correct AI boundary set *before* AI arrived — rare discipline. Proven by SENTINEL with zero new scoring code. | Only one consumer. Eight legacy scorers still live. | Fine | 🟠 **Risk R2 is live:** if migration stalls, CORTEX becomes a 9th way to reason. |
| **Policy (SENTINEL)** | Data-driven, correct, extensible. Packs = recurring revenue. | Five operators. No pack that a customer actually asks for by name (CIS/STIG/PCI). | Fine | 🟡 Low. |
| **Universal Actions** | Well-built (host-key verification, single-use tokens, origin allowlist). | Solves a problem PuTTY solved in 1999. | Fine | 🟡 Over-invested for the value returned. |
| **Web / GUI** | 4,877 lines — the largest module. Works. | **Contains reasoning** (`web/mission.py`). 18 nav items. Flask dev server. Single-user. | 🔴 No multi-user, no RBAC, no API, no auth | 🔴 **Not an enterprise application.** |

### The platform's real verdict

Three of these layers (Memory, Reasoning, Policy) are better than they need to
be. One (Discovery) is the entire business and is under-built. One (Web) is
carrying business logic it shouldn't and an IA that's collapsing under its own
weight.

**You have been building the cathedral's ceiling before its foundations.**

---

## 7. Part 6 — Competitive position

| Competitor | What they are | vs Atlas |
|---|---|---|
| **Forward Networks** | Network digital twin + formal verification. ~$1B. **Your real competitor.** | They verify the network *you documented*. Atlas documents the network *you inherited*. They have a mathematical model and a vast driver matrix; you have two drivers. **They win on depth. You win on cold-start.** |
| **NetBox / Nautobot** | Source of truth. Open, huge ecosystem, free. | **Do not compete.** Their data is *intent* (what should be); yours is *observed* (what is). **Integrate — become the thing that populates and audits NetBox.** That is a feature, a partnership, and a wedge. |
| **Cisco Catalyst Center** | Vendor-native management | Deep on Cisco, blind elsewhere, bundled. Atlas's multi-vendor story is only credible *if you ship multi-vendor drivers*. Today it isn't. |
| **Juniper Mist** | AI-driven, wireless-first, cloud | Genuine AIOps with real telemetry. Atlas has no telemetry and no wireless. Different plane. |
| **SolarWinds NPM / LogicMonitor / ManageEngine** | Monitoring: SNMP, metrics, alerts | 20 years of integrations, agents, alerting. **Atlas is not a monitoring tool and shouldn't become one.** They tell you a link is down; Atlas tells you what the network *is*. |
| **ThousandEyes / Kentik** | Internet/path & flow visibility | Adjacent plane. No overlap. |

### Where Atlas is uniquely strong

1. **Cold-start discovery.** One IP → the network. Nobody else does this well
   because everybody else assumes you have an inventory.
2. **Evidence-grade reasoning.** Every claim cites its source. In a market about
   to be flooded with confidently-wrong AI, "we can prove it" is a real position.
3. **Local, read-only, air-gappable.** Disqualifying for SaaS competitors in gov
   and defence. An accidental moat — *keep it*.

### Where Atlas is weak

Driver coverage (fatal), scale (unproven), events (absent), integration (no
API), enterprise plumbing (none), and — bluntly — **market contact (zero)**.

### The category-defining line

> **"Forward Networks verifies the network you documented.
> Atlas documents the network you inherited."**

Own **"Evidence-Grade Network Truth."** Not monitoring. Not AIOps. Not SoT.
*Truth, with proof.*

---

## 8. Part 7 — The WOW factor

I sat in the CIO's chair. Here's what does and doesn't land.

**Does not make a CIO buy:** confidence bands, content-addressed storage, a
reasoning kernel, deduplicated blobs. These are *how*, and no CIO buys *how*.

**What genuinely lands (and works today):**

> Point Atlas at one IP address. Walk away. Come back to a complete, accurate,
> evidence-backed map of a network nobody had documented — plus a ranked list of
> what's wrong with it, each with proof.

That is a real wow and **you already have it.** It is buried under 18 nav items
and has no report to take away.

**What would make them say "we need this" — and doesn't exist:**

> **"Someone changed core1 at 14:02 on Tuesday. Here is the exact line they
> changed, here is the BGP session that dropped at 14:03 because of it, here are
> the three services that went with it — and here is the rollback."**

**Change → Impact.** This is the #1 question in network operations because
change causes most outages. You own every ingredient: immutable config history
(Memory), the topology (Knowledge), and an engine that reasons with evidence
(CORTEX). **Nobody has connected them.**

It is also the perfect showcase for the evidence architecture — the answer is
*provable*, not guessed. Competitors with metrics-only data models *cannot* build
this, because they never stored the config that caused it.

**This is your killer feature. Build it next.**

---

## 9. Part 8 — Simplification

### Duplicate concepts

| Duplication | Cost |
|---|---|
| **"The past" × 4** — Memory, Configuration, History, Changes | Four pages, one concept. User must learn which of four to open. |
| **"Analysis" × 4** — Advisor, Predict, Paths, Compass | Four surfaces for "answer my question." |
| **"Connect" × 2** — Console, Management | Two nav items for what should be a button on a device. |
| **"Setup" × 4** — Discovery, Profiles, Credentials, Settings | Onboarding spread across four places. |
| **Confidence scoring × 8** | Eight scorers; CORTEX makes 9 until migration completes. |
| **Graph reading × 3** | The contract exists; 5 of 7 consumers ignore it. |

### Over-engineering — the honest list

- **Universal Web Management (PR-044B).** ~1,258 lines to open a browser tab.
  TLS inspection, service store, endpoint resolution — beautiful work, negligible
  value. Would not be missed.
- **Compass.** 1,151 lines answering a question that overlaps Prediction, whose
  belonging your own architecture doc questions.
- **Search / Federation / Workspace.** ~3,300 lines with no route to a user.
- **Confidence display.** In the live lab, **108 of 108 policy results scored
  85% "high."** A number identical across every result carries *zero
  information* while costing the reader attention on every row. The rigour is
  right; **the display is wrong.** Show evidence and conclusion; show confidence
  only when it is *low* — i.e. when it changes what the reader should do.

### Missing workflows

1. **Export / report.** No PDF, no CSV, no evidence pack. An MSP's deliverable
   is a document; you produce none. Cheapest high-value gap on the list.
2. **Change → impact.** §8.
3. **Alerting.** Insight nobody is told about is not insight.
4. **Onboarding.** No first-run experience. A new user meets 18 nav items and no
   guidance.
5. **Scheduled discovery.** Truth must refresh itself, or documentation rot
   returns — which is the very problem you sell against.

### The simplification thesis

> **Atlas's next release should be smaller than this one.**
>
> Delete Compass, Management, Search, Federation, Workspace. Collapse 18 nav
> items to 6. Hide confidence unless it's low. Ship a report. Nothing about that
> list is a feature; all of it is product.

---

## 10. Part 9 — The next 12 months

Capabilities, not PRs. Ordered by *what unblocks what* — and the first item is
non-negotiable, because nothing else matters if Atlas can only talk to a lab.

### Q1 — Reach and reality (existential)

1. **Drivers: Cisco NX-OS, Arista EOS, Juniper Junos.** Turn `FUTURE_PLATFORMS`
   from a tuple of strings into code. This is the moat and the TAM. Nothing on
   this roadmap matters more.
2. **Three design partners** (aim: 2 MSPs, 1 enterprise). Free. Their networks
   decide driver priority — not this document.
3. **Real-network hardening:** banners, pagination, TACACS+, jump hosts, MFA,
   slow links, 500+ devices. Emulated FRR has taught you nothing about any of
   these. **[INFERENCE: this will be humbling.]**

> **Exit criterion:** Atlas discovers a real, multi-vendor, production network of
> 200+ devices that no one on the team has seen. Until then, everything else is
> premature.

### Q2 — Product, not modules

4. **The great simplification.** 18 → 6. Delete Compass/Management/Search/
   Federation/Workspace. Confidence shown only when low.
5. **Change → Impact.** The killer feature. The demo peak. The reason to buy.
6. **Export / Network Onboarding Report.** The MSP's deliverable. Turns Atlas
   from a tool into a billable artefact.

### Q3 — Enterprise plumbing (unglamorous, mandatory)

7. **Persistence:** SQLite/Postgres behind the existing retrieval APIs.
8. **API-first.** No API = no integration = no enterprise. Also unlocks NetBox
   sync (see §7 — become the thing that populates their SoT).
9. **Multi-user, RBAC, audit log, SSO.**
10. **Credential vaulting** (CyberArk / HashiCorp Vault). A bank will never let
    a laptop tool hold domain-wide device credentials. **This is a deal-breaker,
    not a nice-to-have.**

### Q4 — The second dimension

11. **Events: syslog ingestion.** Atlas becomes a stream, not a snapshot. CORTEX
    already has the provider seam — this is the design paying off.
12. **AI narration layer** (§14). Schema-in, prose-out.
13. **Policy packs people ask for by name:** CIS, vendor best-practice. Recurring
    revenue.
14. **Scheduled discovery + drift alerting.** Truth that refreshes itself.

### What is deliberately NOT on this roadmap

Automation/write, telemetry/metrics, cloud/wireless, ML anomaly detection,
mobile, SaaS. All defensible later; all fatal now.

---

## 11. Part 10 — The next three years

A coherent arc: **Know → Assure → Act.**

### v1.0 — "Network Truth" (12 months)
*What is my network, and is it right?*
Multi-vendor discovery, topology, timeline, policy, reports, evidence
everywhere. Read-only. Local/self-hosted.
**Buyer:** MSPs, consultants, M&A. **Value:** documentation + audit + onboarding.
**Proof point:** an MSP onboards a client in a day instead of a month.

### v2.0 — "Network Assurance" (24 months)
*What changed, what broke, what's about to?*
Add events/syslog/SNMP traps, continuous verification, change→impact at scale,
drift alerting, NetBox/ServiceNow integration, AI narration.
**Buyer:** enterprise NOC and network architecture. **Value:** MTTR + change risk.
**Proof point:** Atlas names the cause of a real outage before the war room does.

### v3.0 — "Network Autonomy" (36 months)
*Propose the change, prove the impact, execute it safely.*
The write path — earned, never assumed: propose → predict (deterministically) →
approve → execute → verify → auto-rollback on evidence of harm.
**Buyer:** platform/automation teams. **Value:** safe change at scale.
**Proof point:** a change executes and self-reverts when the evidence says it hurt.

**Why this order is the only honest one:** nobody grants write access to a tool
that hasn't proven it understands the network. Read-only v1 isn't a limitation —
it's how you earn the right to v3. Every automation vendor that skipped this
died of distrust.

---

## 12. Part 11 — Criticise Atlas

### As a VC

1. **1,351 tests. Zero users.** The single most damning fact here. You have
   optimised for correctness against an imagined customer.
2. **You built the reasoning framework before the drivers.** 1,357 lines of
   CORTEX; 1,011 lines of everything Atlas can talk to. That is an engineer's
   priority order, not a founder's.
3. **No design partners, no interviews, no pricing evidence.** Every market
   claim — including mine — is a guess.
4. **Validated on an emulator.** FRR in containerlab is not a network. It has no
   TACACS, no banners, no pagination quirks, no 15-year-old 3750 that hangs on
   `show run`.
5. **Read-only caps ACV.** Insight is the first line cut in a downturn.
6. **Category confusion.** Today Atlas is three products (SoT, verification,
   management). Pick one or lose to all three.
7. **Bus factor 1.** **[INFERENCE]**

### As Gartner

8. **Not a category.** "Evidence-grade network truth" isn't in a Magic Quadrant.
   You'll be forced into NPM/NCCM and lose on features you never wanted.
9. **No ecosystem.** No API, no integrations, no partners, no marketplace.
10. **No cloud/wireless/security** = "legacy infrastructure tool" positioning.
11. **Deployment model.** A local Flask app on 127.0.0.1 is not deployable in
    the enterprises you're targeting.

### As a Fortune 500 buyer

12. **"Where do the credentials live?"** — this ends the meeting today.
13. **"Show me SOC 2, SSO, RBAC, audit."** — none exist.
14. **"How does it scale to 40,000 devices?"** — JSON files.
15. **"Who else uses it?"** — nobody.
16. **"What happens when your engineer leaves?"**
17. **"It only supports two of my seven vendors."**
18. **"Prove it's read-only."** Fair; you can — but you must *prove* it, and
    that's a document, a pen-test, and a security review you don't have.

### The one criticism that matters

Everything above reduces to a single sentence:

> **Atlas has spent its life reasoning about a network that doesn't exist, for a
> customer it has never met.**

The architecture is genuinely excellent — better than most companies at Series B.
That is precisely the trap: **excellence in the wrong dimension feels like
progress.** The next twelve months should feel *less* satisfying to build and
*far* more valuable.

---

## 13. Part 12 — Final recommendations

### Top 10 strengths
1. Cold-start discovery — genuinely differentiated.
2. Evidence-cited reasoning — architecturally hard to copy.
3. Enterprise Memory — a compounding asset competitors lack.
4. CORTEX — the AI boundary drawn correctly *before* AI arrived.
5. Deterministic, never-guess doctrine — trust as architecture.
6. Read-only — low adoption friction, high trust.
7. Local/air-gappable — an accidental gov/defence moat.
8. The topology demo — it already lands.
9. Engineering discipline — 1,351 tests, honest docs, real rigour.
10. Policy as data — packs are a clean revenue engine.

### Top 10 weaknesses
1. **Two drivers.** Everything else is downstream of this.
2. Zero users, zero design partners.
3. Validated only on an emulator.
4. 18 nav items; four ways to see the past.
5. JSON storage — no scale.
6. No API, no integrations.
7. No multi-user/RBAC/SSO/audit.
8. Credentials on a laptop — a deal-breaker.
9. Snapshot, not stream — no events.
10. No export/report — nothing to hand over.

### Top 10 opportunities
1. **Change → Impact** — the killer feature; you own every part.
2. MSP onboarding as a billable artefact.
3. NetBox/Nautobot integration — populate and audit their SoT.
4. Compliance packs (CIS/STIG/PCI) — recurring revenue.
5. "AI you can audit" — sharp positioning against hallucinating AIOps.
6. M&A network diligence — an unserved, well-funded niche.
7. Gov/defence — local+read-only+evidence is unusually well-matched.
8. Open-core adoption motion against NetBox mindshare.
9. Syslog via the CORTEX provider seam — cheap, high value.
10. The onboarding report as a wedge → land, then expand.

### Top 10 threats
1. Forward Networks moves down-market.
2. Cisco/Juniper bundle "good enough" discovery for free.
3. An AI-native competitor ships 80% quality with 10× the noise — and wins on
   narrative.
4. NetBox ecosystem adds discovery.
5. Networks move to cloud/SD-WAN where Atlas is blind.
6. SSH access becomes politically impossible (zero-trust, JIT credentials).
7. Buyers don't value rigour enough to pay for it. **The core hypothesis risk.**
8. Driver maintenance becomes a treadmill you can't fund.
9. Enterprise sales cycle outlasts runway.
10. The architecture keeps being more fun to build than the business.

### Top 20 recommendations

**Existential (now)**
1. **Ship NX-OS, EOS, Junos drivers.** Nothing outranks this.
2. **Get 3 design partners in 60 days.** Free. Their networks set priorities.
3. **Run against a real 200+ device production network.** Expect humbling.
4. **Pick one category: Evidence-Grade Network Truth.** Stop being three products.
5. **Target MSPs/consultants first**, not enterprises.

**Product (Q2)**
6. **18 → 6 nav.**
7. **Delete Compass, Management, Search, Federation, Workspace** (~6,700 lines).
8. **Build Change → Impact.** The demo peak.
9. **Ship the Network Onboarding Report** (PDF/CSV export).
10. **Hide confidence unless low.** 85% on 108/108 rows is noise.
11. **Move Mission's reasoning out of `web/`** (CORTEX §1.4B — bugs already hid there).
12. **Finish the CORTEX migration or stop it.** A framework with one consumer is
    a 9th way to reason (risk R2).

**Platform (Q3)**
13. SQLite/Postgres behind the current APIs.
14. API-first.
15. Multi-user, RBAC, SSO, audit log.
16. **Credential vaulting** (CyberArk/Vault) — a deal-breaker.
17. Prove read-only: threat model + pen-test + a security whitepaper.

**Growth (Q4)**
18. Syslog ingestion via the provider port.
19. CIS/vendor policy packs.
20. AI narration — "AI you can audit."

### Product vision

> **Atlas is the system of record for what your network *actually is* — derived
> from the network itself, proven by evidence, and never guessed.**

### Company positioning

> **"Forward Networks verifies the network you documented.
> Atlas documents the network you inherited."**
>
> Category: **Evidence-Grade Network Truth.** Not monitoring. Not AIOps. Not SoT.

### Pricing model **[INFERENCE — test everything here]**

**Do not price yet.** You have no evidence of value. Give it to 3 design partners
free and let them tell you. When you do price:

| Tier | Who | Shape | Indicative |
|---|---|---|---|
| **Community** (open-core) | Engineers, NetBox crowd | Discovery, topology, inventory. Device cap (~50). | Free |
| **Professional** | MSPs, consultants | + Policy, Memory, Reasoning, API, reports | ~$15–25/device/yr, **or $5–15k per assessment** (MSPs prefer this — it maps to how they bill) |
| **Enterprise** | Regulated, large | + Multi-user, RBAC, SSO, vault, custom packs, support | ~$40–60/device/yr, floor ~$25k/yr |
| **MSP / multi-tenant** | Service providers | Per client network | ~$500/network/month |

Rationale: open-core buys adoption against NetBox mindshare; the moat (drivers +
packs) sits behind the paywall. **Read-only insight prices at insight rates
(~$15–25), not automation rates (~$50–150).** That gap is the commercial argument
for eventually earning the write path.

### Licensing

Open-core. Permissive (Apache-2.0) for the community core to maximise adoption;
commercial licence for Policy packs, Memory retention, multi-user, and
integrations. **Do not open-source the drivers** — that is the moat. Self-hosted
first, always; air-gap support is a differentiator, not a burden.

### Recommended MVP

**Not what exists — a subset of it.**

> **The Network Onboarding Report.**
> Point Atlas at one IP. It discovers a multi-vendor network (IOS, NX-OS, EOS,
> Junos), draws the topology, records every configuration, checks it against a
> starter policy pack, and **produces a document you can hand to a client.**

That's it. Five capabilities: Discover · Topology · Timeline · Policy · Export.
Everything else hidden until a user asks for it. An MSP would buy that this
quarter; nothing else in the current 18-item product moves that needle.

### Recommended Enterprise Edition

Community + **multi-user/RBAC/SSO/audit**, **credential vaulting**, **API**,
**Postgres scale**, **custom policy packs**, **NetBox/ServiceNow integration**,
**scheduled discovery + drift alerting**, support/SLA. Note that *every one of
these is plumbing, not intelligence* — which is exactly why it's been avoided,
and exactly why it gates the enterprise deal.

### AI roadmap

The architecture already made the right call; the roadmap just executes it.

| Phase | Capability | Boundary |
|---|---|---|
| **1** | **NL → question.** "Why can't A reach B?" → a `ReasoningQuestion`. | LLM parses *intent*. Engine answers. LLM sees no evidence. |
| **2** | **Result → prose.** `ReasoningResult` → plain English, every claim linked to its evidence. | LLM may **only re-word**. Never alters conclusion, confidence, severity, recommendation. |
| **3** | **Report generation.** The Onboarding Report, written from `ReasoningResult`s. | Same boundary. Deterministic content, fluent prose. |
| **4** | **Agentic investigation.** LLM chooses *which questions to ask*; the engine answers each. | LLM orchestrates. Never concludes. |
| **Never** | LLM computing confidence, inventing evidence, or deciding remediation. | This is the product. |

**The marketing line writes itself, and it is true:**

> **"Every other AI network tool asks you to trust a model.
> Atlas shows you the evidence — and links every sentence to the command output
> it came from."**

In 2026, when the market is saturated with confidently-wrong network chatbots,
*auditable* AI is not a compromise. It is the differentiator. Your competitors
cannot retrofit it, because it is an architecture, and they built a feature.

---

## 14. The one-page answer

**Keep:** discovery, evidence, memory, reasoning, policy, read-only, local.
**Delete:** Compass, Management, Search, Federation, Workspace, 12 nav items,
and the confidence badge on results that all say 85%.
**Build:** drivers (NX-OS/EOS/Junos), Change→Impact, the Onboarding Report.
**Fix:** credentials, API, multi-user, storage.
**Do first, before any of it:** *find three customers.*

> Atlas's problem is not that it lacks good engineering. It is that it has had
> world-class engineering and no market contact for its entire life, and those
> two facts have started to feel like the same kind of progress. They are not.
>
> **The next twelve months should feel less satisfying to build, and be worth far
> more.**
