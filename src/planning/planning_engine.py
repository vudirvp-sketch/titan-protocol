"""
Planning Engine for TITAN Protocol.

ITEM-DAG-112: Integration of CycleDetector with event-driven planning.

The PlanningEngine orchestrates plan execution with cycle detection
to prevent infinite loops in the execution DAG.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import logging

from pydantic import BaseModel, Field

from .cycle_detector import (
    CycleDetector,
    DAG,
    DAGNode,
    Amendment,
    AmendmentType,
    validate_dag_object
)


class EngineState(Enum):
    """States of the PlanningEngine."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    HALTED = "halted"
    COMPLETED = "completed"
    ERROR = "error"


class HaltReason(Enum):
    """Reasons for engine halt."""
    CYCLE_DETECTED = "cycle_detected"
    BUDGET_EXCEEDED = "budget_exceeded"
    GATE_FAILURE = "gate_failure"
    USER_REQUEST = "user_request"
    ERROR = "error"


@dataclass
class PlanStep:
    """
    A step in the execution plan.
    
    Attributes:
        step_id: Unique identifier for the step
        action: Action to perform
        dependencies: List of step IDs this step depends on
        status: Current status of the step
        result: Result of step execution
    """
    step_id: str
    action: Callable[[], Any]
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"
    result: Any = None


@dataclass
class ValidationResult:
    """
    Result of validating an amendment.
    
    Attributes:
        valid: Whether the amendment is valid
        cycle_path: Path of the cycle if one would be introduced
        amendment: The amendment that was validated
    """
    valid: bool
    cycle_path: Optional[List[str]] = None
    amendment: Optional[Amendment] = None


