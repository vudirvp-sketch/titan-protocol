import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any


class PipelineCheckpoint:
    """Manages inter-phase checkpointing for ContentPipeline."""

    def __init__(self, checkpoint_dir: str = ".ai/checkpoints"):
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(checkpoint_dir, exist_ok=True)

    def save(self, phase: str, state: Dict[str, Any], pipeline_id: str = "default") -> str:
        """Save pipeline state after a phase completes."""
        checkpoint = {
            "pipeline_id": pipeline_id,
            "phase": phase,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "state": state,
        }
        checkpoint_str = json.dumps(checkpoint, sort_keys=True, default=str)
        checksum = hashlib.sha256(checkpoint_str.encode()).hexdigest()
        checkpoint["checksum"] = checksum

        filepath = os.path.join(
            self.checkpoint_dir, f"checkpoint_{pipeline_id}_{phase}.json"
        )
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, default=str)
        return filepath

    def load(self, phase: str, pipeline_id: str = "default") -> Optional[Dict[str, Any]]:
        """Load pipeline state for a given phase."""
        filepath = os.path.join(
            self.checkpoint_dir, f"checkpoint_{pipeline_id}_{phase}.json"
        )
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            checkpoint = json.load(f)

        # Verify integrity
        stored_checksum = checkpoint.pop("checksum", "")
        checkpoint_str = json.dumps(checkpoint, sort_keys=True, default=str)
        computed_checksum = hashlib.sha256(checkpoint_str.encode()).hexdigest()
        if stored_checksum != computed_checksum:
            raise ValueError(
                f"Checkpoint integrity check failed for {phase}: "
                f"expected {stored_checksum}, got {computed_checksum}"
            )
        return checkpoint

    def get_latest_phase(self, pipeline_id: str = "default") -> Optional[str]:
        """Get the latest completed phase for resumption."""
        phase_order = ["INIT", "DISCOVER", "ANALYZE", "PLAN", "EXEC", "DELIVER"]
        latest = None
        for phase in phase_order:
            if self.load(phase, pipeline_id) is not None:
                latest = phase
        return latest

    def clean(self, pipeline_id: str = "default") -> None:
        """Remove all checkpoints for a pipeline."""
        for fname in os.listdir(self.checkpoint_dir):
            if fname.startswith(f"checkpoint_{pipeline_id}_"):
                os.remove(os.path.join(self.checkpoint_dir, fname))
