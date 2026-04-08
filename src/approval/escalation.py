"""
ITEM-OPS-139: Human-in-the-Loop Escalation Protocol.

This module provides structured escalation with SLA tracking for
human-in-the-loop decision making in the TITAN FUSE Protocol.

Features:
- Structured escalation record format with context and decision capture
- SLA tracking with configurable time thresholds per escalation level
- Auto-escalation on SLA breach
- Thread-safe implementation
- Complete audit trail of escalation decisions

SLA Levels:
    L1 (Critical): 15 minutes
    L2 (High): 1 hour
    L3 (Medium): 4 hours

Author: TITAN FUSE Team
Version: 3.4.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
import logging
import threading
import uuid

from src.utils.timezone import now_utc, now_utc_iso, to_iso8601


class EscalationStatus(Enum):
    """Status of an escalation record."""
    PENDING = "pending"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class Severity(Enum):
    """Severity levels for escalations."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class EscalationOption:
    """
    Represents an option available for an escalation decision.

    Attributes:
        id: Unique identifier for this option
        label: Human-readable label for the option
        description: Detailed description of what this option entails
        risk_level: Risk level associated with this option (low/medium/high/critical)
        recommended: Whether this option is recommended
        consequences: Description of consequences if this option is chosen
    """
    id: str
    label: str
    description: str
    risk_level: str = "medium"
    recommended: bool = False
    consequences: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "risk_level": self.risk_level,
            "recommended": self.recommended,
            "consequences": self.consequences,
        }


