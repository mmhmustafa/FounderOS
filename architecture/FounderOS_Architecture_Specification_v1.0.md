# FounderOS Architecture Specification v1.0

> **Document Type:** Core Architecture Specification  
> **Version:** v1.0-alpha  
> **Status:** Draft Architecture Constitution  
> **Purpose:** Define the foundational architecture of FounderOS using five core object types: Agents, Artifacts, Workflows, States, and Decisions.

> **Contract precedence:** The YAML fragments in this document are conceptual. `runtime/contracts/` contains the authoritative machine-valid implementation contracts and preserves the five-object product model while defining required supporting runtime records.

---

## 1. Executive Summary

FounderOS is not a prompt library.

FounderOS is a structured AI operating system for helping technical founders discover, validate, design, build, launch, and grow B2B SaaS companies.

The system is based on five core object types:

1. **Agent**
2. **Artifact**
3. **Workflow**
4. **State**
5. **Decision**

Every module, prompt, document, report, and execution step in FounderOS must be derived from these five object types.

This architecture allows FounderOS to evolve from Markdown documents into a real software platform.

---

## 2. Design Philosophy

FounderOS should behave like a startup operating system, not like a chatbot.

The founder should not need to know which prompt to run.

The system should:

- Understand the current project state
- Know what artifact is missing
- Select the correct agent
- Run the correct workflow
- Produce the next artifact
- Record key decisions
- Move the project forward

---

## 3. Core Object Model

```text
FounderOS
│
├── Agents
├── Artifacts
├── Workflows
├── States
└── Decisions
```

Everything in the system belongs to one of these categories.

---

# 4. Object Type 1: Agent

## Definition

An Agent is a specialist AI role responsible for producing or reviewing artifacts.

Examples:

- Master Orchestrator
- Venture Capitalist
- Market Research Analyst
- Network Engineer
- Product Manager
- CTO
- AI Architect
- UX Designer
- QA Engineer
- DevOps Engineer
- Growth Strategist
- Sales Strategist
- CEO Review Agent

---

## Agent Schema

```yaml
agent:
  id:
  name:
  role:
  domain:
  seniority:
  purpose:
  responsibilities:
  inputs:
  outputs:
  allowed_artifacts:
  tools:
  constraints:
  quality_gates:
  handoff_to:
  failure_modes:
  escalation_rules:
```

---

## Agent Rules

Every agent must:

1. Produce structured output.
2. Declare assumptions.
3. Provide confidence score.
4. Identify missing inputs.
5. Recommend next action.
6. Avoid unsupported claims.
7. Respect security and business constraints.
8. Hand off to the next valid workflow.

---

## Example Agent Instance

```yaml
agent:
  id: AGENT-CTO-001
  name: CTO Agent
  role: Technical Architect
  domain: SaaS Engineering
  seniority: Principal
  purpose: Design secure and scalable technical architecture.
  inputs:
    - PRD
    - Validation Report
    - Founder Constraints
  outputs:
    - Architecture Specification
    - Database Design
    - API Design
  handoff_to:
    - AI Architect
    - Sprint Planner
```

---

# 5. Object Type 2: Artifact

## Definition

An Artifact is a structured output produced by an agent and consumed by another agent or workflow.

Examples:

- Founder Brief
- Opportunity Report
- Validation Report
- PRD
- Architecture Specification
- AI Architecture Specification
- UX Specification
- Sprint Plan
- Test Plan
- Deployment Plan
- GTM Plan
- Sales Playbook
- CEO Review

---

## Artifact Schema

```yaml
artifact:
  id:
  name:
  type:
  version:
  owner_agent:
  status:
  created_at:
  updated_at:
  input_artifacts:
  output_consumers:
  confidence_score:
  assumptions:
  risks:
  open_questions:
  decision_refs:
```

---

## Required Artifact Sections

Every artifact must contain:

1. Summary
2. Inputs Used
3. Findings
4. Recommendations
5. Assumptions
6. Risks
7. Open Questions
8. Decision Log
9. Next Recommended Workflow

---

## Artifact Status

```yaml
status:
  - draft
  - under_review
  - approved
  - rejected
  - needs_more_research
  - deprecated
```

---

## Example Artifact Instance

```yaml
artifact:
  id: ARTIFACT-PRD-001
  name: PRD for FirewallPolicyAI
  type: PRD
  version: v1
  owner_agent: Product Manager
  status: draft
  input_artifacts:
    - Founder Brief
    - Opportunity Report
    - Validation Report
  output_consumers:
    - CTO Agent
    - UX Designer
    - AI Architect
```

---

# 6. Object Type 3: Workflow

## Definition

A Workflow is a sequence of states, agents, and artifacts that moves a startup project forward.

Examples:

