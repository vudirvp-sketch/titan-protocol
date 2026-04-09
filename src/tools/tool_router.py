"""
TITAN FUSE Protocol - Tool Router

Unified routing for MCP, stdio, WebSocket, and API tool calls.
Normalizes requests and responses across different transport types.

TASK-001: Tool Orchestration & Capability Registry
"""

import json
import subprocess
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, Union, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import hashlib
import time


class TransportType(Enum):
    """Supported transport types for tool calls."""
    MCP = "mcp"          # Model Context Protocol
    STDIO = "stdio"      # Standard input/output
    WEBSOCKET = "ws"     # WebSocket
    API = "api"          # HTTP API
    INTERNAL = "internal"  # Internal function call


@dataclass
class ToolCall:
    """
    Represents a tool call request.

    Attributes:
        tool_name: Name of the tool to call
        parameters: Input parameters
        transport: Transport type to use
        timeout: Timeout in seconds
        metadata: Additional metadata
        call_id: Unique call identifier
        timestamp: When the call was made
    """
    tool_name: str
    parameters: Dict[str, Any]
    transport: TransportType = TransportType.STDIO
    timeout: int = 30
    metadata: Dict[str, Any] = field(default_factory=dict)
    call_id: str = field(default_factory=lambda: hashlib.md5(
        f"{time.time()}".encode(), usedforsecurity=False
    ).hexdigest()[:12])
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "transport": self.transport.value,
            "timeout": self.timeout,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass
class ToolResult:
    """
    Represents a tool call result.

    Attributes:
        call_id: ID of the corresponding call
        success: Whether the call succeeded
        output: Output data (if successful)
        error: Error message (if failed)
        duration_ms: Duration in milliseconds
        metadata: Additional metadata
        timestamp: When the result was produced
    """
    call_id: str
    success: bool
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "call_id": self.call_id,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


class TransportHandler:
    """Base class for transport handlers."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    async def call(self, call: ToolCall) -> ToolResult:
        """Execute a tool call."""
        raise NotImplementedError


class StdioHandler(TransportHandler):
    """Handler for stdio-based tool calls."""

    async def call(self, call: ToolCall) -> ToolResult:
        """Execute a stdio tool call."""
        start_time = time.time()

        try:
            # Get command from tool configuration
            command = self.config.get("command", call.tool_name)
            args = self.config.get("args", [])

            # Prepare input
            input_data = json.dumps(call.parameters)

            # Execute subprocess
            proc = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input_data.encode()),
                timeout=call.timeout
            )

            duration_ms = int((time.time() - start_time) * 1000)

            if proc.returncode != 0:
                return ToolResult(
                    call_id=call.call_id,
                    success=False,
                    error=stderr.decode() or f"Process exited with code {proc.returncode}",
                    duration_ms=duration_ms
                )

            output = json.loads(stdout.decode())
            return ToolResult(
                call_id=call.call_id,
                success=True,
                output=output,
                duration_ms=duration_ms
            )

        except asyncio.TimeoutError:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"Timeout after {call.timeout}s",
                duration_ms=call.timeout * 1000
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=str(e),
                duration_ms=duration_ms
            )


class InternalHandler(TransportHandler):
    """Handler for internal function calls."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._handlers: Dict[str, Callable] = {}

    def register_handler(self, tool_name: str, handler: Callable):
        """Register a handler for a tool."""
        self._handlers[tool_name] = handler

    async def call(self, call: ToolCall) -> ToolResult:
        """Execute an internal tool call."""
        start_time = time.time()

        handler = self._handlers.get(call.tool_name)
        if not handler:
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"No handler registered for: {call.tool_name}"
            )

        try:
            # Call handler (sync or async)
            if asyncio.iscoroutinefunction(handler):
                result = await handler(call.parameters)
            else:
                result = handler(call.parameters)

            duration_ms = int((time.time() - start_time) * 1000)

            return ToolResult(
                call_id=call.call_id,
                success=True,
                output=result if isinstance(result, dict) else {"result": result},
                duration_ms=duration_ms
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=str(e),
                duration_ms=duration_ms
            )


class ApiHandler(TransportHandler):
    """Handler for HTTP API tool calls."""

    async def call(self, call: ToolCall) -> ToolResult:
        """Execute an API tool call."""
        start_time = time.time()

        try:
            # This would use aiohttp or similar in production
            # Simplified version for now
            base_url = self.config.get("base_url", "")
            endpoint = self.config.get("endpoint", call.tool_name)

            # Placeholder - in production use aiohttp
            duration_ms = int((time.time() - start_time) * 1000)

            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="API transport not yet implemented - use aiohttp",
                duration_ms=duration_ms
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=str(e),
                duration_ms=duration_ms
            )


