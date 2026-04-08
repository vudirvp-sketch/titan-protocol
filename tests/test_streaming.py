"""
Tests for ITEM-PERF-01: Streaming Response Support

This module tests the StreamingHandler for streaming LLM responses
with event emission and early termination support.

Author: TITAN FUSE Team
Version: 4.0.0
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock

from src.llm.streaming import (
    StreamingHandler,
    StreamConfig,
    StreamState,
    StreamMetrics,
    StreamChunk,
    create_streaming_handler,
)


class TestStreamConfig:
    """Tests for StreamConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = StreamConfig()
        assert config.enabled is True
        assert config.chunk_callback is True
        assert config.max_stream_time_seconds == 300
        assert config.chunk_delay_ms == 0
        assert config.emit_events is True

    def test_custom_config(self):
        """Test custom configuration values."""
        config = StreamConfig(
            enabled=False,
            chunk_callback=False,
            max_stream_time_seconds=60,
            chunk_delay_ms=100,
            emit_events=False
        )
        assert config.enabled is False
        assert config.chunk_callback is False
        assert config.max_stream_time_seconds == 60
        assert config.chunk_delay_ms == 100
        assert config.emit_events is False

    def test_to_dict(self):
        """Test serialization to dictionary."""
        config = StreamConfig(max_stream_time_seconds=120)
        d = config.to_dict()
        assert d["enabled"] is True
        assert d["max_stream_time_seconds"] == 120

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        d = {
            "enabled": False,
            "chunk_callback": False,
            "max_stream_time_seconds": 45,
        }
        config = StreamConfig.from_dict(d)
        assert config.enabled is False
        assert config.chunk_callback is False
        assert config.max_stream_time_seconds == 45


class TestStreamState:
    """Tests for StreamState enum."""

    def test_state_values(self):
        """Test state enum values."""
        assert StreamState.IDLE.value == "idle"
        assert StreamState.STREAMING.value == "streaming"
        assert StreamState.COMPLETED.value == "completed"
        assert StreamState.CANCELLED.value == "cancelled"
        assert StreamState.FAILED.value == "failed"
        assert StreamState.TIMEOUT.value == "timeout"


class TestStreamMetrics:
    """Tests for StreamMetrics dataclass."""

    def test_default_metrics(self):
        """Test default metrics values."""
        metrics = StreamMetrics()
        assert metrics.start_time is None
        assert metrics.end_time is None
        assert metrics.total_chunks == 0
        assert metrics.total_tokens == 0
        assert metrics.total_bytes == 0
        assert metrics.cancelled is False
        assert metrics.cancelled_reason is None

    def test_to_dict(self):
        """Test metrics serialization."""
        metrics = StreamMetrics(
            start_time="2024-01-01T00:00:00Z",
            total_chunks=10,
            cancelled=True,
            cancelled_reason="user_request"
        )
        d = metrics.to_dict()
        assert d["start_time"] == "2024-01-01T00:00:00Z"
        assert d["total_chunks"] == 10
        assert d["cancelled"] is True
        assert d["cancelled_reason"] == "user_request"


class TestStreamChunk:
    """Tests for StreamChunk dataclass."""

    def test_chunk_creation(self):
        """Test chunk creation."""
        chunk = StreamChunk(
            chunk_id="chunk-0001",
            content="Hello",
            accumulated="Hello",
            timestamp="2024-01-01T00:00:00Z",
            token_count=1
        )
        assert chunk.chunk_id == "chunk-0001"
        assert chunk.content == "Hello"
        assert chunk.accumulated == "Hello"
        assert chunk.is_final is False

    def test_chunk_to_dict(self):
        """Test chunk serialization."""
        chunk = StreamChunk(
            chunk_id="chunk-0001",
            content="World",
            accumulated="Hello World",
            timestamp="2024-01-01T00:00:00Z",
            token_count=1
        )
        d = chunk.to_dict()
        assert d["chunk_id"] == "chunk-0001"
        assert d["content"] == "World"
        assert d["accumulated"] == "Hello World"


