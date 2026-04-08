"""
Tests for Invariant Runtime Enforcement (ITEM-PROT-002).

Tests the InvariantEnforcer that validates all 10 INVARIANTS_GLOBAL
at runtime with configurable enforcement levels.

Key tests:
- test_all_10_invariants_checked: All 10 invariants validated at runtime
- test_forbidden_inference_detected: Observable-only violations detected
- test_completeness_verification
- test_enforcement_levels
"""

import pytest
from dataclasses import dataclass
from typing import Dict, Any, List, Set
from unittest.mock import Mock, patch

from src.validation.invariant_enforcer import (
    InvariantEnforcer,
    InvariantViolation,
    InvariantCheckResult,
    SessionSnapshot,
    EnforcementLevel,
    InvariantType,
    ViolationSeverity,
    create_invariant_enforcer,
    FORBIDDEN_INFERENCE_MARKERS,
)


# =============================================================================
# Test Fixtures
# =============================================================================

def get_basic_context() -> Dict[str, Any]:
    """Get a basic context dictionary for testing."""
    return {
        "output": "The user clicked the button and navigated to the homepage.",
        "domain": "test_domain",
        "sources": ["ssot_test.yaml"],
        "evidence": ["User clicked button", "User navigated to homepage"],
        "output_claims": ["User clicked the button", "User navigated to homepage"],
        "extracted_count": 10,
        "classified_count": 8,
        "exclusions_count": 2,
        "forbidden_conditions": [],
        "code_blocks": [],
        "declared_scope": {"read", "write"},
        "actual_scope": {"read", "write"},
    }


def get_session_snapshot(
    session_id: str = "test-session",
    state_hash: str = "abc123",
    checkpoint_hash: str = "abc123",
) -> SessionSnapshot:
    """Create a session snapshot for testing."""
    return SessionSnapshot(
        session_id=session_id,
        state_hash=state_hash,
        checkpoint_hash=checkpoint_hash,
        phase=0,
        gates_passed=[],
    )


# =============================================================================
# Tests for All 10 Invariants
# =============================================================================

