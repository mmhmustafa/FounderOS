# PRISM — The Atlas Evidence Presentation Platform

PRISM is **not an AI assistant**, not conversational AI, and not autonomous reasoning. It is the platform that lets
optional presentation capabilities exist safely inside Atlas: provider abstraction, settings, capability and prompt
registries, privacy enforcement and redaction, cost and token accounting, model management, diagnostics,
governance, auditing, and feature gating.

## The philosophy

> **A prism never changes light. It reveals different views of the same light.**

Likewise, PRISM never changes Atlas evidence. It presents the same evidence differently while preserving every
conclusion, confidence, uncertainty and provenance.

| Atlas | PRISM |
|---|---|
| **discovers** facts | **explains** facts |
| **validates** facts | **summarizes** facts |
| **proves** facts | **translates** facts |
| | **never invents** facts |

**Atlas determines. PRISM explains.** Atlas is responsible for discovery, correlation, investigation, evidence,
confidence, workflow routing and every deterministic conclusion. PRISM is responsible only for presenting that
evidence in forms appropriate for different audiences.

**Atlas functions correctly without PRISM, and that is the default.** Disabling PRISM restores existing Atlas
behaviour exactly — no capability anywhere in Atlas depends on it.

## Architecture

```
Operator
   ↓  (optional AI: question rewriting)
Operational Intent Router          ← deterministic, PR-164/164.1
   ↓
Atlas engines
   ↓
Evidence
   ↓  (optional AI: explanation, summary, translation)
Operator
```

Atlas always determines the facts. AI may only assist interpretation.

| AI may | AI must never |
|---|---|
| Interpret, summarize, explain | Invent or modify evidence |
| Translate, rephrase | Override an Atlas conclusion |
| Generate report narrative | Create devices or topology |
| Suggest questions, assist conversation | Execute configuration changes |
| | Alter workflow routing |
| | Hide uncertainty |

