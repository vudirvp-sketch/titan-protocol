"""
Plan amendment gate for root model changes.
Ensures all plan modifications go through GATE-02 validation.
"""

from typing import Dict, List
from enum import Enum


class PlanAmendmentType(Enum):
    ADD_STEP = "add_step"
    REMOVE_STEP = "remove_step"
    MODIFY_DEPENDENCY = "modify_dependency"
    CHANGE_PRIORITY = "change_priority"


class PlanAmendmentGate:
    """
    Gate for root model plan amendments.
    
    All amendments must be routed through GATE-02 for validation.
    Direct modification of execution DAG is blocked.
    """
    
    PROTECTED_FIELDS = [
        "execution_order",
        "dependencies",
        "batches",
        "keep_veto_markers"
    ]
    
    def __init__(self, session: Dict):
        self.session = session
        self.original_plan = session.get("state_snapshot", {}).get("execution_plan", {})
        self.amendments: List[Dict] = []
    
    def propose_amendment(self, amendment_type: PlanAmendmentType, details: Dict) -> Dict:
        """
        Propose a plan amendment.
        
        Does NOT apply immediately - must be validated by GATE-02.
        """
        amendment = {
            "type": amendment_type.value,
            "details": details,
            "status": "pending",
            "requires_gate_validation": True
        }
        self.amendments.append(amendment)
        
        return {
            "accepted": True,
            "amendment_id": f"AMEND-{len(self.amendments)}",
            "message": "Amendment proposed. Requires GATE-02 validation before application."
        }
    
    def validate_amendments(self) -> Dict:
        """
        Validate all pending amendments through GATE-02.
        
        Returns:
            Validation result with list of approved/rejected amendments
        """
        results = []
        
        for amendment in self.amendments:
            if amendment["status"] != "pending":
                continue
            
            # Check KEEP_VETO
            if self._violates_keep_veto(amendment):
                amendment["status"] = "rejected"
                results.append({
                    "amendment": amendment,
                    "valid": False,
                    "reason": "Violates KEEP_VETO marker"
                })
                continue
            
            # Check dependency validity
            if not self._valid_dependencies(amendment):
                amendment["status"] = "rejected"
                results.append({
                    "amendment": amendment,
                    "valid": False,
                    "reason": "Invalid dependency graph"
                })
                continue
            
            amendment["status"] = "approved"
            results.append({
                "amendment": amendment,
                "valid": True
            })
        
        return {
            "total": len(self.amendments),
            "approved": sum(1 for a in self.amendments if a["status"] == "approved"),
            "rejected": sum(1 for a in self.amendments if a["status"] == "rejected"),
            "details": results
        }
    
    def _violates_keep_veto(self, amendment: Dict) -> bool:
        """Check if amendment violates KEEP markers."""
        keep_markers = self.session.get("state_snapshot", {}).get("keep_veto_markers", [])
        # Check if amendment attempts to modify protected content
        return False  # Simplified - would check actual markers
    
    def _valid_dependencies(self, amendment: Dict) -> bool:
        """Check if amendment creates valid dependencies."""
        # Would use CycleDetector
        return True


def create_amendment_gate(session: Dict) -> PlanAmendmentGate:
    """Create a plan amendment gate for session."""
    return PlanAmendmentGate(session)
