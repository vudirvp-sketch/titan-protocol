"""
Context module for TITAN Protocol.

ITEM-OBS-04: Symbol Map OOM Protection
ITEM-FEAT-91: Auto-split on Chunk Limit
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
]
