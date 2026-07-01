# DECISIONS

## D-001
Decision: FounderOS uses five core objects.
Reason: Simplicity and scalability.
Status: Accepted.

## D-002
Decision: Master Orchestrator is the single user-facing entry point and a thin facade over runtime services.
Reason: Preserve a simple user experience without creating a monolithic controller.
Status: Accepted.

## D-003
Decision: FounderOS is state-driven.
Reason: Predictable workflow transitions.
Status: Accepted.

## D-004
Decision: Networking is the first specialization.
Reason: Founder's expertise and easier validation.
Status: Accepted.

## D-005
Decision: `.ai/` is the official location for AI governance and onboarding documents.
Reason: Provide one explicit entry point and separate project governance from product documentation.
Status: Accepted.

## D-006
Decision: Empty scaffold files represent planned work, not completed components.
Reason: Repository status must distinguish structure from implementation.
Status: Accepted.

## D-007
Decision: Executable runtime contracts precede lifecycle module development.
Reason: Validate shared semantics before implementing Discovery, Validation, Product, or other domain workflows.
Status: Accepted.

## D-008
Decision: FounderOS runtime contracts use JSON Schema Draft 2020-12.
Reason: Provide language-neutral, machine-valid structural contracts with standard reference and conditional validation support.
Status: Accepted.

## D-009
Decision: Persisted entities use immutable type-prefixed ULIDs; definition/content versions use Semantic Versioning; mutable records use integer revisions.
Reason: Separate identity, compatibility, and optimistic concurrency instead of overloading one field.
Status: Accepted.

## D-010
Decision: State changes occur only through guarded Transition records at the State Machine boundary.
Reason: Prevent orchestrators, workflows, agents, or registries from bypassing evidence, approval, authorization, and concurrency checks.
Status: Accepted.

## D-011
Decision: Project mutation and its Event append must commit atomically, while AI and external tool calls occur outside mutation transactions.
Reason: Preserve consistent state and audit history without holding transactions across nondeterministic external operations.
Status: Accepted.

## D-012
Decision: Important lifecycle transitions and decisions require explicit authorized human Approval records.
Reason: Implement the constitutional principle that humans approve important decisions and prevent confidence scores or agent output from implying consent.
Status: Accepted.

## D-013
Decision: Supporting runtime records do not expand the five product-level core objects.
Reason: Project, run, transition, evaluation, approval, and event records are operational infrastructure for Agent, Artifact, Workflow, State, and Decision.
Status: Accepted.

## D-014
Decision: The Runtime Foundation uses Python 3.11+ with `jsonschema` 4.x as its only runtime dependency and standard-library `unittest` for tests.
Reason: Python provides a small, readable implementation surface while `jsonschema` enforces the approved language-neutral contracts without introducing an application framework.
Status: Accepted.

## D-015
Decision: Milestone 3 uses thread-safe in-memory repositories behind explicit service boundaries.
Reason: Validate contracts, transactions, guards, and lifecycle semantics before choosing durable storage technology.
Status: Accepted.

## D-016
Decision: `Project.last_event_sequence` identifies the latest aggregate-mutating Event incorporated into the Project snapshot; the Event repository independently owns the complete gap-free audit-stream sequence.
Reason: Rejected transitions and run lifecycle Events must remain auditable without changing Project state or optimistic revision.
Status: Accepted.

## D-017
Decision: The Runtime Planner is a deterministic, read-only layer that produces recommendations but never creates runs, transitions, events, artifacts, decisions, or state mutations.
Reason: Separate planning from execution so recommendations cannot bypass runtime contracts, quality gates, approvals, or persistence boundaries.
Status: Accepted.

## D-018
Decision: Planner workflow and agent-role mappings are explicit static metadata in Milestone 4, while allowed transitions and guard requirements remain authoritative in the State Machine.
Reason: Keep routing transparent and testable without duplicating transition authority or introducing AI-based planning.
Status: Accepted.

## D-019
Decision: Founder Brief content is caller-supplied structured data validated by a dedicated versioned schema; Milestone 5 performs no generative AI work.
Reason: Exercise the complete runtime path deterministically before introducing nondeterministic providers.
Status: Accepted.

## D-020
Decision: The Founder Setup application service coordinates existing Planner, run, registry, approval, Event, and State Machine boundaries instead of becoming a second transition authority.
Reason: Keep orchestration thin and preserve the runtime contracts as the source of truth.
Status: Accepted.

