"""
Amendment Control for TITAN FUSE Protocol.

ITEM-DAG-114: Root Model Plan Amendment Control

Provides controlled amendment of execution DAG with GATE-02 validation.
All DAG modifications require explicit approval, preventing unauthorized
plan modifications by the root model.

Key Features:
- Amendment requests must be created before DAG changes
- GATE-02 validation required for approval
- Full audit logging of all amendments
- Integration with EventBus for event-driven notifications

Author: TITAN FUSE Team
Version: 4.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Callable, TYPE_CHECKING
import logging
import uuid

if TYPE_CHECKING:
    from ..events.event_bus import EventBus
    from ..policy.gate_manager import GateManager, GateResult


class AmendmentStatus(Enum):
    """Status of an amendment request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AmendmentType(Enum):
    """Type of DAG amendment being requested."""
    ADD_STEP = "add_step"
    REMOVE_STEP = "remove_step"
    MODIFY_DEPENDENCY = "modify_dependency"
    CHANGE_PRIORITY = "change_priority"
    ADD_BATCH = "add_batch"
    REMOVE_BATCH = "remove_batch"
    MODIFY_EXECUTION_ORDER = "modify_execution_order"
    CHANGE_KEEP_VETO = "change_keep_veto"


@dataclass
class Amendment:
    """
    Represents a proposed DAG amendment.
    
    Attributes:
        amendment_type: Type of amendment being requested
        target: Target element being modified (step ID, batch ID, etc.)
        changes: Dictionary of proposed changes
        reason: Human-readable reason for the amendment
        requester: ID of the entity requesting the amendment
    """
    amendment_type: AmendmentType
    target: str
    changes: Dict[str, Any]
    reason: str
    requester: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "amendment_type": self.amendment_type.value,
            "target": self.target,
            "changes": self.changes,
            "reason": self.reason,
            "requester": self.requester,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Amendment':
        """Create from dictionary."""
        return cls(
            amendment_type=AmendmentType(data["amendment_type"]),
            target=data["target"],
            changes=data["changes"],
            reason=data["reason"],
            requester=data["requester"],
            metadata=data.get("metadata", {})
        )


@dataclass
class AmendmentRequest:
    """
    A formal request to amend the execution DAG.
    
    ITEM-DAG-114: All DAG modifications must go through this request/approval flow.
    
    Attributes:
        request_id: Unique identifier for this request
        amendment: The proposed amendment
        status: Current status of the request
        created_at: Timestamp when request was created
        created_by: ID of the entity that created the request
        gate_validation_result: Result of GATE-02 validation
        rejection_reason: Reason for rejection if applicable
        approved_at: Timestamp when approved (if approved)
        approved_by: ID of the entity that approved (if approved)
        audit_entries: List of audit log entries
    """
    request_id: str
    amendment: Amendment
    status: AmendmentStatus = AmendmentStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    created_by: str = ""
    gate_validation_result: Optional[Dict[str, Any]] = None
    rejection_reason: Optional[str] = None
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    audit_entries: List[Dict[str, Any]] = field(default_factory=list)
    
    def __post_init__(self):
        """Add initial audit entry."""
        if not self.audit_entries:
            self.audit_entries.append({
                "timestamp": self.created_at,
                "action": "created",
                "details": f"Amendment request created by {self.created_by or 'system'}"
            })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "request_id": self.request_id,
            "amendment": self.amendment.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "gate_validation_result": self.gate_validation_result,
            "rejection_reason": self.rejection_reason,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "audit_entries": self.audit_entries
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AmendmentRequest':
        """Create from dictionary."""
        return cls(
            request_id=data["request_id"],
            amendment=Amendment.from_dict(data["amendment"]),
            status=AmendmentStatus(data["status"]),
            created_at=data["created_at"],
            created_by=data.get("created_by", ""),
            gate_validation_result=data.get("gate_validation_result"),
            rejection_reason=data.get("rejection_reason"),
            approved_at=data.get("approved_at"),
            approved_by=data.get("approved_by"),
            audit_entries=data.get("audit_entries", [])
        )
    
    def add_audit_entry(self, action: str, details: str) -> None:
        """Add an entry to the audit log."""
        self.audit_entries.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "action": action,
            "details": details
        })


