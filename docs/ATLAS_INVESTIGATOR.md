# Atlas INVESTIGATOR — deterministic investigation planning (PR-167)

Atlas answers operational questions by **investigating** them, not by picking one engine.

```
question
   ↓  understand      structured request: intent, protocol, endpoints, interfaces, VLANs, time, severity
   ↓  resolve         those names, against entities Atlas has actually discovered
   ↓  plan            the checks an operations engineer would run, shown before they run
   ↓  execute         several engines over ONE shared context
   ↓  answer          findings, evidence, and what could not be determined
```

**No AI participates.** Extraction is fixed vocabularies and regex shapes over the operator's own words.
Resolution matches discovered entities and reports ambiguity instead of choosing. The plan is a template's declared
steps. Every finding comes from stored evidence.

## The rule that shapes everything

> A question that names something specific gets an answer about **that**. A question that names nothing keeps
> getting the estate-wide answer it always got.

`investigate()` returns `None` when the question names no protocol, site, device, interface or address, and the
Advisor falls through to its existing single-engine path unchanged. Inventing a scope would be worse than a general
answer — so "Is the network healthy?" still answers exactly as it did before PR-167, and a test pins that.

## Question Understanding (PR-171): subject · objective · scope

PR-171 added the three dimensions the original extraction conflated or lacked. Every one is a fixed
vocabulary over the operator's own words — no scoring, no similarity, no AI — and every one records
the **basis** for its own determination, which the answer shows.

| Dimension | Values | Rule |
|---|---|---|
| **subject** | a protocol key, or a domain subject (`configuration`, `interfaces`) | protocols win over domain subjects — "ospf configuration" is about OSPF. The vocabulary lives in the **subject registry** (`subjects.py`): adding IS-IS is one descriptor, nothing else changes. |
| **objective** | `validate` · `assess` (default) · `locate` · `explain` · `compare` · `forecast` | most specific wins, in that fixed order. **`validate` is gated twice**: it needs a subject ("is the network fine?" stays an assessment), and it needs configuration-context AND a judgement word together, or a self-contained term like "misconfigured" — so "show me the OSPF configuration" stays a lookup. |
| **scope** | `enterprise` · `sites` · `devices` · `interfaces` — a **positive value** | "across the enterprise" is a real, resolved scope, not the absence of one. A validation naming no narrower place is judged estate-wide, and the basis says so. Conflating "named no place" with "asked about everything" is exactly what made an enterprise-scoped OSPF question read as unscoped. |

Subject and scope are orthogonal: `has_subject` and `has_scope` are separate predicates, and the
original PR-167 `named_anything` keeps its exact meaning (named a *place or object*) because the
estate-wide contract is pinned against it.

### Selection order (deterministic, specific-first)

1. **subject + objective=validate** → the subject's validation template, built from its
   **discovered capability** (PR-172, `investigation/validation.py`): the subject's declared
   `policy_tags` select rules in the active pack, or there is no capability and the question is
   **refused honestly** — never handed to the estate summary, never run through an adjacency
   investigation in validation's clothing.
1b. **subject + objective=assess + state capability** (PR-173) → the subject's operational-state
   template — "Is BGP healthy?" earns a judged verdict with the observation age stated. Endpoints
   keep the peering investigation; "show me…" extracts `objective=locate` and keeps its listing;
   a temporal question ("flapping", "stable") is refused before any template runs, because Atlas
   retains no state history. See `docs/ATLAS_STATE_VALIDATION.md`.
2–6. The PR-167 ladder, byte-for-byte: protocol+endpoints → protocol+scope → endpoints →
   named scope → **None**.

### The generic validation template (PR-172)

**One template builder for every subject** — `validation_template(capability)` — parameterised
entirely by labels; the three steps and both engines are identical for OSPF, BGP and every future
subject. It orchestrates the **existing policy engine** and re-implements no matching: the
capability's vetted rules are judged by `PolicyEngine.evaluate()`, and the template aggregates the
engine's own dispositions. Adding a technology is two data edits — a subject descriptor with
`policy_tags`, and rules in a pack carrying those tags. No template, no intent, no dict entry, no
code.

