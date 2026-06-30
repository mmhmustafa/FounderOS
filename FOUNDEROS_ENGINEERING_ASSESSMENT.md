# FounderOS Engineering Assessment

## Executive verdict

FounderOS has a coherent product vision and a promising conceptual model, but the repository is still a documentation scaffold—not yet a runtime.

Key findings:

- 72 files exist; 58 are empty (80.6%).
- 57 of 70 Markdown documents are empty.
- No executable application, schema validation, automated tests, CI, dependency manifest, or development tooling exists.
- The current runtime consists only of a minimal state list.
- `runtime/master-orchestrator.md` is absent, despite project documents claiming it is complete.
- Git history shows the orchestrator was implemented and then deleted.
- The governance documents were moved into `.ai/`, but that relocation is currently uncommitted: Git sees the root documents as deleted and `.ai/` as untracked.
- The architecture is directionally sound but materially underspecified for execution, recovery, persistence, concurrency, and human approval.

No files were modified during the review.

---

## 1. Repository Overview

FounderOS is intended to become a state-driven AI operating platform that moves a founder through:

```text
Founder setup → Discovery → Validation → Product design
→ Architecture → Development → QA → Launch → Growth
```

Its architectural foundation is five objects:

1. Agent
2. Artifact
3. Workflow
4. State
5. Decision

The intended runtime loop is:

```text
Read state
→ Find missing artifacts
→ Select workflow
→ Invoke agents
→ Validate output
→ Record decisions
→ Transition state
```

The current repository, however, implements this as an architectural narrative rather than an operational system. The only substantive project documents are:

- `.ai/ENGINEERING_HANDBOOK.md`
- `.ai/PROJECT_CONTEXT.md`
- `.ai/BUILD_ROADMAP.md`
- `architecture/FounderOS_Architecture_Specification_v1.0.md`
- `runtime/state-machine.md`

This means the project is at “architecture concept/prototype specification,” not “runtime foundation complete.”

---

## 2. Folder Structure Review

| Folder | Assessment | Recommendation |
|---|---|---|
| `.ai/` | Good centralized onboarding concept. Contains all governance material. Relocation is uncommitted and references are inconsistent. | Commit the relocation intentionally and update every path reference. Establish document ownership and status metadata. |
| `agents/` | Sensible separation of specialist roles. All 14 files are empty. | Define one canonical agent schema and implement only the agents needed by the first vertical slice. |
| `architecture/` | Correct home for long-term design. One strong conceptual specification. Four empty files duplicate topics already embedded in the main specification. | Split the specification deliberately or remove placeholder duplicates. Add executable contracts and diagrams. |
| `assets/` | Empty and unexplained. | Remove until needed or document permitted asset types and ownership. |
| `docs/` | Empty and overlaps with `.ai/` and `architecture/`. | Define audience boundaries: user docs, operator docs, engineering docs, architecture records. |
| `domains/networking/` | Sensible domain isolation and aligns with the first specialization. All nine files are empty. | Delay broad taxonomy work; first define the domain knowledge-entry schema and provenance requirements. |
| `examples/` | Named examples are valuable validation targets, but both are empty. | Turn one example into an executable acceptance fixture for the vertical slice. |
| `prompts/` | Lifecycle-oriented organization is understandable. All seven files are empty. | Avoid treating prompts as unversioned text assets. Bind prompts to agent/workflow versions, inputs, outputs, and evaluations. |
| `roadmap/` | Versioned roadmap structure could complement the build roadmap. All files are empty, creating two competing roadmap systems. | Consolidate product releases and engineering milestones into one authoritative hierarchy. |
| `runtime/` | Correct conceptual boundary. Six of seven current files are empty; orchestrator is missing. | Define runtime contracts first, then build a narrow executable path rather than completing isolated Markdown files. |
| `templates/` | Artifact templates are appropriate. All 11 files are empty. | Add machine-valid front matter/schema and implement templates only as required by workflows. |
| Repository root | Simple and approachable. README and changelog are too thin; license is empty. | Add contribution, security, support, architecture index, and development documentation once implementation begins. |
| `.git/` | Small, linear history. History exposes deleted work and an incomplete governance relocation. | Reconcile current working-tree intent before further engineering work. |

### Structural strengths

- Clear separation between runtime, architecture, domain knowledge, agents, and reusable artifacts.
- The repository is small enough to correct structural ambiguity cheaply.
- Domain specialization is isolated from the generic runtime.
- `.ai/README.md` provides a useful onboarding entry point.

### Structural weaknesses

- Empty placeholder files create an illusion of completeness.
- There are overlapping authorities: `.ai/BUILD_ROADMAP.md`, `roadmap/`, architecture “next deliverables,” and `CURRENT_SPRINT.md`.
- No `projects/` directory exists despite the architecture’s storage model requiring it.
- No tests, source directory, schemas, scripts, or executable entry point exist.
- Folder responsibilities are described, but dependency direction is not enforced.