class AmendmentController:
    """
    ITEM-DAG-114: Controls DAG amendment requests with GATE-02 validation.
    
    This controller ensures that all DAG modifications go through a proper
    approval process, preventing unauthorized changes by the root model.
    
    Workflow:
    1. Root model calls request_amendment() to propose a change
    2. Controller validates against protected fields
    3. GATE-02 validation is triggered
    4. If validation passes, amendment can be approved
    5. All actions are audit logged
    
    Integration Points:
    - EventBus: Emits PLAN_AMENDMENT_REQUESTED/APPROVED/REJECTED events
    - GateManager: Validates amendments through GATE-02
    - AuditTrail: Logs all amendment actions
    
    Usage:
        controller = AmendmentController(event_bus, gate_manager)
        
        # Request an amendment
        amendment = Amendment(
            amendment_type=AmendmentType.ADD_STEP,
            target="step-123",
            changes={"name": "new_step", "dependencies": []},
            reason="Need additional processing step",
            requester="root_model"
        )
        request = controller.request_amendment(amendment)
        
        # Later, approve or reject
        if controller.approve_amendment(request.request_id):
            # Apply the changes to the DAG
            apply_amendment(request.amendment)
    """
    
    # Protected fields that require special validation
    PROTECTED_FIELDS = [
        "execution_order",
        "dependencies",
        "batches",
        "keep_veto_markers",
        "critical_path"
    ]
    
    def __init__(
        self,
        event_bus: Optional['EventBus'] = None,
        gate_manager: Optional['GateManager'] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the amendment controller.
        
        Args:
            event_bus: EventBus for emitting amendment events
            gate_manager: GateManager for GATE-02 validation
            config: Configuration dictionary
        """
        self._event_bus = event_bus
        self._gate_manager = gate_manager
        self._config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # Storage for amendment requests
        self._requests: Dict[str, AmendmentRequest] = {}
        
        # Auto-approval setting (disabled by default for security)
        self._auto_approve = self._config.get("auto_approve", False)
        
        # Custom validation hooks
        self._validation_hooks: List[Callable[[Amendment], bool]] = []
        
        # Amendment history for audit
        self._history: List[Dict[str, Any]] = []
        
        # Counter for generating request IDs
        self._request_counter = 0
    
    def set_event_bus(self, event_bus: 'EventBus') -> None:
        """Set the EventBus instance."""
        self._event_bus = event_bus
        self._logger.info("EventBus attached to AmendmentController")
    
    def set_gate_manager(self, gate_manager: 'GateManager') -> None:
        """Set the GateManager instance."""
        self._gate_manager = gate_manager
        self._logger.info("GateManager attached to AmendmentController")
    
    def add_validation_hook(self, hook: Callable[[Amendment], bool]) -> None:
        """
        Add a custom validation hook.
        
        Hooks are called during the validation phase. If any hook
        returns False, the amendment is rejected.
        
        Args:
            hook: Function that takes an Amendment and returns bool
        """
        self._validation_hooks.append(hook)
    
    def request_amendment(self, amendment: Amendment) -> AmendmentRequest:
        """
        Request a DAG amendment.
        
        ITEM-DAG-114: All DAG modifications must go through this method.
        This creates a formal request that must be approved before
        the amendment can be applied.
        
        Args:
            amendment: The proposed amendment
            
        Returns:
            AmendmentRequest with PENDING status
            
        Raises:
            ValueError: If amendment is invalid
        """
        # Validate amendment structure
        self._validate_amendment(amendment)
        
        # Generate request ID
        self._request_counter += 1
        request_id = f"AMEND-{datetime.utcnow().strftime('%Y%m%d')}-{self._request_counter:04d}"
        
        # Create the request
        request = AmendmentRequest(
            request_id=request_id,
            amendment=amendment,
            status=AmendmentStatus.PENDING,
            created_by=amendment.requester
        )
        
        # Store the request
        self._requests[request_id] = request
        
        # Add to history
        self._history.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "action": "requested",
            "request_id": request_id,
            "amendment_type": amendment.amendment_type.value,
            "requester": amendment.requester
        })
        
        # Emit event
        self._emit_event("PLAN_AMENDMENT_REQUESTED", {
            "request_id": request_id,
            "amendment_type": amendment.amendment_type.value,
            "target": amendment.target,
            "requester": amendment.requester,
            "reason": amendment.reason
        })
        
        self._logger.info(
            f"Amendment request created: {request_id} "
            f"(type={amendment.amendment_type.value}, target={amendment.target})"
        )
        
        return request
    
    def approve_amendment(self, request_id: str, approver: str = "system") -> bool:
        """
        Approve an amendment request.
        
        ITEM-DAG-114: Approval requires GATE-02 validation to pass.
        The amendment must be in PENDING status.
        
        Args:
            request_id: ID of the amendment request
            approver: ID of the entity approving the amendment
            
        Returns:
            True if approved, False if validation failed
            
        Raises:
            ValueError: If request not found or not in PENDING status
        """
        request = self._get_request(request_id)
        
        if request.status != AmendmentStatus.PENDING:
            raise ValueError(
                f"Cannot approve request {request_id}: status is {request.status.value}"
            )
        
        # Run GATE-02 validation
        validation_result = self._run_gate_validation(request.amendment)
        request.gate_validation_result = validation_result
        
        if not validation_result.get("valid", False):
            # Auto-reject if validation fails
            request.status = AmendmentStatus.REJECTED
            request.rejection_reason = validation_result.get("reason", "GATE-02 validation failed")
            request.add_audit_entry("rejected", f"GATE-02 validation failed: {request.rejection_reason}")
            
            self._emit_event("PLAN_AMENDMENT_REJECTED", {
                "request_id": request_id,
                "reason": request.rejection_reason,
                "validation_result": validation_result
            })
            
            self._logger.warning(
                f"Amendment {request_id} rejected: GATE-02 validation failed"
            )
            return False
        
        # Approve the request
        request.status = AmendmentStatus.APPROVED
        request.approved_at = datetime.utcnow().isoformat() + "Z"
        request.approved_by = approver
        request.add_audit_entry("approved", f"Approved by {approver}")
        
        # Update history
        self._history.append({
            "timestamp": request.approved_at,
            "action": "approved",
            "request_id": request_id,
            "approver": approver
        })
        
        # Emit event
        self._emit_event("PLAN_AMENDMENT_APPROVED", {
            "request_id": request_id,
            "amendment_type": request.amendment.amendment_type.value,
            "target": request.amendment.target,
            "approver": approver
        })
        
        self._logger.info(f"Amendment {request_id} approved by {approver}")
        return True
    
    def reject_amendment(self, request_id: str, reason: str, rejected_by: str = "system") -> None:
        """
        Reject an amendment request.
        
        ITEM-DAG-114: Rejection is logged for audit purposes.
        
        Args:
            request_id: ID of the amendment request
            reason: Human-readable reason for rejection
            rejected_by: ID of the entity rejecting the amendment
            
        Raises:
            ValueError: If request not found or not in PENDING status
        """
        request = self._get_request(request_id)
        
        if request.status != AmendmentStatus.PENDING:
            raise ValueError(
                f"Cannot reject request {request_id}: status is {request.status.value}"
            )
        
        # Reject the request
        request.status = AmendmentStatus.REJECTED
        request.rejection_reason = reason
        request.add_audit_entry("rejected", f"Rejected by {rejected_by}: {reason}")
        
        # Update history
        self._history.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "action": "rejected",
            "request_id": request_id,
            "reason": reason,
            "rejected_by": rejected_by
        })
        
        # Emit event
        self._emit_event("PLAN_AMENDMENT_REJECTED", {
            "request_id": request_id,
            "reason": reason,
            "rejected_by": rejected_by
        })
        
        self._logger.info(f"Amendment {request_id} rejected by {rejected_by}: {reason}")
    
    def get_request(self, request_id: str) -> Optional[AmendmentRequest]:
        """
        Get an amendment request by ID.
        
        Args:
            request_id: ID of the request
            
        Returns:
            AmendmentRequest if found, None otherwise
        """
        return self._requests.get(request_id)
    
    def get_pending_requests(self) -> List[AmendmentRequest]:
        """
        Get all pending amendment requests.
        
        Returns:
            List of AmendmentRequest with PENDING status
        """
        return [
            req for req in self._requests.values()
            if req.status == AmendmentStatus.PENDING
        ]
    
    def get_approved_requests(self) -> List[AmendmentRequest]:
        """
        Get all approved amendment requests.
        
        Returns:
            List of AmendmentRequest with APPROVED status
        """
        return [
            req for req in self._requests.values()
            if req.status == AmendmentStatus.APPROVED
        ]
    
    def get_rejected_requests(self) -> List[AmendmentRequest]:
        """
        Get all rejected amendment requests.
        
        Returns:
            List of AmendmentRequest with REJECTED status
        """
        return [
            req for req in self._requests.values()
            if req.status == AmendmentStatus.REJECTED
        ]
    
    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get amendment history for audit.
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of history entries
        """
        return self._history[-limit:]
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get amendment controller statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            "total_requests": len(self._requests),
            "pending": len(self.get_pending_requests()),
            "approved": len(self.get_approved_requests()),
            "rejected": len(self.get_rejected_requests()),
            "history_entries": len(self._history),
            "validation_hooks": len(self._validation_hooks),
            "auto_approve_enabled": self._auto_approve
        }
    
    def clear_history(self) -> None:
        """Clear amendment history (for testing)."""
        self._history.clear()
    
    def _get_request(self, request_id: str) -> AmendmentRequest:
        """Get request or raise ValueError if not found."""
        request = self._requests.get(request_id)
        if request is None:
            raise ValueError(f"Amendment request not found: {request_id}")
        return request
    
    def _validate_amendment(self, amendment: Amendment) -> None:
        """Validate amendment structure and constraints."""
        if not amendment.target:
            raise ValueError("Amendment must have a target")
        
        if not amendment.reason:
            raise ValueError("Amendment must have a reason")
        
        if not amendment.requester:
            raise ValueError("Amendment must have a requester")
        
        # Check if amendment modifies protected fields
        for field in self.PROTECTED_FIELDS:
            if field in amendment.changes:
                self._logger.warning(
                    f"Amendment modifies protected field: {field}"
                )
    
    def _run_gate_validation(self, amendment: Amendment) -> Dict[str, Any]:
        """
        Run GATE-02 validation for an amendment.
        
        ITEM-DAG-114: All amendments require GATE-02 validation.
        
        Args:
            amendment: The amendment to validate
            
        Returns:
            Validation result dictionary
        """
        result = {
            "valid": True,
            "checks": [],
            "reason": None
        }
        
        # Run custom validation hooks
        for hook in self._validation_hooks:
            try:
                if not hook(amendment):
                    result["valid"] = False
                    result["reason"] = "Custom validation hook rejected amendment"
                    result["checks"].append({
                        "hook": hook.__name__,
                        "passed": False
                    })
                    return result
                result["checks"].append({
                    "hook": hook.__name__,
                    "passed": True
                })
            except Exception as e:
                result["valid"] = False
                result["reason"] = f"Validation hook error: {e}"
                return result
        
        # Run GateManager validation if available
        if self._gate_manager is not None:
            gate_context = {
                "amendment": amendment.to_dict(),
                "amendment_type": amendment.amendment_type.value,
                "target": amendment.target,
                "changes": amendment.changes,
                "requester": amendment.requester
            }
            
            try:
                from ..policy.gate_manager import GateResult
                gate_result = self._gate_manager.run_pre_exec_gates(gate_context)
                
                if gate_result.overall_result == GateResult.FAIL:
                    result["valid"] = False
                    result["reason"] = f"Gate validation failed: {', '.join(gate_result.failed_gates)}"
                    result["gate_result"] = gate_result.to_dict()
                    return result
                
                result["checks"].append({
                    "gate": "GATE-02",
                    "passed": True,
                    "warnings": gate_result.warnings
                })
                
            except Exception as e:
                self._logger.error(f"Gate validation error: {e}")
                result["valid"] = False
                result["reason"] = f"Gate validation error: {e}"
                return result
        
        return result
    
    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit an event through the EventBus."""
        if self._event_bus is not None:
            try:
                self._event_bus.emit_simple(
                    event_type=event_type,
                    data=data,
                    source="AmendmentController"
                )
            except Exception as e:
                self._logger.error(f"Failed to emit event {event_type}: {e}")


def create_amendment_controller(
    event_bus: Optional['EventBus'] = None,
    gate_manager: Optional['GateManager'] = None,
    config: Optional[Dict[str, Any]] = None
) -> AmendmentController:
    """
    Factory function to create an AmendmentController.
    
    Args:
        event_bus: EventBus for emitting amendment events
        gate_manager: GateManager for GATE-02 validation
        config: Configuration dictionary
        
    Returns:
        AmendmentController instance
    """
    return AmendmentController(event_bus, gate_manager, config)
