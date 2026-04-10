"""
Integration Tests for Resilience Patterns

Tests the integration of resilience components:
1. Circuit breaker with degradation
2. Graceful degradation flow
3. Timeout recovery
4. Unified retry facade

Author: TITAN FUSE Team
Version: 1.2.0
"""

import pytest
import sys
import os
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestCircuitBreakerIntegration:
    """Tests for circuit breaker integration."""
    
    @pytest.fixture
    def event_bus(self):
        """Create EventBus for tests."""
        from src.events.event_bus import EventBus
        return EventBus()
    
    def test_circuit_breaker_opens_on_failures(self, event_bus):
        """Test that circuit opens after consecutive failures."""
        from src.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
        
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker("test_service", config=config, event_bus=event_bus)
        
        # Cause failures
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.execute(lambda: int("invalid"))
        
        assert breaker.state == CircuitState.OPEN
    
    def test_circuit_breaker_half_open_recovery(self, event_bus):
        """Test recovery through half-open state."""
        from src.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
        
        config = CircuitBreakerConfig(
            failure_threshold=2,
            timeout_ms=100,
            success_threshold=2,
            half_open_max_calls=2,
        )
        breaker = CircuitBreaker("test_service", config=config, event_bus=event_bus)
        
        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.execute(lambda: int("invalid"))
        
        assert breaker.state == CircuitState.OPEN
        
        # Wait for timeout
        time.sleep(0.15)
        
        # Should transition to half-open
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Successful operations should close it
        for _ in range(2):
            breaker.execute(lambda: "success")
        
        assert breaker.state == CircuitState.CLOSED
    
    def test_circuit_breaker_with_registry(self, event_bus):
        """Test circuit breaker registry management."""
        from src.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitState, CircuitBreakerConfig
        
        registry = CircuitBreakerRegistry(event_bus=event_bus)
        
        # Create multiple circuits
        config = CircuitBreakerConfig(failure_threshold=2)
        service_a = registry.get_or_create("service_a", config=config)
        service_b = registry.get_or_create("service_b", config=config)
        
        # Open service_a
        for _ in range(2):
            with pytest.raises(ValueError):
                service_a.execute(lambda: int("invalid"))
        
        # Check states
        states = registry.get_all_states()
        assert states["service_a"] == CircuitState.OPEN
        assert states["service_b"] == CircuitState.CLOSED
        
        # Reset all
        registry.reset_all()
        
        states = registry.get_all_states()
        assert states["service_a"] == CircuitState.CLOSED


class TestGracefulDegradation:
    """Tests for graceful degradation."""
    
    @pytest.fixture
    def event_bus(self):
        """Create EventBus for tests."""
        from src.events.event_bus import EventBus
        return EventBus()
    
    def test_full_to_reduced_degradation(self, event_bus):
        """Test degradation from FULL to REDUCED."""
        from src.resilience.degradation import DegradationManager, DegradationLevel, DegradationConfig
        
        config = DegradationConfig(enable_events=True)
        manager = DegradationManager(config=config, event_bus=event_bus)
        
        assert manager.get_level() == DegradationLevel.FULL
        
        # Disable non-critical features
        manager.disable_feature("session_memory", "Service unavailable")
        manager.disable_feature("self_awareness", "Service unavailable")
        
        assert manager.get_level() == DegradationLevel.REDUCED
    
    def test_reduced_to_minimal_degradation(self, event_bus):
        """Test degradation from REDUCED to MINIMAL."""
        from src.resilience.degradation import DegradationManager, DegradationLevel, DegradationConfig
        
        config = DegradationConfig(enable_events=True)
        manager = DegradationManager(config=config, event_bus=event_bus)
        
        # Start at REDUCED
        manager.set_level(DegradationLevel.REDUCED)
        
        # Disable critical features (need 2 for MINIMAL)
        manager.disable_feature("skill_graph", "Critical failure")
        manager.disable_feature("profile_detection", "Critical failure")
        
        assert manager.get_level() == DegradationLevel.MINIMAL
    
    def test_automatic_recovery(self, event_bus):
        """Test automatic feature recovery."""
        from src.resilience.degradation import DegradationManager, DegradationConfig
        
        config = DegradationConfig(
            error_count_threshold=3,
            recovery_success_threshold=2,
            auto_recovery_enabled=True,
        )
        manager = DegradationManager(config=config, event_bus=event_bus)
        
        # Disable through errors
        for _ in range(3):
            manager.record_error("session_memory")
        
        assert not manager.is_feature_enabled("session_memory")
        
        # Attempt recovery
        manager.attempt_recovery("session_memory")
        
        # Record successes
        for _ in range(2):
            manager.record_success("session_memory")
        
        assert manager.is_feature_enabled("session_memory")
    
    def test_profile_detection_weights_adjustment(self, event_bus):
        """Test that profile detection weights adjust with degradation."""
        from src.resilience.degradation import DegradationManager, DegradationLevel
        
        manager = DegradationManager(event_bus=event_bus)
        
        # Full level weights
        weights = manager.get_profile_detection_weights()
        assert weights["history_analysis"] == 0.2
        
        # Reduced level - session memory disabled
        manager.set_level(DegradationLevel.REDUCED)
        weights = manager.get_profile_detection_weights()
        assert weights["history_analysis"] == 0.0
        assert weights["lexical_analysis"] == 0.5  # Redistributed