When Atlas does not know something, AI must preserve that. This is enforced in three independent places: the
non-optional [safety preamble](#prompt-registry-part-7) on every prompt; the fact that the provider contract can
express nothing but text-in/text-out; and the service returning an honest refusal rather than substitute content
whenever anything is missing.

## Modules

| Module | Responsibility |
|---|---|
| `prism/contract.py` | The provider contract: `AIRequest`, `AIResult`, `ProviderHealth`, `ProviderSettings`, `AIProviderError`. |
| `prism/providers.py` | Built-in providers + `ProviderRegistry`. stdlib `urllib` only — PRISM adds **no dependency**. |
| `prism/config.py` | `PrismConfig`, governance policy, feature flags, and the metadata/secret split. |
| `prism/redaction.py` | The privacy engine: mandatory and optional redaction with a counted report. |
| `prism/prompts.py` | Managed, versioned prompts + the safety preamble. |
| `prism/capabilities.py` | The AI capability registry, each with its deterministic fallback. |
| `prism/usage.py` | Cost estimation and the append-only AI audit ledger. |
| `prism/service.py` | `PrismService` — the stable public interface, diagnostics, and fallback contract. |

## Public interface (Part 15)

Consumers depend on `PrismService` and nothing else — never a provider, a prompt, or a key:

```python
from founderos_atlas.prism import CAPABILITY_PLAIN_ENGLISH, PrismService

service = PrismService(workspace_root=..., output_dir=...)
result = service.enhance(
    CAPABILITY_PLAIN_ENGLISH,
    {"finding": answer_summary, "confidence": answer_confidence},
    known_names=graph.device_names,      # for hostname redaction
    evidence_version=snapshot_id,
)
if result.ok:
    show(result.text)                    # an enhancement
else:
    show_atlas_own_output()              # result.fallback says what that is
```

`enhance()` **never raises** for an operational problem and never returns invented content. `ok=False` is a normal
outcome carrying `reason` (why) and `fallback` (what Atlas does instead). Future consumers — REST, CLI, automation,
mobile, agents — use this same surface; none of them couple to a provider.

## Three modes (Part 1)

| Mode | Meaning |
|---|---|
| **AI disabled** | Default. Nothing is configured, nothing is sent, no capability runs. |
| **Local AI** | Customer-hosted: Ollama, vLLM, LM Studio, any OpenAI-compatible server. Nothing leaves the network. |
| **Cloud AI** | OpenAI, Azure OpenAI, Anthropic, Google Gemini, OpenRouter. Requires the cloud-provider policy to be enabled. |

The mode is *derived* from the selected provider's declared `hosting`, so it cannot disagree with reality.

## Provider abstraction (Parts 2–4)

Every provider implements one contract: `complete(AIRequest) -> AIResult` and `health() -> ProviderHealth`. Built-in
kinds: `disabled`, `openai`, `azure-openai`, `anthropic`, `gemini`, `openrouter`, `openai-compatible`, `ollama`,
`lm-studio`, `vllm`. Settings cover endpoint, model, authentication, TLS verification, timeout, retries, max
context, organization, region and API version.

**OpenRouter** is a hosted aggregator: one API key reaches many upstream models, named with a vendor-qualified id
such as `anthropic/claude-sonnet-4` or `meta-llama/llama-3.3-70b`. Put that id in the **Model** field and leave the
endpoint at its default. It is classified `cloud` — and deliberately so twice over, because the prompt goes to
OpenRouter *and* on to the upstream vendor — so the "permit cloud AI providers" governance switch blocks it exactly
like any other third party. Atlas sends an `X-Title` header so the calls are identifiable in your own OpenRouter
dashboard; it carries no evidence and no operator identity.

A future provider registers a `ProviderDescriptor` — no existing code changes:

```python
registry.register(ProviderDescriptor(
    kind="acme-llm", label="ACME", factory=AcmeProvider, hosting="local",
    needs_endpoint=True, default_endpoint="http://localhost:9000/v1",
))
```

**HTTP is stdlib `urllib`** deliberately: a disabled feature has no business adding a dependency, and Atlas ships
with only `jsonschema` and `PyYAML` at its core. TLS verification is on by default; only an explicit customer
setting (for a self-signed local endpoint) turns it off.

## Model management (Part 5)

Configured model, context window, temperature, maximum output, timeout, retries and TLS are all settings. The
connection test lists the models the provider actually offers. `PrismService.reload()` re-reads configuration, so
**changing model or provider needs no restart**.

## AI capability registry (Part 6)

AI is never globally "on". Capabilities register individually and each is enabled separately:

| Capability | Fallback when unavailable |
|---|---|
| Plain English explanation | Atlas shows its deterministic answer with evidence, confidence and limitations. |
| Executive summary | Atlas shows the per-dimension health summary and its evidence. |
| Incident summary | Atlas shows the incident timeline and evidence entries in order. |
| Report narrative | Atlas exports the report's tables and figures without prose. |
| Question rewriting | The OIR classifies the question as typed, and says so honestly when nothing matches. |
| Translation | Atlas presents answers in English. |
| Conversation | *(registered, not available in this release)* Advisor answers one evidence-backed question at a time. |

The fallback is not a degraded mode — with AI off, the fallback **is** the product.

Question rewriting deserves emphasis: AI may rewrite the operator's words, but the rewritten question is then routed
by the deterministic Operational Intent Router exactly as a typed one. **AI never selects the workflow.**

## Prompt registry (Part 7)

Prompts are managed data: name, version, purpose, declared variables, safety rules, supported models, fallback and
owner. Every AI audit record names the prompt version that produced the answer. Updating a prompt is a registration
change, and re-registering the same version is refused — bump the version.

Every rendered prompt begins with `SAFETY_PREAMBLE`, which cannot be switched off (there is no field for it):

> Atlas — not you — determines every fact. Use ONLY the Atlas findings provided. Never add devices, addresses,
> counts, causes or events not present in them. Never contradict, soften or override an Atlas conclusion. Preserve
> uncertainty exactly as Atlas states it… If the findings are insufficient, say so plainly instead of producing a
> plausible answer.

A missing prompt variable is an error, never an empty substitution: an empty prompt is exactly how a model starts
inventing.

## Privacy and redaction (Part 8)

Redaction happens **inside the service**, not in the caller — a privacy guarantee that depends on every consumer
remembering to call it is not a guarantee. A provider is only ever handed text that has already been redacted.

**Mandatory (always, every provider, not configurable):** passwords and enable secrets, API keys and bearer tokens,
SNMP communities, PEM private keys, and credentials embedded in URLs.

**Optional (customer policy):** IP addresses, hostnames, usernames, MAC addresses.

Hostname redaction uses Atlas's **known** device and site names plus strict dotted FQDNs. It deliberately does not
guess at bare single-label words: `snmp-server` and `read-only` are not hostnames, and a guessing rule mangles the
very text it is meant to protect.

Redacted values become stable placeholders (`[redacted:ip-1]`) — consistent within one request, so a model can still
reason about "the same device" without learning its address. Every redaction is counted and the counts are shown to
the operator and recorded in the audit.

### Semantic redaction (PR-166.2)

A placeholder protects an identifier by destroying it, and the resulting explanation is safe but unreadable. PRISM
now replaces values Atlas can describe with a **meaningful alias** built only from metadata it already holds — "the
Mumbai Core Router" rather than `[redacted:hostname-1]` — governed by three **privacy profiles** (Internal, Cloud,
High security) with a per-field policy of Preserve / Semantic alias / Mask / Remove. Secrets remain outside that
policy entirely: no profile, override or form control can preserve one.

