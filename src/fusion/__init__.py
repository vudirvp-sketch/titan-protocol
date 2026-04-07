# TITAN Protocol - Fusion Module
"""
Type-Aware Fusion Engine for TITAN FUSE Protocol.

ITEM-CAT-03: Content fusion with type isolation and density prioritization.
- TYPE: FACT, OPINION, CODE, WARNING, STEP, EXAMPLE, METADATA
- DENSITY: HIGH, LOW (with unique_context/risk_caveat filtering)

Enforces strict type-matching merge rules and transparent discard logging.
"""

from .type_aware_merger import (
    ContentType,
    ContentDensity,
    ContentUnit,
    MergedResult,
    TypeAwareFusion,
    TypeMismatchError,
    DiscardLog,
    create_fusion_engine,
)

__all__ = [
    'ContentType',
    'ContentDensity',
    'ContentUnit',
    'MergedResult',
    'TypeAwareFusion',
    'TypeMismatchError',
    'DiscardLog',
    'create_fusion_engine',
]
