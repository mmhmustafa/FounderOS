"""Atlas Enterprise Federation (PR-037A, codename UNITY).

One enterprise, many observation points. Discovery profiles remain entry
points (credentials, schedules, boundaries) and their scopes stay fully
isolated; the federation layer reads their latest evidence AFTER
discovery and assembles one canonical Enterprise Graph:

- canonical devices via the PR-033 identity engine (serial numbers always
  merge; hostname+IP only within a declared administrative domain; a
  hostname alone or an IP alone never merges);
- canonical interfaces and links with per-observation provenance;
- merge decisions that state the WHY and a documented confidence;
- unknown boundaries that stay visible instead of being invented;
- a content-addressed enterprise ``TopologySnapshot`` every existing
  engine (prediction, path intelligence, topology viewer) consumes
  unchanged.

Deterministic only. Observations are never destroyed. Nothing merges
without deterministic evidence.
"""

from .builder import build_enterprise_graph
from .models import (
    CanonicalInterface,
    CanonicalLink,
    ContributionSummary,
    EnterpriseGraph,
    LinkObservation,
    MergeDecision,
)
from .snapshot import build_enterprise_snapshot
from .service import (
    enterprise_captured_configs,
    enterprise_failed_hosts,
    enterprise_scope_dir,
    enterprise_seed_addresses,
    get_enterprise_graph,
    get_enterprise_inventory,
    merge_observations,
    overall_freshness,
    resolve_canonical_device,
    search_enterprise,
    write_enterprise_artifacts,
)

__all__ = [
    "CanonicalInterface",
    "CanonicalLink",
    "ContributionSummary",
    "EnterpriseGraph",
    "LinkObservation",
    "MergeDecision",
    "build_enterprise_graph",
    "build_enterprise_snapshot",
    "enterprise_captured_configs",
    "enterprise_failed_hosts",
    "enterprise_scope_dir",
    "enterprise_seed_addresses",
    "get_enterprise_graph",
    "get_enterprise_inventory",
    "merge_observations",
    "overall_freshness",
    "resolve_canonical_device",
    "search_enterprise",
    "write_enterprise_artifacts",
]
