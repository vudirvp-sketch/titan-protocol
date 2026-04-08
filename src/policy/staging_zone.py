"""
TITAN FUSE Protocol - Policy Staging Zone

ITEM-ARCH-10: PolicyStagingZone

Holds tentative policy decisions until clarity threshold is reached.
Policies are staged but not activated until sufficient confidence is achieved.

This prevents the Intent Router from selecting policy at clarity_score < 0.6
before the Clarifier has fully understood the user intent.

Features:
- Stage policies with confidence scores
- Commit policies when confidence >= min_confidence
- Rollback staged policies
- Automatic expiration cleanup
- EventBus integration for POLICY_STAGED, POLICY_COMMITTED, POLICY_ROLLBACK events

Author: TITAN FUSE Team
Version: 3.7.0
"""

import uuid
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from .policy_engine import PolicyEngine
    from ..events.event_bus import EventBus


# =============================================================================
# Exception Classes
# =============================================================================

class NoStagedPolicyError(Exception):
    """
    Raised when attempting to commit or rollback a policy
    that has not been staged for the given intent.
    """
    def __init__(self, intent: str, message: str = None):
        self.intent = intent
        self.message = message or f"No staged policy found for intent: {intent}"
        super().__init__(self.message)


class InsufficientClarityError(Exception):
    """
    Raised when attempting to commit a staged policy
    with confidence below the minimum threshold.
    """
    def __init__(self, confidence: float, min_confidence: float = 0.6, message: str = None):
        self.confidence = confidence
        self.min_confidence = min_confidence
        self.message = message or (
            f"Insufficient clarity to commit policy: "
            f"confidence {confidence:.2f} < minimum {min_confidence:.2f}"
        )
        super().__init__(self.message)


class StagedPolicyExpiredError(Exception):
    """
    Raised when attempting to commit a staged policy
    that has exceeded its time-to-live.
    """
    def __init__(self, intent: str, expired_at: datetime, message: str = None):
        self.intent = intent
        self.expired_at = expired_at
        self.message = message or (
            f"Staged policy for intent '{intent}' expired at {expired_at.isoformat()}Z"
        )
        super().__init__(self.message)


# =============================================================================
# StagedPolicy Dataclass
# =============================================================================

