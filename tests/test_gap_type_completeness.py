"""
Tests for ITEM-GAP-001: GAP_TYPE_COMPLETENESS
TITAN PROTOCOL v5.0.0

Validates all 20 GAP_TYPES have proper handlers and resolution paths.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch
import time

from src.state.gap import (
    Gap,
    GapType,
    GapSeverity,
    GapHandler,
    GapResolution,
    GapManager,
    ResolutionStrategy,
    ResolutionStatus,
    convert_gaps_to_objects,
    convert_gaps_to_strings,
    create_gap,
)


class TestGapTypeEnum:
    """Tests for GapType enum completeness."""
    
    def test_all_20_types_defined(self):
        """Verify all 20 GAP_TYPES are defined in the enum."""
        expected_types = [
            "ambiguous_request",
            "scope_not_found",
            "domain_not_injected",
            "resource_exhausted",
            "budget_exceeded",
            "rollback_triggered",
            "abi_locked_violation",
            "dependency_cycle",
            "recursion_limit_reached",
            "unsafe_execution_blocked",
            "llm_query_failed",
            "validation_failure",
            "binary_file",
            "encoding_unresolvable",
            "tool_not_found",
            "policy_violation",
            "state_drift",
            "checkpoint_corrupted",
            "consensus_failure",
            "human_gate_timeout",
        ]
        
        actual_types = [t.value for t in GapType]
        
        assert len(actual_types) == 20, f"Expected 20 gap types, got {len(actual_types)}"
        
        for expected in expected_types:
            assert expected in actual_types, f"Missing gap type: {expected}"
    
    def test_gap_type_values_are_lowercase_underscore(self):
        """Verify all gap type values follow naming convention."""
        for gap_type in GapType:
            value = gap_type.value
            assert value == value.lower(), f"{value} should be lowercase"
            assert " " not in value, f"{value} should use underscores, not spaces"
    
    def test_gap_type_lookup_by_value(self):
        """Verify gap types can be looked up by string value."""
        assert GapType("abi_locked_violation") == GapType.ABI_LOCKED_VIOLATION
        assert GapType("budget_exceeded") == GapType.BUDGET_EXCEEDED
        assert GapType("llm_query_failed") == GapType.LLM_QUERY_FAILED


class TestResolutionStrategy:
    """Tests for ResolutionStrategy enum."""
    
    def test_all_strategies_defined(self):
        """Verify all expected resolution strategies are defined."""
        expected_strategies = [
            "simultaneous_update",
            "inject_or_fallback",
            "checkpoint_and_pause",
            "restore_and_report",
            "halt_and_report",
            "sandbox_or_human_gate",
            "retry_with_backoff",
            "skip_with_log",
            "manual_intervention",
            "escalate",
            "replan",
            "abort",
        ]
        
        actual_strategies = [s.value for s in ResolutionStrategy]
        
        for expected in expected_strategies:
            assert expected in actual_strategies, f"Missing strategy: {expected}"


class TestResolutionStatus:
    """Tests for ResolutionStatus enum."""
    
    def test_all_statuses_defined(self):
        """Verify all resolution statuses are defined."""
        expected_statuses = ["open", "retrying", "escalated", "resolved"]
        
        actual_statuses = [s.value for s in ResolutionStatus]
        
        assert actual_statuses == expected_statuses


class TestGapHandler:
    """Tests for GapHandler dataclass."""
    
    def test_create_handler(self):
        """Test creating a gap handler."""
        handler = GapHandler(
            gap_type=GapType.LLM_QUERY_FAILED,
            resolution_strategy=ResolutionStrategy.RETRY_WITH_BACKOFF,
            max_retries=5,
            backoff_ms=200,
            description="Test handler"
        )
        
        assert handler.gap_type == GapType.LLM_QUERY_FAILED
        assert handler.resolution_strategy == ResolutionStrategy.RETRY_WITH_BACKOFF
        assert handler.max_retries == 5
        assert handler.backoff_ms == 200
        assert handler.description == "Test handler"
    
    def test_handler_defaults(self):
        """Test default values for handler."""
        handler = GapHandler(
            gap_type=GapType.BINARY_FILE,
            resolution_strategy=ResolutionStrategy.SKIP_WITH_LOG
        )
        
        assert handler.max_retries == 3
        assert handler.backoff_ms == 100
        assert handler.handler_func is None
        assert handler.escalation_target is None


class TestGapResolution:
    """Tests for GapResolution dataclass."""
    
    def test_create_resolution(self):
        """Test creating a gap resolution."""
        resolution = GapResolution(
            gap_id="GAP-12345678",
            gap_type=GapType.BUDGET_EXCEEDED,
            status=ResolutionStatus.RESOLVED,
            attempts=2,
            resolution_notes="Resolved by increasing budget"
        )
        
        assert resolution.gap_id == "GAP-12345678"
        assert resolution.gap_type == GapType.BUDGET_EXCEEDED
        assert resolution.status == ResolutionStatus.RESOLVED
        assert resolution.attempts == 2
    
    def test_resolution_to_dict(self):
        """Test resolution serialization."""
        resolution = GapResolution(
            gap_id="GAP-ABCDEF",
            gap_type=GapType.LLM_QUERY_FAILED,
            status=ResolutionStatus.RETRYING,
            attempts=1,
            strategy_used=ResolutionStrategy.RETRY_WITH_BACKOFF
        )
        
        data = resolution.to_dict()
        
        assert data["gap_id"] == "GAP-ABCDEF"
        assert data["gap_type"] == "llm_query_failed"
        assert data["status"] == "retrying"
        assert data["strategy_used"] == "retry_with_backoff"


class TestGap:
    """Tests for enhanced Gap dataclass."""
    
    def test_gap_with_type(self):
        """Test creating a gap with explicit type."""
        gap = Gap(
            id="GAP-TEST",
            reason="Budget limit exceeded",
            severity=GapSeverity.SEV_2,
            gap_type=GapType.BUDGET_EXCEEDED
        )
        
        assert gap.gap_type == GapType.BUDGET_EXCEEDED
        assert gap.severity == GapSeverity.SEV_2
    
    def test_gap_type_inference(self):
        """Test automatic gap type inference from reason."""
        gap = Gap(
            id="",
            reason="LLM query failed due to timeout"
        )
        
        assert gap.gap_type == GapType.LLM_QUERY_FAILED
    
    def test_gap_type_inference_abi_locked(self):
        """Test ABI locked violation inference."""
        gap = Gap(id="", reason="ABI locked violation detected")
        assert gap.gap_type == GapType.ABI_LOCKED_VIOLATION
    
    def test_gap_type_inference_binary_file(self):
        """Test binary file inference."""
        gap = Gap(id="", reason="Cannot process binary file")
        assert gap.gap_type == GapType.BINARY_FILE
    
    def test_gap_to_dict_includes_type(self):
        """Test serialization includes gap type."""
        gap = Gap(
            id="GAP-TEST",
            reason="Test gap",
            gap_type=GapType.VALIDATION_FAILURE
        )
        
        data = gap.to_dict()
        
        assert "gap_type" in data
        assert data["gap_type"] == "validation_failure"
    
    def test_gap_from_dict_with_type(self):
        """Test deserialization with gap type."""
        data = {
            "id": "GAP-TEST",
            "reason": "Test",
            "gap_type": "policy_violation"
        }
        
        gap = Gap.from_dict(data)
        
        assert gap.gap_type == GapType.POLICY_VIOLATION
    
    def test_gap_to_string_includes_type(self):
        """Test string format includes gap type."""
        gap = Gap(
            id="GAP-TEST",
            reason="Budget exceeded",
            severity=GapSeverity.SEV_2,
            gap_type=GapType.BUDGET_EXCEEDED
        )
        
        result = gap.to_string()
        
        assert "[budget_exceeded]" in result
        assert "Budget exceeded" in result


class TestGapManager:
    """Tests for GapManager class."""
    
    def test_all_20_types_have_handlers(self):
        """Verify all 20 gap types have default handlers."""
        manager = GapManager()
        
        # All 20 types should have handlers
        all_types = list(GapType)
        for gap_type in all_types:
            assert manager.has_handler(gap_type), f"Missing handler for {gap_type.value}"
    
    def test_validate_completeness(self):
        """Test completeness validation method."""
        result = GapManager.validate_completeness()
        
        assert result["is_complete"] is True
        assert result["total_gap_types"] == 20
        assert result["handlers_defined"] == 20
        assert result["missing_handlers"] == []
    
    def test_get_all_gap_types(self):
        """Test getting all gap types."""
        all_types = GapManager.get_all_gap_types()
        
        assert len(all_types) == 20
        assert GapType.LLM_QUERY_FAILED in all_types
        assert GapType.BINARY_FILE in all_types
    
    def test_handle_gap_with_handler(self):
        """Test handling a gap with registered handler."""
        manager = GapManager()
        
        gap = Gap(
            id="GAP-HANDLE-TEST",
            reason="Test gap",
            gap_type=GapType.BINARY_FILE
        )
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.status == ResolutionStatus.RESOLVED
        assert resolution.gap_id == "GAP-HANDLE-TEST"
        assert resolution.strategy_used == ResolutionStrategy.SKIP_WITH_LOG
    
    def test_handle_gap_escalation(self):
        """Test handling a gap that escalates."""
        manager = GapManager()
        
        gap = Gap(
            id="GAP-ESCALATE-TEST",
            reason="Ambiguous request",
            gap_type=GapType.AMBIGUOUS_REQUEST
        )
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.status == ResolutionStatus.ESCALATED
        assert resolution.strategy_used == ResolutionStrategy.ESCALATE
    
    def test_get_resolution_status(self):
        """Test getting resolution status."""
        manager = GapManager()
        
        gap = Gap(
            id="GAP-STATUS-TEST",
            reason="Test",
            gap_type=GapType.VALIDATION_FAILURE
        )
        
        manager.handle_gap(gap)
        
        status = manager.get_resolution_status("GAP-STATUS-TEST")
        
        assert status is not None
        assert status.gap_id == "GAP-STATUS-TEST"
    
    def test_register_custom_handler(self):
        """Test registering custom handler."""
        manager = GapManager()
        
        custom_handler = GapHandler(
            gap_type=GapType.LLM_QUERY_FAILED,
            resolution_strategy=ResolutionStrategy.ABORT,
            description="Custom abort handler"
        )
        
        manager.register_handler(GapType.LLM_QUERY_FAILED, custom_handler)
        
        handler = manager.get_handler(GapType.LLM_QUERY_FAILED)
        
        assert handler.resolution_strategy == ResolutionStrategy.ABORT
        assert handler.description == "Custom abort handler"
    
    def test_custom_handler_function(self):
        """Test custom handler function execution."""
        manager = GapManager()
        
        called = []
        
        def custom_func(gap):
            called.append(gap.id)
        
        custom_handler = GapHandler(
            gap_type=GapType.TOOL_NOT_FOUND,
            resolution_strategy=ResolutionStrategy.INJECT_OR_FALLBACK,
            handler_func=custom_func
        )
        
        manager.register_handler(GapType.TOOL_NOT_FOUND, custom_handler)
        
        gap = Gap(
            id="GAP-FUNC-TEST",
            reason="Tool missing",
            gap_type=GapType.TOOL_NOT_FOUND
        )
        
        manager.handle_gap(gap)
        
        assert "GAP-FUNC-TEST" in called
    
    def test_get_all_handlers(self):
        """Test getting all handlers."""
        manager = GapManager()
        
        handlers = manager.get_all_handlers()
        
        assert len(handlers) == 20
        assert GapType.BINARY_FILE in handlers
        assert GapType.LLM_QUERY_FAILED in handlers
    
    def test_get_all_resolutions(self):
        """Test getting all resolution records."""
        manager = GapManager()
        
        gap1 = Gap(id="GAP-1", reason="Test 1", gap_type=GapType.BINARY_FILE)
        gap2 = Gap(id="GAP-2", reason="Test 2", gap_type=GapType.VALIDATION_FAILURE)
        
        manager.handle_gap(gap1)
        manager.handle_gap(gap2)
        
        resolutions = manager.get_all_resolutions()
        
        assert len(resolutions) == 2
        assert "GAP-1" in resolutions
        assert "GAP-2" in resolutions
    
    def test_config_initialization(self):
        """Test initialization with config."""
        config = {
            "custom_handlers": {
                "llm_query_failed": {
                    "strategy": "abort",
                    "max_retries": 1,
                    "description": "Config override"
                }
            }
        }
        
        manager = GapManager(config=config)
        
        handler = manager.get_handler(GapType.LLM_QUERY_FAILED)
        
        assert handler.resolution_strategy == ResolutionStrategy.ABORT
        assert handler.max_retries == 1


class TestGapManagerResolutionStrategies:
    """Tests for specific resolution strategies."""
    
    def test_skip_with_log_strategy(self):
        """Test skip with log strategy."""
        manager = GapManager()
        
        gap = Gap(
            id="GAP-SKIP",
            reason="Binary file",
            gap_type=GapType.BINARY_FILE
        )
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.status == ResolutionStatus.RESOLVED
        assert "Skipped" in resolution.resolution_notes
    
    def test_halt_and_report_strategy(self):
        """Test halt and report strategy."""
        manager = GapManager()
        
        gap = Gap(
            id="GAP-HALT",
            reason="Recursion limit reached",
            gap_type=GapType.RECURSION_LIMIT_REACHED
        )
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.status == ResolutionStatus.RESOLVED
        assert "Halted" in resolution.resolution_notes
    
    def test_checkpoint_and_pause_strategy(self):
        """Test checkpoint and pause strategy."""
        manager = GapManager()
        
        gap = Gap(
            id="GAP-CHECKPOINT",
            reason="Budget exceeded",
            gap_type=GapType.BUDGET_EXCEEDED
        )
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.status == ResolutionStatus.RESOLVED
        assert "Checkpoint" in resolution.resolution_notes
    
    def test_abort_strategy(self):
        """Test abort strategy."""
        manager = GapManager()
        
        gap = Gap(
            id="GAP-ABORT",
            reason="Checkpoint corrupted",
            gap_type=GapType.CHECKPOINT_CORRUPTED
        )
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.status == ResolutionStatus.RESOLVED
        assert "aborted" in resolution.resolution_notes.lower()
    
    def test_restore_and_report_strategy(self):
        """Test restore and report strategy."""
        manager = GapManager()
        
        gap = Gap(
            id="GAP-RESTORE",
            reason="Rollback triggered",
            gap_type=GapType.ROLLBACK_TRIGGERED
        )
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.status == ResolutionStatus.RESOLVED
        assert "restored" in resolution.resolution_notes.lower()


class TestGapManagerRetryLogic:
    """Tests for retry with backoff logic."""
    
    def test_retry_with_backoff_success_on_retry(self):
        """Test retry succeeds on second attempt."""
        manager = GapManager()
        
        attempts = []
        
        def flaky_handler(gap):
            attempts.append(len(attempts))
            if len(attempts) < 2:
                raise Exception("Temporary failure")
        
        custom_handler = GapHandler(
            gap_type=GapType.LLM_QUERY_FAILED,
            resolution_strategy=ResolutionStrategy.RETRY_WITH_BACKOFF,
            handler_func=flaky_handler,
            max_retries=3,
            backoff_ms=10  # Fast for testing
        )
        
        manager.register_handler(GapType.LLM_QUERY_FAILED, custom_handler)
        
        gap = Gap(
            id="GAP-RETRY",
            reason="LLM query failed",
            gap_type=GapType.LLM_QUERY_FAILED
        )
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.status == ResolutionStatus.RESOLVED
        assert resolution.attempts == 2
    
    def test_retry_exhausted(self):
        """Test retry exhausts all attempts."""
        manager = GapManager()
        
        def always_fail(gap):
            raise Exception("Permanent failure")
        
        custom_handler = GapHandler(
            gap_type=GapType.LLM_QUERY_FAILED,
            resolution_strategy=ResolutionStrategy.RETRY_WITH_BACKOFF,
            handler_func=always_fail,
            max_retries=2,
            backoff_ms=10
        )
        
        manager.register_handler(GapType.LLM_QUERY_FAILED, custom_handler)
        
        gap = Gap(
            id="GAP-FAIL",
            reason="LLM query failed",
            gap_type=GapType.LLM_QUERY_FAILED
        )
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.status == ResolutionStatus.ESCALATED
        assert resolution.attempts == 2
        assert "Failed after 2 retries" in resolution.resolution_notes


class TestGapConversion:
    """Tests for gap conversion functions."""
    
    def test_convert_gaps_to_objects(self):
        """Test converting gap strings to objects."""
        strings = [
            "[gap: Budget exceeded (SEV-2)]",
            "[gap: Binary file (SEV-4)]"
        ]
        
        gaps = convert_gaps_to_objects(strings)
        
        assert len(gaps) == 2
        assert gaps[0].reason == "Budget exceeded"
        assert gaps[1].reason == "Binary file"
    
    def test_convert_gaps_to_strings(self):
        """Test converting gap objects to strings."""
        gaps = [
            Gap(id="GAP-1", reason="Test 1", gap_type=GapType.BINARY_FILE),
            Gap(id="GAP-2", reason="Test 2", gap_type=GapType.LLM_QUERY_FAILED)
        ]
        
        strings = convert_gaps_to_strings(gaps)
        
        assert len(strings) == 2
        assert "Test 1" in strings[0]
        assert "Test 2" in strings[1]


class TestCreateGap:
    """Tests for create_gap convenience function."""
    
    def test_create_gap_basic(self):
        """Test basic gap creation."""
        gap = create_gap("Test reason")
        
        assert gap.reason == "Test reason"
        assert gap.severity == GapSeverity.SEV_4
        assert gap.id != ""  # Auto-generated
    
    def test_create_gap_with_type(self):
        """Test gap creation with explicit type."""
        gap = create_gap(
            "Budget exceeded",
            gap_type=GapType.BUDGET_EXCEEDED,
            severity=GapSeverity.SEV_2
        )
        
        assert gap.reason == "Budget exceeded"
        assert gap.gap_type == GapType.BUDGET_EXCEEDED
        assert gap.severity == GapSeverity.SEV_2
    
    def test_create_gap_with_context(self):
        """Test gap creation with additional fields."""
        gap = create_gap(
            "Test",
            gap_type=GapType.VALIDATION_FAILURE,
            context="In validation step",
            suggested_action="Check input format"
        )
        
        assert gap.context == "In validation step"
        assert gap.suggested_action == "Check input format"


class TestGapManagerUnknownGap:
    """Tests for handling unknown gap types."""
    
    def test_handle_unknown_gap_type(self):
        """Test handling a gap with None type."""
        manager = GapManager()
        
        # Create gap without inferrable type
        gap = Gap(
            id="GAP-UNKNOWN",
            reason="Some completely unknown issue xyz123"
        )
        gap.gap_type = None  # Force unknown
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.status == ResolutionStatus.ESCALATED
        assert "Unknown gap type" in resolution.resolution_notes


class TestGapResolutionTracking:
    """Tests for resolution tracking and metrics."""
    
    def test_resolution_time_tracked(self):
        """Test that resolution time is tracked."""
        manager = GapManager()
        
        gap = Gap(
            id="GAP-TIME",
            reason="Test",
            gap_type=GapType.BINARY_FILE
        )
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.resolution_time_ms >= 0
    
    def test_resolved_at_set_on_success(self):
        """Test resolved_at is set on successful resolution."""
        manager = GapManager()
        
        gap = Gap(
            id="GAP-DATE",
            reason="Test",
            gap_type=GapType.BINARY_FILE
        )
        
        resolution = manager.handle_gap(gap)
        
        assert resolution.resolved_at is not None
        # Should be valid ISO format
        datetime.fromisoformat(resolution.resolved_at)


class TestGapHandlerDescriptions:
    """Tests for gap handler descriptions."""
    
    def test_all_handlers_have_descriptions(self):
        """Verify all default handlers have descriptions."""
        for gap_type, handler in GapManager.DEFAULT_HANDLERS.items():
            assert handler.description, f"Handler for {gap_type.value} missing description"
    
    def test_handler_descriptions_are_meaningful(self):
        """Verify descriptions are meaningful (not empty)."""
        for gap_type, handler in GapManager.DEFAULT_HANDLERS.items():
            assert len(handler.description) > 10, \
                f"Description for {gap_type.value} too short"


class TestGapManagerLogging:
    """Tests for logging behavior."""
    
    @patch('src.state.gap.logging.getLogger')
    def test_logs_on_handle(self, mock_get_logger):
        """Test that handling a gap produces logs."""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        manager = GapManager()
        
        gap = Gap(
            id="GAP-LOG",
            reason="Test",
            gap_type=GapType.BINARY_FILE
        )
        
        manager.handle_gap(gap)
        
        # Verify info was called
        assert mock_logger.info.called


# Integration tests
class TestGapManagerIntegration:
    """Integration tests for GapManager."""
    
    def test_full_lifecycle(self):
        """Test complete gap lifecycle."""
        manager = GapManager()
        
        # Create gap
        gap = create_gap(
            "LLM query failed due to timeout",
            gap_type=GapType.LLM_QUERY_FAILED,
            severity=GapSeverity.SEV_2
        )
        
        # Handle gap
        resolution = manager.handle_gap(gap)
        
        # Verify tracking
        assert resolution.gap_id == gap.id
        
        # Retrieve status
        retrieved = manager.get_resolution_status(gap.id)
        assert retrieved is not None
        assert retrieved.gap_type == GapType.LLM_QUERY_FAILED
    
    def test_multiple_gaps_tracking(self):
        """Test tracking multiple gaps."""
        manager = GapManager()
        
        gap_types = [
            GapType.BINARY_FILE,
            GapType.LLM_QUERY_FAILED,
            GapType.BUDGET_EXCEEDED,
            GapType.VALIDATION_FAILURE,
        ]
        
        for i, gap_type in enumerate(gap_types):
            gap = Gap(
                id=f"GAP-{i}",
                reason=f"Test gap {i}",
                gap_type=gap_type
            )
            manager.handle_gap(gap)
        
        resolutions = manager.get_all_resolutions()
        
        assert len(resolutions) == 4