- Founder Setup Workflow
- Discovery Workflow
- Validation Workflow
- Product Design Workflow
- Engineering Workflow
- AI Design Workflow
- Development Workflow
- Launch Workflow
- CEO Review Workflow

---

## Workflow Schema

```yaml
workflow:
  id:
  name:
  purpose:
  entry_state:
  exit_state:
  required_inputs:
  produced_artifacts:
  agents:
  steps:
  quality_gates:
  success_criteria:
  failure_paths:
  next_workflows:
```

---

## Example Workflow Instance

```yaml
workflow:
  id: WORKFLOW-DISCOVERY-001
  name: Discovery Workflow
  purpose: Identify and rank SaaS opportunities.
  entry_state: founder_brief_complete
  exit_state: opportunity_selected
  required_inputs:
    - Founder Brief
  produced_artifacts:
    - Opportunity Report
    - Opportunity Scorecard
  agents:
    - Market Research Agent
    - Network Pain Agent
    - Competitor Agent
    - Opportunity Scoring Agent
  next_workflows:
    - Validation Workflow
```

---

# 7. Object Type 4: State

## Definition

A State represents the current stage of a startup project inside FounderOS.

FounderOS must always know the current state before deciding what to do next.

---

## Core States

```text
NO_PROJECT
FOUNDER_SETUP
FOUNDER_BRIEF_COMPLETE
DISCOVERY_RUNNING
OPPORTUNITY_SELECTED
VALIDATION_RUNNING
VALIDATION_PASSED
PRODUCT_DESIGN_RUNNING
PRD_COMPLETE
ARCHITECTURE_RUNNING
ARCHITECTURE_COMPLETE
AI_DESIGN_RUNNING
AI_ARCHITECTURE_COMPLETE
DEVELOPMENT_PLANNING
SPRINT_READY
MVP_BUILDING
QA_RUNNING
READY_FOR_BETA
LAUNCH_RUNNING
CUSTOMERS_ACQUIRED
CEO_REVIEW
SCALING
```

---

## State Schema

```yaml
state:
  id:
  name:
  description:
  required_artifacts:
  allowed_actions:
  exit_criteria:
  next_states:
  failure_states:
  recovery_actions:
```

---

## Example State Instance

```yaml
state:
  id: STATE-VALIDATION-RUNNING
  name: Validation Running
  required_artifacts:
    - Opportunity Report
  allowed_actions:
    - conduct_interviews
    - test_pricing
    - create_landing_page
  exit_criteria:
    - Validation Report approved
    - Clear go/no-go recommendation
  next_states:
    - VALIDATION_PASSED
    - DISCOVERY_RUNNING
```

---

# 8. Object Type 5: Decision

## Definition

A Decision records an important choice made during the startup-building process.

Examples:

- Choose product opportunity
- Choose target customer
- Choose tech stack
- Choose pricing model
- Choose MVP scope
- Choose AI model
- Choose launch channel

---

## Decision Schema

```yaml
decision:
  id:
  title:
  date:
  state:
  context:
  options_considered:
  selected_option:
  rationale:
  confidence_score:
  risks:
  reversibility:
  owner:
  related_artifacts:
```

---

## Example Decision Instance

```yaml
decision:
  id: DECISION-TECH-001
  title: Choose PostgreSQL as primary database
  state: ARCHITECTURE_RUNNING
  context: Need relational structure, multi-tenancy, audit logs, and reporting.
  options_considered:
    - PostgreSQL
    - MongoDB
    - MySQL
  selected_option: PostgreSQL
  rationale: Strong relational model, mature ecosystem, good SaaS fit.
  confidence_score: 9
  reversibility: medium
```

---

# 9. Relationships Between Objects

```text
Agent produces Artifact
Artifact updates State
State triggers Workflow
Workflow invokes Agent
Agent records Decision
Decision modifies Artifact
Artifact feeds next Workflow
```

---

## Relationship Table

| Source | Relationship | Target |
|---|---|---|
| Agent | produces | Artifact |
| Artifact | enables | State transition |
| State | triggers | Workflow |
| Workflow | invokes | Agent |
| Decision | explains | Artifact |
| Artifact | feeds | Workflow |
| Workflow | updates | Project State |

---

# 10. Runtime Execution Model

FounderOS should execute like this:

```text
1. Read Project State
2. Identify Missing Artifacts
3. Select Valid Workflow
4. Select Required Agents
5. Generate Required Artifact
6. Apply Quality Gate
7. Record Decisions
8. Update State
9. Recommend Next Action
```

---

## Runtime Loop

```text
WHILE project_not_complete:
    read_state()
    identify_next_workflow()
    invoke_agents()
    generate_artifact()
    validate_quality()
    record_decisions()
    update_state()
    present_next_action()
```

---

# 11. Master Orchestrator Responsibility

