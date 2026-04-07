# TITAN Protocol - Scoring Module
"""
Adaptive Weight Profiles Engine for TITAN FUSE Protocol.

ITEM-CAT-01: Four-axis scoring with domain-specific weight profiles.
- TF (Technical Fidelity)
- RS (Reliability Score)
- DS (Domain Specificity)
- AC (Actionability Coefficient)

Provides deterministic scoring formula and conflict resolution thresholds.
"""

from .adaptive_weights import (
    WeightProfile,
    AdaptiveWeightEngine,
    WeightedScore,
    ConflictResolution,
    Decision,
    DEFAULT_WEIGHT_PROFILES,
    create_weight_engine,
)

__all__ = [
    'WeightProfile',
    'AdaptiveWeightEngine',
    'WeightedScore',
    'ConflictResolution',
    'Decision',
    'DEFAULT_WEIGHT_PROFILES',
    'create_weight_engine',
]