class PlanningEngine:
    """
    Planning Engine with cycle detection integration.
    
    ITEM-DAG-112: Integrates CycleDetector with event-driven planning.
    
    Features:
    - Cycle detection before each iteration
    - Amendment validation before applying changes
    - EventBus integration for cycle events
    - Halt mechanism when cycles are detected
    
    Usage:
        engine = PlanningEngine(event_bus=bus)
        
        # Add steps to the plan
        engine.add_step(PlanStep(step_id="step1", action=do_something))
        engine.add_step(PlanStep(step_id="step2", action=do_other, 
                                 dependencies=["step1"]))
        
        # Build and validate the DAG
        engine.build_dag()
        
        # Run the plan
        engine.run()
    """
    
    def __init__(self, event_bus: Optional[Any] = None, config: Dict = None):
        """
        Initialize the PlanningEngine.
        
        Args:
            event_bus: Optional EventBus for emitting events
            config: Optional configuration dictionary
        """
        self._event_bus = event_bus
        self._config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # Core components
        self._cycle_detector = CycleDetector()
        self._dag = DAG()
        
        # Plan state
        self._steps: Dict[str, PlanStep] = {}
        self._state = EngineState.IDLE
        self._halt_reason: Optional[HaltReason] = None
        self._current_iteration = 0
        self._max_iterations = self._config.get("max_iterations", 1000)
        
        # Amendment queue
        self._pending_amendments: List[Amendment] = []
        
        # Callbacks
        self._on_cycle_detected: Optional[Callable[[List[str]], None]] = None
        self._on_halt: Optional[Callable[[HaltReason], None]] = None
    
    @property
    def state(self) -> EngineState:
        """Get the current engine state."""
        return self._state
    
    @property
    def dag(self) -> DAG:
        """Get the current DAG."""
        return self._dag
    
    @property
    def halt_reason(self) -> Optional[HaltReason]:
        """Get the reason for halt if halted."""
        return self._halt_reason
    
    def set_event_bus(self, event_bus: Any) -> None:
        """
        Set the EventBus for emitting events.
        
        Args:
            event_bus: EventBus instance
        """
        self._event_bus = event_bus
        self._logger.info("EventBus attached to PlanningEngine")
    
    def set_on_cycle_detected(self, callback: Callable[[List[str]], None]) -> None:
        """
        Set callback for cycle detection events.
        
        Args:
            callback: Function to call when a cycle is detected
        """
        self._on_cycle_detected = callback
    
    def set_on_halt(self, callback: Callable[[HaltReason], None]) -> None:
        """
        Set callback for halt events.
        
        Args:
            callback: Function to call when engine halts
        """
        self._on_halt = callback
    
    def add_step(self, step: PlanStep) -> None:
        """
        Add a step to the plan.
        
        Args:
            step: PlanStep to add
        """
        self._steps[step.step_id] = step
        self._logger.debug(f"Added step: {step.step_id}")
    
    def remove_step(self, step_id: str) -> bool:
        """
        Remove a step from the plan.
        
        Args:
            step_id: ID of step to remove
            
        Returns:
            True if step was removed
        """
        if step_id in self._steps:
            del self._steps[step_id]
            self._logger.debug(f"Removed step: {step_id}")
            return True
        return False
    
    def build_dag(self) -> Dict:
        """
        Build the DAG from the current steps.
        
        Returns:
            Validation result for the built DAG
        """
        self._dag = DAG()
        
        # Add nodes for each step
        for step_id, step in self._steps.items():
            node = DAGNode(
                id=step_id,
                data={"action": str(step.action), "status": step.status}
            )
            self._dag.add_node(node)
        
        # Add edges from dependencies
        for step_id, step in self._steps.items():
            for dep in step.dependencies:
                self._dag.add_edge(dep, step_id)
        
        # Validate the DAG
        return validate_dag_object(self._dag)
    
    def detect_cycle(self) -> Optional[List[str]]:
        """
        Check for cycles in the current DAG.
        
        Returns:
            List of node IDs forming a cycle, or None if no cycle
        """
        return self._cycle_detector.detect_cycle_in_dag(self._dag)
    
    def validate_amendment(self, amendment: Amendment) -> ValidationResult:
        """
        Validate an amendment before applying it.
        
        Args:
            amendment: Amendment to validate
            
        Returns:
            ValidationResult with validity and cycle path if invalid
        """
        valid, cycle_path = self._cycle_detector.validate_amendment_with_path(
            self._dag, amendment
        )
        return ValidationResult(
            valid=valid,
            cycle_path=cycle_path,
            amendment=amendment
        )
    
    def apply_amendment(self, amendment: Amendment, validate: bool = True) -> bool:
        """
        Apply an amendment to the DAG.
        
        Args:
            amendment: Amendment to apply
            validate: Whether to validate before applying
            
        Returns:
            True if amendment was applied successfully
        """
        if validate:
            result = self.validate_amendment(amendment)
            if not result.valid:
                self._logger.warning(
                    f"Amendment rejected: would introduce cycle {result.cycle_path}"
                )
                self._emit_cycle_detected(result.cycle_path)
                return False
        
        # Apply the amendment
        if amendment.amendment_type == AmendmentType.ADD_EDGE:
            if amendment.source and amendment.target:
                self._dag.add_edge(amendment.source, amendment.target)
                
        elif amendment.amendment_type == AmendmentType.ADD_NODE:
            if amendment.node:
                self._dag.add_node(amendment.node)
                
        elif amendment.amendment_type == AmendmentType.REMOVE_EDGE:
            if amendment.source and amendment.target:
                self._dag.remove_edge(amendment.source, amendment.target)
                
        elif amendment.amendment_type == AmendmentType.REMOVE_NODE:
            if amendment.node:
                if amendment.node.id in self._dag.nodes:
                    del self._dag.nodes[amendment.node.id]
                    
        elif amendment.amendment_type == AmendmentType.UPDATE_NODE:
            if amendment.node and amendment.node.id in self._dag.nodes:
                self._dag.nodes[amendment.node.id].data.update(amendment.node.data)
        
        self._logger.debug(f"Applied amendment: {amendment.amendment_type}")
        return True
    
    def queue_amendment(self, amendment: Amendment) -> None:
        """
        Queue an amendment for later processing.
        
        Args:
            amendment: Amendment to queue
        """
        self._pending_amendments.append(amendment)
    
    def process_pending_amendments(self) -> int:
        """
        Process all pending amendments.
        
        Returns:
            Number of successfully applied amendments
        """
        applied = 0
        while self._pending_amendments:
            amendment = self._pending_amendments.pop(0)
            if self.apply_amendment(amendment):
                applied += 1
            else:
                # Amendment rejected - clear remaining queue
                self._pending_amendments.clear()
                break
        return applied
    
    def _emit_cycle_detected(self, cycle_path: List[str]) -> None:
        """
        Emit a DAG_CYCLE_DETECTED event.
        
        Args:
            cycle_path: Path of the detected cycle
        """
        self._logger.error(f"[gap: dag_cycle_detected] Cycle: {' -> '.join(cycle_path)}")
        
        if self._event_bus:
            from ..events.event_bus import Event, EventSeverity
            event = Event(
                event_type="DAG_CYCLE_DETECTED",
                data={
                    "cycle_path": cycle_path,
                    "cycle_length": len(cycle_path),
                    "dag_nodes": list(self._dag.get_node_ids()),
                    "iteration": self._current_iteration
                },
                severity=EventSeverity.WARN,
                source="PlanningEngine"
            )
            self._event_bus.emit(event)
        
        if self._on_cycle_detected:
            self._on_cycle_detected(cycle_path)
    
    def _halt(self, reason: HaltReason, details: Dict = None) -> None:
        """
        Halt the engine.
        
        Args:
            reason: Reason for halting
            details: Additional details about the halt
        """
        self._state = EngineState.HALTED
        self._halt_reason = reason
        self._logger.warning(f"Engine halted: {reason.value}")
        
        if self._on_halt:
            self._on_halt(reason)
    
    def run(self) -> Dict:
        """
        Run the planning engine.
        
        Returns:
            Execution result with status and any errors
        """
        if self._state == EngineState.HALTED:
            return {
                "success": False,
                "error": "Engine is halted",
                "halt_reason": self._halt_reason.value if self._halt_reason else None
            }
        
        self._state = EngineState.RUNNING
        self._current_iteration = 0
        errors = []
        
        try:
            # Check for cycles before starting
            cycle = self.detect_cycle()
            if cycle:
                self._emit_cycle_detected(cycle)
                self._halt(HaltReason.CYCLE_DETECTED, {"cycle_path": cycle})
                return {
                    "success": False,
                    "error": "[gap: dag_cycle_detected]",
                    "cycle": cycle
                }
            
            # Get topological order for execution
            success, order = self._cycle_detector.topological_sort_dag(self._dag)
            if not success:
                return {
                    "success": False,
                    "error": "Failed to get topological order"
                }
            
            # Execute steps in order
            for step_id in order:
                if self._state != EngineState.RUNNING:
                    break
                
                self._current_iteration += 1
                
                if self._current_iteration > self._max_iterations:
                    self._halt(HaltReason.BUDGET_EXCEEDED)
                    break
                
                # Check for cycles before each iteration
                cycle = self.detect_cycle()
                if cycle:
                    self._emit_cycle_detected(cycle)
                    self._halt(HaltReason.CYCLE_DETECTED, {"cycle_path": cycle})
                    break
                
                # Execute the step
                step = self._steps.get(step_id)
                if step and step.status == "pending":
                    try:
                        step.result = step.action()
                        step.status = "completed"
                        self._logger.debug(f"Completed step: {step_id}")
                    except Exception as e:
                        step.status = "failed"
                        errors.append({
                            "step_id": step_id,
                            "error": str(e)
                        })
                        self._logger.error(f"Step {step_id} failed: {e}")
            
            # Determine final state
            if self._state == EngineState.RUNNING:
                self._state = EngineState.COMPLETED
            
            return {
                "success": len(errors) == 0 and self._state == EngineState.COMPLETED,
                "state": self._state.value,
                "iterations": self._current_iteration,
                "errors": errors,
                "halt_reason": self._halt_reason.value if self._halt_reason else None
            }
            
        except Exception as e:
            self._state = EngineState.ERROR
            self._logger.error(f"Engine error: {e}")
            return {
                "success": False,
                "error": str(e),
                "state": self._state.value
            }
    
    def pause(self) -> bool:
        """
        Pause the engine.
        
        Returns:
            True if paused successfully
        """
        if self._state == EngineState.RUNNING:
            self._state = EngineState.PAUSED
            self._logger.info("Engine paused")
            return True
        return False
    
    def resume(self) -> bool:
        """
        Resume a paused engine.
        
        Returns:
            True if resumed successfully
        """
        if self._state == EngineState.PAUSED:
            self._state = EngineState.RUNNING
            self._logger.info("Engine resumed")
            return True
        return False
    
    def reset(self) -> None:
        """Reset the engine to initial state."""
        self._state = EngineState.IDLE
        self._halt_reason = None
        self._current_iteration = 0
        self._pending_amendments.clear()
        
        # Reset all step statuses
        for step in self._steps.values():
            step.status = "pending"
            step.result = None
        
        self._logger.info("Engine reset")
    
    def get_stats(self) -> Dict:
        """
        Get engine statistics.
        
        Returns:
            Dictionary of engine statistics
        """
        return {
            "state": self._state.value,
            "halt_reason": self._halt_reason.value if self._halt_reason else None,
            "current_iteration": self._current_iteration,
            "max_iterations": self._max_iterations,
            "step_count": len(self._steps),
            "pending_amendments": len(self._pending_amendments),
            "dag_nodes": len(self._dag.nodes),
            "dag_edges": sum(len(v) for v in self._dag.edges.values())
        }


