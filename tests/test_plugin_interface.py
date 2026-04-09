"""
Test cases for PluginInterface (ITEM_018).

Tests for the plugin interface and data structures.
"""

import pytest
from typing import Dict, Any

# Import from the module we're testing
import sys
sys.path.insert(0, '/home/z/my-project/download/titan-impl')

from src.interfaces.plugin_interface import (
    PluginInterface,
    PluginState,
    PluginInfo,
    RoutingDecision,
    RoutingAction,
    ExecutionResult,
    ErrorResult,
    PluginInitializationError,
    PluginExecutionError,
    create_plugin_info,
)


class MockPlugin(PluginInterface):
    """Mock plugin implementation for testing."""
    
    def __init__(self, config: Dict[str, Any] = None):
        self._config = config or {}
        self._state = PluginState.UNINITIALIZED
        self._initialized = False
        self._shutdown = False
    
    def on_init(self) -> None:
        """Initialize the plugin."""
        self._state = PluginState.READY
        self._initialized = True
    
    def on_route(self, intent: str, context: Dict[str, Any]) -> RoutingDecision:
        """Make routing decision."""
        if intent == "test_abort":
            return RoutingDecision.abort_request("Test abort")
        elif intent == "test_redirect":
            return RoutingDecision.redirect_to("other_plugin", 0.9, "Test redirect")
        elif intent == "test_fallback":
            return RoutingDecision.use_fallback("Test fallback")
        return RoutingDecision.continue_routing("Test continue")
    
    def on_execute(self, plan: Dict[str, Any]) -> ExecutionResult:
        """Execute plugin logic."""
        if plan.get("fail"):
            return ExecutionResult.failure_result("Planned failure", 100)
        return ExecutionResult.success_result({"result": "success"}, 50)
    
    def on_error(self, error: Exception, context: Dict[str, Any]) -> ErrorResult:
        """Handle errors."""
        if "recoverable" in str(error):
            return ErrorResult.handled_result("Recovered from error")
        return ErrorResult.unhandled_result(str(error), RoutingAction.FALLBACK)
    
    def on_shutdown(self) -> None:
        """Shutdown the plugin."""
        self._state = PluginState.SHUTDOWN
        self._shutdown = True


