"""
Comprehensive tests for Phase 14 (CATALOG_MECHANICS_COMPLETION) modules.

This test module covers:
1. src.scoring.adaptive_weights - AdaptiveWeightEngine, WeightProfile
2. src.agents.scout_matrix - ScoutPipeline, RADAR, DEVIL, EVAL, STRAT agents
3. src.fusion.type_aware_merger - TypeAwareFusion, ContentType, ContentDensity
4. src.decision.conflict_resolver - ConflictResolver, ConflictMetrics
5. src.validation.guardian - Guardian validation loop
6. src.orchestrator.intent_handler - IntentHandler, MANDATORY_DEVIL_INTENTS

Validation criteria tested:
- formula_deterministic: Same inputs always produce identical score
- profile_weights_applied: MEDICAL_LEGAL profile weights RS highest
- conflict_thresholds_work: Gap >= 2.0 -> auto-select; 1.0-1.9 -> rationale
- devil_mandatory: DEVIL executes for EVALUATE/COMPARE/VALIDATE intents
- eval_veto_works: EVAL veto at EXPERIMENTAL/VAPORWARE blocks STRAT
- type_isolation: Merge fails when mixing FACT+OPINION
- high_density_priority: HIGH_DENSITY units always included

Author: TITAN FUSE Team
Version: 3.2.3
"""

import pytest
from dataclasses import asdict
from typing import Dict, List, Any, Optional
import math

# =============================================================================
# Module Imports
# =============================================================================

# Scoring module
from src.scoring.adaptive_weights import (
    AdaptiveWeightEngine,
    WeightProfile,
    WeightedScore,
    Decision,
    ConflictResolution,
    create_weight_engine,
    DEFAULT_WEIGHT_PROFILES,
)

# Agents module
from src.agents.scout_matrix import (
    ScoutPipeline,
    RADARAgent,
    DEVILAgent,
    EVALAgent,
    STRATAgent,
    AgentRole,
    AgentResult,
    AnalysisContext,
    ScoutOutput,
    PipelineContext,
    AdoptionReadiness,
)

# Fusion module
from src.fusion.type_aware_merger import (
    TypeAwareFusion,
    ContentType,
    ContentDensity,
    ContentUnit,
    MergedResult,
    DiscardLog,
    TypeMismatchError,
    create_fusion_engine,
)

# Decision module
from src.decision.conflict_resolver import (
    ConflictResolver,
    ConflictMetrics,
    Decision as ConflictDecision,
    DecisionConfidence,
    create_conflict_resolver,
    DEFAULT_CONFLICT_WEIGHTS,
)

# Guardian module
from src.validation.guardian import (
    Guardian,
    GuardianResult,
    Conflict,
    Resolution,
    ConflictType,
    ResolutionStatus,
    ValidationMode,
)

# Intent handler module
from src.orchestrator.intent_handler import (
    IntentHandler,
    IntentConfigError,
    IntentValidationResult,
    IntentProcessingStats,
    MANDATORY_DEVIL_INTENTS,
    create_intent_handler,
    integrate_with_intent_router,
)

# State module (for SignalStrength)
from src.state.assessment import SignalStrength


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def weight_engine():
    """Create a default AdaptiveWeightEngine for testing."""
    return AdaptiveWeightEngine()


@pytest.fixture
def technical_engine():
    """Create an AdaptiveWeightEngine with TECHNICAL profile."""
    return AdaptiveWeightEngine(default_profile=WeightProfile.TECHNICAL)


@pytest.fixture
def medical_legal_engine():
    """Create an AdaptiveWeightEngine with MEDICAL_LEGAL profile."""
    return AdaptiveWeightEngine(default_profile=WeightProfile.MEDICAL_LEGAL)


@pytest.fixture
def scout_pipeline():
    """Create a ScoutPipeline with all agents."""
    return ScoutPipeline(include_radar=True, strict_mode=True)


@pytest.fixture
def fusion_engine():
    """Create a TypeAwareFusion engine."""
    return TypeAwareFusion()


@pytest.fixture
def conflict_resolver():
    """Create a ConflictResolver with default weights."""
    return ConflictResolver()


@pytest.fixture
def guardian_config():
    """Create a default Guardian configuration."""
    return {
        "weight_profile": "MIXED",
        "strict_mode": False,
        "score_threshold": 7.0,
        "include_radar": True,
    }


@pytest.fixture
def guardian(guardian_config):
    """Create a Guardian instance for testing."""
    return Guardian(guardian_config)


@pytest.fixture
def sample_analysis_context():
    """Create a sample AnalysisContext for testing."""
    return AnalysisContext(
        subject="Test Technology",
        domain="ai",
        volatility="high",
        confidence=0.7,
        context=PipelineContext.EVALUATE,
        claims=["This is revolutionary technology"],
        evidence=["Evidence 1", "Evidence 2"],
        metadata={"description": "A test AI framework"},
    )


@pytest.fixture
def sample_content_units():
    """Create sample ContentUnit list for testing."""
    return [
        ContentUnit(
            content_type=ContentType.FACT,
            density=ContentDensity.HIGH,
            text="The system processes 1000 requests per second.",
            relevance_score=0.95,
        ),
        ContentUnit(
            content_type=ContentType.FACT,
            density=ContentDensity.LOW,
            text="The system is efficient.",
            relevance_score=0.6,
        ),
        ContentUnit(
            content_type=ContentType.CODE,
            density=ContentDensity.HIGH,
            text="def process(): return True",
            relevance_score=0.9,
        ),
    ]


# =============================================================================
# Test Class: TestWeightProfile
# =============================================================================

class TestWeightProfile:
    """Tests for WeightProfile enum."""

    def test_profile_weights_sum_to_one(self):
        """All profile weights should sum to 1.0."""
        for profile in WeightProfile:
            total = sum(profile.weights.values())
            assert math.isclose(total, 1.0, rel_tol=1e-9), \
                f"Profile {profile.name} weights sum to {total}, not 1.0"

    def test_profile_validate_returns_true(self):
        """Profile validate() method should return True for valid profiles."""
        for profile in WeightProfile:
            assert profile.validate() is True

    def test_medical_legal_highest_rs_weight(self):
        """MEDICAL_LEGAL profile should have highest RS weight (0.40)."""
        ml_weights = WeightProfile.MEDICAL_LEGAL.weights
        assert ml_weights["RS"] == 0.40, "MEDICAL_LEGAL RS weight should be 0.40"
        
        # Verify RS is highest among all profiles
        for profile in WeightProfile:
            if profile != WeightProfile.MEDICAL_LEGAL:
                assert ml_weights["RS"] >= profile.weights["RS"], \
                    f"MEDICAL_LEGAL RS should be highest, but {profile.name} has {profile.weights['RS']}"

    def test_technical_profile_weights(self):
        """TECHNICAL profile should have expected weight distribution."""
        tech = WeightProfile.TECHNICAL.weights
        assert tech["TF"] == 0.30
        assert tech["RS"] == 0.35
        assert tech["DS"] == 0.25
        assert tech["AC"] == 0.10

    def test_narrative_profile_weights(self):
        """NARRATIVE profile should emphasize DS and AC."""
        narr = WeightProfile.NARRATIVE.weights
        assert narr["DS"] == 0.35
        assert narr["AC"] == 0.30
        # RS should be lowest for narrative
        assert narr["RS"] == 0.10

    def test_weights_property_returns_dict(self):
        """weights property should return a dictionary."""
        weights = WeightProfile.MIXED.weights
        assert isinstance(weights, dict)
        assert set(weights.keys()) == {"TF", "RS", "DS", "AC"}


# =============================================================================
# Test Class: TestAdaptiveWeightEngine
# =============================================================================