@dataclass
class StagedPolicy:
    """
    A policy that has been staged pending clarity threshold achievement.

    Attributes:
        staged_id: Unique identifier for this staged policy
        intent: The intent this policy is associated with
        policy_id: The ID of the policy to activate
        confidence: Current confidence score (0.0 to 1.0)
        staged_at: When this policy was staged
        expires_at: When this staged policy expires
        metadata: Additional metadata about the staged policy
    """
    intent: str
    policy_id: str
    confidence: float
    staged_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default=None)
    staged_id: str = field(default_factory=lambda: f"staged-{uuid.uuid4().hex[:8]}")
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Set default expiration if not provided."""
        if self.expires_at is None:
            # Default TTL of 1 hour
            self.expires_at = self.staged_at + timedelta(hours=1)

        # Clamp confidence to valid range
        self.confidence = max(0.0, min(1.0, self.confidence))

    def is_expired(self) -> bool:
        """Check if this staged policy has expired."""
        return datetime.utcnow() > self.expires_at

    def is_commitable(self, min_confidence: float = 0.6) -> bool:
        """
        Check if this staged policy can be committed.

        Args:
            min_confidence: Minimum confidence threshold

        Returns:
            True if policy can be committed (not expired, confidence >= threshold)
        """
        return not self.is_expired() and self.confidence >= min_confidence

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "staged_id": self.staged_id,
            "intent": self.intent,
            "policy_id": self.policy_id,
            "confidence": self.confidence,
            "staged_at": self.staged_at.isoformat() + "Z",
            "expires_at": self.expires_at.isoformat() + "Z",
            "metadata": self.metadata,
            "is_expired": self.is_expired(),
            "is_commitable": self.is_commitable()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StagedPolicy":
        """Create from dictionary."""
        staged_at = data.get("staged_at")
        if isinstance(staged_at, str):
            staged_at = datetime.fromisoformat(staged_at.rstrip("Z"))

        expires_at = data.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.rstrip("Z"))

        return cls(
            staged_id=data.get("staged_id", f"staged-{uuid.uuid4().hex[:8]}"),
            intent=data["intent"],
            policy_id=data["policy_id"],
            confidence=data["confidence"],
            staged_at=staged_at or datetime.utcnow(),
            expires_at=expires_at,
            metadata=data.get("metadata", {})
        )


# =============================================================================
# PolicyStagingZone Configuration
# =============================================================================

@dataclass
class StagingZoneConfig:
    """
    Configuration for PolicyStagingZone.

    Attributes:
        min_confidence: Minimum confidence to commit a policy (default: 0.6)
        max_staged: Maximum number of staged policies (default: 100)
        ttl_seconds: Time-to-live for staged policies in seconds (default: 3600)
        cleanup_interval_seconds: Interval for automatic cleanup (default: 300)
    """
    min_confidence: float = 0.6
    max_staged: int = 100
    ttl_seconds: int = 3600
    cleanup_interval_seconds: int = 300

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StagingZoneConfig":
        """Create config from dictionary."""
        return cls(
            min_confidence=data.get("min_confidence", 0.6),
            max_staged=data.get("max_staged", 100),
            ttl_seconds=data.get("ttl_seconds", 3600),
            cleanup_interval_seconds=data.get("cleanup_interval_seconds", 300)
        )


# =============================================================================
# PolicyStagingZone Class
# =============================================================================

class PolicyStagingZone:
    """
    Holds tentative policy decisions until clarity threshold is reached.

    ITEM-ARCH-10: Prevents Intent Router from selecting policy at
    clarity_score < 0.6 before Clarifier has fully understood intent.

    Policies are staged but not activated until sufficient confidence
    is achieved.

    Usage:
        zone = PolicyStagingZone(policy_engine, event_bus, config)

        # Stage a policy with low confidence
        staged_id = zone.stage_policy(
            intent="code_review",
            policy_id="security_scan",
            confidence=0.4
        )

        # Later, when clarity improves, commit the policy
        try:
            policy_id = zone.commit_policy("code_review")
        except InsufficientClarityError:
            # Handle insufficient clarity
            pass

        # Or rollback if needed
        zone.rollback("code_review")

    Event Types:
        - POLICY_STAGED: Emitted when a policy is staged
        - POLICY_COMMITTED: Emitted when a policy is committed
        - POLICY_ROLLBACK: Emitted when a policy is rolled back
    """

    # Event type constants
    EVENT_POLICY_STAGED = "POLICY_STAGED"
    EVENT_POLICY_COMMITTED = "POLICY_COMMITTED"
    EVENT_POLICY_ROLLBACK = "POLICY_ROLLBACK"

    def __init__(
        self,
        policy_engine: "PolicyEngine" = None,
        event_bus: "EventBus" = None,
        config: StagingZoneConfig = None
    ):
        """
        Initialize PolicyStagingZone.

        Args:
            policy_engine: PolicyEngine instance for activating policies
            event_bus: EventBus for emitting events
            config: Configuration for the staging zone
        """
        self._policy_engine = policy_engine
        self._event_bus = event_bus
        self._config = config or StagingZoneConfig()
        self._staged: Dict[str, StagedPolicy] = {}  # intent -> StagedPolicy
        self._lock = threading.RLock()
        self._logger = logging.getLogger(__name__)

        # Track stats
        self._stats = {
            "total_staged": 0,
            "total_committed": 0,
            "total_rolled_back": 0,
            "total_expired": 0,
            "cleanup_runs": 0
        }

    @property
    def min_confidence(self) -> float:
        """Get minimum confidence threshold."""
        return self._config.min_confidence

    @property
    def max_staged(self) -> int:
        """Get maximum staged policies."""
        return self._config.max_staged

    @property
    def ttl_seconds(self) -> int:
        """Get TTL in seconds."""
        return self._config.ttl_seconds

    def stage_policy(
        self,
        intent: str,
        policy_id: str,
        confidence: float,
        metadata: Dict[str, Any] = None
    ) -> str:
        """
        Stage a policy for later commitment.

        Policies are staged when confidence < min_confidence and held
        until either:
        1. Confidence is updated and commit_policy is called
        2. The staged policy expires
        3. The staged policy is rolled back

        Args:
            intent: The intent this policy is associated with
            policy_id: The ID of the policy to potentially activate
            confidence: Current confidence score (0.0 to 1.0)
            metadata: Additional metadata

        Returns:
            The staged policy ID

        Raises:
            ValueError: If max_staged limit is reached
        """
        with self._lock:
            # Check max staged limit
            if len(self._staged) >= self._config.max_staged:
                # Try cleanup first
                self._cleanup_expired_internal()

                if len(self._staged) >= self._config.max_staged:
                    raise ValueError(
                        f"Maximum staged policies ({self._config.max_staged}) reached"
                    )

            # Calculate expiration
            expires_at = datetime.utcnow() + timedelta(seconds=self._config.ttl_seconds)

            # Create staged policy
            staged = StagedPolicy(
                intent=intent,
                policy_id=policy_id,
                confidence=confidence,
                expires_at=expires_at,
                metadata=metadata or {}
            )

            # Store by intent (replaces any existing staged policy for this intent)
            self._staged[intent] = staged
            self._stats["total_staged"] += 1

            self._logger.info(
                f"[staging_zone] Policy staged: intent={intent}, "
                f"policy_id={policy_id}, confidence={confidence:.2f}, "
                f"staged_id={staged.staged_id}"
            )

            # Emit event
            self._emit_event(self.EVENT_POLICY_STAGED, {
                "staged_id": staged.staged_id,
                "intent": intent,
                "policy_id": policy_id,
                "confidence": confidence,
                "expires_at": expires_at.isoformat() + "Z"
            })

            return staged.staged_id

    def get_staged_policy(self, intent: str) -> Optional[StagedPolicy]:
        """
        Get the staged policy for an intent.

        Args:
            intent: The intent to look up

        Returns:
            StagedPolicy if exists and not expired, None otherwise
        """
        with self._lock:
            staged = self._staged.get(intent)
            if staged is None:
                return None

            # Check expiration
            if staged.is_expired():
                self._logger.debug(
                    f"[staging_zone] Staged policy for intent '{intent}' has expired"
                )
                return None

            return staged

    def update_confidence(self, intent: str, confidence: float) -> bool:
        """
        Update the confidence score for a staged policy.

        Args:
            intent: The intent to update
            confidence: New confidence score

        Returns:
            True if update was successful, False if no staged policy found
        """
        with self._lock:
            staged = self._staged.get(intent)
            if staged is None or staged.is_expired():
                return False

            staged.confidence = max(0.0, min(1.0, confidence))
            self._logger.debug(
                f"[staging_zone] Updated confidence for intent '{intent}': "
                f"{confidence:.2f}"
            )
            return True

    def commit_policy(self, intent: str) -> str:
        """
        Commit a staged policy, activating it in the policy engine.

        This method performs confidence binding:
        1. Retrieves the staged policy for the intent
        2. Checks that confidence >= min_confidence
        3. Checks that the policy hasn't expired
        4. Activates the policy in the policy engine

        Args:
            intent: The intent whose staged policy to commit

        Returns:
            The activated policy ID

        Raises:
            NoStagedPolicyError: If no staged policy exists for the intent
            InsufficientClarityError: If confidence < min_confidence
            StagedPolicyExpiredError: If the staged policy has expired
        """
        with self._lock:
            # Check internal dict directly to detect expired policies
            staged = self._staged.get(intent)

            if not staged:
                raise NoStagedPolicyError(intent)

            if staged.is_expired():
                raise StagedPolicyExpiredError(intent, staged.expires_at)

            if staged.confidence < self._config.min_confidence:
                raise InsufficientClarityError(
                    staged.confidence,
                    self._config.min_confidence
                )

            # Activate the policy
            activated_id = staged.policy_id

            if self._policy_engine:
                # Use policy engine to activate
                # Note: The actual activation depends on PolicyEngine API
                # This is a placeholder for integration
                try:
                    # The policy engine may have an activate method
                    # or we simply return the policy_id for external handling
                    if hasattr(self._policy_engine, 'activate'):
                        activated_id = self._policy_engine.activate(staged.policy_id)
                except Exception as e:
                    self._logger.error(
                        f"[staging_zone] Failed to activate policy: {e}"
                    )
                    raise

            # Remove from staged
            del self._staged[intent]
            self._stats["total_committed"] += 1

            self._logger.info(
                f"[staging_zone] Policy committed: intent={intent}, "
                f"policy_id={activated_id}, confidence={staged.confidence:.2f}"
            )

            # Emit event
            self._emit_event(self.EVENT_POLICY_COMMITTED, {
                "staged_id": staged.staged_id,
                "intent": intent,
                "policy_id": activated_id,
                "confidence": staged.confidence
            })

            return activated_id

    def rollback(self, intent: str) -> None:
        """
        Rollback a staged policy, removing it without activation.

        Args:
            intent: The intent whose staged policy to rollback

        Note:
            Silently does nothing if no staged policy exists.
        """
        with self._lock:
            staged = self._staged.get(intent)
            if staged is None:
                return

            del self._staged[intent]
            self._stats["total_rolled_back"] += 1

            self._logger.info(
                f"[staging_zone] Policy rolled back: intent={intent}, "
                f"staged_id={staged.staged_id}"
            )

            # Emit event
            self._emit_event(self.EVENT_POLICY_ROLLBACK, {
                "staged_id": staged.staged_id,
                "intent": intent,
                "policy_id": staged.policy_id
            })

    def get_all_staged(self) -> List[StagedPolicy]:
        """
        Get all currently staged policies.

        Returns:
            List of all non-expired staged policies
        """
        with self._lock:
            # Filter out expired
            return [
                staged for staged in self._staged.values()
                if not staged.is_expired()
            ]

    def cleanup_expired(self) -> int:
        """
        Remove all expired staged policies.

        Returns:
            Number of expired policies removed
        """
        with self._lock:
            return self._cleanup_expired_internal()

    def _cleanup_expired_internal(self) -> int:
        """
        Internal cleanup of expired policies (assumes lock is held).

        Returns:
            Number of expired policies removed
        """
        expired_intents = [
            intent for intent, staged in self._staged.items()
            if staged.is_expired()
        ]

        for intent in expired_intents:
            del self._staged[intent]
            self._stats["total_expired"] += 1
            self._logger.debug(
                f"[staging_zone] Expired staged policy removed: intent={intent}"
            )

        if expired_intents:
            self._stats["cleanup_runs"] += 1
            self._logger.info(
                f"[staging_zone] Cleaned up {len(expired_intents)} expired policies"
            )

        return len(expired_intents)

    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Emit an event to the event bus.

        Args:
            event_type: Type of event
            data: Event data
        """
        if self._event_bus is None:
            return

        try:
            from ..events.event_bus import Event, EventSeverity
            event = Event(
                event_type=event_type,
                data=data,
                severity=EventSeverity.INFO,
                source="PolicyStagingZone"
            )
            self._event_bus.emit(event)
        except Exception as e:
            self._logger.warning(
                f"[staging_zone] Failed to emit event {event_type}: {e}"
            )

    def get_stats(self) -> Dict[str, Any]:
        """
        Get staging zone statistics.

        Returns:
            Dict with staging statistics
        """
        with self._lock:
            return {
                "current_staged_count": len(self._staged),
                "max_staged": self._config.max_staged,
                "min_confidence": self._config.min_confidence,
                "ttl_seconds": self._config.ttl_seconds,
                **self._stats
            }

    def clear(self) -> int:
        """
        Clear all staged policies.

        Returns:
            Number of policies cleared
        """
        with self._lock:
            count = len(self._staged)
            self._staged.clear()
            self._logger.info(f"[staging_zone] Cleared {count} staged policies")
            return count