class TestAll10InvariantsChecked:
    """
    Test that all 10 invariants are properly checked.
    
    CRITERION: All 10 INVARIANTS_GLOBAL validated at runtime.
    """

    def test_all_invariants_have_types(self):
        """Test that all 10 invariant types are defined."""
        expected_types = [
            "INVAR-01_NO_FABRICATION",
            "INVAR-02_SSOT_PER_DOMAIN",
            "INVAR-03_ZERO_DRIFT",
            "INVAR-04_IDEMPOTENT_PATCH",
            "INVAR-05_ASSERT_ABSENCE",
            "INVAR-06_OBSERVABLE_ONLY",
            "INVAR-07_CODE_IS_EVIDENCE",
            "INVAR-08_SCOPE_LOCALITY",
            "INVAR-09_COMPLETENESS",
            "INVAR-10_VALIDATION_HALT",
        ]
        
        actual_types = [t.value for t in InvariantType]
        
        for expected in expected_types:
            assert expected in actual_types, f"Missing invariant type: {expected}"

    def test_check_all_runs_10_checks(self):
        """Test that check_all runs checks for all 10 invariants."""
        enforcer = InvariantEnforcer()
        
        # Create context that should pass all checks
        context = get_basic_context()
        
        result = enforcer.check_all(context)
        
        # Should have run 10 checks
        assert result.checks_run == 10, f"Expected 10 checks, got {result.checks_run}"

    def test_all_invariants_can_detect_violations(self):
        """Test that each invariant can detect violations."""
        enforcer = InvariantEnforcer()
        
        # Test INVAR-01: No Fabrication
        violation = enforcer.check_no_fabrication(
            output="This is completely made up information.",
            evidence=["Unrelated evidence"],
            output_claims=["This is completely made up information that has no support"],
        )
        assert violation is not None, "INVAR-01 should detect fabrication"
        assert violation.invariant_type == InvariantType.NO_FABRICATION

        # Test INVAR-02: SSOT Per Domain
        violation = enforcer.check_ssot(
            domain="test",
            sources=["ssot_1.yaml", "ssot_2.yaml"],
        )
        assert violation is not None, "INVAR-02 should detect multiple SSOT files"
        assert violation.invariant_type == InvariantType.SSOT_PER_DOMAIN

        # Test INVAR-03: Zero Drift
        session = get_session_snapshot(state_hash="abc", checkpoint_hash="xyz")
        violation = enforcer.check_zero_drift(session)
        assert violation is not None, "INVAR-03 should detect drift"
        assert violation.invariant_type == InvariantType.ZERO_DRIFT

        # Test INVAR-04: Idempotent Patch
        # First run stores the hash
        enforcer.check_idempotent_patch("before content", "after content A", "patch-1")
        # Second run with same before but different after should fail
        violation = enforcer.check_idempotent_patch("before content", "after content B", "patch-1")
        assert violation is not None, "INVAR-04 should detect non-idempotent patch"
        assert violation.invariant_type == InvariantType.IDEMPOTENT_PATCH

        # Test INVAR-05: Assert Absence
        violation = enforcer.check_assert_absence(
            output="This contains forbidden content",
            forbidden_conditions=["forbidden"],
        )
        assert violation is not None, "INVAR-05 should detect forbidden condition"
        assert violation.invariant_type == InvariantType.ASSERT_ABSENCE

        # Test INVAR-06: Observable Only
        violation = enforcer.check_observable_only(
            output="The user believes this will work."
        )
        assert violation is not None, "INVAR-06 should detect forbidden inference"
        assert violation.invariant_type == InvariantType.OBSERVABLE_ONLY

        # Test INVAR-07: Code Is Evidence
        violation = enforcer.check_code_is_evidence(
            code_blocks=["def foo():\n    pass"],
            output="Here's some code",
        )
        assert violation is not None, "INVAR-07 should detect placeholder code"
        assert violation.invariant_type == InvariantType.CODE_IS_EVIDENCE

        # Test INVAR-08: Scope Locality
        violation = enforcer.check_scope_locality(
            declared_scope={"read"},
            actual_scope={"read", "write", "delete"},
        )
        assert violation is not None, "INVAR-08 should detect scope violation"
        assert violation.invariant_type == InvariantType.SCOPE_LOCALITY

        # Test INVAR-09: Completeness
        violation = enforcer.check_completeness(
            extracted=10,
            classified=5,
            exclusions=2,
        )
        assert violation is not None, "INVAR-09 should detect completeness violation"
        assert violation.invariant_type == InvariantType.COMPLETENESS

        # Test INVAR-10: Validation Halt
        violation = enforcer.check_validation_halt(
            validation_result={"passed": False, "phase": 2},
            current_phase=3,
        )
        assert violation is not None, "INVAR-10 should detect continued execution after failure"
        assert violation.invariant_type == InvariantType.VALIDATION_HALT


# =============================================================================
# Tests for INVAR-06: Observable Only
# =============================================================================