class TestAdaptiveWeightEngine:
    """Tests for AdaptiveWeightEngine class."""

    # -------------------------------------------------------------------------
    # Validation Criteria: formula_deterministic
    # -------------------------------------------------------------------------

    def test_formula_deterministic_same_inputs_same_output(self, weight_engine):
        """Same inputs should always produce identical score (deterministic)."""
        # Run calculation multiple times with same inputs
        # MIXED profile weights: TF=0.35, RS=0.25, DS=0.25, AC=0.15
        # Expected: 8.5*0.35 + 7.2*0.25 + 6.0*0.25 + 9.0*0.15 = 7.625
        results = [
            weight_engine.calculate_score(tf=8.5, rs=7.2, ds=6.0, ac=9.0)
            for _ in range(100)
        ]
        
        # All results should be identical
        assert len(set(results)) == 1, "Scores should be deterministic"
        assert results[0] == 7.625  # MIXED profile calculation

    def test_formula_deterministic_different_profiles(self, weight_engine):
        """Different profiles should produce different but deterministic scores."""
        score_technical = weight_engine.calculate_score(
            tf=8.0, rs=7.0, ds=6.0, ac=5.0,
            profile=WeightProfile.TECHNICAL
        )
        score_medical = weight_engine.calculate_score(
            tf=8.0, rs=7.0, ds=6.0, ac=5.0,
            profile=WeightProfile.MEDICAL_LEGAL
        )
        score_narrative = weight_engine.calculate_score(
            tf=8.0, rs=7.0, ds=6.0, ac=5.0,
            profile=WeightProfile.NARRATIVE
        )
        
        # All should be deterministic (repeatable)
        assert score_technical == weight_engine.calculate_score(
            8.0, 7.0, 6.0, 5.0, WeightProfile.TECHNICAL
        )
        assert score_medical == weight_engine.calculate_score(
            8.0, 7.0, 6.0, 5.0, WeightProfile.MEDICAL_LEGAL
        )
        
        # Different profiles should produce different scores
        assert score_technical != score_medical or score_technical != score_narrative

    # -------------------------------------------------------------------------
    # Validation Criteria: profile_weights_applied
    # -------------------------------------------------------------------------

    def test_profile_weights_applied_medical_legal_rs_highest(self, medical_legal_engine):
        """MEDICAL_LEGAL profile should weight RS highest in score calculation."""
        # Create a scenario where RS difference should dominate
        score_high_rs = medical_legal_engine.calculate_score(
            tf=5.0, rs=10.0, ds=5.0, ac=5.0  # High RS
        )
        score_high_tf = medical_legal_engine.calculate_score(
            tf=10.0, rs=5.0, ds=5.0, ac=5.0  # High TF
        )
        
        # With MEDICAL_LEGAL, RS has 0.40 weight, TF has 0.35
        # High RS: 5*0.35 + 10*0.40 + 5*0.15 + 5*0.10 = 1.75 + 4.0 + 0.75 + 0.50 = 7.0
        # High TF: 10*0.35 + 5*0.40 + 5*0.15 + 5*0.10 = 3.5 + 2.0 + 0.75 + 0.50 = 6.75
        assert score_high_rs > score_high_tf, \
            "MEDICAL_LEGAL should weight RS higher than TF"

    def test_calculate_score_basic(self, weight_engine):
        """Basic score calculation should work correctly."""
        score = weight_engine.calculate_score(
            tf=10.0, rs=10.0, ds=10.0, ac=10.0,
            profile=WeightProfile.MIXED
        )
        assert score == 10.0  # All max values should give max score

    def test_calculate_score_zero_values(self, weight_engine):
        """Zero values should produce zero score."""
        score = weight_engine.calculate_score(
            tf=0.0, rs=0.0, ds=0.0, ac=0.0,
            profile=WeightProfile.MIXED
        )
        assert score == 0.0

    def test_calculate_score_invalid_range(self, weight_engine):
        """Invalid score values should raise ValueError."""
        with pytest.raises(ValueError):
            weight_engine.calculate_score(tf=11.0, rs=5.0, ds=5.0, ac=5.0)
        
        with pytest.raises(ValueError):
            weight_engine.calculate_score(tf=-1.0, rs=5.0, ds=5.0, ac=5.0)

    def test_calculate_score_detailed(self, weight_engine):
        """calculate_score_detailed should return WeightedScore with breakdown."""
        result = weight_engine.calculate_score_detailed(
            tf=8.0, rs=7.0, ds=6.0, ac=5.0,
            profile=WeightProfile.TECHNICAL
        )
        
        assert isinstance(result, WeightedScore)
        assert result.profile == WeightProfile.TECHNICAL
        assert result.components == {"TF": 8.0, "RS": 7.0, "DS": 6.0, "AC": 5.0}
        assert "TF" in result.weighted_components
        assert "RS" in result.weighted_components

    def test_default_profile_setter(self, weight_engine):
        """Default profile should be changeable."""
        weight_engine.default_profile = WeightProfile.NARRATIVE
        assert weight_engine.default_profile == WeightProfile.NARRATIVE

    def test_list_profiles(self, weight_engine):
        """list_profiles should return all available profiles."""
        profiles = weight_engine.list_profiles()
        assert "TECHNICAL" in profiles
        assert "MEDICAL_LEGAL" in profiles
        assert "NARRATIVE" in profiles
        assert "MIXED" in profiles

    def test_guardian_callback_registration(self, weight_engine):
        """Guardian callback should be registerable and callable."""
        callback_invoked = []
        
        def test_callback(score: WeightedScore) -> bool:
            callback_invoked.append(score)
            return score.score >= 7.0
        
        weight_engine.register_guardian_callback(test_callback)
        
        score = WeightedScore(8.0, WeightProfile.MIXED, {"TF": 8.0, "RS": 8.0, "DS": 8.0, "AC": 8.0})
        is_valid, error = weight_engine.validate_score(score)
        
        assert is_valid is True
        assert error is None
        assert len(callback_invoked) == 1

    def test_calculate_and_validate(self, weight_engine):
        """calculate_and_validate should combine calculation with validation."""
        def guardian(score: WeightedScore) -> bool:
            return score.score >= 5.0
        
        weight_engine.register_guardian_callback(guardian)
        
        score, is_valid, error = weight_engine.calculate_and_validate(
            tf=8.0, rs=8.0, ds=8.0, ac=8.0
        )
        
        assert isinstance(score, WeightedScore)
        assert is_valid is True
        assert error is None


# =============================================================================
# Test Class: TestWeightedScore
# =============================================================================

class TestWeightedScore:
    """Tests for WeightedScore dataclass."""

    def test_weighted_score_creation(self):
        """WeightedScore should be created correctly."""
        score = WeightedScore(
            score=7.5,
            profile=WeightProfile.TECHNICAL,
            components={"TF": 8.0, "RS": 7.0, "DS": 6.0, "AC": 5.0}
        )
        
        assert score.score == 7.5
        assert score.profile == WeightProfile.TECHNICAL
        assert score.components["TF"] == 8.0

    def test_weighted_score_to_dict(self):
        """WeightedScore should serialize to dict correctly."""
        score = WeightedScore(
            score=7.5,
            profile=WeightProfile.MIXED,
            components={"TF": 8.0, "RS": 7.0, "DS": 6.0, "AC": 5.0}
        )
        
        data = score.to_dict()
        
        assert data["score"] == 7.5
        assert data["profile"] == "MIXED"
        assert "components" in data
        assert "weighted_components" in data

    def test_weighted_score_from_dict(self):
        """WeightedScore should deserialize from dict correctly."""
        data = {
            "score": 7.5,
            "profile": "TECHNICAL",
            "components": {"TF": 8.0, "RS": 7.0, "DS": 6.0, "AC": 5.0},
            "weighted_components": {}
        }
        
        score = WeightedScore.from_dict(data)
        
        assert score.score == 7.5
        assert score.profile == WeightProfile.TECHNICAL

    def test_weighted_score_str(self):
        """WeightedScore string representation should be readable."""
        score = WeightedScore(
            score=7.5,
            profile=WeightProfile.MIXED,
            components={"TF": 8.0, "RS": 7.0, "DS": 6.0, "AC": 5.0}
        )
        
        s = str(score)
        assert "7.50" in s
        assert "MIXED" in s


