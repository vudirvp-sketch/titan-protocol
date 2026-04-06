"""
Cycle detection for Execution DAG.
Prevents infinite loops in planning.
"""

from typing import Dict, List, Set, Tuple
from collections import defaultdict


class CycleDetector:
    """Detect cycles in directed acyclic graph."""
    
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
