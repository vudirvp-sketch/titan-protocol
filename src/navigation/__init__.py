"""
TITAN FUSE Protocol - Navigation Module

Implements Step 0.3: Build Navigation Map from PROTOCOL.md.

Features:
- Semantic boundary detection
- Chunk assignment with IDs
- Cross-reference graph building

ITEM-BOOT-001: Dependency Graph Schema
- DependencyGraphBuilder for code dependency analysis
- Cycle detection and topological ordering
- Multi-language support (Python, JavaScript)
"""

from .nav_map_builder import (
    # Navigation map classes
    NavMapBuilder,
    NavMap,
    Chunk,
    ChunkStatus,
    # ITEM-BOOT-001: Dependency Graph classes
    DependencyGraphBuilder,
    DependencyGraph,
    DependencyNode,
    DependencyEdge,
    DependencyCycle,
    NodeType,
    RelationType,
    # Factory functions
    create_nav_map_builder,
    create_dependency_graph_builder
)

__all__ = [
    # Navigation map exports
    'NavMapBuilder',
    'NavMap',
    'Chunk',
    'ChunkStatus',
    # ITEM-BOOT-001: Dependency Graph exports
    'DependencyGraphBuilder',
    'DependencyGraph',
    'DependencyNode',
    'DependencyEdge',
    'DependencyCycle',
    'NodeType',
    'RelationType',
    # Factory functions
    'create_nav_map_builder',
    'create_dependency_graph_builder'
]
