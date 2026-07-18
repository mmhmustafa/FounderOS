# FounderOS CLI Alpha

## Purpose

The CLI is FounderOS v0.3 Alpha's first public presentation boundary. It parses commands, invokes existing runtime composition, renders plain deterministic text, and returns process exit codes.

```text
founderos version
founderos doctor
founderos demo discovery
founderos atlas demo discovery
founderos atlas demo topology
founderos atlas morning-brief
founderos help
```

## Philosophy and Boundaries

The CLI owns no planning, validation, authorization, Journey execution, Provider behavior, Evaluation rules, Artifact creation, or state mutation. `demo discovery` delegates once to the PR-012 Discovery helper, which remains the composition source of truth.

`atlas demo discovery` delegates to Atlas's fixture-only demo helper. Atlas owns fixture loading, Discovery Engine invocation, and Topology Graph construction; the FounderOS CLI only routes and renders the returned domain values.

`atlas demo topology` runs that same fixture-only pipeline, converts its Snapshot through the Atlas visualization adapter, writes `atlas_topology.html`, and asks the default browser to open it. File delivery and browser launch remain CLI concerns; the Atlas renderer itself is pure.

`atlas morning-brief` invokes the Atlas utility Workflow through FounderOS Journey infrastructure, renders its evaluated structured Artifact, and writes `morning_brief.md`. The CLI owns only routing, console rendering, and file delivery.

`doctor` verifies that the bundled Discovery Workspace loads and that deterministic Evaluation and Mock Provider components are importable. It does not call a network, execute a Journey, or mutate runtime state.

Output contains no ANSI styling and requires no external CLI framework. Execution duration is deliberately reported as unrecorded: wall-clock timing would make otherwise deterministic demo output vary between runs.

## Compatibility

The earlier local Project CLI commands remain delegated to the established application facade for compatibility. New Alpha commands do not reuse or modify that persistence-oriented path.

## Future Web UI

A future Web UI should call the same application/runtime boundaries rather than shelling out to this CLI or copying its orchestration. CLI rendering is a replaceable adapter, not a domain API.

## Non-Responsibilities

There are no interactive prompts, real AI Providers, persistence for the Alpha demo, configuration system, plugins, marketplace, authentication, Web UI, human Approval execution, or Kernel mutation in PR-013.
