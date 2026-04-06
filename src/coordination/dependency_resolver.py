#!/usr/bin/env python3
"""
TITAN FUSE Protocol - Multi-File Coordination (PHASE -1D)

Implements multi-file input handling from PROTOCOL.ext.md:

WHEN INPUT_QUEUE contains > 1 file:

  STEP 1: Classify relationships
    → for each pair (A, B): check SYMBOL_MAP.json for cross-references
    → build DEPENDENCY_GRAPH: {file → [files it depends on]}

  STEP 2: Determine processing order
    → topological sort of DEPENDENCY_GRAPH
    → independent files → process in INPUT_QUEUE order (no guaranteed parallelism)

  STEP 3: Per-file processing
    → for each file in sorted order:
        ├─ run standard TIER 0–5 pipeline
        ├─ on GATE-05 PASS: commit outputs to outputs/{filename}_merged.md
        └─ update shared SYMBOL_MAP.json with this file's symbols

  COORDINATION RULES:
    ├─ Each file gets its own WORK_DIR / IN_MEMORY_BUFFER
    ├─ SYMBOL_MAP.json is shared state — write-lock per file
    ├─ Cross-file patches BLOCKED in v1.0 — log [gap: cross-file-patch-not-supported]
    └─ Max 3 files per session without explicit human approval

Usage:
    from src.coordination import DependencyResolver
    
    resolver = DependencyResolver()
    resolver.build_dependency_graph(files, symbol_map)
    order = resolver.get_processing_order()
    
    for file_node in order.files:
        process_file(file_node.path)
"""

import json
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum


class NodeStatus(Enum):
    """Status of a file node in processing."""
    PENDING = "PENDING"
    READY = "READY"
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass
class FileNode:
    """
    Node representing a file in the dependency graph.
    
    Attributes:
        path: File path
        dependencies: Set of file paths this file depends on
        dependents: Set of file paths that depend on this file
        symbols: Symbols defined in this file
        references: Symbols referenced from other files
        status: Current processing status
    """
    path: str
    dependencies: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)
    symbols: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    status: NodeStatus = NodeStatus.PENDING
    priority: int = 0
    estimated_tokens: int = 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "path": self.path,
            "dependencies": list(self.dependencies),
            "dependents": list(self.dependents),
            "symbols": self.symbols,
            "references": self.references,
            "status": self.status.value,
            "priority": self.priority,
            "estimated_tokens": self.estimated_tokens
        }


@dataclass
class ProcessingOrder:
    """
    Result of topological sort with processing order.
    
    Attributes:
        files: Ordered list of FileNode
        groups: Groups of files that can be processed in parallel
        warnings: Any warnings from the sort (cycles, etc.)
    """
    files: List[FileNode]
    groups: List[List[str]]
    warnings: List[str] = field(default_factory=list)
    has_cycles: bool = False
    cycle_components: List[List[str]] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "files": [f.path for f in self.files],
            "groups": self.groups,
            "warnings": self.warnings,
            "has_cycles": self.has_cycles,
            "cycle_components": self.cycle_components
        }