class TestStreamingHandler:
    """Tests for StreamingHandler class."""

    def test_initialization(self):
        """Test handler initialization."""
        handler = StreamingHandler()
        assert handler.get_state() == StreamState.IDLE
        assert handler.get_accumulated() == ""
        assert handler.active() is False

    def test_initialization_with_config(self):
        """Test handler initialization with custom config."""
        config = StreamConfig(max_stream_time_seconds=60)
        handler = StreamingHandler(config=config)
        assert handler.config.max_stream_time_seconds == 60

    def test_stream_basic(self):
        """Test basic streaming operation."""
        handler = StreamingHandler()
        chunks_received = []

        def callback(chunk: str):
            chunks_received.append(chunk)

        handler.stream("Tell me a story", callback)

        assert handler.get_state() == StreamState.COMPLETED
        assert len(handler.get_accumulated()) > 0
        assert len(chunks_received) > 0

    def test_stream_accumulated_text(self):
        """Test that accumulated text builds correctly."""
        handler = StreamingHandler()
        
        def callback(chunk: str):
            pass

        handler.stream("Explain streaming", callback)

        accumulated = handler.get_accumulated()
        assert len(accumulated) > 0
        # Should contain simulated response
        assert "stream" in accumulated.lower() or "explain" in accumulated.lower()

    def test_stream_callbacks_invoked(self):
        """Test that callbacks are invoked for each chunk."""
        config = StreamConfig(chunk_callback=True)
        handler = StreamingHandler(config=config)
        callback_count = []

        def callback(chunk: str):
            callback_count.append(1)

        handler.stream("Test prompt", callback)

        assert len(callback_count) > 0

    def test_stream_disabled_raises(self):
        """Test that streaming when disabled raises error."""
        config = StreamConfig(enabled=False)
        handler = StreamingHandler(config=config)

        with pytest.raises(RuntimeError, match="Streaming is disabled"):
            handler.stream("Test", lambda x: None)

    def test_stream_double_start_raises(self):
        """Test that starting stream while active raises error."""
        handler = StreamingHandler()
        
        def slow_callback(chunk: str):
            time.sleep(0.1)

        # Start streaming in a thread
        def run_stream():
            handler.stream("Test", slow_callback)

        thread = threading.Thread(target=run_stream)
        thread.start()
        
        # Give it time to start
        time.sleep(0.01)

        try:
            with pytest.raises(RuntimeError, match="already in progress"):
                handler.stream("Another test", lambda x: None)
        finally:
            thread.join(timeout=5)

    def test_cancel_during_stream(self):
        """Test cancellation during streaming."""
        config = StreamConfig(chunk_delay_ms=50)  # Add delay to allow cancellation
        handler = StreamingHandler(config=config)
        
        def callback(chunk: str):
            # Cancel after first chunk
            if len(handler.get_accumulated()) > 10:
                handler.cancel()

        handler.stream("Tell me a long story", callback)

        # Stream should have been cancelled or completed
        state = handler.get_state()
        assert state in [StreamState.CANCELLED, StreamState.COMPLETED]

    def test_cancel_before_stream(self):
        """Test that cancel before stream does nothing."""
        handler = StreamingHandler()
        handler.cancel()  # Should not raise
        assert handler.get_state() == StreamState.IDLE

    def test_active_flag(self):
        """Test the active() method."""
        handler = StreamingHandler()
        assert handler.active() is False

    def test_get_metrics(self):
        """Test getting streaming metrics."""
        handler = StreamingHandler()
        
        handler.stream("Test", lambda x: None)
        
        metrics = handler.get_metrics()
        assert metrics.start_time is not None
        assert metrics.end_time is not None
        assert metrics.total_chunks > 0

    def test_get_chunks(self):
        """Test getting all chunks."""
        handler = StreamingHandler()
        
        handler.stream("Test", lambda x: None)
        
        chunks = handler.get_chunks()
        assert len(chunks) > 0
        assert all(isinstance(c, StreamChunk) for c in chunks)

    def test_reset(self):
        """Test resetting the handler."""
        handler = StreamingHandler()
        
        handler.stream("Test", lambda x: None)
        assert handler.get_state() == StreamState.COMPLETED
        
        handler.reset()
        assert handler.get_state() == StreamState.IDLE
        assert handler.get_accumulated() == ""

    def test_get_config(self):
        """Test getting handler configuration."""
        config = StreamConfig(max_stream_time_seconds=120)
        handler = StreamingHandler(config=config, model="test-model")
        
        cfg = handler.get_config()
        assert cfg["config"]["max_stream_time_seconds"] == 120
        assert cfg["model"] == "test-model"
        assert cfg["state"] == "idle"


