"""
Streaming Response Support for TITAN Protocol v4.0.0.

ITEM-PERF-01: Streaming LLM responses with event emission,
early termination support, and configurable callbacks.

Features:
- Stream LLM responses chunk by chunk
- Event emission via EventBus on each chunk
- Early termination when gate fails
- Configurable streaming behavior
- Max stream time enforcement

Author: TITAN FUSE Team
Version: 4.0.0
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from src.events.event_bus import EventBus, Event


# Check for z-ai-web-dev-sdk availability
try:
    import importlib.util
    ZAI_AVAILABLE = importlib.util.find_spec("z_ai_web_dev_sdk") is not None
except ImportError:
    ZAI_AVAILABLE = False


class StreamState(Enum):
    """State of a streaming operation."""
    IDLE = "idle"
    STREAMING = "streaming"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class StreamConfig:
    """
    Configuration for streaming behavior.
    
    Attributes:
        enabled: Whether streaming is enabled
        chunk_callback: Whether to invoke callback on each chunk
        max_stream_time_seconds: Maximum time for streaming (default 300)
        chunk_delay_ms: Artificial delay between chunks for testing
        emit_events: Whether to emit events on each chunk
    """
    enabled: bool = True
    chunk_callback: bool = True
    max_stream_time_seconds: int = 300
    chunk_delay_ms: int = 0
    emit_events: bool = True
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'StreamConfig':
        """Create from dictionary."""
        return cls(
            enabled=data.get("enabled", True),
            chunk_callback=data.get("chunk_callback", True),
            max_stream_time_seconds=data.get("max_stream_time_seconds", 300),
            chunk_delay_ms=data.get("chunk_delay_ms", 0),
            emit_events=data.get("emit_events", True)
        )


@dataclass
class StreamMetrics:
    """Metrics for a streaming operation."""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    total_chunks: int = 0
    total_tokens: int = 0
    total_bytes: int = 0
    cancelled: bool = False
    cancelled_reason: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class StreamChunk:
    """Represents a single chunk in the stream."""
    chunk_id: str
    content: str
    accumulated: str
    timestamp: str
    token_count: int = 0
    is_final: bool = False
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return asdict(self)


class StreamingHandler:
    """
    Handler for streaming LLM responses.
    
    ITEM-PERF-01: Streaming Response Support.
    
    Provides:
    - Stream LLM responses with chunk-by-chunk delivery
    - Event emission via EventBus on each chunk
    - Early termination when gate fails
    - Configurable streaming behavior
    
    Usage:
        from src.llm.streaming import StreamingHandler, StreamConfig
        from src.events.event_bus import EventBus
        
        bus = EventBus()
        config = StreamConfig(enabled=True, chunk_callback=True)
        handler = StreamingHandler(config=config, event_bus=bus)
        
        # Stream with callback
        def on_chunk(chunk: str):
            print(f"Received: {chunk}")
        
        handler.stream("Tell me a story", on_chunk)
        
        # Check accumulated text
        print(handler.get_accumulated())
        
        # Cancel if needed
        handler.cancel()
    """
    
    def __init__(
        self,
        config: Optional[StreamConfig] = None,
        event_bus: Optional['EventBus'] = None,
        llm_client: Optional[Any] = None,
        model: str = "default"
    ):
        """
        Initialize the streaming handler.
        
        Args:
            config: Streaming configuration
            event_bus: EventBus for emitting events
            llm_client: Optional LLM client for actual queries
            model: Model identifier for streaming
        """
        self.config = config or StreamConfig()
        self.event_bus = event_bus
        self.llm_client = llm_client
        self.model = model
        self._logger = logging.getLogger(__name__)
        
        # State management
        self._state = StreamState.IDLE
        self._accumulated_text = ""
        self._chunks: List[StreamChunk] = []
        self._metrics = StreamMetrics()
        self._lock = threading.RLock()
        self._cancel_flag = threading.Event()
        self._stream_thread: Optional[threading.Thread] = None
        self._gate_fail_handler: Optional[Callable] = None
        
        # Register gate fail handler if event bus available
        if self.event_bus:
            self._register_gate_fail_handler()
    
    def _register_gate_fail_handler(self) -> None:
        """Register handler for GATE_FAIL events to cancel streaming."""
        def on_gate_fail(event: 'Event') -> None:
            """Handle GATE_FAIL event by canceling streaming."""
            if self.active():
                self._logger.warning(
                    f"GATE_FAIL received, canceling streaming: {event.data}"
                )
                self.cancel(reason="gate_fail")
        
        if self.event_bus:
            self.event_bus.subscribe("GATE_FAIL", on_gate_fail, priority=1)
            self._gate_fail_handler = on_gate_fail
    
    def stream(
        self,
        prompt: str,
        callback: Callable[[str], None],
        system_prompt: Optional[str] = None,
        max_tokens: int = 2048
    ) -> None:
        """
        Stream LLM response, invoking callback for each chunk.
        
        Implements streaming with:
        - Event emission on each chunk (LLM_CHUNK)
        - Early termination on cancel or gate fail
        - Max stream time enforcement
        
        Args:
            prompt: The prompt to send to the LLM
            callback: Function to call for each chunk
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens in response
            
        Raises:
            RuntimeError: If streaming is disabled or already active
        """
        if not self.config.enabled:
            raise RuntimeError("Streaming is disabled in configuration")
        
        with self._lock:
            if self._state == StreamState.STREAMING:
                raise RuntimeError("Streaming already in progress")
            
            # Reset state for new stream
            self._accumulated_text = ""
            self._chunks = []
            self._metrics = StreamMetrics()
            self._metrics.start_time = datetime.utcnow().isoformat() + "Z"
            self._cancel_flag.clear()
            self._state = StreamState.STREAMING
        
        try:
            self._execute_stream(
                prompt=prompt,
                callback=callback,
                system_prompt=system_prompt,
                max_tokens=max_tokens
            )
        except Exception as e:
            with self._lock:
                self._state = StreamState.FAILED
            self._logger.error(f"Streaming failed: {e}")
            raise
    
    def _execute_stream(
        self,
        prompt: str,
        callback: Callable[[str], None],
        system_prompt: Optional[str],
        max_tokens: int
    ) -> None:
        """Execute the streaming operation."""
        start_time = time.time()
        timeout_seconds = self.config.max_stream_time_seconds
        chunk_id = 0
        
        try:
            # Try to use z-ai-web-dev-sdk for streaming
            for chunk_content in self._stream_from_sdk(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens
            ):
                # Check for cancellation
                if self._cancel_flag.is_set():
                    with self._lock:
                        self._state = StreamState.CANCELLED
                        self._metrics.cancelled = True
                    self._logger.info("Streaming cancelled by request")
                    return
                
                # Check for timeout
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    with self._lock:
                        self._state = StreamState.TIMEOUT
                    self._logger.warning(
                        f"Streaming timed out after {elapsed:.1f}s"
                    )
                    return
                
                # Check for gate failure (if event bus is monitoring)
                if self._check_gate_failure():
                    with self._lock:
                        self._state = StreamState.CANCELLED
                        self._metrics.cancelled = True
                        self._metrics.cancelled_reason = "gate_fail"
                    self._logger.warning("Streaming cancelled due to gate failure")
                    return
                
                # Process the chunk
                chunk_id += 1
                self._process_chunk(chunk_id, chunk_content, callback)
                
                # Optional delay for testing
                if self.config.chunk_delay_ms > 0:
                    time.sleep(self.config.chunk_delay_ms / 1000.0)
            
            # Streaming completed successfully
            with self._lock:
                self._state = StreamState.COMPLETED
                self._metrics.end_time = datetime.utcnow().isoformat() + "Z"
                self._metrics.total_chunks = chunk_id
            
            self._logger.info(
                f"Streaming completed: {chunk_id} chunks, "
                f"{len(self._accumulated_text)} chars"
            )
            
        except Exception as e:
            with self._lock:
                self._state = StreamState.FAILED
                self._metrics.end_time = datetime.utcnow().isoformat() + "Z"
            raise
    
    def _stream_from_sdk(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int
    ):
        """
        Generator that yields chunks from the LLM SDK.
        
        Falls back to simulated streaming if SDK not available.
        """
        if ZAI_AVAILABLE:
            yield from self._stream_zai_sdk(prompt, system_prompt, max_tokens)
        else:
            yield from self._simulate_stream(prompt, system_prompt)
    
    def _stream_zai_sdk(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int
    ):
        """Stream from z-ai-web-dev-sdk via Node.js subprocess."""
        system = system_prompt or (
            "You are a helpful assistant. Respond concisely and accurately."
        )
        
        script = f'''
        const ZAI = require('z-ai-web-dev-sdk').default;
        
        async function main() {{
            try {{
                const zai = await ZAI.create();
                
                const stream = await zai.chat.completions.create({{
                    messages: [
                        {{ role: 'system', content: {json.dumps(system)} }},
                        {{ role: 'user', content: {json.dumps(prompt)} }}
                    ],
                    max_tokens: {max_tokens},
                    stream: true
                }});
                
                for await (const chunk of stream) {{
                    const content = chunk.choices[0]?.delta?.content || '';
                    if (content) {{
                        console.log(JSON.stringify({{ chunk: content }}));
                    }}
                }}
                
                console.log(JSON.stringify({{ done: true }}));
            }} catch (error) {{
                console.error(JSON.stringify({{ error: error.message }}));
                process.exit(1);
            }}
        }}
        
        main();
        '''
        
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.js', delete=False
            ) as f:
                f.write(script)
                script_path = f.name
            
            process = subprocess.Popen(
                ['node', script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            try:
                while True:
                    line = process.stdout.readline()
                    if not line:
                        break
                    
                    try:
                        data = json.loads(line.strip())
                        if 'chunk' in data:
                            yield data['chunk']
                        elif 'done' in data:
                            break
                        elif 'error' in data:
                            raise RuntimeError(f"SDK error: {data['error']}")
                    except json.JSONDecodeError:
                        continue
                        
            finally:
                process.terminate()
                os.unlink(script_path)
                
        except FileNotFoundError:
            # Node.js not available, fall back to simulation
            yield from self._simulate_stream(prompt, system_prompt)
    
    def _simulate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str]
    ):
        """
        Simulate streaming for testing/development.
        
        Yields word-sized chunks from a simulated response.
        """
        # Generate a simulated response
        response = self._generate_simulated_response(prompt)
        
        # Yield word by word
        words = response.split()
        for i, word in enumerate(words):
            # Add space before word (except first)
            if i > 0:
                yield " "
            yield word
    
    def _generate_simulated_response(self, prompt: str) -> str:
        """Generate a simulated LLM response for testing."""
        prompt_lower = prompt.lower()
        
        if "story" in prompt_lower:
            return (
                "Once upon a time, in a land far away, there lived a brave "
                "adventurer who sought the legendary Crystal of Eternity. "
                "Through forests dark and mountains tall, the journey led "
                "to discoveries untold. In the end, wisdom was the true treasure."
            )
        elif "code" in prompt_lower or "function" in prompt_lower:
            return (
                "Here's a simple function for your needs:\n\n"
                "def example():\n"
                "    '''An example function.'''\n"
                "    result = process_data()\n"
                "    return result\n\n"
                "This function demonstrates basic structure and can be "
                "extended as needed."
            )
        elif "explain" in prompt_lower or "what" in prompt_lower:
            return (
                "Let me explain this concept clearly. The key points are:\n"
                "1. First, understand the fundamentals.\n"
                "2. Then, apply them systematically.\n"
                "3. Finally, verify your results.\n\n"
                "This approach ensures solid understanding and reliable outcomes."
            )
        else:
            return (
                f"I understand you're asking about: '{prompt[:50]}...'\n\n"
                "This is a simulated streaming response for testing purposes. "
                "In production, this would be replaced with actual LLM output "
                "streaming from the configured model endpoint."
            )
    
    def _process_chunk(
        self,
        chunk_id: int,
        content: str,
        callback: Callable[[str], None]
    ) -> None:
        """Process a single chunk from the stream."""
        with self._lock:
            self._accumulated_text += content
            self._metrics.total_bytes += len(content)
            
            # Estimate tokens (rough: ~4 chars per token)
            estimated_tokens = len(content) // 4
            self._metrics.total_tokens += estimated_tokens
            
            # Create chunk record
            chunk = StreamChunk(
                chunk_id=f"chunk-{chunk_id:04d}",
                content=content,
                accumulated=self._accumulated_text,
                timestamp=datetime.utcnow().isoformat() + "Z",
                token_count=estimated_tokens
            )
            self._chunks.append(chunk)
        
        # Invoke callback if enabled
        if self.config.chunk_callback:
            try:
                callback(content)
            except Exception as e:
                self._logger.warning(f"Callback error: {e}")
        
        # Emit event if enabled
        if self.config.emit_events and self.event_bus:
            self._emit_chunk_event(chunk)
    
    def _emit_chunk_event(self, chunk: StreamChunk) -> None:
        """Emit LLM_CHUNK event for the given chunk."""
        from src.events.event_bus import Event, EventSeverity, EventTypes
        
        event = Event(
            event_type="LLM_CHUNK",
            data={
                "chunk_id": chunk.chunk_id,
                "content": chunk.content,
                "accumulated": chunk.accumulated,
                "token_count": chunk.token_count,
                "model": self.model,
                "timestamp": chunk.timestamp
            },
            severity=EventSeverity.INFO,
            source="StreamingHandler"
        )
        
        self.event_bus.emit(event)
    
    def _check_gate_failure(self) -> bool:
        """Check if a gate failure has occurred."""
        # If we have an event bus, check recent events for GATE_FAIL
        if self.event_bus:
            history = self.event_bus.get_history(limit=10)
            for event in reversed(history):
                if event.event_type == "GATE_FAIL":
                    return True
        return False
    
    def cancel(self, reason: str = "user_request") -> None:
        """
        Cancel the current streaming operation.
        
        Args:
            reason: Reason for cancellation
        """
        with self._lock:
            if self._state != StreamState.STREAMING:
                return
            
            self._cancel_flag.set()
            self._metrics.cancelled = True
            self._metrics.cancelled_reason = reason
            self._logger.info(f"Streaming cancellation requested: {reason}")
    
    def get_accumulated(self) -> str:
        """
        Get the accumulated text from streaming.
        
        Returns:
            All text received so far in the stream
        """
        with self._lock:
            return self._accumulated_text
    
    def active(self) -> bool:
        """
        Check if streaming is currently active.
        
        Returns:
            True if streaming is in progress
        """
        with self._lock:
            return self._state == StreamState.STREAMING
    
    def get_state(self) -> StreamState:
        """Get the current streaming state."""
        with self._lock:
            return self._state
    
    def get_metrics(self) -> StreamMetrics:
        """Get streaming metrics."""
        with self._lock:
            return self._metrics
    
    def get_chunks(self) -> List[StreamChunk]:
        """Get all received chunks."""
        with self._lock:
            return list(self._chunks)
    
    def reset(self) -> None:
        """Reset the handler for a new streaming operation."""
        with self._lock:
            self._state = StreamState.IDLE
            self._accumulated_text = ""
            self._chunks = []
            self._metrics = StreamMetrics()
            self._cancel_flag.clear()
    
    def set_event_bus(self, event_bus: 'EventBus') -> None:
        """
        Set or update the event bus.
        
        Args:
            event_bus: EventBus instance
        """
        # Unregister old handler if exists
        if self.event_bus and self._gate_fail_handler:
            self.event_bus.unsubscribe("GATE_FAIL", self._gate_fail_handler)
        
        self.event_bus = event_bus
        self._register_gate_fail_handler()
    
    def get_config(self) -> Dict:
        """Get current configuration."""
        return {
            "config": self.config.to_dict(),
            "model": self.model,
            "state": self._state.value,
            "metrics": self._metrics.to_dict()
        }


def create_streaming_handler(
    config: Optional[Dict] = None,
    event_bus: Optional['EventBus'] = None,
    model: str = "default"
) -> StreamingHandler:
    """
    Factory function to create a StreamingHandler.
    
    Args:
        config: Configuration dictionary
        event_bus: EventBus for event emission
        model: Model identifier
        
    Returns:
        Configured StreamingHandler instance
    """
    stream_config = StreamConfig.from_dict(config) if config else StreamConfig()
    return StreamingHandler(
        config=stream_config,
        event_bus=event_bus,
        model=model
    )