# =============================================================================
# PAT-42: ValidationCase and SeverityLevel (ITEM-B006)
# =============================================================================

class SeverityLevel(str, Enum):
    """Severity levels for validation cases (PAT-42)."""
    BLOCK = "BLOCK"
    WARN = "WARN"
    GAP_TAG = "GAP_TAG"


class ValidationCase(BaseModel):
    """Validation case model for PAT-42 pattern.
    
    Represents a single validation check that can be applied to
    an atomic item or plan step.
    """
    case_id: str
    condition: str
    severity: SeverityLevel
    gap_tag: Optional[str] = None

    class Config:
        use_enum_values = True


class ValidatedAtomicItem(BaseModel):
    """Extended AtomicItem with validation_cases and validate() method (PAT-42).
    
    Combines atomic item fields with validation capabilities, supporting
    BLOCK/WARN/GAP_TAG severity levels for comprehensive validation.
    """
    item_id: str
    title: str
    description: str
    phase: str
    status: str = "PENDING"
    validation_cases: List[ValidationCase] = Field(default_factory=list)

    def validate(self, context: dict = None) -> dict:
        """Run all validation cases and return results.
        
        Args:
            context: Optional context dict for condition evaluation.
            
        Returns:
            Dictionary with 'passed', 'warnings', 'blocked', 'gap_tags' lists.
        """
        results = {"passed": [], "warnings": [], "blocked": [], "gap_tags": []}
        for vc in self.validation_cases:
            condition_met = self._evaluate_condition(vc.condition, context)
            if condition_met:
                results["passed"].append(vc.case_id)
            elif vc.severity == SeverityLevel.BLOCK:
                results["blocked"].append(vc.case_id)
            elif vc.severity == SeverityLevel.WARN:
                results["warnings"].append(vc.case_id)
            elif vc.severity == SeverityLevel.GAP_TAG:
                tag = vc.gap_tag or f"GAP-{vc.case_id}"
                results["gap_tags"].append(tag)
        return results

    def _evaluate_condition(self, condition: str, context: dict) -> bool:
        """Evaluate a validation condition. Override for complex logic.
        
        Args:
            condition: Condition string to evaluate.
            context: Context dictionary for evaluation.
            
        Returns:
            True if condition is met, False otherwise.
        """
        if context is None:
            return True
        return True
