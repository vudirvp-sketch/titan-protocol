"""
Agent Communication Protocol for TITAN FUSE Protocol.

ITEM-AGENT-02: Inter-agent communication with delivery guarantees.

Features:
- AgentMessageType enum for standardized message types
- AgentMessage dataclass for structured inter-agent communication
- AgentMessageRouter for message routing and broadcasting
- Integration with EventBus for delivery guarantees
- Dead Letter Queue support for failed deliveries

Author: TITAN FUSE Team
Version: 4.0.0
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..events.event_bus import EventBus, Event
    from ..events.dead_letter_queue import DeadLetterQueue


# Configure module logger
logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================

class AgentMessageType(Enum):
    """
    Types of messages exchanged between agents.
    
    Attributes:
        TASK_REQUEST: Request task assignment from orchestrator
        TASK_RESULT: Submit task execution result
        CONTEXT_SHARE: Share context/information with other agents
        ASSISTANCE_REQUEST: Request help from other agents
        DISCOVERY_BROADCAST: Broadcast discovered information
        HEARTBEAT: Agent alive signal for health monitoring
        STATUS_UPDATE: Update agent status information
    """
    TASK_REQUEST = "task_request"
    TASK_RESULT = "task_result"
    CONTEXT_SHARE = "context_share"
    ASSISTANCE_REQUEST = "assistance_request"
    DISCOVERY_BROADCAST = "discovery_broadcast"
    HEARTBEAT = "heartbeat"
    STATUS_UPDATE = "status_update"
    
    def is_broadcast_type(self) -> bool:
        """Check if this message type is typically broadcast."""
        return self in (
            AgentMessageType.DISCOVERY_BROADCAST,
            AgentMessageType.HEARTBEAT,
            AgentMessageType.STATUS_UPDATE,
        )
    
    def requires_response(self) -> bool:
        """Check if this message type typically requires a response."""
        return self in (
            AgentMessageType.TASK_REQUEST,
            AgentMessageType.ASSISTANCE_REQUEST,
        )


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class AgentMessage:
    """
    Message exchanged between agents in the TITAN FUSE Protocol.
    
    Attributes:
        message_id: Unique identifier for this message
        message_type: Type of message (from AgentMessageType enum)
        sender_id: ID of the agent sending this message
        recipient_id: ID of the recipient agent (None for broadcast)
        payload: Message payload data
        timestamp: When the message was created
        correlation_id: ID to correlate request/response pairs (optional)
    """
    message_id: str = field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:8]}")
    message_type: AgentMessageType = AgentMessageType.STATUS_UPDATE
    sender_id: str = ""
    recipient_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate message after initialization."""
        if isinstance(self.message_type, str):
            self.message_type = AgentMessageType(self.message_type)
    
    def is_broadcast(self) -> bool:
        """Check if this is a broadcast message."""
        return self.recipient_id is None
    
    def create_response(
        self,
        response_type: AgentMessageType,
        payload: Dict[str, Any],
        sender_id: str = "",
    ) -> "AgentMessage":
        """
        Create a response message correlated to this message.
        
        Args:
            response_type: Type of the response message
            payload: Response payload data
            sender_id: ID of the responding agent
            
        Returns:
            New AgentMessage with correlation_id set
        """
        return AgentMessage(
            message_type=response_type,
            sender_id=sender_id or self.recipient_id or "",
            recipient_id=self.sender_id,
            payload=payload,
            correlation_id=self.message_id,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentMessage":
        """Create from dictionary."""
        message_type = data.get("message_type", "status_update")
        if isinstance(message_type, str):
            message_type = AgentMessageType(message_type)
        
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.utcnow()
        
        return cls(
            message_id=data.get("message_id", f"msg-{uuid.uuid4().hex[:8]}"),
            message_type=message_type,
            sender_id=data.get("sender_id", ""),
            recipient_id=data.get("recipient_id"),
            payload=data.get("payload", {}),
            timestamp=timestamp,
            correlation_id=data.get("correlation_id"),
        )
    
    def to_event_data(self) -> Dict[str, Any]:
        """
        Convert to event data format for EventBus.
        
        Returns:
            Dictionary suitable for EventBus Event.data
        """
        return {
            "agent_message": self.to_dict(),
            "message_type": self.message_type.value,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "is_broadcast": self.is_broadcast(),
        }
    
    @classmethod
    def from_event(cls, event: "Event") -> Optional["AgentMessage"]:
        """
        Create AgentMessage from EventBus Event.
        
        Args:
            event: Event from EventBus
            
        Returns:
            AgentMessage if valid, None otherwise
        """
        if "agent_message" not in event.data:
            return None
        return cls.from_dict(event.data["agent_message"])


# =============================================================================
# Routing Statistics
# =============================================================================

@dataclass
class RouterStats:
    """
    Statistics for the AgentMessageRouter.
    
    Attributes:
        total_messages_routed: Total number of messages routed
        total_broadcasts: Total number of broadcast messages
        total_failures: Total number of failed deliveries
        active_subscribers: Number of active subscriber handlers
        messages_by_type: Count of messages by type
    """
    total_messages_routed: int = 0
    total_broadcasts: int = 0
    total_failures: int = 0
    active_subscribers: int = 0
    messages_by_type: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_messages_routed": self.total_messages_routed,
            "total_broadcasts": self.total_broadcasts,
            "total_failures": self.total_failures,
            "active_subscribers": self.active_subscribers,
            "messages_by_type": self.messages_by_type,
        }


