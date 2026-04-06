"""
TITAN FUSE Protocol - Tools Module

Tool Orchestration & Capability Registry (TASK-001)

This module provides:
- Capability Registry: Declarative registry of tool capabilities
- Tool Router: Unified routing for MCP/stdio/ws/api calls
- Schema Validation: Input/output validation for all tools
"""

from .capability_registry import (
    CapabilityRegistry,
    Capability,
    CapabilityCategory,
    register_capability,
    get_capability,
    list_capabilities
)

from .tool_router import (
    ToolRouter,
    ToolCall,
    ToolResult,
    TransportType,
    route_tool_call
)

from .schema_validator import (
    SchemaValidator,
    ValidationError,
    validate_input,
    validate_output
)

__all__ = [
    # Capability Registry
    "CapabilityRegistry",
    "Capability",
    "CapabilityCategory",
    "register_capability",
    "get_capability",
    "list_capabilities",
    # Tool Router
    "ToolRouter",
    "ToolCall",
    "ToolResult",
    "TransportType",
    "route_tool_call",
    # Schema Validator
    "SchemaValidator",
    "ValidationError",
    "validate_input",
    "validate_output"
]

__version__ = "1.0.0"