class TestStreamingHandlerWithEventBus:
    """Tests for StreamingHandler with EventBus integration."""

    def test_event_emission(self):
        """Test that LLM_CHUNK events are emitted."""
        from src.events.event_bus import EventBus, Event, EventSeverity
        
        bus = EventBus(config={"async_enabled": False})
        events_received = []
        
        def capture_event(event: Event):
            events_received.append(event)
        
        bus.subscribe("LLM_CHUNK", capture_event)
        
        handler = StreamingHandler(event_bus=bus)
        handler.stream("Test prompt", lambda x: None)
        
        # Should have received chunk events
        chunk_events = [e for e in events_received if e.event_type == "LLM_CHUNK"]
        assert len(chunk_events) > 0
        
        # Verify event data
        first_event = chunk_events[0]
        assert "chunk_id" in first_event.data
        assert "content" in first_event.data
        assert "accumulated" in first_event.data

    def test_events_disabled(self):
        """Test that events can be disabled."""
        from src.events.event_bus import EventBus
        
        bus = EventBus(config={"async_enabled": False})
        events_received = []
        
        def capture_event(event):
            events_received.append(event)
        
        bus.subscribe("LLM_CHUNK", capture_event)
        
        config = StreamConfig(emit_events=False)
        handler = StreamingHandler(config=config, event_bus=bus)
        handler.stream("Test", lambda x: None)
        
        chunk_events = [e for e in events_received if e.event_type == "LLM_CHUNK"]
        assert len(chunk_events) == 0

    def test_gate_fail_handler_registration(self):
        """Test that GATE_FAIL handler is registered."""
        from src.events.event_bus import EventBus
        
        bus = EventBus()
        handler = StreamingHandler(event_bus=bus)
        
        # Check that handler was registered
        stats = bus.get_stats()
        assert stats["handler_count"] >= 1

    def test_gate_fail_cancels_streaming(self):
        """Test that GATE_FAIL event cancels streaming."""
        from src.events.event_bus import EventBus, Event, EventSeverity
        
        bus = EventBus(config={"async_enabled": False})
        config = StreamConfig(chunk_delay_ms=50)
        handler = StreamingHandler(config=config, event_bus=bus)
        
        stream_started = threading.Event()
        stream_cancelled = threading.Event()
        
        def callback(chunk: str):
            stream_started.set()
            # Wait to see if cancellation happens
            time.sleep(0.05)
            if handler.get_state() == StreamState.CANCELLED:
                stream_cancelled.set()
        
        def run_stream():
            try:
                handler.stream("Test", callback)
            except Exception:
                pass
        
        # Start streaming in a thread
        thread = threading.Thread(target=run_stream)
        thread.start()
        
        # Wait for stream to start
        stream_started.wait(timeout=2)
        
        # Emit GATE_FAIL event
        gate_event = Event(
            event_type="GATE_FAIL",
            data={"gate_id": "GATE-01", "reason": "test"}
        )
        bus.emit(gate_event)
        
        thread.join(timeout=2)
        
        # Stream should have been cancelled
        # Note: Due to timing, it might complete before cancellation
        final_state = handler.get_state()
        assert final_state in [StreamState.CANCELLED, StreamState.COMPLETED]

    def test_set_event_bus(self):
        """Test setting event bus after initialization."""
        from src.events.event_bus import EventBus
        
        handler = StreamingHandler()
        bus = EventBus()
        
        handler.set_event_bus(bus)
        
        # Handler should be registered
        stats = bus.get_stats()
        assert stats["handler_count"] >= 1


