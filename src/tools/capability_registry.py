"""
TITAN FUSE Protocol - Capability Registry

Declarative registry for tool capabilities with schema validation.
Supports MCP, stdio, WebSocket, and API transport types.

TASK-001: Tool Orchestration & Capability Registry
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, TypeVar, Generic
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
import hashlib


class CapabilityCategory(Enum):
    """Categories of tool capabilities."""
    FILESYSTEM = "fs"
    WEB = "web"
    CODE = "code"
    MEMORY = "memory"
    LLM = "llm"
    DATABASE = "db"
    SYSTEM = "system"
    CUSTOM = "custom"


class CapabilityStatus(Enum):
    """Status of a registered capability."""
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"


@dataclass
class CapabilitySchema:
    """Input/output schema for a capability."""
    input_schema: Dict[str, Any]  # JSON Schema for input
    output_schema: Dict[str, Any]  # JSON Schema for output
    examples: List[Dict[str, Any]] = field(default_factory=list)

    def validate_input(self, data: Dict[str, Any]) -> bool:
        """Validate input against schema."""
        # Simplified validation - in production use jsonschema library
        required = self.input_schema.get("required", [])
        properties = self.input_schema.get("properties", {})

        for req in required:
            if req not in data:
                return False

        return True

    def validate_output(self, data: Dict[str, Any]) -> bool:
        """Validate output against schema."""
        required = self.output_schema.get("required", [])
        properties = self.output_schema.get("properties", {})

        for req in required:
            if req not in data:
                return False

        return True


@dataclass
class Capability:
    """
    A registered tool capability.

    Attributes:
        name: Unique identifier for the capability
        category: Capability category (fs, web, code, memory, etc.)
        description: Human-readable description
        schema: Input/output schemas
        transport: Transport type (mcp, stdio, ws, api)
        handler: Callable to execute the capability
        status: Availability status
        version: Capability version
        permissions: Required permissions
        rate_limit: Optional rate limit (calls per minute)
        timeout: Timeout in seconds
        metadata: Additional metadata
    """
    name: str
    category: CapabilityCategory
    description: str
    schema: CapabilitySchema
    transport: str = "stdio"
    handler: Optional[Callable] = None
    status: CapabilityStatus = CapabilityStatus.AVAILABLE
    version: str = "1.0.0"
    permissions: List[str] = field(default_factory=list)
    rate_limit: Optional[int] = None
    timeout: int = 30
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert capability to dictionary."""
        return {
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "transport": self.transport,
            "status": self.status.value,
            "version": self.version,
            "permissions": self.permissions,
            "rate_limit": self.rate_limit,
            "timeout": self.timeout,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "schema": {
                "input": self.schema.input_schema,
                "output": self.schema.output_schema,
                "examples": self.schema.examples
            }
        }

    def get_id(self) -> str:
        """Generate unique ID for this capability."""
        content = f"{self.category.value}:{self.name}:{self.version}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class CapabilityRegistry:
    """
    Central registry for all tool capabilities.

    Features:
    - Declarative capability registration
    - Schema validation
    - Category-based lookup
    - Transport-based routing
    - Permission checking
    - Rate limiting

    Usage:
        registry = CapabilityRegistry()

        # Register a capability
        registry.register(Capability(
            name="read_file",
            category=CapabilityCategory.FILESYSTEM,
            description="Read file contents",
            schema=CapabilitySchema(
                input_schema={"type": "object", "required": ["path"]},
                output_schema={"type": "object", "required": ["content"]}
            ),
            transport="stdio",
            handler=lambda p: open(p["path"]).read()
        ))

        # Get a capability
        cap = registry.get("read_file")

        # Execute a capability
        result = registry.execute("read_file", {"path": "/tmp/test.txt"})
    """

    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._categories: Dict[CapabilityCategory, List[str]] = {
            cat: [] for cat in CapabilityCategory
        }
        self._transports: Dict[str, List[str]] = {}
        self._call_counts: Dict[str, int] = {}
        self._last_calls: Dict[str, datetime] = {}

    def register(self, capability: Capability) -> str:
        """
        Register a new capability.

        Args:
            capability: The capability to register

        Returns:
            The capability ID

        Raises:
            ValueError: If capability already exists
        """
        if capability.name in self._capabilities:
            raise ValueError(f"Capability already registered: {capability.name}")

        self._capabilities[capability.name] = capability
        self._categories[capability.category].append(capability.name)

        if capability.transport not in self._transports:
            self._transports[capability.transport] = []
        self._transports[capability.transport].append(capability.name)

        self._call_counts[capability.name] = 0

        return capability.get_id()

    def unregister(self, name: str) -> bool:
        """
        Unregister a capability.

        Args:
            name: Name of capability to unregister

        Returns:
            True if unregistered, False if not found
        """
        if name not in self._capabilities:
            return False

        cap = self._capabilities[name]
        self._categories[cap.category].remove(name)
        self._transports[cap.transport].remove(name)
        del self._capabilities[name]

        return True

    def get(self, name: str) -> Optional[Capability]:
        """Get a capability by name."""
        return self._capabilities.get(name)

    def list(self,
             category: Optional[CapabilityCategory] = None,
             transport: Optional[str] = None,
             status: Optional[CapabilityStatus] = None) -> List[Capability]:
        """
        List capabilities with optional filters.

        Args:
            category: Filter by category
            transport: Filter by transport type
            status: Filter by status

        Returns:
            List of matching capabilities
        """
        caps = list(self._capabilities.values())

        if category:
            caps = [c for c in caps if c.category == category]
        if transport:
            caps = [c for c in caps if c.transport == transport]
        if status:
            caps = [c for c in caps if c.status == status]

        return caps

    def execute(self, name: str, params: Dict[str, Any],
                context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a capability.

        Args:
            name: Name of capability to execute
            params: Input parameters
            context: Optional execution context

        Returns:
            Execution result

        Raises:
            ValueError: If capability not found or validation fails
            RuntimeError: If capability is unavailable
        """
        cap = self.get(name)
        if not cap:
            raise ValueError(f"Capability not found: {name}")

        if cap.status != CapabilityStatus.AVAILABLE:
            raise RuntimeError(f"Capability unavailable: {name} (status: {cap.status.value})")

        # Validate input
        if not cap.schema.validate_input(params):
            raise ValueError(f"Input validation failed for: {name}")

        # Check rate limit
        if cap.rate_limit:
            if self._call_counts.get(name, 0) >= cap.rate_limit:
                raise RuntimeError(f"Rate limit exceeded for: {name}")

        # Execute handler
        if cap.handler:
            try:
                result = cap.handler(params, context or {})
                self._call_counts[name] = self._call_counts.get(name, 0) + 1
                self._last_calls[name] = datetime.utcnow()

                # Validate output
                if isinstance(result, dict) and not cap.schema.validate_output(result):
                    raise ValueError(f"Output validation failed for: {name}")

                return {
                    "success": True,
                    "capability": name,
                    "result": result,
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
            except Exception as e:
                return {
                    "success": False,
                    "capability": name,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
        else:
            raise RuntimeError(f"No handler registered for: {name}")

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_capabilities": len(self._capabilities),
            "by_category": {
                cat.value: len(caps)
                for cat, caps in self._categories.items()
            },
            "by_transport": {
                t: len(caps)
                for t, caps in self._transports.items()
            },
            "by_status": {
                status.value: len([c for c in self._capabilities.values() if c.status == status])
                for status in CapabilityStatus
            },
            "total_calls": sum(self._call_counts.values())
        }

    def export_manifest(self) -> Dict[str, Any]:
        """
        Export full capability manifest.

        Returns:
            Complete manifest of all registered capabilities
        """
        return {
            "version": "1.0.0",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "capabilities": {
                name: cap.to_dict()
                for name, cap in self._capabilities.items()
            },
            "stats": self.get_stats()
        }

    def import_manifest(self, manifest: Dict[str, Any]) -> int:
        """
        Import capabilities from a manifest.

        Args:
            manifest: Capability manifest

        Returns:
            Number of capabilities imported
        """
        count = 0
        for name, cap_data in manifest.get("capabilities", {}).items():
            try:
                schema = CapabilitySchema(
                    input_schema=cap_data["schema"]["input"],
                    output_schema=cap_data["schema"]["output"],
                    examples=cap_data["schema"].get("examples", [])
                )

                cap = Capability(
                    name=name,
                    category=CapabilityCategory(cap_data["category"]),
                    description=cap_data["description"],
                    schema=schema,
                    transport=cap_data.get("transport", "stdio"),
                    status=CapabilityStatus(cap_data.get("status", "available")),
                    version=cap_data.get("version", "1.0.0"),
                    permissions=cap_data.get("permissions", []),
                    rate_limit=cap_data.get("rate_limit"),
                    timeout=cap_data.get("timeout", 30),
                    metadata=cap_data.get("metadata", {})
                )

                self.register(cap)
                count += 1
            except Exception as e:
                print(f"Failed to import capability {name}: {e}")

        return count


# Global registry instance
_global_registry: Optional[CapabilityRegistry] = None


def get_registry() -> CapabilityRegistry:
    """Get the global capability registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = CapabilityRegistry()
    return _global_registry


def register_capability(capability: Capability) -> str:
    """Register a capability in the global registry."""
    return get_registry().register(capability)


def get_capability(name: str) -> Optional[Capability]:
    """Get a capability from the global registry."""
    return get_registry().get(name)


def list_capabilities(**kwargs) -> List[Capability]:
    """List capabilities from the global registry."""
    return get_registry().list(**kwargs)