## D-021
Decision: Milestone 5 stores canonical JSON content immutably in memory and records its SHA-256 digest on the Artifact.
Reason: Verify content integrity and replay semantics while deferring storage technology to Milestone 6.
Status: Accepted.

## D-022
Decision: Milestone 6 uses Python standard-library `argparse` and JSON output for the CLI.
Reason: Keep the interface testable and dependency-free while the command surface is small.
Status: Accepted.

## D-023
Decision: CLI commands delegate to a thin application facade, which delegates all planning, approvals, runs, and transitions to existing runtime services.
Reason: Prevent presentation code from duplicating or bypassing runtime rules.
Status: Accepted.

## D-024
Decision: The initial CLI persists one Project using a validated JSON record snapshot, an ordered JSONL Event stream, and immutable JSON Artifact content files under `.founderos/`.
Reason: Provide understandable restart-safe local use without introducing a database or claiming production-grade transaction semantics.
Status: Accepted.

## D-025
Decision: Local writes require an exclusive lock file and must match a monotonic persisted store revision.
Reason: A lock prevents simultaneous writers while the revision rejects stale read-modify-write attempts that occur sequentially.
Status: Accepted.

## D-026
Decision: Every replacement after the first committed save creates one validated pre-write backup under `.founderos/backup/`.
Reason: Preserve a simple, understandable recovery point without introducing a database or transaction log.
Status: Accepted.

## D-027
Decision: Recovery is explicit, restores only a validated backup, and revalidates the restored primary before reporting success.
Reason: Avoid silently masking corruption and make potential loss of the latest write visible to the operator.
Status: Accepted.

## D-028
Decision: Local persistence formats migrate through an ordered registry; missing format metadata is treated as v0 and future versions fail closed.
Reason: Make compatibility behavior testable and prevent newer data from being guessed at by an older runtime.
Status: Accepted.

## D-029
Decision: Runtime repositories expose validated bulk import/export ports; persistence adapters may not call repository-private insertion methods.
Reason: Keep storage adapters independent from in-memory implementation details.
Status: Accepted.

## D-030
Decision: Artifact, Evaluation, Approval, WorkflowRun, and AgentRun mutations belong to reusable lifecycle services rather than vertical-slice coordinators.
Reason: Preserve one mutation owner per runtime record type and make later workflows reuse proven boundaries.
Status: Accepted.

## D-031
Decision: Important CLI mutations accept explicit idempotency keys whose operation and result are persisted in format v2.
Reason: Retries after ambiguous process or transport failure must not duplicate important effects.
Status: Accepted.

## D-032
Decision: Stale locks are never removed automatically; manual removal requires an exact unchanged PID, a confirmed dead owner, and a minimum lock age.
Reason: A false-positive stale-lock break could permit concurrent writers and corrupt local state.
Status: Accepted.

## D-033
Decision: Local-store write phases expose test-only failure injection checkpoints.
Reason: Recovery guarantees must be exercised at phase boundaries rather than inferred from happy-path tests.
Status: Accepted.

## D-034
Decision: Audit and diagnostic output is a derived read model built from authoritative records and ordered Events.
Reason: Observability must never become a second mutation or state authority.
Status: Accepted.

## D-035
Decision: Every CLI mutation uses one root command correlation ID inherited by all child runtime Events and transition metadata.
Reason: Operators need to identify which command caused each run, approval, Artifact, and state change.
Status: Accepted.

## D-036
Decision: Founder Brief content, approval rationale, and other sensitive fields are redacted from diagnostics by default and require explicit opt-in.
Reason: Operational inspection should expose metadata and evidence links without unnecessarily disclosing founder or customer context.
Status: Accepted.

## D-037
Decision: Audit consistency checks verify Event order, deterministic Project replay, and transition Event resolution without writing repair data.
Reason: Diagnostics must detect inconsistency while remaining strictly read-only.
Status: Accepted.

## D-038
Decision: Discovery v1 accepts only local structured input and makes no LLM, web, or external API calls.
Reason: Validate lifecycle, evidence, scoring, approval, and audit behavior before nondeterministic research.
Status: Accepted.

## D-039
Decision: Opportunity total score is the unweighted sum of six integer component scores bounded from 0 to 10.
Reason: Keep v1 scoring transparent and reproducible.
Status: Accepted.

## D-040
Decision: Founder Brief Approval authorizes Discovery start; Opportunity Report Approval and an approved selection Decision authorize `OPPORTUNITY_SELECTED`.
Reason: Satisfy existing State Machine guards without implied consent.
Status: Accepted.