class TestForbiddenInferenceDetection:
    """
    Tests for INVAR-06_OBSERVABLE_ONLY: Forbidden inference detection.
    
    CRITERION: Observable-only violations detected with [gap:inference_violation]
    """

    def test_forbidden_markers_defined(self):
        """Test that forbidden inference markers are defined."""
        assert len(FORBIDDEN_INFERENCE_MARKERS) > 0
        assert "motive" in FORBIDDEN_INFERENCE_MARKERS
        assert "emotion" in FORBIDDEN_INFERENCE_MARKERS
        assert "intent" in FORBIDDEN_INFERENCE_MARKERS
        assert "belief" in FORBIDDEN_INFERENCE_MARKERS

    def test_detects_belief_inference(self):
        """Test detection of belief inference."""
        enforcer = InvariantEnforcer()
        
        violation = enforcer.check_observable_only(
            output="The user believes this feature is useful."
        )
        
        assert violation is not None
        assert violation.invariant_type == InvariantType.OBSERVABLE_ONLY
        assert "[gap:inference_violation]" == violation.gap_tag

    def test_detects_emotion_inference(self):
        """Test detection of emotion inference."""
        enforcer = InvariantEnforcer()
        
        violation = enforcer.check_observable_only(
            output="The user feels frustrated with the slow response."
        )
        
        assert violation is not None
        assert "feels" in violation.context.get("forbidden_markers", [])

    def test_detects_intent_inference(self):
        """Test detection of intent inference."""
        enforcer = InvariantEnforcer()
        
        violation = enforcer.check_observable_only(
            output="The user intends to purchase the product."
        )
        
        assert violation is not None
        assert "intends" in violation.context.get("forbidden_markers", [])

    def test_detects_motive_inference(self):
        """Test detection of motive inference."""
        enforcer = InvariantEnforcer()
        
        violation = enforcer.check_observable_only(
            output="The user's motive was to save money."
        )
        
        assert violation is not None
        assert "motive" in violation.context.get("forbidden_markers", [])

    def test_detects_multiple_inferences(self):
        """Test detection of multiple inference markers."""
        enforcer = InvariantEnforcer()
        
        violation = enforcer.check_observable_only(
            output="The user believes this will work and wants to proceed."
        )
        
        assert violation is not None
        markers = violation.context.get("forbidden_markers", [])
        assert "believes" in markers
        assert "wants" in markers

    def test_observable_output_passes(self):
        """Test that observable-only output passes."""
        enforcer = InvariantEnforcer()
        
        # Output with only observable behaviors
        violation = enforcer.check_observable_only(
            output="The user clicked the button, scrolled down, and filled out the form."
        )
        
        assert violation is None

    def test_case_insensitive_detection(self):
        """Test that detection is case insensitive."""
        enforcer = InvariantEnforcer()
        
        violation = enforcer.check_observable_only(
            output="The User BELIEVES this is correct."
        )
        
        assert violation is not None

    def test_inference_violation_has_evidence(self):
        """Test that inference violation includes evidence context."""
        enforcer = InvariantEnforcer()
        
        violation = enforcer.check_observable_only(
            output="Based on the data, the user believes the system is reliable."
        )
        
        assert violation is not None
        assert violation.evidence is not None
        assert "believes" in violation.evidence.lower()


# =============================================================================
# Tests for INVAR-09: Completeness
# =============================================================================

class TestCompletenessVerification:
    """
    Tests for INVAR-09_COMPLETENESS: Σ(extracted) - exclusions == Σ(classified)
    
    CRITERION: Completeness equation verified at runtime.
    """

    def test_completeness_passes_when_equal(self):
        """Test that completeness passes when equation is satisfied."""
        enforcer = InvariantEnforcer()
        
        # 10 - 2 = 8 classified
        violation = enforcer.check_completeness(
            extracted=10,
            classified=8,
            exclusions=2,
        )
        
        assert violation is None

    def test_completeness_fails_when_missing_classification(self):
        """Test that completeness fails when items are not classified."""
        enforcer = InvariantEnforcer()
        
        # 10 - 2 = 8, but only 5 classified
        violation = enforcer.check_completeness(
            extracted=10,
            classified=5,
            exclusions=2,
        )
        
        assert violation is not None
        assert violation.invariant_type == InvariantType.COMPLETENESS
        assert "[gap:completeness_violation]" == violation.gap_tag

    def test_completeness_fails_when_over_classified(self):
        """Test that completeness fails when more classified than extracted."""
        enforcer = InvariantEnforcer()
        
        # 10 - 2 = 8, but 12 classified (impossible)
        violation = enforcer.check_completeness(
            extracted=10,
            classified=12,
            exclusions=2,
        )
        
        assert violation is not None

    def test_completeness_with_zero_exclusions(self):
        """Test completeness with no exclusions."""
        enforcer = InvariantEnforcer()
        
        # 10 - 0 = 10 classified
        violation = enforcer.check_completeness(
            extracted=10,
            classified=10,
            exclusions=0,
        )
        
        assert violation is None

    def test_completeness_with_zero_extracted(self):
        """Test that zero extracted items returns None (no check needed)."""
        enforcer = InvariantEnforcer()
        
        violation = enforcer.check_completeness(
            extracted=0,
            classified=0,
            exclusions=0,
        )
        
        assert violation is None

    def test_completeness_message_shows_equation(self):
        """Test that violation message shows the equation."""
        enforcer = InvariantEnforcer()
        
        violation = enforcer.check_completeness(
            extracted=100,
            classified=50,
            exclusions=10,
        )
        
        assert violation is not None
        assert "100" in violation.message
        assert "50" in violation.message
        assert "10" in violation.message