Honesty rules, pinned by tests:

- **No matching policies is a refusal, never a pass** — "Atlas has no configuration policies for X."
- A device the engine could not judge stays **unknown, with the engine's own reason**.
- **A device that does not run the subject is *not applicable*, never compliant** (PR-172, R1) —
  a minority protocol's verdict is decided by its real speakers, not drowned by the devices that
  never ran it.
- Devices in scope with no configuration evidence are **counted and named** — "not judged" is part
  of the answer.
- A rule the masked configuration view blinds (its pattern contains a sensitive term such as
  `password` or `community`) **never enters a verdict** — refused at the capability seam (R9).

The verdict is a **projection**, computed and never stored: Compliant · Non-compliant · Partially
verified · Not enough evidence · Not applicable · Unsupported, each mapped onto an existing
Experience-Language chip. See `docs/ATLAS_VALIDATION_FRAMEWORK.md` for the full framework.

**Current rule coverage: OSPF and BGP** (one starter rule each). Every other subject is an honest
refusal naming what Atlas *can* validate — sourced live from the capability registry.

## Part 1 — Structured question understanding

`investigation/extraction.py` extracts, from fixed vocabularies and shapes:

| Field | How |
|---|---|
| protocol | BGP, OSPF, EIGRP, IS-IS, HSRP/VRRP, STP, VPN/IPsec, MPLS, LLDP/CDP, DNS, DHCP, NTP, SNMP |
| source / destination | `between X and Y`, `from X to Y`, `can X reach Y`, `X cannot reach Y`, `X unreachable from Y` |
| sites | only names Atlas knows (see the scope vocabulary below) |
| interfaces | `Gi0/1`, `GigabitEthernet0/0/1`, `eth2`, `ge-0/0/1`, `port-channel10`, … |
| VLANs / VRFs | `vlan 300`, `vrf CUSTOMER` |
| applications | HTTPS, HTTP, SSH, SAP, Citrix, voice, video, backup, email, file sharing |
| addresses | IPv4, with or without a prefix length |
| time range | last hour / last 24 hours / yesterday / last week / last month |
| severity | down, unstable (flapping), degraded, slow |
| direction | inbound, outbound |

Single alphanumeric terms match on word boundaries, so `bgp` never fires inside a longer token.

## Part 2 — Entity resolution

`investigation/resolution.py` resolves each name to exactly one of three outcomes:

- **RESOLVED** — one site or device matches.
- **AMBIGUOUS** — several match. Every candidate is reported and the investigation says so. Choosing one would be a
  guess wearing a fact's clothing.
- **UNKNOWN** — nothing matches. Atlas says precisely that, and does **not** answer a different question instead.

The ladder is: discovered site → canonical device (via `resolve_canonical_device`, which reports its own ambiguity)
→ hostname grouping → UNKNOWN.

### The hostname grouping, and why it is labelled

Many estates encode location in the hostname (`chennai-regional-edge`) while Atlas's site inference has assigned
nothing — on such a graph every device reads `unknown` and a site-named question would be unanswerable although the
evidence is plainly there. So when no real site matches, devices are grouped by leading hostname token.

That basis is **weaker than an assigned site**, so the entity carries the sentence *"Atlas has not assigned sites in
this enterprise, so this grouping is by naming convention, not by a discovered site"* — and every answer built on it
repeats that in its limitations. A stated assumption, never a silent one.

## Parts 3, 6 — The plan and its execution

Every investigation builds an `InvestigationPlan` **before** executing, and the plan is shown to the operator with
each step's outcome:

- `done` — the step ran and contributed.
- `skipped` — an optional step with nothing in scope.
- `blocked` — the step could not run; the reason is stated and the gap recorded.

## Part 4/5 — Multi-engine execution over shared context

`InvestigationContext` carries the resolved entities, the device ids in scope, accumulated facts, findings, gaps and
citations. Devices resolve once; every later step reuses them. Engines available today:

| Engine | Reads |
|---|---|
| `graph` | sites, devices, interfaces (status, addressing) |
| `routing` | per-device `routing_evidence`: BGP sessions, OSPF adjacencies |
| `topology` | discovered links between the endpoints |
| `path` | **Path Intelligence** — walks the path hop by hop against captured routing tables |
| `changes` | recorded change counts |

