"""
TITAN FUSE Protocol - Multi-File Coordination Module

Implements PHASE -1D: Multi-File Input Handling from PROTOCOL.ext.md.

STATUS: Full implementation of dependency graph and topological sort.

Features:
- Dependency graph construction from SYMBOL_MAP.json
- Topological sort for processing order
- Cross-file reference detection
- Write-lock management for shared state

ITEM-GAP-002: ABI_LOCKED_PROTOCOL
- Cluster detection and classification
- Atomic update operations with rollback
- ABI compatibility management
"""

from .dependency_resolver import (
    DependencyResolver,
    DependencyGraph,
    FileNode,
    ProcessingOrder
)

from .abi_locked import (
    AbiLockedProtocol,
    ClusterClassification,
    Dependency,
    Cluster,
    UpdateResult,
    UpdateOperation,
    UpdateStatus,
    AbiUpdateFailed,
    ClusterLockedError,
    create_abi_locked_protocol
)

__all__ = [
    'DependencyResolver',
    'DependencyGraph',
    'FileNode',
    'ProcessingOrder',
    # ITEM-GAP-002: ABI_LOCKED_PROTOCOL
    'AbiLockedProtocol',
    'ClusterClassification',
    'Dependency',
    'Cluster',
    'UpdateResult',
    'UpdateOperation',
    'UpdateStatus',
    'AbiUpdateFailed',
    'ClusterLockedError',
    'create_abi_locked_protocol'
]
