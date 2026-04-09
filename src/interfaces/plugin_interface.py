"""
ITEM-INTERFACE-001: Plugin Interface for TITAN Protocol v5.0.0.

This module defines the abstract base class for all TITAN plugins,
providing a standardized interface for lifecycle management, routing,
execution, error handling, and shutdown.

All plugins must implement this interface to be registered with the
UniversalRouter and participate in the skill execution pipeline.

Integration Points:
- UniversalRouter: Calls on_route() for routing decisions
- SkillLibrary: Uses PluginInterface implementations for skill execution
- EventBus: Plugins can emit and subscribe to events
- ChainComposer: Composes plugins into execution chains

Author: TITAN Protocol Team
Version: 5.0.0
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Callable


class PluginState(Enum):
    """State of a plugin instance."""
    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"
    SHUTDOWN = "shutdown"


class RoutingAction(Enum):
    """Actions that can be taken during routing."""
    CONTINUE = "continue"           # Continue to next handler
    SKIP = "skip"                   # Skip remaining handlers
    REDIRECT = "redirect"           # Redirect to different target
    FALLBACK = "fallback"           # Use fallback pipeline
    ABORT = "abort"                 # Abort the request
    DEFER = "defer"                 # Defer for later processing


@dataclass
class RoutingDecision:
    """
    Result of a routing decision.
    
    Attributes:
        action: The action to take (CONTINUE, SKIP, REDIRECT, etc.)
        target: Optional target skill or pipeline
        confidence: Confidence in this routing decision (0.0 to 1.0)
        metadata: Additional metadata about the decision
        reason: Human-readable reason for the decision
        alternatives: Alternative routing options if primary fails
        required_gates: Gates that must pass before execution
        estimated_duration_ms: Estimated execution duration
    """
    action: RoutingAction = RoutingAction.CONTINUE
    target: Optional[str] = None
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    alternatives: List[str] = field(default_factory=list)
    required_gates: List[str] = field(default_factory=list)
    estimated_duration_ms: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "action": self.action.value,
            "target": self.target,
            "confidence": self.confidence,
            "metadata": self.metadata,
            "reason": self.reason,
            "alternatives": self.alternatives,
            "required_gates": self.required_gates,
            "estimated_duration_ms": self.estimated_duration_ms
        }
    
    @classmethod
    def continue_routing(cls, reason: str = "") -> "RoutingDecision":
        """Create a CONTINUE routing decision."""
        return cls(action=RoutingAction.CONTINUE, reason=reason)
    
    @classmethod
    def redirect_to(cls, target: str, confidence: float = 1.0, 
                    reason: str = "") -> "RoutingDecision":
        """Create a REDIRECT routing decision."""
        return cls(
            action=RoutingAction.REDIRECT, 
            target=target, 
            confidence=confidence,
            reason=reason
        )
    
    @classmethod
    def use_fallback(cls, reason: str = "") -> "RoutingDecision":
        """Create a FALLBACK routing decision."""
        return cls(action=RoutingAction.FALLBACK, reason=reason)
    
    @classmethod
    def abort_request(cls, reason: str) -> "RoutingDecision":
        """Create an ABORT routing decision."""
        return cls(action=RoutingAction.ABORT, reason=reason)


@dataclass
class ExecutionResult:
    """
    Result of plugin execution.
    
    Attributes:
        success: Whether the execution succeeded
        outputs: Output data from execution
        gaps: Gaps or issues found during execution
        metrics: Performance metrics
        next_action: Suggested next action
        error: Error message if execution failed
        execution_time_ms: Time taken for execution
        fallback_used: Whether a fallback skill was used for this execution
    """
    success: bool = True
    outputs: Dict[str, Any] = field(default_factory=dict)
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    next_action: Optional[RoutingAction] = None
    error: Optional[str] = None
    execution_time_ms: int = 0
    fallback_used: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "outputs": self.outputs,
            "gaps": self.gaps,
            "metrics": self.metrics,
            "next_action": self.next_action.value if self.next_action else None,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "fallback_used": self.fallback_used
        }
    
    @classmethod
    def success_result(cls, outputs: Dict[str, Any], 
                       execution_time_ms: int = 0) -> "ExecutionResult":
        """Create a successful execution result."""
        return cls(success=True, outputs=outputs, execution_time_ms=execution_time_ms)
    
    @classmethod
    def failure_result(cls, error: str, 
                       execution_time_ms: int = 0) -> "ExecutionResult":
        """Create a failed execution result."""
        return cls(success=False, error=error, execution_time_ms=execution_time_ms)


@dataclass
class ErrorResult:
    """
    Result of error handling.
    
    Attributes:
        handled: Whether the error was handled by this plugin
        fallback_action: Action to take if error wasn't fully handled
        error_message: Human-readable error message
        should_retry: Whether the operation should be retried
        retry_after_ms: Milliseconds to wait before retry
        log_level: Suggested log level for this error
        notify_user: Whether to notify the user
    """
    handled: bool = False
    fallback_action: Optional[RoutingAction] = None
    error_message: str = ""
    should_retry: bool = False
    retry_after_ms: int = 0
    log_level: str = "ERROR"
    notify_user: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "handled": self.handled,
            "fallback_action": self.fallback_action.value if self.fallback_action else None,
            "error_message": self.error_message,
            "should_retry": self.should_retry,
            "retry_after_ms": self.retry_after_ms,
            "log_level": self.log_level,
            "notify_user": self.notify_user
        }
    
    @classmethod
    def handled_result(cls, message: str = "") -> "ErrorResult":
        """Create a handled error result."""
        return cls(handled=True, error_message=message)
    
    @classmethod
    def unhandled_result(cls, message: str, 
                         fallback: RoutingAction = RoutingAction.FALLBACK) -> "ErrorResult":
        """Create an unhandled error result with fallback."""
        return cls(
            handled=False, 
            error_message=message, 
            fallback_action=fallback
        )


@dataclass
class PluginInfo:
    """
    Information about a plugin.
    
    Attributes:
        plugin_id: Unique identifier for this plugin
        plugin_type: Type/category of the plugin
        version: Plugin version
        description: Human-readable description
        capabilities: List of capabilities this plugin provides
        dependencies: List of other plugins this depends on
        priority: Execution priority (lower = higher priority)
        author: Plugin author
        created_at: When the plugin was created
        updated_at: When the plugin was last updated
    """
    plugin_id: str
    plugin_type: str
    version: str = "1.0.0"
    description: str = ""
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    priority: int = 10
    author: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "plugin_id": self.plugin_id,
            "plugin_type": self.plugin_type,
            "version": self.version,
            "description": self.description,
            "capabilities": self.capabilities,
            "dependencies": self.dependencies,
            "priority": self.priority,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


class PluginInterface(ABC):
    """
    Abstract base class for all TITAN plugins.
    
    This interface defines the lifecycle hooks and methods that all plugins
    must implement to participate in the TITAN execution pipeline.
    
    Lifecycle:
    1. Plugin is instantiated with config and event_bus
    2. on_init() is called to initialize the plugin
    3. on_route() is called for each request during routing
    4. on_execute() is called to execute the plugin's logic
    5. on_error() is called if any errors occur
    6. on_shutdown() is called when the plugin is being shut down
    
    Usage:
        class MyPlugin(PluginInterface):
            def on_init(self) -> None:
                # Initialize resources
            
            def on_route(self, intent: str, context: Dict) -> RoutingDecision:
                # Make routing decision
                return RoutingDecision.continue_routing()
            
            def on_execute(self, plan: Dict) -> ExecutionResult:
                # Execute the plugin logic
                return ExecutionResult.success_result({"result": "ok"})
            
            def on_error(self, error: Exception, context: Dict) -> ErrorResult:
                # Handle errors
                return ErrorResult.handled_result(str(error))
            
            def on_shutdown(self) -> None:
                # Clean up resources
                pass
    
    Attributes:
        _config: Configuration dictionary
        _event_bus: EventBus instance for event emission
        _state: Current state of the plugin
        _logger: Logger instance
    """
    
    @abstractmethod
    def on_init(self) -> None:
        """
        Called when the plugin is initialized.
        
        Use this method to:
        - Set up resources (connections, caches, etc.)
        - Subscribe to events
        - Validate configuration
        - Register capabilities
        
        Raises:
            PluginInitializationError: If initialization fails
        """
        pass
    
    @abstractmethod
    def on_route(self, intent: str, context: Dict[str, Any]) -> RoutingDecision:
        """
        Called during the routing phase.
        
        Implement this method to:
        - Determine if this plugin should handle the request
        - Redirect to other plugins or pipelines
        - Add metadata to influence routing decisions
        
        Args:
            intent: The classified intent of the request
            context: Execution context including user profile, session data, etc.
        
        Returns:
            RoutingDecision indicating what action to take
        """
        pass
    
    @abstractmethod
    def on_execute(self, plan: Dict[str, Any]) -> ExecutionResult:
        """
        Called during the execution phase.
        
        Implement this method to:
        - Execute the plugin's main logic
        - Return results and any gaps found
        - Collect performance metrics
        
        Args:
            plan: Execution plan including inputs, configuration, and context
        
        Returns:
            ExecutionResult with outputs, gaps, and metrics
        """
        pass
    
    @abstractmethod
    def on_error(self, error: Exception, context: Dict[str, Any]) -> ErrorResult:
        """
        Called when an error occurs during plugin execution.
        
        Implement this method to:
        - Handle recoverable errors
        - Log error details
        - Determine if retry is appropriate
        - Provide user-friendly error messages
        
        Args:
            error: The exception that occurred
            context: Context where the error occurred
        
        Returns:
            ErrorResult indicating if error was handled
        """
        pass
    
    @abstractmethod
    def on_shutdown(self) -> None:
        """
        Called when the plugin is being shut down.
        
        Use this method to:
        - Clean up resources
        - Flush buffers
        - Unsubscribe from events
        - Save state if needed
        """
        pass
    
    def get_info(self) -> PluginInfo:
        """
        Get information about this plugin.
        
        Override this method to provide plugin-specific information.
        
        Returns:
            PluginInfo with plugin metadata
        """
        return PluginInfo(
            plugin_id=self.__class__.__name__,
            plugin_type="base",
            description=self.__doc__ or ""
        )
    
    def get_state(self) -> PluginState:
        """
        Get the current state of the plugin.
        
        Returns:
            Current PluginState
        """
        return getattr(self, '_state', PluginState.UNINITIALIZED)
    
    def is_ready(self) -> bool:
        """
        Check if the plugin is ready to process requests.
        
        Returns:
            True if plugin is in READY state
        """
        return self.get_state() == PluginState.READY
    
    def get_capabilities(self) -> List[str]:
        """
        Get the capabilities this plugin provides.
        
        Returns:
            List of capability strings
        """
        return self.get_info().capabilities
    
    def get_dependencies(self) -> List[str]:
        """
        Get the plugins this plugin depends on.
        
        Returns:
            List of plugin IDs that must be loaded first
        """
        return self.get_info().dependencies


class PluginInitializationError(Exception):
    """Exception raised when plugin initialization fails."""
    
    def __init__(self, plugin_id: str, reason: str, details: Dict[str, Any] = None):
        self.plugin_id = plugin_id
        self.reason = reason
        self.details = details or {}
        super().__init__(f"Plugin {plugin_id} initialization failed: {reason}")


class PluginExecutionError(Exception):
    """Exception raised when plugin execution fails."""
    
    def __init__(self, plugin_id: str, error: Exception, context: Dict[str, Any] = None):
        self.plugin_id = plugin_id
        self.original_error = error
        self.context = context or {}
        super().__init__(f"Plugin {plugin_id} execution failed: {error}")


# Type alias for plugin factory function
PluginFactory = Callable[[], PluginInterface]


def create_plugin_info(
    plugin_id: str,
    plugin_type: str,
    version: str = "1.0.0",
    description: str = "",
    capabilities: List[str] = None,
    dependencies: List[str] = None,
    priority: int = 10
) -> PluginInfo:
    """
    Factory function to create PluginInfo.
    
    Args:
        plugin_id: Unique identifier
        plugin_type: Type/category
        version: Plugin version
        description: Human-readable description
        capabilities: List of capabilities
        dependencies: List of dependencies
        priority: Execution priority
    
    Returns:
        PluginInfo instance
    """
    return PluginInfo(
        plugin_id=plugin_id,
        plugin_type=plugin_type,
        version=version,
        description=description,
        capabilities=capabilities or [],
        dependencies=dependencies or [],
        priority=priority
    )