---

## 3. Architecture Review

### Strengths

- The five-object vocabulary provides a useful shared language.
- State-driven routing is more predictable than a free-form prompt library.
- Artifacts and decisions are treated as durable records.
- Human approval and evidence-based progression are stated principles.
- Quality gates are recognized as first-class behavior.
- The design anticipates a transition from Markdown to persistent software.

### Weaknesses

#### The five-object model is insufficient as the complete runtime model

The architecture also requires projects, workflow executions, quality evaluations, knowledge entries, human approvals, and tool calls. Forcing all of these into the five objects will either distort semantics or create hidden concepts.

The five objects should remain the product-level vocabulary, not necessarily the complete implementation data model.

#### Schemas are descriptive, not contractual

The YAML fragments do not define:

- Required versus optional fields
- Types and constraints
- Identifier format
- Referential integrity
- Schema versions and migrations
- Mutability rules
- Ownership and authorization
- Timestamps and audit semantics

#### Artifact presence is conflated with artifact validity

A file existing is not enough. The runtime needs a distinction between:

- Artifact instance
- Artifact version
- Review
- Quality evaluation
- Approval
- Publication/current version

#### Orchestration is centralized too early

A single entry point is good UX. A single component owning routing, validation, state mutation, dashboards, agent execution, and persistence would become a god object.

The external “Master Orchestrator” should be a facade over smaller services.

#### The model assumes one linear happy path

Real startup development includes:

- Parallel workflows
- Rework loops
- Conditional branches
- Optional stages
- Paused/cancelled workflows
- Multiple active experiments
- Approval delays
- Failed agent/tool calls
- Project pivots
- Reopened decisions

These cannot be represented safely by the present linear state chain.

### Missing abstractions

- `Project`
- `WorkflowDefinition` versus `WorkflowRun`
- `ArtifactDefinition` versus versioned `ArtifactInstance`
- `AgentDefinition` versus `AgentRun`
- `Transition` and transition guard
- `QualityGate` and `EvaluationResult`
- `ApprovalRequest`
- `Event` or audit record
- `Command`
- `ToolAdapter` / AI provider boundary
- Prompt version
- Retry and failure policy
- Repository/persistence interface
- Knowledge entry with source provenance
- Policy/authorization boundary
- Tenant/workspace boundary
- Cost and token-usage record

### Scalability and maintainability concerns

- Hard-coded routing will grow combinatorially as domains and workflow variants expand.
- One global project state document will cause contention and weak auditability.
- Markdown parsing is too fragile to become the internal source of runtime truth.
- Synchronous agent chains will become slow and expensive.
- Unversioned prompts and schemas will make past runs irreproducible.
- Confidence score `>= 7` is arbitrary without a scoring rubric or calibration.
- Future multi-tenant requirements are acknowledged but absent from the foundational model.

---

## 4. Runtime Review

### Master Orchestrator

The current repository has no Master Orchestrator file.

Git history shows:

1. A substantial orchestrator was added.
2. It was later deleted in the same commit that added the root governance files.
3. The project context and roadmap still mark it complete.

Even the deleted version was a large behavioral prompt rather than an executable orchestrator. It also had notable issues:

- Missing or incomplete handlers for several listed states.
- State mutation mixed with agent behavior and UI formatting.
- User-specific Mustafa/networking defaults embedded in generic runtime behavior.
- No persistence, locking, replay, idempotency, or execution history.
- No explicit human-approval enforcement.
- No agent/tool failure policy.
- No formal command validation.

### State Machine

`runtime/state-machine.md` is a state enumeration, not a state machine implementation.

Missing:

- Transition table
- Entry and exit guards
- Transition ownership
- Events that cause transitions
- Invalid-transition handling
- Failure states
- Recovery paths
- Approval gates
- Terminal-state semantics
- Re-entry rules
- Transition audit record
- Concurrency/version checks

It also duplicates the architecture specification without adding operational precision.

### Runtime architecture

The claimed runtime components are mostly empty:

- Agent registry
- Artifact registry
- Workflow engine
- Project state
- Decision engine
- Knowledge base

There is no contract explaining how these components communicate or which component is allowed to mutate state.

### Runtime inconsistencies

- Architecture defines five core objects, while the runtime separately elevates Knowledge Base and Project State.
- `Master Orchestrator` is declared complete but is absent.
- Current sprint says “implement” Markdown files while its definition of done promises automatic runtime behavior.
- Architecture requires a `projects/` storage location; none exists.
- Artifact states require approval, but approval is not modeled as an object or workflow.
- “Humans approve important decisions” is constitutional, but transitions do not specify mandatory human checkpoints.
- The universal quality gate requires confidence scores without defining assessors or calibration.
- The orchestrator is expected to select agents, but no registry exists.
- State transitions depend on artifacts, but no authoritative artifact identity/version rules exist.

---

## 5. Documentation Review

### Completeness

Documentation is strong at vision level and weak at execution level.

Missing substantive documentation includes:

- Runtime component contracts
- Data dictionary
- Transition specification
- Error model
- Human approval policy
- Security and privacy model
- AI provider/tool abstraction
- Prompt lifecycle
- Evaluation methodology
- Observability
- Persistence semantics
- Local development setup
- Testing strategy
- Deployment architecture
- Contribution workflow

### Consistency

Important inconsistencies include:

- Governance paths reference root files although onboarding now locates them under `.ai/`.
- “Completed” lists include the missing orchestrator.
- The architecture specifies `projects/`, but the repository omits it.
- The architecture and README lifecycle stages differ.
- The handbook calls every major document to include purpose, inputs, outputs, dependencies, risks, and next steps; most existing documents do not.
- Changelog does not include later architecture/governance work.
- Architecture status is “Draft Constitution,” while other documents treat it as settled authority.
- Some rendered arrows/tree characters appear mojibaked in the current shell, indicating an encoding/toolchain portability risk.

### Duplication

- State definitions appear in both the architecture specification and runtime state machine.
- Roadmapping is split between `.ai/BUILD_ROADMAP.md` and empty `roadmap/v*.md`.
- Architecture topics have both empty dedicated files and sections in the monolithic specification.
- Project overview is repeated across README, project context, handbook, and architecture specification.

### Recommended documentation model

Use four clear classes:

1. Governance: `.ai/`
2. Architecture and ADRs: `architecture/`
3. User/operator/developer guides: `docs/`
4. Executable definitions and schemas: runtime source directories

Each fact should have one authoritative source; other documents should link to it.

---

## 6. Technical Debt

### Critical

1. Governance relocation is uncommitted and currently appears as eight deleted tracked files plus a new untracked `.ai/` directory.
2. Master Orchestrator is absent while declared complete.
3. Runtime completion claims are unsupported: nearly every runtime component is empty.
4. No enforceable schemas or transition contracts exist.
5. Human approval is a constitutional requirement but is not represented operationally.

### High

1. State machine supports only a linear happy path.
2. Architecture lacks execution/run/event abstractions.
3. No executable vertical slice or acceptance test proves the design.
4. No testing, CI, linting, validation, or dependency setup.
5. No persistence, idempotency, retry, or audit model.
6. Artifact identity, versioning, review, and approval semantics are ambiguous.
7. Roadmap sequencing delays executable validation too long.
8. Empty placeholders obscure actual project maturity.

### Medium

1. Documentation duplication and inconsistent authorities.
2. Prompt ownership and versioning are undefined.
3. Knowledge provenance and freshness are undefined.
4. Security, tenancy, privacy, and secrets management are deferred.
5. No observability, cost accounting, or model evaluation strategy.
6. README and changelog are stale.
7. Architecture is concentrated in one large document without ADR discipline.

### Low

1. Empty `assets/` and `docs/` folders.
2. Empty license file.
3. Encoding portability of diagrams/arrows.
4. Naming inconsistencies between state names, artifact names, and workflow names.
5. No glossary or terminology index.

---

## 7. Missing Components

### Missing runtime components

- Master Orchestrator
- Executable state-transition service
- Project state repository
- Workflow definition loader
- Workflow execution engine
- Agent registry and runner
- Artifact registry and version store
- Decision service
- Quality-gate evaluator
- Human approval service
- Knowledge retrieval/provenance layer
- Prompt registry/version manager
- Tool/provider adapters
- Event/audit log
- Retry and recovery manager
- Scheduler/queue abstraction
- Configuration and secrets layer
- Observability and cost tracking

### Missing engineering components

- Application source tree
- Dependency manifest
- Schema language and validator
- Unit/integration/contract tests
- Test fixtures
- CI pipeline
- Formatting and linting
- Static type checking
- Local development commands
- Environment configuration
- Logging conventions
- Release/versioning process
- Security scanning
- CODEOWNERS/review policy

### Missing documentation

- Runtime architecture specification
- Canonical data model
- State-transition matrix
- Workflow authoring guide
- Agent authoring guide
- Artifact/template authoring guide
- Approval and escalation policy
- Error/recovery semantics
- Security and threat model
- Privacy/data retention policy
- AI evaluation strategy
- Development and testing guide
- Deployment/runbook
- ADR index
- Definition of done for runtime milestones

---

## 8. Build Roadmap Review

The current roadmap is too component-oriented:

```text
Write registries and engines
→ Add domain runtimes
→ Add engineering/growth layers
→ Eventually convert to software
```

