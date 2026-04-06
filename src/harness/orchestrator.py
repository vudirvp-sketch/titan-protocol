"""
Orchestrator for TITAN FUSE Protocol.

Provides mode-specific gate behavior and execution coordination.

Author: TITAN FUSE Team
Version: 3.2.3
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from enum import Enum
import logging


class ExecutionMode(Enum):
    """Execution modes for TITAN FUSE Protocol."""
    DIRECT = "direct"          # Standard execution
    AUTO = "auto"              # Automated with stricter gates
    MANUAL = "manual"          # Human-in-loop with advisory gates
    INTERACTIVE = "interactive"  # Interactive with human checkpoints


@dataclass
class ModeConfig:
    """Configuration for a specific execution mode."""
    eval_veto_sensitivity: str = "NORMAL"
    gate_03_mode: str = "BLOCKING"
    gate_04_mode: str = "BLOCKING"
    gate_04_threshold: float = 0.75
    requires_human_ack: bool = False
    auto_rollback_enabled: bool = True
    checkpoint_frequency: str = "normal"  # "low", "normal", "high"

    def to_dict(self) -> Dict:
        return {
            "eval_veto_sensitivity": self.eval_veto_sensitivity,
            "gate_03_mode": self.gate_03_mode,
            "gate_04_mode": self.gate_04_mode,
            "gate_04_threshold": self.gate_04_threshold,
            "requires_human_ack": self.requires_human_ack,
            "auto_rollback_enabled": self.auto_rollback_enabled,
            "checkpoint_frequency": self.checkpoint_frequency
        }


class ModeAdapter:
    """
    Apply mode-specific gate behavior modifications.

    Different execution modes have different gate behaviors:
    - DIRECT: Standard blocking gates
    - AUTO: Stricter GATE-04 threshold, higher eval_veto sensitivity
    - MANUAL: GATE-03/04 demoted to ADVISORY, requires human acknowledgment
    - INTERACTIVE: ADVISORY gates with checkpoints at each phase
    """

    MODE_PRESETS = {
        "direct": ModeConfig(
            eval_veto_sensitivity="NORMAL",
            gate_03_mode="BLOCKING",
            gate_04_mode="BLOCKING",
            gate_04_threshold=0.75,
            requires_human_ack=False,
            auto_rollback_enabled=True,
            checkpoint_frequency="normal"
        ),
        "auto": ModeConfig(
            eval_veto_sensitivity="HIGH",
            gate_03_mode="BLOCKING",
            gate_04_mode="BLOCKING",
            gate_04_threshold=0.85,  # Stricter
            requires_human_ack=False,
            auto_rollback_enabled=True,
            checkpoint_frequency="high"
        ),
        "manual": ModeConfig(
            eval_veto_sensitivity="NORMAL",
            gate_03_mode="ADVISORY",  # Demoted to advisory
            gate_04_mode="ADVISORY",  # Demoted to advisory
            gate_04_threshold=0.75,
            requires_human_ack=True,
            auto_rollback_enabled=False,
            checkpoint_frequency="high"
        ),
        "interactive": ModeConfig(
            eval_veto_sensitivity="NORMAL",
            gate_03_mode="ADVISORY",
            gate_04_mode="ADVISORY",
            gate_04_threshold=0.70,  # More lenient
            requires_human_ack=True,
            auto_rollback_enabled=True,
            checkpoint_frequency="high"
        )
    }

    def __init__(self, mode: str = "direct", custom_config: ModeConfig = None):
        """
        Initialize mode adapter.

        Args:
            mode: Execution mode name
            custom_config: Optional custom mode configuration
        """
        self.mode = mode
        self._logger = logging.getLogger(__name__)

        if custom_config:
            self.config = custom_config
        else:
            self.config = self.MODE_PRESETS.get(mode, self.MODE_PRESETS["direct"])

        self._logger.info(f"ModeAdapter initialized with mode: {mode}")

    def apply_to_gate(self, gate_id: str, base_result: Dict) -> Dict:
        """
        Apply mode-specific modifications to gate result.

        Args:
            gate_id: Gate identifier (e.g., "GATE-03")
            base_result: Base gate result dictionary

        Returns:
            Modified gate result with mode-specific behavior
        """
        result = base_result.copy()

        # Apply GATE-03 modifications
        if gate_id == "GATE-03" and self.config.gate_03_mode == "ADVISORY":
            result["mode"] = "ADVISORY"
            if result.get("status") == "FAIL":
                result["status"] = "WARN"
                result["advisory_note"] = "GATE-03 demoted to ADVISORY in current mode"
                result["requires_acknowledgment"] = self.config.requires_human_ack
                self._logger.info(f"GATE-03 demoted to ADVISORY: {result.get('reason', 'unknown')}")

        # Apply GATE-04 modifications
        elif gate_id == "GATE-04":
            if self.config.gate_04_mode == "ADVISORY":
                result["mode"] = "ADVISORY"
                result["requires_acknowledgment"] = self.config.requires_human_ack

            if self.config.gate_04_threshold != 0.75:
                result["threshold"] = self.config.gate_04_threshold
                result["threshold_note"] = f"Threshold adjusted to {self.config.gate_04_threshold} for {self.mode} mode"

            if result.get("status") == "FAIL" and self.config.gate_04_mode == "ADVISORY":
                result["status"] = "WARN"
                result["advisory_note"] = "GATE-04 demoted to ADVISORY in current mode"

        # Apply eval_veto sensitivity
        if self.config.eval_veto_sensitivity == "HIGH":
            result["eval_veto_sensitivity"] = "HIGH"
            # Higher sensitivity means more cautious evaluation
            if "confidence" in result and result["confidence"] < 0.9:
                result["eval_veto_triggered"] = True

        return result

    def get_modifications(self) -> Dict[str, Any]:
        """Get all mode modifications as dict."""
        return {
            "mode": self.mode,
            **self.config.to_dict()
        }

    def should_checkpoint(self, phase: int) -> bool:
        """Determine if checkpoint should be created at this phase."""
        if self.config.checkpoint_frequency == "high":
            return True
        elif self.config.checkpoint_frequency == "low":
            return phase in [0, 3, 5]
        else:  # normal
            return phase in [0, 2, 4, 5]

    def should_auto_rollback(self) -> bool:
        """Check if auto-rollback is enabled for this mode."""
        return self.config.auto_rollback_enabled

    def requires_acknowledgment(self) -> bool:
        """Check if human acknowledgment is required."""
        return self.config.requires_human_ack

    @classmethod
    def register_mode(cls, mode_name: str, config: ModeConfig) -> None:
        """Register a custom mode."""
        cls.MODE_PRESETS[mode_name] = config

    @classmethod
    def list_modes(cls) -> List[str]:
        """List available modes."""
        return list(cls.MODE_PRESETS.keys())


class Orchestrator:
    """
    Main orchestrator for TITAN FUSE Protocol execution.

    Coordinates phases, gates, and state transitions.
    """

    def __init__(self, mode: str = "direct", config: Dict = None):
        self.mode_adapter = ModeAdapter(mode)
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
        self._current_phase = 0
        self._state = "INIT"

    def get_current_state(self) -> Dict:
        """Get current orchestration state."""
        return {
            "state": self._state,
            "current_phase": self._current_phase,
            "mode": self.mode_adapter.get_modifications()
        }

    def transition_to_phase(self, phase: int) -> Dict:
        """Transition to a new phase."""
        old_phase = self._current_phase
        self._current_phase = phase
        self._logger.info(f"Phase transition: {old_phase} -> {phase}")
        return {
            "success": True,
            "from_phase": old_phase,
            "to_phase": phase
        }

    def process_gate_result(self, gate_id: str, result: Dict) -> Dict:
        """Process gate result with mode-specific modifications."""
        return self.mode_adapter.apply_to_gate(gate_id, result)
