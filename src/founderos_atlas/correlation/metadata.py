"""The canonical snapshot-metadata contribution of Evidence Correlation.

Every snapshot that consumers treat as Enterprise Knowledge — each
per-profile discovery snapshot AND the federated enterprise snapshot —
must carry the SAME correlation metadata keys, produced the same way:

    correlation               fusion summary (counts, determinism flag)
    correlated_relationships  fused relationships with full provenance
    unresolved_observations   honest unknowns, with reason and origin
    address_ownership         the enterprise address ownership index
    ownership_conflicts       fail-closed multi-device claims (if any)

This helper is the single producer of those keys so the two pipelines
can never drift apart (the drift is exactly what once left the site
overview with zero inter-site links and dozens of resolvable peers
displayed as unresolved).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .engine import EvidenceCorrelationEngine


def correlation_metadata(
    devices: Iterable[Mapping[str, Any]],
    edges: Iterable[Mapping[str, Any]],
    *,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Run evidence correlation and return the canonical metadata keys."""

    correlation = EvidenceCorrelationEngine().correlate(
        devices, edges, observed_at=observed_at
    )
    ownership = correlation.ownership.to_dict()
    return {
        "correlation": correlation.summary(),
        "correlated_relationships": tuple(
            relationship.to_dict() for relationship in correlation.relationships
        ),
        "unresolved_observations": tuple(
            observation.to_dict() for observation in correlation.unresolved
        ),
        "address_ownership": ownership["addresses"],
        **(
            {"ownership_conflicts": ownership["conflicts"]}
            if ownership["conflicts"] else {}
        ),
    }
