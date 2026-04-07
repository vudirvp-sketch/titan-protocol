"""
Feedback Loop Module for TITAN Protocol.

ITEM-FEEDBACK-01: FeedbackLoop Module Implementation

This module provides the core feedback collection, aggregation, and
threshold adjustment system for the TITAN Protocol skill catalog.

Features:
- Multi-type feedback collection (thumbs up/down, ratings, comments)
- Time-windowed feedback aggregation
- Threshold adjustment calculation based on feedback
- Rollback support for adjustments
- Event-driven architecture integration

Components:
- FeedbackType: Enum for feedback types
- FeedbackEvent: Individual feedback event dataclass
- AggregatedFeedback: Aggregated statistics dataclass
- ThresholdAdjustment: Threshold change record dataclass
- ApplyResult: Result of applying an adjustment
- FeedbackLoop: Main feedback loop orchestrator

Author: TITAN Protocol Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, TYPE_CHECKING
import logging
import uuid
import json

if TYPE_CHECKING:
    from src.events.event_bus import EventBus
    from src.storage.backend import StorageBackend


class FeedbackType(Enum):
    """
    Types of feedback that can be collected.
    
    Attributes:
        THUMBS_UP: Positive quick feedback
        THUMBS_DOWN: Negative quick feedback
        RATING: Numeric rating (1-5 scale)
        COMMENT: Textual feedback with optional rating
    """
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    RATING = "rating"
    COMMENT = "comment"


@dataclass
class FeedbackEvent:
    """
    Individual feedback event from a user.
    
    Represents a single piece of feedback about a skill execution,
    including the type of feedback, optional rating, and contextual
    information about the session.
    
    Attributes:
        feedback_id: Unique identifier for this feedback event
        session_id: Session where the feedback was given
        skill_id: Skill that received the feedback
        feedback_type: Type of feedback (thumbs up/down/rating/comment)
        rating: Optional numeric rating (1-5 for RATING type)
        context: Additional context about the feedback
        timestamp: When the feedback was given (ISO 8601 format)
    
    Example:
        >>> event = FeedbackEvent(
        ...     feedback_id="fb-123",
        ...     session_id="sess-abc",
        ...     skill_id="skill-web-search",
        ...     feedback_type=FeedbackType.THUMBS_UP,
        ...     context={"query": "example query"}
        ... )
    """
    feedback_id: str
    session_id: str
    skill_id: str
    feedback_type: FeedbackType
    rating: Optional[int] = None
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def __post_init__(self):
        """Validate feedback event after initialization."""
        # Validate rating if provided
        if self.rating is not None:
            if not 1 <= self.rating <= 5:
                raise ValueError(f"Rating must be between 1 and 5, got {self.rating}")
        
        # Validate feedback_type is FeedbackType enum
        if isinstance(self.feedback_type, str):
            self.feedback_type = FeedbackType(self.feedback_type)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert feedback event to dictionary for serialization.
        
        Returns:
            Dictionary representation of the feedback event
        """
        return {
            "feedback_id": self.feedback_id,
            "session_id": self.session_id,
            "skill_id": self.skill_id,
            "feedback_type": self.feedback_type.value,
            "rating": self.rating,
            "context": self.context,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FeedbackEvent':
        """
        Create a FeedbackEvent from a dictionary.
        
        Args:
            data: Dictionary containing feedback event data
            
        Returns:
            FeedbackEvent instance
        """
        feedback_type = data.get("feedback_type")
        if isinstance(feedback_type, str):
            feedback_type = FeedbackType(feedback_type)
        
        return cls(
            feedback_id=data.get("feedback_id", str(uuid.uuid4())),
            session_id=data["session_id"],
            skill_id=data["skill_id"],
            feedback_type=feedback_type,
            rating=data.get("rating"),
            context=data.get("context", {}),
            timestamp=data.get("timestamp", datetime.utcnow().isoformat() + "Z")
        )


@dataclass
class AggregatedFeedback:
    """
    Aggregated feedback statistics for a skill.
    
    Represents the aggregated feedback statistics for a skill over
    a specific time window, including counts of positive/negative
    feedback and average ratings.
    
    Attributes:
        skill_id: Skill these statistics apply to
        thumbs_up_count: Number of thumbs up feedback
        thumbs_down_count: Number of thumbs down feedback
        total_count: Total number of feedback events
        average_rating: Average rating (if any ratings received)
        window_start: Start of the aggregation window (ISO 8601)
        window_end: End of the aggregation window (ISO 8601)
    """
    skill_id: str
    thumbs_up_count: int = 0
    thumbs_down_count: int = 0
    total_count: int = 0
    average_rating: Optional[float] = None
    window_start: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    window_end: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    @property
    def positive_rate(self) -> float:
        """
        Calculate the positive feedback rate.
        
        Returns:
            Ratio of thumbs up to total thumbs feedback (0.0-1.0)
        """
        total_thumbs = self.thumbs_up_count + self.thumbs_down_count
        if total_thumbs == 0:
            return 0.5  # Neutral if no thumbs feedback
        return self.thumbs_up_count / total_thumbs
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation
        """
        return {
            "skill_id": self.skill_id,
            "thumbs_up_count": self.thumbs_up_count,
            "thumbs_down_count": self.thumbs_down_count,
            "total_count": self.total_count,
            "average_rating": self.average_rating,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "positive_rate": self.positive_rate
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AggregatedFeedback':
        """
        Create from dictionary.
        
        Args:
            data: Dictionary containing aggregated feedback data
            
        Returns:
            AggregatedFeedback instance
        """
        return cls(
            skill_id=data["skill_id"],
            thumbs_up_count=data.get("thumbs_up_count", 0),
            thumbs_down_count=data.get("thumbs_down_count", 0),
            total_count=data.get("total_count", 0),
            average_rating=data.get("average_rating"),
            window_start=data.get("window_start", datetime.utcnow().isoformat() + "Z"),
            window_end=data.get("window_end", datetime.utcnow().isoformat() + "Z")
        )


@dataclass
class ThresholdAdjustment:
    """
    Record of a threshold adjustment for a skill.
    
    Represents a change to a skill's confidence threshold based on
    feedback analysis. This record is used for audit trails and
    rollback support.
    
    Attributes:
        skill_id: Skill whose threshold was adjusted
        current_threshold: Threshold before adjustment
        new_threshold: Threshold after adjustment
        magnitude: Size of the adjustment (absolute difference)
        reason: Explanation of why the adjustment was made
        timestamp: When the adjustment was made (ISO 8601)
    """
    skill_id: str
    current_threshold: float
    new_threshold: float
    magnitude: float
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    adjustment_id: str = field(default_factory=lambda: f"adj-{uuid.uuid4().hex[:8]}")
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation
        """
        return {
            "adjustment_id": self.adjustment_id,
            "skill_id": self.skill_id,
            "current_threshold": self.current_threshold,
            "new_threshold": self.new_threshold,
            "magnitude": self.magnitude,
            "reason": self.reason,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ThresholdAdjustment':
        """
        Create from dictionary.
        
        Args:
            data: Dictionary containing adjustment data
            
        Returns:
            ThresholdAdjustment instance
        """
        return cls(
            adjustment_id=data.get("adjustment_id", f"adj-{uuid.uuid4().hex[:8]}"),
            skill_id=data["skill_id"],
            current_threshold=data["current_threshold"],
            new_threshold=data["new_threshold"],
            magnitude=data["magnitude"],
            reason=data["reason"],
            timestamp=data.get("timestamp", datetime.utcnow().isoformat() + "Z")
        )


@dataclass
class ApplyResult:
    """
    Result of applying a threshold adjustment.
    
    Indicates whether an adjustment was successfully applied,
    and includes identifiers for the adjustment and new catalog version.
    
    Attributes:
        success: Whether the adjustment was applied successfully
        adjustment_id: ID of the adjustment record
        version_id: ID of the new catalog version (if successful)
        error_message: Error description (if unsuccessful)
    """
    success: bool
    adjustment_id: str
    version_id: str = ""
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation
        """
        return {
            "success": self.success,
            "adjustment_id": self.adjustment_id,
            "version_id": self.version_id,
            "error_message": self.error_message
        }


class FeedbackLoop:
    """
    Main feedback loop orchestrator for TITAN Protocol.
    
    Collects feedback, aggregates statistics, calculates threshold
    adjustments, and applies them to the skill catalog with full
    rollback support.
    
    Features:
    - Multi-type feedback collection
    - Time-windowed aggregation
    - Event-driven notifications (FEEDBACK_RECEIVED events)
    - Persistent storage integration
    - Rollback support for adjustments
    
    Integration:
        - EventBus: Emits FEEDBACK_RECEIVED events
        - StorageBackend: Persists feedback and adjustments
        - ThresholdAdapter: Calculates new thresholds
        - CatalogVersionManager: Manages catalog versions
    
    Example:
        >>> from src.events import EventBus
        >>> from src.storage import LocalStorageBackend
        >>> 
        >>> event_bus = EventBus()
        >>> storage = LocalStorageBackend(base_path="./.titan/storage")
        >>> feedback_loop = FeedbackLoop(config={}, event_bus=event_bus, storage_backend=storage)
        >>> 
        >>> # Receive feedback
        >>> event = FeedbackEvent(...)
        >>> feedback_id = feedback_loop.receive_feedback(event)
    """
    
    # Storage paths
    FEEDBACK_PATH = "feedback"
    ADJUSTMENTS_PATH = "adjustments"
    CATALOG_PATH = "skills/catalog"
    
    def __init__(self, config: Dict[str, Any], event_bus: 'EventBus', 
                 storage_backend: 'StorageBackend'):
        """
        Initialize the feedback loop.
        
        Args:
            config: Configuration dictionary with options:
                - min_samples: Minimum samples for adjustment (default: 10)
                - default_threshold: Default skill threshold (default: 0.7)
                - feedback_retention_days: Days to retain feedback (default: 90)
            event_bus: EventBus instance for event emission
            storage_backend: StorageBackend instance for persistence
        """
        self.config = config
        self.event_bus = event_bus
        self.storage = storage_backend
        
        # Configuration defaults
        self._min_samples = config.get("min_samples", 10)
        self._default_threshold = config.get("default_threshold", 0.7)
        self._feedback_retention_days = config.get("feedback_retention_days", 90)
        
        # In-memory cache
        self._feedback_cache: Dict[str, List[FeedbackEvent]] = {}
        self._adjustment_history: Dict[str, List[ThresholdAdjustment]] = {}
        self._catalog_cache: Dict[str, Any] = {}
        
        self._logger = logging.getLogger(__name__)
        
        # Subscribe to own events for metrics
        self._setup_event_handlers()
    
    def _setup_event_handlers(self) -> None:
        """Set up internal event handlers."""
        # Could subscribe to specific events here if needed
        pass
    
    def receive_feedback(self, feedback: FeedbackEvent) -> str:
        """
        Receive and store a feedback event.
        
        Stores the feedback event, updates in-memory cache, and emits
        a FEEDBACK_RECEIVED event to the event bus.
        
        Args:
            feedback: FeedbackEvent to receive
            
        Returns:
            The feedback_id of the received feedback
            
        Raises:
            ValueError: If feedback is invalid
        """
        # Validate feedback
        if not feedback.skill_id:
            raise ValueError("Feedback must have a skill_id")
        if not feedback.session_id:
            raise ValueError("Feedback must have a session_id")
        
        # Ensure feedback_id is set
        if not feedback.feedback_id:
            feedback.feedback_id = f"fb-{uuid.uuid4().hex[:12]}"
        
        # Store feedback
        self._store_feedback(feedback)
        
        # Update cache
        skill_id = feedback.skill_id
        if skill_id not in self._feedback_cache:
            self._feedback_cache[skill_id] = []
        self._feedback_cache[skill_id].append(feedback)
        
        # Emit FEEDBACK_RECEIVED event
        self._emit_feedback_event(feedback)
        
        self._logger.info(
            f"Received feedback {feedback.feedback_id} for skill {feedback.skill_id}: "
            f"{feedback.feedback_type.value}"
        )
        
        return feedback.feedback_id
    
    def _store_feedback(self, feedback: FeedbackEvent) -> None:
        """
        Store feedback to persistent storage.
        
        Args:
            feedback: FeedbackEvent to store
        """
        path = f"{self.FEEDBACK_PATH}/{feedback.skill_id}/{feedback.feedback_id}.json"
        self.storage.save_json(path, feedback.to_dict())
    
    def _emit_feedback_event(self, feedback: FeedbackEvent) -> None:
        """
        Emit FEEDBACK_RECEIVED event to the event bus.
        
        Args:
            feedback: FeedbackEvent that was received
        """
        from src.events.event_bus import Event, EventSeverity
        
        event = Event(
            event_type="FEEDBACK_RECEIVED",
            data={
                "feedback_id": feedback.feedback_id,
                "skill_id": feedback.skill_id,
                "session_id": feedback.session_id,
                "feedback_type": feedback.feedback_type.value,
                "rating": feedback.rating
            },
            severity=EventSeverity.INFO,
            source="FeedbackLoop"
        )
        self.event_bus.emit(event)
    
    def aggregate_feedback(self, skill_id: str, window: timedelta) -> AggregatedFeedback:
        """
        Aggregate feedback for a skill over a time window.
        
        Calculates aggregated statistics including thumbs up/down counts,
        total feedback count, and average rating.
        
        Args:
            skill_id: Skill to aggregate feedback for
            window: Time window to aggregate over (e.g., timedelta(days=7))
            
        Returns:
            AggregatedFeedback with statistics for the window
        """
        # Calculate window boundaries
        now = datetime.utcnow()
        window_start = now - window
        
        # Get feedback events for skill
        events = self._get_feedback_events(skill_id)
        
        # Filter by time window
        filtered_events = []
        for event in events:
            try:
                event_time = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))
                event_time = event_time.replace(tzinfo=None)  # Make naive for comparison
                if event_time >= window_start:
                    filtered_events.append(event)
            except (ValueError, AttributeError):
                # Include events with invalid timestamps
                filtered_events.append(event)
        
        # Aggregate statistics
        thumbs_up = 0
        thumbs_down = 0
        ratings = []
        
        for event in filtered_events:
            if event.feedback_type == FeedbackType.THUMBS_UP:
                thumbs_up += 1
            elif event.feedback_type == FeedbackType.THUMBS_DOWN:
                thumbs_down += 1
            elif event.feedback_type == FeedbackType.RATING and event.rating is not None:
                ratings.append(event.rating)
            elif event.feedback_type == FeedbackType.COMMENT and event.rating is not None:
                ratings.append(event.rating)
        
        # Calculate average rating
        avg_rating = sum(ratings) / len(ratings) if ratings else None
        
        return AggregatedFeedback(
            skill_id=skill_id,
            thumbs_up_count=thumbs_up,
            thumbs_down_count=thumbs_down,
            total_count=len(filtered_events),
            average_rating=round(avg_rating, 2) if avg_rating else None,
            window_start=window_start.isoformat() + "Z",
            window_end=now.isoformat() + "Z"
        )
    
    def _get_feedback_events(self, skill_id: str) -> List[FeedbackEvent]:
        """
        Get all feedback events for a skill.
        
        First checks the in-memory cache, then loads from storage.
        
        Args:
            skill_id: Skill to get feedback for
            
        Returns:
            List of FeedbackEvent objects
        """
        # Check cache first
        if skill_id in self._feedback_cache:
            return self._feedback_cache[skill_id]
        
        # Load from storage
        events = []
        prefix = f"{self.FEEDBACK_PATH}/{skill_id}/"
        
        try:
            for path in self.storage.list(prefix):
                if path.endswith('.json'):
                    try:
                        data = self.storage.load_json(path)
                        events.append(FeedbackEvent.from_dict(data))
                    except Exception as e:
                        self._logger.warning(f"Failed to load feedback from {path}: {e}")
        except Exception as e:
            self._logger.debug(f"No feedback found for skill {skill_id}: {e}")
        
        # Update cache
        self._feedback_cache[skill_id] = events
        
        return events
    
    def calculate_threshold_adjustment(self, skill_id: str) -> ThresholdAdjustment:
        """
        Calculate a threshold adjustment for a skill.
        
        Uses the ThresholdAdapter to calculate a new threshold based on
        aggregated feedback statistics.
        
        Args:
            skill_id: Skill to calculate adjustment for
            
        Returns:
            ThresholdAdjustment with the calculated adjustment
            
        Raises:
            ValueError: If not enough samples for adjustment
        """
        from src.feedback.threshold_adapter import ThresholdAdapter
        
        # Get aggregated feedback
        # Use 30-day window by default
        window = timedelta(days=self.config.get("aggregation_window_days", 30))
        aggregated = self.aggregate_feedback(skill_id, window)
        
        # Get current catalog
        catalog = self._get_catalog()
        
        # Get current threshold for skill
        current_threshold = self._get_skill_threshold(skill_id, catalog)
        
        # Create threshold adapter
        adapter = ThresholdAdapter(
            config=self.config,
            catalog=catalog,
            feedback_store=self
        )
        
        # Calculate new threshold
        new_threshold = adapter.calculate_new_threshold(skill_id, aggregated)
        
        # Create adjustment record
        adjustment = ThresholdAdjustment(
            skill_id=skill_id,
            current_threshold=current_threshold,
            new_threshold=new_threshold,
            magnitude=abs(new_threshold - current_threshold),
            reason=self._generate_adjustment_reason(aggregated, current_threshold, new_threshold)
        )
        
        self._logger.info(
            f"Calculated threshold adjustment for {skill_id}: "
            f"{current_threshold:.3f} -> {new_threshold:.3f}"
        )
        
        return adjustment
    
    def _get_catalog(self) -> Dict[str, Any]:
        """
        Get the current skill catalog.
        
        Returns:
            Catalog dictionary
        """
        if not self._catalog_cache:
            try:
                self._catalog_cache = self.storage.load_json(self.CATALOG_PATH)
            except Exception:
                # Return empty catalog if not found
                self._catalog_cache = {"skills": {}, "version": "1.0.0"}
        
        return self._catalog_cache
    
    def _get_skill_threshold(self, skill_id: str, catalog: Dict[str, Any]) -> float:
        """
        Get the current threshold for a skill from the catalog.
        
        Args:
            skill_id: Skill to get threshold for
            catalog: Catalog dictionary
            
        Returns:
            Current threshold (or default if not found)
        """
        skills = catalog.get("skills", {})
        skill = skills.get(skill_id, {})
        return skill.get("threshold", self._default_threshold)
    
    def _generate_adjustment_reason(self, aggregated: AggregatedFeedback,
                                    current: float, new: float) -> str:
        """
        Generate a human-readable reason for an adjustment.
        
        Args:
            aggregated: Aggregated feedback statistics
            current: Current threshold
            new: New threshold
            
        Returns:
            Human-readable reason string
        """
        direction = "increased" if new > current else "decreased"
        change = abs(new - current)
        
        return (
            f"Threshold {direction} by {change:.3f} based on "
            f"{aggregated.total_count} feedback events "
            f"({aggregated.thumbs_up_count} thumbs up, "
            f"{aggregated.thumbs_down_count} thumbs down, "
            f"avg rating: {aggregated.average_rating or 'N/A'})"
        )
    
    def apply_adjustment(self, adjustment: ThresholdAdjustment) -> ApplyResult:
        """
        Apply a threshold adjustment to the catalog.
        
        Creates a new catalog version with the adjusted threshold
        and stores the adjustment record.
        
        Args:
            adjustment: ThresholdAdjustment to apply
            
        Returns:
            ApplyResult indicating success or failure
        """
        try:
            from src.feedback.catalog_versioning import CatalogVersionManager
            
            # Get current catalog
            catalog = self._get_catalog()
            
            # Update threshold in catalog
            if "skills" not in catalog:
                catalog["skills"] = {}
            
            if adjustment.skill_id not in catalog["skills"]:
                catalog["skills"][adjustment.skill_id] = {}
            
            catalog["skills"][adjustment.skill_id]["threshold"] = adjustment.new_threshold
            
            # Create version manager
            version_manager = CatalogVersionManager(self.storage)
            
            # Create new version
            version_id = version_manager.create_version(
                catalog=catalog,
                reason=adjustment.reason
            )
            
            # Store adjustment record
            self._store_adjustment(adjustment)
            
            # Update cache
            self._catalog_cache = catalog
            
            # Track adjustment in history
            if adjustment.skill_id not in self._adjustment_history:
                self._adjustment_history[adjustment.skill_id] = []
            self._adjustment_history[adjustment.skill_id].append(adjustment)
            
            self._logger.info(
                f"Applied adjustment {adjustment.adjustment_id}: "
                f"threshold for {adjustment.skill_id} changed to {adjustment.new_threshold:.3f}"
            )
            
            return ApplyResult(
                success=True,
                adjustment_id=adjustment.adjustment_id,
                version_id=version_id
            )
            
        except Exception as e:
            self._logger.error(f"Failed to apply adjustment: {e}")
            return ApplyResult(
                success=False,
                adjustment_id=adjustment.adjustment_id,
                error_message=str(e)
            )
    
    def _store_adjustment(self, adjustment: ThresholdAdjustment) -> None:
        """
        Store an adjustment record to persistent storage.
        
        Args:
            adjustment: ThresholdAdjustment to store
        """
        path = f"{self.ADJUSTMENTS_PATH}/{adjustment.adjustment_id}.json"
        self.storage.save_json(path, adjustment.to_dict())
    
    def rollback_adjustment(self, adjustment_id: str) -> bool:
        """
        Rollback a previously applied adjustment.
        
        Reverts the catalog to the state before the adjustment was applied.
        
        Args:
            adjustment_id: ID of the adjustment to rollback
            
        Returns:
            True if rollback was successful, False otherwise
        """
        try:
            # Load adjustment record
            adjustment = self._load_adjustment(adjustment_id)
            if not adjustment:
                self._logger.warning(f"Adjustment {adjustment_id} not found")
                return False
            
            # Get current catalog
            catalog = self._get_catalog()
            
            # Revert threshold in catalog
            if adjustment.skill_id in catalog.get("skills", {}):
                catalog["skills"][adjustment.skill_id]["threshold"] = adjustment.current_threshold
            
            # Create version manager
            from src.feedback.catalog_versioning import CatalogVersionManager
            version_manager = CatalogVersionManager(self.storage)
            
            # Create new version with rollback
            version_manager.create_version(
                catalog=catalog,
                reason=f"Rollback of adjustment {adjustment_id}"
            )
            
            # Update cache
            self._catalog_cache = catalog
            
            # Mark adjustment as rolled back
            self._mark_adjustment_rolled_back(adjustment_id)
            
            self._logger.info(
                f"Rolled back adjustment {adjustment_id}: "
                f"threshold for {adjustment.skill_id} reverted to {adjustment.current_threshold:.3f}"
            )
            
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to rollback adjustment {adjustment_id}: {e}")
            return False
    
    def _load_adjustment(self, adjustment_id: str) -> Optional[ThresholdAdjustment]:
        """
        Load an adjustment record from storage.
        
        Args:
            adjustment_id: ID of the adjustment to load
            
        Returns:
            ThresholdAdjustment or None if not found
        """
        path = f"{self.ADJUSTMENTS_PATH}/{adjustment_id}.json"
        try:
            data = self.storage.load_json(path)
            return ThresholdAdjustment.from_dict(data)
        except Exception:
            return None
    
    def _mark_adjustment_rolled_back(self, adjustment_id: str) -> None:
        """
        Mark an adjustment as rolled back in storage.
        
        Args:
            adjustment_id: ID of the adjustment to mark
        """
        path = f"{self.ADJUSTMENTS_PATH}/{adjustment_id}.json"
        try:
            data = self.storage.load_json(path)
            data["rolled_back"] = True
            data["rolled_back_at"] = datetime.utcnow().isoformat() + "Z"
            self.storage.save_json(path, data)
        except Exception as e:
            self._logger.warning(f"Failed to mark adjustment as rolled back: {e}")
    
    def get_feedback_stats(self, skill_id: str) -> Dict[str, Any]:
        """
        Get feedback statistics for a skill.
        
        Args:
            skill_id: Skill to get stats for
            
        Returns:
            Dictionary with feedback statistics
        """
        events = self._get_feedback_events(skill_id)
        
        # Aggregate all time
        all_time = AggregatedFeedback(skill_id=skill_id)
        for event in events:
            all_time.total_count += 1
            if event.feedback_type == FeedbackType.THUMBS_UP:
                all_time.thumbs_up_count += 1
            elif event.feedback_type == FeedbackType.THUMBS_DOWN:
                all_time.thumbs_down_count += 1
        
        return {
            "skill_id": skill_id,
            "total_feedback": all_time.total_count,
            "thumbs_up": all_time.thumbs_up_count,
            "thumbs_down": all_time.thumbs_down_count,
            "positive_rate": all_time.positive_rate,
            "adjustment_count": len(self._adjustment_history.get(skill_id, []))
        }