# =============================================================================
# AgentMessageRouter Class
# =============================================================================

class AgentMessageRouter:
    """
    Router for inter-agent communication with delivery guarantees.
    
    Features:
    - Direct message routing to specific agents
    - Broadcast messaging to all subscribed agents
    - EventBus integration for delivery guarantees
    - Dead Letter Queue support for failed deliveries
    - Thread-safe subscriber management
    
    Usage:
        router = AgentMessageRouter(event_bus=event_bus)
        
        # Subscribe an agent to receive messages
        router.subscribe("agent-1", handler_function)
        
        # Route a message to a specific agent
        router.route(message)
        
        # Broadcast a message to all agents
        router.broadcast(broadcast_message)
    """
    
    # Event type prefix for agent messages
    AGENT_MESSAGE_EVENT_TYPE = "AGENT_MESSAGE"
    AGENT_MESSAGE_FAILURE_EVENT_TYPE = "EVENT_HANDLER_FAILURE"
    
    def __init__(
        self,
        event_bus: Optional["EventBus"] = None,
        dead_letter_queue: Optional["DeadLetterQueue"] = None,
    ):
        """
        Initialize the AgentMessageRouter.
        
        Args:
            event_bus: Optional EventBus for delivery guarantees
            dead_letter_queue: Optional DLQ for failed deliveries
        """
        self._event_bus = event_bus
        self._dlq = dead_letter_queue
        self._subscribers: Dict[str, List[Callable[[AgentMessage], None]]] = {}
        self._type_subscribers: Dict[AgentMessageType, List[Callable[[AgentMessage], None]]] = {}
        self._lock = threading.RLock()
        self._stats = RouterStats()
        
        # Register with EventBus if available
        if self._event_bus is not None:
            self._register_with_event_bus()
        
        logger.info("AgentMessageRouter initialized")
    
    def _register_with_event_bus(self) -> None:
        """Register message handler with EventBus."""
        # Subscribe to agent message events
        self._event_bus.subscribe(
            self.AGENT_MESSAGE_EVENT_TYPE,
            self._handle_event_bus_message,
            priority=5,  # Higher priority for agent messages
        )
        
        logger.debug("Registered with EventBus for agent message handling")
    
    def _handle_event_bus_message(self, event: "Event") -> None:
        """
        Handle messages coming from EventBus.
        
        Args:
            event: Event containing AgentMessage
        """
        message = AgentMessage.from_event(event)
        if message is None:
            return
        
        # Route through our internal routing
        if message.is_broadcast():
            self._deliver_broadcast(message)
        else:
            self._deliver_to_recipient(message)
    
    def subscribe(
        self,
        agent_id: str,
        handler: Callable[[AgentMessage], None],
    ) -> None:
        """
        Subscribe an agent to receive messages.
        
        Args:
            agent_id: ID of the agent to subscribe
            handler: Function to call when message is received
        """
        with self._lock:
            if agent_id not in self._subscribers:
                self._subscribers[agent_id] = []
            self._subscribers[agent_id].append(handler)
            self._stats.active_subscribers = sum(
                len(handlers) for handlers in self._subscribers.values()
            )
        
        logger.debug(f"Subscribed handler for agent: {agent_id}")
    
    def subscribe_to_type(
        self,
        message_type: AgentMessageType,
        handler: Callable[[AgentMessage], None],
    ) -> None:
        """
        Subscribe to all messages of a specific type.
        
        Args:
            message_type: Type of messages to receive
            handler: Function to call when matching message is received
        """
        with self._lock:
            if message_type not in self._type_subscribers:
                self._type_subscribers[message_type] = []
            self._type_subscribers[message_type].append(handler)
        
        logger.debug(f"Subscribed handler for message type: {message_type.value}")
    
    def unsubscribe(
        self,
        agent_id: str,
        handler: Optional[Callable[[AgentMessage], None]] = None,
    ) -> bool:
        """
        Unsubscribe an agent from receiving messages.
        
        Args:
            agent_id: ID of the agent to unsubscribe
            handler: Optional specific handler to remove (removes all if None)
            
        Returns:
            True if unsubscribe was successful
        """
        with self._lock:
            if agent_id not in self._subscribers:
                return False
            
            if handler is None:
                del self._subscribers[agent_id]
            else:
                try:
                    self._subscribers[agent_id].remove(handler)
                    if not self._subscribers[agent_id]:
                        del self._subscribers[agent_id]
                except ValueError:
                    return False
            
            self._stats.active_subscribers = sum(
                len(handlers) for handlers in self._subscribers.values()
            )
        
        logger.debug(f"Unsubscribed handler for agent: {agent_id}")
        return True
    
    def route(self, message: AgentMessage) -> bool:
        """
        Route a message to the intended recipient.
        
        For direct messages (recipient_id set), delivers to that agent.
        For broadcast messages (recipient_id is None), use broadcast() instead.
        
        Args:
            message: Message to route
            
        Returns:
            True if message was routed successfully
        """
        if message.is_broadcast():
            logger.warning("Use broadcast() for broadcast messages")
            return self._deliver_broadcast(message)
        
        # Emit to EventBus if available (for delivery guarantees)
        if self._event_bus is not None:
            self._emit_to_event_bus(message)
        
        return self._deliver_to_recipient(message)
    
    def broadcast(self, message: AgentMessage) -> bool:
        """
        Broadcast a message to all subscribed agents.
        
        Args:
            message: Message to broadcast (recipient_id should be None)
            
        Returns:
            True if broadcast was successful
        """
        # Ensure this is a broadcast message
        if message.recipient_id is not None:
            logger.warning("Broadcast message has recipient_id set, clearing it")
            message.recipient_id = None
        
        # Emit to EventBus if available
        if self._event_bus is not None:
            self._emit_to_event_bus(message)
        
        return self._deliver_broadcast(message)
    
    def _emit_to_event_bus(self, message: AgentMessage) -> None:
        """
        Emit message to EventBus for delivery guarantees.
        
        Converts AgentMessage to Event and emits through EventBus,
        which provides WAL journaling and DLQ support.
        
        Args:
            message: Message to emit
        """
        from ..events.event_bus import Event, EventSeverity
        
        event = Event(
            event_type=self.AGENT_MESSAGE_EVENT_TYPE,
            data=message.to_event_data(),
            severity=EventSeverity.INFO,
            source="AgentMessageRouter",
        )
        
        self._event_bus.emit(event)
        logger.debug(f"Emitted message {message.message_id} to EventBus")
    
    def _deliver_to_recipient(self, message: AgentMessage) -> bool:
        """
        Deliver message to specific recipient agent(s).
        
        Args:
            message: Message to deliver
            
        Returns:
            True if delivery was successful
        """
        with self._lock:
            recipients = self._subscribers.get(message.recipient_id, [])
            type_handlers = self._type_subscribers.get(message.message_type, [])
        
        if not recipients and not type_handlers:
            logger.warning(
                f"No subscribers found for recipient: {message.recipient_id}"
            )
            return False
        
        # Deliver to recipient handlers
        success = True
        for handler in recipients:
            success &= self._safe_deliver(handler, message)
        
        # Deliver to type-specific handlers
        for handler in type_handlers:
            success &= self._safe_deliver(handler, message)
        
        # Update stats
        self._update_stats(message, success)
        
        return success
    
    def _deliver_broadcast(self, message: AgentMessage) -> bool:
        """
        Deliver broadcast message to all subscribed agents.
        
        Args:
            message: Message to broadcast
            
        Returns:
            True if broadcast was successful to at least one agent
        """
        with self._lock:
            all_handlers: List[Callable[[AgentMessage], None]] = []
            for handlers in self._subscribers.values():
                all_handlers.extend(handlers)
            
            type_handlers = self._type_subscribers.get(message.message_type, [])
        
        if not all_handlers and not type_handlers:
            logger.warning("No subscribers for broadcast message")
            return False
        
        # Deliver to all handlers (excluding sender)
        success = False
        for handler in all_handlers:
            if self._safe_deliver(handler, message):
                success = True
        
        # Deliver to type-specific handlers
        for handler in type_handlers:
            if self._safe_deliver(handler, message):
                success = True
        
        # Update stats
        with self._lock:
            self._stats.total_broadcasts += 1
        
        self._update_stats(message, success)
        
        return success
    
    def _safe_deliver(
        self,
        handler: Callable[[AgentMessage], None],
        message: AgentMessage,
    ) -> bool:
        """
        Safely deliver message to handler with error handling.
        
        On failure, the message is enqueued to DLQ if available.
        
        Args:
            handler: Handler function to call
            message: Message to deliver
            
        Returns:
            True if delivery was successful
        """
        try:
            handler(message)
            return True
        except Exception as e:
            logger.error(
                f"Handler failed for message {message.message_id}: {e}"
            )
            self._handle_delivery_failure(message, e, handler)
            return False
    
    def _handle_delivery_failure(
        self,
        message: AgentMessage,
        error: Exception,
        handler: Callable[[AgentMessage], None],
    ) -> None:
        """
        Handle message delivery failure.
        
        Uses DLQ for retry mechanism and emits EVENT_HANDLER_FAILURE
        event for monitoring.
        
        Args:
            message: Message that failed delivery
            error: Exception that caused the failure
            handler: Handler that failed
        """
        handler_name = getattr(handler, '__name__', str(handler))
        
        # Enqueue to DLQ if available
        dlq_id = None
        if self._dlq is not None:
            from ..events.event_bus import Event, EventSeverity
            
            # Create a synthetic event for DLQ
            synthetic_event = Event(
                event_type=self.AGENT_MESSAGE_EVENT_TYPE,
                data=message.to_event_data(),
                severity=EventSeverity.INFO,
                source="AgentMessageRouter",
            )
            dlq_id = self._dlq.enqueue(
                event=synthetic_event,
                error=error,
                context={
                    "handler": handler_name,
                    "message_id": message.message_id,
                    "message_type": message.message_type.value,
                    "sender_id": message.sender_id,
                    "recipient_id": message.recipient_id,
                },
            )
            logger.info(f"Message {message.message_id} enqueued to DLQ: {dlq_id}")
        
        # Emit failure event
        if self._event_bus is not None:
            from ..events.event_bus import Event, EventSeverity
            
            failure_event = Event(
                event_type=self.AGENT_MESSAGE_FAILURE_EVENT_TYPE,
                data={
                    "failed_handler": handler_name,
                    "original_message_id": message.message_id,
                    "original_message_type": message.message_type.value,
                    "sender_id": message.sender_id,
                    "recipient_id": message.recipient_id,
                    "error": str(error),
                    "error_type": type(error).__name__,
                    "dlq_id": dlq_id,
                },
                severity=EventSeverity.CRITICAL,
                source="AgentMessageRouter",
            )
            self._event_bus.emit(failure_event)
        
        # Update failure stats
        with self._lock:
            self._stats.total_failures += 1
    
    def _update_stats(self, message: AgentMessage, success: bool) -> None:
        """Update routing statistics."""
        with self._lock:
            self._stats.total_messages_routed += 1
            
            type_name = message.message_type.value
            self._stats.messages_by_type[type_name] = (
                self._stats.messages_by_type.get(type_name, 0) + 1
            )
    
    def get_stats(self) -> RouterStats:
        """
        Get router statistics.
        
        Returns:
            RouterStats with current statistics
        """
        with self._lock:
            self._stats.active_subscribers = sum(
                len(handlers) for handlers in self._subscribers.values()
            )
            return RouterStats(
                total_messages_routed=self._stats.total_messages_routed,
                total_broadcasts=self._stats.total_broadcasts,
                total_failures=self._stats.total_failures,
                active_subscribers=self._stats.active_subscribers,
                messages_by_type=dict(self._stats.messages_by_type),
            )
    
    def set_event_bus(self, event_bus: "EventBus") -> None:
        """
        Set or update the EventBus.
        
        Args:
            event_bus: EventBus instance
        """
        self._event_bus = event_bus
        self._register_with_event_bus()
        logger.info("EventBus attached to AgentMessageRouter")
    
    def set_dlq(self, dlq: "DeadLetterQueue") -> None:
        """
        Set or update the Dead Letter Queue.
        
        Args:
            dlq: DeadLetterQueue instance
        """
        self._dlq = dlq
        logger.info("Dead Letter Queue attached to AgentMessageRouter")
    
    def get_subscribers(self) -> List[str]:
        """Get list of subscribed agent IDs."""
        with self._lock:
            return list(self._subscribers.keys())
    
    def has_subscriber(self, agent_id: str) -> bool:
        """Check if an agent is subscribed."""
        with self._lock:
            return agent_id in self._subscribers
    
    def clear_subscribers(self) -> None:
        """Remove all subscribers."""
        with self._lock:
            self._subscribers.clear()
            self._type_subscribers.clear()
            self._stats.active_subscribers = 0
        
        logger.info("All subscribers cleared from AgentMessageRouter")