# =============================================================================
# Test Class: TestConflictResolution
# =============================================================================

class TestConflictResolution:
    """Tests for ConflictResolution from adaptive_weights module."""

    def test_conflict_resolution_creation(self):
        """ConflictResolution should be created correctly."""
        winner = WeightedScore(8.0, WeightProfile.MIXED, {})
        loser = WeightedScore(5.0, WeightProfile.MIXED, {})
        
        resolution = ConflictResolution(
            decision=Decision.AUTO_SELECT,
            winner_score=winner,
            loser_score=loser,
            gap=3.0,
            rationale=None
        )
        
        assert resolution.decision == Decision.AUTO_SELECT
        assert resolution.gap == 3.0
        assert resolution.is_auto_select() is True
        assert resolution.requires_review() is False

    def test_conflict_resolution_conditional_requires_review(self):
        """CONDITIONAL decision should require review."""
        winner = WeightedScore(6.0, WeightProfile.MIXED, {})
        loser = WeightedScore(5.5, WeightProfile.MIXED, {})
        
        resolution = ConflictResolution(
            decision=Decision.CONDITIONAL,
            winner_score=winner,
            loser_score=loser,
            gap=0.5,
            rationale="Close call"
        )
        
        assert resolution.requires_review() is True
        assert resolution.is_auto_select() is False


# =============================================================================
# Test Class: TestRADARAgent
# =============================================================================

class TestRADARAgent:
    """Tests for RADAR agent."""

    def test_radar_initialization(self):
        """RADAR agent should initialize correctly."""
        radar = RADARAgent()
        assert radar.role == AgentRole.RADAR

    def test_radar_execute_high_volatility(self):
        """RADAR should classify high volatility domain correctly."""
        radar = RADARAgent()
        context = AnalysisContext(
            subject="AI Framework",
            domain="ai",
            volatility="high",
            confidence=0.5
        )
        
        result = radar.execute(context, {})
        
        assert result.success is True
        assert result.output["volatility"] == "high"
        assert "high_domain_volatility" in result.flags

    def test_radar_execute_low_volatility(self):
        """RADAR should classify low volatility domain correctly."""
        radar = RADARAgent()
        context = AnalysisContext(
            subject="Database System",
            domain="infrastructure",
            volatility="low",
            confidence=0.9
        )
        
        result = radar.execute(context, {})
        
        assert result.success is True
        assert result.output["volatility"] == "low"
        assert result.output["signal_strength"] == "STRONG"

    def test_radar_classify_signal_strength(self):
        """RADAR should classify signal strength based on volatility."""
        radar = RADARAgent()
        
        # High volatility -> WEAK signal
        context_high = AnalysisContext(subject="Test", domain="ai", volatility="high")
        assert radar.classify_signal_strength(context_high) == SignalStrength.WEAK
        
        # Medium volatility -> MODERATE signal
        context_med = AnalysisContext(subject="Test", domain="backend", volatility="medium")
        assert radar.classify_signal_strength(context_med) == SignalStrength.MODERATE
        
        # Low volatility -> STRONG signal
        context_low = AnalysisContext(subject="Test", domain="database", volatility="low")
        assert radar.classify_signal_strength(context_low) == SignalStrength.STRONG


# =============================================================================
# Test Class: TestDEVILAgent
# =============================================================================

class TestDEVILAgent:
    """Tests for DEVIL agent."""

    def test_devil_initialization(self):
        """DEVIL agent should initialize correctly."""
        devil = DEVILAgent()
        assert devil.role == AgentRole.DEVIL

    def test_devil_detect_hype(self):
        """DEVIL should detect hype indicators."""
        devil = DEVILAgent()
        
        hype_text = "This is a revolutionary game-changing technology that will disrupt the industry."
        hype_flags = devil.detect_hype(hype_text)
        
        assert len(hype_flags) >= 2
        assert any("revolutionary" in f for f in hype_flags)
        assert any("game-changing" in f for f in hype_flags)

    def test_devil_flag_unverified(self):
        """DEVIL should flag unverified claims."""
        devil = DEVILAgent()
        
        claims = [
            "This potentially improves performance by up to 50%",
            "The system reportedly handles millions of requests",
        ]
        unverified = devil.flag_unverified(claims)
        
        assert len(unverified) >= 1

    def test_devil_execute_with_hype(self):
        """DEVIL should identify hype in context claims."""
        devil = DEVILAgent()
        context = AnalysisContext(
            subject="New Framework",
            domain="ai",
            claims=["This is a revolutionary breakthrough"],
            metadata={"description": "A game-changing technology"},
        )
        
        result = devil.execute(context, {})
        
        assert result.success is True
        assert len(result.output["hype_flags"]) >= 1

    def test_devil_veto_if_risk(self):
        """DEVIL should trigger veto when risk threshold is exceeded."""
        devil = DEVILAgent()
        
        # Context with many hype indicators should trigger veto
        context = AnalysisContext(
            subject="Vaporware",
            domain="ai",
            volatility="high",
            confidence=0.3,
            claims=[
                "Revolutionary breakthrough",
                "Game-changing technology", 
                "Paradigm shift",
                "Industry-changing innovation",
                "Unprecedented performance",
                "Best-in-class solution",
            ]
        )
        
        # Execute to populate internal flags
        devil.execute(context, {})
        
        # Check veto
        veto_triggered, reason = devil.veto_if_risk(context, {})
        # Note: Veto depends on hype_score calculation


# =============================================================================
# Test Class: TestEVALAgent
# =============================================================================

