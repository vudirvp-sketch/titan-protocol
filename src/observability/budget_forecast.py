"""
TITAN FUSE Protocol - Budget Forecasting

ITEM-OBS-05: Token velocity forecasting for proactive budget management.

This module provides:
- BudgetForecaster: Token velocity calculation and forecasting
- UsageRecord: Individual usage tracking record
- ForecastReport: Comprehensive forecast report with recommendations
- Proactive warning system with actionable recommendations

Features:
- Tracks last 100 operations for velocity calculation
- Calculates tokens per second velocity
- Proactive warnings at 90% and 95% thresholds
- EventBus integration for warning events
- Metrics integration for monitoring

Author: TITAN FUSE Team
Version: 3.7.1
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from enum import Enum
from collections import deque
import logging
import time
import threading

if TYPE_CHECKING:
    from ..events.event_bus import EventBus, Event
    from .metrics import MetricsCollector


class WarningLevel(Enum):
    """Budget warning severity levels."""
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class UsageRecord:
    """
    Individual token usage record.

    Tracks token consumption with metadata for velocity calculation.
    """
    tokens: int
    phase: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    model: str = "unknown"
    operation: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "tokens": self.tokens,
            "phase": self.phase,
            "timestamp": self.timestamp.isoformat() + "Z",
            "model": self.model,
            "operation": self.operation
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UsageRecord':
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.rstrip("Z"))
        return cls(
            tokens=data["tokens"],
            phase=data["phase"],
            timestamp=timestamp or datetime.utcnow(),
            model=data.get("model", "unknown"),
            operation=data.get("operation", "unknown")
        )


@dataclass
class ForecastReport:
    """
    Comprehensive budget forecast report.

    Contains current state, velocity metrics, forecasts, and recommendations.
    """
    current_usage: int
    budget: int
    remaining: int
    velocity: float  # tokens per second
    estimated_remaining_seconds: float
    estimated_tokens_at_completion: int
    warning_level: str  # OK | WARNING | CRITICAL
    recommended_action: Optional[str] = None
    usage_records_count: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "current_usage": self.current_usage,
            "budget": self.budget,
            "remaining": self.remaining,
            "velocity": self.velocity,
            "estimated_remaining_seconds": self.estimated_remaining_seconds,
            "estimated_tokens_at_completion": self.estimated_tokens_at_completion,
            "warning_level": self.warning_level,
            "recommended_action": self.recommended_action,
            "usage_records_count": self.usage_records_count,
            "timestamp": self.timestamp.isoformat() + "Z"
        }

    @property
    def usage_percentage(self) -> float:
        """Get usage as percentage of budget."""
        if self.budget == 0:
            return 0.0
        return (self.current_usage / self.budget) * 100

    @property
    def remaining_percentage(self) -> float:
        """Get remaining budget as percentage."""
        return 100.0 - self.usage_percentage


class BudgetForecaster:
    """
    Token velocity forecasting for proactive budget management.

    ITEM-OBS-05: Provides predictive budget forecasting with early warning
    system and actionable recommendations.

    Features:
    - Tracks last N operations for velocity calculation (default: 100)
    - Calculates tokens per second velocity
    - Proactive warnings at configurable thresholds
    - EventBus integration for warning events
    - Metrics integration for monitoring

    Usage:
        forecaster = BudgetForecaster(budget=100000)
        forecaster.record_usage(1000, phase=1, model="gpt-4", operation="chunk")

        # Get velocity
        velocity = forecaster.get_velocity()  # tokens/second

        # Get forecast report
        report = forecaster.get_forecast_report()

        # Check if warning needed
        if report.warning_level != "OK":
            print(f"Warning: {report.recommended_action}")
    """

    DEFAULT_WARNING_THRESHOLD = 0.9  # 90%
    DEFAULT_CRITICAL_THRESHOLD = 0.95  # 95%
    DEFAULT_HISTORY_WINDOW = 100
    DEFAULT_MIN_VELOCITY_SAMPLES = 2

    RECOMMENDED_ACTIONS = {
        "warning": [
            "compact_context",
            "switch_to_leaf_model",
            "reduce_chunk_size"
        ],
        "critical": [
            "switch_to_leaf_model",
            "reduce_scope",
            "request_budget_increase"
        ]
    }

    def __init__(
        self,
        budget: int,
        config: Optional[Dict[str, Any]] = None,
        event_bus: Optional['EventBus'] = None,
        metrics: Optional['MetricsCollector'] = None
    ):
        """
        Initialize BudgetForecaster.

        Args:
            budget: Total token budget
            config: Configuration dictionary with optional keys:
                - warning_threshold: Warning threshold (default: 0.9)
                - critical_threshold: Critical threshold (default: 0.95)
                - history_window: Max records to track (default: 100)
                - enabled: Whether forecasting is enabled (default: True)
            event_bus: Optional EventBus for warning events
            metrics: Optional MetricsCollector for metrics
        """
        self.budget = budget
        self.config = config or {}
        self._event_bus = event_bus
        self._metrics = metrics
        self._logger = logging.getLogger(__name__)

        # Configuration
        self._warning_threshold = self.config.get(
            "warning_threshold", self.DEFAULT_WARNING_THRESHOLD
        )
        self._critical_threshold = self.config.get(
            "critical_threshold", self.DEFAULT_CRITICAL_THRESHOLD
        )
        self._history_window = self.config.get(
            "history_window", self.DEFAULT_HISTORY_WINDOW
        )
        self._enabled = self.config.get("enabled", True)

        # State
        self._usage_records: deque = deque(maxlen=self._history_window)
        self._total_usage = 0
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._last_warning_level = WarningLevel.OK

        # Recommended actions from config
        self._recommended_actions = self.config.get(
            "recommended_actions",
            self.RECOMMENDED_ACTIONS["warning"]
        )

        # Register metrics
        self._register_metrics()

    def _register_metrics(self) -> None:
        """Register budget forecasting metrics."""
        if self._metrics is None:
            return

        # Register gauges for budget metrics
        self._forecast_tokens_gauge = self._metrics.register_gauge(
            "budget_forecast_tokens",
            "Predicted token usage at completion"
        )
        self._velocity_gauge = self._metrics.register_gauge(
            "budget_velocity_tps",
            "Token velocity in tokens per second"
        )
        self._remaining_seconds_gauge = self._metrics.register_gauge(
            "budget_remaining_seconds",
            "Estimated seconds until budget exhaustion"
        )
        self._warning_level_gauge = self._metrics.register_gauge(
            "budget_warning_level",
            "Budget warning level (0=OK, 1=WARNING, 2=CRITICAL)"
        )

    def record_usage(
        self,
        tokens: int,
        phase: int,
        model: str = "unknown",
        operation: str = "unknown"
    ) -> None:
        """
        Record token usage for velocity calculation.

        Args:
            tokens: Number of tokens used
            phase: Current phase number
            model: Model used (default: "unknown")
            operation: Operation type (default: "unknown")
        """
        if not self._enabled:
            return

        with self._lock:
            record = UsageRecord(
                tokens=tokens,
                phase=phase,
                timestamp=datetime.utcnow(),
                model=model,
                operation=operation
            )
            self._usage_records.append(record)
            self._total_usage += tokens

        # Update metrics and check for warnings
        self._update_metrics()
        self._check_and_emit_warning()

    def get_velocity(self) -> float:
        """
        Calculate token velocity (tokens per second).

        Velocity is calculated based on the time span between
        the first and last usage records. Returns 0 if insufficient data.

        Returns:
            Tokens per second velocity
        """
        with self._lock:
            if len(self._usage_records) < self.DEFAULT_MIN_VELOCITY_SAMPLES:
                return 0.0

            records = list(self._usage_records)
            first = records[0]
            last = records[-1]

            # Calculate time span in seconds
            time_span = (last.timestamp - first.timestamp).total_seconds()

            if time_span <= 0:
                # All records at same timestamp - use total tokens
                # as instantaneous velocity estimate
                total = sum(r.tokens for r in records)
                return float(total) if total > 0 else 0.0

            # Calculate total tokens in the window
            total_tokens = sum(r.tokens for r in records)

            # Velocity = tokens / time
            return total_tokens / time_span

    def get_current_usage(self) -> int:
        """Get total tokens used so far."""
        with self._lock:
            return self._total_usage

    def get_remaining_budget(self) -> int:
        """Get remaining token budget."""
        return max(0, self.budget - self.get_current_usage())

    def forecast_remaining_time(self) -> float:
        """
        Forecast remaining time until budget exhaustion.

        Returns:
            Estimated seconds until budget exhaustion, or -1 if
            velocity is 0 (cannot estimate)
        """
        remaining = self.get_remaining_budget()
        velocity = self.get_velocity()

        if velocity <= 0:
            return -1.0  # Cannot estimate

        return remaining / velocity

    def forecast_tokens_at_completion(self) -> int:
        """
        Forecast total tokens at completion.

        This is a simple projection based on current velocity and
        assumes the session will complete normally.

        Returns:
            Estimated total tokens at session completion
        """
        # For now, return current usage + estimated remaining
        # A more sophisticated implementation could use phase progression
        current = self.get_current_usage()
        remaining = self.get_remaining_budget()

        # If we have velocity and time estimates, use them
        velocity = self.get_velocity()
        if velocity > 0:
            remaining_time = self.forecast_remaining_time()
            if remaining_time > 0:
                # Estimate based on velocity
                estimated_remaining = int(velocity * remaining_time)
                # Cap at budget
                estimated_remaining = min(estimated_remaining, remaining)
                return current + estimated_remaining

        return current + remaining

    def get_warning_level(self) -> WarningLevel:
        """
        Determine current warning level based on budget usage.

        Returns:
            WarningLevel enum value
        """
        if self.budget == 0:
            return WarningLevel.OK

        usage_ratio = self.get_current_usage() / self.budget

        if usage_ratio >= self._critical_threshold:
            return WarningLevel.CRITICAL
        elif usage_ratio >= self._warning_threshold:
            return WarningLevel.WARNING
        else:
            return WarningLevel.OK

    def get_recommended_action(self, level: WarningLevel) -> Optional[str]:
        """
        Get recommended action for warning level.

        Args:
            level: Warning level

        Returns:
            Recommended action string or None
        """
        if level == WarningLevel.OK:
            return None

        actions = self.RECOMMENDED_ACTIONS.get(
            "critical" if level == WarningLevel.CRITICAL else "warning",
            []
        )

        # Return first action from configured actions that matches
        for action in self._recommended_actions:
            if action in actions:
                return action

        return actions[0] if actions else None

    def get_forecast_report(self) -> ForecastReport:
        """
        Generate comprehensive forecast report.

        Returns:
            ForecastReport with current state and predictions
        """
        with self._lock:
            current_usage = self._total_usage
            records_count = len(self._usage_records)

        remaining = self.get_remaining_budget()
        velocity = self.get_velocity()
        remaining_time = self.forecast_remaining_time()
        tokens_at_completion = self.forecast_tokens_at_completion()
        warning_level = self.get_warning_level()
        recommended_action = self.get_recommended_action(warning_level)

        return ForecastReport(
            current_usage=current_usage,
            budget=self.budget,
            remaining=remaining,
            velocity=velocity,
            estimated_remaining_seconds=remaining_time,
            estimated_tokens_at_completion=tokens_at_completion,
            warning_level=warning_level.value,
            recommended_action=recommended_action,
            usage_records_count=records_count
        )

    def _update_metrics(self) -> None:
        """Update registered metrics with current values."""
        if self._metrics is None:
            return

        report = self.get_forecast_report()

        # Set gauge values
        self._forecast_tokens_gauge.set(report.estimated_tokens_at_completion)
        self._velocity_gauge.set(report.velocity)

        if report.estimated_remaining_seconds >= 0:
            self._remaining_seconds_gauge.set(report.estimated_remaining_seconds)

        # Map warning level to numeric
        level_map = {"OK": 0, "WARNING": 1, "CRITICAL": 2}
        self._warning_level_gauge.set(
            level_map.get(report.warning_level, 0)
        )

    def _check_and_emit_warning(self) -> None:
        """Check warning level and emit events if threshold crossed."""
        if self._event_bus is None:
            return

        current_level = self.get_warning_level()

        # Only emit if level changed
        if current_level == self._last_warning_level:
            return

        self._last_warning_level = current_level

        if current_level == WarningLevel.OK:
            return

        # Import here to avoid circular dependency
        from ..events.event_bus import Event, EventSeverity

        event_type = (
            "BUDGET_CRITICAL" if current_level == WarningLevel.CRITICAL
            else "BUDGET_WARNING"
        )

        report = self.get_forecast_report()

        event = Event(
            event_type=event_type,
            data={
                "current_usage": report.current_usage,
                "budget": report.budget,
                "remaining": report.remaining,
                "velocity": report.velocity,
                "estimated_remaining_seconds": report.estimated_remaining_seconds,
                "recommended_action": report.recommended_action,
                "warning_level": report.warning_level
            },
            severity=EventSeverity.WARN if current_level == WarningLevel.WARNING
                     else EventSeverity.CRITICAL,
            source="BudgetForecaster"
        )

        self._event_bus.emit(event)
        self._logger.warning(
            f"Budget warning: {current_level.value} - "
            f"Usage: {report.current_usage}/{report.budget} "
            f"({report.usage_percentage:.1f}%) - "
            f"Recommended: {report.recommended_action}"
        )

    def reset(self, new_budget: Optional[int] = None) -> None:
        """
        Reset forecaster state.

        Args:
            new_budget: Optional new budget (keeps current if not provided)
        """
        with self._lock:
            if new_budget is not None:
                self.budget = new_budget
            self._usage_records.clear()
            self._total_usage = 0
            self._start_time = time.time()
            self._last_warning_level = WarningLevel.OK

        self._logger.info(f"BudgetForecaster reset with budget: {self.budget}")

    def set_budget(self, budget: int) -> None:
        """
        Update budget limit.

        Args:
            budget: New budget limit
        """
        with self._lock:
            self.budget = budget
        self._check_and_emit_warning()

    def set_event_bus(self, event_bus: 'EventBus') -> None:
        """Set the EventBus instance."""
        self._event_bus = event_bus

    def set_metrics(self, metrics: 'MetricsCollector') -> None:
        """Set the MetricsCollector instance."""
        self._metrics = metrics
        self._register_metrics()

    def get_stats(self) -> Dict[str, Any]:
        """Get forecaster statistics."""
        with self._lock:
            return {
                "budget": self.budget,
                "total_usage": self._total_usage,
                "remaining": self.get_remaining_budget(),
                "usage_percentage": (self._total_usage / self.budget * 100)
                                   if self.budget > 0 else 0,
                "velocity_tps": self.get_velocity(),
                "warning_level": self.get_warning_level().value,
                "records_tracked": len(self._usage_records),
                "enabled": self._enabled,
                "warning_threshold": self._warning_threshold,
                "critical_threshold": self._critical_threshold,
                "uptime_seconds": time.time() - self._start_time
            }


# Module-level convenience functions
_global_forecaster: Optional[BudgetForecaster] = None


def get_forecaster() -> Optional[BudgetForecaster]:
    """Get the global BudgetForecaster instance."""
    return _global_forecaster


def init_forecaster(
    budget: int,
    config: Optional[Dict[str, Any]] = None,
    event_bus: Optional['EventBus'] = None,
    metrics: Optional['MetricsCollector'] = None
) -> BudgetForecaster:
    """
    Initialize and set the global BudgetForecaster.

    Args:
        budget: Total token budget
        config: Configuration dictionary
        event_bus: Optional EventBus
        metrics: Optional MetricsCollector

    Returns:
        The initialized BudgetForecaster
    """
    global _global_forecaster
    _global_forecaster = BudgetForecaster(
        budget=budget,
        config=config,
        event_bus=event_bus,
        metrics=metrics
    )
    return _global_forecaster


def record_usage(tokens: int, phase: int, model: str = "unknown",
                 operation: str = "unknown") -> None:
    """Record usage to global forecaster."""
    if _global_forecaster is not None:
        _global_forecaster.record_usage(tokens, phase, model, operation)


def get_budget_report() -> Optional[ForecastReport]:
    """Get forecast report from global forecaster."""
    if _global_forecaster is not None:
        return _global_forecaster.get_forecast_report()
    return None
