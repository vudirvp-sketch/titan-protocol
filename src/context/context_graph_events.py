#!/usr/bin/env python3
"""
TITAN Protocol - Context Graph with EventBus Integration

ITEM-SAE-010: Context Graph EventBus Integration

Extends ContextGraph to emit events on state changes.
Provides full observability into context graph operations.

Integration:
    - CONTEXT_GRAPH_UPDATED: When nodes/edges change
    - CONTEXT_NODE_TRUST_CHANGED: When trust scores update
    - CONTEXT_STALE_DETECTED: When stale nodes are detected
    - CONTEXT_VERSION_CONFLICT: When version conflicts occur

Author: TITAN FUSE Team
Version: 1.0.0
"""

from typing import Optional, Dict, Any, List
import logging

from src.context.context_graph import (
    ContextGraph as BaseContextGraph,
    ContextNode,
    ContextEdge,
    NodeType,
    EdgeRelation,
    TrustTier,
    VersionVector,
)
from src.events.event_bus import EventBus, get_event_bus
from src.events.context_events import (
    create_graph_updated_event,
    create_node_trust_changed_event,
    create_stale_detected_event,
    EventBusEmitter,
)


class ContextGraphWithEvents(BaseContextGraph, EventBusEmitter):
    """
    ContextGraph with EventBus integration.
    
    Emits events on all state changes for observability.
    
    Usage:
        from src.events.event_bus import get_event_bus
        
        event_bus = get_event_bus()
        graph = ContextGraphWithEvents(event_bus=event_bus)
        
        # Events are emitted automatically
        graph.add_node(node)  # Emits CONTEXT_GRAPH_UPDATED
        graph.update_trust_score("file.py", 0.1)  # Emits CONTEXT_NODE_TRUST_CHANGED
    """
    
    def __init__(
        self,
        session_id: Optional[str] = None,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize with optional EventBus.
        
        Args:
            session_id: Optional session ID
            event_bus: Optional EventBus for event emission
        """
        super().__init__(session_id=session_id)
        EventBusEmitter.__init__(self, event_bus=event_bus)
        
        # Track changes for batch events
        self._pending_changes: Dict[str, int] = {
            "nodes_added": 0,
            "nodes_removed": 0,
            "nodes_modified": 0,
        }
        
        self._logger = logging.getLogger(__name__)
    
    # =========================================================================
    # Override Node Operations
    # =========================================================================
    
    def add_node(self, node: ContextNode) -> None:
        """Add node and emit event."""
        super().add_node(node)
        
        self._pending_changes["nodes_added"] += 1
        
        # Emit event
        self._emit_graph_updated(
            graph_version="1.0.0",
            nodes_added=1,
            nodes_removed=0,
            nodes_modified=0,
            source="ContextGraphWithEvents.add_node"
        )
    
    def remove_node(self, node_id: str) -> bool:
        """Remove node and emit event."""
        result = super().remove_node(node_id)
        
        if result:
            self._pending_changes["nodes_removed"] += 1
            
            self._emit_graph_updated(
                graph_version="1.0.0",
                nodes_added=0,
                nodes_removed=1,
                nodes_modified=0,
                source="ContextGraphWithEvents.remove_node"
            )
        
        return result
    
    # =========================================================================
    # Override Trust Operations
    # =========================================================================
    
    def update_trust_score(self, node_id: str, delta: float) -> bool:
        """Update trust score and emit event."""
        node = self.get_node(node_id)
        if not node:
            return False
        
        old_score = node.trust_score
        result = super().update_trust_score(node_id, delta)
        
        if result:
            new_score = node.trust_score
            
            self._emit_trust_changed(
                node_id=node_id,
                old_trust=old_score,
                new_trust=new_score,
                reason=f"delta:{delta:+.3f}",
                source="ContextGraphWithEvents.update_trust_score"
            )
        
        return result
    
    def boost_related_nodes(self, node_id: str, boost: float = 0.05) -> None:
        """Boost related nodes and emit events."""
        neighbors = self.get_neighbors(node_id)
        
        for neighbor_id in neighbors:
            node = self.get_node(neighbor_id)
            if node:
                old_score = node.trust_score
                super().update_trust_score(neighbor_id, boost)
                
                self._emit_trust_changed(
                    node_id=neighbor_id,
                    old_trust=old_score,
                    new_trust=node.trust_score,
                    reason=f"related_boost_from:{node_id}",
                    source="ContextGraphWithEvents.boost_related_nodes"
                )
    
    # =========================================================================
    # Override Stale Detection
    # =========================================================================
    
    def detect_stale_nodes(
        self,
        max_age_hours: float = 24.0,
        min_trust: float = 0.3
    ) -> List[ContextNode]:
        """Detect stale nodes and emit events."""
        stale = super().detect_stale_nodes(max_age_hours, min_trust)
        
        for node in stale:
            self._emit_stale_detected(
                node_id=node.id,
                stale_reason=f"age>{max_age_hours}h or trust<{min_trust}",
                suggested_action="refresh",
                last_modified=node.last_modified.isoformat() if node.last_modified else None,
                source="ContextGraphWithEvents.detect_stale_nodes"
            )
        
        return stale
    
    # =========================================================================
    # Additional Event Methods
    # =========================================================================
    
    def emit_version_conflict(
        self,
        node_id: str,
        vector1: Dict[str, int],
        vector2: Dict[str, int]
    ) -> None:
        """Emit version conflict event."""
        from src.events.context_events import Event, ContextEventType, CONTEXT_EVENT_SEVERITY
        
        event = Event(
            event_type=ContextEventType.CONTEXT_VERSION_CONFLICT.value,
            data={
                "node_id": node_id,
                "vector1": vector1,
                "vector2": vector2,
            },
            severity=CONTEXT_EVENT_SEVERITY[ContextEventType.CONTEXT_VERSION_CONFLICT.value],
            source="ContextGraphWithEvents",
        )
        self._emit_event(event)
    
    def get_pending_changes(self) -> Dict[str, int]:
        """Get pending changes count."""
        return dict(self._pending_changes)
    
    def reset_pending_changes(self) -> None:
        """Reset pending changes counter."""
        self._pending_changes = {
            "nodes_added": 0,
            "nodes_removed": 0,
            "nodes_modified": 0,
        }


def create_context_graph_with_events(
    session_id: Optional[str] = None,
    event_bus: Optional[EventBus] = None,
) -> ContextGraphWithEvents:
    """
    Factory function to create ContextGraphWithEvents.
    
    Args:
        session_id: Optional session ID
        event_bus: Optional EventBus (uses default if not provided)
        
    Returns:
        ContextGraphWithEvents instance
    """
    if event_bus is None:
        try:
            event_bus = get_event_bus()
        except Exception:
            pass  # EventBus not available
    
    return ContextGraphWithEvents(
        session_id=session_id,
        event_bus=event_bus
    )