Path Intelligence is *orchestrated*, not replaced: for reachability it is far stronger than reading links, so the
connectivity template calls it and wraps it with interface and change context.

## Part 7 — Templates

| Template | Chosen when | Answers |
|---|---|---|
| `bgp-between` | protocol BGP + two endpoints | sessions between them, states, AS numbers, accepted prefixes |
| `bgp-scope` | protocol BGP + one scope | every observed session for that scope |
| `ospf-scope` | protocol OSPF | adjacencies and their states |
| `connectivity-between` | two endpoints, no protocol | hop-by-hop path walk, links, interfaces, changes |
| `site-scope` | a named site or device | devices, interfaces, routing evidence, changes |

Selection is specific-first: protocol + endpoints, then protocol + scope, then endpoints, then a named scope, then
**None**.

## Part 8 — Smart answers

A BGP question produces a BGP answer:

> BGP between mumbai and hyderabad: 2 session(s) observed, 2 established. 1 interface(s) in scope are reported down.

with per-session findings naming the peer, both AS numbers, the state and the accepted-prefix count. A test asserts
the summary contains no estate-wide phrasing (`managed device(s)`, `discovery`).

## Part 9 — Missing information

Stated exactly, never substituted:

- *"Atlas found no BGP peering between Chennai and Bengaluru. 2 BGP session(s) exist at Chennai, none of them to Bengaluru."*
- *"Atlas has not discovered anything called “Atlantis” — no site, device, alias or address matches it."*
- *"Atlas has discovered no direct link between Chennai and Bengaluru. They may still be connected through devices Atlas has not discovered."*

### The evidence limits Atlas always declares

- **BGP:** Atlas collects `show bgp summary`. It knows state, peer, AS numbers and accepted prefixes. It does **not**
  know advertised prefix counts, session uptime or last-flap times — stated on every BGP answer.
- **OSPF:** the neighbour output collected does not carry the area, so adjacencies are reported without one.
- **Interfaces:** status and addressing only — no error counters, utilisation or optical levels.

## Part 11 — The investigation panel

The Advisor shows, above the summary: the plan title and objective, each resolved entity with its status and detail
(including ambiguity candidates), every planned check with its outcome, and the findings with deep links.

## Part 12 — Performance

Investigations are **reads over stored evidence**. They never re-run discovery and never touch a device. The graph
and snapshot are the ones the page already loaded; devices resolve once and are reused by every step. Typical
runtime on an 85-device estate is a few milliseconds; the only slower path is the hop-by-hop path walk.

## Schema

`AdvisorResponse` gained an **additive** `investigation` block (schema `1.2.0`). No key has ever been renamed or
removed, so conversations stored under 1.0.0 and 1.1.0 still render.

## Remaining limitations

- **Investigation history is the conversation history.** Stored answers carry their full investigation (plan,
  entities, findings, gaps), so they can be reopened and read — but there is no dedicated history page, no replay
  button that re-executes a plan, and no per-run duration index.
- **Cancellation is not implemented.** Investigations are short synchronous reads; there is no long-running job to
  cancel. A future engine that is genuinely slow would need one.
- **Five templates, not ten.** Routing (BGP/OSPF), connectivity and scope investigations ship. Policy, identity,
  configuration, discovery, performance, security, maintenance and risk investigations are named in the spec but
  would each need their engine adapter written; today those questions keep their existing single-engine answers.
- **No VRF or VLAN investigation.** Both are extracted from the question, and neither is modelled in the enterprise
  graph, so nothing can yet be investigated with them.
- **Applications are extracted but not investigated.** Atlas holds no application telemetry; a "why is HTTPS slow"
  question extracts the application and severity, then honestly reports what network evidence exists.
- **BGP peering is matched by peer address** against the far endpoint's management, interface and router-id
  addresses. A session peering to an address Atlas never discovered cannot be attributed to a site.
- **Site overrides are not applied to the federated graph** (a pre-existing Atlas behaviour), so operator-curated
  site membership shown on the topology page can differ from what the investigator resolves.