class WebSocketHandler(TransportHandler):
    """Handler for WebSocket tool calls."""

    async def call(self, call: ToolCall) -> ToolResult:
        """Execute a WebSocket tool call."""
        start_time = time.time()

        try:
            # Placeholder - in production use websockets library
            duration_ms = int((time.time() - start_time) * 1000)

            return ToolResult(
                call_id=call.call_id,
                success=False,
                error="WebSocket transport not yet implemented",
                duration_ms=duration_ms
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=str(e),
                duration_ms=duration_ms
            )


class ToolRouter:
    """
    Unified router for tool calls across different transports.

    Features:
    - Transport-agnostic tool calls
    - Automatic routing based on tool configuration
    - Request/response normalization
    - Timeout handling
    - Retry logic
    - Metrics collection

    Usage:
        router = ToolRouter()

        # Register transport handlers
        router.register_handler(TransportType.STDIO, StdioHandler())
        router.register_handler(TransportType.INTERNAL, InternalHandler())

        # Make a tool call
        call = ToolCall(
            tool_name="read_file",
            parameters={"path": "/tmp/test.txt"},
            transport=TransportType.INTERNAL
        )
        result = await router.route(call)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._handlers: Dict[TransportType, TransportHandler] = {}
        self._metrics = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "total_duration_ms": 0,
            "by_tool": {},
            "by_transport": {}
        }

    def register_handler(self, transport: TransportType,
                         handler: TransportHandler) -> None:
        """Register a handler for a transport type."""
        self._handlers[transport] = handler

    def get_handler(self, transport: TransportType) -> Optional[TransportHandler]:
        """Get handler for a transport type."""
        return self._handlers.get(transport)

    async def route(self, call: ToolCall) -> ToolResult:
        """
        Route a tool call to the appropriate handler.

        Args:
            call: The tool call to route

        Returns:
            Tool execution result
        """
        self._metrics["total_calls"] += 1

        # Track by tool
        if call.tool_name not in self._metrics["by_tool"]:
            self._metrics["by_tool"][call.tool_name] = {"calls": 0, "total_ms": 0}
        self._metrics["by_tool"][call.tool_name]["calls"] += 1

        # Track by transport
        transport_key = call.transport.value
        if transport_key not in self._metrics["by_transport"]:
            self._metrics["by_transport"][transport_key] = 0
        self._metrics["by_transport"][transport_key] += 1

        # Get handler
        handler = self._handlers.get(call.transport)

        if not handler:
            result = ToolResult(
                call_id=call.call_id,
                success=False,
                error=f"No handler for transport: {call.transport.value}"
            )
            self._metrics["failed_calls"] += 1
            return result

        # Execute call
        result = await handler.call(call)

        # Update metrics
        if result.success:
            self._metrics["successful_calls"] += 1
        else:
            self._metrics["failed_calls"] += 1

        self._metrics["total_duration_ms"] += result.duration_ms
        self._metrics["by_tool"][call.tool_name]["total_ms"] += result.duration_ms

        return result

    def route_sync(self, call: ToolCall) -> ToolResult:
        """Synchronous wrapper for route."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.route(call))

    def get_metrics(self) -> Dict[str, Any]:
        """Get router metrics."""
        avg_duration = (
            self._metrics["total_duration_ms"] / self._metrics["total_calls"]
            if self._metrics["total_calls"] > 0 else 0
        )

        return {
            **self._metrics,
            "average_duration_ms": avg_duration,
            "success_rate": (
                self._metrics["successful_calls"] / self._metrics["total_calls"] * 100
                if self._metrics["total_calls"] > 0 else 0
            )
        }

    def register_internal_tool(self, name: str,
                               handler: Callable) -> None:
        """Convenience method to register an internal tool."""
        internal_handler = self._handlers.get(TransportType.INTERNAL)
        if isinstance(internal_handler, InternalHandler):
            internal_handler.register_handler(name, handler)


# Global router instance
_global_router: Optional[ToolRouter] = None


def get_router() -> ToolRouter:
    """Get the global tool router."""
    global _global_router
    if _global_router is None:
        _global_router = ToolRouter()
        # Register default handlers
        _global_router.register_handler(TransportType.STDIO, StdioHandler())
        _global_router.register_handler(TransportType.INTERNAL, InternalHandler())
    return _global_router


async def route_tool_call(call: ToolCall) -> ToolResult:
    """Route a tool call through the global router."""
    return await get_router().route(call)
