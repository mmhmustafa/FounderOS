# Artifact Registry

> **Status:** Validated repository and reusable creation/approval lifecycle service implemented
>
> **Schema:** `runtime/contracts/artifact.schema.json`

## Purpose

The Artifact Registry owns Artifact metadata, immutable content versions, review status, lineage, and evidence references.

## Inputs

- Project and producing AgentRun references
- Artifact type, version, immutable content URI, and SHA-256 digest
- Input lineage, assumptions, risks, and open questions
- Evaluation and Approval outcomes

## Outputs

- Persisted Artifact version
- Artifact lifecycle Events
- Exact version references for workflows, decisions, evaluations, and transitions

## Invariants

1. Artifact IDs use `art_`; content versions use Semantic Versioning.
2. Content is immutable for an Artifact version and verified by digest.
3. Content changes create a new version; metadata status changes increment revision.
4. Artifact lineage references exact input versions.
5. AI-generated content starts as `draft`, never `approved`.
6. Approval requires completed passing Evaluations and authorized human Approval where policy requires it.
7. An approved version remains historically resolvable after deprecation or supersession.
8. Cross-project artifact references are rejected unless a future sharing policy explicitly allows them.

## Status Transitions

```text
draft -> under_review
under_review -> approved | rejected | needs_more_research
needs_more_research -> draft
rejected -> draft
approved -> deprecated
```

Rework that changes content creates a new version rather than mutating reviewed content.

## Content Boundary

The Registry stores metadata and a content address. Artifact content storage is an implementation choice, but writes must be immutable and digest-verifiable before metadata is committed.

## Dependencies

- Agent Registry
- Evaluation and Human Approval services
- Decision Engine
- Project State reference attachment

## Failure and Recovery

Digest mismatch, invalid lineage, missing content, or cross-project ownership rejects creation. Failed review preserves the reviewed version and requires a new draft/version as appropriate.

## Risks

- Artifact-type-specific content schemas are future work.
- Storage retention, access control, and large-object handling are undecided.

## Implementation

`ArtifactLifecycleService` owns Artifact creation Events and approval-reference attachment. Repositories retain contract validation, immutable identity, defensive reads, and revision-checked replacement. Content storage remains external.

## Next Step

Add audit diagnostics without expanding Artifact behavior.
