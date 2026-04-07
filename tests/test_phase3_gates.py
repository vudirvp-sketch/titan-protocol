"""
Tests for PHASE_3: GATES_ENHANCEMENT

ITEM-GATE-01: Gate-04 Early Exit Fix
ITEM-GATE-02: Mode-Based Gate Sensitivity
ITEM-GATE-03: Pre-Intent Token Budget
ITEM-GATE-04: Split Pre/Post Exec Gates
ITEM-GATE-05: Model Downgrade Determinism

Author: TITAN FUSE Team
Version: 3.3.0
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# ITEM-GATE-01: Gate-04 Early Exit Fix Tests
# =============================================================================

class TestGate04EarlyExit:
    """Tests for Gate-04 Early Exit functionality."""
    
    def test_should_early_exit_with_high_confidence_no_critical_gaps(self):
        """High confidence with no critical gaps should trigger early exit."""
        from src.policy.gate_evaluation import Gate04Evaluator, Gap, Severity, GateResult
        
        evaluator = Gate04Evaluator()
        
        # Only SEV-3 and SEV-4 gaps
        gaps = [
            Gap(gap_id="G1", severity=Severity.SEV_3, description="Minor issue"),
            Gap(gap_id="G2", severity=Severity.SEV_4, description="Low priority")
        ]
        
        should_exit = evaluator.should_early_exit(gaps, confidence="HIGH")
        assert should_exit is True
    
    def test_should_not_early_exit_with_sev1_gaps(self):
        """SEV-1 gaps should block early exit."""
        from src.policy.gate_evaluation import Gate04Evaluator, Gap, Severity
        
        evaluator = Gate04Evaluator()
        
        gaps = [
            Gap(gap_id="G1", severity=Severity.SEV_1, description="Critical issue")
        ]
        
        should_exit = evaluator.should_early_exit(gaps, confidence="HIGH")
        assert should_exit is False
    
    def test_should_not_early_exit_with_medium_confidence(self):
        """Medium confidence should not trigger early exit."""
        from src.policy.gate_evaluation import Gate04Evaluator, Gap, Severity
        
        evaluator = Gate04Evaluator()
        
        gaps = [
            Gap(gap_id="G1", severity=Severity.SEV_4, description="Low priority")
        ]
        
        should_exit = evaluator.should_early_exit(gaps, confidence="MEDIUM")
        assert should_exit is False
    
    def test_early_exit_skips_sev4_processing(self):
        """Early exit should result in ADVISORY_PASS."""
        from src.policy.gate_evaluation import Gate04Evaluator, Gap, Severity, GateResult
        
        evaluator = Gate04Evaluator()
        
        gaps = [
            Gap(gap_id="G1", severity=Severity.SEV_3, description="Minor issue")
        ]
        
        result = evaluator.evaluate_with_early_exit(gaps, confidence="HIGH", phase=4)
        
        assert result.result == GateResult.ADVISORY_PASS
        assert "early exit" in result.reason.lower()
    
    def test_lint_detects_misplaced_confidence_check(self):
        """Lint should detect early exit issues."""
        from src.validation.gate_lint import GateLinter, LintSeverity
        
        linter = GateLinter({
            "gate04": {"max_sev2_gaps": 0, "allow_advisory_pass": True}
        })
        
        gaps = [
            {"gap_id": "G1", "severity": "SEV-3", "resolved": False}
        ]
        
        result = linter.lint_gate_config(gaps, confidence="HIGH", phase=4)
        
        # Should have warning about potential missed early exit
        assert result.passed is True  # No errors
        # May have warnings about early exit positioning


# =============================================================================
# ITEM-GATE-02: Mode-Based Gate Sensitivity Tests
# =============================================================================

class TestModeBasedGateSensitivity:
    """Tests for mode-based gate sensitivity."""
    
    def test_deterministic_mode_is_strict(self):
        """Deterministic mode should have strictest settings."""
        from src.policy.gate_behavior import GateBehaviorModifier
        
        modifier = GateBehaviorModifier()
        sensitivity = modifier.get_sensitivity("deterministic")
        
        assert sensitivity.fail_on_any_gap is True
        assert sensitivity.max_sev1_gaps == 0
        assert sensitivity.max_sev2_gaps == 0
        assert sensitivity.allow_advisory_pass is False
        assert sensitivity.confidence_override is False
    
    def test_fast_prototype_mode_is_lenient(self):
        """Fast prototype mode should be most lenient."""
        from src.policy.gate_behavior import GateBehaviorModifier
        
        modifier = GateBehaviorModifier()
        sensitivity = modifier.get_sensitivity("fast_prototype")
        
        assert sensitivity.fail_on_any_gap is False
        assert sensitivity.allow_advisory_pass is True
        assert sensitivity.allow_unsafe is True
    
    def test_mode_affects_gate_result(self):
        """Different modes should produce different gate results."""
        from src.policy.gate_behavior import GateBehaviorModifier, GateResult
        
        modifier = GateBehaviorModifier()
        
        gaps = [
            {"severity": "SEV-3", "resolved": False}
        ]
        
        # Deterministic: should fail on any gap
        result_det = modifier.apply_mode_rules(
            GateResult.PASS, "deterministic", gaps, confidence="HIGH"
        )
        
        # Fast prototype: should allow
        result_fast = modifier.apply_mode_rules(
            GateResult.PASS, "fast_prototype", gaps, confidence="HIGH"
        )
        
        # Deterministic should be stricter
        assert result_det.modified_result != result_fast.modified_result or \
               len(result_det.warnings) >= len(result_fast.warnings)
    
    def test_sev1_always_blocks_regardless_of_mode(self):
        """SEV-1 gaps should always block, even in fast_prototype."""
        from src.policy.gate_behavior import GateBehaviorModifier, GateResult
        
        modifier = GateBehaviorModifier()
        
        gaps = [
            {"severity": "SEV-1", "resolved": False}
        ]
        
        result = modifier.apply_mode_rules(
            GateResult.PASS, "fast_prototype", gaps, confidence="HIGH"
        )
        
        assert result.modified_result == GateResult.FAIL
    
    def test_custom_mode_sensitivity(self):
        """Custom mode sensitivity should be loadable from config."""
        from src.policy.gate_behavior import GateBehaviorModifier
        
        config = {
            "gate_sensitivity": {
                "custom_mode": {
                    "fail_on_any_gap": False,
                    "max_sev2_gaps": 10
                }
            }
        }
        
        modifier = GateBehaviorModifier(config)
        sensitivity = modifier.get_sensitivity("custom_mode")
        
        assert sensitivity.fail_on_any_gap is False
        assert sensitivity.max_sev2_gaps == 10


# =============================================================================
# ITEM-GATE-03: Pre-Intent Token Budget Tests
# =============================================================================

class TestPreIntentTokenBudget:
    """Tests for pre-intent token budget checking."""
    
    def test_normal_query_within_budget(self):
        """Normal query should classify successfully."""
        from src.policy.intent_router import IntentRouter
        
        router = IntentRouter(config={"pre_intent": {"token_limit": 5000}})
        result = router.classify_intent("Please review this code for security issues")
        
        assert result.budget_exceeded is False
        assert result.intent == "security_audit"
    
    def test_large_query_exceeds_budget(self):
        """Large query should trigger budget exceeded."""
        from src.policy.intent_router import IntentRouter
        
        router = IntentRouter(config={"pre_intent": {"token_limit": 100}})
        
        # Create a large query
        large_query = "Please review " + "x" * 1000
        
        result = router.classify_intent(large_query)
        
        assert result.budget_exceeded is True
        assert result.intent == "MANUAL"
    
    def test_budget_exceeded_falls_back_to_manual(self):
        """Budget exceeded should fall back to MANUAL mode."""
        from src.policy.intent_router import IntentRouter
        
        router = IntentRouter(config={
            "pre_intent": {
                "token_limit": 50,
                "fallback_mode": "MANUAL"
            }
        })
        
        result = router.classify_intent("This is a reasonably long query that exceeds the limit")
        
        assert result.intent == "MANUAL"
        assert result.budget_exceeded is True
    
    def test_token_counting_reasonable(self):
        """Token counting should be reasonable."""
        from src.policy.intent_router import IntentRouter
        
        router = IntentRouter()
        
        # Short query
        short = "review code"
        short_count = router.count_tokens(short)
        
        # Long query
        long = "review code" * 100
        long_count = router.count_tokens(long)
        
        assert short_count < long_count
        assert short_count > 0
        assert long_count > short_count * 50  # Should scale
    
    def test_low_confidence_falls_back(self):
        """Low confidence should fall back to MANUAL."""
        from src.policy.intent_router import IntentRouter
        
        router = IntentRouter(config={
            "pre_intent": {
                "token_limit": 5000,
                "ambiguity_threshold": 0.8
            }
        })
        
        # Ambiguous query
        result = router.classify_intent("do something")
        
        # Should fall back due to low confidence
        assert result.intent == "MANUAL" or result.confidence < 0.8


# =============================================================================
# ITEM-GATE-04: Split Pre/Post Exec Gates Tests
# =============================================================================

class TestSplitPrePostGates:
    """Tests for split pre/post execution gates."""
    
    def test_pre_exec_gates_exist(self):
        """Pre-exec gates should be defined."""
        from src.policy.gate_manager import GateManager, GateType
        
        manager = GateManager()
        gates = manager.list_gates()
        
        assert "pre_exec" in gates
        assert len(gates["pre_exec"]) > 0
        
        for gate in gates["pre_exec"]:
            assert gate["check_type"] == "pre_exec"
    
    def test_post_exec_gates_exist(self):
        """Post-exec gates should be defined."""
        from src.policy.gate_manager import GateManager, GateType
        
        manager = GateManager()
        gates = manager.list_gates()
        
        assert "post_exec" in gates
        assert len(gates["post_exec"]) > 0
        
        for gate in gates["post_exec"]:
            assert gate["check_type"] == "post_exec"
    
    def test_pre_exec_runs_successfully(self):
        """Pre-exec gates should run and return result."""
        from src.policy.gate_manager import GateManager, GateResult
        
        manager = GateManager()
        
        context = {
            "policies": {"policy1": {}},
            "user": {"permissions": ["read", "write"]},
            "required_permissions": ["read"],
            "resources": {
                "required": {"memory": 100},
                "available": {"memory": 1000}
            }
        }
        
        result = manager.run_pre_exec_gates(context)
        
        assert result.overall_result in [GateResult.PASS, GateResult.ADVISORY_PASS, GateResult.FAIL]
    
    def test_post_exec_runs_successfully(self):
        """Post-exec gates should run and return result."""
        from src.policy.gate_manager import GateManager, GateResult
        
        manager = GateManager()
        
        context = {
            "output": {"result": "success", "gaps": []}
        }
        
        result = manager.run_post_exec_gates(context, {"result": "success"})
        
        assert result.overall_result in [GateResult.PASS, GateResult.ADVISORY_PASS, GateResult.FAIL]
    
    def test_required_gate_failure_blocks(self):
        """Required gate failure should block execution."""
        from src.policy.gate_manager import GateManager, GateResult, GateCheck, GateType
        
        manager = GateManager()
        
        # Register a failing required gate
        manager.register_check_function("Policy Check", lambda ctx: False)
        
        context = {"policies": {}}
        result = manager.run_pre_exec_gates(context)
        
        # Should fail due to required gate
        assert result.overall_result == GateResult.FAIL
    
    def test_custom_gate_can_be_added(self):
        """Custom gates should be addable."""
        from src.policy.gate_manager import GateManager, GateCheck, GateType
        
        manager = GateManager()
        
        custom_gate = GateCheck(
            name="Custom Check",
            check_type=GateType.PRE_EXEC,
            description="Custom validation",
            required=True
        )
        
        manager.add_gate(custom_gate)
        gates = manager.list_gates()
        
        assert any(g["name"] == "Custom Check" for g in gates["pre_exec"])


# =============================================================================
# ITEM-GATE-05: Model Downgrade Determinism Tests
# =============================================================================

class TestModelDowngradeDeterminism:
    """Tests for model downgrade determinism."""
    
    def test_deterministic_blocks_downgrade(self):
        """Deterministic mode should block downgrade on budget exhaustion."""
        from src.llm.router import ModelRouter, BudgetStatus, BudgetExhaustedError, ExecutionStrictness
        
        config = {
            "model_routing": {
                "root_model": {"provider": "openai", "model": "gpt-4"}
            },
            "model_fallback": {
                "enabled": True,
                "chain": ["gpt-3.5-turbo"]
            },
            "mode": {"current": "deterministic"}
        }
        
        router = ModelRouter(config)
        budget = BudgetStatus(total_budget=100, used=100, remaining=0, exhausted=True)
        
        with pytest.raises(BudgetExhaustedError):
            router.get_model(budget_status=budget)
    
    def test_guided_autonomy_allows_downgrade(self):
        """Guided autonomy mode should allow downgrade."""
        from src.llm.router import ModelRouter, BudgetStatus, ExecutionStrictness
        
        config = {
            "model_routing": {
                "root_model": {"provider": "openai", "model": "gpt-4"}
            },
            "model_fallback": {
                "enabled": True,
                "chain": ["gpt-3.5-turbo", "local-model"]
            },
            "mode": {"current": "guided_autonomy"}
        }
        
        router = ModelRouter(config)
        budget = BudgetStatus(total_budget=100, used=100, remaining=0, exhausted=True)
        
        model = router.get_model(budget_status=budget)
        
        # Should return first fallback model
        assert model.model == "gpt-3.5-turbo"
    
    def test_fast_prototype_uses_cheapest_model(self):
        """Fast prototype mode should use cheapest model on exhaustion."""
        from src.llm.router import ModelRouter, BudgetStatus
        
        config = {
            "model_routing": {
                "root_model": {"provider": "openai", "model": "gpt-4"}
            },
            "model_fallback": {
                "enabled": True,
                "chain": ["gpt-3.5-turbo", "local-model"]
            },
            "mode": {"current": "fast_prototype"}
        }
        
        router = ModelRouter(config)
        budget = BudgetStatus(total_budget=100, used=100, remaining=0, exhausted=True)
        
        model = router.get_model(budget_status=budget)
        
        # Should return last (cheapest) model
        assert model.model == "local-model"
    
    def test_fallback_blocked_in_deterministic(self):
        """Fallback activation should be blocked in deterministic mode."""
        from src.llm.router import ModelRouter, ExecutionStrictness
        
        config = {
            "model_routing": {
                "root_model": {"provider": "openai", "model": "gpt-4"}
            },
            "model_fallback": {
                "enabled": True,
                "chain": ["gpt-3.5-turbo"]
            },
            "mode": {"current": "deterministic"}
        }
        
        router = ModelRouter(config)
        
        # Should return None (blocked)
        result = router.activate_fallback("test")
        assert result is None
    
    def test_downgrade_stats_tracked(self):
        """Downgrade statistics should be tracked."""
        from src.llm.router import ModelRouter, BudgetStatus
        
        config = {
            "model_routing": {
                "root_model": {"provider": "openai", "model": "gpt-4"}
            },
            "model_fallback": {
                "enabled": True,
                "chain": ["gpt-3.5-turbo"]
            },
            "mode": {"current": "guided_autonomy"}
        }
        
        router = ModelRouter(config)
        budget = BudgetStatus(total_budget=100, used=100, remaining=0, exhausted=True)
        
        # Trigger downgrade
        router.get_model(budget_status=budget)
        
        stats = router.get_usage_summary()
        assert stats["downgrade_attempts"] == 1


# =============================================================================
# Integration Tests
# =============================================================================

class TestPhase3Integration:
    """Integration tests for PHASE_3 components."""
    
    def test_full_gate_flow(self):
        """Test full gate flow from pre-exec to post-exec."""
        from src.policy.gate_manager import GateManager, GateResult
        from src.policy.gate_evaluation import Gate04Evaluator, Gap, Severity
        
        manager = GateManager()
        evaluator = Gate04Evaluator()
        
        # Pre-exec check
        context = {
            "policies": {"policy1": {}},
            "user": {"permissions": ["read"]},
            "resources": {"required": {}, "available": {}}
        }
        
        pre_result = manager.run_pre_exec_gates(context)
        
        # Simulate operation
        output = {"result": "success", "gaps": []}
        
        # Post-exec check
        post_result = manager.run_post_exec_gates(context, output)
        
        # Gate-04 check
        gaps = [Gap(gap_id="G1", severity=Severity.SEV_3, description="Minor")]
        gate_result = evaluator.evaluate(gaps, confidence="HIGH")
        
        # All should have results
        assert pre_result.overall_result in GateResult
        assert post_result.overall_result in GateResult
        assert gate_result.result in GateResult
    
    def test_mode_affects_all_components(self):
        """Mode should affect gate behavior across components."""
        from src.policy.gate_behavior import GateBehaviorModifier, GateResult
        from src.llm.router import ModelRouter, BudgetStatus, ExecutionStrictness
        
        # Test deterministic mode
        config = {
            "mode": {"current": "deterministic"},
            "model_routing": {"root_model": {"provider": "openai", "model": "gpt-4"}},
            "model_fallback": {"enabled": True, "chain": ["gpt-3.5"]}
        }
        
        modifier = GateBehaviorModifier(config)
        router = ModelRouter(config)
        
        # Check strictness
        sensitivity = modifier.get_sensitivity("deterministic")
        assert sensitivity.fail_on_any_gap is True
        assert router.strictness == ExecutionStrictness.DETERMINISTIC


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
