"""
Graph utilities for Flow Builder.
Provides DAG construction, topological sort, and graph traversal.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class Node:
    """Represents a node in the flow graph."""
    id: str
    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    position: Dict[str, float] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.data.get("label", self.id)


@dataclass
class Edge:
    """Represents an edge (connection) in the flow graph."""
    id: str
    source: str
    target: str
    source_handle: Optional[str] = None
    target_handle: Optional[str] = None
    condition: Optional[str] = None  # For conditional edges (true/false)


class FlowGraph:
    """
    Directed Acyclic Graph representation of a flow.
    Provides methods for traversal, topological sort, and execution planning.
    """

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self._adjacency: Dict[str, List[str]] = defaultdict(list)
        self._reverse_adjacency: Dict[str, List[str]] = defaultdict(list)
        self._edge_map: Dict[str, List[Edge]] = defaultdict(list)  # source -> edges

    @classmethod
    def from_definition(cls, definition: dict) -> 'FlowGraph':
        """Build a FlowGraph from a flow definition JSON."""
        graph = cls()

        # Add nodes
        for node_data in definition.get("nodes", []):
            node = Node(
                id=node_data["id"],
                type=node_data["type"],
                data=node_data.get("data", {}),
                position=node_data.get("position", {})
            )
            graph.add_node(node)

        # Add edges
        for edge_data in definition.get("edges", []):
            edge = Edge(
                id=edge_data.get("id", f"{edge_data['source']}-{edge_data['target']}"),
                source=edge_data["source"],
                target=edge_data["target"],
                source_handle=edge_data.get("sourceHandle"),
                target_handle=edge_data.get("targetHandle"),
                condition=edge_data.get("condition")
            )
            graph.add_edge(edge)

        return graph

    def add_node(self, node: Node):
        """Add a node to the graph."""
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge):
        """Add an edge to the graph."""
        self.edges.append(edge)
        self._adjacency[edge.source].append(edge.target)
        self._reverse_adjacency[edge.target].append(edge.source)
        self._edge_map[edge.source].append(edge)

    def get_node(self, node_id: str) -> Optional[Node]:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def get_starting_nodes(self) -> List[str]:
        """Get nodes with no incoming edges (flow entry points)."""
        starting = []
        for node_id in self.nodes:
            if not self._reverse_adjacency[node_id]:
                starting.append(node_id)
        return starting

    def get_ending_nodes(self) -> List[str]:
        """Get nodes with no outgoing edges (flow exit points)."""
        ending = []
        for node_id in self.nodes:
            if not self._adjacency[node_id]:
                ending.append(node_id)
        return ending

    def get_predecessors(self, node_id: str) -> List[str]:
        """Get all nodes that have edges pointing to this node."""
        return self._reverse_adjacency.get(node_id, [])

    def get_successors(self, node_id: str) -> List[str]:
        """Get all nodes that this node has edges pointing to."""
        return self._adjacency.get(node_id, [])

    def get_outgoing_edges(self, node_id: str) -> List[Edge]:
        """Get all edges originating from a node."""
        return self._edge_map.get(node_id, [])

    def topological_sort(self) -> List[str]:
        """
        Return nodes in topological order (Kahn's algorithm).
        Raises ValueError if the graph contains a cycle.
        """
        in_degree = {node_id: 0 for node_id in self.nodes}
        for source, targets in self._adjacency.items():
            for target in targets:
                in_degree[target] += 1

        queue = deque([n for n, d in in_degree.items() if d == 0])
        result = []

        while queue:
            node_id = queue.popleft()
            result.append(node_id)

            for successor in self._adjacency[node_id]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)

        if len(result) != len(self.nodes):
            raise ValueError("Flow graph contains a cycle - cannot execute")

        return result

    def has_cycle(self) -> bool:
        """Check if the graph contains a cycle."""
        try:
            self.topological_sort()
            return False
        except ValueError:
            return True

    def dependencies_met(self, node_id: str, completed: Set[str]) -> bool:
        """Check if all dependencies (predecessors) of a node have been completed."""
        predecessors = self.get_predecessors(node_id)
        return all(pred in completed for pred in predecessors)

    def get_executable_nodes(self, completed: Set[str], running: Set[str]) -> List[str]:
        """
        Get nodes that are ready to execute.
        A node is ready if:
        1. It's not completed
        2. It's not currently running
        3. All its predecessors are completed
        """
        executable = []
        for node_id in self.nodes:
            if node_id not in completed and node_id not in running:
                if self.dependencies_met(node_id, completed):
                    executable.append(node_id)
        return executable

    def evaluate_edges(self, node_id: str, result: dict) -> List[str]:
        """
        Evaluate outgoing edges from a node and return target nodes.
        For condition nodes, only returns targets matching the branch result.
        """
        outgoing = self.get_outgoing_edges(node_id)
        node = self.get_node(node_id)

        if not outgoing:
            return []

        # For condition nodes, filter by branch
        if node and node.type == "condition":
            branch = result.get("branch", "true")
            targets = []
            for edge in outgoing:
                # Match edge's source handle to the branch
                if edge.source_handle == branch or edge.condition == branch:
                    targets.append(edge.target)
            return targets

        # For non-condition nodes, return all targets
        return [edge.target for edge in outgoing]

    def validate(self) -> List[str]:
        """
        Validate the flow graph.
        Returns a list of validation errors (empty if valid).
        """
        errors = []

        # Check for cycles
        if self.has_cycle():
            errors.append("Flow contains a cycle")

        # Check for orphan nodes (not reachable from start)
        starting = self.get_starting_nodes()
        if not starting:
            errors.append("Flow has no starting nodes")

        # Check that start nodes are of type 'start'
        for node_id in starting:
            node = self.get_node(node_id)
            if node and node.type != "start":
                errors.append(f"Node '{node_id}' has no incoming edges but is not a Start node")

        # Check for disconnected components
        reachable = set()
        queue = deque(starting)
        while queue:
            node_id = queue.popleft()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            queue.extend(self.get_successors(node_id))

        unreachable = set(self.nodes.keys()) - reachable
        if unreachable:
            errors.append(f"Nodes not reachable from start: {', '.join(unreachable)}")

        # Check condition nodes have exactly two outgoing edges
        for node_id, node in self.nodes.items():
            if node.type == "condition":
                outgoing = self.get_outgoing_edges(node_id)
                if len(outgoing) < 2:
                    errors.append(f"Condition node '{node_id}' must have at least 2 outgoing edges (true/false)")

        return errors

    def to_dict(self) -> dict:
        """Convert the graph back to a flow definition dict."""
        return {
            "nodes": [
                {
                    "id": node.id,
                    "type": node.type,
                    "data": node.data,
                    "position": node.position
                }
                for node in self.nodes.values()
            ],
            "edges": [
                {
                    "id": edge.id,
                    "source": edge.source,
                    "target": edge.target,
                    "sourceHandle": edge.source_handle,
                    "targetHandle": edge.target_handle,
                    "condition": edge.condition
                }
                for edge in self.edges
            ]
        }

    def __repr__(self) -> str:
        return f"FlowGraph(nodes={len(self.nodes)}, edges={len(self.edges)})"
