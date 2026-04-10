from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any


class PipelinePhase(Enum):
    """Six-phase pipeline execution order."""
    INIT = "INIT"
    DISCOVER = "DISCOVER"
    ANALYZE = "ANALYZE"
    PLAN = "PLAN"
    EXEC = "EXEC"
    DELIVER = "DELIVER"


@dataclass
class PhaseResult:
    """Result of a pipeline phase execution."""
    phase: PipelinePhase
    success: bool
    artifacts: Dict[str, Any]
    checksum: str
    timestamp: str
    gate_passed: bool
    duration_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase.value,
            "success": self.success,
            "artifacts": self.artifacts,
            "checksum": self.checksum,
            "timestamp": self.timestamp,
            "gate_passed": self.gate_passed,
            "duration_ms": self.duration_ms,
        }
