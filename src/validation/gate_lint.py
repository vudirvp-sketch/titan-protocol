"""
Gate Lint Checks for TITAN FUSE Protocol.

ITEM-GATE-01: Gate-04 Early Exit Fix
Provides lint validation for gate configuration and behavior.

This module ensures:
- Confidence advisory is not misapplied to SEV-1/SEV-2 gaps
- Early exit logic is correctly positioned
- Gate evaluation follows proper sequence

Author: TITAN FUSE Team
Version: 3.3.0
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
import logging
import re


class LintSeverity(Enum):
    """Severity of lint findings."""
    ERROR = "ERROR"      # Must be fixed
    WARNING = "WARNING"  # Should be fixed
    INFO = "INFO"        # Informational


@dataclass
class LintFinding:
    """A lint finding."""
    code: str
    severity: LintSeverity
    message: str
    location: str = ""
    suggestion: str = ""
    gap_tag: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "location": self.location,
            "suggestion": self.suggestion,
            "gap_tag": self.gap_tag
        }


@dataclass
class LintResult:
    """Result of lint check run."""
    passed: bool
    findings: List[LintFinding] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "findings": [f.to_dict() for f in self.findings],
            "error_count": len([f for f in self.findings if f.severity == LintSeverity.ERROR]),
            "warning_count": len([f for f in self.findings if f.severity == LintSeverity.WARNING])
        }


class GateLinter:
    """
    Linter for gate configuration and behavior.
    
    ITEM-GATE-01: Validates that:
    1. Confidence advisory is not applied to SEV-1/SEV-2 gaps
    2. Early exit logic is positioned before Phase 4
    3. Gate evaluation follows proper sequence
    
    Usage:
        linter = GateLinter()
        result = linter.lint_gate_config(config, gaps, confidence)
        
        if not result.passed:
            for finding in result.findings:
                print(f"{finding.code}: {finding.message}")
    """
    
    # Lint check codes
    CODES = {
        "GATE001": "Confidence advisory misapplied to SEV-1 gaps",
        "GATE002": "Confidence advisory misapplied to SEV-2 gaps above threshold",
        "GATE003": "Early exit logic misplaced (after Phase 4)",
        "GATE004": "Gate evaluation sequence incorrect",
        "GATE005": "Missing confidence check before SEV-4 processing",
        "GATE006": "Advisory pass without HIGH confidence",
        "GATE007": "Gate04 confidence_override enabled in deterministic mode",
    }
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize gate linter.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
    
    def lint_gate_config(self, gaps: List[Dict[str, Any]], 
                         confidence: str = "MEDIUM",
                         phase: int = 0) -> LintResult:
        """
        Run all lint checks on gate configuration.
        
        Args:
            gaps: List of gap dictionaries
            confidence: Current confidence level
            phase: Current processing phase
            
        Returns:
            LintResult with findings
        """
        findings: List[LintFinding] = []
        
        # Check for SEV-1 advisory misapplication
        sev1_findings = self._check_sev1_advisory(gaps, confidence)
        findings.extend(sev1_findings)
        
        # Check for SEV-2 threshold advisory misapplication
        sev2_findings = self._check_sev2_threshold(gaps, confidence)
        findings.extend(sev2_findings)
        
        # Check early exit positioning
        early_exit_findings = self._check_early_exit_position(gaps, confidence, phase)
        findings.extend(early_exit_findings)
        
        # Check confidence override in deterministic mode
        mode_findings = self._check_mode_compatibility()
        findings.extend(mode_findings)
        
        passed = not any(f.severity == LintSeverity.ERROR for f in findings)
        
        return LintResult(passed=passed, findings=findings)
    
    def _check_sev1_advisory(self, gaps: List[Dict[str, Any]], 
                              confidence: str) -> List[LintFinding]:
        """
        Check if confidence advisory is being applied to SEV-1 gaps.
        
        ITEM-GATE-01: SEV-1 gaps should NEVER be overridden by confidence.
        """
        findings = []
        
        sev1_gaps = [g for g in gaps 
                     if g.get("severity") == "SEV-1" and not g.get("resolved", False)]
        
        if sev1_gaps and confidence == "HIGH":
            findings.append(LintFinding(
                code="GATE001",
                severity=LintSeverity.ERROR,
                message=f"Confidence advisory cannot apply to {len(sev1_gaps)} SEV-1 gap(s). "
                        f"SEV-1 gaps always block regardless of confidence level.",
                location="gate_evaluation",
                suggestion="Resolve all SEV-1 gaps before proceeding. "
                          "Confidence override cannot bypass critical gaps.",
                gap_tag="[gap: confidence_advisory_misapplied]"
            ))
            
            self._logger.error(
                f"[gap: confidence_advisory_misapplied] "
                f"Attempted to apply confidence advisory to SEV-1 gaps: "
                f"{[g.get('gap_id') or g.get('id') for g in sev1_gaps]}"
            )
        
        return findings
    
    def _check_sev2_threshold(self, gaps: List[Dict[str, Any]], 
                               confidence: str) -> List[LintFinding]:
        """
        Check if confidence advisory is being applied to SEV-2 gaps above threshold.
        
        ITEM-GATE-01: SEV-2 gaps above threshold cannot be overridden.
        """
        findings = []
        
        max_sev2 = self.config.get("gate04", {}).get("max_sev2_gaps", 0)
        sev2_gaps = [g for g in gaps 
                     if g.get("severity") == "SEV-2" and not g.get("resolved", False)]
        
        if len(sev2_gaps) > max_sev2 and confidence == "HIGH":
            findings.append(LintFinding(
                code="GATE002",
                severity=LintSeverity.ERROR,
                message=f"Confidence advisory cannot apply to {len(sev2_gaps)} SEV-2 gap(s). "
                        f"Maximum allowed: {max_sev2}. "
                        f"SEV-2 gaps above threshold always block.",
                location="gate_evaluation",
                suggestion=f"Reduce unresolved SEV-2 gaps to {max_sev2} or fewer, "
                          f"or increase gate04.max_sev2_gaps threshold.",
                gap_tag="[gap: confidence_advisory_misapplied]"
            ))
            
            self._logger.error(
                f"[gap: confidence_advisory_misapplied] "
                f"Attempted to apply confidence advisory to SEV-2 gaps above threshold: "
                f"{len(sev2_gaps)} > {max_sev2}"
            )
        
        return findings
    
    def _check_early_exit_position(self, gaps: List[Dict[str, Any]], 
                                    confidence: str,
                                    phase: int) -> List[LintFinding]:
        """
        Check if early exit logic is positioned before Phase 4.
        
        ITEM-GATE-01: Confidence check should occur BEFORE SEV-4 batch processing.
        """
        findings = []
        
        # If we're in Phase 4 or later, check if early exit was considered
        if phase >= 4:
            # Check if there's a flag indicating early exit was evaluated
            gate04_config = self.config.get("gate04", {})
            allow_advisory = gate04_config.get("allow_advisory_pass", True)
            
            # If HIGH confidence and no critical gaps, but we're in Phase 4,
            # early exit might have been missed
            sev1_gaps = [g for g in gaps 
                        if g.get("severity") == "SEV-1" and not g.get("resolved", False)]
            sev2_gaps = [g for g in gaps 
                        if g.get("severity") == "SEV-2" and not g.get("resolved", False)]
            max_sev2 = gate04_config.get("max_sev2_gaps", 0)
            
            if (confidence == "HIGH" and allow_advisory and 
                not sev1_gaps and len(sev2_gaps) <= max_sev2):
                findings.append(LintFinding(
                    code="GATE003",
                    severity=LintSeverity.WARNING,
                    message="Early exit may have been missed. "
                            "HIGH confidence with no critical gaps should skip SEV-4 processing.",
                    location="phase_4_entry",
                    suggestion="Ensure confidence check occurs before Phase 4 batch processing. "
                              "Add early exit logic in orchestrator before entering Phase 4.",
                    gap_tag="[gap: gate04_early_exit_misplaced]"
                ))
                
                self._logger.warning(
                    "[gap: gate04_early_exit_misplaced] "
                    "HIGH confidence with no critical gaps but reached Phase 4"
                )
        
        return findings
    
    def _check_mode_compatibility(self) -> List[LintFinding]:
        """
        Check if gate configuration is compatible with execution mode.
        
        Validates that confidence_override is not enabled in deterministic mode.
        """
        findings = []
        
        mode = self.config.get("mode", {}).get("current", "direct")
        confidence_override = self.config.get("gate04_confidence_override", False)
        
        if mode == "deterministic" and confidence_override:
            findings.append(LintFinding(
                code="GATE007",
                severity=LintSeverity.ERROR,
                message="gate04_confidence_override is enabled in deterministic mode. "
                        "This violates determinism requirements.",
                location="config.yaml",
                suggestion="Set gate04_confidence_override: false for deterministic mode, "
                          "or switch to a less strict mode.",
                gap_tag="[gap: deterministic_mode_confidence_override]"
            ))
            
            self._logger.error(
                "[gap: deterministic_mode_confidence_override] "
                "Confidence override enabled in deterministic mode"
            )
        
        return findings
    
    def lint_gate_sequence(self, sequence: List[str]) -> LintResult:
        """
        Validate gate evaluation sequence.
        
        ITEM-GATE-04: Ensure pre-exec and post-exec gates are properly ordered.
        
        Args:
            sequence: List of gate names in evaluation order
            
        Returns:
            LintResult with findings
        """
        findings = []
        
        # Expected pre-exec gates
        expected_pre_exec = {"Policy Check", "Access Control", "Resource Availability"}
        # Expected post-exec gates
        expected_post_exec = {"Output Structure", "Invariant Validation", "Change Verification"}
        
        pre_exec_found = []
        post_exec_found = []
        
        for i, gate in enumerate(sequence):
            if gate in expected_pre_exec:
                pre_exec_found.append((i, gate))
            if gate in expected_post_exec:
                post_exec_found.append((i, gate))
        
        # Check that all pre-exec gates come before post-exec gates
        if pre_exec_found and post_exec_found:
            last_pre_exec_idx = max(idx for idx, _ in pre_exec_found)
            first_post_exec_idx = min(idx for idx, _ in post_exec_found)
            
            if last_pre_exec_idx > first_post_exec_idx:
                findings.append(LintFinding(
                    code="GATE004",
                    severity=LintSeverity.ERROR,
                    message="Gate evaluation sequence incorrect: "
                            "pre-exec gates found after post-exec gates.",
                    location="gate_sequence",
                    suggestion="Ensure all pre-exec gates (Policy Check, Access Control, "
                              "Resource Availability) run before post-exec gates.",
                    gap_tag="[gap: gate_sequence_invalid]"
                ))
        
        # Check for missing essential gates
        missing_pre_exec = expected_pre_exec - {g for _, g in pre_exec_found}
        if missing_pre_exec:
            findings.append(LintFinding(
                code="GATE004",
                severity=LintSeverity.WARNING,
                message=f"Missing pre-exec gates: {missing_pre_exec}",
                location="gate_sequence",
                suggestion="Add missing pre-exec gates for comprehensive validation."
            ))
        
        passed = not any(f.severity == LintSeverity.ERROR for f in findings)
        
        return LintResult(passed=passed, findings=findings)
    
    def check_confidence_before_phase4(self, context: Dict[str, Any]) -> Optional[str]:
        """
        Check if confidence evaluation happened before Phase 4.
        
        This is a runtime check to be called at Phase 4 entry.
        
        Args:
            context: Execution context with confidence and gaps info
            
        Returns:
            Gap tag if early exit should have occurred, None otherwise
        """
        confidence = context.get("confidence", "MEDIUM")
        gaps = context.get("gaps", [])
        early_exit_evaluated = context.get("early_exit_evaluated", False)
        
        if not early_exit_evaluated and confidence == "HIGH":
            # Check if we should have early exited
            sev1_gaps = [g for g in gaps 
                        if g.get("severity") == "SEV-1" and not g.get("resolved", False)]
            sev2_gaps = [g for g in gaps 
                        if g.get("severity") == "SEV-2" and not g.get("resolved", False)]
            max_sev2 = self.config.get("gate04", {}).get("max_sev2_gaps", 0)
            
            if not sev1_gaps and len(sev2_gaps) <= max_sev2:
                self._logger.error(
                    "[gap: gate04_early_exit_misplaced] "
                    "Confidence check not performed before Phase 4"
                )
                return "[gap: gate04_early_exit_misplaced] Confidence check not performed before Phase 4"
        
        return None


def lint_gate_configuration(config: Dict[str, Any], 
                            gaps: List[Dict[str, Any]],
                            confidence: str = "MEDIUM") -> LintResult:
    """
    Convenience function to run gate lint checks.
    
    Args:
        config: Configuration dictionary
        gaps: List of gap dictionaries
        confidence: Current confidence level
        
    Returns:
        LintResult with findings
    """
    linter = GateLinter(config)
    return linter.lint_gate_config(gaps, confidence)


def check_early_exit_required(config: Dict[str, Any],
                               gaps: List[Dict[str, Any]],
                               confidence: str) -> bool:
    """
    Check if early exit from Gate-04 should occur.
    
    ITEM-GATE-01: Determines if HIGH confidence + no critical gaps
    should skip SEV-4 batch processing.
    
    Args:
        config: Configuration dictionary
        gaps: List of gap dictionaries
        confidence: Current confidence level
        
    Returns:
        True if early exit should occur (skip SEV-4 processing)
    """
    if confidence != "HIGH":
        return False
    
    gate04_config = config.get("gate04", {})
    allow_advisory = gate04_config.get("allow_advisory_pass", True)
    
    if not allow_advisory:
        return False
    
    # Check for blocking gaps
    sev1_gaps = [g for g in gaps 
                if g.get("severity") == "SEV-1" and not g.get("resolved", False)]
    sev2_gaps = [g for g in gaps 
                if g.get("severity") == "SEV-2" and not g.get("resolved", False)]
    max_sev2 = gate04_config.get("max_sev2_gaps", 0)
    
    # Early exit if no critical gaps
    if not sev1_gaps and len(sev2_gaps) <= max_sev2:
        return True
    
    return False
