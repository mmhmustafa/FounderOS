"""Extensible dependency graph: what depends on what, across layers.

The layered semantics future engines build on:

    device -> interface -> protocol -> topology -> service -> application -> users

Node *kinds* are open strings — VLANs, VRFs, OSPF processes, HSRP groups,
firewalls, applications, Kubernetes CNIs, and cloud resources all become
nodes without any model change. Nothing here hardcodes protocols; the
first builder populates device/interface/adjacency layers from the
topology snapshot, and future builders (configuration parsers, service
maps, cloud inventories) only *add* nodes and edges.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


# Well-known kinds (a vocabulary, not a restriction — any string works).
KIND_DEVICE = "device"
KIND_INTERFACE = "interface"
KIND_VLAN = "vlan"
KIND_VRF = "vrf"
KIND_ROUTING_PROTOCOL = "routing-protocol"
KIND_GATEWAY_PROTOCOL = "gateway-protocol"
KIND_SERVICE = "service"
KIND_APPLICATION = "application"
KIND_SITE = "site"
KIND_USER_POPULATION = "user-population"

RELATION_HOSTS = "hosts"            # device hosts interface/protocol
RELATION_CONNECTS = "connects"      # interface connects to interface/device
RELATION_RUNS_OVER = "runs-over"    # protocol/service runs over interface
RELATION_DEPENDS_ON = "depends-on"  # generic dependency


@dataclass(frozen=True)
class DependencyNode:
    node_id: str
    kind: str
    name: str
    device: str | None = None       # owning device, when applicable
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "name": self.name,
            "device": self.device,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class DependencyEdge:
    """Directed: the target depends on (is affected by) the source."""

    source_id: str
    target_id: str
    relation: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation,
            "attributes": dict(self.attributes),
        }


class DependencyGraph:
    """Deterministic directed graph of dependencies across all layers."""

    def __init__(self) -> None:
        self._nodes: dict[str, DependencyNode] = {}
        self._out: dict[str, list[DependencyEdge]] = {}
        self._in: dict[str, list[DependencyEdge]] = {}

    def add_node(self, node: DependencyNode) -> None:
        self._nodes[node.node_id] = node

    def add_edge(self, edge: DependencyEdge) -> None:
        if edge.source_id == edge.target_id:
            return
        existing = self._out.setdefault(edge.source_id, [])
        if any(
            item.target_id == edge.target_id and item.relation == edge.relation
            for item in existing
        ):
            return
        existing.append(edge)
        self._in.setdefault(edge.target_id, []).append(edge)

    def node(self, node_id: str) -> DependencyNode | None:
        return self._nodes.get(node_id)

    def nodes(self, kind: str | None = None) -> tuple[DependencyNode, ...]:
        values = sorted(self._nodes.values(), key=lambda item: item.node_id)
        if kind is None:
            return tuple(values)
        return tuple(node for node in values if node.kind == kind)

    def edges(self) -> tuple[DependencyEdge, ...]:
        collected: list[DependencyEdge] = []
        for source_id in sorted(self._out):
            collected.extend(
                sorted(self._out[source_id], key=lambda item: item.target_id)
            )
        return tuple(collected)

    def dependents_of(self, node_id: str) -> tuple[DependencyNode, ...]:
        """Everything transitively affected when this node fails.

        Deterministic breadth-first walk along outgoing edges (source
        affects target), excluding the start node.
        """

        seen: set[str] = {node_id}
        ordered: list[DependencyNode] = []
        queue: deque[str] = deque([node_id])
        while queue:
            current = queue.popleft()
            for edge in sorted(
                self._out.get(current, ()), key=lambda item: item.target_id
            ):
                if edge.target_id in seen:
                    continue
                seen.add(edge.target_id)
                node = self._nodes.get(edge.target_id)
                if node is not None:
                    ordered.append(node)
                queue.append(edge.target_id)
        return tuple(ordered)

    def neighbors(self, node_id: str) -> tuple[str, ...]:
        """Adjacent node ids in either direction (deterministic)."""

        found: set[str] = set()
        for edge in self._out.get(node_id, ()):
            found.add(edge.target_id)
        for edge in self._in.get(node_id, ()):
            found.add(edge.source_id)
        return tuple(sorted(found))

    def path_exists(
        self, from_id: str, to_id: str, *, without: frozenset[str] = frozenset()
    ) -> bool:
        """Undirected reachability, optionally with nodes removed —
        the primitive redundancy evaluation is built on."""

        if from_id in without or to_id in without:
            return False
        seen: set[str] = {from_id}
        queue: deque[str] = deque([from_id])
        while queue:
            current = queue.popleft()
            if current == to_id:
                return True
            for neighbor in self.neighbors(current):
                if neighbor in seen or neighbor in without:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes()],
            "edges": [edge.to_dict() for edge in self.edges()],
        }


def device_node_id(hostname: str) -> str:
    return f"device:{hostname.casefold()}"


def interface_node_id(hostname: str, interface: str) -> str:
    return f"interface:{hostname.casefold()}:{interface.casefold()}"


def build_topology_dependency_graph(snapshot: dict | None) -> DependencyGraph:
    """First builder: devices, interfaces, and adjacency from a snapshot.

    Future builders (configuration parsers, service maps, cloud
    inventories) add VLAN/VRF/protocol/service/application nodes onto the
    same graph without touching this one.
    """

    graph = DependencyGraph()
    if not isinstance(snapshot, dict):
        return graph
    hostname_by_id: dict[str, str] = {}
    for device in snapshot.get("devices") or ():
        if not isinstance(device, dict):
            continue
        hostname = str(device.get("hostname") or "unknown")
        hostname_by_id[str(device.get("device_id"))] = hostname
        graph.add_node(
            DependencyNode(
                node_id=device_node_id(hostname),
                kind=KIND_DEVICE,
                name=hostname,
                device=hostname,
                attributes={
                    "management_ip": str(device.get("management_ip") or ""),
                    "platform": str(device.get("platform") or ""),
                },
            )
        )
        for interface in device.get("interfaces") or ():
            if not isinstance(interface, dict):
                continue
            name = str(interface.get("name") or "unknown")
            node_id = interface_node_id(hostname, name)
            graph.add_node(
                DependencyNode(
                    node_id=node_id,
                    kind=KIND_INTERFACE,
                    name=name,
                    device=hostname,
                    attributes={"status": str(interface.get("status") or "")},
                )
            )
            # The interface depends on its device; the device's reachability
            # depends on its interfaces (bidirectional dependency edges).
            graph.add_edge(
                DependencyEdge(device_node_id(hostname), node_id, RELATION_HOSTS)
            )
    for edge in snapshot.get("edges") or ():
        if not isinstance(edge, dict):
            continue
        local = hostname_by_id.get(
            str(edge.get("local_device_id")), str(edge.get("local_device_id"))
        )
        remote = str(edge.get("remote_hostname"))
        local_interface = str(edge.get("local_interface") or "unknown")
        remote_interface = edge.get("remote_interface")
        local_if_id = _ensure_interface(graph, local, local_interface)
        remote_device_id = device_node_id(remote)
        if graph.node(remote_device_id) is None:
            graph.add_node(
                DependencyNode(
                    node_id=remote_device_id,
                    kind=KIND_DEVICE,
                    name=remote,
                    device=remote,
                )
            )
        if remote_interface:
            # A link exists through BOTH endpoints: shutting either
            # interface breaks the path — so the path must traverse both.
            remote_if_id = _ensure_interface(graph, remote, str(remote_interface))
            graph.add_edge(
                DependencyEdge(local_if_id, remote_if_id, RELATION_CONNECTS)
            )
        else:
            graph.add_edge(
                DependencyEdge(local_if_id, remote_device_id, RELATION_CONNECTS)
            )
    return graph


def _ensure_interface(graph: DependencyGraph, device: str, interface: str) -> str:
    node_id = interface_node_id(device, interface)
    if graph.node(node_id) is None:
        graph.add_node(
            DependencyNode(
                node_id=node_id,
                kind=KIND_INTERFACE,
                name=interface,
                device=device,
            )
        )
    if graph.node(device_node_id(device)) is None:
        graph.add_node(
            DependencyNode(
                node_id=device_node_id(device),
                kind=KIND_DEVICE,
                name=device,
                device=device,
            )
        )
    graph.add_edge(DependencyEdge(device_node_id(device), node_id, RELATION_HOSTS))
    return node_id