@dataclass
class EscalationRecord:
    """
    Represents an escalation record with full context and decision tracking.

    ITEM-OPS-139 Implementation:
    Structured format for capturing escalation context, options, and decisions.

    Attributes:
        id: Unique identifier for this escalation
        timestamp: When the escalation was created (ISO8601 format)
        context: Dictionary containing context for the escalation
        severity: Severity level of this escalation
        options: List of available options for decision
        selected_option: ID of the option that was selected (if any)
        reviewer: Identifier of the reviewer who made the decision
        rationale: Explanation for the decision
        sla_deadline: ISO8601 timestamp for SLA deadline
        escalation_level: Current escalation level (1, 2, or 3)
        status: Current status of the escalation
        created_at: ISO8601 timestamp when record was created
        resolved_at: ISO8601 timestamp when record was resolved (if applicable)
        metadata: Additional metadata for the escalation
    """
    id: str
    timestamp: str
    context: Dict[str, Any]
    severity: str
    options: List[EscalationOption] = field(default_factory=list)
    selected_option: Optional[str] = None
    reviewer: Optional[str] = None
    rationale: Optional[str] = None
    sla_deadline: str = ""
    escalation_level: int = 1
    status: EscalationStatus = EscalationStatus.PENDING
    created_at: str = field(default_factory=now_utc_iso)
    resolved_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "context": self.context,
            "severity": self.severity,
            "options": [opt.to_dict() for opt in self.options],
            "selected_option": self.selected_option,
            "reviewer": self.reviewer,
            "rationale": self.rationale,
            "sla_deadline": self.sla_deadline,
            "escalation_level": self.escalation_level,
            "status": self.status.value,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EscalationRecord":
        """Create an EscalationRecord from a dictionary."""
        options = [
            EscalationOption(**opt) if isinstance(opt, dict) else opt
            for opt in data.get("options", [])
        ]
        return cls(
            id=data["id"],
            timestamp=data["timestamp"],
            context=data.get("context", {}),
            severity=data.get("severity", "medium"),
            options=options,
            selected_option=data.get("selected_option"),
            reviewer=data.get("reviewer"),
            rationale=data.get("rationale"),
            sla_deadline=data.get("sla_deadline", ""),
            escalation_level=data.get("escalation_level", 1),
            status=EscalationStatus(data.get("status", "pending")),
            created_at=data.get("created_at", now_utc_iso()),
            resolved_at=data.get("resolved_at"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SLAStatus:
    """
    Represents the SLA status for an escalation.

    Attributes:
        escalation_id: ID of the associated escalation
        level: Current escalation level
        deadline: ISO8601 timestamp of the SLA deadline
        time_remaining: Seconds remaining until SLA breach (negative if breached)
        is_breached: Whether the SLA has been breached
        is_warning: Whether the escalation is close to breach (80% of time elapsed)
        warning_threshold: Threshold for warning (default 0.8 = 80%)
    """
    escalation_id: str
    level: int
    deadline: str
    time_remaining: float
    is_breached: bool
    is_warning: bool
    warning_threshold: float = 0.8

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "escalation_id": self.escalation_id,
            "level": self.level,
            "deadline": self.deadline,
            "time_remaining": self.time_remaining,
            "is_breached": self.is_breached,
            "is_warning": self.is_warning,
            "warning_threshold": self.warning_threshold,
        }


# SLA configuration by escalation level
SLA_DURATIONS: Dict[int, timedelta] = {
    1: timedelta(minutes=15),   # L1: 15 minutes (critical)
    2: timedelta(hours=1),      # L2: 1 hour (high)
    3: timedelta(hours=4),      # L3: 4 hours (medium)
}


class EscalationProtocol:
    """
    Escalation protocol with structured records and SLA tracking.

    ITEM-OPS-139 Implementation:

    Provides structured escalation with:
    - Context and options capture
    - Decision tracking with reviewer and rationale
    - SLA monitoring per escalation level
    - Auto-escalation on SLA breach

    Thread Safety:
        All operations are thread-safe using a lock.

    Usage:
        >>> protocol = EscalationProtocol()
        >>>
        >>> # Create an escalation
        >>> options = [
        ...     EscalationOption(
        ...         id="approve",
        ...         label="Approve",
        ...         description="Approve the request",
        ...         risk_level="low",
        ...         recommended=True
        ...     ),
        ...     EscalationOption(
        ...         id="reject",
        ...         label="Reject",
        ...         description="Reject the request",
        ...         risk_level="medium"
        ...     )
        ... ]
        >>> record = protocol.create_escalation(
        ...     context={"request_id": "REQ-123", "user": "alice"},
        ...     severity="high",
        ...     options=options,
        ...     level=1
        ... )
        >>>
        >>> # Check SLA status
        >>> sla_status = protocol.check_sla(record.id)
        >>> if sla_status.is_breached:
        ...     auto_escalated = protocol.auto_escalate_breached()
        >>>
        >>> # Capture decision
        >>> protocol.capture_decision(
        ...     escalation_id=record.id,
        ...     selected_option="approve",
        ...     reviewer="bob",
        ...     rationale="Request meets all criteria"
        ... )
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the EscalationProtocol.

        Args:
            config: Optional configuration dictionary with:
                - sla_durations: Dict mapping level to timedelta
                - warning_threshold: Float for SLA warning threshold (default 0.8)
                - auto_escalate: Whether to auto-escalate on breach (default True)
        """
        self._config = config or {}
        self._lock = threading.RLock()

        # Override SLA durations if provided
        self._sla_durations = SLA_DURATIONS.copy()
        if "sla_durations" in self._config:
            for level, duration in self._config["sla_durations"].items():
                self._sla_durations[level] = duration

        # Configuration options
        self._warning_threshold = self._config.get("warning_threshold", 0.8)
        self._auto_escalate_enabled = self._config.get("auto_escalate", True)

        # Storage
        self._escalations: Dict[str, EscalationRecord] = {}

        # Logger
        self._logger = logging.getLogger(__name__)
        self._logger.info(
            "EscalationProtocol initialized with SLA durations: %s",
            {k: str(v) for k, v in self._sla_durations.items()}
        )

    def create_escalation(
        self,
        context: Dict[str, Any],
        severity: str,
        options: Optional[List[EscalationOption]] = None,
        level: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EscalationRecord:
        """
        Create a new escalation record.

        Args:
            context: Dictionary containing context for the escalation
            severity: Severity level (critical, high, medium, low)
            options: List of available options for decision
            level: Escalation level (1, 2, or 3)
            metadata: Additional metadata for the escalation

        Returns:
            The created EscalationRecord

        Raises:
            ValueError: If level is not in valid range
        """
        if level not in self._sla_durations:
            raise ValueError(
                f"Invalid escalation level: {level}. "
                f"Valid levels: {list(self._sla_durations.keys())}"
            )

        with self._lock:
            # Generate ID
            escalation_id = f"ESC-{uuid.uuid4().hex[:12]}"

            # Calculate SLA deadline
            now = now_utc()
            duration = self._sla_durations[level]
            deadline = now + duration

            # Create record
            record = EscalationRecord(
                id=escalation_id,
                timestamp=now_utc_iso(),
                context=context,
                severity=severity,
                options=options or [],
                escalation_level=level,
                sla_deadline=to_iso8601(deadline),
                status=EscalationStatus.PENDING,
                metadata=metadata or {},
            )

            # Store record
            self._escalations[escalation_id] = record

            self._logger.info(
                "Created escalation %s (level=%d, severity=%s, deadline=%s)",
                escalation_id, level, severity, record.sla_deadline
            )

            return record

    def present_options(self, escalation_id: str) -> List[EscalationOption]:
        """
        Get the available options for an escalation.

        Args:
            escalation_id: ID of the escalation

        Returns:
            List of EscalationOption objects

        Raises:
            KeyError: If escalation not found
        """
        with self._lock:
            record = self._escalations.get(escalation_id)
            if not record:
                raise KeyError(f"Escalation not found: {escalation_id}")

            return list(record.options)

    def capture_decision(
        self,
        escalation_id: str,
        selected_option: str,
        reviewer: str,
        rationale: str,
    ) -> bool:
        """
        Capture a decision for an escalation.

        Args:
            escalation_id: ID of the escalation
            selected_option: ID of the selected option
            reviewer: Identifier of the reviewer
            rationale: Explanation for the decision

        Returns:
            True if decision was captured successfully

        Raises:
            KeyError: If escalation not found
            ValueError: If escalation is not pending or selected option is invalid
        """
        with self._lock:
            record = self._escalations.get(escalation_id)
            if not record:
                raise KeyError(f"Escalation not found: {escalation_id}")

            if record.status != EscalationStatus.PENDING:
                raise ValueError(
                    f"Escalation {escalation_id} is not pending "
                    f"(current status: {record.status.value})"
                )

            # Validate selected option
            option_ids = [opt.id for opt in record.options]
            if option_ids and selected_option not in option_ids:
                raise ValueError(
                    f"Invalid option '{selected_option}'. "
                    f"Valid options: {option_ids}"
                )

            # Update record
            record.selected_option = selected_option
            record.reviewer = reviewer
            record.rationale = rationale
            record.status = EscalationStatus.RESOLVED
            record.resolved_at = now_utc_iso()

            self._logger.info(
                "Captured decision for escalation %s: option=%s, reviewer=%s",
                escalation_id, selected_option, reviewer
            )

            return True

    def get_escalation_history(
        self,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[EscalationRecord]:
        """
        Get escalation history with optional filtering.

        Args:
            filters: Optional dictionary of filters:
                - status: Filter by status
                - severity: Filter by severity
                - level: Filter by escalation level
                - reviewer: Filter by reviewer
                - from_timestamp: Filter escalations after this timestamp
                - to_timestamp: Filter escalations before this timestamp

        Returns:
            List of EscalationRecord objects matching filters
        """
        with self._lock:
            records = list(self._escalations.values())

        if not filters:
            return records

        # Apply filters
        if "status" in filters:
            status_filter = filters["status"]
            if isinstance(status_filter, str):
                status_filter = EscalationStatus(status_filter)
            records = [r for r in records if r.status == status_filter]

        if "severity" in filters:
            records = [r for r in records if r.severity == filters["severity"]]

        if "level" in filters:
            records = [r for r in records if r.escalation_level == filters["level"]]

        if "reviewer" in filters:
            records = [r for r in records if r.reviewer == filters["reviewer"]]

        if "from_timestamp" in filters:
            from_ts = filters["from_timestamp"]
            records = [r for r in records if r.timestamp >= from_ts]

        if "to_timestamp" in filters:
            to_ts = filters["to_timestamp"]
            records = [r for r in records if r.timestamp <= to_ts]

        # Sort by timestamp descending (most recent first)
        records.sort(key=lambda r: r.timestamp, reverse=True)

        return records

    def check_sla(self, escalation_id: str) -> SLAStatus:
        """
        Check the SLA status for an escalation.

        Args:
            escalation_id: ID of the escalation

        Returns:
            SLAStatus object with current SLA information

        Raises:
            KeyError: If escalation not found
        """
        with self._lock:
            record = self._escalations.get(escalation_id)
            if not record:
                raise KeyError(f"Escalation not found: {escalation_id}")

            return self._compute_sla_status(record)

    def check_all_slas(self) -> List[SLAStatus]:
        """
        Check SLA status for all pending escalations.

        Returns:
            List of SLAStatus objects for all pending escalations
        """
        with self._lock:
            pending = [
                r for r in self._escalations.values()
                if r.status == EscalationStatus.PENDING
            ]

        return [self._compute_sla_status(record) for record in pending]

    def auto_escalate_breached(self) -> List[EscalationRecord]:
        """
        Auto-escalate all pending escalations with breached SLA.

        Escalations are moved to the next level (up to level 3).
        If already at level 3, the status is changed to EXPIRED.

        Returns:
            List of EscalationRecord objects that were escalated/expired
        """
        if not self._auto_escalate_enabled:
            return []

        escalated_records = []

        with self._lock:
            for record in list(self._escalations.values()):
                if record.status != EscalationStatus.PENDING:
                    continue

                sla_status = self._compute_sla_status(record)

                if sla_status.is_breached:
                    if record.escalation_level < 3:
                        # Escalate to next level
                        new_level = record.escalation_level + 1
                        old_level = record.escalation_level

                        # Calculate new deadline
                        duration = self._sla_durations[new_level]
                        new_deadline = now_utc() + duration

                        record.escalation_level = new_level
                        record.sla_deadline = to_iso8601(new_deadline)
                        record.status = EscalationStatus.ESCALATED

                        # Reset status to pending for the new level
                        record.status = EscalationStatus.PENDING

                        self._logger.warning(
                            "Auto-escalated %s from L%d to L%d (new deadline: %s)",
                            record.id, old_level, new_level, record.sla_deadline
                        )
                    else:
                        # Already at max level, mark as expired
                        record.status = EscalationStatus.EXPIRED
                        record.resolved_at = now_utc_iso()

                        self._logger.error(
                            "Escalation %s expired (breached at L3)",
                            record.id
                        )

                    escalated_records.append(record)

        return escalated_records

    def get_escalation(self, escalation_id: str) -> EscalationRecord:
        """
        Get an escalation by ID.

        Args:
            escalation_id: ID of the escalation

        Returns:
            The EscalationRecord

        Raises:
            KeyError: If escalation not found
        """
        with self._lock:
            record = self._escalations.get(escalation_id)
            if not record:
                raise KeyError(f"Escalation not found: {escalation_id}")
            return record

    def cancel_escalation(
        self,
        escalation_id: str,
        reason: str,
        cancelled_by: Optional[str] = None,
    ) -> bool:
        """
        Cancel an escalation.

        Args:
            escalation_id: ID of the escalation
            reason: Reason for cancellation
            cancelled_by: Identifier of who cancelled

        Returns:
            True if cancellation was successful

        Raises:
            KeyError: If escalation not found
            ValueError: If escalation is not pending
        """
        with self._lock:
            record = self._escalations.get(escalation_id)
            if not record:
                raise KeyError(f"Escalation not found: {escalation_id}")

            if record.status != EscalationStatus.PENDING:
                raise ValueError(
                    f"Escalation {escalation_id} is not pending "
                    f"(current status: {record.status.value})"
                )

            record.status = EscalationStatus.CANCELLED
            record.resolved_at = now_utc_iso()
            record.metadata["cancellation_reason"] = reason
            if cancelled_by:
                record.metadata["cancelled_by"] = cancelled_by

            self._logger.info(
                "Cancelled escalation %s: reason=%s",
                escalation_id, reason
            )

            return True

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about escalations.

        Returns:
            Dictionary with escalation statistics
        """
        with self._lock:
            records = list(self._escalations.values())

        total = len(records)
        if total == 0:
            return {
                "total": 0,
                "by_status": {},
                "by_level": {},
                "by_severity": {},
            }

        # Count by status
        by_status: Dict[str, int] = {}
        for record in records:
            status = record.status.value
            by_status[status] = by_status.get(status, 0) + 1

        # Count by level
        by_level: Dict[int, int] = {}
        for record in records:
            level = record.escalation_level
            by_level[level] = by_level.get(level, 0) + 1

        # Count by severity
        by_severity: Dict[str, int] = {}
        for record in records:
            severity = record.severity
            by_severity[severity] = by_severity.get(severity, 0) + 1

        # Calculate average resolution time for resolved escalations
        resolved = [r for r in records if r.status == EscalationStatus.RESOLVED]
        avg_resolution_time = None
        if resolved:
            times = []
            for r in resolved:
                if r.resolved_at and r.created_at:
                    from src.utils.timezone import from_iso8601
                    resolved_dt = from_iso8601(r.resolved_at)
                    created_dt = from_iso8601(r.created_at)
                    times.append((resolved_dt - created_dt).total_seconds())
            if times:
                avg_resolution_time = sum(times) / len(times)

        return {
            "total": total,
            "by_status": by_status,
            "by_level": by_level,
            "by_severity": by_severity,
            "pending_count": by_status.get("pending", 0),
            "resolved_count": by_status.get("resolved", 0),
            "expired_count": by_status.get("expired", 0),
            "avg_resolution_time_seconds": avg_resolution_time,
        }

    def _compute_sla_status(self, record: EscalationRecord) -> SLAStatus:
        """
        Compute the SLA status for a record.

        Args:
            record: The escalation record

        Returns:
            SLAStatus object
        """
        from src.utils.timezone import from_iso8601

        deadline = from_iso8601(record.sla_deadline)
        now = now_utc()

        time_remaining = (deadline - now).total_seconds()
        is_breached = time_remaining <= 0

        # Calculate if warning threshold is crossed
        is_warning = False
        if not is_breached and record.escalation_level in self._sla_durations:
            total_duration = self._sla_durations[record.escalation_level].total_seconds()
            elapsed = total_duration - time_remaining
            elapsed_ratio = elapsed / total_duration
            is_warning = elapsed_ratio >= self._warning_threshold

        return SLAStatus(
            escalation_id=record.id,
            level=record.escalation_level,
            deadline=record.sla_deadline,
            time_remaining=time_remaining,
            is_breached=is_breached,
            is_warning=is_warning,
            warning_threshold=self._warning_threshold,
        )


def create_escalation_protocol(
    config: Optional[Dict[str, Any]] = None,
) -> EscalationProtocol:
    """
    Factory function to create an EscalationProtocol.

    Args:
        config: Optional configuration dictionary

    Returns:
        Configured EscalationProtocol instance
    """
    return EscalationProtocol(config=config)
