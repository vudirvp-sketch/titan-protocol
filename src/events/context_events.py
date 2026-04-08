"""
Context Events for TITAN FUSE Protocol.

ITEM-SAE-010: Context Graph EventBus Integration

Defines context-related events for integration with EventBus:
- CONTEXT_GRAPH_UPDATED: Graph modification events
- CONTEXT_NODE_TRUST_CHANGED: Trust score changes
- CONTEXT_DRIFT_DETECTED: Semantic drift detection
- CONTEXT_STALE_DETECTED: Stale node identification
- CONTEXT_SUMMARY_PRUNED: Stage summarization events

Author: TITAN FUSE Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import logging

from src.events.event_bus import Event, EventSeverity, EventBus, get_severity_for_event
from src.utils.timezone import now_utc_iso


# =============================================================================
# Event Types
# =============================================================================

class ContextEventType(Enum):
    """Context-related event types."""
    # Graph events
    CONTEXT_GRAPH_UPDATED = "CONTEXT_GRAPH_UPDATED"
    CONTEXT_GRAPH_GENERATED = "CONTEXT_GRAPH_GENERATED"
    
    # Node events
    CONTEXT_NODE_ADDED = "CONTEXT_NODE_ADDED"
    CONTEXT_NODE_REMOVED = "CONTEXT_NODE_REMOVED"
    CONTEXT_NODE_TRUST_CHANGED = "CONTEXT_NODE_TRUST_CHANGED"
    
    # Drift events
    CONTEXT_DRIFT_DETECTED = "CONTEXT_DRIFT_DETECTED"
    CONTEXT_STALE_DETECTED = "CONTEXT_STALE_DETECTED"
    CONTEXT_REFRESH_SUGGESTED = "CONTEXT_REFRESH_SUGGESTED"
    
    # Summarization events
    CONTEXT_SUMMARY_PRUNED = "CONTEXT_SUMMARY_PRUNED"
    CONTEXT_SUMMARY_CREATED = "CONTEXT_SUMMARY_CREATED"
    
    # Version events
    CONTEXT_VERSION_CONFLICT = "CONTEXT_VERSION_CONFLICT"


# =============================================================================
# Severity Mapping
# =============================================================================

CONTEXT_EVENT_SEVERITY: Dict[str, EventSeverity] = {
    # INFO events
    ContextEventType.CONTEXT_GRAPH_UPDATED.value: EventSeverity.INFO,
    ContextEventType.CONTEXT_GRAPH_GENERATED.value: EventSeverity.INFO,
    ContextEventType.CONTEXT_NODE_ADDED.value: EventSeverity.DEBUG,
    ContextEventType.CONTEXT_NODE_REMOVED.value: EventSeverity.DEBUG,
    ContextEventType.CONTEXT_NODE_TRUST_CHANGED.value: EventSeverity.DEBUG,
    ContextEventType.CONTEXT_SUMMARY_CREATED.value: EventSeverity.INFO,
    
    # WARN events
    ContextEventType.CONTEXT_DRIFT_DETECTED.value: EventSeverity.WARN,
    ContextEventType.CONTEXT_STALE_DETECTED.value: EventSeverity.WARN,
    ContextEventType.CONTEXT_REFRESH_SUGGESTED.value: EventSeverity.WARN,
    ContextEventType.CONTEXT_SUMMARY_PRUNED.value: EventSeverity.INFO,
    
    # CRITICAL events
    ContextEventType.CONTEXT_VERSION_CONFLICT.value: EventSeverity.WARN,
}


def get_context_event_severity(event_type: str) -> EventSeverity:
    """Get severity for context event type."""
    return CONTEXT_EVENT_SEVERITY.get(event_type, EventSeverity.INFO)


# =============================================================================
# Event Factory Functions
# =============================================================================

def create_graph_updated_event(
    graph_version: str,
    nodes_added: int = 0,
    nodes_removed: int = 0,
    nodes_modified: int = 0,
    source: str = "ContextGraph"
) -> Event:
    """
    Create CONTEXT_GRAPH_UPDATED event.
    
    Args:
        graph_version: Current graph version
        nodes_added: Number of nodes added
        nodes_removed: Number of nodes removed
        nodes_modified: Number of nodes modified
        source: Event source
        
    Returns:
        Event object
    """
    return Event(
        event_type=ContextEventType.CONTEXT_GRAPH_UPDATED.value,
        data={
            "graph_version": graph_version,
            "nodes_added": nodes_added,
            "nodes_removed": nodes_removed,
            "nodes_modified": nodes_modified,
            "total_changes": nodes_added + nodes_removed + nodes_modified,
        },
        severity=CONTEXT_EVENT_SEVERITY[ContextEventType.CONTEXT_GRAPH_UPDATED.value],
        source=source,
    )


def create_node_trust_changed_event(
    node_id: str,
    old_trust: float,
    new_trust: float,
    reason: str,
    source: str = "TrustEngine"
) -> Event:
    """
    Create CONTEXT_NODE_TRUST_CHANGED event.
    
    Args:
        node_id: Node identifier
        old_trust: Previous trust score
        new_trust: New trust score
        reason: Reason for change
        source: Event source
        
    Returns:
        Event object
    """
    return Event(
        event_type=ContextEventType.CONTEXT_NODE_TRUST_CHANGED.value,
        data={
            "node_id": node_id,
            "old_trust": round(old_trust, 4),
            "new_trust": round(new_trust, 4),
            "delta": round(new_trust - old_trust, 4),
            "reason": reason,
        },
        severity=CONTEXT_EVENT_SEVERITY[ContextEventType.CONTEXT_NODE_TRUST_CHANGED.value],
        source=source,
    )


def create_drift_detected_event(
    node_id: str,
    drift_score: float,
    drift_level: str,
    recommended_action: str,
    source: str = "DriftDetector"
) -> Event:
    """
    Create CONTEXT_DRIFT_DETECTED event.
    
    Args:
        node_id: Node identifier
        drift_score: Drift score (0.0 to 1.0)
        drift_level: Drift level (NONE, MINOR, MODERATE, SEVERE)
        recommended_action: Suggested action
        source: Event source
        
    Returns:
        Event object
    """
    return Event(
        event_type=ContextEventType.CONTEXT_DRIFT_DETECTED.value,
        data={
            "node_id": node_id,
            "drift_score": round(drift_score, 4),
            "drift_level": drift_level,
            "recommended_action": recommended_action,
        },
        severity=CONTEXT_EVENT_SEVERITY[ContextEventType.CONTEXT_DRIFT_DETECTED.value],
        source=source,
    )


def create_stale_detected_event(
    node_id: str,
    stale_reason: str,
    suggested_action: str,
    last_modified: Optional[str] = None,
    source: str = "ContextGraph"
) -> Event:
    """
    Create CONTEXT_STALE_DETECTED event.
    
    Args:
        node_id: Node identifier
        stale_reason: Reason for staleness
        suggested_action: Suggested action
        last_modified: Last modification timestamp
        source: Event source
        
    Returns:
        Event object
    """
    return Event(
        event_type=ContextEventType.CONTEXT_STALE_DETECTED.value,
        data={
            "node_id": node_id,
            "stale_reason": stale_reason,
            "suggested_action": suggested_action,
            "last_modified": last_modified,
        },
        severity=CONTEXT_EVENT_SEVERITY[ContextEventType.CONTEXT_STALE_DETECTED.value],
        source=source,
    )


def create_summary_pruned_event(
    stage_id: str,
    summary_id: str,
    compression_ratio: float,
    bytes_saved: int,
    source: str = "RecursiveSummarizer"
) -> Event:
    """
    Create CONTEXT_SUMMARY_PRUNED event.
    
    Args:
        stage_id: Pruned stage ID
        summary_id: Generated summary ID
        compression_ratio: Compression ratio achieved
        bytes_saved: Bytes saved by compression
        source: Event source
        
    Returns:
        Event object
    """
    return Event(
        event_type=ContextEventType.CONTEXT_SUMMARY_PRUNED.value,
        data={
            "stage_id": stage_id,
            "summary_id": summary_id,
            "compression_ratio": round(compression_ratio, 3),
            "bytes_saved": bytes_saved,
        },
        severity=CONTEXT_EVENT_SEVERITY[ContextEventType.CONTEXT_SUMMARY_PRUNED.value],
        source=source,
    )


# =============================================================================
# Event Handlers
# =============================================================================

class ContextEventHandler:
    """
    Handles context-related events.
    
    Provides default handlers for context events that can be
    registered with the EventBus.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize event handler."""
        self._logger = logger or logging.getLogger(__name__)
    
    def on_graph_updated(self, event: Event) -> None:
        """Handle CONTEXT_GRAPH_UPDATED event."""
        data = event.data
        self._logger.info(
            f"[ContextGraph] Updated: v{data.get('graph_version')} "
            f"(+{data.get('nodes_added')} -{data.get('nodes_removed')} "
            f"~{data.get('nodes_modified')})"
        )
    
    def on_trust_changed(self, event: Event) -> None:
        """Handle CONTEXT_NODE_TRUST_CHANGED event."""
        data = event.data
        self._logger.debug(
            f"[TrustEngine] {data.get('node_id')}: "
            f"{data.get('old_trust'):.3f} → {data.get('new_trust'):.3f} "
            f"({data.get('reason')})"
        )
    
    def on_drift_detected(self, event: Event) -> None:
        """Handle CONTEXT_DRIFT_DETECTED event."""
        data = event.data
        level = data.get('drift_level', 'UNKNOWN')
        icon = {"NONE": "✅", "MINOR": "📝", "MODERATE": "⚠️", "SEVERE": "🚨"}.get(level, "❓")
        self._logger.warning(
            f"{icon} [Drift] {data.get('node_id')}: "
            f"score={data.get('drift_score'):.3f} level={level} "
            f"action={data.get('recommended_action')}"
        )
    
    def on_stale_detected(self, event: Event) -> None:
        """Handle CONTEXT_STALE_DETECTED event."""
        data = event.data
        self._logger.warning(
            f"🧹 [Stale] {data.get('node_id')}: "
            f"reason={data.get('stale_reason')} "
            f"action={data.get('suggested_action')}"
        )
    
    def on_summary_pruned(self, event: Event) -> None:
        """Handle CONTEXT_SUMMARY_PRUNED event."""
        data = event.data
        self._logger.info(
            f"📝 [Summarizer] Pruned stage {data.get('stage_id')} "
            f"→ summary {data.get('summary_id')} "
            f"(ratio={data.get('compression_ratio'):.2f}, saved={data.get('bytes_saved')}b)"
        )


def register_context_handlers(event_bus: EventBus, handler: Optional[ContextEventHandler] = None) -> None:
    """
    Register context event handlers with EventBus.
    
    Args:
        event_bus: EventBus to register handlers with
        handler: Optional custom handler (default: ContextEventHandler)
    """
    handler = handler or ContextEventHandler()
    
    # Register handlers for each event type
    event_bus.subscribe(
        ContextEventType.CONTEXT_GRAPH_UPDATED.value,
        handler.on_graph_updated,
        priority=10
    )
    
    event_bus.subscribe(
        ContextEventType.CONTEXT_NODE_TRUST_CHANGED.value,
        handler.on_trust_changed,
        priority=20
    )
    
    event_bus.subscribe(
        ContextEventType.CONTEXT_DRIFT_DETECTED.value,
        handler.on_drift_detected,
        priority=10
    )
    
    event_bus.subscribe(
        ContextEventType.CONTEXT_STALE_DETECTED.value,
        handler.on_stale_detected,
        priority=10
    )
    
    event_bus.subscribe(
        ContextEventType.CONTEXT_SUMMARY_PRUNED.value,
        handler.on_summary_pruned,
        priority=20
    )


# =============================================================================
# EventBus Integration Mixin
# =============================================================================

class EventBusEmitter:
    """
    Mixin for emitting events to EventBus.
    
    Provides convenient event emission methods for context components.
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        """Initialize with optional EventBus."""
        self._event_bus = event_bus
    
    def set_event_bus(self, event_bus: EventBus) -> None:
        """Set the EventBus instance."""
        self._event_bus = event_bus
    
    def _emit_event(self, event: Event) -> None:
        """Emit event to EventBus if available."""
        if self._event_bus:
            self._event_bus.emit(event)
    
    def _emit_graph_updated(self, **kwargs) -> None:
        """Emit CONTEXT_GRAPH_UPDATED event."""
        self._emit_event(create_graph_updated_event(**kwargs))
    
    def _emit_trust_changed(self, **kwargs) -> None:
        """Emit CONTEXT_NODE_TRUST_CHANGED event."""
        self._emit_event(create_node_trust_changed_event(**kwargs))
    
    def _emit_drift_detected(self, **kwargs) -> None:
        """Emit CONTEXT_DRIFT_DETECTED event."""
        self._emit_event(create_drift_detected_event(**kwargs))
    
    def _emit_stale_detected(self, **kwargs) -> None:
        """Emit CONTEXT_STALE_DETECTED event."""
        self._emit_event(create_stale_detected_event(**kwargs))
    
    def _emit_summary_pruned(self, **kwargs) -> None:
        """Emit CONTEXT_SUMMARY_PRUNED event."""
        self._emit_event(create_summary_pruned_event(**kwargs))


# =============================================================================
# Update EVENT_SEVERITY_MAP in event_bus.py
# =============================================================================

def extend_event_severity_map() -> None:
    """Extend the global EVENT_SEVERITY_MAP with context events."""
    from src.events import event_bus
    
    # Add context events to severity map
    event_bus.EVENT_SEVERITY_MAP.update(CONTEXT_EVENT_SEVERITY)


# Auto-extend on import
try:
    extend_event_severity_map()
except ImportError:
    pass  # event_bus not available yet