# =============================================================================
# Tests for Enforcement Levels
# =============================================================================

class TestEnforcementLevels:
    """
    Tests for different enforcement levels.
    
    CRITERION: Enforcement levels control blocking behavior.
    """

    def test_permissive_never_blocks(self):
        """Test that PERMISSIVE level never blocks execution."""
        enforcer = InvariantEnforcer(level=EnforcementLevel.PERMISSIVE)
        
        context = {
            "output": "The user believes this will work.",
            "extracted_count": 10,
            "classified_count": 5,  # Incomplete
            "exclusions_count": 2,
        }
        
        result = enforcer.check_all(context)
        
        # Should have violations
        assert result.has_violations
        # But should pass (permissive doesn't block)
        assert result.passed

    def test_standard_blocks_on_critical(self):
        """Test that STANDARD level blocks on critical violations."""
        enforcer = InvariantEnforcer(level=EnforcementLevel.STANDARD)
        
        context = {
            "output": "This is completely fabricated content with no evidence.",
            "evidence": ["Unrelated"],
            "output_claims": ["This is completely fabricated content with no evidence at all"],
            "extracted_count": 10,
            "classified_count": 10,
            "exclusions_count": 0,
        }
        
        result = enforcer.check_all(context)
        
        assert result.has_violations
        # NO_FABRICATION is CRITICAL, should block
        assert not result.passed

    def test_strict_blocks_on_any_violation(self):
        """Test that STRICT level blocks on any violation."""
        enforcer = InvariantEnforcer(level=EnforcementLevel.STRICT)
        
        context = {
            "output": "The user feels happy about this.",
            "extracted_count": 10,
            "classified_count": 10,
            "exclusions_count": 0,
        }
        
        result = enforcer.check_all(context)
        
        assert result.has_violations
        # STRICT should block on any violation
        assert not result.passed

    def test_paranoid_provides_audit_trail(self):
        """Test that PARANOID level provides comprehensive audit trail."""
        enforcer = InvariantEnforcer(level=EnforcementLevel.PARANOID)
        
        context = {
            "output": "The user believes this.",
            "extracted_count": 10,
            "classified_count": 10,
            "exclusions_count": 0,
        }
        
        result = enforcer.check_all(context)
        
        assert result.has_violations
        assert not result.passed
        # Check metadata is populated
        assert "enabled_invariants" in result.metadata

    def test_enforcement_level_in_result(self):
        """Test that enforcement level is included in result."""
        enforcer = InvariantEnforcer(level=EnforcementLevel.STRICT)
        
        result = enforcer.check_all(get_basic_context())
        
        assert result.enforcement_level == EnforcementLevel.STRICT


# =============================================================================
# Tests for InvariantViolation and InvariantCheckResult
# =============================================================================

class TestViolationDataclasses:
    """Tests for InvariantViolation and InvariantCheckResult dataclasses."""

    def test_violation_to_dict(self):
        """Test converting violation to dictionary."""
        violation = InvariantViolation(
            invariant_type=InvariantType.OBSERVABLE_ONLY,
            severity=ViolationSeverity.ERROR,
            message="Test violation",
            evidence="Test evidence",
            gap_tag="[gap:test]",
        )
        
        data = violation.to_dict()
        
        assert data["invariant_type"] == "INVAR-06_OBSERVABLE_ONLY"
        assert data["severity"] == "error"
        assert data["message"] == "Test violation"
        assert data["evidence"] == "Test evidence"
        assert data["gap_tag"] == "[gap:test]"
        assert "timestamp" in data

    def test_violation_is_blocking(self):
        """Test is_blocking method."""
        info = InvariantViolation(
            invariant_type=InvariantType.OBSERVABLE_ONLY,
            severity=ViolationSeverity.INFO,
            message="Info",
        )
        assert not info.is_blocking()
        
        warning = InvariantViolation(
            invariant_type=InvariantType.OBSERVABLE_ONLY,
            severity=ViolationSeverity.WARNING,
            message="Warning",
        )
        assert not warning.is_blocking()
        
        error = InvariantViolation(
            invariant_type=InvariantType.OBSERVABLE_ONLY,
            severity=ViolationSeverity.ERROR,
            message="Error",
        )
        assert error.is_blocking()
        
        critical = InvariantViolation(
            invariant_type=InvariantType.OBSERVABLE_ONLY,
            severity=ViolationSeverity.CRITICAL,
            message="Critical",
        )
        assert critical.is_blocking()

    def test_result_to_dict(self):
        """Test converting result to dictionary."""
        result = InvariantCheckResult(
            passed=True,
            violations=[],
            checks_run=10,
            enforcement_level=EnforcementLevel.STANDARD,
            duration_ms=123.45,
        )
        
        data = result.to_dict()
        
        assert data["passed"] is True
        assert data["violations"] == []
        assert data["checks_run"] == 10
        assert data["enforcement_level"] == "standard"
        assert data["duration_ms"] == 123.45

    def test_result_blocking_violations(self):
        """Test getting blocking violations from result."""
        violations = [
            InvariantViolation(
                invariant_type=InvariantType.OBSERVABLE_ONLY,
                severity=ViolationSeverity.WARNING,
                message="Warning",
            ),
            InvariantViolation(
                invariant_type=InvariantType.NO_FABRICATION,
                severity=ViolationSeverity.CRITICAL,
                message="Critical",
            ),
        ]
        
        result = InvariantCheckResult(
            passed=False,
            violations=violations,
        )
        
        blocking = result.blocking_violations
        assert len(blocking) == 1
        assert blocking[0].severity == ViolationSeverity.CRITICAL

    def test_result_get_violations_by_type(self):
        """Test filtering violations by type."""
        violations = [
            InvariantViolation(
                invariant_type=InvariantType.OBSERVABLE_ONLY,
                severity=ViolationSeverity.WARNING,
                message="Violation 1",
            ),
            InvariantViolation(
                invariant_type=InvariantType.OBSERVABLE_ONLY,
                severity=ViolationSeverity.ERROR,
                message="Violation 2",
            ),
            InvariantViolation(
                invariant_type=InvariantType.COMPLETENESS,
                severity=ViolationSeverity.ERROR,
                message="Violation 3",
            ),
        ]
        
        result = InvariantCheckResult(
            passed=False,
            violations=violations,
        )
        
        observable = result.get_violations_by_type(InvariantType.OBSERVABLE_ONLY)
        assert len(observable) == 2
        
        completeness = result.get_violations_by_type(InvariantType.COMPLETENESS)
        assert len(completeness) == 1


# =============================================================================
# Tests for Factory Function
# =============================================================================

class TestFactoryFunction:
    """Tests for create_invariant_enforcer factory function."""

    def test_create_default(self):
        """Test creating with default settings."""
        enforcer = create_invariant_enforcer()
        
        assert isinstance(enforcer, InvariantEnforcer)
        assert enforcer._level == EnforcementLevel.STANDARD

    def test_create_with_level_string(self):
        """Test creating with level as string."""
        enforcer = create_invariant_enforcer(level="strict")
        
        assert enforcer._level == EnforcementLevel.STRICT

    def test_create_with_config(self):
        """Test creating with configuration."""
        config = {
            "custom_severities": {
                InvariantType.OBSERVABLE_ONLY: ViolationSeverity.CRITICAL,
            }
        }
        
        enforcer = create_invariant_enforcer(level="standard", config=config)
        
        assert enforcer._severities[InvariantType.OBSERVABLE_ONLY] == ViolationSeverity.CRITICAL


# =============================================================================
# Tests for Statistics
# =============================================================================

