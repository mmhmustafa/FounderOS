# Atlas Operational Intent Router (OIR)

Codename INTENT (PR-164), hardened as a platform service by **PR-164.1 FOUNDATION**.

The OIR is Atlas's **single, authoritative workflow-orchestration platform service**. It understands the operator's
GOAL — deterministically, from their own words and known enterprise entities — and routes them into the workflow that
serves it. Every routing decision carries its confidence and its WHY.

**No AI. No fuzzy matching. No guessing.** A question no registration claims routes to the honest Unknown intent.

## Public interface (Part 6)

Consumers depend on **`OperationalIntentRouter`** and nothing else:

```python
from founderos_atlas.oir import default_router

route = default_router().route("Can Mumbai reach Chennai?", sites=graph.sites)
route.intent.name      # "Connectivity Validation"
route.engine           # "path"          — the EXECUTION engine that answers
route.confidence       # "High" | "Medium" | "Unknown"  (routing confidence)
route.why              # every matched signal, in order
route.escalated        # True when inferred from fallback keywords
```

`default_router()` is the process-wide instance over the default capability catalog — built once (registration →
validation → freeze), then immutable. Consumers today: the Advisor (`advisor/router.route()` delegates here).
Tomorrow: REST APIs, CLI, automation, mobile, a future AI layer — all through this same surface. Internal modules
(`registry`, `detection`, `bootstrap`, `validation`, `catalog`) may evolve; this surface stays stable.

## Intent resolution vs workflow execution (Part 7)

These are different jobs, deliberately separated:

- **OIR resolves INTENT** — *what is the operator trying to accomplish.* Its output is an `IntentRoute`: an intent,
  the name of an execution engine, a confidence, and the why. OIR never touches evidence and never executes anything.
- **Execution engines perform the WORK** — *how Atlas does it.* Today those are the Advisor engine's handlers
  (health/path/changes/search/discovery/compass/prediction/continue/investigation/enterprise/unknown), each of which
  orchestrates existing Atlas services and cites evidence. A future consumer (API, automation) maps `route.engine`
  onto its own execution however it chooses.

## Registration model (Part 1) — one declarative source of truth

Everything the router knows comes from `IntentDefinition` registrations. A definition may declare:

| Field | Meaning |
|---|---|
| `name`, `key`, `description`, `examples` | Identity and documentation. |
| `capability` | The owning Atlas capability (diagnostics + accountability). |
| `engine`, `domain` | The execution engine that answers; the answer-layout family. |
| `routing_phrases`, `routing_priority` | DIRECT routing phrases and their explicit precedence (lower fires first; priorities are unique; phrases have one owner). |
| `default_for_engine` | The ONE intent per engine a bare engine match falls back to. |
| `refine_keywords`, `refine_entities` | Signals that pick this intent WITHIN its engine family (single tokens match at word starts; `("site",)` matches a NAMED KNOWN site). |
| `fallback_keywords` | Escalation signals used only when no direct phrase matched (Medium confidence). |
| `objective` | PR-171: WHAT KIND of answer this intent wants — `validate`, `assess` (default), `locate`, `explain`, `compare` or `forecast`. Validated at freeze against the controlled vocabulary. The engine says WHERE the answer comes from; the objective says WHAT SHAPE it takes — and the Advisor dispatches on `(engine, objective)`, falling back to the engine alone. Every pre-PR-171 intent declares the default, so their dispatch is byte-for-byte unchanged. Before this field, the resolved intent was never consulted at execution time: Atlas recognised "OSPF" in a configuration question and still answered with the enterprise summary. |
| `required_evidence` | Canonical evidence kinds (validated against `oir/vocabulary.py`). |
| `workflows`, `recommendations` | The workflows that serve the intent — each with a WHY (hrefs validated against the known workflow surfaces). |
| `followups` | Suggested next questions. |
| `confidence_rule`, `limitations` | The honest confidence story and standing blind spots. |

## Data-driven routing (Part 2)