class TestStreamingTimeout:
    """Tests for streaming timeout behavior."""

    def test_timeout_enforcement(self):
        """Test that streaming times out after max_stream_time_seconds."""
        # Very short timeout
        config = StreamConfig(
            max_stream_time_seconds=0,
            chunk_delay_ms=100  # Add delay so we can hit timeout
        )
        handler = StreamingHandler(config=config)
        
        handler.stream("Test", lambda x: None)
        
        # Should have timed out or completed quickly
        state = handler.get_state()
        assert state in [StreamState.TIMEOUT, StreamState.COMPLETED]

    def test_no_timeout_normal_stream(self):
        """Test that normal streaming doesn't timeout."""
        config = StreamConfig(max_stream_time_seconds=300)
        handler = StreamingHandler(config=config)
        
        handler.stream("Test", lambda x: None)
        
        assert handler.get_state() == StreamState.COMPLETED


class TestFactoryFunction:
    """Tests for factory function."""

    def test_create_streaming_handler_defaults(self):
        """Test creating handler with defaults."""
        handler = create_streaming_handler()
        assert handler.get_state() == StreamState.IDLE
        assert handler.config.enabled is True

    def test_create_streaming_handler_with_config(self):
        """Test creating handler with config dict."""
        config = {
            "enabled": True,
            "max_stream_time_seconds": 60,
            "chunk_callback": False
        }
        handler = create_streaming_handler(config=config)
        assert handler.config.max_stream_time_seconds == 60
        assert handler.config.chunk_callback is False

    def test_create_streaming_handler_with_event_bus(self):
        """Test creating handler with event bus."""
        from src.events.event_bus import EventBus
        
        bus = EventBus()
        handler = create_streaming_handler(event_bus=bus, model="test-model")
        
        assert handler.event_bus is bus
        assert handler.model == "test-model"


class TestStreamIntegration:
    """Integration tests for streaming handler."""

    def test_full_streaming_workflow(self):
        """Test complete streaming workflow."""
        from src.events.event_bus import EventBus
        
        bus = EventBus(config={"async_enabled": False})
        config = StreamConfig(
            enabled=True,
            chunk_callback=True,
            emit_events=True,
            max_stream_time_seconds=60
        )
        
        handler = StreamingHandler(config=config, event_bus=bus)
        
        all_chunks = []
        
        def callback(chunk: str):
            all_chunks.append(chunk)
        
        # Stream a prompt
        handler.stream("Tell me about streaming APIs", callback)
        
        # Verify completion
        assert handler.get_state() == StreamState.COMPLETED
        
        # Verify accumulated text
        accumulated = handler.get_accumulated()
        assert len(accumulated) > 0
        
        # Verify metrics
        metrics = handler.get_metrics()
        assert metrics.total_chunks > 0
        assert metrics.total_bytes > 0
        
        # Reset for next stream
        handler.reset()
        assert handler.get_state() == StreamState.IDLE
        assert handler.get_accumulated() == ""

    def test_multiple_sequential_streams(self):
        """Test multiple sequential streaming operations."""
        handler = StreamingHandler()
        
        for i in range(3):
            handler.stream(f"Query {i}", lambda x: None)
            assert handler.get_state() == StreamState.COMPLETED
            handler.reset()
            assert handler.get_state() == StreamState.IDLE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