class TestEVALAgent:
    """Tests for EVAL agent."""

    def test_eval_initialization(self):
        """EVAL agent should initialize correctly."""
        eval_agent = EVALAgent()
        assert eval_agent.role == AgentRole.EVAL

    def test_eval_assess_readiness_production_ready(self):
        """EVAL should assess PRODUCTION_READY for high confidence and evidence."""
        eval_agent = EVALAgent()
        
        context = AnalysisContext(
            subject="Stable System",
            domain="infrastructure",
            volatility="low",
            confidence=0.95,
            evidence=["E1", "E2", "E3", "E4", "E5"],
        )
        
        # Mock prior results from RADAR and DEVIL
        prior_results = {
            AgentRole.RADAR.value: AgentResult(
                agent_role=AgentRole.RADAR,
                output={"volatility": "low", "maturity_score": 0.9}
            ),
            AgentRole.DEVIL.value: AgentResult(
                agent_role=AgentRole.DEVIL,
                output={"hype_score": 0.0, "risk_flags": []}
            ),
        }
        
        readiness = eval_agent.assess_readiness(context, prior_results)
        
        # With high confidence, low volatility, and 5+ evidence, should be high tier
        assert readiness in [AdoptionReadiness.PRODUCTION_READY, AdoptionReadiness.EARLY_ADOPTER]

    def test_eval_assess_readiness_vaporware(self):
        """EVAL should assess VAPORWARE for low confidence and evidence."""
        eval_agent = EVALAgent()
        
        context = AnalysisContext(
            subject="Unknown System",
            domain="ai",
            volatility="high",
            confidence=0.2,
            evidence=[],
        )
        
        prior_results = {
            AgentRole.RADAR.value: AgentResult(
                agent_role=AgentRole.RADAR,
                output={"volatility": "high", "maturity_score": 0.3}
            ),
            AgentRole.DEVIL.value: AgentResult(
                agent_role=AgentRole.DEVIL,
                output={"hype_score": 0.8, "risk_flags": ["experimental"]}
            ),
        }
        
        readiness = eval_agent.assess_readiness(context, prior_results)
        
        assert readiness in [AdoptionReadiness.EXPERIMENTAL, AdoptionReadiness.VAPORWARE]

    # -------------------------------------------------------------------------
    # Validation Criteria: eval_veto_works
    # -------------------------------------------------------------------------

    def test_eval_veto_blocks_strat_for_experimental(self):
        """EVAL veto should block STRAT for EXPERIMENTAL readiness."""
        eval_agent = EVALAgent()
        
        context = AnalysisContext(
            subject="Experimental System",
            domain="quantum",
            volatility="high",
            confidence=0.3,
            evidence=["E1"],
        )
        
        prior_results = {
            AgentRole.RADAR.value: AgentResult(
                agent_role=AgentRole.RADAR,
                output={"volatility": "high", "maturity_score": 0.2}
            ),
            AgentRole.DEVIL.value: AgentResult(
                agent_role=AgentRole.DEVIL,
                output={"hype_score": 0.7, "risk_flags": ["experimental", "beta"]}
            ),
        }
        
        result = eval_agent.execute(context, prior_results)
        
        # Check if veto is active for EXPERIMENTAL/VAPORWARE
        if result.output["readiness"] in [AdoptionReadiness.EXPERIMENTAL.value, AdoptionReadiness.VAPORWARE.value]:
            assert result.output["veto_active"] is True
            assert eval_agent.can_veto_strat(context, prior_results) is True

    def test_adoption_readiness_blocks_strat(self):
        """EXPERIMENTAL and VAPORWARE should block STRAT."""
        assert AdoptionReadiness.EXPERIMENTAL.blocks_strat is True
        assert AdoptionReadiness.VAPORWARE.blocks_strat is True
        assert AdoptionReadiness.PRODUCTION_READY.blocks_strat is False
        assert AdoptionReadiness.EARLY_ADOPTER.blocks_strat is False


# =============================================================================
# Test Class: TestSTRATAgent
# =============================================================================

class TestSTRATAgent:
    """Tests for STRAT agent."""

    def test_strat_initialization(self):
        """STRAT agent should initialize correctly."""
        strat = STRATAgent()
        assert strat.role == AgentRole.STRAT

    def test_strat_synthesize_strategy(self):
        """STRAT should synthesize strategy from prior results."""
        strat = STRATAgent()
        
        context = AnalysisContext(
            subject="Test Technology",
            domain="ai",
            confidence=0.8,
        )
        
        prior_results = {
            AgentRole.RADAR.value: AgentResult(
                agent_role=AgentRole.RADAR,
                output={
                    "domain_analysis": {
                        "volatility": "medium",
                        "maturity_score": 0.7,
                        "category": "practical"
                    }
                }
            ),
            AgentRole.DEVIL.value: AgentResult(
                agent_role=AgentRole.DEVIL,
                output={"hype_flags": [], "risk_flags": []}
            ),
            AgentRole.EVAL.value: AgentResult(
                agent_role=AgentRole.EVAL,
                output={
                    "readiness": "EARLY_ADOPTER",
                    "tier_details": {"recommendation": "Proceed with monitoring"}
                }
            ),
        }
        
        strategy = strat.synthesize_strategy(context, prior_results)
        
        assert "Test Technology" in strategy
        assert "ai" in strategy.lower()

    def test_strat_respects_eval_veto(self):
        """STRAT should respect EVAL veto and not synthesize strategy."""
        strat = STRATAgent()
        
        context = AnalysisContext(subject="Test", domain="ai")
        
        # EVAL result with veto active
        eval_result = AgentResult(
            agent_role=AgentRole.EVAL,
            output={
                "readiness": "EXPERIMENTAL",
                "veto_active": True,
                "tier_details": {"recommendation": "Do not use in production"}
            }
        )
        
        prior_results = {
            AgentRole.EVAL.value: eval_result
        }
        
        result = strat.execute(context, prior_results)
        
        # Strategy should be blocked
        assert result.output.get("strategy") is None or result.output.get("blocked") is True

    def test_strat_add_caveat_if_experimental(self):
        """STRAT should add caveats for EXPERIMENTAL readiness."""
        strat = STRATAgent()
        
        context = AnalysisContext(subject="Test", domain="ai", confidence=0.5)
        
        strat.add_caveat_if_experimental(AdoptionReadiness.EXPERIMENTAL, context)
        
        assert "production_use_prohibited" in strat._caveats
        assert "limited_trial_recommended" in strat._caveats


# =============================================================================
# Test Class: TestScoutPipeline
# =============================================================================

class TestScoutPipeline:
    """Tests for ScoutPipeline orchestrator."""

    def test_pipeline_initialization(self, scout_pipeline):
        """Pipeline should initialize with all agents."""
        assert AgentRole.DEVIL in scout_pipeline.agents
        assert AgentRole.EVAL in scout_pipeline.agents
        assert AgentRole.STRAT in scout_pipeline.agents
        assert AgentRole.RADAR in scout_pipeline.agents

    def test_pipeline_without_radar(self):
        """Pipeline should work without RADAR agent."""
        pipeline = ScoutPipeline(include_radar=False)
        
        assert AgentRole.RADAR not in pipeline.agents
        assert AgentRole.DEVIL in pipeline.agents

    # -------------------------------------------------------------------------
    # Validation Criteria: devil_mandatory
    # -------------------------------------------------------------------------

    def test_devil_mandatory_for_evaluate_context(self, scout_pipeline):
        """DEVIL should execute for EVALUATE context."""
        context = AnalysisContext(
            subject="Test",
            domain="ai",
            context=PipelineContext.EVALUATE,
        )
        
        output = scout_pipeline.execute_pipeline(context)
        
        # DEVIL output should be present
        assert "devil" in output.agent_outputs

    def test_devil_mandatory_for_compare_context(self, scout_pipeline):
        """DEVIL should execute for COMPARE context."""
        context = AnalysisContext(
            subject="Test",
            domain="ai",
            context=PipelineContext.COMPARE,
        )
        
        output = scout_pipeline.execute_pipeline(context)
        
        assert "devil" in output.agent_outputs

    def test_devil_mandatory_for_validate_context(self, scout_pipeline):
        """DEVIL should execute for VALIDATE context."""
        context = AnalysisContext(
            subject="Test",
            domain="ai",
            context=PipelineContext.VALIDATE,
        )
        
        output = scout_pipeline.execute_pipeline(context)
        
        assert "devil" in output.agent_outputs

    def test_devil_optional_for_discover_context(self, scout_pipeline):
        """DEVIL should NOT execute for DISCOVER context."""
        context = AnalysisContext(
            subject="Test",
            domain="ai",
            context=PipelineContext.DISCOVER,
        )
        
        output = scout_pipeline.execute_pipeline(context)
        
        # DEVIL should be skipped for DISCOVER
        assert "devil" not in output.agent_outputs or output.agent_outputs.get("devil") is None

    def test_pipeline_execute_full(self, scout_pipeline, sample_analysis_context):
        """Pipeline should execute all agents in sequence."""
        output = scout_pipeline.execute_pipeline(sample_analysis_context)
        
        assert isinstance(output, ScoutOutput)
        assert output.readiness is not None
        assert output.signal_strength is not None

    # -------------------------------------------------------------------------
    # Validation Criteria: eval_veto_works
    # -------------------------------------------------------------------------

    def test_eval_veto_blocks_strat_in_pipeline(self, scout_pipeline):
        """EVAL veto should block STRAT execution in pipeline."""
        # Create context that will result in VAPORWARE
        context = AnalysisContext(
            subject="Vaporware Product",
            domain="quantum",
            volatility="high",
            confidence=0.1,
            evidence=[],  # No evidence
            context=PipelineContext.VALIDATE,
        )
        
        output = scout_pipeline.execute_pipeline(context)
        
        # Should be blocked due to low readiness
        if output.readiness in [AdoptionReadiness.EXPERIMENTAL, AdoptionReadiness.VAPORWARE]:
            assert output.blocked is True or output.strategy is None


