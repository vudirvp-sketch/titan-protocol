"""
Tests for Agent Communication Protocol.

ITEM-AGENT-02: Test suite for inter-agent communication.

Tests cover:
- AgentMessageType enum
- AgentMessage dataclass
- AgentMessageRouter routing and broadcasting
- EventBus integration
- Dead Letter Queue integration
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
import threading
import time

from src.agents.agent_protocol import (
    AgentMessageType,
    AgentMessage,
    RouterStats,
    AgentMessageRouter,
    create_message_router,
    create_heartbeat_message,
    create_task_request_message,
    create_task_result_message,
    create_context_share_message,
    create_assistance_request_message,
    create_discovery_broadcast_message,
    create_status_update_message,
)


# =============================================================================
# AgentMessageType Tests
# =============================================================================

class TestAgentMessageType:
    """Tests for AgentMessageType enum."""
    
    def test_message_type_values(self):
        """Test AgentMessageType enum values."""
        assert AgentMessageType.TASK_REQUEST.value == "task_request"
        assert AgentMessageType.TASK_RESULT.value == "task_result"
        assert AgentMessageType.CONTEXT_SHARE.value == "context_share"
        assert AgentMessageType.ASSISTANCE_REQUEST.value == "assistance_request"
        assert AgentMessageType.DISCOVERY_BROADCAST.value == "discovery_broadcast"
        assert AgentMessageType.HEARTBEAT.value == "heartbeat"
        assert AgentMessageType.STATUS_UPDATE.value == "status_update"
    
    def test_is_broadcast_type(self):
        """Test is_broadcast_type method."""
        assert AgentMessageType.DISCOVERY_BROADCAST.is_broadcast_type() is True
        assert AgentMessageType.HEARTBEAT.is_broadcast_type() is True
        assert AgentMessageType.STATUS_UPDATE.is_broadcast_type() is True
        
        assert AgentMessageType.TASK_REQUEST.is_broadcast_type() is False
        assert AgentMessageType.TASK_RESULT.is_broadcast_type() is False
        assert AgentMessageType.CONTEXT_SHARE.is_broadcast_type() is False
    
    def test_requires_response(self):
        """Test requires_response method."""
        assert AgentMessageType.TASK_REQUEST.requires_response() is True
        assert AgentMessageType.ASSISTANCE_REQUEST.requires_response() is True
        
        assert AgentMessageType.TASK_RESULT.requires_response() is False
        assert AgentMessageType.HEARTBEAT.requires_response() is False
        assert AgentMessageType.DISCOVERY_BROADCAST.requires_response() is False


# =============================================================================
# AgentMessage Tests
# =============================================================================

class TestAgentMessage:
    """Tests for AgentMessage dataclass."""
    
    def test_message_creation(self):
        """Test creating an agent message."""
        message = AgentMessage(
            message_type=AgentMessageType.TASK_REQUEST,
            sender_id="agent-1",
            recipient_id="agent-2",
            payload={"task": "analyze"},
        )
        
        assert message.message_type == AgentMessageType.TASK_REQUEST
        assert message.sender_id == "agent-1"
        assert message.recipient_id == "agent-2"
        assert message.payload == {"task": "analyze"}
        assert message.message_id.startswith("msg-")
        assert message.timestamp is not None
    
    def test_message_creation_with_string_type(self):
        """Test creating message with string message type."""
        message = AgentMessage(
            message_type="task_request",
            sender_id="agent-1",
        )
        
        assert message.message_type == AgentMessageType.TASK_REQUEST
    
    def test_is_broadcast(self):
        """Test is_broadcast method."""
        direct_message = AgentMessage(
            sender_id="agent-1",
            recipient_id="agent-2",
        )
        assert direct_message.is_broadcast() is False
        
        broadcast_message = AgentMessage(
            sender_id="agent-1",
            recipient_id=None,
        )
        assert broadcast_message.is_broadcast() is True
    
    def test_create_response(self):
        """Test create_response method."""
        original = AgentMessage(
            message_id="msg-original",
            message_type=AgentMessageType.TASK_REQUEST,
            sender_id="agent-1",
            recipient_id="agent-2",
            payload={"task": "analyze"},
        )
        
        response = original.create_response(
            response_type=AgentMessageType.TASK_RESULT,
            payload={"result": "done"},
            sender_id="agent-2",
        )
        
        assert response.message_type == AgentMessageType.TASK_RESULT
        assert response.sender_id == "agent-2"
        assert response.recipient_id == "agent-1"
        assert response.correlation_id == "msg-original"
        assert response.payload == {"result": "done"}
    
    def test_to_dict(self):
        """Test to_dict method."""
        message = AgentMessage(
            message_id="msg-123",
            message_type=AgentMessageType.HEARTBEAT,
            sender_id="agent-1",
            payload={"status": "idle"},
            correlation_id="corr-456",
        )
        
        data = message.to_dict()
        
        assert data["message_id"] == "msg-123"
        assert data["message_type"] == "heartbeat"
        assert data["sender_id"] == "agent-1"
        assert data["recipient_id"] is None
        assert data["payload"] == {"status": "idle"}
        assert data["correlation_id"] == "corr-456"
    
    def test_from_dict(self):
        """Test from_dict method."""
        data = {
            "message_id": "msg-123",
            "message_type": "heartbeat",
            "sender_id": "agent-1",
            "recipient_id": None,
            "payload": {"status": "idle"},
            "timestamp": datetime.utcnow().isoformat(),
            "correlation_id": "corr-456",
        }
        
        message = AgentMessage.from_dict(data)
        
        assert message.message_id == "msg-123"
        assert message.message_type == AgentMessageType.HEARTBEAT
        assert message.sender_id == "agent-1"
        assert message.recipient_id is None
        assert message.correlation_id == "corr-456"
    
    def test_to_event_data(self):
        """Test to_event_data method."""
        message = AgentMessage(
            message_type=AgentMessageType.TASK_REQUEST,
            sender_id="agent-1",
            recipient_id="agent-2",
            payload={"task": "analyze"},
        )
        
        event_data = message.to_event_data()
        
        assert "agent_message" in event_data
        assert event_data["message_type"] == "task_request"
        assert event_data["sender_id"] == "agent-1"
        assert event_data["recipient_id"] == "agent-2"
        assert event_data["is_broadcast"] is False
    
    def test_from_event(self):
        """Test from_event method."""
        mock_event = Mock()
        mock_event.data = {
            "agent_message": {
                "message_id": "msg-123",
                "message_type": "heartbeat",
                "sender_id": "agent-1",
                "recipient_id": None,
                "payload": {"status": "idle"},
                "timestamp": datetime.utcnow().isoformat(),
            }
        }
        
        message = AgentMessage.from_event(mock_event)
        
        assert message is not None
        assert message.message_id == "msg-123"
        assert message.message_type == AgentMessageType.HEARTBEAT
    
    def test_from_event_invalid(self):
        """Test from_event with invalid event."""
        mock_event = Mock()
        mock_event.data = {}
        
        message = AgentMessage.from_event(mock_event)
        
        assert message is None


# =============================================================================
# RouterStats Tests
# =============================================================================

class TestRouterStats:
    """Tests for RouterStats dataclass."""
    
    def test_stats_creation(self):
        """Test creating router stats."""
        stats = RouterStats(
            total_messages_routed=100,
            total_broadcasts=20,
            total_failures=5,
            active_subscribers=10,
            messages_by_type={"heartbeat": 50, "task_request": 30},
        )
        
        assert stats.total_messages_routed == 100
        assert stats.total_broadcasts == 20
        assert stats.total_failures == 5
        assert stats.active_subscribers == 10
    
    def test_to_dict(self):
        """Test to_dict method."""
        stats = RouterStats(
            total_messages_routed=100,
            total_broadcasts=20,
            messages_by_type={"heartbeat": 50},
        )
        
        data = stats.to_dict()
        
        assert data["total_messages_routed"] == 100
        assert data["total_broadcasts"] == 20
        assert data["messages_by_type"] == {"heartbeat": 50}


# =============================================================================
# AgentMessageRouter Tests
# =============================================================================

class TestAgentMessageRouter:
    """Tests for AgentMessageRouter class."""
    
    def test_router_creation(self):
        """Test creating a router."""
        router = AgentMessageRouter()
        
        assert router is not None
        stats = router.get_stats()
        assert stats.total_messages_routed == 0
        assert stats.active_subscribers == 0
    
    def test_router_creation_with_event_bus(self):
        """Test creating router with EventBus."""
        mock_event_bus = Mock()
        mock_event_bus.subscribe = Mock()
        
        router = AgentMessageRouter(event_bus=mock_event_bus)
        
        assert router._event_bus == mock_event_bus
        mock_event_bus.subscribe.assert_called_once()
    
    def test_subscribe(self):
        """Test subscribing an agent."""
        router = AgentMessageRouter()
        handler = Mock()
        
        router.subscribe("agent-1", handler)
        
        assert router.has_subscriber("agent-1")
        stats = router.get_stats()
        assert stats.active_subscribers == 1
    
    def test_subscribe_multiple_handlers(self):
        """Test subscribing multiple handlers for same agent."""
        router = AgentMessageRouter()
        handler1 = Mock()
        handler2 = Mock()
        
        router.subscribe("agent-1", handler1)
        router.subscribe("agent-1", handler2)
        
        stats = router.get_stats()
        assert stats.active_subscribers == 2
    
    def test_subscribe_to_type(self):
        """Test subscribing to message type."""
        router = AgentMessageRouter()
        handler = Mock()
        
        router.subscribe_to_type(AgentMessageType.HEARTBEAT, handler)
        
        # Verify by sending a heartbeat message
        message = AgentMessage(
            message_type=AgentMessageType.HEARTBEAT,
            sender_id="agent-1",
            recipient_id="agent-2",
        )
        
        router.route(message)
        handler.assert_called_once_with(message)
    
    def test_unsubscribe(self):
        """Test unsubscribing an agent."""
        router = AgentMessageRouter()
        handler = Mock()
        
        router.subscribe("agent-1", handler)
        result = router.unsubscribe("agent-1")
        
        assert result is True
        assert not router.has_subscriber("agent-1")
    
    def test_unsubscribe_specific_handler(self):
        """Test unsubscribing a specific handler."""
        router = AgentMessageRouter()
        handler1 = Mock()
        handler2 = Mock()
        
        router.subscribe("agent-1", handler1)
        router.subscribe("agent-1", handler2)
        
        result = router.unsubscribe("agent-1", handler1)
        
        assert result is True
        assert router.has_subscriber("agent-1")
        stats = router.get_stats()
        assert stats.active_subscribers == 1
    
    def test_unsubscribe_nonexistent(self):
        """Test unsubscribing non-existent agent."""
        router = AgentMessageRouter()
        
        result = router.unsubscribe("non-existent")
        
        assert result is False
    
    def test_route_direct_message(self):
        """Test routing a direct message."""
        router = AgentMessageRouter()
        handler = Mock()
        
        router.subscribe("agent-2", handler)
        
        message = AgentMessage(
            message_type=AgentMessageType.TASK_RESULT,
            sender_id="agent-1",
            recipient_id="agent-2",
            payload={"result": "done"},
        )
        
        result = router.route(message)
        
        assert result is True
        handler.assert_called_once_with(message)
    
    def test_route_message_no_recipient(self):
        """Test routing to non-existent recipient."""
        router = AgentMessageRouter()
        
        message = AgentMessage(
            message_type=AgentMessageType.TASK_RESULT,
            sender_id="agent-1",
            recipient_id="non-existent",
        )
        
        result = router.route(message)
        
        assert result is False
    
    def test_broadcast(self):
        """Test broadcasting a message."""
        router = AgentMessageRouter()
        handler1 = Mock()
        handler2 = Mock()
        
        router.subscribe("agent-1", handler1)
        router.subscribe("agent-2", handler2)
        
        message = AgentMessage(
            message_type=AgentMessageType.DISCOVERY_BROADCAST,
            sender_id="agent-3",
            recipient_id=None,  # Broadcast
            payload={"info": "discovered"},
        )
        
        result = router.broadcast(message)
        
        assert result is True
        handler1.assert_called_once_with(message)
        handler2.assert_called_once_with(message)
    
    def test_broadcast_no_subscribers(self):
        """Test broadcasting with no subscribers."""
        router = AgentMessageRouter()
        
        message = AgentMessage(
            message_type=AgentMessageType.DISCOVERY_BROADCAST,
            sender_id="agent-1",
        )
        
        result = router.broadcast(message)
        
        assert result is False
    
    def test_route_with_event_bus(self):
        """Test that route emits to EventBus."""
        mock_event_bus = Mock()
        mock_event_bus.subscribe = Mock()
        mock_event_bus.emit = Mock()
        
        router = AgentMessageRouter(event_bus=mock_event_bus)
        handler = Mock()
        router.subscribe("agent-2", handler)
        
        message = AgentMessage(
            message_type=AgentMessageType.TASK_RESULT,
            sender_id="agent-1",
            recipient_id="agent-2",
        )
        
        router.route(message)
        
        mock_event_bus.emit.assert_called_once()
        call_args = mock_event_bus.emit.call_args
        event = call_args[0][0]
        assert event.event_type == "AGENT_MESSAGE"
    
    def test_handler_failure_without_dlq(self):
        """Test handler failure without DLQ."""
        router = AgentMessageRouter()
        failing_handler = Mock(side_effect=Exception("Handler failed"))
        
        router.subscribe("agent-2", failing_handler)
        
        message = AgentMessage(
            message_type=AgentMessageType.TASK_RESULT,
            sender_id="agent-1",
            recipient_id="agent-2",
        )
        
        result = router.route(message)
        
        assert result is False
        stats = router.get_stats()
        assert stats.total_failures == 1
    
    def test_handler_failure_with_dlq(self):
        """Test handler failure with DLQ."""
        mock_event_bus = Mock()
        mock_event_bus.subscribe = Mock()
        mock_event_bus.emit = Mock()
        
        mock_dlq = Mock()
        mock_dlq.enqueue = Mock(return_value="dlq-123")
        
        router = AgentMessageRouter(
            event_bus=mock_event_bus,
            dead_letter_queue=mock_dlq,
        )
        
        failing_handler = Mock(side_effect=Exception("Handler failed"))
        router.subscribe("agent-2", failing_handler)
        
        message = AgentMessage(
            message_type=AgentMessageType.TASK_RESULT,
            sender_id="agent-1",
            recipient_id="agent-2",
        )
        
        result = router.route(message)
        
        assert result is False
        mock_dlq.enqueue.assert_called_once()
    
    def test_get_stats(self):
        """Test get_stats method."""
        router = AgentMessageRouter()
        handler = Mock()
        
        router.subscribe("agent-1", handler)
        router.subscribe("agent-2", handler)
        
        # Route some messages
        message1 = AgentMessage(
            message_type=AgentMessageType.HEARTBEAT,
            sender_id="agent-1",
            recipient_id="agent-2",
        )
        message2 = AgentMessage(
            message_type=AgentMessageType.TASK_RESULT,
            sender_id="agent-3",
            recipient_id="agent-1",
        )
        
        router.route(message1)
        router.route(message2)
        
        stats = router.get_stats()
        
        assert stats.total_messages_routed == 2
        assert stats.active_subscribers == 2
        assert "heartbeat" in stats.messages_by_type
        assert "task_result" in stats.messages_by_type
    
    def test_set_event_bus(self):
        """Test setting EventBus after creation."""
        router = AgentMessageRouter()
        mock_event_bus = Mock()
        mock_event_bus.subscribe = Mock()
        
        router.set_event_bus(mock_event_bus)
        
        assert router._event_bus == mock_event_bus
        mock_event_bus.subscribe.assert_called_once()
    
    def test_set_dlq(self):
        """Test setting DLQ after creation."""
        router = AgentMessageRouter()
        mock_dlq = Mock()
        
        router.set_dlq(mock_dlq)
        
        assert router._dlq == mock_dlq
    
    def test_get_subscribers(self):
        """Test getting list of subscribers."""
        router = AgentMessageRouter()
        handler = Mock()
        
        router.subscribe("agent-1", handler)
        router.subscribe("agent-2", handler)
        
        subscribers = router.get_subscribers()
        
        assert len(subscribers) == 2
        assert "agent-1" in subscribers
        assert "agent-2" in subscribers
    
    def test_clear_subscribers(self):
        """Test clearing all subscribers."""
        router = AgentMessageRouter()
        handler = Mock()
        
        router.subscribe("agent-1", handler)
        router.subscribe("agent-2", handler)
        
        router.clear_subscribers()
        
        assert not router.has_subscriber("agent-1")
        assert not router.has_subscriber("agent-2")
        stats = router.get_stats()
        assert stats.active_subscribers == 0


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestCreateMessageRouter:
    """Tests for create_message_router factory function."""
    
    def test_create_router_default(self):
        """Test creating router with defaults."""
        router = create_message_router()
        
        assert router is not None
        assert isinstance(router, AgentMessageRouter)
    
    def test_create_router_with_event_bus(self):
        """Test creating router with EventBus."""
        mock_event_bus = Mock()
        mock_event_bus.subscribe = Mock()
        
        router = create_message_router(event_bus=mock_event_bus)
        
        assert router._event_bus == mock_event_bus
    
    def test_create_router_with_dlq(self):
        """Test creating router with DLQ."""
        mock_dlq = Mock()
        
        router = create_message_router(dlq=mock_dlq)
        
        assert router._dlq == mock_dlq


# =============================================================================
# Convenience Message Creator Tests
# =============================================================================

class TestConvenienceMessageCreators:
    """Tests for convenience message creator functions."""
    
    def test_create_heartbeat_message(self):
        """Test create_heartbeat_message."""
        message = create_heartbeat_message(
            agent_id="agent-1",
            status="idle",
            metadata={"version": "1.0"},
        )
        
        assert message.message_type == AgentMessageType.HEARTBEAT
        assert message.sender_id == "agent-1"
        assert message.is_broadcast() is True
        assert message.payload["status"] == "idle"
        assert message.payload["metadata"] == {"version": "1.0"}
    
    def test_create_task_request_message(self):
        """Test create_task_request_message."""
        message = create_task_request_message(
            agent_id="agent-1",
            capabilities=["analysis", "validation"],
            priority=1,
        )
        
        assert message.message_type == AgentMessageType.TASK_REQUEST
        assert message.sender_id == "agent-1"
        assert message.payload["capabilities"] == ["analysis", "validation"]
        assert message.payload["priority"] == 1
    
    def test_create_task_result_message(self):
        """Test create_task_result_message."""
        message = create_task_result_message(
            agent_id="agent-1",
            task_id="task-123",
            success=True,
            result={"output": "done"},
            correlation_id="msg-456",
        )
        
        assert message.message_type == AgentMessageType.TASK_RESULT
        assert message.sender_id == "agent-1"
        assert message.payload["task_id"] == "task-123"
        assert message.payload["success"] is True
        assert message.payload["result"] == {"output": "done"}
        assert message.correlation_id == "msg-456"
    
    def test_create_task_result_message_error(self):
        """Test create_task_result_message with error."""
        message = create_task_result_message(
            agent_id="agent-1",
            task_id="task-123",
            success=False,
            error="Processing failed",
        )
        
        assert message.payload["success"] is False
        assert message.payload["error"] == "Processing failed"
    
    def test_create_context_share_message(self):
        """Test create_context_share_message."""
        message = create_context_share_message(
            agent_id="agent-1",
            context_type="analysis",
            context_data={"results": [1, 2, 3]},
            ttl_seconds=3600,
        )
        
        assert message.message_type == AgentMessageType.CONTEXT_SHARE
        assert message.sender_id == "agent-1"
        assert message.payload["context_type"] == "analysis"
        assert message.payload["context_data"] == {"results": [1, 2, 3]}
        assert message.payload["ttl_seconds"] == 3600
    
    def test_create_assistance_request_message(self):
        """Test create_assistance_request_message."""
        message = create_assistance_request_message(
            agent_id="agent-1",
            assistance_type="analysis",
            description="Need help with complex analysis",
            required_capabilities=["ml", "statistics"],
            urgency=1,
        )
        
        assert message.message_type == AgentMessageType.ASSISTANCE_REQUEST
        assert message.sender_id == "agent-1"
        assert message.payload["assistance_type"] == "analysis"
        assert message.payload["description"] == "Need help with complex analysis"
        assert message.payload["required_capabilities"] == ["ml", "statistics"]
        assert message.payload["urgency"] == 1
    
    def test_create_discovery_broadcast_message(self):
        """Test create_discovery_broadcast_message."""
        message = create_discovery_broadcast_message(
            agent_id="agent-1",
            discovery_type="new_api",
            discovered_info={"endpoint": "/api/v2"},
        )
        
        assert message.message_type == AgentMessageType.DISCOVERY_BROADCAST
        assert message.sender_id == "agent-1"
        assert message.is_broadcast() is True
        assert message.payload["discovery_type"] == "new_api"
        assert message.payload["discovered_info"] == {"endpoint": "/api/v2"}
    
    def test_create_status_update_message(self):
        """Test create_status_update_message."""
        message = create_status_update_message(
            agent_id="agent-1",
            old_status="idle",
            new_status="busy",
            reason="Processing task",
        )
        
        assert message.message_type == AgentMessageType.STATUS_UPDATE
        assert message.sender_id == "agent-1"
        assert message.is_broadcast() is True
        assert message.payload["old_status"] == "idle"
        assert message.payload["new_status"] == "busy"
        assert message.payload["reason"] == "Processing task"


# =============================================================================
# Thread Safety Tests
# =============================================================================

class TestThreadSafety:
    """Tests for thread safety."""
    
    def test_concurrent_subscribe(self):
        """Test concurrent subscription."""
        router = AgentMessageRouter()
        errors = []
        
        def subscribe_agent(i):
            try:
                handler = Mock()
                router.subscribe(f"agent-{i}", handler)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=subscribe_agent, args=(i,)) for i in range(100)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        subscribers = router.get_subscribers()
        assert len(subscribers) == 100
    
    def test_concurrent_route(self):
        """Test concurrent message routing."""
        router = AgentMessageRouter()
        received = []
        
        def handler(msg):
            received.append(msg.message_id)
        
        router.subscribe("agent-2", handler)
        
        def send_message(i):
            message = AgentMessage(
                message_id=f"msg-{i}",
                message_type=AgentMessageType.HEARTBEAT,
                sender_id="agent-1",
                recipient_id="agent-2",
            )
            router.route(message)
        
        threads = [threading.Thread(target=send_message, args=(i,)) for i in range(100)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(received) == 100
        stats = router.get_stats()
        assert stats.total_messages_routed == 100
    
    def test_concurrent_broadcast(self):
        """Test concurrent broadcasting."""
        router = AgentMessageRouter()
        received_1 = []
        received_2 = []
        
        def handler_1(msg):
            received_1.append(msg.message_id)
        
        def handler_2(msg):
            received_2.append(msg.message_id)
        
        router.subscribe("agent-1", handler_1)
        router.subscribe("agent-2", handler_2)
        
        def broadcast_message(i):
            message = AgentMessage(
                message_id=f"msg-{i}",
                message_type=AgentMessageType.DISCOVERY_BROADCAST,
                sender_id="agent-3",
            )
            router.broadcast(message)
        
        threads = [threading.Thread(target=broadcast_message, args=(i,)) for i in range(50)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(received_1) == 50
        assert len(received_2) == 50
        stats = router.get_stats()
        assert stats.total_broadcasts == 50


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for the agent protocol."""
    
    def test_full_communication_workflow(self):
        """Test a complete communication workflow."""
        router = AgentMessageRouter()
        
        # Set up orchestrator first
        orchestrator_handler = Mock()
        router.subscribe("orchestrator", orchestrator_handler)
        
        # Worker requests a task (broadcast to all agents including orchestrator)
        task_request = create_task_request_message(
            agent_id="worker-1",
            capabilities=["analysis"],
        )
        router.broadcast(task_request)
        
        # Orchestrator receives the task request
        orchestrator_handler.assert_called_once()
        
        # Now register worker after orchestrator received the request
        worker_handler = Mock()
        router.subscribe("worker-1", worker_handler)
        
        # Orchestrator assigns task to worker-1 (direct message)
        task_assignment = AgentMessage(
            message_type=AgentMessageType.TASK_RESULT,
            sender_id="orchestrator",
            recipient_id="worker-1",
            payload={"task_id": "task-123", "task": "analyze_data"},
        )
        router.route(task_assignment)
        
        worker_handler.assert_called_once()
        
        # Worker sends heartbeat
        heartbeat = create_heartbeat_message(
            agent_id="worker-1",
            status="busy",
        )
        router.broadcast(heartbeat)
        
        # Worker submits result to orchestrator
        result = create_task_result_message(
            agent_id="worker-1",
            task_id="task-123",
            success=True,
            result={"analysis": "complete"},
        )
        # Send directly to orchestrator
        result.recipient_id = "orchestrator"
        router.route(result)
        
        # Verify stats
        stats = router.get_stats()
        assert stats.total_messages_routed >= 3
        assert stats.total_broadcasts >= 2
    
    def test_message_correlation(self):
        """Test request-response correlation."""
        router = AgentMessageRouter()
        
        received_messages = []
        
        def handler(msg):
            received_messages.append(msg)
        
        router.subscribe("agent-2", handler)
        
        # Send a request
        request = AgentMessage(
            message_id="req-123",
            message_type=AgentMessageType.ASSISTANCE_REQUEST,
            sender_id="agent-1",
            recipient_id="agent-2",
            payload={"help": "needed"},
        )
        
        router.route(request)
        
        # Create and send response
        response = received_messages[0].create_response(
            response_type=AgentMessageType.TASK_RESULT,
            payload={"help": "provided"},
            sender_id="agent-2",
        )
        
        router.subscribe("agent-1", handler)
        router.route(response)
        
        # Verify correlation
        assert response.correlation_id == "req-123"
        assert response.recipient_id == "agent-1"
    
    def test_type_subscriber_receives_all_of_type(self):
        """Test that type subscribers receive all messages of that type."""
        router = AgentMessageRouter()
        
        all_heartbeats = []
        
        def heartbeat_handler(msg):
            all_heartbeats.append(msg)
        
        # Subscribe to all heartbeats
        router.subscribe_to_type(AgentMessageType.HEARTBEAT, heartbeat_handler)
        
        # Subscribe specific agents
        agent1_handler = Mock()
        agent2_handler = Mock()
        router.subscribe("agent-1", agent1_handler)
        router.subscribe("agent-2", agent2_handler)
        
        # Send heartbeats
        hb1 = create_heartbeat_message("agent-1", status="idle")
        hb2 = create_heartbeat_message("agent-2", status="busy")
        
        router.broadcast(hb1)
        router.broadcast(hb2)
        
        # Type subscriber should receive both
        assert len(all_heartbeats) == 2
        
        # Broadcasts are sent to all subscribers, so each handler receives both messages
        # agent1_handler receives both hb1 and hb2 (2 calls)
        # agent2_handler receives both hb1 and hb2 (2 calls)
        assert agent1_handler.call_count == 2
        assert agent2_handler.call_count == 2
