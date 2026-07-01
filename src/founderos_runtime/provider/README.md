# FounderOS Mock Provider

## Purpose

A Provider is an outbound adapter that accepts a canonical structured generation request and returns a canonical response. The Mock Provider simulates that boundary locally and deterministically without calling a model, network service, subprocess, or external system.

```python
from founderos_runtime.provider import MockProvider, ProviderRequest

provider = MockProvider()
response = provider.generate(
    ProviderRequest(
        request_id="req-001",
        operation="discovery.summarize",
        input={"candidate": "Example"},
        correlation_id="command-001",
        idempotency_key="summary-001",
    )
)
```

## Why It Exists

Provider-based workflows need stable contracts and failure behavior before real AI integration is safe. The Mock Provider proves request/response shape, output-schema checks, correlation, idempotency metadata, fixtures, and failures while keeping tests fast, offline, cost-free, and reproducible.

Real OpenAI, Claude, Gemini, Ollama, or other adapters are intentionally absent. They introduce authentication, secrets, cost, latency, rate limits, data disclosure, cancellation, retries, and ambiguous external outcomes that require authorization and durable Activity enforcement first.

## Contracts

- `ProviderRequest` contains request identity, operation, structured input, optional expected output schema, metadata, correlation ID, and idempotency key.
- `ProviderResponse` contains request identity, status, structured output or error, deterministic metadata, and exact Provider name/version.
- `ProviderStatus` is `success` or `error`.
- `ProviderError` is structured response data with a stable code, safe message, retryability, and JSON details.
- `MockProvider` provides deterministic fallback output, strict fixture responses, and simulated failures.

Contracts are frozen and recursively protect mappings/lists. `thaw` returns a defensive JSON-compatible copy when a caller needs serialization.

## Determinism

The same request and Mock Provider configuration returns an equal response. No timestamps, random values, environment details, network state, or mutable runtime state enter the result. Response metadata includes a canonical SHA-256 request fingerprint plus correlation and idempotency values.

Without fixtures, successful output is a deterministic envelope:

```json
{"operation": "requested.operation", "input": {"...": "..."}}
```

`MockProvider.from_fixtures(path)` enables strict JSON fixtures keyed by exact operation and input. Missing fixtures raise `ProviderFixtureNotFoundError`; they never silently fall back. Fixtures can return output or a structured simulated error.

## Fixture Format

```json
{
  "format_version": "1.0.0",
  "responses": [
    {
      "operation": "discovery.summarize",
      "input": {"candidate": "Example"},
      "output": {"summary": "Deterministic fixture"},
      "metadata": {"fixture_id": "discovery-summary-1"}
    }
  ]
}
```

Duplicate operation/input fixtures, unknown fields, invalid errors, unsupported versions, and malformed JSON fail explicitly.

## Output Validation and Errors

If `expected_output_schema` is supplied, output is validated with JSON Schema Draft 2020-12. A mismatch produces an error response with code `invalid_output`; it does not raise or coerce output.

Invalid requests and fixture configuration raise typed local exceptions. Simulated Provider failures are Provider responses because they model an outbound operation outcome.

## Architecture Relationships

- **Durable Activities:** a future real Provider invocation must be represented as an authorized `ai` Activity. This Mock Provider does not create ActivityRequest/Result records or bypass RFC-0001.
- **Agents:** Agents may request generation through future Workflow coordination; they never call Providers directly or gain authority from a Provider response.
- **Workflows:** Workflows may eventually consume recorded Provider results, but PR-006 executes no Workflow or step.
- **Apps:** Apps may package prompt and fixture assets; they do not select or invoke this Provider.
- **Workspace:** Workspace remains a read-only manifest model and neither owns nor calls Providers.
- **Kernel:** Provider responses are untrusted external-style data. They cannot write repositories, append Events, create Artifacts, satisfy Approvals, or mutate Project state.
- **Authorization:** no authorization is implemented here. Future Provider invocation remains deny-by-default and must precede execution.

## Non-responsibilities

No real models, API keys, network, streaming, embeddings, prompt rendering, Provider registry, model routing, retries, budgets, Tool execution, Workflow/Agent execution, CLI, persistence, Events, Activities, or runtime mutation are implemented.

## Known Limitations and Next Step

The default fallback is an echo envelope rather than generated content. Fixtures match exact operation and input only. There is no Provider protocol/registry, durable Activity adapter, prompt pack contract, usage/cost accounting, streaming, cancellation, or concurrency behavior.

PR-007's deterministic Evaluation Runner can now assess explicitly supplied Provider output without invoking the Provider itself or persisting evidence. PR-008 should define a versioned Evaluation Rubric Manifest so these rules can be packaged declaratively without adding Workflow execution or Kernel mutation.
