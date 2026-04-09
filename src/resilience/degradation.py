"""
TITAN FUSE Protocol - Graceful Degradation Manager

ITEM_014: DegradationManager for TITAN Protocol v1.2.0

Defines fallback behaviors when components fail.
Implements tiered degradation with automatic recovery detection.

Key Features:
- Three degradation levels: full, reduced, minimal
- Feature tracking and automatic recovery
- Profile detection weight redistribution
- EventBus integration for degradation events
- Metrics collection

Integration Points:
- UniversalRouter: Uses degradation manager for fallback handling
- ProfileRouter: Adjusts detection weights when session memory disabled
- RetryExecutorFacade: Triggers degradation on repeated failures
- EventBus: Emits DEGRADATION_LEVEL_CHANGED, FEATURE_DISABLED events

Author: TITAN FUSE Team
Version: 1.2.0
"""

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List, Callable, Set
import logging

from src.events.event_bus import Event, EventSeverity, EventBus
from src.utils.timezone import now_utc_iso


class DegradationLevel(Enum):
    """
    Degradation level enumeration.
    
    Levels:
    - FULL: All features available, normal operation
    - REDUCED: Non-critical features disabled
    - MINIMAL: Only direct prompt available
    """
    FULL = "full"
    REDUCED = "reduced"
    MINIMAL = "minimal"


@dataclass
class FeatureState:
    """
    State of a feature.
    
    Attributes:
        name: Feature name
        enabled: Whether feature is enabled
        disabled_at: When feature was disabled (if applicable)
        disabled_reason: Reason for disabling
        recovery_attempts: Number of recovery attempts
        last_recovery_attempt: Last recovery attempt timestamp
    """
    name: str
    enabled: bool = True
    disabled_at: Optional[str] = None
    disabled_reason: Optional[str] = None
    recovery_attempts: int = 0
    last_recovery_attempt: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "disabled_at": self.disabled_at,
            "disabled_reason": self.disabled_reason,
            "recovery_attempts": self.recovery_attempts,
            "last_recovery_attempt": self.last_recovery_attempt,
        }


@dataclass
class DegradationConfig:
    """
    Configuration for DegradationManager.
    
    Attributes:
        recovery_check_interval_seconds: Interval between recovery checks
        max_recovery_attempts: Maximum recovery attempts per feature
        recovery_success_threshold: Successes needed to re-enable feature
        auto_recovery_enabled: Enable automatic recovery detection
        enable_events: Enable event emission
        enable_metrics: Enable metrics collection
    """
    recovery_check_interval_seconds: int = 30
    max_recovery_attempts: int = 5
    recovery_success_threshold: int = 3
    auto_recovery_enabled: bool = True
    enable_events: bool = True
    enable_metrics: bool = True
    
    # Thresholds for automatic degradation
    failure_rate_threshold: float = 0.5  # 50% failure rate triggers degradation
    latency_threshold_ms: int = 5000  # High latency triggers degradation
    error_count_threshold: int = 10  # Consecutive errors trigger degradation
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "recovery_check_interval_seconds": self.recovery_check_interval_seconds,
            "max_recovery_attempts": self.max_recovery_attempts,
            "recovery_success_threshold": self.recovery_success_threshold,
            "auto_recovery_enabled": self.auto_recovery_enabled,
            "enable_events": self.enable_events,
            "enable_metrics": self.enable_metrics,
            "failure_rate_threshold": self.failure_rate_threshold,
            "latency_threshold_ms": self.latency_threshold_ms,
            "error_count_threshold": self.error_count_threshold,
        }


@dataclass
class DegradationStats:
    """
    Statistics for degradation manager.
    
    Attributes:
        current_level: Current degradation level
        level_changes: Number of level changes
        features_disabled: Total features disabled
        features_recovered: Total features recovered
        recovery_attempts: Total recovery attempts
        last_level_change: Timestamp of last level change
    """
    current_level: DegradationLevel = DegradationLevel.FULL
    level_changes: int = 0
    features_disabled: int = 0
    features_recovered: int = 0
    recovery_attempts: int = 0
    last_level_change: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "current_level": self.current_level.value,
            "level_changes": self.level_changes,
            "features_disabled": self.features_disabled,
            "features_recovered": self.features_recovered,
            "recovery_attempts": self.recovery_attempts,
            "last_level_change": self.last_level_change,
        }


