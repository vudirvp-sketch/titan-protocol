"""
ITEM-OBS-85: Granular Token Attribution per Gate

This module provides per-gate token attribution to track token costs
for individual gates, enabling detailed cost breakdown in metrics.json.

Token costs are tracked globally but not attributed to individual gates.
This module solves that by implementing per-gate token attribution with
detailed breakdown.

Features:
- Track tokens per gate (prompt, completion, total)
- Active gate tracking with timing
- Thread-safe implementation
- Statistics for monitoring
- Easy integration with gate execution wrapping

Usage:
    from src.observability.token_attribution import (
        TokenAttributor,
        get_token_attributor,
        start_gate,
        end_gate,
    )

    # Get or create the global attributor
    attributor = get_token_attributor()

    # Manual tracking
    attributor.start_gate("GATE-00")
    # ... gate execution ...
    attributor.end_gate("GATE-00", tokens_used=150, prompt_tokens=100, completion_tokens=50)

    # Or use wrapper for automatic timing
    result = attributor.wrap_gate_execution("GATE-01", my_callable, tokens_used=200)

    # Get attribution data
    attribution = attributor.get_attribution()
    # {
    #     "GATE-00": {"prompt_tokens": 100, "completion_tokens": 50, ...},
    #     "GATE-01": {...}
    # }
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, TypeVar, List
from datetime import datetime
import threading
import logging
import functools

from src.utils.timezone import now_utc, now_utc_iso

T = TypeVar('T')


@dataclass
class GateTokenRecord:
    """
    Token usage record for a single gate.
    
    Attributes:
        gate_id: Unique identifier for the gate (e.g., "GATE-00")
        prompt_tokens: Total prompt tokens used by this gate
        completion_tokens: Total completion tokens used by this gate
        total_tokens: Total tokens (prompt + completion)
        call_count: Number of times this gate was invoked
        first_started_at: ISO timestamp of first gate start
        last_started_at: ISO timestamp of most recent gate start
        last_ended_at: ISO timestamp of most recent gate end
        total_duration_ms: Total duration in milliseconds across all calls
    """
    gate_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    first_started_at: Optional[str] = None
    last_started_at: Optional[str] = None
    last_ended_at: Optional[str] = None
    total_duration_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary for serialization."""
        avg_tokens = (
            round(self.total_tokens / self.call_count, 2)
            if self.call_count > 0 else 0.0
        )
        avg_duration = (
            round(self.total_duration_ms / self.call_count, 2)
            if self.call_count > 0 else 0.0
        )
        
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
            "avg_tokens_per_call": avg_tokens,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "avg_duration_ms": avg_duration,
            "first_started_at": self.first_started_at,
            "last_started_at": self.last_started_at,
            "last_ended_at": self.last_ended_at,
        }


@dataclass
class ActiveGate:
    """
    Tracks an actively executing gate.
    
    Attributes:
        gate_id: Unique identifier for the gate
        started_at: ISO timestamp when gate started
        started_at_dt: DateTime object for duration calculation
    """
    gate_id: str
    started_at: str
    started_at_dt: datetime