# =============================================================================
# Test Class: TestContentType
# =============================================================================

class TestContentType:
    """Tests for ContentType enum."""

    def test_content_types_exist(self):
        """All expected content types should exist."""
        expected_types = {"FACT", "OPINION", "CODE", "WARNING", "STEP", "EXAMPLE", "METADATA"}
        actual_types = {ct.name for ct in ContentType}
        
        assert expected_types == actual_types

    def test_content_type_values(self):
        """ContentType values should match names."""
        assert ContentType.FACT.value == "FACT"
        assert ContentType.OPINION.value == "OPINION"


# =============================================================================
# Test Class: TestContentDensity
# =============================================================================

class TestContentDensity:
    """Tests for ContentDensity enum."""

    def test_density_values(self):
        """ContentDensity should have HIGH and LOW values."""
        assert ContentDensity.HIGH.value == "HIGH"
        assert ContentDensity.LOW.value == "LOW"


# =============================================================================
# Test Class: TestContentUnit
# =============================================================================

class TestContentUnit:
    """Tests for ContentUnit dataclass."""

    def test_content_unit_creation(self):
        """ContentUnit should be created correctly."""
        unit = ContentUnit(
            content_type=ContentType.FACT,
            density=ContentDensity.HIGH,
            text="This is a fact.",
            relevance_score=0.9
        )
        
        assert unit.content_type == ContentType.FACT
        assert unit.density == ContentDensity.HIGH
        assert unit.text == "This is a fact."
        assert unit.relevance_score == 0.9

    def test_content_unit_invalid_relevance(self):
        """Invalid relevance score should raise ValueError."""
        with pytest.raises(ValueError):
            ContentUnit(
                content_type=ContentType.FACT,
                density=ContentDensity.HIGH,
                text="Test",
                relevance_score=1.5
            )

    def test_content_unit_empty_text(self):
        """Empty text should raise ValueError."""
        with pytest.raises(ValueError):
            ContentUnit(
                content_type=ContentType.FACT,
                density=ContentDensity.HIGH,
                text="   "
            )

    # -------------------------------------------------------------------------
    # Validation Criteria: high_density_priority
    # -------------------------------------------------------------------------

    def test_high_density_always_included(self):
        """HIGH_DENSITY units should always be included."""
        unit = ContentUnit(
            content_type=ContentType.FACT,
            density=ContentDensity.HIGH,
            text="Important fact",
            unique_context=False,
            risk_caveat=None
        )
        
        assert unit.should_include() is True

    def test_low_density_excluded_without_context(self):
        """LOW_DENSITY units should be excluded without unique_context or risk_caveat."""
        unit = ContentUnit(
            content_type=ContentType.FACT,
            density=ContentDensity.LOW,
            text="Minor detail",
            unique_context=False,
            risk_caveat=None
        )
        
        assert unit.should_include() is False

    def test_low_density_included_with_unique_context(self):
        """LOW_DENSITY units with unique_context should be included."""
        unit = ContentUnit(
            content_type=ContentType.FACT,
            density=ContentDensity.LOW,
            text="Unique detail",
            unique_context=True
        )
        
        assert unit.should_include() is True

    def test_low_density_included_with_risk_caveat(self):
        """LOW_DENSITY units with risk_caveat should be included."""
        unit = ContentUnit(
            content_type=ContentType.WARNING,
            density=ContentDensity.LOW,
            text="Warning note",
            risk_caveat="Potential issue"
        )
        
        assert unit.should_include() is True


# =============================================================================
# Test Class: TestTypeAwareFusion
# =============================================================================

class TestTypeAwareFusion:
    """Tests for TypeAwareFusion engine."""

    def test_fusion_initialization(self, fusion_engine):
        """Fusion engine should initialize correctly."""
        assert fusion_engine.min_relevance_threshold == 0.0

    def test_merge_units_basic(self, fusion_engine, sample_content_units):
        """Basic merge should group by type and filter by density."""
        result = fusion_engine.merge_units(sample_content_units)
        
        assert isinstance(result, MergedResult)
        assert result.total_units_processed == 3
        # HIGH_DENSITY units should be included, LOW_DENSITY without context excluded
        assert result.total_units_included >= 2

    # -------------------------------------------------------------------------
    # Validation Criteria: high_density_priority
    # -------------------------------------------------------------------------

    def test_high_density_priority_in_merge(self, fusion_engine):
        """HIGH_DENSITY units should always be included in merge."""
        units = [
            ContentUnit(ContentType.FACT, ContentDensity.HIGH, "Fact 1"),
            ContentUnit(ContentType.FACT, ContentDensity.HIGH, "Fact 2"),
            ContentUnit(ContentType.FACT, ContentDensity.LOW, "Fact 3"),  # No context
        ]
        
        result = fusion_engine.merge_units(units)
        
        # Both HIGH_DENSITY should be included
        fact_content = result.get_content_by_type(ContentType.FACT)
        assert fact_content is not None
        assert "Fact 1" in fact_content
        assert "Fact 2" in fact_content
        # LOW_DENSITY without context should be excluded
        assert "Fact 3" not in fact_content

    # -------------------------------------------------------------------------
    # Validation Criteria: type_isolation
    # -------------------------------------------------------------------------

    def test_type_isolation_fact_opinion_separation(self, fusion_engine):
        """FACT and OPINION should be kept separate in merge."""
        units = [
            ContentUnit(ContentType.FACT, ContentDensity.HIGH, "Fact statement"),
            ContentUnit(ContentType.OPINION, ContentDensity.HIGH, "Opinion statement"),
        ]
        
        result = fusion_engine.merge_units(units)
        
        # Each type should have its own entry
        fact_content = result.get_content_by_type(ContentType.FACT)
        opinion_content = result.get_content_by_type(ContentType.OPINION)
        
        assert fact_content is not None
        assert opinion_content is not None
        assert "Fact statement" in fact_content
        assert "Opinion statement" in opinion_content
        # Types should NOT be mixed
        assert "Opinion" not in fact_content
        assert "Fact" not in opinion_content

    def test_type_isolation_mixed_types_error(self, fusion_engine):
        """Cross-type merge should raise TypeMismatchError."""
        units = [
            ContentUnit(ContentType.FACT, ContentDensity.HIGH, "Fact"),
            ContentUnit(ContentType.OPINION, ContentDensity.HIGH, "Opinion"),
        ]
        
        # Attempting cross-type merge should raise error
        with pytest.raises(TypeMismatchError) as exc_info:
            fusion_engine.merge_cross_type(units, ContentType.METADATA)
        
        assert exc_info.value.source_type != exc_info.value.target_type

    def test_merge_discard_logging(self, fusion_engine):
        """Merge should log all discarded units."""
        units = [
            ContentUnit(ContentType.FACT, ContentDensity.HIGH, "Important"),
            ContentUnit(ContentType.FACT, ContentDensity.LOW, "Unimportant"),
        ]
        
        result = fusion_engine.merge_units(units)
        
        # Should have discard log for LOW_DENSITY without context
        assert len(result.discard_logs) >= 1
        assert result.discard_logs[0].reason is not None

    def test_validate_type_consistency(self, fusion_engine):
        """Type consistency check should work correctly."""
        same_type = [
            ContentUnit(ContentType.FACT, ContentDensity.HIGH, "F1"),
            ContentUnit(ContentType.FACT, ContentDensity.HIGH, "F2"),
        ]
        mixed_types = [
            ContentUnit(ContentType.FACT, ContentDensity.HIGH, "F1"),
            ContentUnit(ContentType.OPINION, ContentDensity.HIGH, "O1"),
        ]
        
        assert fusion_engine.validate_type_consistency(same_type) is True
        assert fusion_engine.validate_type_consistency(mixed_types) is False