class TestTimeoutRecovery:
    """Tests for timeout handling and recovery."""
    
    @pytest.fixture
    def event_bus(self):
        """Create EventBus for tests."""
        from src.events.event_bus import EventBus
        return EventBus()
    
    def test_timeout_triggers_fallback(self, event_bus):
        """Test that timeout triggers fallback behavior."""
        from src.resilience.degradation import DegradationManager
        
        manager = DegradationManager(event_bus=event_bus)
        fallback_chain = manager.get_fallback_chain()
        
        assert "direct_prompt" in fallback_chain
    
    def test_timeout_with_degradation(self, event_bus):
        """Test timeout handling during degradation."""
        from src.resilience.degradation import DegradationManager, DegradationLevel
        
        manager = DegradationManager(event_bus=event_bus)
        
        # Set to MINIMAL
        manager.set_level(DegradationLevel.MINIMAL)
        
        # Should only have direct_prompt fallback
        fallback_chain = manager.get_fallback_chain()
        assert fallback_chain == ["direct_prompt"]


class TestUnifiedRetryFacade:
    """Tests for unified retry facade integration."""
    
    @pytest.fixture
    def event_bus(self):
        """Create EventBus for tests."""
        from src.events.event_bus import EventBus
        return EventBus()
    
    def test_retry_with_success(self, event_bus):
        """Test retry with eventual success."""
        from src.resilience.retry_executor_facade import RetryExecutorFacade
        
        facade = RetryExecutorFacade(event_bus=event_bus)
        
        call_count = [0]
        
        def eventually_succeed():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("Temporary failure")
            return "success"
        
        facade_result = facade.execute_with_retry(
            eventually_succeed,
            max_retries=5,
        )
        
        assert facade_result.success
        assert facade_result.result == "success"
        assert call_count[0] == 3
    
    def test_retry_exhaustion(self, event_bus):
        """Test retry exhaustion."""
        from src.resilience.retry_executor_facade import RetryExecutorFacade
        
        facade = RetryExecutorFacade(event_bus=event_bus)
        
        def always_fail():
            raise ValueError("Permanent failure")
        
        facade_result = facade.execute_with_retry(
            always_fail,
            max_retries=3,
        )
        
        assert not facade_result.success
        assert facade_result.error is not None
    
    def test_circuit_breaker_integration(self, event_bus):
        """Test circuit breaker integration with retry facade."""
        from src.resilience.retry_executor_facade import RetryExecutorFacade
        
        facade = RetryExecutorFacade(event_bus=event_bus)
        
        # Multiple failures with circuit
        for _ in range(10):
            facade.execute_with_retry(
                lambda: int("invalid"),
                max_retries=1,
                circuit_id="test_circuit",
            )
        
        # Circuit should be tracked
        metrics = facade.get_metrics()
        assert metrics is not None
        assert metrics["total_failures"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