class TestPluginInterface:
    """Test cases for PluginInterface."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.plugin = MockPlugin()
    
    def test_plugin_initialization(self):
        """Test plugin initialization."""
        assert self.plugin.get_state() == PluginState.UNINITIALIZED
        assert not self.plugin._initialized
        
        self.plugin.on_init()
        
        assert self.plugin.get_state() == PluginState.READY
        assert self.plugin._initialized
        assert self.plugin.is_ready()
    
    def test_routing_continue(self):
        """Test CONTINUE routing decision."""
        decision = self.plugin.on_route("test_intent", {})
        
        assert decision.action == RoutingAction.CONTINUE
        assert decision.confidence == 1.0
        assert "continue" in decision.reason.lower()
    
    def test_routing_abort(self):
        """Test ABORT routing decision."""
        decision = self.plugin.on_route("test_abort", {})
        
        assert decision.action == RoutingAction.ABORT
        assert "abort" in decision.reason.lower()
    
    def test_routing_redirect(self):
        """Test REDIRECT routing decision."""
        decision = self.plugin.on_route("test_redirect", {})
        
        assert decision.action == RoutingAction.REDIRECT
        assert decision.target == "other_plugin"
        assert decision.confidence == 0.9
    
    def test_routing_fallback(self):
        """Test FALLBACK routing decision."""
        decision = self.plugin.on_route("test_fallback", {})
        
        assert decision.action == RoutingAction.FALLBACK
    
    def test_execution_success(self):
        """Test successful execution."""
        result = self.plugin.on_execute({"action": "test"})
        
        assert result.success
        assert result.outputs["result"] == "success"
        assert result.execution_time_ms == 50
        assert result.error is None
    
    def test_execution_failure(self):
        """Test failed execution."""
        result = self.plugin.on_execute({"fail": True})
        
        assert not result.success
        assert result.error == "Planned failure"
        assert result.execution_time_ms == 100
    
    def test_error_handling_recoverable(self):
        """Test recoverable error handling."""
        error = Exception("recoverable error")
        result = self.plugin.on_error(error, {})
        
        assert result.handled
        assert "Recovered" in result.error_message
    
    def test_error_handling_unrecoverable(self):
        """Test unrecoverable error handling."""
        error = Exception("critical error")
        result = self.plugin.on_error(error, {})
        
        assert not result.handled
        assert result.fallback_action == RoutingAction.FALLBACK
    
    def test_shutdown(self):
        """Test plugin shutdown."""
        self.plugin.on_init()
        assert self.plugin.get_state() == PluginState.READY
        
        self.plugin.on_shutdown()
        
        assert self.plugin.get_state() == PluginState.SHUTDOWN
        assert self.plugin._shutdown
    
    def test_get_info(self):
        """Test getting plugin info."""
        info = self.plugin.get_info()
        
        assert info.plugin_id == "MockPlugin"
        assert info.plugin_type == "base"
    
    def test_get_capabilities(self):
        """Test getting plugin capabilities."""
        capabilities = self.plugin.get_capabilities()
        
        assert isinstance(capabilities, list)


class TestRoutingDecision:
    """Test cases for RoutingDecision dataclass."""
    
    def test_continue_routing_factory(self):
        """Test continue_routing factory method."""
        decision = RoutingDecision.continue_routing("Test reason")
        
        assert decision.action == RoutingAction.CONTINUE
        assert decision.reason == "Test reason"
        assert decision.confidence == 1.0
    
    def test_redirect_to_factory(self):
        """Test redirect_to factory method."""
        decision = RoutingDecision.redirect_to("target_plugin", 0.75, "Test redirect")
        
        assert decision.action == RoutingAction.REDIRECT
        assert decision.target == "target_plugin"
        assert decision.confidence == 0.75
        assert decision.reason == "Test redirect"
    
    def test_use_fallback_factory(self):
        """Test use_fallback factory method."""
        decision = RoutingDecision.use_fallback("Test fallback")
        
        assert decision.action == RoutingAction.FALLBACK
        assert decision.reason == "Test fallback"
    
    def test_abort_request_factory(self):
        """Test abort_request factory method."""
        decision = RoutingDecision.abort_request("Critical failure")
        
        assert decision.action == RoutingAction.ABORT
        assert decision.reason == "Critical failure"
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        decision = RoutingDecision(
            action=RoutingAction.REDIRECT,
            target="test_target",
            confidence=0.8,
            reason="Test",
            alternatives=["alt1", "alt2"]
        )
        
        data = decision.to_dict()
        
        assert data["action"] == "redirect"
        assert data["target"] == "test_target"
        assert data["confidence"] == 0.8
        assert data["alternatives"] == ["alt1", "alt2"]


class TestExecutionResult:
    """Test cases for ExecutionResult dataclass."""
    
    def test_success_result_factory(self):
        """Test success_result factory method."""
        result = ExecutionResult.success_result({"data": "test"}, 100)
        
        assert result.success
        assert result.outputs == {"data": "test"}
        assert result.execution_time_ms == 100
        assert result.error is None
    
    def test_failure_result_factory(self):
        """Test failure_result factory method."""
        result = ExecutionResult.failure_result("Test error", 50)
        
        assert not result.success
        assert result.error == "Test error"
        assert result.execution_time_ms == 50
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        result = ExecutionResult(
            success=True,
            outputs={"key": "value"},
            gaps=[{"gap_id": "G001"}],
            metrics={"duration": 100}
        )
        
        data = result.to_dict()
        
        assert data["success"] is True
        assert data["outputs"] == {"key": "value"}
        assert len(data["gaps"]) == 1


class TestErrorResult:
    """Test cases for ErrorResult dataclass."""
    
    def test_handled_result_factory(self):
        """Test handled_result factory method."""
        result = ErrorResult.handled_result("Error handled")
        
        assert result.handled
        assert result.error_message == "Error handled"
    
    def test_unhandled_result_factory(self):
        """Test unhandled_result factory method."""
        result = ErrorResult.unhandled_result("Critical error", RoutingAction.ABORT)
        
        assert not result.handled
        assert result.error_message == "Critical error"
        assert result.fallback_action == RoutingAction.ABORT


class TestPluginInfo:
    """Test cases for PluginInfo dataclass."""
    
    def test_plugin_info_creation(self):
        """Test creating plugin info."""
        info = PluginInfo(
            plugin_id="test_plugin",
            plugin_type="test",
            version="2.0.0",
            description="Test plugin",
            capabilities=["cap1", "cap2"],
            dependencies=["dep1"],
            priority=5
        )
        
        assert info.plugin_id == "test_plugin"
        assert info.plugin_type == "test"
        assert info.version == "2.0.0"
        assert info.capabilities == ["cap1", "cap2"]
        assert info.priority == 5
    
    def test_create_plugin_info_function(self):
        """Test create_plugin_info factory function."""
        info = create_plugin_info(
            plugin_id="factory_plugin",
            plugin_type="factory",
            capabilities=["test"],
            priority=3
        )
        
        assert info.plugin_id == "factory_plugin"
        assert info.plugin_type == "factory"
        assert info.capabilities == ["test"]
        assert info.priority == 3


class TestExceptions:
    """Test cases for custom exceptions."""
    
    def test_plugin_initialization_error(self):
        """Test PluginInitializationError."""
        error = PluginInitializationError(
            plugin_id="test_plugin",
            reason="Config missing",
            details={"missing_key": "db_url"}
        )
        
        assert error.plugin_id == "test_plugin"
        assert error.reason == "Config missing"
        assert error.details["missing_key"] == "db_url"
        assert "test_plugin" in str(error)
    
    def test_plugin_execution_error(self):
        """Test PluginExecutionError."""
        original = ValueError("Bad value")
        error = PluginExecutionError(
            plugin_id="exec_plugin",
            error=original,
            context={"input": "test"}
        )
        
        assert error.plugin_id == "exec_plugin"
        assert error.original_error == original
        assert error.context["input"] == "test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
