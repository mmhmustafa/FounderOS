"""Critical path model: forwarding paths whose loss matters.

Architecture first: a ``CriticalPath`` carries the hop endpoints, the
dependency node ids it rests on, its redundancy assessment, and a
criticality band. The first identifier is honest and simple — it reports
the device pairs whose topology connectivity *breaks* when the changed
node is removed (critical, non-redundant). Future engines (routing
tables, traffic data, service maps) replace the identifier without
touching the model or the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .dependency import DependencyGraph, KIND_DEVICE
from .redundancy import RedundancyAssessment, assess_redundancy


CRITICALITY_HIGH = "high"
CRITICALITY_MEDIUM = "medium"
CRITICALITY_LOW = "low"


@dataclass(frozen=True)
class CriticalPath:
    path_id: str
    description: str
    hops: tuple[str, ...]                 # device endpoints (full hops later)
    dependencies: tuple[str, ...]         # dependency node ids the path rests on
    redundancy: RedundancyAssessment
    criticality: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_id": self.path_id,
            "description": self.description,
            "hops": list(self.hops),
            "dependencies": list(self.dependencies),
            "redundancy": self.redundancy.to_dict(),
            "criticality": self.criticality,
        }


def affected_critical_paths(
    graph: DependencyGraph, changed_node_id: str
) -> tuple[CriticalPath, ...]:
    """Device pairs whose connectivity breaks without the changed node.

    Pairs that stay connected have redundancy and are not reported as
    affected critical paths. Deterministic order by path id.
    """

    removed = frozenset({changed_node_id})
    devices = [
        node for node in graph.nodes(KIND_DEVICE) if node.node_id != changed_node_id
    ]
    paths: list[CriticalPath] = []
    for index, first in enumerate(devices):
        for second in devices[index + 1 :]:
            if not graph.path_exists(first.node_id, second.node_id):
                continue  # not connected today: nothing to break
            redundancy = assess_redundancy(
                graph, first.node_id, second.node_id, removed=removed
            )
            if redundancy.redundant:
                continue  # an alternate path absorbs the change
            paths.append(
                CriticalPath(
                    path_id=f"path:{first.name}:{second.name}",
                    description=(
                        f"Forwarding between {first.name} and {second.name}"
                    ),
                    hops=(first.name, second.name),
                    dependencies=(changed_node_id,),
                    redundancy=redundancy,
                    criticality=CRITICALITY_HIGH,
                )
            )
    paths.sort(key=lambda item: item.path_id)
    return tuple(paths)
