"""
Model Fallback Policy for TITAN FUSE Protocol.

ITEM-CONFLICT-F: Implements composite trigger policy for model fallback
with configurable thresholds for timeout, error rate, and token limits.

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging


@dataclass
class FallbackMetrics:
    """Metrics used for fallback decision."""
    timeout_ms: int = 0
    error_rate: float = 0.0
    token_limit_exceeded: bool = False
    last_error: Optional[str] = None
    last_error_time: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "timeout_ms": self.timeout_ms,
            "error_rate": self.error_rate,
            "token_limit_exceeded": self.token_limit_exceeded,
            "last_error": self.last_error,
            "last_error_time": self.last_error_time
        }


@dataclass
class ErrorWindow:
    """Sliding window for error rate calculation."""
    errors: deque = field(default_factory=lambda: deque(maxlen=100))
    total: int = 0
    
    def record_error(self, timestamp: datetime = None) -> None:
        """Record an error occurrence."""
        ts = timestamp or datetime.utcnow()
        self.errors.append(ts)
        self.total += 1
    
    def record_success(self) -> None:
        """Record a successful request."""
        self.total += 1
    
    def get_error_rate(self, window_seconds: int) -> float:
        """Calculate error rate within window."""
        if self.total == 0:
            return 0.0
        
        cutoff = datetime.utcnow() - timedelta(seconds=window_seconds)
        recent_errors = sum(1 for ts in self.errors if ts >= cutoff)
        
        # Simple approximation: errors / max(total_in_window, 1)
        return recent_errors / max(len(self.errors), 1)


@dataclass
class FallbackTrigger:
    """Configuration for a single fallback trigger."""
    name: str
    enabled: bool = True
    threshold: Any = None  # Varies by trigger type
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "threshold": self.threshold
        }


class FallbackPolicy:
    """
    Composite trigger policy for model fallback.
    
    ITEM-CONFLICT-F: Model fallback trigger conditions.
    
    Manages fallback decisions based on multiple configurable triggers:
    - Timeout: Request exceeds timeout threshold
    - Error rate: Error rate exceeds threshold within window
    - Token limit: Token budget exceeded
    
    The fallback chain is followed in order when any trigger activates.
    
    Usage:
        config = {
            "chain": ["gpt-4", "gpt-3.5-turbo", "claude-instant"],
            "triggers": {
                "timeout_ms": 30000,
                "error_rate_threshold": 0.1,
                "error_rate_window_seconds": 60,
                "token_limit_exceeded": True
            }
        }
        
        policy = FallbackPolicy(config)
        
        # Check if fallback needed
        if policy.should_fallback(metrics):
            next_model = policy.get_fallback_model("gpt-4")
    """
    
    DEFAULT_TRIGGERS = {
        "timeout_ms": 30000,
        "error_rate_threshold": 0.1,  # 10% error rate
        "error_rate_window_seconds": 60,
        "token_limit_exceeded": True
    }
    
    def __init__(self, config: Dict):
        """
        Initialize fallback policy.
        
        Args:
            config: Configuration with 'chain' and 'triggers' keys
        """
        self.config = config
        self._logger = logging.getLogger(__name__)
        
        # Parse fallback chain
        self.chain: List[str] = config.get("chain", [])
        self._current_index = 0
        
        # Parse trigger configuration
        triggers = config.get("triggers", {})
        self._timeout_ms = triggers.get("timeout_ms", self.DEFAULT_TRIGGERS["timeout_ms"])
        self._error_rate_threshold = triggers.get(
            "error_rate_threshold", 
            self.DEFAULT_TRIGGERS["error_rate_threshold"]
        )
        self._error_rate_window = triggers.get(
            "error_rate_window_seconds",
            self.DEFAULT_TRIGGERS["error_rate_window_seconds"]
        )
        self._token_limit_trigger = triggers.get(
            "token_limit_exceeded",
            self.DEFAULT_TRIGGERS["token_limit_exceeded"]
        )
        
        # Error tracking
        self._error_window = ErrorWindow()
        
        self._logger.info(
            f"FallbackPolicy initialized: chain={self.chain}, "
            f"timeout={self._timeout_ms}ms, "
            f"error_rate_threshold={self._error_rate_threshold}"
        )
    
    def should_fallback(self, metrics: FallbackMetrics) -> bool:
        """
        Determine if fallback should be triggered.
        
        Args:
            metrics: Current metrics to evaluate
            
        Returns:
            True if any trigger condition is met
        """
        # Check timeout trigger
        if self._check_timeout(metrics.timeout_ms):
            self._logger.info(
                f"Fallback triggered: timeout ({metrics.timeout_ms}ms > {self._timeout_ms}ms)"
            )
            return True
        
        # Check error rate trigger
        if self._check_error_rate(metrics.error_rate):
            self._logger.info(
                f"Fallback triggered: error rate "
                f"({metrics.error_rate:.2%} > {self._error_rate_threshold:.2%})"
            )
            return True
        
        # Check token limit trigger
        if self._check_token_limit(metrics.token_limit_exceeded):
            self._logger.info("Fallback triggered: token limit exceeded")
            return True
        
        return False
    
    def _check_timeout(self, timeout_ms: int) -> bool:
        """Check if timeout exceeds threshold."""
        return timeout_ms > self._timeout_ms
    
    def _check_error_rate(self, error_rate: float) -> bool:
        """Check if error rate exceeds threshold."""
        return error_rate > self._error_rate_threshold
    
    def _check_token_limit(self, exceeded: bool) -> bool:
        """Check if token limit exceeded trigger is enabled."""
        return exceeded and self._token_limit_trigger
    
    def get_fallback_model(self, current_model: str) -> Optional[str]:
        """
        Get the next model in the fallback chain.
        
        Args:
            current_model: Current model that triggered fallback
            
        Returns:
            Next model in chain, or None if chain exhausted
        """
        if not self.chain:
            self._logger.warning("Fallback chain is empty")
            return None
        
        # Find current model in chain
        try:
            current_idx = self.chain.index(current_model)
            next_idx = current_idx + 1
        except ValueError:
            # Current model not in chain, start from beginning
            next_idx = 0
        
        if next_idx < len(self.chain):
            next_model = self.chain[next_idx]
            self._current_index = next_idx
            self._logger.info(
                f"Fallback model selected: {current_model} -> {next_model}"
            )
            return next_model
        
        self._logger.error(
            f"Fallback chain exhausted after {current_model}"
        )
        return None
    
    def record_error(self, error: str) -> None:
        """
        Record an error for rate calculation.
        
        Args:
            error: Error message
        """
        self._error_window.record_error()
        self._logger.debug(f"Error recorded: {error}")
    
    def record_success(self) -> None:
        """Record a successful request."""
        self._error_window.record_success()
    
    def get_current_error_rate(self) -> float:
        """Get current error rate within window."""
        return self._error_window.get_error_rate(self._error_rate_window)
    
    def reset(self) -> None:
        """Reset fallback state."""
        self._current_index = 0
        self._error_window = ErrorWindow()
        self._logger.info("FallbackPolicy reset")
    
    def get_chain_position(self, model: str) -> int:
        """Get position of model in chain (-1 if not found)."""
        try:
            return self.chain.index(model)
        except ValueError:
            return -1
    
    def is_last_in_chain(self, model: str) -> bool:
        """Check if model is the last in the chain."""
        if not self.chain:
            return True
        return model == self.chain[-1]
    
    def get_remaining_models(self, current_model: str) -> List[str]:
        """Get remaining models in chain after current."""
        try:
            idx = self.chain.index(current_model)
            return self.chain[idx + 1:]
        except ValueError:
            return []
    
    def get_config(self) -> Dict:
        """Get current configuration."""
        return {
            "chain": self.chain,
            "triggers": {
                "timeout_ms": self._timeout_ms,
                "error_rate_threshold": self._error_rate_threshold,
                "error_rate_window_seconds": self._error_rate_window,
                "token_limit_exceeded": self._token_limit_trigger
            },
            "current_index": self._current_index,
            "current_error_rate": self.get_current_error_rate()
        }
    
    def update_triggers(self, triggers: Dict) -> None:
        """
        Update trigger thresholds.
        
        Args:
            triggers: New trigger configuration
        """
        if "timeout_ms" in triggers:
            self._timeout_ms = triggers["timeout_ms"]
        if "error_rate_threshold" in triggers:
            self._error_rate_threshold = triggers["error_rate_threshold"]
        if "error_rate_window_seconds" in triggers:
            self._error_rate_window = triggers["error_rate_window_seconds"]
        if "token_limit_exceeded" in triggers:
            self._token_limit_trigger = triggers["token_limit_exceeded"]
        
        self._logger.info(f"Triggers updated: {triggers}")
    
    def get_status(self) -> Dict:
        """Get comprehensive status."""
        return {
            "chain": self.chain,
            "current_index": self._current_index,
            "current_model": (
                self.chain[self._current_index] 
                if self._current_index < len(self.chain) else None
            ),
            "triggers": {
                "timeout_ms": self._timeout_ms,
                "error_rate_threshold": self._error_rate_threshold,
                "error_rate_window_seconds": self._error_rate_window,
                "token_limit_exceeded": self._token_limit_trigger
            },
            "error_rate": self.get_current_error_rate(),
            "errors_in_window": len(self._error_window.errors),
            "total_requests": self._error_window.total
        }


def create_fallback_policy(config: Dict) -> FallbackPolicy:
    """
    Factory function to create a FallbackPolicy.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        FallbackPolicy instance
    """
    return FallbackPolicy(config)
