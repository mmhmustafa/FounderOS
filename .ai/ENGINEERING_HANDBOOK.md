# ENGINEERING_HANDBOOK.md

# FounderOS Engineering Handbook
Version: v1.0-alpha

## Purpose

This handbook is the constitution of FounderOS.

Every AI assistant (ChatGPT, Codex, Claude, Cursor, etc.) must read this document before making changes.

---

# Vision

FounderOS is an AI-native platform that helps technical founders discover, validate, design, build, launch, and grow B2B SaaS products.

The long-term goal is to evolve FounderOS from a Markdown-based operating framework into a software platform.

---

# Core Principles

1. Problems before products.
2. Evidence before opinions.
3. Humans approve important decisions.
4. Build iteratively.
5. Every change must improve maintainability.
6. Documentation is part of the product.

---

# Five Core Objects

FounderOS is built on five object types:

- Agent
- Artifact
- Workflow
- State
- Decision

Everything must map to one of these.

---

# Repository Philosophy

The repository is the single source of truth.

Do not rely on chat history.

Important project knowledge belongs in version-controlled files.

---

# Core Documents

Read these first:

1. `.ai/PROJECT_CONTEXT.md`
2. `.ai/AI_INSTRUCTIONS.md`
3. `.ai/BUILD_ROADMAP.md`
4. `.ai/CURRENT_SPRINT.md`
5. `.ai/DECISIONS.md`
6. architecture/FounderOS_Architecture_Specification_v1.0.md

---

# Folder Responsibilities

runtime/
- orchestration
- state
- workflows

architecture/
- long-term design

agents/
- AI role definitions

templates/
- reusable artifacts

domains/
- domain-specific knowledge only

examples/
- reference implementations

---

# AI Working Rules

Before changing anything:

- Understand the current sprint.
- Avoid redesign unless requested.
- Prefer extending existing work.
- Keep naming consistent.
- Update CHANGELOG for meaningful milestones.

---

# Documentation Standard

Every major document should include:

- Purpose
- Inputs
- Outputs
- Dependencies
- Risks
- Next steps

---

# Git Standard

One logical milestone per commit.

Recommended format:

feat:
docs:
refactor:
fix:
chore:

---

# Sprint Workflow

1. Read current sprint.
2. Implement one milestone.
3. Update documentation.
4. Summarize changes.
5. Recommend next milestone.

---

# Long-Term Roadmap

Phase 1 - Runtime
Phase 2 - Discovery
Phase 3 - Validation
Phase 4 - Product
Phase 5 - Engineering
Phase 6 - AI
Phase 7 - Development
Phase 8 - Growth
Phase 9 - Web Application

---

# Lessons

Never optimize for document count.

Optimize for:

- clarity
- consistency
- reuse
- automation

---

# Definition of Success

A new AI assistant should be able to clone the repository, read the handbook, and become productive within one session.
