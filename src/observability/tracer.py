"""
TITAN FUSE Protocol - Reasoning Tracer

Step-by-step reasoning trace for transparency and debugging.
Captures every reasoning step, tool call, and decision point.

TASK-002: Advanced Observability & Transparency Layer
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import uuid
import time


class StepType(Enum):
    """Types of reasoning steps."""
    ANALYSIS = "analysis"
    DECISION = "decision"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    VALIDATION = "validation"
    PATCH = "patch"
    ROLLBACK = "rollback"
    GATE_CHECK = "gate_check"
    ERROR = "error"
    INFO = "info"


class StepStatus(Enum):
    """Status of a reasoning step."""
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


@dataclass
class ReasoningStep:
    """
    A single step in the reasoning trace.

    Attributes:
        step_id: Unique identifier
        step_type: Type of reasoning step
        description: Human-readable description
        status: Current status
        input_data: Input data for the step
        output_data: Output data from the step
        reasoning: Reasoning/explanation for decisions
        duration_ms: Duration in milliseconds
        parent_id: Parent step ID (for nested steps)
        metadata: Additional metadata
        timestamp: When the step was created
    """
    step_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    step_type: StepType = StepType.INFO
    description: str = ""
    status: StepStatus = StepStatus.STARTED
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    duration_ms: int = 0
    parent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    _start_time: float = field(default_factory=time.time, repr=False)

    def complete(self, output_data: Optional[Dict[str, Any]] = None,
                 reasoning: str = "") -> None:
        """Mark step as completed."""
        self.status = StepStatus.COMPLETED
        self.duration_ms = int((time.time() - self._start_time) * 1000)
        if output_data:
            self.output_data = output_data
        if reasoning:
            self.reasoning = reasoning

    def fail(self, error: str, reasoning: str = "") -> None:
        """Mark step as failed."""
        self.status = StepStatus.FAILED
        self.duration_ms = int((time.time() - self._start_time) * 1000)
        self.output_data = {"error": error}
        if reasoning:
            self.reasoning = reasoning

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "step_id": self.step_id,
            "step_type": self.step_type.value,
            "description": self.description,
            "status": self.status.value,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "reasoning": self.reasoning,
            "duration_ms": self.duration_ms,
            "parent_id": self.parent_id,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


@dataclass
class ReasoningTrace:
    """
    Complete reasoning trace for a session.

    Attributes:
        trace_id: Unique trace identifier
        session_id: Associated session ID
        steps: List of reasoning steps
        start_time: When the trace started
        end_time: When the trace ended
        metadata: Trace metadata
    """
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None
    steps: List[ReasoningStep] = field(default_factory=list)
    start_time: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    end_time: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: ReasoningStep) -> str:
        """Add a step to the trace."""
        self.steps.append(step)
        return step.step_id

    def get_step(self, step_id: str) -> Optional[ReasoningStep]:
        """Get a step by ID."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def get_children(self, parent_id: str) -> List[ReasoningStep]:
        """Get all child steps of a parent."""
        return [s for s in self.steps if s.parent_id == parent_id]

    def end(self) -> None:
        """End the trace."""
        self.end_time = datetime.utcnow().isoformat() + "Z"

    def get_summary(self) -> Dict[str, Any]:
        """Get trace summary."""
        total_duration = sum(s.duration_ms for s in self.steps)
        by_type = {}
        by_status = {}

        for step in self.steps:
            t = step.step_type.value
            s = step.status.value
            by_type[t] = by_type.get(t, 0) + 1
            by_status[s] = by_status.get(s, 0) + 1

        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "total_steps": len(self.steps),
            "total_duration_ms": total_duration,
            "by_type": by_type,
            "by_status": by_status,
            "start_time": self.start_time,
            "end_time": self.end_time
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "steps": [s.to_dict() for s in self.steps],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "metadata": self.metadata,
            "summary": self.get_summary()
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class ReasoningTracer:
    """
    Tracer for reasoning steps.

    Features:
    - Step-by-step reasoning capture
    - Nested step support
    - Duration tracking
    - Export to JSON/Prometheus
    - Integration with event bus

    Usage:
        tracer = ReasoningTracer()

        # Start a trace
        tracer.start_trace(session_id="abc123")

        # Add steps
        step = tracer.add_step(
            step_type=StepType.ANALYSIS,
            description="Analyzing file structure",
            input_data={"file": "test.md"}
        )
        # ... do work ...
        tracer.complete_step(step.step_id, output_data={"sections": 5})

        # End trace
        trace = tracer.end_trace()
    """

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path
        self._current_trace: Optional[ReasoningTrace] = None
        self._step_stack: List[str] = []  # Stack of step IDs for nesting
        self._traces: List[ReasoningTrace] = []

    def start_trace(self, session_id: Optional[str] = None,
                    metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Start a new reasoning trace.

        Args:
            session_id: Optional session ID
            metadata: Optional metadata

        Returns:
            Trace ID
        """
        self._current_trace = ReasoningTrace(
            session_id=session_id,
            metadata=metadata or {}
        )
        self._step_stack = []
        self._traces.append(self._current_trace)
        return self._current_trace.trace_id

    def add_step(self,
                 step_type: StepType,
                 description: str,
                 input_data: Optional[Dict[str, Any]] = None,
                 reasoning: str = "",
                 metadata: Optional[Dict[str, Any]] = None) -> ReasoningStep:
        """
        Add a reasoning step.

        Args:
            step_type: Type of step
            description: Description
            input_data: Input data
            reasoning: Reasoning explanation
            metadata: Additional metadata

        Returns:
            The created step
        """
        if not self._current_trace:
            raise RuntimeError("No active trace. Call start_trace() first.")

        # Determine parent from stack
        parent_id = self._step_stack[-1] if self._step_stack else None

        step = ReasoningStep(
            step_type=step_type,
            description=description,
            input_data=input_data or {},
            reasoning=reasoning,
            parent_id=parent_id,
            metadata=metadata or {}
        )

        self._current_trace.add_step(step)
        self._step_stack.append(step.step_id)

        # Write to log if configured
        if self.log_path:
            self._write_step(step)

        return step

    def complete_step(self, step_id: str,
                      output_data: Optional[Dict[str, Any]] = None,
                      reasoning: str = "") -> Optional[ReasoningStep]:
        """
        Complete a reasoning step.

        Args:
            step_id: ID of step to complete
            output_data: Output data
            reasoning: Reasoning explanation

        Returns:
            The completed step
        """
        if not self._current_trace:
            return None

        step = self._current_trace.get_step(step_id)
        if step:
            step.complete(output_data, reasoning)

            # Remove from stack
            if step_id in self._step_stack:
                self._step_stack.remove(step_id)

            # Write to log if configured
            if self.log_path:
                self._write_step(step)

        return step

    def fail_step(self, step_id: str, error: str,
                  reasoning: str = "") -> Optional[ReasoningStep]:
        """Mark a step as failed."""
        if not self._current_trace:
            return None

        step = self._current_trace.get_step(step_id)
        if step:
            step.fail(error, reasoning)

            if step_id in self._step_stack:
                self._step_stack.remove(step_id)

            if self.log_path:
                self._write_step(step)

        return step

    def end_trace(self) -> Optional[ReasoningTrace]:
        """
        End the current trace.

        Returns:
            The completed trace
        """
        if not self._current_trace:
            return None

        self._current_trace.end()
        trace = self._current_trace
        self._current_trace = None
        self._step_stack = []

        return trace

    def get_current_trace(self) -> Optional[ReasoningTrace]:
        """Get the current trace."""
        return self._current_trace

    def get_traces(self) -> List[ReasoningTrace]:
        """Get all traces."""
        return self._traces

    def _write_step(self, step: ReasoningStep) -> None:
        """Write step to log file."""
        if not self.log_path:
            return

        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(step.to_dict()) + "\n")
        except Exception as e:
            print(f"Failed to write trace log: {e}")

    def export_prometheus(self) -> str:
        """
        Export metrics in Prometheus format.

        Returns:
            Prometheus-formatted metrics
        """
        lines = []

        total_steps = sum(len(t.steps) for t in self._traces)
        total_duration = sum(
            sum(s.duration_ms for s in t.steps)
            for t in self._traces
        )

        lines.append("# HELP titan_reasoning_steps_total Total reasoning steps")
        lines.append("# TYPE titan_reasoning_steps_total counter")
        lines.append(f"titan_reasoning_steps_total {total_steps}")

        lines.append("# HELP titan_reasoning_duration_ms Total reasoning duration")
        lines.append("# TYPE titan_reasoning_duration_ms counter")
        lines.append(f"titan_reasoning_duration_ms {total_duration}")

        lines.append("# HELP titan_traces_total Total number of traces")
        lines.append("# TYPE titan_traces_total counter")
        lines.append(f"titan_traces_total {len(self._traces)}")

        # By type
        type_counts = {}
        for trace in self._traces:
            for step in trace.steps:
                t = step.step_type.value
                type_counts[t] = type_counts.get(t, 0) + 1

        lines.append("# HELP titan_steps_by_type Steps by type")
        lines.append("# TYPE titan_steps_by_type counter")
        for t, count in type_counts.items():
            lines.append(f'titan_steps_by_type{{type="{t}"}} {count}')

        return "\n".join(lines)


# Global tracer instance
_global_tracer: Optional[ReasoningTracer] = None


def get_tracer() -> ReasoningTracer:
    """Get the global tracer."""
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = ReasoningTracer()
    return _global_tracer


def start_trace(session_id: Optional[str] = None,
                metadata: Optional[Dict[str, Any]] = None) -> str:
    """Start a new trace in the global tracer."""
    return get_tracer().start_trace(session_id, metadata)


def add_step(step_type: StepType, description: str,
             **kwargs) -> ReasoningStep:
    """Add a step to the current trace."""
    return get_tracer().add_step(step_type, description, **kwargs)


def end_trace() -> Optional[ReasoningTrace]:
    """End the current trace."""
    return get_tracer().end_trace()


def get_current_trace() -> Optional[ReasoningTrace]:
    """Get the current trace."""
    return get_tracer().get_current_trace()