## D-041
Decision: Equal totals are ordered by problem and target-user text.
Reason: Guarantee deterministic ranking independent of input order.
Status: Accepted.

## D-042
Decision: Pytest is the official developer test runner and is installed through the `dev` optional dependency group.
Reason: Provide one consistent runner and installation path across supported environments while keeping test tooling out of runtime dependencies.
Status: Accepted.

## D-043
Decision: Official test scripts run pytest verbosely and report the slowest tests.
Reason: The persistence-heavy suite takes roughly 80–90 seconds on Windows; continuous progress distinguishes expected work from a deadlock or shutdown hang.
Status: Accepted.

## D-044
Decision: Pytest uses its standard ignored `.pytest_cache` path; invalid local ACLs are repaired rather than bypassed with a second cache location.
Reason: Keep standard tool behavior and correct the underlying filesystem permission defect instead of suppressing its warning.
Status: Accepted.

## D-045
Decision: The documented Windows test command starts the repository script in a child PowerShell process with process-scoped execution-policy bypass.
Reason: Make one-command testing work on default restricted Windows environments without changing persistent user or machine policy.
Status: Accepted.

## D-046
Decision: Windows stale-lock owner checks use `OpenProcess` and `GetExitCodeProcess`, close every acquired handle, and treat access-denied or indeterminate results as alive.
Reason: `os.kill(pid, 0)` is a POSIX idiom with unsafe, version-dependent Windows behavior; stale-lock recovery must inspect without signalling and fail closed when uncertain.
Status: Accepted.

## D-047
Decision: A FounderOS App is an immutable, versioned package/index of definitions and assets, not a sixth core object or an execution authority.
Reason: Packaging Workflows, Agents, schemas, prompts, rubrics, policies, fixtures, and tests enables reuse without duplicating runtime semantics.
Status: Accepted.

## D-048
Decision: Workflow remains the sole executable process definition, and WorkflowRun remains its runtime execution record.
Reason: Reusing and evolving the existing contracts prevents parallel App/Workflow step, retry, approval, state, and recovery models.
Status: Accepted.

## D-049
Decision: The FounderOS Kernel remains the sole domain-mutation authority, and only the State Machine may change `Project.current_state`.
Reason: Apps, Agents, Providers, Tools, interfaces, and orchestration must not bypass the service boundaries, guards, approvals, revisions, or authoritative Event stream established in v0.1.
Status: Accepted.

## D-050
Decision: Lifecycle Workflows may request guarded Project transitions; utility Workflows may create records through Kernel services but cannot change `Project.current_state`.
Reason: General-purpose Apps such as reviews and incident analysis must not distort or bypass the startup lifecycle state machine.
Status: Accepted.

## D-051
Decision: FounderOS v0.2 is a modular monolith with Provider, Tool, Knowledge, persistence, Event, and secret/configuration capabilities behind outbound ports.
Reason: Explicit dependency directions preserve testability and future adapter replacement without premature services or distributed-system complexity.
Status: Accepted.

## D-052
Decision: Authorization Policy Foundation must complete before AI Provider or Tool execution is implemented.
Reason: Audit actors and manifest declarations do not prove identity or grant authority; protected reads, mutations, approvals, transitions, secrets, data disclosure, and external effects require enforceable deny-by-default policy.
Status: Accepted.

## D-053
Decision: The first v0.2 product proof is a bundled, first-party, package-defined Validation vertical slice shaped by preceding authorization, durable-activity, App-package, and fake-provider gates.
Reason: A real founder outcome should drive the minimum reusable abstractions before marketplace, broad Provider/Tool, memory, or Knowledge infrastructure is built.
Status: Accepted.

## D-054
Decision: Runtime authorization is distinct from authentication and evaluates an explicit Actor, Action, Resource, and context before a protected Kernel operation.
Reason: Audit actor metadata does not prove identity or authority, while Milestone 12C must remain compatible with future authentication and enterprise identity without implementing either.
Status: Accepted.

## D-055
Decision: Authorization Policies are immutable and versioned, use `default_effect: deny` with `deny_overrides`, and must produce deterministic AuthorizationDecisions.
Reason: Fail-closed, exact-version policy evaluation is testable, auditable, and safe for future human and non-human Actors.
Status: Accepted.