class TokenAttributor:
    """
    ITEM-OBS-85: Token Attribution per Gate.
    
    Tracks token costs per individual gate for detailed cost breakdown.
    
    Thread-safe implementation that supports:
    - Per-gate token tracking (prompt, completion, total)
    - Active gate tracking with timing
    - Statistics aggregation
    - Easy integration via wrap_gate_execution
    
    Example:
        attributor = TokenAttributor()
        
        # Start tracking a gate
        attributor.start_gate("GATE-00")
        
        # End tracking with token usage
        attributor.end_gate(
            "GATE-00",
            tokens_used=200,
            prompt_tokens=150,
            completion_tokens=50
        )
        
        # Get attribution report
        report = attributor.get_attribution()
        
        # Verify totals match
        assert attributor.get_total_tokens() == 200
    """
    
    def __init__(self):
        """Initialize the token attributor."""
        self._lock = threading.Lock()
        self._records: Dict[str, GateTokenRecord] = {}
        self._active_gates: Dict[str, ActiveGate] = {}
        self._logger = logging.getLogger(__name__)
    
    def start_gate(self, gate_id: str) -> None:
        """
        Mark the start of gate execution.
        
        Records the start time for duration tracking. Must be paired
        with end_gate() call.
        
        Args:
            gate_id: Unique identifier for the gate (e.g., "GATE-00")
        
        Raises:
            ValueError: If gate_id is already active
        """
        with self._lock:
            if gate_id in self._active_gates:
                raise ValueError(
                    f"Gate '{gate_id}' is already active. "
                    f"Call end_gate() before starting again."
                )
            
            now_dt = now_utc()
            now_iso = now_utc_iso()
            
            # Create active gate entry
            self._active_gates[gate_id] = ActiveGate(
                gate_id=gate_id,
                started_at=now_iso,
                started_at_dt=now_dt
            )
            
            # Initialize record if first time
            if gate_id not in self._records:
                self._records[gate_id] = GateTokenRecord(gate_id=gate_id)
            
            record = self._records[gate_id]
            record.last_started_at = now_iso
            if record.first_started_at is None:
                record.first_started_at = now_iso
            
            self._logger.debug(f"[ITEM-OBS-85] Started gate: {gate_id}")
    
    def end_gate(
        self,
        gate_id: str,
        tokens_used: int,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None
    ) -> None:
        """
        Mark the end of gate execution and record token usage.
        
        Must be called after start_gate() for the same gate_id.
        
        Args:
            gate_id: Unique identifier for the gate
            tokens_used: Total tokens used in this gate execution
            prompt_tokens: Optional breakdown of prompt tokens
            completion_tokens: Optional breakdown of completion tokens
        
        Raises:
            ValueError: If gate_id is not active (start_gate not called)
        """
        with self._lock:
            if gate_id not in self._active_gates:
                raise ValueError(
                    f"Gate '{gate_id}' is not active. "
                    f"Call start_gate() before ending."
                )
            
            active_gate = self._active_gates.pop(gate_id)
            now_dt = now_utc()
            now_iso = now_utc_iso()
            
            # Calculate duration
            duration_ms = (now_dt - active_gate.started_at_dt).total_seconds() * 1000
            
            # Update record
            record = self._records[gate_id]
            
            # If prompt/completion not provided, derive from total
            if prompt_tokens is None:
                prompt_tokens = 0
            if completion_tokens is None:
                completion_tokens = tokens_used - prompt_tokens
            
            # Ensure totals are consistent
            calculated_total = prompt_tokens + completion_tokens
            if calculated_total != tokens_used and tokens_used > 0:
                # Adjust completion_tokens to match total
                completion_tokens = tokens_used - prompt_tokens
            
            record.prompt_tokens += prompt_tokens
            record.completion_tokens += completion_tokens
            record.total_tokens += tokens_used
            record.call_count += 1
            record.last_ended_at = now_iso
            record.total_duration_ms += duration_ms
            
            self._logger.debug(
                f"[ITEM-OBS-85] Ended gate: {gate_id}, "
                f"tokens={tokens_used}, duration_ms={duration_ms:.2f}"
            )
    
    def get_attribution(self) -> Dict[str, Dict[str, Any]]:
        """
        Get token attribution for all gates.
        
        Returns:
            Dictionary mapping gate_id to token breakdown:
            {
                "GATE-00": {
                    "prompt_tokens": 150,
                    "completion_tokens": 50,
                    "total_tokens": 200,
                    "call_count": 3,
                    "avg_tokens_per_call": 66.67,
                    "avg_duration_ms": 12.34,
                    "first_started_at": "...",
                    "last_started_at": "...",
                    "last_ended_at": "..."
                },
                ...
            }
        """
        with self._lock:
            return {
                gate_id: record.to_dict()
                for gate_id, record in self._records.items()
            }
    
    def get_gate_attribution(self, gate_id: str) -> Optional[Dict[str, Any]]:
        """
        Get token attribution for a specific gate.
        
        Args:
            gate_id: The gate identifier
        
        Returns:
            Attribution dict for the gate, or None if not found
        """
        with self._lock:
            if gate_id in self._records:
                return self._records[gate_id].to_dict()
            return None
    
    def get_total_tokens(self) -> int:
        """
        Get the sum of all attributed tokens.
        
        Returns:
            Total tokens across all gates
        """
        with self._lock:
            return sum(record.total_tokens for record in self._records.values())
    
    def get_total_prompt_tokens(self) -> int:
        """
        Get the sum of all prompt tokens.
        
        Returns:
            Total prompt tokens across all gates
        """
        with self._lock:
            return sum(record.prompt_tokens for record in self._records.values())
    
    def get_total_completion_tokens(self) -> int:
        """
        Get the sum of all completion tokens.
        
        Returns:
            Total completion tokens across all gates
        """
        with self._lock:
            return sum(record.completion_tokens for record in self._records.values())
    
    def get_gate_count(self) -> int:
        """
        Get the number of unique gates tracked.
        
        Returns:
            Number of gates with recorded usage
        """
        with self._lock:
            return len(self._records)
    
    def get_total_call_count(self) -> int:
        """
        Get the total number of gate calls.
        
        Returns:
            Sum of call_count across all gates
        """
        with self._lock:
            return sum(record.call_count for record in self._records.values())
    
    def get_active_gates(self) -> List[str]:
        """
        Get list of currently active gate IDs.
        
        Returns:
            List of gate_ids that have been started but not ended
        """
        with self._lock:
            return list(self._active_gates.keys())
    
    def is_gate_active(self, gate_id: str) -> bool:
        """
        Check if a gate is currently active.
        
        Args:
            gate_id: The gate identifier
        
        Returns:
            True if gate is active (started but not ended)
        """
        with self._lock:
            return gate_id in self._active_gates
    
    def reset(self) -> None:
        """
        Clear all attribution data.
        
        Removes all records and active gates. Use with caution.
        """
        with self._lock:
            self._records.clear()
            self._active_gates.clear()
            self._logger.info("[ITEM-OBS-85] Token attribution reset")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get summary statistics.
        
        Returns:
            Dictionary with summary stats:
            {
                "total_gates": 5,
                "total_calls": 15,
                "total_tokens": 5000,
                "total_prompt_tokens": 3500,
                "total_completion_tokens": 1500,
                "active_gates": 1,
                "gates": {...}
            }
        """
        with self._lock:
            return {
                "total_gates": len(self._records),
                "total_calls": sum(r.call_count for r in self._records.values()),
                "total_tokens": sum(r.total_tokens for r in self._records.values()),
                "total_prompt_tokens": sum(r.prompt_tokens for r in self._records.values()),
                "total_completion_tokens": sum(r.completion_tokens for r in self._records.values()),
                "active_gates": len(self._active_gates),
                "gates": {
                    gate_id: record.to_dict()
                    for gate_id, record in self._records.items()
                }
            }
    
    def wrap_gate_execution(
        self,
        gate_id: str,
        func: Callable[..., T],
        tokens_used: int,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None
    ) -> T:
        """
        Wrap a callable with gate execution tracking.
        
        Automatically handles start_gate and end_gate calls with
        timing and exception handling.
        
        Args:
            gate_id: Unique identifier for the gate
            func: Callable to execute within gate tracking
            tokens_used: Total tokens used by this execution
            prompt_tokens: Optional prompt tokens breakdown
            completion_tokens: Optional completion tokens breakdown
        
        Returns:
            The result of func()
        
        Raises:
            Exception: Any exception raised by func()
        
        Example:
            def my_llm_call():
                # ... LLM call ...
                return result
            
            result = attributor.wrap_gate_execution(
                "GATE-00",
                my_llm_call,
                tokens_used=150,
                prompt_tokens=100,
                completion_tokens=50
            )
        """
        self.start_gate(gate_id)
        try:
            result = func()
            self.end_gate(
                gate_id,
                tokens_used=tokens_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens
            )
            return result
        except Exception as e:
            # End gate even on exception (with 0 tokens since we don't know)
            self._logger.warning(
                f"[ITEM-OBS-85] Gate '{gate_id}' raised exception: {e}"
            )
            # Still end the gate to clean up active state
            with self._lock:
                if gate_id in self._active_gates:
                    self._active_gates.pop(gate_id)
            raise
    
    def record_existing_usage(
        self,
        gate_id: str,
        tokens_used: int,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None
    ) -> None:
        """
        Record token usage without active gate tracking.
        
        Use this for batch recording or when integrating with existing
        systems that don't use start_gate/end_gate pattern.
        
        Args:
            gate_id: Unique identifier for the gate
            tokens_used: Total tokens used
            prompt_tokens: Optional prompt tokens breakdown
            completion_tokens: Optional completion tokens breakdown
        """
        with self._lock:
            now_iso = now_utc_iso()
            
            if gate_id not in self._records:
                self._records[gate_id] = GateTokenRecord(gate_id=gate_id)
            
            record = self._records[gate_id]
            
            # Handle token breakdown
            if prompt_tokens is None:
                prompt_tokens = 0
            if completion_tokens is None:
                completion_tokens = tokens_used - prompt_tokens
            
            record.prompt_tokens += prompt_tokens
            record.completion_tokens += completion_tokens
            record.total_tokens += tokens_used
            record.call_count += 1
            
            if record.first_started_at is None:
                record.first_started_at = now_iso
            record.last_started_at = now_iso
            record.last_ended_at = now_iso
            
            self._logger.debug(
                f"[ITEM-OBS-85] Recorded usage for gate: {gate_id}, tokens={tokens_used}"
            )


# Global instance
_global_attributor: Optional[TokenAttributor] = None
_global_lock = threading.Lock()


def get_token_attributor() -> TokenAttributor:
    """
    Get the global TokenAttributor instance.
    
    Creates a new instance on first call.
    
    Returns:
        The global TokenAttributor instance
    """
    global _global_attributor
    if _global_attributor is None:
        with _global_lock:
            if _global_attributor is None:
                _global_attributor = TokenAttributor()
    return _global_attributor


def init_token_attributor() -> TokenAttributor:
    """
    Initialize and return a new global TokenAttributor.
    
    Replaces any existing global instance.
    
    Returns:
        The new global TokenAttributor instance
    """
    global _global_attributor
    with _global_lock:
        _global_attributor = TokenAttributor()
    return _global_attributor


def start_gate(gate_id: str) -> None:
    """
    Start tracking a gate using the global attributor.
    
    Convenience function for get_token_attributor().start_gate().
    
    Args:
        gate_id: Unique identifier for the gate
    """
    get_token_attributor().start_gate(gate_id)


def end_gate(
    gate_id: str,
    tokens_used: int,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None
) -> None:
    """
    End tracking a gate using the global attributor.
    
    Convenience function for get_token_attributor().end_gate().
    
    Args:
        gate_id: Unique identifier for the gate
        tokens_used: Total tokens used
        prompt_tokens: Optional prompt tokens breakdown
        completion_tokens: Optional completion tokens breakdown
    """
    get_token_attributor().end_gate(
        gate_id,
        tokens_used=tokens_used,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens
    )


def get_attribution() -> Dict[str, Dict[str, Any]]:
    """
    Get token attribution from global attributor.
    
    Convenience function for get_token_attributor().get_attribution().
    
    Returns:
        Dictionary of gate_id -> token breakdown
    """
    return get_token_attributor().get_attribution()


def get_total_tokens() -> int:
    """
    Get total tokens from global attributor.
    
    Convenience function for get_token_attributor().get_total_tokens().
    
    Returns:
        Total tokens across all gates
    """
    return get_token_attributor().get_total_tokens()


def reset_attribution() -> None:
    """
    Reset the global attributor.
    
    Convenience function for get_token_attributor().reset().
    """
    get_token_attributor().reset()
