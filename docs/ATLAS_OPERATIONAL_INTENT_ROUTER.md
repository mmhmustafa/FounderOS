# Atlas Operational Intent Router (OIR) — codename INTENT (PR-164)

The OIR is Atlas's **single workflow-orchestration platform service**. It
understands the operator's GOAL — deterministically, from their own words
and known enterprise entities — and routes them into the workflow that
serves it. Every routing decision carries its confidence and its WHY.

**No AI. No fuzzy matching. No guessing.** A question no rule claims routes
to the honest Unknown intent.

## Architecture

```
question ──▶ founderos_atlas.oir.detect()
              │
              ├─ Layer 1: ENGINE RESOLUTION  (catalog.ENGINE_RULES)
              │    The proven fixed-order phrase table that has routed
              │    Advisor questions since PR-042, moved here VERBATIM.
              │    First match wins. Decides which answering engine runs.
              │
              ├─ Layer 2: INTENT REFINEMENT  (registry families)
              │    Within the engine's registered family, refine_keywords
              │    (word-start matches) and declared entity signals pick
              │    the finest intent. No signal → the family's base
              │    intent (its first registration). Ties break toward the
              │    earlier registration. Refinement never changes engines.
              │
              ├─ ESCALATION (only when Layer 1 found nothing):
              │    one pass over declared fallback_keywords — how
              │    "Why is BGP unstable?" reaches BGP Investigation and
              │    "Can I reboot Core1?" reaches Risk Assessment instead
              │    of Unknown — at MEDIUM confidence, because the intent
              │    was inferred from keywords, not a workflow phrase.
              │
              └─▶ IntentRoute { intent, engine, confidence, why, escalated }
```

- `founderos_atlas/oir/registry.py` — the registration contract
  (`IntentDefinition`, `IntentRegistry`).
- `founderos_atlas/oir/catalog.py` — `ENGINE_RULES` + the built-in
  catalog (`DEFAULT_REGISTRY`, ~25 intents).
- `founderos_atlas/oir/detection.py` — `detect()` and `IntentRoute`.
- `founderos_atlas/oir/analytics.py` — record-only usage telemetry.

## Routing confidence (of the ROUTING, not the answer)

| Confidence | Meaning |
|---|---|
| High | A direct workflow phrase matched (Layer 1). |
| Medium | No direct phrase; the intent was inferred from declared fallback keywords (escalated). |
| Unknown | Nothing matched. Atlas will not guess. |

Answer confidence is a separate fact computed by the answering engine
from its evidence; the GUI shows both and never blends them.

## The intent catalog

Health family: Enterprise Health · Site Health (selected by a NAMED KNOWN
SITE, not keywords) · Routing / BGP / OSPF / WAN / LAN Investigation ·
Policy Compliance. Connectivity: Connectivity Validation. Changes: Change
Analysis · Timeline Review · Configuration Comparison. Search: Device
Lookup · Configuration Review · Interface Investigation · Evidence
Lookup. Discovery: Discovery Health. Maintenance: Maintenance Planning ·
Risk Assessment. Continuation: Resume Investigation · Incident
Investigation. Enterprise: Inventory · Identity Resolution. Honest gaps:
Performance Investigation and Security Investigation (they answer
honestly — Atlas holds no performance/security-event telemetry — and
route to the workflows that CAN help: timeline, paths, policy, audit).
Fallback: Unknown.

Every definition declares: description, examples, the evidence it needs,
the workflows that serve it, recommendations and follow-ups **each with a
WHY**, its confidence rule, and its honest limitations.

## Consumers

**Advisor** (first consumer): `advisor/router.classify()` delegates to
the OIR (the old rule table physically moved to `catalog.ENGINE_RULES`;
behaviour pinned by the existing routing tests). `engine.answer()`
attaches the route ADDITIVELY to the stored response as
`operational_intent` (schema 1.1.0 — no existing key renamed; 1.0.0
conversations still render). The Advisor page shows the intent chip, the
routing why, a domain-aware summary heading, named operational checks,
and the intent's recommendations with their reasons.

## Workflow analytics — record-only

`oir-analytics.jsonl` in the workspace output directory records
`detection` events (intent, confidence, engine, scope, duration) and
`choice` events (which recommended workflow the operator opened, via
`POST /api/advisor/workflow-choice`). Append-only JSON lines,
best-effort (a write failure never breaks answering).

**This data is never used for AI learning.** Routing stays the
deterministic catalog; nothing trains, weights, or adapts.

## Governance — how future modules integrate

1. Register an `IntentDefinition` (unique key) in the catalog — or call
   `IntentRegistry.register()` on a purpose-built registry for tests.
2. Do **NOT** implement your own intent detection.
3. Do **NOT** duplicate detection logic elsewhere.
4. Do **NOT** modify Advisor — it already reads the catalog.
5. Declare honest `limitations` for anything your intent cannot see;
   they surface with every answer of that intent.
6. Detection stays deterministic because a definition can only declare
   phrases/keywords/entities — never code.

Adding an intent is additive: new keys, new phrases. Changing
`ENGINE_RULES` changes pinned Advisor behaviour — don't, unless the
routing tests move with it deliberately.