## D-056
Decision: An authorization allow permits a request to reach the owning Kernel service but performs no mutation and bypasses no contract, revision, guard, Evaluation, Approval, transaction, or Event rule.
Reason: The Kernel and State Machine must remain the sole domain and Project-state mutation authorities.
Status: Accepted.

## D-057
Decision: Authorization and human Approval are independent requirements; neither substitutes for the other.
Reason: Authorization governs whether an Actor may attempt an Action, while Approval records an authorized human decision about a specific subject and remains explicit transition or lifecycle evidence.
Status: Accepted.

## D-058
Decision: Milestone 12C authorization schemas remain under a non-loaded contract subdirectory and are not registered, persisted, or enforced by the current runtime.
Reason: The milestone was explicitly limited to architecture, contracts, documentation, and placeholder interfaces; future adoption requires deliberate compatibility, persistence, service-wiring, and acceptance-test work.
Status: Accepted.

## D-059
Decision: Every future external operation is represented by a durable ActivityRequest before execution and executes outside all FounderOS Kernel mutation transactions.
Reason: External systems cannot join Kernel transactions and introduce unbounded latency, nondeterminism, partial failure, and side effects that must not be repeated by replay.
Status: Proposed by RFC-0001.

## D-060
Decision: One logical Activity retains one immutable request and idempotency identity across all attempts; retries do not create new logical Activities.
Reason: Stable identity allows command and Workflow replay to reuse recorded outcomes without duplicating external effects.
Status: Proposed by RFC-0001.

## D-061
Decision: FounderOS claims effectively-once rather than exactly-once external behavior, using durable intent, stable idempotency, bounded attempts, receipts, and reconciliation.
Reason: Exactly-once execution cannot be guaranteed across a local transaction and an independent external system.
Status: Proposed by RFC-0001.

## D-062
Decision: Ambiguous or non-idempotent external writes are never blindly retried; they require reconciliation, while compensation is a separate linked and newly authorized Activity.
Reason: A timeout or lost response may occur after an effect succeeded, and rewriting the original Activity would destroy historical truth.
Status: Proposed by RFC-0001.

## D-063
Decision: ActivityExecutors perform only external work and return immutable results/receipts; a future Kernel Activity service alone owns ActivityRecord mutation and authoritative Activity Events.
Reason: Workflows, Agents, Providers, Tools, and workers must not become alternate repository, Event, or Project-state authorities.
Status: Proposed by RFC-0001.

## D-064
Decision: Event and Workflow replay reconstruct Activity state and consume recorded results but never invoke an ActivityExecutor.
Reason: Replay must remain deterministic and cannot repeat nondeterministic or destructive side effects.
Status: Proposed by RFC-0001.

## D-065
Decision: An Agent Manifest is an immutable, versioned, stateless package definition validated independently from runtime Agent execution records.
Reason: Apps and Workflows need exact, reviewable role/capability contracts without embedding prompts, secrets, memory, model configuration, runtime state, or a competing execution authority.
Status: Accepted by PR-001.

## D-066
Decision: Agent Manifest Tool categories and Provider preferences declare maximum requirements only; they never grant authorization or select an executor, Provider, or model.
Reason: Authorization must remain deny-by-default, Providers and Tools remain outbound capabilities, and the Kernel remains the sole runtime mutation authority.
Status: Accepted by PR-001.

## D-067
Decision: PR-001 Agent Manifest contracts remain in a non-loaded contract subdirectory and do not replace the active v0.1 Agent runtime schema.
Reason: Independent contract validation is required now, while loader, registry, compatibility mapping, execution, and runtime migration are explicitly deferred.
Status: Accepted by PR-001.

## D-068
Decision: A Workflow Manifest is an immutable, versioned, declarative executable-process definition, while WorkflowRun remains the record of execution and the manifest never executes itself.
Reason: Steps, exact Agents, Artifacts, Evaluations, Approvals, recovery, and transition intent need one inspectable definition without creating a second coordinator or mutation authority.
Status: Accepted by PR-002.

## D-069
Decision: Lifecycle Workflow Manifests require an exit state and transition intent; utility Workflow Manifests require both values to be null.
Reason: Utility work may produce records through Kernel services but must be structurally incapable of requesting a change to `Project.current_state`.
Status: Accepted by PR-002.

## D-070
Decision: Workflow transition intent is a non-authoritative request that must match declared entry/exit states and resolve required Approval references before reaching the State Machine.
Reason: Workflow completion, a manifest declaration, or an Approval requirement cannot bypass authorization, runtime evidence, guards, current Approval records, or the State Machine's sole state-mutation authority.
Status: Accepted by PR-002.