What the provider receives and what an authorised Atlas operator reads are deliberately **not the same thing**: the
operator sees the alias annotated and linked back to the real object, gated by the permissions they already hold.

See **[ATLAS_PRISM_SEMANTIC_REDACTION.md](ATLAS_PRISM_SEMANTIC_REDACTION.md)** for the full design, the profile
table, the RBAC rules and the architecture diagram.

## Cost management and AI audit (Parts 9–10)

One append-only ledger, `prism-usage.jsonl`, in the workspace output directory (5 MB rotation, 3 backups). Each
call records: timestamp, capability, provider, model, **prompt version**, outcome, redaction policy and count, input
and output tokens, estimated cost, latency, retries, and the Atlas evidence version.

**Never recorded:** prompt text, response text, API keys, or any redacted value — enforced structurally by a
forbidden-field filter. An audit trail that quotes prompts becomes a second copy of your evidence with none of the
evidence store's protections.

Cost is an **estimate**, labelled as one: Atlas multiplies the operator's configured per-million rate by the token
counts the provider reports. When a provider reports no tokens or no rate is set, the cost is `None` — Atlas does
not invent a number to fill a column, and the dashboard shows how many calls it could actually price.

## Governance (Part 11) and feature flags (Part 12)

Administrators may: enable/disable AI; enable individual capabilities; restrict which providers may be selected;
restrict which models may be used; and forbid cloud providers entirely (`allow_cloud_providers`), which blocks any
external AI communication regardless of what else is configured. Policy lives in the configuration, so it is
auditable — and it is enforced in the service's gate, not merely in the UI.

## Secret handling

The API key is **never** in `prism.json`. It goes to Atlas's existing `CredentialProvider` (OS keyring, or
AES-256-GCM encrypted file) under `atlas-prism:<provider-kind>`, exactly like device credentials. If no secure
store is available, saving fails loudly — Atlas has never written a secret in the clear and PRISM does not
introduce the first one. The metadata store additionally rejects secret-named keys structurally.

## Diagnostics (Part 13)

`GET /api/prism/diagnostics` (system-admin; add `?probe=1` for a live provider health check) reports mode,
provider, hosting, model, endpoint, authentication state (never the key), TLS, timeout, context window, redaction
policy, configuration problems, every registered provider/prompt/capability with its enabled and usable state, and
the usage summary.

## Fallbacks (Part 14)

If AI is unavailable — disabled, misconfigured, unreachable, rate-limited, or crashing — only the AI enhancement is
disabled. Atlas functionality is never disabled. A provider that raises an unexpected exception is caught: a
third-party client library must not be able to break a page.

## Web surface

| Route | Permission | Purpose |
|---|---|---|
| `GET /settings/ai` | `pages.view` | AI settings + transparency (what is enabled, what is redacted, what the fallbacks are). |
| `POST /settings/ai` | `settings.manage` | Save AI policy, capabilities, redaction and cost settings. |
| `POST /settings/ai/key` | `system.admin` | Store or remove the provider API key. |
| `POST /settings/ai/test` | `system.admin` | Connection test (no evidence, no prompt — only reachability and auth). |
| `GET /api/prism/diagnostics` | `system.admin` | Diagnostics JSON. |

The page is readable by every role on purpose: an operator should be able to see whether AI is on and exactly what
leaves the network, without holding administrative rights.

## Extending PRISM

1. **New provider** — implement `complete`/`health`, register a `ProviderDescriptor` with the honest `hosting`.
2. **New capability** — register an `AICapability` naming its prompt and, above all, its deterministic `fallback`.
3. **New prompt** — register a `PromptTemplate` with a new version; the safety preamble is applied for you.
4. **New redaction rule** — add it to `OPTIONAL_RULES` with a label; mandatory rules are for credentials only.
5. Never bypass `PrismService` — redaction, governance, feature flags and auditing all live in its gate.
6. Never make an Atlas capability depend on AI. If it cannot degrade to a deterministic fallback, it is not an AI
   capability.

## Remaining limitations

- **No consumer ships enabled in PR-165.** PRISM is the platform; wiring Advisor's plain-English enhancement into
  the answer page is a separate, deliberately separate, change.
- **Token counts come from the provider.** Providers that report none leave token and cost columns empty rather
  than estimated — honest, but incomplete for such providers.
- **The connection test lists models**; it does not verify that the configured model can actually serve a
  completion, because that would mean spending tokens on a settings page.
- **Prompts are registered in code.** They are data, and updating one needs no consumer change, but editing prompts
  from the GUI is not offered — that would make the audit trail's prompt version unverifiable.
- **Conversation** is registered for governance visibility only; enabling it changes nothing yet.
- Rotated usage ledger backups are not merged into the dashboard summary, which reads the current file.
