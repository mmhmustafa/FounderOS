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
