"""
Drift Policy Module for TITAN FUSE Protocol.

ITEM-ARCH-16: External State Drift Policy

Provides configurable conflict resolution policies for handling external
state modifications detected during cursor hash verification.

Features:
- ConflictPolicy enum (FAIL, CLOBBER, MERGE, BRANCH)
- DriftReport dataclass for detailed drift information
- DriftPolicyHandler for policy-based conflict resolution
- Integration with CursorTracker and EventBus

Author: TITAN FUSE Team
Version: 3.7.0
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..events.event_bus import EventBus, EventSeverity


class ConflictPolicy(Enum):
    """
    Policy for handling external state drift conflicts.

    FAIL: Abort operation on drift, raise DriftDetectedError
    CLOBBER: Overwrite external changes with local state
    MERGE: Attempt automatic merge of changes
    BRANCH: Create divergent branch for manual resolution
    """
    FAIL = "FAIL"
    CLOBBER = "CLOBBER"
    MERGE = "MERGE"
    BRANCH = "BRANCH"


@dataclass
class DriftReport:
    """
    Report of detected state drift.

    Contains all information about the detected drift including
    the local and external state hashes, affected keys, and
    resolution information.
    """
    detected_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    local_hash: str = ""
    external_hash: str = ""
    diff_summary: Dict[str, Any] = field(default_factory=dict)
    affected_keys: List[str] = field(default_factory=list)
    resolution: Optional[str] = None
    drift_id: str = field(default_factory=lambda: f"drift-{uuid.uuid4().hex[:8]}")

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "drift_id": self.drift_id,
            "detected_at": self.detected_at,
            "local_hash": self.local_hash,
            "external_hash": self.external_hash,
            "diff_summary": self.diff_summary,
            "affected_keys": self.affected_keys,
            "resolution": self.resolution
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'DriftReport':
        """Create from dictionary."""
        return cls(
            drift_id=data.get("drift_id", f"drift-{uuid.uuid4().hex[:8]}"),
            detected_at=data.get("detected_at", datetime.utcnow().isoformat() + "Z"),
            local_hash=data.get("local_hash", ""),
            external_hash=data.get("external_hash", ""),
            diff_summary=data.get("diff_summary", {}),
            affected_keys=data.get("affected_keys", []),
            resolution=data.get("resolution")
        )


@dataclass
class ActionResult:
    """
    Result of applying a drift policy action.

    Contains the outcome of conflict resolution including
    success status, any merged state, and branch information.
    """
    success: bool
    policy_applied: ConflictPolicy
    message: str
    merged_state: Optional[Dict] = None
    branch_id: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "policy_applied": self.policy_applied.value,
            "message": self.message,
            "merged_state": self.merged_state,
            "branch_id": self.branch_id,
            "error": self.error,
            "timestamp": self.timestamp
        }


class DriftDetectedError(Exception):
    """Exception raised when drift is detected under FAIL policy."""

    def __init__(self, report: DriftReport):
        self.report = report
        super().__init__(
            f"State drift detected: local={report.local_hash}, external={report.external_hash}. "
            f"Affected keys: {report.affected_keys}"
        )


class MergeConflictError(Exception):
    """Exception raised when automatic merge fails."""

    def __init__(self, key: str, local_value: Any, external_value: Any):
        self.key = key
        self.local_value = local_value
        self.external_value = external_value
        super().__init__(
            f"Cannot merge conflicting values for key '{key}': "
            f"local={local_value}, external={external_value}"
        )


class DriftPolicyHandler:
    """
    Handler for state drift detection and resolution.

    ITEM-ARCH-16 Implementation:
    - detect_drift(): Compare current and external state
    - apply_policy(): Execute conflict resolution policy
    - resolve_conflict(): Handle individual field conflicts
    - create_branch(): Create divergent branch for manual resolution
    - _merge_states(): Field-by-field merge with conflict detection
    - _merge_field(): Single field merge with type awareness

    Usage:
        handler = DriftPolicyHandler(event_bus=event_bus)

        # Detect drift
        report = handler.detect_drift(local_state, external_state)

        if report is not None:
            # Apply policy
            result = handler.apply_policy(ConflictPolicy.MERGE, report)
    """

    # Event types for EventBus integration
    STATE_DRIFT = "STATE_DRIFT"
    DRIFT_RESOLVED = "DRIFT_RESOLVED"
    BRANCH_CREATED = "BRANCH_CREATED"

    def __init__(
        self,
        event_bus: 'EventBus' = None,
        merge_strategy: str = "local",
        conflict_resolution: str = "manual"
    ):
        """
        Initialize drift policy handler.

        Args:
            event_bus: Optional EventBus for emitting drift events
            merge_strategy: Strategy for merges - "local", "external", "newer"
            conflict_resolution: How to handle merge conflicts - "manual", "prefer_local", "prefer_external"
        """
        self._event_bus = event_bus
        self._merge_strategy = merge_strategy
        self._conflict_resolution = conflict_resolution
        self._branches: Dict[str, Dict] = {}
        self._drift_history: List[DriftReport] = []

    def detect_drift(
        self,
        local: Dict,
        external: Dict,
        local_hash: str = None,
        external_hash: str = None
    ) -> Optional[DriftReport]:
        """
        Detect drift between local and external state.

        Compares two state dictionaries and returns a DriftReport
        if differences are detected.

        Args:
            local: Local state dictionary
            external: External state dictionary
            local_hash: Optional hash of local state
            external_hash: Optional hash of external state

        Returns:
            DriftReport if drift detected, None otherwise
        """
        # Compute hashes if not provided
        if local_hash is None:
            local_hash = self._compute_hash(local)
        if external_hash is None:
            external_hash = self._compute_hash(external)

        # Quick check: if hashes match, no drift
        if local_hash == external_hash:
            return None

        # Find differences
        diff_summary = self._compute_diff(local, external)
        affected_keys = list(diff_summary.keys())

        report = DriftReport(
            local_hash=local_hash,
            external_hash=external_hash,
            diff_summary=diff_summary,
            affected_keys=affected_keys
        )

        # Record drift
        self._drift_history.append(report)

        # Emit STATE_DRIFT event
        if self._event_bus:
            from ..events.event_bus import EventSeverity
            self._event_bus.emit_simple(
                self.STATE_DRIFT,
                report.to_dict(),
                EventSeverity.WARN,
                source="DriftPolicyHandler"
            )

        return report

    def apply_policy(
        self,
        policy: ConflictPolicy,
        report: DriftReport,
        local: Dict,
        external: Dict
    ) -> ActionResult:
        """
        Apply conflict resolution policy to drift.

        Args:
            policy: The ConflictPolicy to apply
            report: The DriftReport describing the drift
            local: Local state dictionary
            external: External state dictionary

        Returns:
            ActionResult with the outcome of policy application
        """
        try:
            if policy == ConflictPolicy.FAIL:
                return self._apply_fail_policy(report)
            elif policy == ConflictPolicy.CLOBBER:
                return self._apply_clobber_policy(report, local)
            elif policy == ConflictPolicy.MERGE:
                return self._apply_merge_policy(report, local, external)
            elif policy == ConflictPolicy.BRANCH:
                return self._apply_branch_policy(report, local, external)
            else:
                return ActionResult(
                    success=False,
                    policy_applied=policy,
                    message=f"Unknown policy: {policy}",
                    error="InvalidPolicy"
                )
        except DriftDetectedError:
            # Re-raise DriftDetectedError without wrapping
            raise
        except Exception as e:
            return ActionResult(
                success=False,
                policy_applied=policy,
                message=f"Policy application failed: {str(e)}",
                error=str(e)
            )

    def _apply_fail_policy(self, report: DriftReport) -> ActionResult:
        """
        Apply FAIL policy: abort and raise error.

        Args:
            report: The DriftReport

        Returns:
            ActionResult (never actually returned, raises error)
        """
        # Update report resolution
        report.resolution = "FAILED"

        # Emit DRIFT_RESOLVED event
        self._emit_resolved_event(report, "FAIL", False)

        # Raise error
        raise DriftDetectedError(report)

    def _apply_clobber_policy(
        self,
        report: DriftReport,
        local: Dict
    ) -> ActionResult:
        """
        Apply CLOBBER policy: overwrite external with local.

        Args:
            report: The DriftReport
            local: Local state (will be used)

        Returns:
            ActionResult with success
        """
        report.resolution = "CLOBBERED"

        # Emit DRIFT_RESOLVED event
        self._emit_resolved_event(report, "CLOBBER", True)

        return ActionResult(
            success=True,
            policy_applied=ConflictPolicy.CLOBBER,
            message="External state overwritten with local state",
            merged_state=local
        )

    def _apply_merge_policy(
        self,
        report: DriftReport,
        local: Dict,
        external: Dict
    ) -> ActionResult:
        """
        Apply MERGE policy: attempt automatic merge.

        Args:
            report: The DriftReport
            local: Local state
            external: External state

        Returns:
            ActionResult with merged state
        """
        try:
            merged = self._merge_states(local, external)
            report.resolution = "MERGED"

            # Emit DRIFT_RESOLVED event
            self._emit_resolved_event(report, "MERGE", True)

            return ActionResult(
                success=True,
                policy_applied=ConflictPolicy.MERGE,
                message="States merged successfully",
                merged_state=merged
            )
        except MergeConflictError as e:
            report.resolution = "MERGE_FAILED"

            # Emit DRIFT_RESOLVED event
            self._emit_resolved_event(report, "MERGE", False, str(e))

            return ActionResult(
                success=False,
                policy_applied=ConflictPolicy.MERGE,
                message=f"Merge failed: {str(e)}",
                error=str(e)
            )

    def _apply_branch_policy(
        self,
        report: DriftReport,
        local: Dict,
        external: Dict
    ) -> ActionResult:
        """
        Apply BRANCH policy: create divergent branch.

        Args:
            report: The DriftReport
            local: Local state
            external: External state

        Returns:
            ActionResult with branch ID
        """
        branch_id = self.create_branch(report, local, external)
        report.resolution = f"BRANCHED:{branch_id}"

        # Emit events
        self._emit_resolved_event(report, "BRANCH", True)
        if self._event_bus:
            from ..events.event_bus import EventSeverity
            # Use WARN severity for synchronous dispatch
            self._event_bus.emit_simple(
                self.BRANCH_CREATED,
                {
                    "branch_id": branch_id,
                    "drift_id": report.drift_id,
                    "local_hash": report.local_hash,
                    "external_hash": report.external_hash
                },
                EventSeverity.WARN,  # WARN for sync dispatch
                source="DriftPolicyHandler"
            )

        return ActionResult(
            success=True,
            policy_applied=ConflictPolicy.BRANCH,
            message=f"Divergent branch created: {branch_id}",
            branch_id=branch_id
        )

    def resolve_conflict(
        self,
        key: str,
        local_value: Any,
        external_value: Any
    ) -> Any:
        """
        Resolve a single field conflict.

        Uses the configured conflict_resolution strategy.

        Args:
            key: The conflicting key
            local_value: Value in local state
            external_value: Value in external state

        Returns:
            The resolved value
        """
        if self._conflict_resolution == "prefer_local":
            return local_value
        elif self._conflict_resolution == "prefer_external":
            return external_value
        elif self._conflict_resolution == "manual":
            raise MergeConflictError(key, local_value, external_value)
        else:
            # Default to manual
            raise MergeConflictError(key, local_value, external_value)

    def create_branch(
        self,
        report: DriftReport,
        local: Dict,
        external: Dict
    ) -> str:
        """
        Create a divergent branch for manual resolution.

        Args:
            report: The DriftReport
            local: Local state
            external: External state

        Returns:
            Branch ID for later resolution
        """
        branch_id = f"branch-{uuid.uuid4().hex[:8]}"

        self._branches[branch_id] = {
            "branch_id": branch_id,
            "drift_id": report.drift_id,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "local_state": local,
            "external_state": external,
            "resolved": False,
            "resolution": None
        }

        return branch_id

    def get_branch(self, branch_id: str) -> Optional[Dict]:
        """
        Get branch information.

        Args:
            branch_id: The branch ID

        Returns:
            Branch dictionary or None if not found
        """
        return self._branches.get(branch_id)

    def resolve_branch(
        self,
        branch_id: str,
        resolution: str,
        resolved_state: Dict = None
    ) -> bool:
        """
        Resolve a branch with the chosen state.

        Args:
            branch_id: The branch ID
            resolution: "local", "external", or "merged"
            resolved_state: Optional merged state if resolution is "merged"

        Returns:
            True if resolved successfully
        """
        branch = self._branches.get(branch_id)
        if not branch:
            return False

        branch["resolved"] = True
        branch["resolution"] = resolution
        branch["resolved_at"] = datetime.utcnow().isoformat() + "Z"

        if resolution == "local":
            branch["final_state"] = branch["local_state"]
        elif resolution == "external":
            branch["final_state"] = branch["external_state"]
        elif resolution == "merged":
            branch["final_state"] = resolved_state

        return True

    def _merge_states(
        self,
        local: Dict,
        external: Dict
    ) -> Dict:
        """
        Merge local and external states field by field.

        Args:
            local: Local state dictionary
            external: External state dictionary

        Returns:
            Merged state dictionary
        """
        result = external.copy()
        conflicts = []

        for key, local_value in local.items():
            if key in external:
                external_value = external[key]

                if external_value != local_value:
                    # Conflict detected
                    conflicts.append(key)
                    result[key] = self._merge_field(key, local_value, external_value)
            else:
                # Key only in local
                result[key] = local_value

        return result

    def _merge_field(
        self,
        key: str,
        local_value: Any,
        external_value: Any
    ) -> Any:
        """
        Merge a single field based on merge strategy.

        Args:
            key: Field key
            local_value: Local value
            external_value: External value

        Returns:
            Merged value
        """
        # If values are the same, return either
        if local_value == external_value:
            return local_value

        # Handle dictionaries recursively
        if isinstance(local_value, dict) and isinstance(external_value, dict):
            return self._merge_states(local_value, external_value)

        # Handle lists - concatenate unique values
        if isinstance(local_value, list) and isinstance(external_value, list):
            return self._merge_lists(local_value, external_value)

        # Apply merge strategy for simple values
        if self._merge_strategy == "local":
            return local_value
        elif self._merge_strategy == "external":
            return external_value
        elif self._merge_strategy == "newer":
            # Check for timestamp in key name
            if "timestamp" in key.lower() or "at" in key.lower():
                # Compare timestamps (assuming ISO format)
                try:
                    local_ts = datetime.fromisoformat(local_value.replace("Z", "+00:00"))
                    external_ts = datetime.fromisoformat(external_value.replace("Z", "+00:00"))
                    return local_value if local_ts > external_ts else external_value
                except (ValueError, AttributeError):
                    pass
            # Default to local for non-timestamp fields
            return local_value

        # Use conflict resolution strategy
        return self.resolve_conflict(key, local_value, external_value)

    def _merge_lists(
        self,
        local: List,
        external: List
    ) -> List:
        """
        Merge two lists, preserving unique values.

        Args:
            local: Local list
            external: External list

        Returns:
            Merged list
        """
        # For simple lists, combine and deduplicate
        if all(not isinstance(item, (dict, list)) for item in local + external):
            seen = set()
            result = []
            for item in external + local:  # External first, then local
                item_hash = str(item)
                if item_hash not in seen:
                    seen.add(item_hash)
                    result.append(item)
            return result

        # For complex lists, prefer external (or could implement smarter merge)
        return external + [item for item in local if item not in external]

    def _compute_hash(self, state: Dict) -> str:
        """Compute SHA-256 hash of state."""
        state_json = json.dumps(state, sort_keys=True, default=str)
        return hashlib.sha256(state_json.encode('utf-8')).hexdigest()[:32]

    def _compute_diff(
        self,
        local: Dict,
        external: Dict
    ) -> Dict[str, Any]:
        """
        Compute differences between local and external states.

        Args:
            local: Local state
            external: External state

        Returns:
            Dictionary of differences
        """
        diff = {}

        # Keys in local but not external
        for key in local:
            if key not in external:
                diff[key] = {
                    "status": "local_only",
                    "local_value": local[key]
                }
            elif local[key] != external[key]:
                diff[key] = {
                    "status": "conflict",
                    "local_value": local[key],
                    "external_value": external[key]
                }

        # Keys in external but not local
        for key in external:
            if key not in local:
                diff[key] = {
                    "status": "external_only",
                    "external_value": external[key]
                }

        return diff

    def _emit_resolved_event(
        self,
        report: DriftReport,
        policy: str,
        success: bool,
        error: str = None
    ) -> None:
        """Emit DRIFT_RESOLVED event."""
        if self._event_bus:
            from ..events.event_bus import EventSeverity
            self._event_bus.emit_simple(
                self.DRIFT_RESOLVED,
                {
                    "drift_id": report.drift_id,
                    "policy": policy,
                    "success": success,
                    "error": error,
                    "affected_keys": report.affected_keys
                },
                EventSeverity.INFO if success else EventSeverity.WARN,
                source="DriftPolicyHandler"
            )

    def set_event_bus(self, event_bus: 'EventBus') -> None:
        """Set the EventBus for event emission."""
        self._event_bus = event_bus

    def set_merge_strategy(self, strategy: str) -> None:
        """Set the merge strategy."""
        if strategy in ("local", "external", "newer"):
            self._merge_strategy = strategy

    def set_conflict_resolution(self, resolution: str) -> None:
        """Set the conflict resolution strategy."""
        if resolution in ("manual", "prefer_local", "prefer_external"):
            self._conflict_resolution = resolution

    def get_drift_history(self, limit: int = 100) -> List[DriftReport]:
        """Get history of detected drifts."""
        return self._drift_history[-limit:]

    def get_branches(self) -> Dict[str, Dict]:
        """Get all branches."""
        return self._branches.copy()

    def get_stats(self) -> Dict:
        """Get drift policy handler statistics."""
        return {
            "total_drifts_detected": len(self._drift_history),
            "branches_created": len(self._branches),
            "branches_resolved": sum(1 for b in self._branches.values() if b.get("resolved")),
            "merge_strategy": self._merge_strategy,
            "conflict_resolution": self._conflict_resolution
        }


# Convenience function for quick drift detection
def check_state_drift(
    local: Dict,
    external: Dict,
    policy: ConflictPolicy = ConflictPolicy.FAIL
) -> Optional[DriftReport]:
    """
    Quick check for state drift.

    Convenience function for one-off drift detection.
    Does not apply policy, only detects drift.

    Args:
        local: Local state
        external: External state
        policy: Not used, for API consistency

    Returns:
        DriftReport if drift detected, None otherwise
    """
    handler = DriftPolicyHandler()
    return handler.detect_drift(local, external)
