"""Internal causal graph: evidence nodes, directed cause->effect edges.

Built by the correlation engine and consumed by hypothesis generation and
the explanation chain. Internal only — the graph never appears in the JSON
artifact; the artifact carries the derived reasoning with evidence ids.
"""

from __future__ import annotations


class CausalGraph:
    def __init__(self) -> None:
        self._effects: dict[str, list[tuple[str, str]]] = {}
        self._causes: dict[str, list[tuple[str, str]]] = {}

    def add_edge(self, cause_id: str, effect_id: str, reason: str) -> None:
        if cause_id == effect_id:
            return
        forward = self._effects.setdefault(cause_id, [])
        if not any(target == effect_id for target, _ in forward):
            forward.append((effect_id, reason))
            self._causes.setdefault(effect_id, []).append((cause_id, reason))

    def effects_of(self, evidence_id: str) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._effects.get(evidence_id, ())))

    def causes_of(self, evidence_id: str) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._causes.get(evidence_id, ())))

    def has_edges(self) -> bool:
        return bool(self._effects)

    def chain_from(self, root_id: str) -> tuple[str, ...]:
        """Deterministic depth-first cause->effect chain from one root."""

        chain: list[str] = []
        seen: set[str] = set()

        def walk(node: str) -> None:
            if node in seen:
                return
            seen.add(node)
            chain.append(node)
            for target, _reason in self.effects_of(node):
                walk(target)

        walk(root_id)
        return tuple(chain)
