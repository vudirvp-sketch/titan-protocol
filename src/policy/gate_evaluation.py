"""
Gate-04 Evaluation for TITAN FUSE Protocol.

ITEM-ARCH-04: Gate-04 SEV-1 Override Fix

Implements proper severity-based gate evaluation where:
- SEV-1 gaps ALWAYS block, regardless of confidence
- SEV-2 gaps block if count exceeds threshold
- SEV-3/SEV-4 gaps can be overridden with HIGH confidence

This module ensures that confidence advisory cannot override
critical severity gaps.

Author: TITAN FUSE Team
Version: 3.3.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import logging


class GateResult(Enum):
    """Result of gate evaluation."""
    PASS = "PASS"
    FAIL = "FAIL"
    ADVISORY_PASS = "ADVISORY_PASS"  # Passed with warnings
    PENDING = "PENDING"


class Severity(Enum):
    """Gap severity levels."""
    SEV_1 = "SEV-1"  # Critical - always blocks
    SEV_2 = "SEV-2"  # High - blocks if above threshold
    SEV_3 = "SEV-3"  # Medium - advisory pass possible
    SEV_4 = "SEV-4"  # Low - advisory pass possible


@dataclass
class Gap:
    """
    Represents a gap that may affect gate evaluation.
    
    Attributes:
        gap_id: Unique gap identifier
        severity: Severity level (SEV-1 to SEV-4)
        description: Human-readable description
        resolved: Whether the gap has been resolved
        metadata: Additional metadata
    """
    gap_id: str
    severity: Severity
    description: str = ""
    resolved: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "severity": self.severity.value,
            "description": self.description,
            "resolved": self.resolved,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Gap':
        return cls(
            gap_id=data["gap_id"],
            severity=Severity(data["severity"]),
            description=data.get("description", ""),
            resolved=data.get("resolved", False),
            metadata=data.get("metadata", {})
        )


@dataclass
class Gate04Result:
    """Result of Gate-04 evaluation."""
    result: GateResult
    reason: str
    sev1_gaps: List[Gap] = field(default_factory=list)
    sev2_gaps: List[Gap] = field(default_factory=list)
    sev3_gaps: List[Gap] = field(default_factory=list)
    sev4_gaps: List[Gap] = field(default_factory=list)
    confidence: str = "UNKNOWN"
    advisory_warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "result": self.result.value,
            "reason": self.reason,
            "sev1_count": len(self.sev1_gaps),
            "sev2_count": len(self.sev2_gaps),
            "sev3_count": len(self.sev3_gaps),
            "sev4_count": len(self.sev4_gaps),
            "confidence": self.confidence,
            "advisory_warnings": self.advisory_warnings
        }


class Gate04Evaluator:
    """
    Gate-04 evaluator with proper severity-based blocking.
    
    ITEM-ARCH-04 Implementation:
    
    Rules:
    1. SEV-1: ALWAYS BLOCK if any unresolved gaps exist.
       Confidence CANNOT override SEV-1 gaps.
       
    2. SEV-2: ALWAYS BLOCK if count exceeds threshold.
       Confidence CANNOT override SEV-2 threshold.
       
    3. SEV-3/SEV-4: HIGH confidence allows ADVISORY_PASS.
       This is a warning-only pass with logged gaps.
    
    Configuration:
        - gate04_confidence_override: Enable/disable confidence override (default: false)
        - gate04.max_sev2_gaps: Maximum allowed SEV-2 gaps before blocking (default: 0)
    
    Usage:
        evaluator = Gate04Evaluator(config)
        result = evaluator.evaluate(gaps, confidence="HIGH")
        
        if result.result == GateResult.FAIL:
            print(f"Gate blocked: {result.reason}")
    """
    
    # Default configuration
    DEFAULT_CONFIG = {
        "gate04_confidence_override": False,  # Disabled by default
        "gate04": {
            "max_sev2_gaps": 0,  # Any unresolved SEV-2 blocks
            "allow_advisory_pass": True  # Allow advisory pass for SEV-3/4
        }
    }
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize Gate-04 evaluator.
        
        Args:
            config: Configuration dictionary
        """
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self._logger = logging.getLogger(__name__)
    
    def evaluate(self, gaps: List[Gap], confidence: str = "MEDIUM") -> Gate04Result:
        """
        Evaluate Gate-04 with proper severity handling.
        
        Args:
            gaps: List of gaps to evaluate
            confidence: Confidence level ("HIGH", "MEDIUM", "LOW")
            
        Returns:
            Gate04Result with evaluation outcome
        """
        # Categorize gaps by severity
        sev1_gaps = [g for g in gaps if g.severity == Severity.SEV_1 and not g.resolved]
        sev2_gaps = [g for g in gaps if g.severity == Severity.SEV_2 and not g.resolved]
        sev3_gaps = [g for g in gaps if g.severity == Severity.SEV_3 and not g.resolved]
        sev4_gaps = [g for g in gaps if g.severity == Severity.SEV_4 and not g.resolved]
        
        result = Gate04Result(
            result=GateResult.PASS,
            reason="",
            sev1_gaps=sev1_gaps,
            sev2_gaps=sev2_gaps,
            sev3_gaps=sev3_gaps,
            sev4_gaps=sev4_gaps,
            confidence=confidence
        )
        
        # RULE 1: SEV-1 gaps ALWAYS block
        if sev1_gaps:
            result.result = GateResult.FAIL
            result.reason = f"Blocked by {len(sev1_gaps)} unresolved SEV-1 gap(s). " \
                           "SEV-1 gaps cannot be overridden by confidence."
            
            self._logger.error(
                f"[gap: gate04_sev1_block] {result.reason} "
                f"Gap IDs: {[g.gap_id for g in sev1_gaps]}"
            )
            return result
        
        # RULE 2: SEV-2 gaps block if above threshold
        max_sev2 = self.config.get("gate04", {}).get("max_sev2_gaps", 0)
        
        if len(sev2_gaps) > max_sev2:
            result.result = GateResult.FAIL
            result.reason = f"Blocked by {len(sev2_gaps)} unresolved SEV-2 gap(s). " \
                           f"Maximum allowed: {max_sev2}. " \
                           "SEV-2 threshold cannot be overridden by confidence."
            
            self._logger.error(
                f"[gap: gate04_sev2_threshold] {result.reason} "
                f"Gap IDs: {[g.gap_id for g in sev2_gaps]}"
            )
            return result
        
        # Check if confidence override is enabled
        confidence_override = self.config.get("gate04_confidence_override", False)
        
        # RULE 3: SEV-3/SEV-4 can have advisory pass with HIGH confidence
        if sev3_gaps or sev4_gaps:
            if confidence == "HIGH" and confidence_override:
                # Advisory pass - passed but with warnings
                result.result = GateResult.ADVISORY_PASS
                result.reason = f"Advisory pass with {len(sev3_gaps)} SEV-3 and " \
                               f"{len(sev4_gaps)} SEV-4 gaps (HIGH confidence)."
                
                result.advisory_warnings = [
                    f"SEV-3 gap: {g.gap_id} - {g.description}" 
                    for g in sev3_gaps
                ] + [
                    f"SEV-4 gap: {g.gap_id} - {g.description}" 
                    for g in sev4_gaps
                ]
                
                self._logger.warning(
                    f"[gap: gate04_advisory_pass] {result.reason}"
                )
            elif sev3_gaps or sev4_gaps:
                # With MEDIUM/LOW confidence, SEV-3/4 gaps are warnings but still pass
                # if confidence_override is disabled
                result.result = GateResult.PASS
                result.reason = f"Passed with {len(sev3_gaps)} SEV-3 and " \
                               f"{len(sev4_gaps)} SEV-4 gaps."
                result.advisory_warnings = [
                    f"Gap present: {g.gap_id} ({g.severity.value})"
                    for g in sev3_gaps + sev4_gaps
                ]
        else:
            # No blocking gaps
            result.result = GateResult.PASS
            result.reason = "All gates passed. No unresolved gaps."
        
        return result
    
    def check_advisory_misapplication(self, gaps: List[Gap], 
                                       confidence: str) -> Optional[str]:
        """
        Check if advisory pass is being misapplied to SEV-1/SEV-2 gaps.
        
        This is used by lint checks to catch configuration errors.
        
        Args:
            gaps: List of gaps
            confidence: Confidence level
            
        Returns:
            Gap tag if misapplication detected, None otherwise
        """
        sev1_gaps = [g for g in gaps if g.severity == Severity.SEV_1 and not g.resolved]
        sev2_gaps = [g for g in gaps if g.severity == Severity.SEV_2 and not g.resolved]
        
        if sev1_gaps and confidence == "HIGH":
            return "[gap: confidence_advisory_misapplied] " \
                   "Confidence advisory cannot apply to SEV-1 gaps"
        
        max_sev2 = self.config.get("gate04", {}).get("max_sev2_gaps", 0)
        if len(sev2_gaps) > max_sev2 and confidence == "HIGH":
            return "[gap: confidence_advisory_misapplied] " \
                   "Confidence advisory cannot apply to SEV-2 gaps above threshold"
        
        return None
    
    def get_gap_summary(self, gaps: List[Gap]) -> Dict[str, Any]:
        """
        Get summary of gaps by severity.
        
        Args:
            gaps: List of gaps
            
        Returns:
            Dict with gap counts by severity
        """
        return {
            "total": len(gaps),
            "resolved": len([g for g in gaps if g.resolved]),
            "unresolved": len([g for g in gaps if not g.resolved]),
            "by_severity": {
                "SEV-1": len([g for g in gaps if g.severity == Severity.SEV_1 and not g.resolved]),
                "SEV-2": len([g for g in gaps if g.severity == Severity.SEV_2 and not g.resolved]),
                "SEV-3": len([g for g in gaps if g.severity == Severity.SEV_3 and not g.resolved]),
                "SEV-4": len([g for g in gaps if g.severity == Severity.SEV_4 and not g.resolved])
            }
        }


def evaluate_gate_04(gaps: List[Dict[str, Any]], 
                     confidence: str = "MEDIUM",
                     config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Convenience function to evaluate Gate-04.
    
    Args:
        gaps: List of gap dictionaries
        confidence: Confidence level
        config: Configuration dictionary
        
    Returns:
        Evaluation result dictionary
    """
    evaluator = Gate04Evaluator(config)
    
    # Convert dict gaps to Gap objects
    gap_objects = []
    for g in gaps:
        if isinstance(g, dict):
            gap_objects.append(Gap.from_dict(g))
        elif isinstance(g, Gap):
            gap_objects.append(g)
    
    result = evaluator.evaluate(gap_objects, confidence)
    return result.to_dict()
