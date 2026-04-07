"""
Feedback Module for TITAN Protocol.

ITEM-FEEDBACK-01: FeedbackLoop Module Implementation

This module provides the complete feedback collection, aggregation,
and threshold adjustment system for the TITAN Protocol skill catalog.

Key Components:
    Feedback Collection:
    - FeedbackType: Enum for feedback types (THUMBS_UP, THUMBS_DOWN, RATING, COMMENT)
    - FeedbackEvent: Individual feedback event dataclass
    
    Aggregation:
    - AggregatedFeedback: Aggregated statistics over time windows
    
    Threshold Management:
    - ThresholdAdjustment: Record of threshold changes
    - ApplyResult: Result of applying an adjustment
    - ThresholdAdapter: Adaptive threshold calculator with confidence weighting
    - DryRunResult: Simulation result for safe adjustment testing
    
    Version Control:
    - CatalogVersion: Immutable catalog snapshot
    - CatalogDiff: Difference between versions
    - CatalogVersionManager: Version control for catalog
    
    Main Orchestrator:
    - FeedbackLoop: Main feedback loop orchestrator

Usage:
    >>> from src.feedback import FeedbackLoop, FeedbackEvent, FeedbackType
    >>> from src.events import EventBus
    >>> from src.storage import LocalStorageBackend
    >>> 
    >>> # Initialize components
    >>> event_bus = EventBus()
    >>> storage = LocalStorageBackend(base_path="./.titan/storage")
    >>> feedback_loop = FeedbackLoop(config={}, event_bus=event_bus, storage_backend=storage)
    >>> 
    >>> # Receive feedback
    >>> event = FeedbackEvent(
    ...     session_id="sess-123",
    ...     skill_id="skill-web-search",
    ...     feedback_type=FeedbackType.THUMBS_UP,
    ...     context={"query": "example"}
    ... )
    >>> feedback_id = feedback_loop.receive_feedback(event)
    >>> 
    >>> # Aggregate feedback
    >>> from datetime import timedelta
    >>> aggregated = feedback_loop.aggregate_feedback("skill-web-search", timedelta(days=7))
    >>> 
    >>> # Calculate and apply threshold adjustment
    >>> adjustment = feedback_loop.calculate_threshold_adjustment("skill-web-search")
    >>> result = feedback_loop.apply_adjustment(adjustment)

Algorithm:
    The threshold adjustment uses a gradient-based learning algorithm:
    
        new_threshold = current_threshold + alpha * (positive_rate - target_rate) * confidence_factor
    
    Where:
    - alpha: learning rate (default 0.1)
    - positive_rate: thumbs_up / (thumbs_up + thumbs_down)
    - target_rate: target success rate (default 0.8)
    - confidence_factor: sqrt(sample_size / min_samples)

Integration:
    - EventBus: Emits FEEDBACK_RECEIVED events
    - StorageBackend: Persists feedback and catalog versions
    - Versions stored in .titan/skills/versions/

Author: TITAN Protocol Team
Version: 1.0.0
"""

# Core feedback types and events
from src.feedback.feedback_loop import (
    FeedbackType,
    FeedbackEvent,
    AggregatedFeedback,
    ThresholdAdjustment,
    ApplyResult,
    FeedbackLoop
)

# Threshold adapter
from src.feedback.threshold_adapter import (
    ValidationResult,
    DryRunResult,
    ThresholdAdapter
)

# Catalog versioning
from src.feedback.catalog_versioning import (
    CatalogVersion,
    CatalogDiff,
    CatalogVersionManager
)


__all__ = [
    # Feedback types and events
    'FeedbackType',
    'FeedbackEvent',
    'AggregatedFeedback',
    
    # Threshold management
    'ThresholdAdjustment',
    'ApplyResult',
    'ThresholdAdapter',
    'DryRunResult',
    'ValidationResult',
    
    # Version control
    'CatalogVersion',
    'CatalogDiff',
    'CatalogVersionManager',
    
    # Main orchestrator
    'FeedbackLoop',
]


# Module metadata
__version__ = '1.0.0'
__author__ = 'TITAN Protocol Team'