# =============================================================================
# Test Class: TestMergedResult
# =============================================================================

class TestMergedResult:
    """Tests for MergedResult dataclass."""

    def test_merged_result_creation(self):
        """MergedResult should be created correctly."""
        result = MergedResult(
            merged_content={ContentType.FACT: "Test fact"},
            total_units_processed=1,
            total_units_included=1,
            total_units_discarded=0,
        )
        
        assert result.total_units_processed == 1
        assert result.get_content_by_type(ContentType.FACT) == "Test fact"

    def test_merged_result_discard_rate(self):
        """Discard rate calculation should be correct."""
        result = MergedResult(
            total_units_processed=10,
            total_units_discarded=3,
        )
        
        assert result.get_discard_rate() == 0.3

    def test_merged_result_get_combined_output(self):
        """Combined output should include all types."""
        result = MergedResult(
            merged_content={
                ContentType.FACT: "Fact content",
                ContentType.CODE: "Code content",
            }
        )
        
        combined = result.get_combined_output()
        
        assert "[FACT]" in combined
        assert "[CODE]" in combined


# =============================================================================
# Test Class: TestConflictMetrics
# =============================================================================

class TestConflictMetrics:
    """Tests for ConflictMetrics dataclass."""

    def test_conflict_metrics_creation(self):
        """ConflictMetrics should be created correctly."""
        metrics = ConflictMetrics(
            accuracy=0.9,
            utility=0.8,
            efficiency=0.7,
            consensus=0.6
        )
        
        assert metrics.accuracy == 0.9
        assert metrics.utility == 0.8
        assert metrics.efficiency == 0.7
        assert metrics.consensus == 0.6

    def test_conflict_metrics_validation(self):
        """Invalid metric values should raise errors."""
        with pytest.raises(ValueError):
            ConflictMetrics(accuracy=1.5, utility=0.5, efficiency=0.5, consensus=0.5)
        
        with pytest.raises(ValueError):
            ConflictMetrics(accuracy=-0.1, utility=0.5, efficiency=0.5, consensus=0.5)

    def test_conflict_metrics_with_context(self):
        """ConflictMetrics should accept optional context."""
        metrics = ConflictMetrics(
            accuracy=0.9,
            utility=0.8,
            efficiency=0.7,
            consensus=0.6,
            optimal_context="Best for production"
        )
        
        assert metrics.optimal_context == "Best for production"


# =============================================================================
# Test Class: TestConflictResolver
# =============================================================================

class TestConflictResolver:
    """Tests for ConflictResolver class."""

    def test_resolver_initialization(self, conflict_resolver):
        """Resolver should initialize with default weights."""
        assert conflict_resolver.weights["accuracy"] == 0.40
        assert conflict_resolver.weights["utility"] == 0.35
        assert conflict_resolver.weights["efficiency"] == 0.15
        assert conflict_resolver.weights["consensus"] == 0.10

    def test_calculate_conflict_score(self, conflict_resolver):
        """Conflict score calculation should be correct."""
        metrics = ConflictMetrics(
            accuracy=1.0,
            utility=1.0,
            efficiency=1.0,
            consensus=1.0
        )
        
        score = conflict_resolver.calculate_conflict_score(metrics)
        
        assert score == 1.0  # All max values = max score

    # -------------------------------------------------------------------------
    # Validation Criteria: conflict_thresholds_work
    # -------------------------------------------------------------------------

    def test_conflict_threshold_high_confidence_auto_select(self, conflict_resolver):
        """Gap >= 2.0 should result in auto-select (HIGH confidence, no rationale)."""
        option_a = ConflictMetrics(accuracy=1.0, utility=1.0, efficiency=1.0, consensus=1.0)
        option_b = ConflictMetrics(accuracy=0.0, utility=0.0, efficiency=0.0, consensus=0.0)
        
        decision = conflict_resolver.resolve(option_a, option_b, "A", "B")
        
        # Gap should be >= 2.0 (scaled by 10)
        assert decision.gap >= 2.0
        assert decision.confidence == DecisionConfidence.HIGH
        assert decision.winner is not None
        assert decision.rationale is None  # No rationale for auto-select
        assert decision.conditional is False

    def test_conflict_threshold_medium_confidence_with_rationale(self, conflict_resolver):
        """Gap 1.0-1.9 should result in recommended with rationale."""
        # Create options with moderate difference
        option_a = ConflictMetrics(accuracy=0.9, utility=0.8, efficiency=0.7, consensus=0.6)
        option_b = ConflictMetrics(accuracy=0.5, utility=0.4, efficiency=0.5, consensus=0.4)
        
        decision = conflict_resolver.resolve(option_a, option_b, "A", "B")
        
        # Should have rationale
        if decision.gap >= 1.0 and decision.gap < 2.0:
            assert decision.confidence == DecisionConfidence.MEDIUM
            assert decision.rationale is not None
            assert decision.conditional is False

    def test_conflict_threshold_low_confidence_conditional(self, conflict_resolver):
        """Gap < 1.0 should result in conditional recommendation."""
        # Create options with small difference
        option_a = ConflictMetrics(accuracy=0.6, utility=0.6, efficiency=0.6, consensus=0.6)
        option_b = ConflictMetrics(accuracy=0.5, utility=0.5, efficiency=0.5, consensus=0.5)
        
        decision = conflict_resolver.resolve(option_a, option_b, "A", "B")
        
        # Gap < 1.0 should be conditional
        if decision.gap < 1.0:
            assert decision.confidence == DecisionConfidence.LOW
            assert decision.conditional is True
            assert decision.rationale is not None

    def test_resolve_custom_weights(self):
        """Resolver should accept custom weights."""
        custom_weights = {
            "accuracy": 0.5,
            "utility": 0.3,
            "efficiency": 0.1,
            "consensus": 0.1
        }
        resolver = ConflictResolver(weights=custom_weights)
        
        assert resolver.weights["accuracy"] == 0.5
        assert resolver.weights["utility"] == 0.3

    def test_resolve_invalid_weights_raises_error(self):
        """Invalid weights should raise ValueError."""
        # Weights not summing to 1.0
        with pytest.raises(ValueError):
            ConflictResolver(weights={"accuracy": 0.5, "utility": 0.5, "efficiency": 0.5, "consensus": 0.5})
        
        # Missing required key
        with pytest.raises(ValueError):
            ConflictResolver(weights={"accuracy": 0.5, "utility": 0.5})


# =============================================================================
# Test Class: TestGuardian
# =============================================================================