class TestStatistics:
    """Tests for enforcement statistics."""

    def test_stats_tracking(self):
        """Test that statistics are tracked."""
        enforcer = InvariantEnforcer()
        
        # Run some checks
        enforcer.check_all(get_basic_context())
        enforcer.check_all({
            "output": "The user believes this.",
            "extracted_count": 10,
            "classified_count": 5,
            "exclusions_count": 2,
        })
        
        stats = enforcer.get_stats()
        
        assert stats["total_checks"] == 20  # 2 runs * 10 checks
        assert stats["total_violations"] > 0

    def test_stats_reset(self):
        """Test resetting statistics."""
        enforcer = InvariantEnforcer()
        
        # Run a check with violations
        enforcer.check_all({
            "output": "The user believes this.",
            "extracted_count": 10,
            "classified_count": 5,
            "exclusions_count": 2,
        })
        
        assert enforcer._total_checks > 0
        
        enforcer.reset_stats()
        
        assert enforcer._total_checks == 0
        assert enforcer._total_violations == 0


# =============================================================================
# Tests for Custom Forbidden Markers
# =============================================================================

class TestCustomForbiddenMarkers:
    """Tests for adding custom forbidden markers."""

    def test_add_custom_marker(self):
        """Test adding a custom forbidden marker."""
        enforcer = InvariantEnforcer()
        
        # Add custom marker
        enforcer.add_forbidden_marker("custom_mental_state")
        
        # Should now detect it
        violation = enforcer.check_observable_only(
            output="The user has a custom_mental_state about this."
        )
        
        assert violation is not None


# =============================================================================
# Tests for Integration with Orchestrator
# =============================================================================

class TestOrchestratorIntegration:
    """Tests for integration with the orchestrator."""

    def test_invariant_enforcer_available(self):
        """Test that invariant enforcer is available in orchestrator."""
        from src.harness.orchestrator import Orchestrator, INVARIANT_ENFORCER_AVAILABLE
        
        assert INVARIANT_ENFORCER_AVAILABLE, "InvariantEnforcer should be available"

    def test_orchestrator_initializes_enforcer(self):
        """Test that orchestrator initializes the enforcer."""
        from src.harness.orchestrator import Orchestrator
        
        orchestrator = Orchestrator(config={"invariant_enforcement": "standard"})
        
        assert orchestrator._invariant_enforcer is not None

    def test_orchestrator_runs_invariant_checks(self):
        """Test that orchestrator runs invariant checks during pipeline."""
        from src.harness.orchestrator import Orchestrator
        
        orchestrator = Orchestrator()
        session = {
            "source_file": None,
            "output": "Test output",
            "extracted_count": 10,
            "classified_count": 10,
            "exclusions_count": 0,
        }
        
        result = orchestrator.run_pipeline(session)
        
        # Should have invariant_checks in results
        assert "invariant_checks" in result

    def test_orchestrator_gets_invariant_stats(self):
        """Test that orchestrator provides invariant stats."""
        from src.harness.orchestrator import Orchestrator
        
        orchestrator = Orchestrator()
        
        stats = orchestrator.get_invariant_stats()
        
        assert "available" in stats


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_output(self):
        """Test with empty output."""
        enforcer = InvariantEnforcer()
        
        violation = enforcer.check_observable_only("")
        
        assert violation is None

    def test_none_values(self):
        """Test handling of None values."""
        enforcer = InvariantEnforcer()
        
        result = enforcer.check_all({})
        
        # Should not crash, just return a result
        assert isinstance(result, InvariantCheckResult)

    def test_disabled_invariants(self):
        """Test with some invariants disabled."""
        enforcer = InvariantEnforcer(
            disabled_invariants={InvariantType.OBSERVABLE_ONLY}
        )
        
        context = {
            "output": "The user believes this.",
            "extracted_count": 10,
            "classified_count": 10,
            "exclusions_count": 0,
        }
        
        result = enforcer.check_all(context)
        
        # Should have fewer checks
        assert result.checks_run == 9
        # Should not have OBSERVABLE_ONLY violation
        assert not result.get_violations_by_type(InvariantType.OBSERVABLE_ONLY)

    def test_enabled_invariants_subset(self):
        """Test with only specific invariants enabled."""
        enforcer = InvariantEnforcer(
            enabled_invariants={
                InvariantType.OBSERVABLE_ONLY,
                InvariantType.COMPLETENESS,
            }
        )
        
        context = {
            "output": "The user believes this.",
            "extracted_count": 10,
            "classified_count": 5,
            "exclusions_count": 2,
        }
        
        result = enforcer.check_all(context)
        
        # Should only run 2 checks
        assert result.checks_run == 2