# =============================================================================
# Factory Functions
# =============================================================================

def create_message_router(
    event_bus: Optional["EventBus"] = None,
    dlq: Optional["DeadLetterQueue"] = None,
) -> AgentMessageRouter:
    """
    Create an AgentMessageRouter with optional EventBus and DLQ.
    
    Args:
        event_bus: Optional EventBus for delivery guarantees
        dlq: Optional DeadLetterQueue for failed deliveries
        
    Returns:
        Configured AgentMessageRouter instance
    """
    return AgentMessageRouter(event_bus=event_bus, dead_letter_queue=dlq)


# =============================================================================
# Convenience Message Creators
# =============================================================================

def create_heartbeat_message(
    agent_id: str,
    status: str = "idle",
    metadata: Optional[Dict[str, Any]] = None,
) -> AgentMessage:
    """
    Create a heartbeat message for an agent.
    
    Args:
        agent_id: ID of the sending agent
        status: Current status of the agent
        metadata: Optional additional metadata
        
    Returns:
        AgentMessage configured as a heartbeat
    """
    return AgentMessage(
        message_type=AgentMessageType.HEARTBEAT,
        sender_id=agent_id,
        payload={
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {},
        },
    )


def create_task_request_message(
    agent_id: str,
    capabilities: List[str],
    priority: int = 2,
) -> AgentMessage:
    """
    Create a task request message.
    
    Args:
        agent_id: ID of the agent requesting work
        capabilities: Capabilities the agent has
        priority: Request priority (lower = higher priority)
        
    Returns:
        AgentMessage configured as a task request
    """
    return AgentMessage(
        message_type=AgentMessageType.TASK_REQUEST,
        sender_id=agent_id,
        payload={
            "capabilities": capabilities,
            "priority": priority,
            "requested_at": datetime.utcnow().isoformat(),
        },
    )