The Master Orchestrator is not a normal agent.

It is the single user-facing entry point and a thin coordination facade over runtime services.

It should:

- Read state
- Determine missing artifacts
- Select next workflow
- Route to agents
- Validate outputs
- Request guarded state updates through the State Machine
- Show dashboard
- Ask only necessary questions

---

## Master Orchestrator Should Not

- Do all specialist work itself
- Ask the user to choose modules manually
- Skip quality gates
- Move forward with weak evidence
- Hide assumptions
- Create unsupported market claims

---

# 12. Project State Model

Every FounderOS project should maintain a project state file.

## Project State Schema

```yaml
project:
  id:
  name:
  founder:
  domain:
  current_state:
  current_workflow:
  completed_artifacts:
  pending_artifacts:
  decisions:
  risks:
  next_action:
  updated_at:
```

---

## Example

```yaml
project:
  id: PROJECT-001
  name: FirewallPolicyAI
  founder: Mustafa Hussain
  domain: Enterprise Networking
  current_state: VALIDATION_RUNNING
  current_workflow: Validation Workflow
  completed_artifacts:
    - Founder Brief
    - Opportunity Report
  pending_artifacts:
    - Validation Report
  next_action: Conduct 10 customer interviews
```

---

# 13. Quality Gates

Every workflow must pass quality gates.

## Universal Quality Gate

Before moving forward:

- Required artifact exists
- Artifact status is approved or reviewed
- Confidence score is at least 7
- Risks are documented
- Assumptions are documented
- Next state is valid
- Decision log is updated

---

## Failure Handling

If quality gate fails:

```text
Do not continue.
Explain why.
Recommend recovery action.
Stay in current state.
```

---

# 14. FounderOS State Machine

```text
NO_PROJECT
  ↓
FOUNDER_SETUP
  ↓
FOUNDER_BRIEF_COMPLETE
  ↓
DISCOVERY_RUNNING
  ↓
OPPORTUNITY_SELECTED
  ↓
VALIDATION_RUNNING
  ↓
VALIDATION_PASSED
  ↓
PRODUCT_DESIGN_RUNNING
  ↓
PRD_COMPLETE
  ↓
ARCHITECTURE_RUNNING
  ↓
ARCHITECTURE_COMPLETE
  ↓
AI_DESIGN_RUNNING
  ↓
AI_ARCHITECTURE_COMPLETE
  ↓
DEVELOPMENT_PLANNING
  ↓
SPRINT_READY
  ↓
MVP_BUILDING
  ↓
QA_RUNNING
  ↓
READY_FOR_BETA
  ↓
LAUNCH_RUNNING
  ↓
CUSTOMERS_ACQUIRED
  ↓
CEO_REVIEW
  ↓
SCALING
```

---

# 15. Storage Model

For the Markdown version of FounderOS:

```text
/runtime
  agent-registry.md
  artifact-registry.md
  workflow-engine.md
  state-machine.md
  decision-engine.md
  project-state.md

/templates
  artifact templates

/projects
  project-specific artifacts
```

For a future software version:

```text
agents table
artifacts table
workflows table
states table
decisions table
projects table
knowledge_entries table
```

---

# 16. Future Software Implementation

FounderOS can later become a real SaaS platform.

## Possible Stack

- Frontend: Next.js
- Backend: FastAPI or Node.js
- Database: PostgreSQL
- Vector DB: pgvector
- Queue: Redis + workers
- Auth: Auth.js / Clerk / Auth0
- Storage: S3-compatible
- AI: OpenAI / Anthropic / local models
- Deployment: Vercel + Render/Fly.io/AWS

---

## Future UI

Founder sees:

```text
Project Dashboard
Current State
Completed Artifacts
Pending Artifacts
Next Action
Agent Activity
Decision Log
Knowledge Base
```

---

# 17. Runtime Deliverable Status

The State Machine, Master Orchestrator, Project State, Agent Registry, Artifact Registry, Workflow Engine, Decision Engine, and Knowledge Base now have contract-level specifications.

The authoritative machine-valid contracts are in `runtime/contracts/`. No application runtime behavior is implemented yet.

The next deliverable is Milestone 3: implement the Runtime Foundation against those contracts and their acceptance scenarios.

---

# 18. Architecture Decision

## Decision

FounderOS will be based on five core object types:

- Agent
- Artifact
- Workflow
- State
- Decision

## Rationale

This reduces complexity, makes the system scalable, and allows future software implementation.

## Confidence

9/10

## Risk

The architecture may feel abstract initially, but it prevents the project from becoming an unmaintainable prompt library.

---

# 19. Final Summary

FounderOS should now be treated as a structured AI operating system.

Every future file, module, prompt, and workflow must derive from the five core object types.

This document is the architectural constitution of FounderOS v1.0.
