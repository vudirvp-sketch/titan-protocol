"""
State Transition Validator for TITAN FUSE Protocol.

ITEM-OBS-06: Event-State Transition Contract

This module validates that events produce valid state transitions,
ensuring that the event system maintains a consistent state machine.

Author: TITAN FUSE Team
Version: 3.3.0
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Set
from copy import deepcopy


class TransitionResult(Enum):
    """Result of a state transition validation."""
    VALID = "valid"
    INVALID = "invalid"
    WARNING = "warning"
    UNKNOWN_EVENT = "unknown_event"


@dataclass
class StateMutation:
    """Represents a single state mutation."""
    path: str  # e.g., "gates.{gate_id}.status"
    value: Any
    resolved_path: str = ""  # Path with variables resolved


@dataclass
class TransitionValidation:
    """Result of validating a transition."""
    result: TransitionResult
    event_type: str
    state_mutations: List[StateMutation] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    gap_tags: List[str] = field(default_factory=list)


@dataclass
class StateSnapshot:
    """A snapshot of the current state for validation."""
    session: Dict[str, Any] = field(default_factory=dict)
    phases: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    chunks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    gates: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    issues: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    cursor: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    inventory: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session": self.session,
            "phases": self.phases,
            "chunks": self.chunks,
            "gates": self.gates,
            "issues": self.issues,
            "cursor": self.cursor,
            "metrics": self.metrics,
            "inventory": self.inventory,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StateSnapshot':
        """Create from dictionary."""
        return cls(
            session=data.get("session", {}),
            phases=data.get("phases", {}),
            chunks=data.get("chunks", {}),
            gates=data.get("gates", {}),
            issues=data.get("issues", {}),
            cursor=data.get("cursor", {}),
            metrics=data.get("metrics", {}),
            inventory=data.get("inventory", {}),
        )


class StateTransitionValidator:
    """
    Validates state transitions for events.

    ITEM-OBS-06: Implements the event-state transition contract.
    Ensures that events produce valid state transitions based on
    the event_state_map.json schema.
    """

    def __init__(self, config: Dict[str, Any] = None, state_map_path: str = None):
        """
        Initialize the state transition validator.

        Args:
            config: Configuration dictionary
            state_map_path: Path to event_state_map.json
        """
        self.config = config or {}
        self._logger = logging.getLogger(__name__)

        # Load state map
        self._state_map = self._load_state_map(state_map_path)

        # Current state snapshot
        self._state = StateSnapshot()

        # Strict mode configuration
        self._strict_mode = self.config.get("strict_mode", True)

        # Event history for replay
        self._event_history: List[Dict[str, Any]] = []

        # Validation callbacks
        self._on_invalid_transition: Optional[Callable] = None

    def _load_state_map(self, path: str = None) -> Dict[str, Any]:
        """Load the event state map from JSON file."""
        if path is None:
            # Default path
            path = str(Path(__file__).parent.parent.parent / "schemas" / "event_state_map.json")

        try:
            with open(path, 'r') as f:
                data = json.load(f)
                self._logger.info(f"Loaded event state map from {path}")
                return data
        except FileNotFoundError:
            self._logger.warning(f"Event state map not found at {path}, using defaults")
            return {"event_state_map": {}, "state_machine": {}}
        except json.JSONDecodeError as e:
            self._logger.error(f"Invalid JSON in state map: {e}")
            return {"event_state_map": {}, "state_machine": {}}

    def set_state(self, state: StateSnapshot) -> None:
        """Set the current state snapshot."""
        self._state = state

    def get_state(self) -> StateSnapshot:
        """Get the current state snapshot."""
        return self._state

    def set_on_invalid_transition(self, callback: Callable) -> None:
        """Set callback for invalid transitions."""
        self._on_invalid_transition = callback

    def validate_transition(self, event_type: str, event_data: Dict[str, Any]) -> TransitionValidation:
        """
        Validate that an event can produce a valid state transition.

        Args:
            event_type: The type of event
            event_data: The event payload

        Returns:
            TransitionValidation with result and details
        """
        event_map = self._state_map.get("event_state_map", {})

        if event_type not in event_map:
            return TransitionValidation(
                result=TransitionResult.UNKNOWN_EVENT,
                event_type=event_type,
                warnings=[f"Event type '{event_type}' not in state map"]
            )

        event_def = event_map[event_type]
        errors = []
        warnings = []
        gap_tags = []

        # Check valid pre-states
        valid_pre_states = event_def.get("valid_pre_states", [])
        invalid_pre_states = event_def.get("invalid_pre_states", [])

        current_session_status = self._state.session.get("status", "initialized")

        # Check if current state is valid for this event
        if invalid_pre_states and current_session_status in invalid_pre_states:
            errors.append(
                f"Event '{event_type}' cannot occur in session state '{current_session_status}'"
            )

        if valid_pre_states and "*" not in valid_pre_states:
            if current_session_status not in valid_pre_states:
                warnings.append(
                    f"Event '{event_type}' expected session state in {valid_pre_states}, "
                    f"but got '{current_session_status}'"
                )

        # Build state mutations
        mutations = self._build_mutations(event_def, event_data)

        # Collect gap tags if event emits gaps
        if event_def.get("emits_gaps", False):
            gap_tags = event_def.get("gap_tags", [])

        # Determine result
        if errors:
            result = TransitionResult.INVALID
        elif warnings:
            result = TransitionResult.WARNING
        else:
            result = TransitionResult.VALID

        return TransitionValidation(
            result=result,
            event_type=event_type,
            state_mutations=mutations,
            errors=errors,
            warnings=warnings,
            gap_tags=gap_tags
        )

    def apply_transition(self, event_type: str, event_data: Dict[str, Any]) -> TransitionValidation:
        """
        Validate and apply a state transition.

        Args:
            event_type: The type of event
            event_data: The event payload

        Returns:
            TransitionValidation with result
        """
        validation = self.validate_transition(event_type, event_data)

        if validation.result == TransitionResult.INVALID:
            if self._on_invalid_transition:
                self._on_invalid_transition(event_type, event_data, validation)
            return validation

        # Apply mutations
        for mutation in validation.state_mutations:
            self._apply_mutation(mutation)

        # Record event in history
        self._event_history.append({
            "event_type": event_type,
            "event_data": event_data,
            "validation_result": validation.result.value
        })

        return validation

    def _build_mutations(self, event_def: Dict[str, Any], event_data: Dict[str, Any]) -> List[StateMutation]:
        """Build list of state mutations from event definition."""
        mutations = []
        mutation_defs = event_def.get("state_mutations", [])

        for mutation_str in mutation_defs:
            # Parse mutation string like "gates.{gate_id}.status = PASS"
            if " = " not in mutation_str:
                continue

            path_template, value_str = mutation_str.split(" = ", 1)

            # Resolve template variables
            resolved_path = self._resolve_path(path_template, event_data)

            # Parse value
            value = self._parse_value(value_str, event_data)

            mutations.append(StateMutation(
                path=path_template,
                value=value,
                resolved_path=resolved_path
            ))

        return mutations

    def _resolve_path(self, path_template: str, event_data: Dict[str, Any]) -> str:
        """Resolve template variables in path."""
        import re

        # Find all {variable} patterns
        pattern = r'\{(\w+)\}'

        def replace_var(match):
            var_name = match.group(1)
            # Try to get from event_data
            if var_name in event_data:
                return str(event_data[var_name])
            return f"{{{var_name}}}"  # Keep as-is if not found

        return re.sub(pattern, replace_var, path_template)

    def _parse_value(self, value_str: str, event_data: Dict[str, Any]) -> Any:
        """Parse a value string, resolving variables."""
        # Check if it's a variable reference
        if value_str.startswith("{") and value_str.endswith("}"):
            var_name = value_str[1:-1]
            return event_data.get(var_name, value_str)

        # Check if it's a special value
        if value_str == "timestamp":
            from datetime import datetime
            return datetime.utcnow().isoformat() + "Z"
        if value_str == "true":
            return True
        if value_str == "false":
            return False

        # Try to parse as number
        try:
            if "." in value_str:
                return float(value_str)
            return int(value_str)
        except ValueError:
            pass

        # Return as string
        return value_str

    def _apply_mutation(self, mutation: StateMutation) -> None:
        """Apply a state mutation to the current state."""
        path_parts = mutation.resolved_path.split(".")

        if not path_parts:
            return

        # Navigate to the target location
        target = self._state.to_dict()
        for part in path_parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]

        # Set the value
        final_key = path_parts[-1]
        target[final_key] = mutation.value

        # Update state
        self._state = StateSnapshot.from_dict(
            self._state.to_dict()  # Get the updated dict
        )

    def get_valid_events(self, current_state: str = None) -> List[str]:
        """
        Get list of events valid for the current state.

        Args:
            current_state: Optional state override

        Returns:
            List of valid event types
        """
        if current_state is None:
            current_state = self._state.session.get("status", "initialized")

        valid_events = []
        event_map = self._state_map.get("event_state_map", {})

        for event_type, event_def in event_map.items():
            valid_pre_states = event_def.get("valid_pre_states", [])
            invalid_pre_states = event_def.get("invalid_pre_states", [])

            # Check if current state is allowed
            if invalid_pre_states and current_state in invalid_pre_states:
                continue

            if not valid_pre_states or "*" in valid_pre_states:
                valid_events.append(event_type)
            elif current_state in valid_pre_states:
                valid_events.append(event_type)

        return valid_events

    def replay_events(self, events: List[Dict[str, Any]]) -> StateSnapshot:
        """
        Replay a list of events to rebuild state.

        Args:
            events: List of events to replay

        Returns:
            Final state snapshot after replay
        """
        # Reset to initial state
        self._state = StateSnapshot()

        for event in events:
            event_type = event.get("event_type")
            event_data = event.get("data", {})
            self.apply_transition(event_type, event_data)

        return self._state

    def get_event_history(self) -> List[Dict[str, Any]]:
        """Get the event history."""
        return self._event_history.copy()

    def get_stats(self) -> Dict[str, Any]:
        """Get validator statistics."""
        return {
            "events_processed": len(self._event_history),
            "current_session_status": self._state.session.get("status", "initialized"),
            "phases_completed": self._state.session.get("phases_completed", 0),
            "chunks_completed": self._state.session.get("chunks_completed", 0),
            "strict_mode": self._strict_mode,
            "state_map_loaded": bool(self._state_map.get("event_state_map")),
        }


def validate_event_transition(
    event_type: str,
    event_data: Dict[str, Any],
    current_state: Dict[str, Any],
    state_map_path: str = None
) -> TransitionValidation:
    """
    Convenience function to validate a single event transition.

    Args:
        event_type: The event type
        event_data: The event payload
        current_state: Current state dictionary
        state_map_path: Optional path to state map

    Returns:
        TransitionValidation result
    """
    validator = StateTransitionValidator(state_map_path=state_map_path)
    validator.set_state(StateSnapshot.from_dict(current_state))
    return validator.validate_transition(event_type, event_data)


def get_state_transition_map() -> Dict[str, Any]:
    """
    Get the event-state transition map.

    Returns:
        The event state map dictionary
    """
    validator = StateTransitionValidator()
    return validator._state_map