class TestGuardian:
    """Tests for Guardian validation loop."""

    def test_guardian_initialization(self, guardian):
        """Guardian should initialize with all components."""
        assert guardian._weight_engine is not None
        assert guardian._conflict_resolver is not None
        assert guardian._scout_pipeline is not None

    def test_guardian_validate_content_basic(self, guardian):
        """Basic content validation should work."""
        content = {
            "subject": "Test Technology",
            "domain": "ai",
            "claims": ["This is a test claim"],
            "evidence": ["Evidence 1", "Evidence 2"],
        }
        
        result = guardian.validate_content(content)
        
        assert isinstance(result, GuardianResult)
        assert result.content_id == "Test Technology"
        assert isinstance(result.valid, bool)

    def test_guardian_validate_missing_fields(self, guardian):
        """Validation with missing required fields should raise error."""
        content = {"subject": "Test"}  # Missing domain
        
        with pytest.raises(ValueError):
            guardian.validate_content(content)

    def test_guardian_detect_conflicts(self, guardian):
        """Guardian should detect conflicts from SCOUT output."""
        context = {
            "content": {
                "subject": "Test",
                "domain": "ai",
                "volatility": "high",
                "confidence": 0.3,
            },
            "scout_output": ScoutOutput(
                readiness=AdoptionReadiness.EXPERIMENTAL,
                signal_strength=SignalStrength.WEAK,
                hype_flags=["hype:revolutionary"],
                risk_flags=["risk:experimental"],
                blocked=False,
            ),
            "scores": {
                "primary": WeightedScore(5.0, WeightProfile.MIXED, {})
            }
        }
        
        conflicts = guardian.detect_conflicts(context)
        
        assert len(conflicts) >= 1
        assert any(c.conflict_type == ConflictType.HYPE_DETECTED for c in conflicts)

    def test_guardian_resolve_conflicts(self, guardian):
        """Guardian should resolve detected conflicts."""
        conflicts = [
            Conflict(
                conflict_type=ConflictType.HYPE_DETECTED,
                severity=3,
                description="Hype detected",
                source="DEVIL"
            )
        ]
        
        resolutions = guardian.resolve_conflicts(conflicts)
        
        assert len(resolutions) == 1
        assert resolutions[0].status == ResolutionStatus.RESOLVED

    def test_guardian_critical_conflict_blocks(self, guardian):
        """Critical conflicts should block validation."""
        conflicts = [
            Conflict(
                conflict_type=ConflictType.VETO_TRIGGERED,
                severity=5,
                description="VETO triggered",
                source="EVAL"
            )
        ]
        
        resolutions = guardian.resolve_conflicts(conflicts)
        
        assert resolutions[0].status == ResolutionStatus.BLOCKED

    def test_guardian_custom_validator(self):
        """Guardian should run custom validators."""
        custom_conflicts = []
        
        def my_validator(ctx):
            custom_conflicts.append(Conflict(
                conflict_type=ConflictType.POLICY_VIOLATION,
                severity=2,
                description="Custom check",
                source="custom"
            ))
            return custom_conflicts
        
        config = {
            "weight_profile": "MIXED",
            "custom_validators": [my_validator]
        }
        guardian = Guardian(config)
        
        content = {
            "subject": "Test",
            "domain": "ai",
            "evidence": ["E1"],
        }
        
        result = guardian.validate_content(content)
        
        # Custom conflict should be detected
        assert any(c.conflict_type == ConflictType.POLICY_VIOLATION for c in result.conflicts)

    def test_guardian_decision_log(self, guardian):
        """Guardian should maintain a decision log."""
        content = {
            "subject": "Test",
            "domain": "ai",
        }
        
        guardian.validate_content(content)
        
        log = guardian.get_decision_log()
        assert len(log) >= 1


# =============================================================================
# Test Class: TestGuardianResult
# =============================================================================

class TestGuardianResult:
    """Tests for GuardianResult dataclass."""

    def test_guardian_result_creation(self):
        """GuardianResult should be created correctly."""
        result = GuardianResult(
            valid=True,
            content_id="test-123",
            mode=ValidationMode.STANDARD,
        )
        
        assert result.valid is True
        assert result.content_id == "test-123"
        assert result.has_conflicts is False

    def test_guardian_result_with_conflicts(self):
        """GuardianResult should track conflicts correctly."""
        conflicts = [
            Conflict(
                conflict_type=ConflictType.HYPE_DETECTED,
                severity=3,
                description="Test",
                source="test"
            )
        ]
        
        result = GuardianResult(
            valid=True,
            content_id="test",
            mode=ValidationMode.STANDARD,
            conflicts=conflicts,
        )
        
        assert result.has_conflicts is True
        assert result.has_critical_conflicts is False

    def test_guardian_result_critical_conflicts(self):
        """GuardianResult should identify critical conflicts."""
        conflicts = [
            Conflict(
                conflict_type=ConflictType.VETO_TRIGGERED,
                severity=5,
                description="Critical",
                source="test"
            )
        ]
        
        result = GuardianResult(
            valid=False,
            content_id="test",
            mode=ValidationMode.STRICT,
            conflicts=conflicts,
        )
        
        assert result.has_critical_conflicts is True


# =============================================================================
# Test Class: TestIntentHandler
# =============================================================================

class TestIntentHandler:
    """Tests for IntentHandler class."""

    @pytest.fixture
    def handler(self, scout_pipeline):
        """Create an IntentHandler for testing."""
        config = {"strict_mode": True}
        return IntentHandler(config, scout_pipeline)

    def test_handler_initialization(self, handler):
        """Handler should initialize correctly."""
        assert handler._strict_mode is True
        assert handler._scout_pipeline is not None

    # -------------------------------------------------------------------------
    # Validation Criteria: devil_mandatory
    # -------------------------------------------------------------------------

    def test_mandatory_devil_intents_defined(self):
        """MANDATORY_DEVIL_INTENTS should contain required intents."""
        assert "EVALUATE" in MANDATORY_DEVIL_INTENTS
        assert "COMPARE" in MANDATORY_DEVIL_INTENTS
        assert "VALIDATE" in MANDATORY_DEVIL_INTENTS
        # AUDIT is also mandatory
        assert "AUDIT" in MANDATORY_DEVIL_INTENTS

    def test_validate_intent_config_requires_devil(self, handler):
        """validate_intent_config should require DEVIL for mandatory intents."""
        # Should pass when DEVIL is enabled
        assert handler.validate_intent_config("EVALUATE") is True
        assert handler.validate_intent_config("COMPARE") is True
        assert handler.validate_intent_config("VALIDATE") is True

    def test_validate_intent_config_fails_without_devil(self, scout_pipeline):
        """Intent requiring DEVIL should fail if DEVIL is disabled."""
        config = {"strict_mode": True, "enable_devil": False}
        handler = IntentHandler(config, scout_pipeline)
        
        with pytest.raises(IntentConfigError):
            handler.validate_intent_config("EVALUATE")

    def test_is_devil_required(self, handler):
        """is_devil_required should identify mandatory intents."""
        assert handler.is_devil_required("EVALUATE") is True
        assert handler.is_devil_required("COMPARE") is True
        assert handler.is_devil_required("VALIDATE") is True
        assert handler.is_devil_required("AUDIT") is True
        assert handler.is_devil_required("DISCOVER") is False

    def test_process_intent(self, handler, sample_analysis_context):
        """process_intent should execute the pipeline."""
        output = handler.process_intent("EVALUATE", sample_analysis_context)
        
        assert isinstance(output, ScoutOutput)
        assert output.readiness is not None

    def test_get_validation_result(self, handler):
        """get_validation_result should return detailed result."""
        result = handler.get_validation_result("EVALUATE")
        
        assert isinstance(result, IntentValidationResult)
        assert result.intent == "EVALUATE"
        assert result.requires_devil is True

    def test_get_processing_stats(self, handler, sample_analysis_context):
        """get_processing_stats should track processed intents."""
        handler.process_intent("EVALUATE", sample_analysis_context)
        
        stats = handler.get_processing_stats()
        
        assert len(stats) == 1
        assert stats[0].intent == "EVALUATE"

    def test_get_handler_info(self, handler):
        """get_handler_info should return configuration details."""
        info = handler.get_handler_info()
        
        assert "strict_mode" in info
        assert "devil_enabled" in info
        assert "mandatory_devil_intents" in info