This risks producing extensive Markdown architecture that has never been tested through execution.

A safer order is:

```text
Reconcile repository truth
→ Formalize contracts
→ Build one thin executable vertical slice
→ Evaluate it
→ Generalize only proven abstractions
→ Add more lifecycle stages
```

The first slice should be:

```text
Create project
→ Produce Founder Brief
→ Human approval
→ Persist artifact and decision
→ Transition to FOUNDER_BRIEF_COMPLETE
→ Resume project deterministically
```

This exercises every foundational concern without requiring the full startup lifecycle.

Phase 7—“convert architecture into executable application”—should therefore move immediately after the minimum contracts, not after Discovery, Validation, Product, Engineering, AI, Development, Growth, Sales, and CEO Review specifications.

---

## 9. Risk Assessment

### Architectural risks

- Five-object absolutism may force unrelated runtime concepts into incorrect abstractions.
- A monolithic orchestrator could become impossible to test and change safely.
- Linear states may fail once workflows run concurrently.
- Markdown could leak from presentation/storage format into core domain logic.
- Quality scores may create false confidence rather than reliable gates.

### Implementation risks

- Building every registry separately before a vertical slice may yield incompatible interfaces.
- Empty placeholders can be mistaken for implemented components.
- Premature stack selection could harden assumptions before contracts are validated.
- AI nondeterminism may corrupt state unless state mutation is separated from model output.
- Missing schema versioning will make early project data disposable.

### Scaling risks

- Long synchronous AI workflows will have poor latency and reliability.
- Large artifacts and knowledge collections will increase context cost.
- Multiple projects/users require optimistic concurrency and tenant isolation.
- Replay, retries, and duplicate tool calls can cause inconsistent state.
- Provider-specific prompt behavior can undermine portability.

### Maintenance risks

- Duplicated state lists will drift.
- Unversioned prompts and templates make regressions hard to diagnose.
- No automated verification means documentation and runtime will diverge.
- A broad agent catalogue creates a large maintenance surface before value is proven.
- Undocumented folder boundaries encourage ad hoc additions.

---

## 10. Recommended Next 20 Milestones

Effort is estimated in focused engineer-days and excludes stakeholder waiting time.

| Priority | Milestone | Effort | Dependencies |
|---:|---|---:|---|
| 1 | Reconcile `.ai/` relocation, missing orchestrator, Git state, and authoritative document paths | 0.5–1 day | None |
| 2 | Publish an accurate baseline inventory and redefine “completed” versus “planned” | 0.5 day | 1 |
| 3 | Record ADRs for the five-object boundary, orchestrator facade, and Markdown’s role | 1–2 days | 1–2 |
| 4 | Define canonical identifiers, versions, timestamps, statuses, and references | 1–2 days | 3 |
| 5 | Define machine-valid schemas for Project, State, Workflow, Agent, Artifact, and Decision | 3–5 days | 4 |
| 6 | Add missing runtime schemas: runs, transitions, evaluations, approvals, and events | 3–5 days | 4–5 |
| 7 | Specify the transition matrix, guards, failure paths, and recovery semantics | 2–4 days | 5–6 |
| 8 | Specify human approval checkpoints and authority rules | 1–2 days | 6–7 |
| 9 | Define the first vertical-slice acceptance scenario using one example project | 1 day | 5–8 |
| 10 | Select the minimal executable stack and establish source/test/tooling structure | 1–2 days | 9 |
| 11 | Implement schema validation and canonical serialization | 2–4 days | 10 |
| 12 | Implement append-only project events plus derived project state | 4–7 days | 6, 10–11 |
| 13 | Implement guarded state transitions with optimistic concurrency | 3–5 days | 7, 12 |
| 14 | Implement artifact creation, versioning, review, and approval | 4–7 days | 8, 11–13 |
| 15 | Implement workflow definitions and a deterministic workflow runner | 5–8 days | 11–14 |
| 16 | Implement agent registry and provider-independent agent execution boundary | 4–7 days | 11, 15 |
| 17 | Implement the Master Orchestrator as a thin application facade | 3–5 days | 13–16 |
| 18 | Complete the Founder Setup → Founder Brief vertical slice with resume support | 4–7 days | 17 |
| 19 | Add unit, contract, integration, replay, failure, and approval-path tests plus CI | 4–7 days | 11–18 |
| 20 | Evaluate the slice, document lessons, then implement Discovery as the second slice | 5–10 days | 18–19 |

Approximate foundation effort: **52–93 engineer-days**. A credible first executable vertical slice should be reachable around milestones 1–18, approximately **41–76 engineer-days**, depending on production-hardening depth.

The immediate next milestone should be repository truth reconciliation, followed by executable contracts—not completion of more empty Markdown component files.

No implementation or repository changes were made during the engineering review.
