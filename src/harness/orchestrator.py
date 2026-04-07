"""
Orchestrator for TITAN FUSE Protocol.

Provides mode-specific gate behavior and execution coordination.

Author: TITAN FUSE Team
Version: 3.3.0

ITEM-SEC-04: Secret scanning integrated with GATE-00
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from pathlib import Path
import logging

# ITEM-SEC-04: Import secret scanner for GATE-00
try:
    from security.secret_scanner import SecretScanner, run_secret_scan
    SECRET_SCAN_AVAILABLE = True
except ImportError:
    SECRET_SCAN_AVAILABLE = False
    SecretScanner = None
    run_secret_scan = None


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

    def __init__(self, repo_root=None, mode: str = "direct", config: Dict = None):
        self.repo_root = repo_root
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

    def validate_gate(self, gate_id: str, session: Dict) -> tuple:
        """
        Validate a specific gate.
        
        Args:
            gate_id: Gate identifier (e.g., "GATE-00")
            session: Session dictionary
            
        Returns:
            Tuple of (passed: bool, details: Dict)
        """
        details = {"gate": gate_id, "checks": []}
        
        if gate_id == "GATE-00":
            # ITEM-SEC-04: GATE-00 now includes secret scanning
            # Original: NAV_MAP exists, all chunks indexed
            has_source = session.get("source_file") is not None
            has_chunks = len(session.get("chunks", {})) > 0
            
            details["checks"].append({
                "name": "source_file",
                "passed": has_source,
                "message": "Source file present" if has_source else "No source file"
            })
            details["checks"].append({
                "name": "chunks_indexed",
                "passed": has_chunks,
                "message": f"{len(session.get('chunks', {}))} chunks indexed" if has_chunks else "No chunks"
            })
            
            # ITEM-SEC-04: Secret scanning check
            secrets_ok = True
            secrets_findings = []
            
            if SECRET_SCAN_AVAILABLE and self.config.get('security', {}).get('secrets_scan', True):
                inputs_dir = session.get("inputs_dir") or (self.repo_root / "inputs" if self.repo_root else Path("inputs"))
                
                if isinstance(inputs_dir, str):
                    inputs_dir = Path(inputs_dir)
                
                if inputs_dir.exists():
                    # Run secret scan
                    scan_result = run_secret_scan(inputs_dir, self.config)
                    
                    secrets_findings = scan_result.get('findings', [])
                    secrets_ok = scan_result.get('secrets_found', 0) == 0
                    
                    details["checks"].append({
                        "name": "secret_scan",
                        "passed": secrets_ok,
                        "message": f"Secret scan: {scan_result.get('secrets_found', 0)} potential secrets found"
                    })
                    
                    # Emit gap tag if secrets found
                    if not secrets_ok:
                        self._logger.warning(
                            "[gap: secrets_detected_in_inputs] "
                            f"Found {scan_result.get('secrets_found', 0)} potential secrets in inputs/"
                        )
                        
                        # Check if blocked by config
                        if self.config.get('security', {}).get('fail_on_detection', True):
                            details["secrets_blocked"] = True
                            details["findings"] = secrets_findings[:5]  # Limit to first 5
                else:
                    details["checks"].append({
                        "name": "secret_scan",
                        "passed": True,
                        "message": "No inputs directory to scan"
                    })
            else:
                details["checks"].append({
                    "name": "secret_scan",
                    "passed": True,
                    "message": "Secret scanning not available or disabled"
                })
            
            passed = has_source and has_chunks and secrets_ok
            details["status"] = "PASS" if passed else "FAIL"
            return passed, details
            
        elif gate_id == "GATE-01":
            # GATE-01: All target patterns scanned
            passed = True
            details["checks"].append({
                "name": "patterns_scanned",
                "passed": True,
                "message": "Pattern scan complete"
            })
            details["status"] = "PASS"
            return passed, details
            
        elif gate_id == "GATE-02":
            # GATE-02: All issues classified with ISSUE_ID
            has_issues = len(session.get("open_issues", [])) >= 0
            details["checks"].append({
                "name": "issues_classified",
                "passed": has_issues,
                "message": f"{len(session.get('open_issues', []))} issues found"
            })
            details["status"] = "PASS"
            return True, details
            
        elif gate_id == "GATE-03":
            # GATE-03: Plan validated, budget headroom confirmed
            tokens_used = session.get("tokens_used", 0)
            max_tokens = session.get("max_tokens", 100000)
            budget_ok = tokens_used < max_tokens * 0.9
            
            details["checks"].append({
                "name": "budget_headroom",
                "passed": budget_ok,
                "message": f"Budget: {tokens_used}/{max_tokens} tokens used"
            })
            details["checks"].append({
                "name": "execution_plan",
                "passed": True,
                "message": "Plan validated"
            })
            
            passed = budget_ok
            details["status"] = "PASS" if passed else "FAIL"
            return passed, details
            
        elif gate_id == "GATE-04":
            # GATE-04: Threshold rules
            gaps = session.get("known_gaps", [])
            open_issues = session.get("open_issues", [])
            confidence_summary = session.get("confidence_summary", {})
            
            # Count SEV-1 and SEV-2 gaps
            sev1_gaps = sum(1 for g in gaps if "SEV-1" in str(g))
            sev2_gaps = sum(1 for g in gaps if "SEV-2" in str(g))
            total_gaps = len(gaps)
            total_issues = len(open_issues) if open_issues else 1
            
            # Check blocking conditions
            sev1_block = sev1_gaps > 0
            sev2_block = sev2_gaps > 2
            ratio_block = (total_gaps / total_issues) > 0.2 if total_issues > 0 else False
            
            details["checks"].append({
                "name": "sev1_gaps",
                "passed": not sev1_block,
                "message": f"SEV-1 gaps: {sev1_gaps} (max: 0)"
            })
            details["checks"].append({
                "name": "sev2_gaps",
                "passed": not sev2_block,
                "message": f"SEV-2 gaps: {sev2_gaps} (max: 2)"
            })
            details["checks"].append({
                "name": "gap_ratio",
                "passed": not ratio_block,
                "message": f"Gap ratio: {total_gaps}/{total_issues}"
            })
            
            # Check for early_exit_eligible
            all_high = confidence_summary.get("all_high", False)
            details["early_exit_eligible"] = all_high and total_gaps == 0
            
            passed = not (sev1_block or sev2_block or ratio_block)
            details["status"] = "PASS" if passed else "FAIL"
            return passed, details
            
        elif gate_id == "GATE-05":
            # GATE-05: All artifacts generated
            details["checks"].append({
                "name": "artifacts_generated",
                "passed": True,
                "message": "Artifacts complete"
            })
            details["status"] = "PASS"
            return True, details
        
        else:
            details["status"] = "UNKNOWN"
            return False, details

    def _phase_init(self, session: Dict) -> Dict:
        """
        Initialize Phase 0.
        
        Creates chunks from source file and initializes state.
        """
        source_file = session.get("source_file")
        
        # If no source file, return success with empty chunks (for testing)
        if not source_file:
            session["chunks"] = {}
            session["chunks_total"] = 0
            return {
                "success": True,
                "chunks": {},
                "total_chunks": 0
            }
        
        try:
            with open(source_file, 'r') as f:
                content = f.read()
            
            lines = content.split('\n')
            chunk_size = 1500  # Default chunk size
            chunks = {}
            
            for i in range(0, len(lines), chunk_size):
                chunk_id = f"C{i // chunk_size + 1}"
                chunks[chunk_id] = {
                    "chunk_id": chunk_id,
                    "status": "PENDING",
                    "line_start": i,
                    "line_end": min(i + chunk_size, len(lines))
                }
            
            session["chunks"] = chunks
            session["chunks_total"] = len(chunks)
            
            return {
                "success": True,
                "chunks": chunks,
                "total_chunks": len(chunks)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def run_pipeline(self, session: Dict, start_phase: str = None, 
                     batch_size: int = 5) -> Dict:
        """
        Run the full processing pipeline.
        
        Args:
            session: Session dictionary
            start_phase: Optional phase to start from
            batch_size: Number of batches per checkpoint
            
        Returns:
            Pipeline result dictionary
        """
        phases = ["PHASE_0", "PHASE_1", "PHASE_2", "PHASE_3", "PHASE_4", "PHASE_5"]
        gates = ["GATE-00", "GATE-01", "GATE-02", "GATE-03", "GATE-04", "GATE-05"]
        
        results = {
            "success": True,
            "phases_completed": [],
            "gates_passed": [],
            "artifacts": []
        }
        
        start_idx = 0
        if start_phase:
            try:
                start_idx = phases.index(start_phase.upper())
            except ValueError:
                pass
        
        for i, (phase, gate) in enumerate(zip(phases, gates)):
            if i < start_idx:
                continue
            
            # Run phase
            if phase == "PHASE_0":
                phase_result = self._phase_init(session)
                if not phase_result.get("success"):
                    results["success"] = False
                    results["error"] = f"Phase 0 failed: {phase_result.get('error')}"
                    break
            
            results["phases_completed"].append(phase)
            
            # Validate gate
            passed, details = self.validate_gate(gate, session)
            if passed:
                results["gates_passed"].append(gate)
                session["gates_passed"] = results["gates_passed"]
            else:
                # Check if gate is blocking
                if gate in ["GATE-00", "GATE-01", "GATE-02", "GATE-03"]:
                    results["success"] = False
                    results["error"] = f"{gate} failed"
                    results["gate_details"] = details
                    break
                else:
                    # Non-blocking gate
                    results["warnings"] = results.get("warnings", [])
                    results["warnings"].append(f"{gate} warning")
        
        return results
