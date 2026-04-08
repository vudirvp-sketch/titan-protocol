"""
Context module for TITAN Protocol.

ITEM-OBS-04: Symbol Map OOM Protection
ITEM-FEAT-91: Auto-split on Chunk Limit
ITEM-FEAT-74: Chunk Dependency Graph for Recovery
ITEM-CTX-001: ProfileRouter Enhancement
ITEM-SAE-003: Context Graph Schema Definition
ITEM-SAE-004: Trust Score Engine
ITEM-SAE-005: Version Vector System
ITEM-SAE-006: AST Checksum System
ITEM-SAE-007: Semantic Drift Detector
ITEM-SAE-008: EXEC Stage Pruning
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
# ITEM-SAE-005: Version Vector System
from .version_vectors import (
    VectorClockManager,
    StaleDetector,
    StaleNode,
    Conflict,
    Resolution,
    VectorOrder,
    get_vector_clock_manager,
    get_stale_detector,
    reset_version_vector_system,
)
# ITEM-SAE-006: AST Checksum System
from .semantic_checksum import (
    SemanticChecksum,
    SemanticChecksumResult,
    ChecksumDiff,
    Language,
    get_semantic_checksum,
    compute_semantic_hash,
)
from .checksum_cache import (
    ChecksumCache,
    ChecksumEntry,
    CacheStats,
    get_checksum_cache,
)
# ITEM-SAE-007: Semantic Drift Detector
from .drift_detector import (
    DriftDetector,
    DriftLevel,
    DriftResult,
    DriftReport,
    Change,
    get_drift_detector,
)
from .change_tracker import (
    ChangeTracker,
    FileChange,
    ChangeType,
    ImpactScore,
    get_change_tracker,
)
# ITEM-SAE-008: EXEC Stage Pruning
from .summarization import (
    RecursiveSummarizer,
    ExecutionStage,
    StageSummary,
    StageType,
    StageStatus,
    CompressedSummary,
    get_summarizer,
)
from .pruning_policy import (
    PruningPolicy,
    PruningPolicyConfig,
    PruningStrategy,
    PruningResult,
    PruningCandidate,
    get_pruning_policy,
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
    # ITEM-SAE-005: Version Vector System
    "VectorClockManager",
    "StaleDetector",
    "StaleNode",
    "Conflict",
    "Resolution",
    "VectorOrder",
    "get_vector_clock_manager",
    "get_stale_detector",
    "reset_version_vector_system",
    # ITEM-SAE-006: AST Checksum System
    "SemanticChecksum",
    "SemanticChecksumResult",
    "ChecksumDiff",
    "Language",
    "get_semantic_checksum",
    "compute_semantic_hash",
    "ChecksumCache",
    "ChecksumEntry",
    "CacheStats",
    "get_checksum_cache",
    # ITEM-SAE-007: Semantic Drift Detector
    "DriftDetector",
    "DriftLevel",
    "DriftResult",
    "DriftReport",
    "Change",
    "get_drift_detector",
    "ChangeTracker",
    "FileChange",
    "ChangeType",
    "ImpactScore",
    "get_change_tracker",
    # ITEM-SAE-008: EXEC Stage Pruning
    "RecursiveSummarizer",
    "ExecutionStage",
    "StageSummary",
    "StageType",
    "StageStatus",
    "CompressedSummary",
    "get_summarizer",
    "PruningPolicy",
    "PruningPolicyConfig",
    "PruningStrategy",
    "PruningResult",
    "PruningCandidate",
    "get_pruning_policy",
]