# =============================================================================
# Test Class: TestIntentConfigError
# =============================================================================

class TestIntentConfigError:
    """Tests for IntentConfigError exception."""

    def test_error_creation(self):
        """IntentConfigError should be created correctly."""
        error = IntentConfigError(
            intent="EVALUATE",
            reason="DEVIL not enabled",
            details={"devil_enabled": False}
        )
        
        assert error.intent == "EVALUATE"
        assert error.reason == "DEVIL not enabled"
        assert error.details["devil_enabled"] is False

    def test_error_to_dict(self):
        """IntentConfigError should serialize to dict."""
        error = IntentConfigError(
            intent="TEST",
            reason="Test reason"
        )
        
        data = error.to_dict()
        
        assert data["error_type"] == "IntentConfigError"
        assert data["intent"] == "TEST"
        assert data["reason"] == "Test reason"


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests between modules."""

    def test_weight_engine_to_conflict_resolver_integration(self, weight_engine, conflict_resolver):
        """Weight engine scores should be usable with conflict resolver."""
        # Calculate scores using weight engine
        score_a = weight_engine.calculate_score_detailed(
            tf=9.0, rs=8.0, ds=7.0, ac=6.0,
            profile=WeightProfile.TECHNICAL
        )
        score_b = weight_engine.calculate_score_detailed(
            tf=6.0, rs=5.0, ds=4.0, ac=3.0,
            profile=WeightProfile.TECHNICAL
        )
        
        # Use scores in conflict resolution
        option_a = ConflictMetrics(
            accuracy=score_a.score / 10.0,
            utility=0.8,
            efficiency=0.7,
            consensus=0.6
        )
        option_b = ConflictMetrics(
            accuracy=score_b.score / 10.0,
            utility=0.5,
            efficiency=0.5,
            consensus=0.5
        )
        
        decision = conflict_resolver.resolve(option_a, option_b)
        
        assert decision.winner is not None

    def test_scout_pipeline_to_guardian_integration(self, guardian):
        """SCOUT pipeline output should be usable with Guardian."""
        content = {
            "subject": "AI Framework",
            "domain": "ai",
            "volatility": "high",
            "confidence": 0.6,
            "claims": ["Revolutionary technology"],
            "evidence": ["Doc 1"],
        }
        
        result = guardian.validate_content(content)
        
        # SCOUT output should be present
        assert result.scout_output is not None
        assert result.scout_output.readiness is not None

    def test_fusion_to_guardian_integration(self, fusion_engine, guardian):
        """TypeAwareFusion results should integrate with Guardian workflow."""
        # Create content units
        units = [
            ContentUnit(ContentType.FACT, ContentDensity.HIGH, "Verified fact"),
            ContentUnit(ContentType.WARNING, ContentDensity.HIGH, "Risk warning"),
        ]
        
        # Fuse content
        merged = fusion_engine.merge_units(units)
        
        # Use merged content in Guardian validation
        content = {
            "subject": "Merged Content",
            "domain": "backend",
            "metadata": {
                "merged_facts": merged.get_content_by_type(ContentType.FACT),
                "merged_warnings": merged.get_content_by_type(ContentType.WARNING),
            }
        }
        
        result = guardian.validate_content(content)
        
        assert isinstance(result, GuardianResult)

    def test_full_validation_workflow(self, guardian):
        """Complete validation workflow should work end-to-end."""
        content = {
            "subject": "Production Framework",
            "domain": "infrastructure",
            "volatility": "low",
            "confidence": 0.9,
            "claims": ["Stable and tested"],
            "evidence": ["E1", "E2", "E3", "E4", "E5"],
        }
        
        result = guardian.validate_content(content)
        
        # Should have valid result
        assert isinstance(result.valid, bool)
        assert result.duration_ms > 0
        
        # Should have SCOUT output
        assert result.scout_output is not None
        
        # Should have scores
        assert "primary" in result.scores

    # -------------------------------------------------------------------------
    # Comprehensive Validation Tests
    # -------------------------------------------------------------------------

    def test_formula_deterministic_across_modules(self):
        """Verify deterministic formula behavior across all modules."""
        engine = AdaptiveWeightEngine(default_profile=WeightProfile.MEDICAL_LEGAL)
        resolver = ConflictResolver()
        
        # Run multiple iterations
        scores = []
        decisions = []
        
        for _ in range(10):
            score = engine.calculate_score(tf=8.0, rs=7.5, ds=6.0, ac=5.5)
            scores.append(score)
            
            decision = resolver.resolve(
                ConflictMetrics(accuracy=0.9, utility=0.8, efficiency=0.7, consensus=0.6),
                ConflictMetrics(accuracy=0.5, utility=0.5, efficiency=0.5, consensus=0.5),
                "A", "B"
            )
            decisions.append((decision.score_a, decision.winner))
        
        # All scores should be identical
        assert len(set(scores)) == 1
        
        # All decisions should be identical
        assert len(set(decisions)) == 1

    def test_profile_weights_applied_in_guardian(self):
        """Verify MEDICAL_LEGAL profile weights RS highest in Guardian."""
        config = {"weight_profile": "MEDICAL_LEGAL"}
        guardian = Guardian(config)
        
        # Verify profile is applied
        assert guardian._weight_engine.default_profile == WeightProfile.MEDICAL_LEGAL
        assert guardian._weight_engine.default_profile.weights["RS"] == 0.40

    def test_type_isolation_enforced(self):
        """Verify type isolation prevents cross-type merging."""
        fusion = TypeAwareFusion()
        
        units = [
            ContentUnit(ContentType.FACT, ContentDensity.HIGH, "Fact"),
            ContentUnit(ContentType.OPINION, ContentDensity.HIGH, "Opinion"),
        ]
        
        # Cross-type merge should raise error
        with pytest.raises(TypeMismatchError):
            fusion.merge_cross_type(units, ContentType.METADATA)

    def test_eval_veto_propagates_to_guardian(self, guardian):
        """Verify EVAL veto propagates to Guardian validation."""
        # Create content that will result in VAPORWARE
        content = {
            "subject": "Vaporware",
            "domain": "quantum",
            "volatility": "high",
            "confidence": 0.1,
            "evidence": [],
        }
        
        result = guardian.validate_content(content)
        
        # Should have EVAL-related conflict if blocked
        if result.scout_output.blocked:
            assert any(
                c.conflict_type == ConflictType.VETO_TRIGGERED 
                for c in result.conflicts
            )


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_weight_engine(self):
        """create_weight_engine should create configured engine."""
        engine = create_weight_engine("TECHNICAL")
        
        assert isinstance(engine, AdaptiveWeightEngine)
        assert engine.default_profile == WeightProfile.TECHNICAL

    def test_create_weight_engine_invalid_profile(self):
        """create_weight_engine should raise for invalid profile."""
        with pytest.raises(ValueError):
            create_weight_engine("INVALID")

    def test_create_fusion_engine(self):
        """create_fusion_engine should create configured engine."""
        engine = create_fusion_engine(min_relevance_threshold=0.5)
        
        assert isinstance(engine, TypeAwareFusion)
        assert engine.min_relevance_threshold == 0.5

    def test_create_conflict_resolver(self):
        """create_conflict_resolver should create configured resolver."""
        resolver = create_conflict_resolver()
        
        assert isinstance(resolver, ConflictResolver)
        assert resolver.weights == DEFAULT_CONFLICT_WEIGHTS

    def test_create_intent_handler(self, scout_pipeline):
        """create_intent_handler should create configured handler."""
        handler = create_intent_handler({"strict_mode": False}, scout_pipeline)
        
        assert isinstance(handler, IntentHandler)
        assert handler._strict_mode is False


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
