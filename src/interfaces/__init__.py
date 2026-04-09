"""
TITAN Protocol Interfaces Module.

This module contains abstract base classes and interfaces that define
the contracts for plugin implementations and system integrations.

Components:
- PluginInterface: Base class for all TITAN plugins
- RoutingDecision: Routing decision data structure
- ExecutionResult: Plugin execution result data structure
- ErrorResult: Error handling result data structure
"""

from .plugin_interface import (
    PluginInterface,
    PluginState,
    PluginInfo,
    PluginInitializationError,
    PluginExecutionError,
    RoutingDecision,
    RoutingAction,
    ExecutionResult,
    ErrorResult,
    create_plugin_info,
    PluginFactory,
)

__all__ = [
    # Main interface
    "PluginInterface",
    
    # State management
    "PluginState",
    
    # Data structures
    "PluginInfo",
    "RoutingDecision",
    "RoutingAction",
    "ExecutionResult",
    "ErrorResult",
    
    # Exceptions
    "PluginInitializationError",
    "PluginExecutionError",
    
    # Factory functions
    "create_plugin_info",
    "PluginFactory",
]

__version__ = "5.0.0"