def create_task_result_message(
    agent_id: str,
    task_id: str,
    success: bool,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> AgentMessage:
    """
    Create a task result message.
    
    Args:
        agent_id: ID of the agent submitting the result
        task_id: ID of the completed task
        success: Whether the task succeeded
        result: Result data if successful
        error: Error message if failed
        correlation_id: ID of the original task assignment message
        
    Returns:
        AgentMessage configured as a task result
    """
    return AgentMessage(
        message_type=AgentMessageType.TASK_RESULT,
        sender_id=agent_id,
        payload={
            "task_id": task_id,
            "success": success,
            "result": result or {},
            "error": error,
            "completed_at": datetime.utcnow().isoformat(),
        },
        correlation_id=correlation_id,
    )


def create_context_share_message(
    agent_id: str,
    context_type: str,
    context_data: Dict[str, Any],
    ttl_seconds: Optional[int] = None,
) -> AgentMessage:
    """
    Create a context sharing message.
    
    Args:
        agent_id: ID of the sharing agent
        context_type: Type of context being shared
        context_data: The context data
        ttl_seconds: Optional time-to-live for the context
        
    Returns:
        AgentMessage configured as a context share
    """
    payload: Dict[str, Any] = {
        "context_type": context_type,
        "context_data": context_data,
        "shared_at": datetime.utcnow().isoformat(),
    }
    if ttl_seconds is not None:
        payload["ttl_seconds"] = ttl_seconds
    
    return AgentMessage(
        message_type=AgentMessageType.CONTEXT_SHARE,
        sender_id=agent_id,
        payload=payload,
    )


def create_assistance_request_message(
    agent_id: str,
    assistance_type: str,
    description: str,
    required_capabilities: Optional[List[str]] = None,
    urgency: int = 2,
) -> AgentMessage:
    """
    Create an assistance request message.
    
    Args:
        agent_id: ID of the requesting agent
        assistance_type: Type of assistance needed
        description: Description of what's needed
        required_capabilities: Capabilities required to help
        urgency: Urgency level (lower = more urgent)
        
    Returns:
        AgentMessage configured as an assistance request
    """
    return AgentMessage(
        message_type=AgentMessageType.ASSISTANCE_REQUEST,
        sender_id=agent_id,
        payload={
            "assistance_type": assistance_type,
            "description": description,
            "required_capabilities": required_capabilities or [],
            "urgency": urgency,
            "requested_at": datetime.utcnow().isoformat(),
        },
    )


def create_discovery_broadcast_message(
    agent_id: str,
    discovery_type: str,
    discovered_info: Dict[str, Any],
) -> AgentMessage:
    """
    Create a discovery broadcast message.
    
    Args:
        agent_id: ID of the discovering agent
        discovery_type: Type of discovery
        discovered_info: The discovered information
        
    Returns:
        AgentMessage configured as a discovery broadcast
    """
    return AgentMessage(
        message_type=AgentMessageType.DISCOVERY_BROADCAST,
        sender_id=agent_id,
        payload={
            "discovery_type": discovery_type,
            "discovered_info": discovered_info,
            "discovered_at": datetime.utcnow().isoformat(),
        },
    )


def create_status_update_message(
    agent_id: str,
    old_status: str,
    new_status: str,
    reason: Optional[str] = None,
) -> AgentMessage:
    """
    Create a status update message.
    
    Args:
        agent_id: ID of the updating agent
        old_status: Previous status
        new_status: New status
        reason: Reason for the status change
        
    Returns:
        AgentMessage configured as a status update
    """
    return AgentMessage(
        message_type=AgentMessageType.STATUS_UPDATE,
        sender_id=agent_id,
        payload={
            "old_status": old_status,
            "new_status": new_status,
            "reason": reason,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )
