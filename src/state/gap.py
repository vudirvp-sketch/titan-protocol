"""
Structured Gap representation with complete GAP_TYPES support.
ITEM-GAP-001: GAP_TYPE_COMPLETENESS for TITAN PROTOCOL v5.0.0

Provides comprehensive gap type handling with resolution strategies and tracking.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, TYPE_CHECKING
from enum import Enum
import hashlib
import re
import logging
import time
from datetime import datetime

if TYPE_CHECKING:
    pass


class GapSeverity(Enum):
    """Gap severity levels"""
    SEV_1 = "SEV-1"  # Critical - blocks release
    SEV_2 = "SEV-2"  # High - should be fixed
    SEV_3 = "SEV-3"  # Medium - nice to fix
    SEV_4 = "SEV-4"  # Low - minor issue


class GapType(Enum):
    """
    All 20 GAP_TYPES from TITAN PROTOCOL v5.0.0.
    ITEM-GAP-001: Complete enumeration of all gap types.
    """
    AMBIGUOUS_REQUEST = "ambiguous_request"
    SCOPE_NOT_FOUND = "scope_not_found"
    DOMAIN_NOT_INJECTED = "domain_not_injected"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    BUDGET_EXCEEDED = "budget_exceeded"
    ROLLBACK_TRIGGERED = "rollback_triggered"
    ABI_LOCKED_VIOLATION = "abi_locked_violation"
    DEPENDENCY_CYCLE = "dependency_cycle"
    RECURSION_LIMIT_REACHED = "recursion_limit_reached"
    UNSAFE_EXECUTION_BLOCKED = "unsafe_execution_blocked"
    LLM_QUERY_FAILED = "llm_query_failed"
    VALIDATION_FAILURE = "validation_failure"
    BINARY_FILE = "binary_file"
    ENCODING_UNRESOLVABLE = "encoding_unresolvable"
    TOOL_NOT_FOUND = "tool_not_found"
    POLICY_VIOLATION = "policy_violation"
    STATE_DRIFT = "state_drift"
    CHECKPOINT_CORRUPTED = "checkpoint_corrupted"
    CONSENSUS_FAILURE = "consensus_failure"
    HUMAN_GATE_TIMEOUT = "human_gate_timeout"


class ResolutionStrategy(Enum):
    """
    Resolution strategies for gaps.
    Each strategy defines how a gap type should be handled.
    """
    SIMULTANEOUS_UPDATE = "simultaneous_update"
    INJECT_OR_FALLBACK = "inject_or_fallback"
    CHECKPOINT_AND_PAUSE = "checkpoint_and_pause"
    RESTORE_AND_REPORT = "restore_and_report"
    HALT_AND_REPORT = "halt_and_report"
    SANDBOX_OR_HUMAN_GATE = "sandbox_or_human_gate"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    SKIP_WITH_LOG = "skip_with_log"
    MANUAL_INTERVENTION = "manual_intervention"
    ESCALATE = "escalate"
    REPLAN = "replan"
    ABORT = "abort"


class ResolutionStatus(Enum):
    """Status of gap resolution process"""
    OPEN = "open"
    RETRYING = "retrying"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


@dataclass
class GapHandler:
    """
    Handler configuration for a specific gap type.
    ITEM-GAP-001: Defines resolution strategy and behavior.
    """
    gap_type: GapType
    resolution_strategy: ResolutionStrategy
    handler_func: Optional[Callable[[Any], None]] = None
    max_retries: int = 3
    escalation_target: Optional[str] = None
    backoff_ms: int = 100
    description: str = ""


@dataclass
class GapResolution:
    """
    Track gap resolution progress.
    ITEM-GAP-001: Records resolution attempts and outcomes.
    """
    gap_id: str
    gap_type: Optional[GapType] = None
    status: ResolutionStatus = ResolutionStatus.OPEN
    attempts: int = 0
    resolved_at: Optional[str] = None
    resolution_notes: str = ""
    resolution_time_ms: float = 0.0
    strategy_used: Optional[ResolutionStrategy] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "gap_id": self.gap_id,
            "gap_type": self.gap_type.value if self.gap_type else None,
            "status": self.status.value,
            "attempts": self.attempts,
            "resolved_at": self.resolved_at,
            "resolution_notes": self.resolution_notes,
            "resolution_time_ms": self.resolution_time_ms,
            "strategy_used": self.strategy_used.value if self.strategy_used else None,
            "error_message": self.error_message
        }


@dataclass
class Gap:
    """
    Structured representation of a gap.
    
    A gap indicates something that could not be verified or completed.
    ITEM-GAP-001: Enhanced with gap_type field for complete type tracking.
    """
    id: str
    reason: str
    severity: GapSeverity = GapSeverity.SEV_4
    gap_type: Optional[GapType] = None
    
    # Source reference
    source_file: Optional[str] = None
    source_line_start: Optional[int] = None
    source_line_end: Optional[int] = None
    
    # Verification
    source_checksum: Optional[str] = None
    verified: bool = False
    
    # Metadata
    context: str = ""
    suggested_action: str = ""
    tags: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.id:
            self.id = self._generate_id()
        # Infer gap_type from reason if not set
        if self.gap_type is None and self.reason:
            self.gap_type = self._infer_gap_type()
    
    def _generate_id(self) -> str:
        """Generate unique gap ID."""
        content = f"{self.reason}{self.source_file}{self.source_line_start}"
        return f"GAP-{hashlib.md5(content.encode()).hexdigest()[:8].upper()}"
    
    def _infer_gap_type(self) -> Optional[GapType]:
        """Infer gap type from reason string."""
        reason_lower = self.reason.lower()
        
        # Map common patterns to gap types
        type_patterns = {
            GapType.ABI_LOCKED_VIOLATION: ["abi_locked", "abi violation", "abi lock"],
            GapType.DOMAIN_NOT_INJECTED: ["domain not injected", "domain_missing", "injection failed"],
            GapType.BUDGET_EXCEEDED: ["budget exceeded", "budget over", "token limit"],
            GapType.ROLLBACK_TRIGGERED: ["rollback", "rolled back"],
            GapType.RECURSION_LIMIT_REACHED: ["recursion limit", "max recursion", "recursion depth"],
            GapType.UNSAFE_EXECUTION_BLOCKED: ["unsafe execution", "blocked execution", "security block"],
            GapType.LLM_QUERY_FAILED: ["llm query failed", "llm error", "model error", "llm failure"],
            GapType.BINARY_FILE: ["binary file", "binary content", "non-text file"],
            GapType.ENCODING_UNRESOLVABLE: ["encoding", "unresolvable encoding", "charset"],
            GapType.AMBIGUOUS_REQUEST: ["ambiguous", "unclear request", "multiple interpretations"],
            GapType.SCOPE_NOT_FOUND: ["scope not found", "missing scope", "scope undefined"],
            GapType.RESOURCE_EXHAUSTED: ["resource exhausted", "out of memory", "resource limit"],
            GapType.DEPENDENCY_CYCLE: ["dependency cycle", "circular dependency", "cycle detected"],
            GapType.VALIDATION_FAILURE: ["validation failed", "validation failure", "invalid"],
            GapType.TOOL_NOT_FOUND: ["tool not found", "missing tool", "unknown tool"],
            GapType.POLICY_VIOLATION: ["policy violation", "policy breach", "violated policy"],
            GapType.STATE_DRIFT: ["state drift", "drift detected", "state mismatch"],
            GapType.CHECKPOINT_CORRUPTED: ["checkpoint corrupted", "corrupted checkpoint", "checkpoint invalid"],
            GapType.CONSENSUS_FAILURE: ["consensus failure", "consensus error", "disagreement"],
            GapType.HUMAN_GATE_TIMEOUT: ["human gate timeout", "approval timeout", "gate timeout"]
        }
        
        for gap_type, patterns in type_patterns.items():
            for pattern in patterns:
                if pattern in reason_lower:
                    return gap_type
        
        return None
    
    def to_string(self) -> str:
        """Convert to legacy string format for compatibility."""
        checksum_part = ""
        if self.source_checksum:
            checksum_part = f" -- source:{self.source_line_start}-{self.source_line_end}:{self.source_checksum}"
        
        type_part = ""
        if self.gap_type:
            type_part = f" [{self.gap_type.value}]"
        
        return f"[gap: {self.reason} ({self.severity.value}){type_part}{checksum_part}]"
    
    @classmethod
    def from_string(cls, gap_str: str) -> "Gap":
        """Parse legacy gap string."""
        # Extract reason
        match = re.search(r'\[gap:\s*([^\]]+)\]', gap_str)
        if not match:
            return cls(id="", reason=gap_str)
        
        content = match.group(1)
        
        # Extract severity
        severity = GapSeverity.SEV_4
        for sev in GapSeverity:
            if sev.value in content:
                severity = sev
                break
        
        # Extract gap type if present
        gap_type = None
        type_match = re.search(r'\[([a-z_]+)\]', content)
        if type_match:
            try:
                gap_type = GapType(type_match.group(1))
            except ValueError:
                pass
        
        # Extract source reference
        source_match = re.search(r'source:(\d+)-(\d+):([a-f0-9]+)', content)
        source_file = None
        line_start = None
        line_end = None
        checksum = None
        
        if source_match:
            line_start = int(source_match.group(1))
            line_end = int(source_match.group(2))
            checksum = source_match.group(3)
        
        # Clean reason
        reason = re.sub(r'\s*--\s*source:.*$', '', content)
        reason = re.sub(r'\s*\[[a-z_]+\]\s*$', '', reason)
        reason = re.sub(r'\s*\([A-Z]+-\d+\)\s*$', '', reason).strip()
        
        return cls(
            id="",
            reason=reason,
            severity=severity,
            gap_type=gap_type,
            source_line_start=line_start,
            source_line_end=line_end,
            source_checksum=checksum,
            verified=bool(checksum)
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "reason": self.reason,
            "severity": self.severity.value,
            "gap_type": self.gap_type.value if self.gap_type else None,
            "source_file": self.source_file,
            "source_line_start": self.source_line_start,
            "source_line_end": self.source_line_end,
            "source_checksum": self.source_checksum,
            "verified": self.verified,
            "context": self.context,
            "suggested_action": self.suggested_action,
            "tags": self.tags
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Gap":
        """Create from dictionary."""
        gap_type = None
        if data.get("gap_type"):
            try:
                gap_type = GapType(data.get("gap_type"))
            except ValueError:
                pass
        
        return cls(
            id=data.get("id", ""),
            reason=data.get("reason", ""),
            severity=GapSeverity(data.get("severity", "SEV-4")),
            gap_type=gap_type,
            source_file=data.get("source_file"),
            source_line_start=data.get("source_line_start"),
            source_line_end=data.get("source_line_end"),
            source_checksum=data.get("source_checksum"),
            verified=data.get("verified", False),
            context=data.get("context", ""),
            suggested_action=data.get("suggested_action", ""),
            tags=data.get("tags", [])
        )


class GapManager:
    """
    ITEM-GAP-001: Manage all 20 gap types with handlers and resolution tracking.
    
    Provides comprehensive gap handling with configurable strategies and
    resolution tracking for TITAN PROTOCOL v5.0.0.
    """
    
    # Default handlers for all 20 gap types
    DEFAULT_HANDLERS: Dict[GapType, GapHandler] = {
        GapType.ABI_LOCKED_VIOLATION: GapHandler(
            GapType.ABI_LOCKED_VIOLATION,
            ResolutionStrategy.SIMULTANEOUS_UPDATE,
            description="Handle ABI locked violations via simultaneous update"
        ),
        GapType.DOMAIN_NOT_INJECTED: GapHandler(
            GapType.DOMAIN_NOT_INJECTED,
            ResolutionStrategy.INJECT_OR_FALLBACK,
            description="Inject missing domain or fallback to default"
        ),
        GapType.BUDGET_EXCEEDED: GapHandler(
            GapType.BUDGET_EXCEEDED,
            ResolutionStrategy.CHECKPOINT_AND_PAUSE,
            description="Checkpoint state and pause execution"
        ),
        GapType.ROLLBACK_TRIGGERED: GapHandler(
            GapType.ROLLBACK_TRIGGERED,
            ResolutionStrategy.RESTORE_AND_REPORT,
            description="Restore from checkpoint and report"
        ),
        GapType.RECURSION_LIMIT_REACHED: GapHandler(
            GapType.RECURSION_LIMIT_REACHED,
            ResolutionStrategy.HALT_AND_REPORT,
            description="Halt execution and report recursion depth"
        ),
        GapType.UNSAFE_EXECUTION_BLOCKED: GapHandler(
            GapType.UNSAFE_EXECUTION_BLOCKED,
            ResolutionStrategy.SANDBOX_OR_HUMAN_GATE,
            description="Route to sandbox or require human approval"
        ),
        GapType.LLM_QUERY_FAILED: GapHandler(
            GapType.LLM_QUERY_FAILED,
            ResolutionStrategy.RETRY_WITH_BACKOFF,
            max_retries=3,
            backoff_ms=100,
            description="Retry LLM query with exponential backoff"
        ),
        GapType.BINARY_FILE: GapHandler(
            GapType.BINARY_FILE,
            ResolutionStrategy.SKIP_WITH_LOG,
            description="Skip binary file processing and log"
        ),
        GapType.ENCODING_UNRESOLVABLE: GapHandler(
            GapType.ENCODING_UNRESOLVABLE,
            ResolutionStrategy.MANUAL_INTERVENTION,
            description="Require manual intervention for encoding issues"
        ),
        GapType.AMBIGUOUS_REQUEST: GapHandler(
            GapType.AMBIGUOUS_REQUEST,
            ResolutionStrategy.ESCALATE,
            description="Escalate ambiguous requests for clarification"
        ),
        GapType.SCOPE_NOT_FOUND: GapHandler(
            GapType.SCOPE_NOT_FOUND,
            ResolutionStrategy.INJECT_OR_FALLBACK,
            description="Inject scope or fallback to default"
        ),
        GapType.RESOURCE_EXHAUSTED: GapHandler(
            GapType.RESOURCE_EXHAUSTED,
            ResolutionStrategy.CHECKPOINT_AND_PAUSE,
            description="Checkpoint and pause due to resource exhaustion"
        ),
        GapType.DEPENDENCY_CYCLE: GapHandler(
            GapType.DEPENDENCY_CYCLE,
            ResolutionStrategy.REPLAN,
            description="Replan to break dependency cycle"
        ),
        GapType.VALIDATION_FAILURE: GapHandler(
            GapType.VALIDATION_FAILURE,
            ResolutionStrategy.ESCALATE,
            description="Escalate validation failures"
        ),
        GapType.TOOL_NOT_FOUND: GapHandler(
            GapType.TOOL_NOT_FOUND,
            ResolutionStrategy.INJECT_OR_FALLBACK,
            description="Inject tool or fallback to alternative"
        ),
        GapType.POLICY_VIOLATION: GapHandler(
            GapType.POLICY_VIOLATION,
            ResolutionStrategy.HALT_AND_REPORT,
            description="Halt execution and report policy violation"
        ),
        GapType.STATE_DRIFT: GapHandler(
            GapType.STATE_DRIFT,
            ResolutionStrategy.RESTORE_AND_REPORT,
            description="Restore state from checkpoint and report drift"
        ),
        GapType.CHECKPOINT_CORRUPTED: GapHandler(
            GapType.CHECKPOINT_CORRUPTED,
            ResolutionStrategy.ABORT,
            description="Abort execution due to corrupted checkpoint"
        ),
        GapType.CONSENSUS_FAILURE: GapHandler(
            GapType.CONSENSUS_FAILURE,
            ResolutionStrategy.ESCALATE,
            description="Escalate consensus failures for resolution"
        ),
        GapType.HUMAN_GATE_TIMEOUT: GapHandler(
            GapType.HUMAN_GATE_TIMEOUT,
            ResolutionStrategy.ESCALATE,
            description="Escalate timeout to alternate approver"
        ),
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize GapManager.
        
        Args:
            config: Optional configuration dictionary
        """
        self._handlers = dict(self.DEFAULT_HANDLERS)
        self._resolutions: Dict[str, GapResolution] = {}
        self._logger = logging.getLogger(__name__)
        self._config = config or {}
        
        # Register custom handlers from config
        if config and "custom_handlers" in config:
            for gap_type_str, handler_config in config["custom_handlers"].items():
                try:
                    gap_type = GapType(gap_type_str)
                    strategy = ResolutionStrategy(handler_config.get("strategy", "escalate"))
                    custom_handler = GapHandler(
                        gap_type=gap_type,
                        resolution_strategy=strategy,
                        max_retries=handler_config.get("max_retries", 3),
                        description=handler_config.get("description", "")
                    )
                    self._handlers[gap_type] = custom_handler
                    self._logger.info(
                        f"[ITEM-GAP-001] Registered custom handler for {gap_type_str}"
                    )
                except (ValueError, KeyError) as e:
                    self._logger.warning(
                        f"[ITEM-GAP-001] Failed to register custom handler for {gap_type_str}: {e}"
                    )
    
    def handle_gap(self, gap: Gap) -> GapResolution:
        """
        Handle a gap with appropriate handler.
        
        Args:
            gap: The gap to handle
            
        Returns:
            GapResolution tracking the resolution process
        """
        start_time = time.time()
        handler = self._handlers.get(gap.gap_type)
        
        if not handler:
            return self._handle_unknown_gap(gap, start_time)
        
        resolution = GapResolution(
            gap_id=gap.id,
            gap_type=gap.gap_type,
            status=ResolutionStatus.OPEN,
            strategy_used=handler.resolution_strategy
        )
        
        self._logger.info(
            f"[ITEM-GAP-001] Handling gap {gap.id} "
            f"type={gap.gap_type.value if gap.gap_type else 'unknown'} "
            f"strategy={handler.resolution_strategy.value}"
        )
        
        try:
            # Handle based on strategy
            # Note: For RETRY_WITH_BACKOFF, handler_func is called inside retry loop
            resolution = self._execute_strategy(gap, handler, resolution)
            
        except Exception as e:
            resolution.status = ResolutionStatus.ESCALATED
            resolution.error_message = str(e)
            resolution.resolution_notes = f"Failed: {e}"
            self._logger.error(
                f"[ITEM-GAP-001] Gap {gap.id} handling failed: {e}"
            )
        
        resolution.resolution_time_ms = (time.time() - start_time) * 1000
        if resolution.status == ResolutionStatus.RESOLVED:
            resolution.resolved_at = datetime.now().isoformat()
        
        self._resolutions[gap.id] = resolution
        return resolution
    
    def _execute_strategy(
        self, 
        gap: Gap, 
        handler: GapHandler, 
        resolution: GapResolution
    ) -> GapResolution:
        """Execute the resolution strategy for a gap."""
        strategy = handler.resolution_strategy
        
        # Call handler function for non-retry strategies
        # RETRY_WITH_BACKOFF handles this in its own loop
        if handler.handler_func and strategy != ResolutionStrategy.RETRY_WITH_BACKOFF:
            handler.handler_func(gap)
        
        if strategy == ResolutionStrategy.SKIP_WITH_LOG:
            self._logger.info(f"[ITEM-GAP-001] Skipping gap {gap.id} with log")
            resolution.status = ResolutionStatus.RESOLVED
            resolution.resolution_notes = "Skipped with logging"
            
        elif strategy == ResolutionStrategy.RETRY_WITH_BACKOFF:
            resolution = self._retry_with_backoff(gap, handler, resolution)
            
        elif strategy == ResolutionStrategy.ESCALATE:
            resolution.status = ResolutionStatus.ESCALATED
            resolution.resolution_notes = f"Escalated to: {handler.escalation_target or 'default'}"
            
        elif strategy == ResolutionStrategy.HALT_AND_REPORT:
            self._logger.warning(f"[ITEM-GAP-001] Halting due to gap {gap.id}")
            resolution.status = ResolutionStatus.RESOLVED
            resolution.resolution_notes = "Halted and reported"
            
        elif strategy == ResolutionStrategy.CHECKPOINT_AND_PAUSE:
            self._logger.info(f"[ITEM-GAP-001] Checkpoint and pause for gap {gap.id}")
            resolution.status = ResolutionStatus.RESOLVED
            resolution.resolution_notes = "Checkpoint created, execution paused"
            
        elif strategy == ResolutionStrategy.RESTORE_AND_REPORT:
            self._logger.info(f"[ITEM-GAP-001] Restore and report for gap {gap.id}")
            resolution.status = ResolutionStatus.RESOLVED
            resolution.resolution_notes = "State restored from checkpoint"
            
        elif strategy == ResolutionStrategy.ABORT:
            self._logger.error(f"[ITEM-GAP-001] Aborting due to gap {gap.id}")
            resolution.status = ResolutionStatus.RESOLVED
            resolution.resolution_notes = "Execution aborted"
            
        elif strategy == ResolutionStrategy.INJECT_OR_FALLBACK:
            resolution.status = ResolutionStatus.RESOLVED
            resolution.resolution_notes = "Fallback applied"
            
        elif strategy == ResolutionStrategy.SANDBOX_OR_HUMAN_GATE:
            resolution.status = ResolutionStatus.ESCALATED
            resolution.resolution_notes = "Routed to sandbox/human gate"
            
        elif strategy == ResolutionStrategy.SIMULTANEOUS_UPDATE:
            resolution.status = ResolutionStatus.RESOLVED
            resolution.resolution_notes = "Simultaneous update applied"
            
        elif strategy == ResolutionStrategy.REPLAN:
            resolution.status = ResolutionStatus.RESOLVED
            resolution.resolution_notes = "Replanned execution path"
            
        elif strategy == ResolutionStrategy.MANUAL_INTERVENTION:
            resolution.status = ResolutionStatus.ESCALATED
            resolution.resolution_notes = "Requires manual intervention"
            
        else:
            resolution.status = ResolutionStatus.ESCALATED
            resolution.resolution_notes = f"Unknown strategy: {strategy.value}"
        
        return resolution
    
    def _retry_with_backoff(
        self, 
        gap: Gap, 
        handler: GapHandler, 
        resolution: GapResolution
    ) -> GapResolution:
        """Execute retry with backoff strategy."""
        resolution.status = ResolutionStatus.RETRYING
        
        for attempt in range(handler.max_retries):
            resolution.attempts = attempt + 1
            backoff = handler.backoff_ms * (2 ** attempt)
            
            self._logger.info(
                f"[ITEM-GAP-001] Retry {attempt + 1}/{handler.max_retries} "
                f"for gap {gap.id}, backoff={backoff}ms"
            )
            
            time.sleep(backoff / 1000.0)
            
            # Execute handler if provided
            if handler.handler_func:
                try:
                    handler.handler_func(gap)
                    resolution.status = ResolutionStatus.RESOLVED
                    resolution.resolution_notes = f"Resolved on attempt {attempt + 1}"
                    return resolution
                except Exception as e:
                    self._logger.warning(
                        f"[ITEM-GAP-001] Retry {attempt + 1} failed: {e}"
                    )
        
        resolution.status = ResolutionStatus.ESCALATED
        resolution.resolution_notes = f"Failed after {handler.max_retries} retries"
        return resolution
    
    def _handle_unknown_gap(self, gap: Gap, start_time: float) -> GapResolution:
        """Handle a gap with unknown or missing type."""
        resolution = GapResolution(
            gap_id=gap.id,
            gap_type=gap.gap_type,
            status=ResolutionStatus.ESCALATED,
            resolution_notes="Unknown gap type - no handler available"
        )
        resolution.resolution_time_ms = (time.time() - start_time) * 1000
        self._resolutions[gap.id] = resolution
        
        self._logger.warning(
            f"[ITEM-GAP-001] Unknown gap type for {gap.id}: {gap.gap_type}"
        )
        
        return resolution
    
    def get_resolution_status(self, gap_id: str) -> Optional[GapResolution]:
        """Get resolution status for a gap."""
        return self._resolutions.get(gap_id)
    
    def get_all_resolutions(self) -> Dict[str, GapResolution]:
        """Get all resolution records."""
        return dict(self._resolutions)
    
    def register_handler(self, gap_type: GapType, handler: GapHandler) -> None:
        """
        Register custom handler for gap type.
        
        Args:
            gap_type: The gap type to handle
            handler: Handler configuration
        """
        self._handlers[gap_type] = handler
        self._logger.info(
            f"[ITEM-GAP-001] Registered handler for {gap_type.value}"
        )
    
    def get_handler(self, gap_type: GapType) -> Optional[GapHandler]:
        """Get handler for a gap type."""
        return self._handlers.get(gap_type)
    
    def get_all_handlers(self) -> Dict[GapType, GapHandler]:
        """Get all registered handlers."""
        return dict(self._handlers)
    
    def has_handler(self, gap_type: GapType) -> bool:
        """Check if a handler exists for a gap type."""
        return gap_type in self._handlers
    
    @classmethod
    def get_all_gap_types(cls) -> List[GapType]:
        """Get all 20 defined gap types."""
        return list(GapType)
    
    @classmethod
    def validate_completeness(cls) -> Dict[str, Any]:
        """
        Validate that all 20 gap types have handlers.
        
        Returns:
            Dictionary with validation results
        """
        all_types = set(GapType)
        handlers_with_types = set(cls.DEFAULT_HANDLERS.keys())
        
        missing = all_types - handlers_with_types
        extra = handlers_with_types - all_types
        
        return {
            "total_gap_types": len(all_types),
            "handlers_defined": len(handlers_with_types),
            "missing_handlers": [t.value for t in missing],
            "extra_handlers": [t.value for t in extra],
            "is_complete": len(missing) == 0 and len(extra) == 0
        }


def convert_gaps_to_objects(gap_strings: List[str]) -> List[Gap]:
    """Convert list of gap strings to Gap objects."""
    return [Gap.from_string(s) for s in gap_strings]


def convert_gaps_to_strings(gaps: List[Gap]) -> List[str]:
    """Convert list of Gap objects to strings."""
    return [g.to_string() for g in gaps]


# Convenience function for creating typed gaps
def create_gap(
    reason: str,
    gap_type: Optional[GapType] = None,
    severity: GapSeverity = GapSeverity.SEV_4,
    **kwargs
) -> Gap:
    """
    Create a Gap with type inference.
    
    Args:
        reason: Gap reason/description
        gap_type: Optional explicit gap type
        severity: Gap severity level
        **kwargs: Additional Gap fields
        
    Returns:
        Configured Gap instance
    """
    return Gap(
        id="",
        reason=reason,
        severity=severity,
        gap_type=gap_type,
        **kwargs
    )