## D-071
Decision: PR-002 Workflow Manifest contracts and semantic validation remain outside the active runtime registry and do not replace the v0.1 Workflow runtime schema.
Reason: This PR establishes independently testable package contracts while intentionally deferring loading, registry, coordination, execution, migration, and runtime adoption.
Status: Accepted by PR-002.

## D-072
Decision: An App Package Manifest is an immutable, versioned asset index and never an executable process or runtime mutation authority.
Reason: Packaging exact Workflows, Agents, schemas, prompts, Evaluation rules, fixtures, and documentation enables composition without duplicating Workflow execution or Kernel ownership.
Status: Accepted by PR-003.

## D-073
Decision: App packages use stable namespaced identities such as `founderos.discovery` rather than a new runtime-entity ULID prefix.
Reason: App is a packaging/deployment concept, not a sixth persisted core object, and namespaced identities support future publisher and marketplace boundaries.
Status: Accepted by PR-003.

## D-074
Decision: Initial App runtime and dependency compatibility use the canonical bounded form `>=X.Y.Z <A.B.C`, and published package assets are identified by an exact SHA-256 digest shape.
Reason: A deliberately narrow compatibility grammar and immutable content identity are deterministic and reviewable without prematurely implementing a package manager or canonical archive algorithm.
Status: Accepted by PR-003.

## D-075
Decision: PR-003 accepts bundled `first_party` publisher trust only and keeps App contracts outside the active runtime registry.
Reason: Signing, third-party trust, installation, dependency resolution, marketplace behavior, loading, and execution require later security and lifecycle architecture and are not implied by a schema-valid package.
Status: Accepted by PR-003.

## D-076
Decision: Executable manifest loading lives under `src/founderos_runtime/manifest_loader/`, while `runtime/contracts/` remains the authoritative schema and specification source.
Reason: Python behavior belongs in the established runtime package, and duplicating schemas into code would create competing contract authorities.
Status: Accepted by PR-004.

## D-077
Decision: The Manifest Loader is stateless and uncached; every call rereads and validates the exact schema and requested YAML file before returning a defensive object.
Reason: Determinism and immediate contract-file fidelity matter more than premature optimization, while caching would introduce invalidation and hidden lifecycle semantics.
Status: Accepted by PR-004.

## D-078
Decision: Manifest loading applies both Draft 2020-12 structural validation and the semantic cross-field invariants established by the Workflow and App contract PRs.
Reason: Returning a structurally valid but referentially contradictory object as “validated” would weaken the package contracts before a registry exists.
Status: Accepted by PR-004.

## D-079
Decision: Manifest Loader failures are typed and carry deterministic `file`, `field`, and `reason` details.
Reason: Callers and tests need actionable diagnostics without parsing generic YAML, filesystem, or jsonschema exception text.
Status: Accepted by PR-004.

## D-080
Decision: PyYAML is a runtime dependency beginning with PR-004.
Reason: Safe YAML parsing is now production loader behavior rather than test-only contract tooling.
Status: Accepted by PR-004.

## D-081
Decision: A Workspace is a fresh, read-only, in-memory semantic snapshot of validated manifests beneath one bounded project root, not a registry.
Reason: Callers need coherent relationships and deterministic queries before execution, while registration lifecycle, persistence, global state, and version resolution remain separate future concerns.
Status: Accepted by PR-005.

## D-082
Decision: Workspace manifest kind is determined by the nearest ancestor directory named `agents`, `workflows`, or `apps`, and every discovered file is validated through PR-004 before indexing.
Reason: An explicit bounded convention avoids content guessing and keeps YAML/schema validation owned by one loader boundary.
Status: Accepted by PR-005.

## D-083
Decision: One Workspace permits one manifest per logical Agent, Workflow, or App ID and resolves references by exact ID and version.
Reason: Deterministic snapshots must reject ambiguity; side-by-side versions and selection policy belong to a future registry/version resolver.
Status: Accepted by PR-005.

## D-084
Decision: Workspace compatibility checks use runtime `0.1.0` by default, enforce App/Workflow bounds and App dependency ranges, and reject circular present dependencies.
Reason: A semantic model must fail before planning when its definitions cannot coexist with the active runtime or each other.
Status: Accepted by PR-005.

## D-085
Decision: Workspace query APIs return deterministically ordered defensive copies and expose no add, update, remove, execute, authorize, persist, or mutate operations.
Reason: Consumers may safely inspect the semantic model without gaining a back door into definition lifecycle or runtime state.
Status: Accepted by PR-005.