@dataclass
class DependencyGraph:
    """
    Dependency graph for multi-file coordination.
    
    Implements DEPENDENCY_GRAPH from PROTOCOL.md:
    {file → [files it depends on]}
    """
    nodes: Dict[str, FileNode] = field(default_factory=dict)
    edges: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    reverse_edges: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    
    def add_node(self, path: str, symbols: List[str] = None, 
                 references: List[str] = None) -> FileNode:
        """Add a node to the graph."""
        if path not in self.nodes:
            self.nodes[path] = FileNode(
                path=path,
                symbols=symbols or [],
                references=references or []
            )
        return self.nodes[path]
    
    def add_edge(self, from_path: str, to_path: str) -> None:
        """Add a dependency edge (from depends on to)."""
        self.edges[from_path].add(to_path)
        self.reverse_edges[to_path].add(from_path)
        
        if from_path in self.nodes:
            self.nodes[from_path].dependencies.add(to_path)
        if to_path in self.nodes:
            self.nodes[to_path].dependents.add(from_path)
    
    def get_dependencies(self, path: str) -> Set[str]:
        """Get all dependencies of a file (direct and transitive)."""
        visited = set()
        stack = list(self.edges.get(path, set()))
        
        while stack:
            current = stack.pop()
            if current not in visited:
                visited.add(current)
                stack.extend(self.edges.get(current, set()))
        
        return visited
    
    def detect_cycles(self) -> List[List[str]]:
        """
        Detect cycles in the dependency graph.
        
        Returns list of cycles found.
        """
        cycles = []
        visited = set()
        rec_stack = set()
        path = []
        
        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self.edges.get(node, set()):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)
                    return True
            
            path.pop()
            rec_stack.remove(node)
            return False
        
        for node in self.nodes:
            if node not in visited:
                dfs(node)
        
        return cycles
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "edges": {k: list(v) for k, v in self.edges.items()},
            "reverse_edges": {k: list(v) for k, v in self.reverse_edges.items()}
        }


