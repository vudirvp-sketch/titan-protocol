"""
Context module for TITAN Protocol.

ITEM-OBS-04: Symbol Map OOM Protection
ITEM-FEAT-91: Auto-split on Chunk Limit
ITEM-FEAT-74: Chunk Dependency Graph for Recovery
ITEM-CTX-001: ProfileRouter Enhancement
ITEM-SAE-003: Context Graph Schema Definition
"""

from .symbol_map import (
    BoundedSymbolMap,
    SymbolEntry,
    EvictionPolicy,
    get_symbol_map,
    reset_symbol_map
)
from .chunk_optimizer import ChunkOptimizer
from .auto_split import (
    AutoSplitter,
    SplitStats,
    AutoSplitConfig,
    BoundaryType,
    create_auto_splitter
)
from .chunk_dependency_graph import (
    ChunkDependencyGraph,
    ChunkStatus,
    ChunkNode,
    DependencyGraphStats,
    create_dependency_graph
)
from .profile_router import (
    ProfileType,
    ProfileConfig,
    ProfileRouter,
    DEFAULT_PROFILES,
    create_profile_router
)
# ITEM-SAE-003: Context Graph
from .context_graph import (
    ContextGraph,
    ContextNode,
    ContextEdge,
    NodeType,
    EdgeRelation,
    TrustTier,
    VersionVector,
    ContextGraphMetadata,
)
# ITEM-SAE-004: Trust Score Engine
from .trust_engine import (
    TrustEngine,
    TrustEngineConfig,
    TrustFactor,
    TrustFactorWeights,
    TrustScoreRecord,
    TrustEngineStats,
    get_trust_engine,
    reset_trust_engine,
)

__all__ = [
    "BoundedSymbolMap",
    "SymbolEntry",
    "EvictionPolicy",
    "get_symbol_map",
    "reset_symbol_map",
    "ChunkOptimizer",
    "AutoSplitter",
    "SplitStats",
    "AutoSplitConfig",
    "BoundaryType",
    "create_auto_splitter",
    "ChunkDependencyGraph",
    "ChunkStatus",
    "ChunkNode",
    "DependencyGraphStats",
    "create_dependency_graph",
    # ITEM-CTX-001: ProfileRouter
    "ProfileType",
    "ProfileConfig",
    "ProfileRouter",
    "DEFAULT_PROFILES",
    "create_profile_router",
    # ITEM-SAE-003: Context Graph
    "ContextGraph",
    "ContextNode",
    "ContextEdge",
    "NodeType",
    "EdgeRelation",
    "TrustTier",
    "VersionVector",
    "ContextGraphMetadata",
    # ITEM-SAE-004: Trust Score Engine
    "TrustEngine",
    "TrustEngineConfig",
    "TrustFactor",
    "TrustFactorWeights",
    "TrustScoreRecord",
    "TrustEngineStats",
    "get_trust_engine",
    "reset_trust_engine",
]