## D-086
Decision: ProviderRequest, ProviderResponse, ProviderStatus, and ProviderError are immutable structured contracts independent from any real Provider SDK.
Reason: FounderOS needs one stable generation boundary before adopting vendor transports, credentials, model configuration, or nondeterministic behavior.
Status: Accepted by PR-006.

## D-087
Decision: The Mock Provider is a pure offline adapter whose default response and exact fixture responses contain no time, randomness, environment, network, or runtime-state inputs.
Reason: Identical requests and configuration must produce equal responses so Provider-based workflow tests can be deterministic and cost-free.
Status: Accepted by PR-006.

## D-088
Decision: Correlation ID and idempotency key are preserved as explicit response metadata, while the request fingerprint derives only from operation, structured input, and expected output schema.
Reason: Trace context may change across attempts without changing logical generation intent, and idempotency identity must remain separate from canonical request content.
Status: Accepted by PR-006.

## D-089
Decision: Invalid caller requests and fixture configuration raise typed local exceptions; simulated Provider failures return structured error responses.
Reason: Contract/configuration misuse is a local programming boundary, while failure responses model the outcome of a future outbound Provider operation.
Status: Accepted by PR-006.

## D-090
Decision: PR-006 does not wire MockProvider into Workflows, Agents, Workspace, authorization, Activities, Kernel services, persistence, or CLI behavior.
Reason: Provider invocation must eventually pass through authorization and RFC-0001 durable Activity boundaries; a deterministic test adapter must not bypass those gates.
Status: Accepted by PR-006.

## D-091
Decision: PR-007 EvaluationRule, EvaluationRequest, EvaluationFinding, and EvaluationResult are immutable pure assessment contracts distinct from persisted runtime `evl_` Evaluation records.
Reason: Quality logic must be testable without implicitly creating durable evidence, Events, approvals, or Kernel mutation.
Status: Accepted by PR-007.

## D-092
Decision: Evaluation always applies a non-empty-content finding, optionally applies the request's expected schema, then evaluates declared rules in lexicographic rule-ID order.
Reason: Fixed ordering and explicit built-ins produce stable findings independent of caller rule ordering.
Status: Accepted by PR-007.

## D-093
Decision: Evaluation score is the unweighted passed-finding ratio rounded to six decimals; overall pass also requires no failed error or critical finding.
Reason: Transparent scoring avoids premature weighting while severity preserves hard quality and safety gates even under a relaxed score threshold.
Status: Accepted by PR-007.

## D-094
Decision: Custom Evaluation rules are injected named pure callables receiving defensive copies and must return bool or `(bool, message)`.
Reason: Narrow injection supports deterministic domain checks without dynamic code loading, global registration, Provider calls, or runtime mutation.
Status: Accepted by PR-007.

## D-095
Decision: PR-007 does not persist EvaluationResult, invoke Providers, execute Workflows, record human Approval, call the Planner, or mutate Kernel state.
Reason: A future authorized lifecycle service must explicitly translate assessment output into runtime Evaluation evidence and authoritative Events.
Status: Accepted by PR-007.

## D-096
Decision: PR-008 introduces a Workspace-based Planner under `founderos_runtime.planner`, while the earlier state-aware lifecycle Planner remains an explicit compatibility component.
Reason: Manifest planning and live Project-state routing answer different questions; preserving the established API avoids breaking the CLI and vertical slices while keeping the new contract boundary coherent.
Status: Accepted by PR-008.

## D-097
Decision: Execution Plans are immutable read-only projections whose transition requests are intent, never authorization or Kernel mutation authority.
Reason: Planning must remain deterministic and independently inspectable before authorization, Activity execution, Approval, persistence, or state mutation occurs.
Status: Accepted by PR-008.

## D-098
Decision: Planner step order is a stable topological sort over declared Artifact dependencies, with manifest position and step ID as deterministic tie-breakers.
Reason: Artifact data flow is the declarative dependency vocabulary already available in Workflow manifests; adding an unrelated orchestration graph would create competing semantics.
Status: Accepted by PR-008.

## D-099
Decision: Declared Evaluations and Approvals absent from explicit Workflow steps become synthetic immutable checkpoints in the plan.
Reason: Quality and human gates must be visible to a future executor even when a manifest declares them at Workflow level rather than as executable steps.
Status: Accepted by PR-008.