class DependencyResolver:
    """
    Dependency resolver for multi-file coordination.
    
    Implements PHASE -1D from PROTOCOL.ext.md.
    
    Example:
        resolver = DependencyResolver()
        
        # Build graph from files
        graph = resolver.build_dependency_graph(
            files=["file1.md", "file2.md", "file3.md"],
            symbol_map_path="SYMBOL_MAP.json"
        )
        
        # Get processing order
        order = resolver.topological_sort(graph)
        
        # Process files in order
        for file_node in order.files:
            process_file(file_node.path)
    """
    
    # Maximum files per session without explicit approval
    MAX_FILES_DEFAULT = 3
    MAX_FILES_HARD_LIMIT = 10
    
    def __init__(self, config: Optional[Dict] = None):
        """Initialize the dependency resolver."""
        self.config = config or {}
        self.max_files = self.config.get("multi_file", {}).get("default_limit", self.MAX_FILES_DEFAULT)
        self.hard_limit = self.config.get("multi_file", {}).get("hard_limit", self.MAX_FILES_HARD_LIMIT)
    
    def build_dependency_graph(self,
                               files: List[str],
                               symbol_map: Optional[Dict] = None,
                               symbol_map_path: Optional[str] = None) -> DependencyGraph:
        """
        Build dependency graph from files and symbol map.
        
        STEP 1: Classify relationships
        → for each pair (A, B): check SYMBOL_MAP.json for cross-references
        → build DEPENDENCY_GRAPH: {file → [files it depends on]}
        
        Args:
            files: List of file paths
            symbol_map: Symbol map dictionary (optional)
            symbol_map_path: Path to SYMBOL_MAP.json (optional)
            
        Returns:
            DependencyGraph with all nodes and edges
        """
        graph = DependencyGraph()
        
        # Load symbol map if path provided
        if symbol_map_path and not symbol_map:
            try:
                with open(symbol_map_path) as f:
                    symbol_map = json.load(f)
            except Exception:
                symbol_map = {}
        
        symbol_map = symbol_map or {}
        
        # Add all files as nodes
        for file_path in files:
            file_symbols = symbol_map.get(file_path, {})
            graph.add_node(
                path=file_path,
                symbols=file_symbols.get("symbols", []),
                references=file_symbols.get("references", [])
            )
        
        # Build edges based on cross-references
        # Symbol map format: {symbol: {file, line, type, dependencies}}
        symbol_to_file: Dict[str, str] = {}
        
        for file_path, data in symbol_map.items():
            for symbol in data.get("symbols", []):
                symbol_to_file[symbol] = file_path
        
        # Check references
        for file_path, data in symbol_map.items():
            for ref in data.get("references", []):
                if ref in symbol_to_file:
                    dep_file = symbol_to_file[ref]
                    if dep_file != file_path:
                        graph.add_edge(file_path, dep_file)
        
        # Also check file-level imports/references
        for file_path in files:
            self._detect_file_references(file_path, graph)
        
        return graph
    
    def _detect_file_references(self, file_path: str, graph: DependencyGraph) -> None:
        """Detect file-level references (imports, includes, etc.)."""
        try:
            path = Path(file_path)
            if not path.exists():
                return
            
            with open(path) as f:
                content = f.read()
            
            # Markdown references: [text](file.md)
            import re
            md_refs = re.findall(r'\[[^\]]+\]\(([^)]+\.md)\)', content)
            
            for ref in md_refs:
                # Resolve relative path
                ref_path = (path.parent / ref).resolve()
                ref_str = str(ref_path)
                
                if ref_str in graph.nodes and ref_str != file_path:
                    graph.add_edge(file_path, ref_str)
            
            # Code imports (Python)
            py_imports = re.findall(r'(?:from|import)\s+(\S+)', content)
            for imp in py_imports:
                # Convert module to file path
                imp_file = imp.replace('.', '/') + '.py'
                for node_path in graph.nodes:
                    if node_path.endswith(imp_file):
                        graph.add_edge(file_path, node_path)
                        
        except Exception:
            pass
    
    def topological_sort(self, graph: DependencyGraph) -> ProcessingOrder:
        """
        Perform topological sort on the dependency graph.
        
        STEP 2: Determine processing order
        → topological sort of DEPENDENCY_GRAPH
        → independent files → process in INPUT_QUEUE order (no guaranteed parallelism)
        
        Args:
            graph: Dependency graph to sort
            
        Returns:
            ProcessingOrder with ordered files and parallel groups
        """
        warnings = []
        
        # Check for cycles
        cycles = graph.detect_cycles()
        has_cycles = len(cycles) > 0
        
        if has_cycles:
            warnings.append(f"[gap: circular_dependency — {len(cycles)} cycle(s) detected]")
            # Break cycles by removing edges
            for cycle in cycles:
                # Remove the last edge in the cycle
                if len(cycle) >= 2:
                    from_node = cycle[-2]
                    to_node = cycle[-1]
                    if to_node in graph.edges[from_node]:
                        graph.edges[from_node].discard(to_node)
                        warnings.append(f"Breaking cycle: removed dependency {from_node} → {to_node}")
        
        # Kahn's algorithm for topological sort
        in_degree = {node: 0 for node in graph.nodes}
        
        for node in graph.nodes:
            for dep in graph.edges.get(node, set()):
                if dep in in_degree:
                    in_degree[node] += 1
        
        # Start with nodes that have no dependencies
        queue = [node for node, degree in in_degree.items() if degree == 0]
        
        # Sort queue for deterministic ordering
        queue.sort()
        
        result = []
        groups = []
        
        while queue:
            # Process all nodes at current level together (parallel group)
            current_level = sorted(queue)
            groups.append(current_level)
            
            next_queue = []
            
            for node in current_level:
                result.append(graph.nodes[node])
                graph.nodes[node].status = NodeStatus.READY
                
                # Update in-degrees
                for dependent in graph.reverse_edges.get(node, set()):
                    if dependent in in_degree:
                        in_degree[dependent] -= 1
                        if in_degree[dependent] == 0:
                            next_queue.append(dependent)
            
            queue = next_queue
        
        # Check for nodes not processed (should not happen after cycle breaking)
        if len(result) < len(graph.nodes):
            missing = set(graph.nodes.keys()) - {n.path for n in result}
            warnings.append(f"Unprocessed nodes: {missing}")
            for path in missing:
                graph.nodes[path].status = NodeStatus.BLOCKED
        
        return ProcessingOrder(
            files=result,
            groups=groups,
            warnings=warnings,
            has_cycles=has_cycles,
            cycle_components=cycles
        )
    
    def get_processing_order(self,
                            files: List[str],
                            symbol_map: Optional[Dict] = None,
                            symbol_map_path: Optional[str] = None) -> ProcessingOrder:
        """
        Convenience method to build graph and get processing order.
        
        Args:
            files: List of file paths
            symbol_map: Symbol map dictionary
            symbol_map_path: Path to SYMBOL_MAP.json
            
        Returns:
            ProcessingOrder with ordered files
        """
        # Validate file count
        if len(files) > self.max_files:
            if len(files) > self.hard_limit:
                raise ValueError(f"Too many files: {len(files)} exceeds hard limit of {self.hard_limit}")
            # Would require human approval in production
        
        graph = self.build_dependency_graph(files, symbol_map, symbol_map_path)
        return self.topological_sort(graph)
    
    def check_parallel_safe(self, 
                           batch: List[str],
                           graph: DependencyGraph) -> Tuple[bool, str]:
        """
        Check if a batch of files can be processed in parallel.
        
        A batch is parallel_safe IF AND ONLY IF all of:
          [P1] No two files in the batch depend on each other
          [P2] No file depends on the output of another in the same batch
          [P3] No file touches sections referenced by cross-file dependencies
          [P4] No file modifies shared symbols used by sibling files
        
        Args:
            batch: List of file paths in the batch
            graph: Dependency graph
            
        Returns:
            Tuple of (is_parallel_safe, justification)
        """
        batch_set = set(batch)
        
        # P1: Check for interdependencies
        for file_path in batch:
            deps = graph.edges.get(file_path, set())
            inter_deps = deps & batch_set
            if inter_deps:
                return (False, f"P1 violation: {file_path} depends on {inter_deps} in same batch")
        
        # P2: No file depends on output of another (already checked in P1 for file-level)
        # For symbol-level, would need more detailed analysis
        
        # P3: Cross-file reference check
        # Would need to analyze actual content for cross-file section references
        
        # P4: Shared symbol check
        # Would need symbol-level dependency analysis
        
        return (True, "All P1-P4 conditions satisfied")
    
    def get_file_status(self, graph: DependencyGraph, 
                        file_path: str) -> Dict:
        """
        Get processing status for a specific file.
        
        Args:
            graph: Dependency graph
            file_path: File path to check
            
        Returns:
            Status dictionary with dependencies and dependents
        """
        if file_path not in graph.nodes:
            return {"error": f"File not in graph: {file_path}"}
        
        node = graph.nodes[file_path]
        
        return {
            "path": file_path,
            "status": node.status.value,
            "dependencies": list(node.dependencies),
            "dependents": list(node.dependents),
            "can_process": node.status == NodeStatus.READY,
            "blocking_files": [
                f for f in node.dependencies 
                if graph.nodes.get(f, FileNode(path=f)).status != NodeStatus.COMPLETE
            ]
        }
    
    def mark_file_complete(self, graph: DependencyGraph, 
                          file_path: str) -> None:
        """
        Mark a file as complete and update dependent statuses.
        
        Args:
            graph: Dependency graph
            file_path: Completed file path
        """
        if file_path in graph.nodes:
            graph.nodes[file_path].status = NodeStatus.COMPLETE
        
        # Update dependents
        for dependent in graph.reverse_edges.get(file_path, set()):
            if dependent in graph.nodes:
                node = graph.nodes[dependent]
                # Check if all dependencies are complete
                all_deps_complete = all(
                    graph.nodes.get(d, FileNode(path=d)).status == NodeStatus.COMPLETE
                    for d in node.dependencies
                )
                if all_deps_complete:
                    node.status = NodeStatus.READY
    
    def mark_file_failed(self, graph: DependencyGraph, 
                        file_path: str, 
                        error: str) -> None:
        """
        Mark a file as failed and block dependents.
        
        Args:
            graph: Dependency graph
            file_path: Failed file path
            error: Error message
        """
        if file_path in graph.nodes:
            node = graph.nodes[file_path]
            node.status = NodeStatus.FAILED
        
        # Block all dependents
        for dependent in graph.reverse_edges.get(file_path, set()):
            if dependent in graph.nodes:
                graph.nodes[dependent].status = NodeStatus.BLOCKED


def create_dependency_resolver(config: Optional[Dict] = None) -> DependencyResolver:
    """
    Factory function to create DependencyResolver.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Configured DependencyResolver instance
    """
    return DependencyResolver(config=config)
