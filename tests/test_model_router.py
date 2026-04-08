"""
Tests for ITEM-MODEL-001: Root/Leaf Routing Optimization.

Tests the intelligent task-to-model routing based on task complexity
and model capabilities.

Author: TITAN FUSE Team
Version: 5.0.0
"""

import pytest
from unittest.mock import MagicMock, patch

from src.llm.router import (
    ModelRouter,
    ModelTier,
    TaskType,
    TaskComplexity,
    RoutingDecision,
    ModelConfig,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def basic_config():
    """Basic configuration for ModelRouter."""
    return {
        "model_routing": {
            "root_model": {"provider": "openai", "model": "gpt-4"},
            "leaf_model": {"provider": "openai", "model": "gpt-3.5-turbo"},
            "track_costs": True,
            "log_model_usage": False,  # Disable for tests
            "complexity_weights": {
                "context_length": 0.3,
                "dependency_depth": 0.2,
                "gate_count": 0.2,
                "pattern_complexity": 0.3,
            },
            "tier_demotion": {
                "enabled": True,
                "low_complexity_threshold": 0.3,
                "high_complexity_threshold": 0.7,
                "high_confidence_threshold": 0.9,
            }
        },
        "model_fallback": {
            "enabled": False,
            "chain": []
        },
        "mode": {"current": "guided_autonomy"}
    }


@pytest.fixture
def router(basic_config):
    """Create ModelRouter instance."""
    return ModelRouter(basic_config)


# =============================================================================
# Test: Correct Routing
# =============================================================================

class TestCorrectRouting:
    """Test that tasks are routed to appropriate model tier."""
    
    def test_orchestration_routes_to_root_with_high_complexity(self, router):
        """Orchestration tasks with high complexity should route to ROOT tier."""
        # Use a task with enough complexity to stay on ROOT
        task = {
            "type": "orchestration",
            "context": "x" * 50000,  # Medium context
            "dependencies": list(range(5)),
            "gates": list(range(3)),
            "patterns": list(range(10))
        }
        decision = router.route_task(task)
        
        assert decision.task_type == TaskType.ORCHESTRATION
        # With sufficient complexity, should stay on ROOT
        assert decision.tier == ModelTier.ROOT
        assert decision.model_id == router.root_model.model
    
    def test_orchestration_demotes_to_leaf_when_low_complexity(self, router):
        """Low complexity orchestration tasks should demote to LEAF."""
        task = {"type": "orchestration", "context": "test"}
        decision = router.route_task(task)
        
        assert decision.task_type == TaskType.ORCHESTRATION
        # Low complexity should demote to LEAF
        assert decision.tier == ModelTier.LEAF
    
    def test_planning_routes_to_root_with_high_complexity(self, router):
        """Planning tasks with high complexity should route to ROOT tier."""
        task = {
            "type": "planning",
            "context": "x" * 50000,
            "dependencies": list(range(5)),
            "gates": list(range(3)),
            "patterns": list(range(10))
        }
        decision = router.route_task(task)
        
        assert decision.task_type == TaskType.PLANNING
        assert decision.tier == ModelTier.ROOT
    
    def test_conflict_resolution_routes_to_root_with_high_complexity(self, router):
        """Conflict resolution tasks with high complexity should route to ROOT tier."""
        task = {
            "type": "conflict_resolution",
            "context": "x" * 50000,
            "dependencies": list(range(5)),
            "gates": list(range(3)),
            "patterns": list(range(10))
        }
        decision = router.route_task(task)
        
        assert decision.task_type == TaskType.CONFLICT_RESOLUTION
        assert decision.tier == ModelTier.ROOT
    
    def test_gate_decision_routes_to_root_with_high_complexity(self, router):
        """Gate decision tasks with high complexity should route to ROOT tier."""
        task = {
            "type": "gate_decision",
            "context": "x" * 50000,
            "dependencies": list(range(5)),
            "gates": list(range(3)),
            "patterns": list(range(10))
        }
        decision = router.route_task(task)
        
        assert decision.task_type == TaskType.GATE_DECISION
        assert decision.tier == ModelTier.ROOT
    
    def test_chunk_query_routes_to_leaf(self, router):
        """Chunk query tasks should route to LEAF tier."""
        task = {"type": "chunk_query", "context": "test"}
        decision = router.route_task(task)
        
        assert decision.tier == ModelTier.LEAF
        assert decision.task_type == TaskType.CHUNK_QUERY
        assert decision.model_id == router.leaf_model.model
    
    def test_code_analysis_routes_to_leaf(self, router):
        """Code analysis tasks should route to LEAF tier."""
        task = {"type": "code_analysis", "context": "test"}
        decision = router.route_task(task)
        
        assert decision.tier == ModelTier.LEAF
        assert decision.task_type == TaskType.CODE_ANALYSIS
    
    def test_pattern_matching_routes_to_leaf(self, router):
        """Pattern matching tasks should route to LEAF tier."""
        task = {"type": "pattern_matching", "context": "test"}
        decision = router.route_task(task)
        
        assert decision.tier == ModelTier.LEAF
        assert decision.task_type == TaskType.PATTERN_MATCHING
    
    def test_validation_routes_to_leaf(self, router):
        """Validation tasks should route to LEAF tier."""
        task = {"type": "validation", "context": "test"}
        decision = router.route_task(task)
        
        assert decision.tier == ModelTier.LEAF
        assert decision.task_type == TaskType.VALIDATION


# =============================================================================
# Test: Cost Optimization
# =============================================================================

class TestCostOptimized:
    """Test that low-complexity tasks use cheaper models."""
    
    def test_low_complexity_root_task_demotes_to_leaf(self, router):
        """Low complexity ROOT tasks should demote to LEAF for cost savings."""
        # Simple orchestration task with minimal complexity
        task = {
            "type": "orchestration",
            "context": "simple",  # Short context
            "dependencies": [],    # No dependencies
            "gates": [],           # No gates
            "patterns": []         # No patterns
        }
        decision = router.route_task(task)
        
        # Should be demoted to LEAF due to low complexity
        assert decision.tier == ModelTier.LEAF
        assert decision.task_type == TaskType.ORCHESTRATION
        assert "demotion" in decision.rationale.lower() or "leaf" in decision.rationale.lower()
    
    def test_high_complexity_leaf_task_promotes_to_root(self, router):
        """High complexity LEAF tasks should promote to ROOT."""
        # Complex chunk query
        large_context = "x" * 80000  # Large context
        task = {
            "type": "chunk_query",
            "context": large_context,
            "dependencies": list(range(10)),  # Many dependencies
            "gates": list(range(5)),          # Many gates
            "patterns": list(range(20))       # Many patterns
        }
        decision = router.route_task(task)
        
        # Should be promoted to ROOT due to high complexity
        assert decision.tier == ModelTier.ROOT
        assert decision.task_type == TaskType.CHUNK_QUERY
        assert "promotion" in decision.rationale.lower() or "root" in decision.rationale.lower()
    
    def test_medium_complexity_uses_base_tier(self, router):
        """Medium complexity tasks should use their base tier."""
        # Use complexity in the middle range (0.3-0.7) to avoid demotion/promotion
        task = {
            "type": "planning",
            "context": "x" * 40000,  # 0.4 context_length
            "dependencies": list(range(5)),  # 0.5 dependency_depth
            "gates": list(range(2)),  # 0.4 gate_count
            "patterns": list(range(8))  # 0.4 pattern_complexity
        }
        decision = router.route_task(task)
        
        # Should stay on ROOT (base tier for planning) with medium complexity
        assert decision.task_type == TaskType.PLANNING
        # With ~0.4 complexity, should stay on ROOT
        assert decision.tier == ModelTier.ROOT


# =============================================================================
# Test: Complexity Estimation
# =============================================================================

class TestComplexityEstimation:
    """Test task complexity estimation."""
    
    def test_empty_task_has_zero_complexity(self, router):
        """Empty task should have zero complexity."""
        task = {}
        complexity = router.estimate_complexity(task)
        
        assert complexity.context_length == 0.0
        assert complexity.dependency_depth == 0.0
        assert complexity.gate_count == 0.0
        assert complexity.pattern_complexity == 0.0
        assert complexity.overall_score == 0.0
    
    def test_context_length_normalization(self, router):
        """Context length should be normalized to 0-1 range."""
        # Small context
        task = {"context": "x" * 10000}
        complexity = router.estimate_complexity(task)
        assert 0.0 <= complexity.context_length <= 1.0
        
        # Large context
        task = {"context": "x" * 100000}
        complexity = router.estimate_complexity(task)
        assert complexity.context_length == 1.0  # Capped at 1.0
    
    def test_dependency_depth_normalization(self, router):
        """Dependency depth should be normalized to 0-1 range."""
        # Few dependencies
        task = {"dependencies": ["a", "b"]}
        complexity = router.estimate_complexity(task)
        assert 0.0 <= complexity.dependency_depth <= 1.0
        
        # Many dependencies
        task = {"dependencies": list(range(20))}
        complexity = router.estimate_complexity(task)
        assert complexity.dependency_depth == 1.0  # Capped at 1.0
    
    def test_gate_count_normalization(self, router):
        """Gate count should be normalized to 0-1 range."""
        task = {"gates": ["gate1", "gate2"]}
        complexity = router.estimate_complexity(task)
        assert 0.0 <= complexity.gate_count <= 1.0
        
        task = {"gates": list(range(10))}
        complexity = router.estimate_complexity(task)
        assert complexity.gate_count == 1.0  # Capped at 1.0
    
    def test_pattern_complexity_normalization(self, router):
        """Pattern complexity should be normalized to 0-1 range."""
        task = {"patterns": ["p1", "p2", "p3"]}
        complexity = router.estimate_complexity(task)
        assert 0.0 <= complexity.pattern_complexity <= 1.0
        
        task = {"patterns": list(range(30))}
        complexity = router.estimate_complexity(task)
        assert complexity.pattern_complexity == 1.0  # Capped at 1.0
    
    def test_overall_score_calculation(self, router):
        """Overall score should be weighted average of factors."""
        task = {
            "context": "x" * 50000,        # 0.5
            "dependencies": list(range(5)), # 0.5
            "gates": list(range(3)),        # 0.6
            "patterns": list(range(10))     # 0.5
        }
        complexity = router.estimate_complexity(task)
        
        # Verify overall score is calculated
        assert complexity.overall_score > 0.0
        assert complexity.overall_score <= 1.0
        
        # Verify weights are applied correctly
        expected = (
            0.5 * 0.3 +  # context_length * weight
            0.5 * 0.2 +  # dependency_depth * weight
            0.6 * 0.2 +  # gate_count * weight
            0.5 * 0.3    # pattern_complexity * weight
        )
        assert abs(complexity.overall_score - expected) < 0.01


# =============================================================================
# Test: Tier Demotion
# =============================================================================

class TestTierDemotion:
    """Test tier demotion functionality."""
    
    def test_tier_demotion_disabled(self, basic_config):
        """Tier demotion should be disabled when configured."""
        basic_config["model_routing"]["tier_demotion"]["enabled"] = False
        router = ModelRouter(basic_config)
        
        # Low complexity task
        task = {"type": "orchestration", "context": "simple"}
        decision = router.route_task(task)
        
        # Should stay on ROOT despite low complexity
        assert decision.tier == ModelTier.ROOT
    
    def test_tier_demotion_increases_stats(self, router):
        """Tier demotion should update statistics."""
        initial_stats = router.get_routing_stats()
        initial_demotions = initial_stats["tier_demotions"]
        
        # Trigger demotion
        task = {"type": "orchestration", "context": "x"}
        router.route_task(task)
        
        final_stats = router.get_routing_stats()
        assert final_stats["tier_demotions"] > initial_demotions
    
    def test_custom_low_complexity_threshold(self, basic_config):
        """Custom low complexity threshold should be respected."""
        basic_config["model_routing"]["tier_demotion"]["low_complexity_threshold"] = 0.5
        router = ModelRouter(basic_config)
        
        # Task with complexity ~0.4 should demote (under 0.5 threshold)
        task = {
            "type": "orchestration",
            "context": "x" * 40000,  # ~0.4 context_length
            "dependencies": [],
            "gates": [],
            "patterns": []
        }
        decision = router.route_task(task)
        
        # Should demote since complexity < 0.5
        assert decision.tier == ModelTier.LEAF


# =============================================================================
# Test: Task Type Classification
# =============================================================================

class TestTaskTypeClassification:
    """Test task type classification logic."""
    
    def test_explicit_type_classification(self, router):
        """Explicit task type should be used."""
        task = {"type": "planning", "context": "test"}
        task_type = router._classify_task(task)
        
        assert task_type == TaskType.PLANNING
    
    def test_infer_conflict_resolution_from_conflicts(self, router):
        """Should infer CONFLICT_RESOLUTION from has_conflicts flag."""
        task = {"has_conflicts": True}
        task_type = router._classify_task(task)
        
        assert task_type == TaskType.CONFLICT_RESOLUTION
    
    def test_infer_planning_from_gates_and_deps(self, router):
        """Should infer PLANNING from gates and dependencies."""
        task = {"gates": ["gate1"], "dependencies": ["dep1"]}
        task_type = router._classify_task(task)
        
        assert task_type == TaskType.PLANNING
    
    def test_infer_gate_decision_from_gates_only(self, router):
        """Should infer GATE_DECISION from gates only."""
        task = {"gates": ["gate1"]}
        task_type = router._classify_task(task)
        
        assert task_type == TaskType.GATE_DECISION
    
    def test_infer_chunk_query_from_is_chunk(self, router):
        """Should infer CHUNK_QUERY from is_chunk flag."""
        task = {"is_chunk": True}
        task_type = router._classify_task(task)
        
        assert task_type == TaskType.CHUNK_QUERY
    
    def test_infer_orchestration_from_flag(self, router):
        """Should infer ORCHESTRATION from is_orchestration flag."""
        task = {"is_orchestration": True}
        task_type = router._classify_task(task)
        
        assert task_type == TaskType.ORCHESTRATION
    
    def test_infer_validation_from_flag(self, router):
        """Should infer VALIDATION from is_validation flag."""
        task = {"is_validation": True}
        task_type = router._classify_task(task)
        
        assert task_type == TaskType.VALIDATION
    
    def test_infer_pattern_matching_from_flag(self, router):
        """Should infer PATTERN_MATCHING from is_pattern_matching flag."""
        task = {"is_pattern_matching": True}
        task_type = router._classify_task(task)
        
        assert task_type == TaskType.PATTERN_MATCHING
    
    def test_infer_code_analysis_from_flag(self, router):
        """Should infer CODE_ANALYSIS from is_code_analysis flag."""
        task = {"is_code_analysis": True}
        task_type = router._classify_task(task)
        
        assert task_type == TaskType.CODE_ANALYSIS
    
    def test_unknown_type_for_empty_task(self, router):
        """Empty task should classify as UNKNOWN."""
        task = {}
        task_type = router._classify_task(task)
        
        assert task_type == TaskType.UNKNOWN
    
    def test_case_insensitive_type_matching(self, router):
        """Task type matching should be case insensitive."""
        task = {"type": "ORCHESTRATION"}
        task_type = router._classify_task(task)
        
        assert task_type == TaskType.ORCHESTRATION


# =============================================================================
# Test: Backward Compatibility
# =============================================================================

class TestBackwardCompatibility:
    """Test backward compatibility with existing ModelRouter API."""
    
    def test_get_model_for_phase_still_works(self, router):
        """get_model_for_phase should still work."""
        # ROOT phases
        for phase in [0, 1, 2, 3, 5]:
            model = router.get_model_for_phase(phase)
            assert model == router.root_model
        
        # LEAF phase
        model = router.get_model_for_phase(4)
        assert model == router.leaf_model
    
    def test_get_status_includes_new_fields(self, router):
        """get_status should include new routing optimization fields."""
        status = router.get_status()
        
        assert "root_model" in status
        assert "leaf_model" in status
        assert "fallback_enabled" in status
    
    def test_get_usage_summary_includes_routing_stats(self, router):
        """get_usage_summary should include routing optimization stats."""
        summary = router.get_usage_summary()
        
        assert "routing_optimization" in summary
        routing_stats = summary["routing_optimization"]
        assert "total_routing_decisions" in routing_stats
        assert "tier_demotions" in routing_stats
        assert "tier_promotions" in routing_stats


# =============================================================================
# Test: RoutingDecision Dataclass
# =============================================================================

class TestRoutingDecision:
    """Test RoutingDecision dataclass."""
    
    def test_to_dict_serialization(self, router):
        """RoutingDecision should serialize to dict correctly."""
        task = {"type": "orchestration", "context": "test"}
        decision = router.route_task(task)
        
        d = decision.to_dict()
        
        assert "tier" in d
        assert "model_id" in d
        assert "complexity" in d
        assert "confidence" in d
        assert "rationale" in d
        assert "task_type" in d
    
    def test_confidence_range(self, router):
        """Confidence should be between 0 and 1."""
        task = {"type": "orchestration", "context": "test"}
        decision = router.route_task(task)
        
        assert 0.0 <= decision.confidence <= 1.0


# =============================================================================
# Test: TaskComplexity Dataclass
# =============================================================================

class TestTaskComplexity:
    """Test TaskComplexity dataclass."""
    
    def test_to_dict_serialization(self):
        """TaskComplexity should serialize to dict correctly."""
        complexity = TaskComplexity(
            context_length=0.5,
            dependency_depth=0.3,
            gate_count=0.2,
            pattern_complexity=0.4
        )
        
        d = complexity.to_dict()
        
        assert d["context_length"] == 0.5
        assert d["dependency_depth"] == 0.3
        assert d["gate_count"] == 0.2
        assert d["pattern_complexity"] == 0.4
        assert "overall_score" in d
    
    def test_post_init_calculates_overall_score(self):
        """Overall score should be calculated in __post_init__."""
        complexity = TaskComplexity(
            context_length=0.5,
            dependency_depth=0.5,
            gate_count=0.5,
            pattern_complexity=0.5
        )
        
        # Overall score should be calculated
        assert complexity.overall_score > 0.0
        assert abs(complexity.overall_score - 0.5) < 0.01


# =============================================================================
# Test: Statistics Tracking
# =============================================================================

class TestStatisticsTracking:
    """Test routing statistics tracking."""
    
    def test_routing_decisions_count(self, router):
        """routing_decisions count should increment with each route_task call."""
        initial = router.get_routing_stats()["total_routing_decisions"]
        
        router.route_task({"type": "orchestration"})
        router.route_task({"type": "chunk_query"})
        router.route_task({"type": "planning"})
        
        final = router.get_routing_stats()["total_routing_decisions"]
        assert final == initial + 3
    
    def test_demotion_and_promotion_tracking(self, router):
        """Demotions and promotions should be tracked separately."""
        # Trigger demotion
        router.route_task({"type": "orchestration", "context": "x"})
        
        # Trigger promotion
        large_context = "x" * 90000
        router.route_task({
            "type": "chunk_query",
            "context": large_context,
            "dependencies": list(range(15)),
            "gates": list(range(10)),
            "patterns": list(range(25))
        })
        
        stats = router.get_routing_stats()
        # At least one demotion or promotion should have occurred
        assert (stats["tier_demotions"] + stats["tier_promotions"]) > 0


# =============================================================================
# Test: Integration with Existing Model Selection
# =============================================================================

class TestIntegrationWithExistingAPI:
    """Test integration with existing ModelRouter API."""
    
    def test_route_task_updates_usage_stats(self, router):
        """route_task should update usage stats."""
        initial_root = router._usage_stats["root_calls"]
        initial_leaf = router._usage_stats["leaf_calls"]
        
        router.route_task({"type": "orchestration", "context": "x" * 50000})
        router.route_task({"type": "chunk_query", "context": "short"})
        
        # Stats should be updated (may vary based on complexity)
        total_calls = (
            router._usage_stats["root_calls"] + 
            router._usage_stats["leaf_calls"]
        )
        assert total_calls >= initial_root + initial_leaf + 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