# =============================================================================
# Factory Function
# =============================================================================

_global_staging_zone: Optional[PolicyStagingZone] = None
_staging_zone_lock = threading.Lock()


def create_staging_zone(
    policy_engine: "PolicyEngine" = None,
    event_bus: "EventBus" = None,
    config: Dict[str, Any] = None
) -> PolicyStagingZone:
    """
    Create a PolicyStagingZone with optional configuration.

    Args:
        policy_engine: PolicyEngine instance
        event_bus: EventBus instance
        config: Configuration dictionary

    Returns:
        Configured PolicyStagingZone instance
    """
    staging_config = None
    if config:
        staging_config = StagingZoneConfig.from_dict(
            config.get("staging_zone", config)
        )

    return PolicyStagingZone(
        policy_engine=policy_engine,
        event_bus=event_bus,
        config=staging_config
    )


def get_staging_zone(
    policy_engine: "PolicyEngine" = None,
    event_bus: "EventBus" = None,
    config: Dict[str, Any] = None
) -> PolicyStagingZone:
    """
    Get the global PolicyStagingZone singleton.

    Args:
        policy_engine: PolicyEngine instance (only used on first call)
        event_bus: EventBus instance (only used on first call)
        config: Configuration dictionary (only used on first call)

    Returns:
        Global PolicyStagingZone instance
    """
    global _global_staging_zone
    if _global_staging_zone is None:
        with _staging_zone_lock:
            if _global_staging_zone is None:
                _global_staging_zone = create_staging_zone(
                    policy_engine=policy_engine,
                    event_bus=event_bus,
                    config=config
                )
    return _global_staging_zone


def reset_staging_zone() -> None:
    """Reset the global staging zone (for testing)."""
    global _global_staging_zone
    with _staging_zone_lock:
        _global_staging_zone = None