# Default feature sets for each degradation level
DEFAULT_FEATURE_SETS = {
    DegradationLevel.FULL: {
        "skill_graph": True,
        "self_awareness": True,
        "session_memory": True,
        "profile_detection": True,
        "intent_enrichment": True,
        "all_tools": True,
        "advanced_tools": True,
        "caching": True,
    },
    DegradationLevel.REDUCED: {
        "skill_graph": True,
        "self_awareness": False,
        "session_memory": False,
        "profile_detection": True,
        "intent_enrichment": True,
        "all_tools": True,
        "advanced_tools": False,
        "caching": True,
    },
    DegradationLevel.MINIMAL: {
        "skill_graph": False,
        "self_awareness": False,
        "session_memory": False,
        "profile_detection": False,
        "intent_enrichment": False,
        "all_tools": False,
        "advanced_tools": False,
        "caching": False,
        "direct_prompt": True,
    },
}

# Profile detection weight redistribution for degraded states
PROFILE_DETECTION_WEIGHTS = {
    DegradationLevel.FULL: {
        "lexical_analysis": 0.4,
        "pattern_matching": 0.3,
        "history_analysis": 0.2,
        "explicit_signal": 0.1,
    },
    DegradationLevel.REDUCED: {
        # Session memory disabled, redistribute history weight
        "lexical_analysis": 0.5,
        "pattern_matching": 0.375,
        "history_analysis": 0.0,  # Disabled
        "explicit_signal": 0.125,
    },
    DegradationLevel.MINIMAL: {
        # Only basic detection available
        "lexical_analysis": 0.6,
        "pattern_matching": 0.4,
        "history_analysis": 0.0,
        "explicit_signal": 0.0,
    },
}


