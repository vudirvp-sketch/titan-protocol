"""
TITAN FUSE Protocol - Multi-File Coordination Module

Implements PHASE -1D: Multi-File Input Handling from PROTOCOL.ext.md.

STATUS: Full implementation of dependency graph and topological sort.

Features:
- Dependency graph construction from SYMBOL_MAP.json
- Topological sort for processing order
- Cross-file reference detection
- Write-lock management for shared state
"""

from .dependency_resolver import (
    DependencyResolver,
    DependencyGraph,
    FileNode,
    ProcessingOrder
)

__all__ = [
    'DependencyResolver',
    'DependencyGraph',
    'FileNode',
    'ProcessingOrder'
]
