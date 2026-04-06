"""
TITAN FUSE Protocol - Navigation Module

Implements Step 0.3: Build Navigation Map from PROTOCOL.md.

Features:
- Semantic boundary detection
- Chunk assignment with IDs
- Cross-reference graph building
"""

from .nav_map_builder import (
    NavMapBuilder,
    NavMap,
    Chunk,
    ChunkStatus
)

__all__ = [
    'NavMapBuilder',
    'NavMap',
    'Chunk',
    'ChunkStatus'
]
