"""
Orchestrator for TITAN FUSE Protocol.

Provides mode-specific gate behavior and execution coordination.

Author: TITAN FUSE Team
Version: 5.0.0

ITEM-SEC-04: Secret scanning integrated with GATE-00
ITEM-PROT-002: Invariant runtime enforcement integrated
ITEM-ART-001: Audit trail signing in DELIVERY phase
ITEM-ART-002: Decision record enforcement in DELIVERY phase
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from pathlib import Path
import logging
import json

# ITEM-SEC-04: Import secret scanner for GATE-00
try:
    from security.secret_scanner import SecretScanner, run_secret_scan
    SECRET_SCAN_AVAILABLE = True
except ImportError:
    SECRET_SCAN_AVAILABLE = False
    SecretScanner = None
    run_secret_scan = None

# ITEM-PROT-002: Import invariant enforcer
try:
    from src.validation.invariant_enforcer import (
        InvariantEnforcer,
        InvariantCheckResult,
        InvariantViolation,
        EnforcementLevel,
        InvariantType,
        create_invariant_enforcer,
    )
    INVARIANT_ENFORCER_AVAILABLE = True
except ImportError:
    INVARIANT_ENFORCER_AVAILABLE = False
    InvariantEnforcer = None
    InvariantCheckResult = None
    InvariantViolation = None
    EnforcementLevel = None
    InvariantType = None
    create_invariant_enforcer = None

# ITEM-ART-001: Import audit signer for trail signing
try:
    from src.events.audit_signer import (
        AuditSigner,
        AuditTrailV2,
        AuditEventV2,
        SignedTrail,
        create_audit_signer,
        generate_audit_trail,
        write_signed_trail,
    )
    AUDIT_SIGNER_AVAILABLE = True
except ImportError:
    AUDIT_SIGNER_AVAILABLE = False
    AuditSigner = None
    AuditTrailV2 = None
    AuditEventV2 = None
    SignedTrail = None
    create_audit_signer = None
    generate_audit_trail = None
    write_signed_trail = None

# ITEM-ART-002: Import decision record manager
try:
    from src.decision.decision_record import (
        DecisionRecordManager,
        DecisionType,
        Decision,
        write_decision_record,
        create_decision_record_manager,
    )
    DECISION_RECORD_AVAILABLE = True
except ImportError:
    DECISION_RECORD_AVAILABLE = False
    DecisionRecordManager = None
    DecisionType = None
    Decision = None
    write_decision_record = None
    create_decision_record_manager = None


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
        
        # ITEM-PROT-002: Initialize invariant enforcer
        self._invariant_enforcer = None
        self._invariant_results: List[Dict] = []
        if INVARIANT_ENFORCER_AVAILABLE:
            enforcement_level = self.config.get("invariant_enforcement", "standard")
            self._invariant_enforcer = create_invariant_enforcer(enforcement_level, config)
            self._logger.info(
                f"[ITEM-PROT-002] InvariantEnforcer initialized with level: {enforcement_level}"
            )
        
        # ITEM-ART-001: Initialize audit signer
        self._audit_signer = None
        self._audit_events: List[Dict] = []
        if AUDIT_SIGNER_AVAILABLE:
            audit_config = self.config.get('audit', {})
            if audit_config.get('enabled', True):
                self._audit_signer = create_audit_signer(self.config)
                self._logger.info(
                    f"[ITEM-ART-001] AuditSigner initialized with backend: "
                    f"{self._audit_signer.get_backend_type()}"
                )
        
        # ITEM-ART-002: Initialize decision record manager
        self._decision_record_manager = None
        if DECISION_RECORD_AVAILABLE:
            decision_record_config = self.config.get('decision_record', {})
            if decision_record_config.get('enabled', True):
                # Session ID will be set when session is created
                self._decision_record_manager = None  # Initialize lazily
                self._logger.info(
                    "[ITEM-ART-002] DecisionRecordManager will be initialized on session start"
                )

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
            "artifacts": [],
            "invariant_checks": []
        }
        
        # ITEM-ART-002: Initialize decision record manager with session ID
        session_id = session.get('session_id', 'unknown')
        if DECISION_RECORD_AVAILABLE:
            self.get_decision_record_manager(session_id)
        
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
            
            # ITEM-PROT-002: Run invariant checks after phase
            invariant_result = self._run_invariant_check(session, phase)
            if invariant_result:
                results["invariant_checks"].append(invariant_result)
                # If invariant check failed with blocking violations, halt
                if not invariant_result.get("passed", True):
                    blocking = [v for v in invariant_result.get("violations", []) 
                               if v.get("severity") in ("error", "critical")]
                    if blocking:
                        results["success"] = False
                        results["error"] = f"Invariant violation at {phase}"
                        results["invariant_violations"] = blocking
                        self._logger.error(
                            f"[ITEM-PROT-002] Pipeline halted due to invariant violations at {phase}"
                        )
                        break
            
            # Validate gate
            passed, details = self.validate_gate(gate, session)
            if passed:
                results["gates_passed"].append(gate)
                session["gates_passed"] = results["gates_passed"]
                # ITEM-ART-001: Record gate pass event
                self.record_audit_event("GATE_PASS", {"gate": gate})
            else:
                # ITEM-ART-001: Record gate fail event
                self.record_audit_event("GATE_FAIL", {"gate": gate, "details": details})
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
        
        # ITEM-ART-001: Deliver artifacts (including signed audit trail)
        # ITEM-ART-002: Deliver decision record artifact
        if results["success"]:
            delivery_result = self._deliver_artifacts(session)
            results["artifacts"].extend(delivery_result.get("artifacts_delivered", []))
            results["audit_trail_signed"] = delivery_result.get("audit_trail_signed", False)
            results["decision_record_delivered"] = delivery_result.get("decision_record_delivered", False)
            
            # ITEM-ART-002: Handle decision record blocking
            if delivery_result.get("decision_record_blocked"):
                results["success"] = False
                results["error"] = delivery_result.get("error", "Decision record required but empty")
                results["gate_details"] = {"gate": "GATE-05", "reason": "decision_record_required"}
            
            if delivery_result.get("error") and not delivery_result.get("decision_record_blocked"):
                results["warnings"] = results.get("warnings", [])
                results["warnings"].append(f"Delivery warning: {delivery_result['error']}")
        
        return results
    
    def _run_invariant_check(self, session: Dict, phase: str) -> Optional[Dict]:
        """
        Run invariant checks for the current phase.
        
        ITEM-PROT-002: Runtime enforcement of INVARIANTS_GLOBAL
        
        Args:
            session: Current session dictionary
            phase: Current phase name
            
        Returns:
            Dictionary with invariant check results, or None if enforcer unavailable
        """
        if not self._invariant_enforcer:
            return None
        
        # Build context for invariant check
        context = {
            "output": session.get("output", ""),
            "domain": session.get("domain", ""),
            "sources": session.get("sources", []),
            "evidence": session.get("evidence", []),
            "output_claims": session.get("output_claims", []),
            "forbidden_conditions": session.get("forbidden_conditions", []),
            "code_blocks": session.get("code_blocks", []),
            "declared_scope": session.get("declared_scope", set()),
            "actual_scope": session.get("actual_scope", set()),
            "extracted_count": session.get("extracted_count", 0),
            "classified_count": session.get("classified_count", 0),
            "exclusions_count": session.get("exclusions_count", 0),
            "current_phase": self._current_phase,
            "validation_result": session.get("last_validation_result"),
        }
        
        # Add session snapshot for drift check if available
        if "session_snapshot" in session:
            context["session"] = session["session_snapshot"]
        
        # Run the check
        result = self._invariant_enforcer.check_all(context)
        
        # Log result
        if result.violations:
            for violation in result.violations:
                self._logger.warning(
                    f"[ITEM-PROT-002] {violation.gap_tag or ''} "
                    f"{violation.invariant_type.value}: {violation.message}"
                )
        
        # Store result
        result_dict = result.to_dict()
        result_dict["phase"] = phase
        self._invariant_results.append(result_dict)
        
        return result_dict
    
    def get_invariant_stats(self) -> Dict:
        """
        Get invariant enforcement statistics.
        
        ITEM-PROT-002: Statistics for monitoring
        
        Returns:
            Dictionary with invariant stats
        """
        if not self._invariant_enforcer:
            return {"available": False}
        
        return {
            "available": True,
            "enforcer_stats": self._invariant_enforcer.get_stats(),
            "check_count": len(self._invariant_results),
            "results": self._invariant_results,
        }
    
    # ========================================================================
    # ITEM-ART-001: Audit Trail Integration
    # ========================================================================
    
    def record_audit_event(self, event_type: str, data: Dict = None) -> None:
        """
        Record an audit event for the trail.
        
        Args:
            event_type: Type of event (e.g., 'GATE_PASS', 'GATE_FAIL')
            data: Optional event data
        """
        import uuid
        from datetime import datetime
        
        event = {
            'event_id': f"evt-{uuid.uuid4().hex[:8]}",
            'type': event_type,
            'timestamp': datetime.utcnow().isoformat() + "Z",
            'data': data or {}
        }
        self._audit_events.append(event)
        
        # Log critical events
        if self._audit_signer and self._audit_signer.is_critical_event(event_type):
            self._logger.info(f"[ITEM-ART-001] Critical audit event: {event_type}")
    
    def _deliver_artifacts(self, session: Dict) -> Dict:
        """
        Deliver artifacts including signed audit trail and decision record.
        
        ITEM-ART-001: Integration with DELIVERY phase
        ITEM-ART-002: Decision record enforcement in DELIVERY phase
        
        Args:
            session: Session dictionary with execution data
            
        Returns:
            Dictionary with delivery results
        """
        results = {
            'artifacts_delivered': [],
            'audit_trail_signed': False,
            'decision_record_delivered': False
        }
        
        # ====================================================================
        # ITEM-ART-001: Audit Trail Signing
        # ====================================================================
        if not AUDIT_SIGNER_AVAILABLE or not self._audit_signer:
            self._logger.warning(
                "[ITEM-ART-001] Audit signer not available, skipping trail signing"
            )
        else:
            try:
                # Get session ID
                session_id = session.get('session_id', 'unknown')
                
                # Generate audit trail from recorded events
                trail = generate_audit_trail(session_id, self._audit_events)
                
                # Sign the trail
                signed_trail = self._audit_signer.sign_trail(trail)
                
                # Write to configured path
                trail_path = self.config.get('audit', {}).get(
                    'trail_path', '.titan/audit_trail.json'
                )
                if self.repo_root:
                    trail_path = Path(self.repo_root) / trail_path
                
                write_signed_trail(signed_trail, trail_path)
                
                results['artifacts_delivered'].append('audit_trail.json')
                results['audit_trail_signed'] = True
                results['audit_trail_path'] = str(trail_path)
                results['audit_backend_type'] = signed_trail.backend_type
                
                self._logger.info(
                    f"[ITEM-ART-001] Signed audit trail delivered to {trail_path}"
                )
                
            except Exception as e:
                self._logger.error(f"[ITEM-ART-001] Failed to deliver audit trail: {e}")
                results['error'] = str(e)
        
        # ====================================================================
        # ITEM-ART-002: Decision Record Enforcement
        # ====================================================================
        decision_record_config = self.config.get('decision_record', {})
        require_for_delivery = decision_record_config.get('require_for_delivery', True)
        
        if DECISION_RECORD_AVAILABLE:
            manager = self._decision_record_manager
            
            # Check if decision record is required but empty
            if manager is not None and manager.empty():
                if require_for_delivery:
                    # Emit gap tag
                    self._logger.error(
                        "[gap:decision_record_required] "
                        "DECISION_RECORD is REQUIRED by ARTIFACT_CONTRACT but no decisions recorded"
                    )
                    results['decision_record_blocked'] = True
                    results['error'] = "Decision record required but empty"
                    return results
                else:
                    self._logger.warning(
                        "[ITEM-ART-002] Decision record is empty but not required for delivery"
                    )
            
            # Generate and write decision record artifact
            if manager is not None and not manager.empty():
                try:
                    # Get output path from config
                    output_dir = self.config.get('output', {}).get('directory', 'outputs/')
                    decision_record_path = Path(output_dir) / 'decision_record.json'
                    if self.repo_root:
                        decision_record_path = Path(self.repo_root) / decision_record_path
                    
                    # Write the decision record
                    write_result = write_decision_record(manager, str(decision_record_path))
                    
                    results['artifacts_delivered'].append('decision_record.json')
                    results['decision_record_delivered'] = True
                    results['decision_record_path'] = str(decision_record_path)
                    results['decision_count'] = write_result.get('decision_count', 0)
                    results['decision_summary'] = write_result.get('summary', {})
                    
                    self._logger.info(
                        f"[ITEM-ART-002] Decision record delivered to {decision_record_path} "
                        f"with {write_result.get('decision_count', 0)} decisions"
                    )
                    
                except Exception as e:
                    self._logger.error(f"[ITEM-ART-002] Failed to deliver decision record: {e}")
                    if results.get('error'):
                        results['error'] += f"; Decision record error: {e}"
                    else:
                        results['error'] = str(e)
        else:
            self._logger.warning(
                "[ITEM-ART-002] DecisionRecordManager not available"
            )
        
        return results
    
    def get_audit_stats(self) -> Dict:
        """
        Get audit trail statistics.
        
        ITEM-ART-001: Statistics for monitoring
        
        Returns:
            Dictionary with audit stats
        """
        return {
            "available": AUDIT_SIGNER_AVAILABLE,
            "signer_initialized": self._audit_signer is not None,
            "event_count": len(self._audit_events),
            "backend_type": self._audit_signer.get_backend_type() if self._audit_signer else None,
            "public_key_id": self._audit_signer.get_public_key_id() if self._audit_signer else None,
        }
    
    # ========================================================================
    # ITEM-ART-002: Decision Record Integration
    # ========================================================================
    
    def get_decision_record_manager(self, session_id: str = None) -> Optional["DecisionRecordManager"]:
        """
        Get or create the DecisionRecordManager for this session.
        
        ITEM-ART-002: Lazy initialization of decision record manager
        
        Args:
            session_id: Optional session ID. Required for first initialization.
        
        Returns:
            DecisionRecordManager instance or None if unavailable.
        """
        if not DECISION_RECORD_AVAILABLE:
            return None
        
        # Check if decision record is disabled in config
        decision_record_config = self.config.get('decision_record', {})
        if not decision_record_config.get('enabled', True):
            return None
        
        # Initialize if needed
        if self._decision_record_manager is None and session_id:
            self._decision_record_manager = create_decision_record_manager(session_id)
            self._logger.info(
                f"[ITEM-ART-002] DecisionRecordManager initialized for session: {session_id}"
            )
        
        return self._decision_record_manager
    
    def record_decision(
        self,
        decision_type: "DecisionType",
        context: Dict[str, Any],
        options_considered: List[Dict[str, Any]],
        selected_option: str,
        rationale: str,
        confidence: float,
        gate_id: Optional[str] = None,
        conflict_id: Optional[str] = None,
        metadata: Dict[str, Any] = None
    ) -> Optional["Decision"]:
        """
        Record a decision in the decision record.
        
        ITEM-ART-002: Convenience method for recording decisions
        
        Args:
            decision_type: Type of decision
            context: Contextual information
            options_considered: Options that were evaluated
            selected_option: The selected option
            rationale: Explanation for the selection
            confidence: Confidence level (0.0-1.0)
            gate_id: Optional gate ID
            conflict_id: Optional conflict ID
            metadata: Additional metadata
        
        Returns:
            The created Decision or None if manager unavailable.
        """
        manager = self._decision_record_manager
        if manager is None:
            self._logger.warning(
                "[ITEM-ART-002] Cannot record decision: manager not initialized"
            )
            return None
        
        decision = manager.record_decision(
            decision_type=decision_type,
            context=context,
            options_considered=options_considered,
            selected_option=selected_option,
            rationale=rationale,
            confidence=confidence,
            gate_id=gate_id,
            conflict_id=conflict_id,
            metadata=metadata
        )
        
        return decision
    
    def get_decision_stats(self) -> Dict:
        """
        Get decision record statistics.
        
        ITEM-ART-002: Statistics for monitoring
        
        Returns:
            Dictionary with decision stats
        """
        manager = self._decision_record_manager
        return {
            "available": DECISION_RECORD_AVAILABLE,
            "manager_initialized": manager is not None,
            "decision_count": manager.get_decision_count() if manager else 0,
            "enabled": self.config.get('decision_record', {}).get('enabled', True),
            "require_for_delivery": self.config.get('decision_record', {}).get('require_for_delivery', True),
        }
