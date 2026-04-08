"""
Cycle detection for Execution DAG.
Prevents infinite loops in planning.

ITEM-DAG-112: Enhanced cycle detection with DAG and Amendment support.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional, Any
from collections import defaultdict
from enum import Enum


class AmendmentType(Enum):
    """Types of amendments that can be applied to a DAG."""
    ADD_EDGE = "add_edge"
    REMOVE_EDGE = "remove_edge"
    ADD_NODE = "add_node"
    REMOVE_NODE = "remove_node"
    UPDATE_NODE = "update_node"


@dataclass
class DAGNode:
    """
    Node in a DAG.
    
    Attributes:
        id: Unique identifier for the node
        data: Optional data associated with the node
        dependencies: List of node IDs this node depends on
    """
    id: str
    data: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    
    def __hash__(self):
        return hash(self.id)
    
    def __eq__(self, other):
        if isinstance(other, DAGNode):
            return self.id == other.id
        return False


@dataclass
class DAG:
    """
    Directed Acyclic Graph representation.
    
    Attributes:
        nodes: Dictionary of node ID to DAGNode
        edges: Adjacency list of from_node -> [to_nodes]
        metadata: Optional metadata about the DAG
    """
    nodes: Dict[str, DAGNode] = field(default_factory=dict)
    edges: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_node(self, node: DAGNode) -> None:
        """Add a node to the DAG."""
        self.nodes[node.id] = node
        # Add edges from dependencies
        for dep in node.dependencies:
            self.add_edge(dep, node.id)
    
    def add_edge(self, from_node: str, to_node: str) -> None:
        """Add a directed edge to the DAG."""
        if from_node not in self.edges:
            self.edges[from_node] = []
        if to_node not in self.edges[from_node]:
            self.edges[from_node].append(to_node)
    
    def remove_edge(self, from_node: str, to_node: str) -> bool:
        """Remove an edge from the DAG. Returns True if edge existed."""
        if from_node in self.edges and to_node in self.edges[from_node]:
            self.edges[from_node].remove(to_node)
            return True
        return False
    
    def get_node_ids(self) -> Set[str]:
        """Get all node IDs in the DAG."""
        ids = set(self.nodes.keys())
        for from_node, to_nodes in self.edges.items():
            ids.add(from_node)
            ids.update(to_nodes)
        return ids
    
    def copy(self) -> 'DAG':
        """Create a deep copy of the DAG."""
        new_dag = DAG(
            nodes={nid: DAGNode(id=n.id, data=n.data.copy(), dependencies=n.dependencies.copy()) 
                   for nid, n in self.nodes.items()},
            edges={k: v.copy() for k, v in self.edges.items()},
            metadata=self.metadata.copy()
        )
        return new_dag
    
    @classmethod
    def from_edges(cls, edges: List[Tuple[str, str]]) -> 'DAG':
        """
        Create a DAG from a list of edges.
        
        Args:
            edges: List of (from_node, to_node) tuples
            
        Returns:
            New DAG instance
        """
        dag = cls()
        for from_node, to_node in edges:
            dag.add_edge(from_node, to_node)
            if from_node not in dag.nodes:
                dag.nodes[from_node] = DAGNode(id=from_node)
            if to_node not in dag.nodes:
                dag.nodes[to_node] = DAGNode(id=to_node)
        return dag


@dataclass
class Amendment:
    """
    Amendment to be applied to a DAG.
    
    Represents a proposed change to the DAG structure that needs
    to be validated for cycle introduction before being applied.
    
    Attributes:
        amendment_type: Type of amendment
        source: Source node ID (for edge operations)
        target: Target node ID (for edge operations)
        node: Node data (for node operations)
        metadata: Additional metadata about the amendment
    """
    amendment_type: AmendmentType
    source: Optional[str] = None
    target: Optional[str] = None
    node: Optional[DAGNode] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def add_edge(cls, from_node: str, to_node: str, 
                 metadata: Dict[str, Any] = None) -> 'Amendment':
        """Create an ADD_EDGE amendment."""
        return cls(
            amendment_type=AmendmentType.ADD_EDGE,
            source=from_node,
            target=to_node,
            metadata=metadata or {}
        )
    
    @classmethod
    def remove_edge(cls, from_node: str, to_node: str,
                    metadata: Dict[str, Any] = None) -> 'Amendment':
        """Create a REMOVE_EDGE amendment."""
        return cls(
            amendment_type=AmendmentType.REMOVE_EDGE,
            source=from_node,
            target=to_node,
            metadata=metadata or {}
        )
    
    @classmethod
    def add_node(cls, node: DAGNode, 
                 metadata: Dict[str, Any] = None) -> 'Amendment':
        """Create an ADD_NODE amendment."""
        return cls(
            amendment_type=AmendmentType.ADD_NODE,
            node=node,
            metadata=metadata or {}
        )


class CycleDetector:
    """
    Detect cycles in directed acyclic graph.
    
    ITEM-DAG-112: Enhanced with DAG and Amendment support.
    
    Supports both incremental edge-by-edge building and
    whole-DAG analysis for planning engine integration.
    """
    
    def __init__(self):
        self.graph: Dict[str, List[str]] = defaultdict(list)
        self.nodes: Set[str] = set()
    
    def add_edge(self, from_node: str, to_node: str) -> None:
        """Add directed edge to graph."""
        self.graph[from_node].append(to_node)
        self.nodes.add(from_node)
        self.nodes.add(to_node)
    
    def detect_cycle(self) -> Tuple[bool, List[str]]:
        """
        Detect if graph contains a cycle.
        
        Returns:
            Tuple of (has_cycle, cycle_path)
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {node: WHITE for node in self.nodes}
        parent = {}
        
        def dfs(node: str) -> Tuple[bool, List[str]]:
            color[node] = GRAY
            
            for neighbor in self.graph.get(node, []):
                if color[neighbor] == GRAY:
                    # Found cycle - reconstruct path
                    cycle = [neighbor, node]
                    current = node
                    while current in parent and parent[current] != neighbor:
                        current = parent[current]
                        cycle.append(current)
                    cycle.append(neighbor)
                    return True, cycle[::-1]
                
                if color[neighbor] == WHITE:
                    parent[neighbor] = node
                    found, path = dfs(neighbor)
                    if found:
                        return True, path
            
            color[node] = BLACK
            return False, []
        
        for node in self.nodes:
            if color[node] == WHITE:
                found, path = dfs(node)
                if found:
                    return True, path
        
        return False, []
    
    def detect_cycle_in_dag(self, dag: DAG) -> Optional[List[str]]:
        """
        ITEM-DAG-112: Detect cycle in a DAG object.
        
        Args:
            dag: DAG object to check for cycles
            
        Returns:
            List of node IDs forming the cycle, or None if no cycle
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        
        # Get all nodes including those only in edges
        all_nodes = dag.get_node_ids()
        
        color = {node: WHITE for node in all_nodes}
        parent = {}
        
        def dfs(node: str) -> Tuple[bool, List[str]]:
            color[node] = GRAY
            
            for neighbor in dag.edges.get(node, []):
                if color[neighbor] == GRAY:
                    # Found cycle - reconstruct path
                    cycle = [neighbor, node]
                    current = node
                    while current in parent and parent[current] != neighbor:
                        current = parent[current]
                        cycle.append(current)
                    cycle.append(neighbor)
                    return True, cycle[::-1]
                
                if color[neighbor] == WHITE:
                    parent[neighbor] = node
                    found, path = dfs(neighbor)
                    if found:
                        return True, path
            
            color[node] = BLACK
            return False, []
        
        for node in all_nodes:
            if color[node] == WHITE:
                found, path = dfs(node)
                if found:
                    return path
        
        return None
    
    def validate_amendment(self, dag: DAG, amendment: Amendment) -> bool:
        """
        ITEM-DAG-112: Validate if an amendment would introduce a cycle.
        
        Simulates the amendment on a copy of the DAG and checks for cycles.
        
        Args:
            dag: Current DAG state
            amendment: Amendment to validate
            
        Returns:
            True if amendment is valid (no cycle introduced), False otherwise
        """
        # Create a copy to simulate the amendment
        simulated_dag = dag.copy()
        
        # Apply the amendment to the copy
        if amendment.amendment_type == AmendmentType.ADD_EDGE:
            if amendment.source and amendment.target:
                simulated_dag.add_edge(amendment.source, amendment.target)
                
        elif amendment.amendment_type == AmendmentType.ADD_NODE:
            if amendment.node:
                simulated_dag.add_node(amendment.node)
                
        elif amendment.amendment_type == AmendmentType.REMOVE_EDGE:
            # Removing edges cannot introduce cycles
            return True
            
        elif amendment.amendment_type == AmendmentType.REMOVE_NODE:
            # Removing nodes cannot introduce cycles
            return True
            
        elif amendment.amendment_type == AmendmentType.UPDATE_NODE:
            # Updating node data doesn't affect structure
            return True
        
        # Check for cycles in the simulated DAG
        cycle = self.detect_cycle_in_dag(simulated_dag)
        return cycle is None
    
    def validate_amendment_with_path(self, dag: DAG, amendment: Amendment) -> Tuple[bool, Optional[List[str]]]:
        """
        Validate amendment and return the cycle path if one would be introduced.
        
        Args:
            dag: Current DAG state
            amendment: Amendment to validate
            
        Returns:
            Tuple of (is_valid, cycle_path_if_invalid)
        """
        # Create a copy to simulate the amendment
        simulated_dag = dag.copy()
        
        # Apply the amendment to the copy
        if amendment.amendment_type == AmendmentType.ADD_EDGE:
            if amendment.source and amendment.target:
                simulated_dag.add_edge(amendment.source, amendment.target)
                
        elif amendment.amendment_type == AmendmentType.ADD_NODE:
            if amendment.node:
                simulated_dag.add_node(amendment.node)
                
        elif amendment.amendment_type in (AmendmentType.REMOVE_EDGE, 
                                          AmendmentType.REMOVE_NODE,
                                          AmendmentType.UPDATE_NODE):
            # These operations cannot introduce cycles
            return True, None
        
        # Check for cycles in the simulated DAG
        cycle = self.detect_cycle_in_dag(simulated_dag)
        return cycle is None, cycle
    
    def topological_sort(self) -> Tuple[bool, List[str]]:
        """
        Return topological order of nodes.
        
        Returns:
            Tuple of (success, ordered_nodes)
        """
        has_cycle, _ = self.detect_cycle()
        if has_cycle:
            return False, []
        
        in_degree = {node: 0 for node in self.nodes}
        for node in self.nodes:
            for neighbor in self.graph.get(node, []):
                in_degree[neighbor] += 1
        
        queue = [node for node, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            node = queue.pop(0)
            result.append(node)
            
            for neighbor in self.graph.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        return True, result
    
    def topological_sort_dag(self, dag: DAG) -> Tuple[bool, List[str]]:
        """
        Return topological order of nodes in a DAG object.
        
        Args:
            dag: DAG to sort
            
        Returns:
            Tuple of (success, ordered_nodes)
        """
        cycle = self.detect_cycle_in_dag(dag)
        if cycle:
            return False, []
        
        all_nodes = dag.get_node_ids()
        in_degree = {node: 0 for node in all_nodes}
        
        for from_node, to_nodes in dag.edges.items():
            for to_node in to_nodes:
                in_degree[to_node] += 1
        
        queue = [node for node, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            node = queue.pop(0)
            result.append(node)
            
            for neighbor in dag.edges.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        return True, result
    
    def clear(self) -> None:
        """Clear the internal graph state."""
        self.graph.clear()
        self.nodes.clear()


def validate_dag(edges: List[Tuple[str, str]]) -> Dict:
    """
    Validate DAG has no cycles.
    
    Args:
        edges: List of (from_node, to_node) tuples
    
    Returns:
        Validation result with cycle info if found
    """
    detector = CycleDetector()
    for from_node, to_node in edges:
        detector.add_edge(from_node, to_node)
    
    has_cycle, cycle_path = detector.detect_cycle()
    
    if has_cycle:
        return {
            "valid": False,
            "error": "[gap: dag_cycle_detected]",
            "cycle": cycle_path
        }
    
    success, order = detector.topological_sort()
    return {
        "valid": True,
        "order": order
    }


def validate_dag_object(dag: DAG) -> Dict:
    """
    ITEM-DAG-112: Validate a DAG object has no cycles.
    
    Args:
        dag: DAG object to validate
    
    Returns:
        Validation result with cycle info if found
    """
    detector = CycleDetector()
    cycle = detector.detect_cycle_in_dag(dag)
    
    if cycle:
        return {
            "valid": False,
            "error": "[gap: dag_cycle_detected]",
            "cycle": cycle
        }
    
    success, order = detector.topological_sort_dag(dag)
    return {
        "valid": True,
        "order": order
    }
