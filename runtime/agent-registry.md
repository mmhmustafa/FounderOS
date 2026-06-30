# Agent Registry

> **Status:** Contract-level specification; implementation not started
>
> **Schemas:** `runtime/contracts/agent.schema.json` and `runtime/contracts/agent-run.schema.json`

## Purpose

The Agent Registry stores versioned Agent definitions and controls creation of auditable AgentRuns through a provider-independent execution boundary.

## Inputs

- Agent definition publication/deprecation command
- Workflow step with exact Agent reference
- Project and WorkflowRun context
- Valid input references and bounded execution policy

## Outputs

- Resolved Agent definition
- AgentRun lifecycle records and Events
- Output references or structured failure

## Registry Invariants

1. Published Agent definitions are immutable by version.
2. Deprecated definitions resolve historically but cannot start new runs.
3. AgentRun pins Agent version, prompt version, and provider/model identifiers when used.
4. Inputs and outputs must conform to the definition's allowed artifact types.
5. Agent output is untrusted until schema validation and quality evaluation pass.
6. Agents cannot approve their own output or mutate Project state.
7. Tools execute only when declared by the Agent definition and allowed by runtime policy.

## AgentRun State Transitions

```text
queued -> running -> succeeded | failed | cancelled
```

Every retry is a new AgentRun attempt; failed records are never overwritten.

## Provider Boundary

Provider-specific requests and responses remain adapter details. The canonical record stores provider/model names, prompt version, inputs, outputs, status, attempt, timestamps, and failure. Provider output cannot become a canonical Artifact without Artifact Registry validation.

## Dependencies

- Workflow Engine
- Artifact Registry
- Event store
- Future tool/provider adapters

## Failure and Recovery

Invalid definition/input fails before invocation. Transient provider failure follows bounded Workflow policy. Invalid output marks the run failed and produces no approved artifact. Authorization/tool-policy failure is never retried automatically.

## Risks

- Tool permission and model safety policies need implementation detail.
- Token/cost metrics are reserved for later observability contracts.

## Next Step

Implement definition resolution and provider adapter interfaces in Milestone 3.
