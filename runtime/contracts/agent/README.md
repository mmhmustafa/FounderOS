# FounderOS Agent Manifest Contract

## Purpose

An Agent Manifest is an immutable, versioned declaration of a specialist role. It describes what an Agent can accept and produce, its capabilities and constraints, its maximum Tool categories, Provider-neutral requirements, Evaluation evidence, and handoff shape.

The canonical schema is `agent.schema.yaml`. `examples/product-manager.yaml` is a valid first-party example. Both are YAML documents, and the schema uses JSON Schema Draft 2020-12 semantics.

## What a Manifest Is Not

A manifest is not:

- prompt text or a prompt template;
- executable code, a Workflow, or an AgentRun;
- runtime state, memory, conversation history, or Project context;
- a Provider or model configuration;
- a secret, API key, credential, or authorization grant; or
- permission to call a Tool, mutate the Kernel, or approve an output.

The schema closes the root and every nested object with `additionalProperties: false`. Prompt fields, secrets, model settings, runtime state, and history therefore fail validation instead of becoming ungoverned extension data.

## Prompt and Execution Boundaries

Prompt templates are separately versioned App assets. A future coordinator may combine a manifest, a referenced prompt template, validated Artifact inputs, and an authorized Provider request. None of those operations is performed by this contract.

The Agent definition is stateless. An AgentRun records one execution. Durable facts belong in Artifacts, Decisions, Events, or a future Knowledge repository; temporary execution context belongs to the run. Memory belongs to the platform because it requires Project scoping, retention, authorization, audit, redaction, and replay rules that no Agent may own independently.

## Relationships

- **Apps** package exact Agent manifest versions alongside Workflows, schemas, prompts, rubrics, policies, and fixtures.
- **Workflows** are executable process definitions. They select Agents and coordinate work; the Agent manifest does not define steps or transitions.
- **Providers** are AI/model backends behind a future port. `provider_preferences` declares only neutral capability and data-handling needs, never a Provider or model configuration.
- **Tools** are controlled external capabilities. `allowed_tool_categories` is an upper bound, not permission or an executor binding.
- **Authorization** evaluates every protected operation. A manifest requests no authority and cannot override deny-by-default policy.
- **Kernel** remains the sole runtime mutation authority. Agents return candidate outputs through services and never write repositories, Events, Approvals, or Project state directly.

## Identity and Lifecycle

`id` uses the existing canonical `agt_` ULID namespace. `version` follows Semantic Versioning and identifies immutable manifest content. A changed published definition requires a new version. `status` describes publication lifecycle:

- `draft` — not available for normal selection;
- `active` — eligible for selection subject to package compatibility and policy;
- `deprecated` — retained for pinned historical references but discouraged for new work;
- `retired` — retained for history and unavailable for new work.

`maturity` independently describes confidence: `experimental`, `beta`, `stable`, or `deprecated`. Neither field grants execution authority.

## Tool Categories

Known Tool categories are `filesystem`, `network`, `git`, `browser`, `shell`, `python`, `docker`, `cloud`, and `notification`. AI generation is a Provider activity, and human Approval is a Kernel record, so neither is represented as a Tool category. An empty list means the definition declares no Tool access.

## Validation

Install development dependencies and run the focused contract tests:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest tests/test_agent_manifest_schema.py -q
```

The active runtime `ContractRegistry` remains non-recursive and does not adopt this definition. PR-004's explicit Manifest Loader can validate a requested Agent Manifest path without registering or executing it.

## Dependencies

- `runtime/contracts/common.schema.json` for the established identity and version conventions
- `architecture/FounderOS_v0.2_Blueprint.md` for App, Workflow, Agent, Provider, Tool, and Kernel boundaries
- `runtime/authorization.md` for policy precedence
- `docs/rfcs/RFC-0001-durable-activity-and-side-effect-contracts.md` for future external execution boundaries

## Risks and Next Step

The manifest is not yet resolved from App packages, registered, loaded, authorized, or executed. PR-002 now defines a Workflow Manifest that references exact Agent IDs and versions; a later adoption boundary must still resolve those references without replacing historical runtime definitions.