class DegradationManager:
    """
    Manager for graceful degradation.
    
    Implements tiered degradation with automatic recovery detection.
    Tracks feature states and provides fallback behaviors.
    
    Usage:
        manager = DegradationManager(event_bus=event_bus)
        
        # Check feature availability
        if manager.is_feature_enabled("session_memory"):
            # Use session memory
            pass
        
        # Disable feature
        manager.disable_feature("session_memory", reason="Service unavailable")
        
        # Check level
        if manager.get_level() == DegradationLevel.MINIMAL:
            # Use direct prompt fallback
            pass
        
        # Get adjusted weights for profile detection
        weights = manager.get_profile_detection_weights()
        
        # Attempt recovery
        manager.attempt_recovery("session_memory")
    
    Attributes:
        config: DegradationConfig instance
        event_bus: Optional EventBus for degradation events
    """
    
    def __init__(
        self,
        config: Optional[DegradationConfig] = None,
        event_bus: Optional[EventBus] = None,
        feature_sets: Optional[Dict[DegradationLevel, Dict[str, bool]]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize DegradationManager.
        
        Args:
            config: Configuration options
            event_bus: EventBus for emitting degradation events
            feature_sets: Custom feature sets per degradation level
            logger: Optional logger instance
        """
        self._config = config or DegradationConfig()
        self._event_bus = event_bus
        self._feature_sets = feature_sets or DEFAULT_FEATURE_SETS
        self._logger = logger or logging.getLogger(__name__)
        
        # State management
        self._level = DegradationLevel.FULL
        self._features: Dict[str, FeatureState] = {}
        self._feature_errors: Dict[str, int] = {}
        self._feature_latencies: Dict[str, List[int]] = {}
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Statistics
        self._stats = DegradationStats()
        
        # Recovery tracking
        self._recovery_successes: Dict[str, int] = {}
        self._last_recovery_check: Optional[float] = None
        
        # Initialize features from FULL level
        self._initialize_features()
    
    def _initialize_features(self) -> None:
        """Initialize features from the FULL level feature set."""
        with self._lock:
            for feature_name in self._feature_sets.get(DegradationLevel.FULL, {}):
                self._features[feature_name] = FeatureState(name=feature_name)
    
    def get_level(self) -> DegradationLevel:
        """Get current degradation level."""
        return self._level
    
    def set_level(self, level: DegradationLevel, reason: str = "") -> None:
        """
        Set degradation level.
        
        Args:
            level: The degradation level to set
            reason: Reason for changing level
        """
        with self._lock:
            old_level = self._level
            
            if old_level == level:
                return
            
            self._level = level
            self._stats.level_changes += 1
            self._stats.last_level_change = now_utc_iso()
            self._stats.current_level = level
            
            # Update feature states based on level
            self._apply_level_features(level)
            
            # Emit event
            self._emit_level_change(old_level, level, reason)
            
            self._logger.warning(
                f"Degradation level changed: {old_level.value} -> {level.value}. "
                f"Reason: {reason or 'Not specified'}"
            )
    
    def _apply_level_features(self, level: DegradationLevel) -> None:
        """Apply feature states for the given degradation level."""
        feature_set = self._feature_sets.get(level, {})
        
        for feature_name, enabled in feature_set.items():
            if feature_name not in self._features:
                self._features[feature_name] = FeatureState(name=feature_name)
            
            feature = self._features[feature_name]
            
            if enabled and not feature.enabled:
                # Enable feature
                feature.enabled = True
                feature.disabled_at = None
                feature.disabled_reason = None
                self._stats.features_recovered += 1
                
            elif not enabled and feature.enabled:
                # Disable feature
                feature.enabled = False
                feature.disabled_at = now_utc_iso()
                feature.disabled_reason = f"Degradation level: {level.value}"
                self._stats.features_disabled += 1
    
    def _emit_level_change(
        self,
        old_level: DegradationLevel,
        new_level: DegradationLevel,
        reason: str,
    ) -> None:
        """Emit degradation level change event."""
        if not self._config.enable_events or not self._event_bus:
            return
        
        event = Event(
            event_type="DEGRADATION_LEVEL_CHANGED",
            data={
                "old_level": old_level.value,
                "new_level": new_level.value,
                "reason": reason,
                "timestamp": now_utc_iso(),
                "enabled_features": self.get_enabled_features(),
                "disabled_features": self.get_disabled_features(),
            },
            severity=EventSeverity.WARN if new_level != DegradationLevel.FULL else EventSeverity.INFO,
            source="DegradationManager",
        )
        self._event_bus.emit(event)
    
    def is_feature_enabled(self, feature_name: str) -> bool:
        """
        Check if a feature is enabled.
        
        Args:
            feature_name: Name of the feature
            
        Returns:
            True if feature is enabled, False otherwise
        """
        with self._lock:
            feature = self._features.get(feature_name)
            return feature.enabled if feature else False
    
    def enable_feature(self, feature_name: str) -> bool:
        """
        Enable a feature.
        
        Args:
            feature_name: Name of the feature
            
        Returns:
            True if feature was enabled, False if not found
        """
        with self._lock:
            if feature_name not in self._features:
                return False
            
            feature = self._features[feature_name]
            
            if feature.enabled:
                return True
            
            feature.enabled = True
            feature.disabled_at = None
            feature.disabled_reason = None
            self._stats.features_recovered += 1
            
            # Reset error tracking
            self._feature_errors[feature_name] = 0
            self._recovery_successes[feature_name] = 0
            
            self._emit_feature_change(feature_name, True)
            
            return True
    
    def disable_feature(
        self,
        feature_name: str,
        reason: str = "",
    ) -> bool:
        """
        Disable a feature.
        
        Args:
            feature_name: Name of the feature
            reason: Reason for disabling
            
        Returns:
            True if feature was disabled, False if not found or already disabled
        """
        with self._lock:
            if feature_name not in self._features:
                return False
            
            feature = self._features[feature_name]
            
            if not feature.enabled:
                return True
            
            feature.enabled = False
            feature.disabled_at = now_utc_iso()
            feature.disabled_reason = reason
            self._stats.features_disabled += 1
            
            self._emit_feature_change(feature_name, False, reason)
            
            # Check if we need to degrade
            self._check_degradation()
            
            return True
    
    def _emit_feature_change(
        self,
        feature_name: str,
        enabled: bool,
        reason: str = "",
    ) -> None:
        """Emit feature state change event."""
        if not self._config.enable_events or not self._event_bus:
            return
        
        event = Event(
            event_type="FEATURE_ENABLED" if enabled else "FEATURE_DISABLED",
            data={
                "feature_name": feature_name,
                "enabled": enabled,
                "reason": reason,
                "timestamp": now_utc_iso(),
                "current_level": self._level.value,
            },
            severity=EventSeverity.INFO,
            source="DegradationManager",
        )
        self._event_bus.emit(event)
    
    def _check_degradation(self) -> None:
        """Check if degradation level needs to change."""
        disabled_critical = [
            f for f in ["skill_graph", "profile_detection", "intent_enrichment"]
            if not self.is_feature_enabled(f)
        ]
        disabled_non_critical = [
            f for f in ["session_memory", "self_awareness", "advanced_tools"]
            if not self.is_feature_enabled(f)
        ]
        
        # Determine appropriate level
        if len(disabled_critical) >= 2:
            # Multiple critical features disabled
            self.set_level(DegradationLevel.MINIMAL, "Critical features disabled")
        elif len(disabled_critical) >= 1 or len(disabled_non_critical) >= 2:
            # Some features disabled
            self.set_level(DegradationLevel.REDUCED, "Features disabled")
        else:
            # All features available
            if self._level != DegradationLevel.FULL:
                self.set_level(DegradationLevel.FULL, "All features recovered")
    
    def get_enabled_features(self) -> List[str]:
        """Get list of enabled features."""
        with self._lock:
            return [name for name, state in self._features.items() if state.enabled]
    
    def get_disabled_features(self) -> List[str]:
        """Get list of disabled features."""
        with self._lock:
            return [name for name, state in self._features.items() if not state.enabled]
    
    def get_feature_state(self, feature_name: str) -> Optional[FeatureState]:
        """Get state of a specific feature."""
        with self._lock:
            return self._features.get(feature_name)
    
    def record_error(self, feature_name: str) -> None:
        """
        Record an error for a feature.
        
        Used for automatic degradation detection.
        
        Args:
            feature_name: Name of the feature that had an error
        """
        with self._lock:
            self._feature_errors[feature_name] = self._feature_errors.get(feature_name, 0) + 1
            
            # Check if error threshold exceeded
            if self._feature_errors[feature_name] >= self._config.error_count_threshold:
                self.disable_feature(
                    feature_name,
                    reason=f"Error threshold exceeded ({self._feature_errors[feature_name]} errors)"
                )
    
    def record_latency(self, feature_name: str, latency_ms: int) -> None:
        """
        Record latency for a feature.
        
        Used for automatic degradation detection.
        
        Args:
            feature_name: Name of the feature
            latency_ms: Latency in milliseconds
        """
        with self._lock:
            if feature_name not in self._feature_latencies:
                self._feature_latencies[feature_name] = []
            
            self._feature_latencies[feature_name].append(latency_ms)
            
            # Keep only last 100 measurements
            self._feature_latencies[feature_name] = self._feature_latencies[feature_name][-100:]
            
            # Check latency threshold
            if latency_ms >= self._config.latency_threshold_ms:
                avg_latency = sum(self._feature_latencies[feature_name]) / len(self._feature_latencies[feature_name])
                if avg_latency >= self._config.latency_threshold_ms * 0.8:
                    self._logger.warning(
                        f"Feature '{feature_name}' has high average latency: {avg_latency:.0f}ms"
                    )
    
    def record_success(self, feature_name: str) -> None:
        """
        Record a successful operation for a feature.
        
        Used for recovery detection.
        
        Args:
            feature_name: Name of the feature
        """
        with self._lock:
            # Reset error count
            self._feature_errors[feature_name] = 0
            
            # Track recovery successes
            if feature_name in self._recovery_successes:
                self._recovery_successes[feature_name] += 1
                
                # Check if we can re-enable the feature
                feature = self._features.get(feature_name)
                if feature and not feature.enabled:
                    if self._recovery_successes[feature_name] >= self._config.recovery_success_threshold:
                        self.enable_feature(feature_name)
                        self._logger.info(
                            f"Feature '{feature_name}' re-enabled after recovery"
                        )
    
    def attempt_recovery(self, feature_name: str) -> bool:
        """
        Attempt to recover a disabled feature.
        
        Args:
            feature_name: Name of the feature to recover
            
        Returns:
            True if recovery attempt was made, False if feature not disabled
        """
        with self._lock:
            feature = self._features.get(feature_name)
            
            if not feature or feature.enabled:
                return False
            
            if not self._config.auto_recovery_enabled:
                return False
            
            if feature.recovery_attempts >= self._config.max_recovery_attempts:
                self._logger.warning(
                    f"Feature '{feature_name}' exceeded max recovery attempts"
                )
                return False
            
            feature.recovery_attempts += 1
            feature.last_recovery_attempt = now_utc_iso()
            self._stats.recovery_attempts += 1
            self._recovery_successes[feature_name] = 0
            
            self._logger.info(
                f"Attempting recovery for feature '{feature_name}' "
                f"(attempt {feature.recovery_attempts}/{self._config.max_recovery_attempts})"
            )
            
            return True
    
    def get_profile_detection_weights(self) -> Dict[str, float]:
        """
        Get profile detection weights adjusted for current degradation level.
        
        Returns:
            Dictionary of detection method weights
        """
        return PROFILE_DETECTION_WEIGHTS.get(self._level, PROFILE_DETECTION_WEIGHTS[DegradationLevel.FULL])
    
    def get_fallback_chain(self) -> List[str]:
        """
        Get fallback chain for current degradation level.
        
        Returns:
            List of fallback strategies in priority order
        """
        if self._level == DegradationLevel.FULL:
            return [
                "skill_graph_composition",
                "intent_router_only",
                "direct_prompt",
            ]
        elif self._level == DegradationLevel.REDUCED:
            return [
                "skill_graph_composition",
                "intent_router_only",
                "direct_prompt",
            ]
        else:  # MINIMAL
            return ["direct_prompt"]
    
    def get_stats(self) -> DegradationStats:
        """Get degradation manager statistics."""
        with self._lock:
            return self._stats
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        with self._lock:
            self._stats = DegradationStats(current_level=self._level)
    
    def set_event_bus(self, event_bus: EventBus) -> None:
        """Set EventBus for emitting events."""
        self._event_bus = event_bus
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        with self._lock:
            return {
                "level": self._level.value,
                "config": self._config.to_dict(),
                "stats": self._stats.to_dict(),
                "features": {name: state.to_dict() for name, state in self._features.items()},
                "enabled_features": self.get_enabled_features(),
                "disabled_features": self.get_disabled_features(),
                "profile_detection_weights": self.get_profile_detection_weights(),
                "fallback_chain": self.get_fallback_chain(),
            }


# Global instance
_global_manager: Optional[DegradationManager] = None


def get_degradation_manager(
    config: Optional[Dict[str, Any]] = None,
    event_bus: Optional[EventBus] = None,
) -> DegradationManager:
    """
    Get global DegradationManager instance.
    
    Creates instance on first call, returns existing on subsequent calls.
    
    Args:
        config: Configuration dictionary (only used on first call)
        event_bus: EventBus instance (only used on first call)
        
    Returns:
        Global DegradationManager instance
    """
    global _global_manager
    if _global_manager is None:
        degradation_config = None
        if config:
            degradation_config = DegradationConfig(**config)
        _global_manager = DegradationManager(
            config=degradation_config,
            event_bus=event_bus,
        )
    return _global_manager


def reset_degradation_manager() -> None:
    """Reset global DegradationManager instance."""
    global _global_manager
    _global_manager = None