There are **no static routing tables**. The routing table is *derived* at freeze from every registered intent's
`routing_phrases`, ordered by `routing_priority`. Detection then runs three deterministic steps:

1. **Direct routing** — first phrase hit across the priority-ordered derived table, **anchored at a word start**
   (PR-171). Bare substring containment ran first and at High confidence, so "security **breach**" selected the
   connectivity engine (it contains "reach") and "inventory of ex**changes**" selected the change engine — silent,
   confident misroutes with no escalation flag. A phrase can no longer fire from the middle of a longer word;
   registered prefix-style phrases ("scan ", "how is ") still work because the anchor is at the start only. Phrases
   shorter than 4 characters are refused at freeze. A phrase owned by an engine's
   default intent resolves the engine and continues to refinement; a phrase owned by a specific intent selects that
   intent outright.
2. **Refinement** — within the engine's registered family, `refine_keywords`/`refine_entities` pick the finest
   intent; no signal → the engine's declared default. Ties break toward the earlier registration.
3. **Escalation** — only when nothing matched directly: one pass over `fallback_keywords`, at **Medium** confidence,
   flagged `escalated` (how "Why is BGP unstable?" reaches BGP Investigation instead of Unknown).

Behavioural equivalence with the pre-FOUNDATION fixed table is pinned by `tests/test_oir.py::
test_derived_table_equals_the_legacy_table_verbatim` — engine for engine, phrase for phrase, in first-match order.

## Registry lifecycle (Part 3)

```
Startup → Module Registration → Validation → Freeze → Runtime
```

- `build_default_registry()` runs every capability registrar, in order, into a fresh **open** registry.
- `registry.freeze()` validates EVERY registration and derives the routing table. It raises
  `RegistryValidationError` listing every problem at once — fail fast, before a single question is routed. Even a
  declaration that defeats the field checks but cannot serialise fails as a `RegistryValidationError` naming the
  intent, and never leaves half-derived state behind.
- After freeze the registry is **immutable**: `register()` raises `RegistryFrozenError`, loudly and clearly.
- Routing requires a frozen registry — `detect()` refuses an open one. Resolution only ever runs against a
  validated, immutable catalog; that is what makes it deterministic and auditable.
- **Concurrency**: `default_router()` uses double-checked locking — concurrent first calls on a threaded server all
  receive the SAME frozen router. The bootstrap's circular-registration guard is per-thread, so genuine recursion is
  caught while legitimate parallel builds (tests, embedders) are not misdiagnosed.
- **Startup warm-up**: `create_app()` calls `default_router()` — a registration problem crashes the app at startup,
  loudly, instead of returning a 500 to the first operator question; the one-time catalog build also leaves the
  first request's latency untouched.
- **Registry version** is a content hash over the COMPLETE declaration (including refine/fallback keywords and
  entities): a catalog that routes differently always versions differently.

## Capability-owned registration (Part 4)

Registrations live with their owners — `founderos_atlas.<capability>.intents`, each exposing `CAPABILITY` and
`register(registry)`, importing **nothing but the OIR contract**:

| Module | Registers |
|---|---|
| `health.intents` | Enterprise Health, Site Health |
| `routing.intents` | Configuration Validation (PR-172: ONE subject-free intent, registered first so validation wording wins fallback ties against protocol intents) / Routing / BGP / OSPF / WAN / LAN Investigation |
| `policy.intents` | Policy Compliance |
| `path_intelligence.intents` | Connectivity Validation, Resume Investigation |
| `change.intents` | Change Analysis, Timeline Review, Configuration Comparison, Configuration Review |
| `search.intents` | Device Lookup, Interface Investigation, Evidence Lookup |
| `discovery.intents` | Discovery Health |
| `compass.intents` | Maintenance Planning |
| `prediction.intents` | Risk Assessment |
| `incidents.intents` | Incident Investigation |
| `enterprise.intents` | Inventory |
| `identity.intents` | Identity Resolution |
| `telemetry.intents` | Performance Investigation (honest: no telemetry unless an adapter is configured) |
| `audit.intents` | Security Investigation (honest: policy + audit evidence, no live security events) |
| `oir.registrations` | Unknown (the platform's honest fallback) |

`oir/bootstrap.py` only lists WHO registers and in WHAT ORDER (ties break toward earlier registration — the order is
part of the contract). Re-entrant bootstrap (a registrar triggering registration) is detected and refused.

## Validation (Part 5)

At freeze, across the whole set: duplicate intent keys and names; duplicate routing phrases (one phrase, one owner);
missing or conflicting routing priorities (must be explicit and unique); unknown workflow references (href paths
checked against `KNOWN_WORKFLOW_PATHS`); unknown evidence kinds (checked against `EVIDENCE_KINDS`); workflows without
labels or whys; follow-ups without questions; engines without exactly one `default_for_engine`. Every problem is
reported in one pass. Extending the workflow or evidence vocabulary is a deliberate edit to `oir/vocabulary.py`.

## Registry diagnostics (Part 8)

`OperationalIntentRouter.diagnostics()` — also served at **`GET /api/oir/diagnostics`** (SYSTEM_ADMIN) — reports:
registry version (deterministic content hash — identical declarations hash identically), frozen/validation state,
intent count, capability ownership map, the registrar list, the full derived routing table with priorities, engine
defaults, every workflow surface referenced, and startup duration.

## Workflow analytics — record-only (Parts 9–10)

`oir-analytics.jsonl` in the workspace output directory records `detection` events (every ask) and `choice` events
(which recommended workflow the operator opened, via `POST /api/advisor/workflow-choice`). Hardened:

- every record carries `schema` (`ANALYTICS_SCHEMA_VERSION`), stamped by the recorder LAST — payload keys can never
  forge the provenance markers;
- input is validated and bounded — flat JSON scalars only (non-finite floats dropped), values truncated at 300
  chars, field count capped;
- the file rotates at 5 MB keeping 3 numbered backups, under a write lock (bounded retention by construction);
- recording is best-effort: **analytics can never impact routing or answering**;
- the choice endpoint is rate-limited, size-caps and type-checks its body BEFORE parsing (a non-object JSON document
  is a clean 400, an oversized body a 413 — never a 500), and rejects external URLs, scheme-relative tricks,
  backslashes, traversal, unknown workflow areas, unknown intent names, and oversized fields;
- the click beacon carries the CSRF token in its JSON body (sendBeacon cannot set headers), so recording works in
  password mode without weakening the CSRF regime — and ordinary clicks never masquerade as CSRF denials in the
  audit log;
- **never used for AI learning**: routing stays the deterministic catalog; nothing trains, weights, or adapts.

Layering note: `safe_redirect_target` moved to the package-neutral `founderos_atlas.redirects` (the web module
re-exports it), so the capability bootstrap no longer drags the web layer into headless OIR consumers.

## Extending Atlas (future extension guidelines)

1. Create `founderos_atlas.<your_capability>.intents` with `CAPABILITY` and `register(registry)` declaring
   `IntentDefinition` data — phrases, keywords, workflows, evidence, whys, limitations. Data only, never code.
2. Add the module to `bootstrap.CAPABILITY_REGISTRARS` (order matters only for refinement/fallback tie-breaks).
3. New workflow surface or evidence kind? Add it to `oir/vocabulary.py` first — validation will hold you to it.
4. New direct phrases need an unused, explicit `routing_priority`; changing EXISTING phrases changes pinned Advisor
   behaviour — the equivalence test will tell you.
5. Do **NOT** implement your own detection, do **NOT** duplicate routing knowledge, do **NOT** modify Advisor.
6. Declare honest `limitations` for anything your intent cannot see; they surface with every answer of that intent.
7. Run `tests/test_oir.py` — the lifecycle, validation, and equivalence pins are your safety net.
