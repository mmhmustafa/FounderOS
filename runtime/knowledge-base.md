# Knowledge Base

> **Status:** Contract-level specification; implementation not started

## Purpose

The Knowledge Base stores and retrieves source material with provenance, scope, freshness, and content integrity. It supports the five core objects but is not itself a sixth core product object.

## Knowledge Entry Contract

Each entry must contain:

- Immutable internal identifier
- Project or global scope
- Source URI and source type
- Source title and publisher/owner when known
- Acquisition and last-verified UTC timestamps
- Immutable content URI and SHA-256 digest
- Version or source revision when available
- Provenance chain and ingestion actor
- Freshness status: `current`, `stale`, `unknown`, or `deprecated`
- Access classification
- Optional structured metadata and tags

The concrete machine schema is deferred until Milestone 3 confirms storage and retrieval boundaries; KnowledgeEntry is not one of the required Milestone 2 runtime records.

## Inputs

- Authorized source ingestion command
- Source content and provenance metadata
- Project/global scope
- Retrieval query and access context

## Outputs

- Ranked knowledge references with source, digest, scope, and freshness
- Explicit no-result or stale-result outcome
- Retrieval audit Event or trace reference

## Invariants

1. Knowledge never satisfies a transition guard by itself.
2. Relied-upon knowledge must be cited by an Artifact or Evaluation.
3. Retrieval preserves source attribution and exact content digest.
4. Stale or unknown freshness is visible to consumers.
5. Project-scoped knowledge cannot cross project boundaries.
6. Generated summaries never replace original-source references.
7. Ingestion does not imply factual approval.

## Mutation Boundary

Content changes produce a new immutable entry version/digest. Metadata freshness may be updated through an auditable operation. Indexes and embeddings are disposable derived read models.

## Dependencies

- Artifact Registry
- Evaluation service
- Event/audit boundary
- Future storage and retrieval adapters

## Failure and Recovery

Missing provenance, digest mismatch, inaccessible scope, or unsupported source rejects ingestion/retrieval. Stale evidence triggers refresh or explicit risk recording; it is never silently treated as current.

## Risks

- Retrieval ranking, embedding model, licensing, retention, and sensitive-data policy remain undefined.
- A machine schema is intentionally deferred to Milestone 3 implementation design.

## Next Step

Define KnowledgeEntry schema and repository/retrieval interfaces when implementing the Runtime Foundation in Milestone 3.
