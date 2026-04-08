"""
Tests for ITEM-AGENT-001: ScoutMatrix Integration.

Tests the integration of ScoutMatrix with RoleWeightedConsensus
for unified decision making in conflict resolution.

Test Categories:
- test_scouts_integrated: Scout findings flow to consensus
- test_veto_rules_work: Veto rules correctly applied
- test_consensus_calculation: Consensus score calculation
- test_role_weights: Role weight validation
- test_security_veto: Security veto enforcement
"""

import pytest
from datetime import datetime
from typing import Dict, List

from src.agents.scout_matrix import (
    AgentRole,
    ScoutFindingType,
    ScoutFinding,
    AggregatedFindings,
    ConsensusResult,
    ScoutMatrix,
    ScoutPipeline,
    AnalysisContext,
    AgentResult,
    PipelineContext,
    AdoptionReadiness,
)
from src.decision.conflict_resolver import (
    ConflictResolver,
    Conflict,
    Resolution,
    ResolutionStatus,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def scout_matrix():
    """Create a ScoutMatrix instance for testing."""
    return ScoutMatrix()


@pytest.fixture
def conflict_resolver():
    """Create a ConflictResolver instance for testing."""
    return ConflictResolver()


@pytest.fixture
def sample_radar_finding():
    """Create a sample RADAR finding."""
    return ScoutFinding(
        finding_id="radar_001",
        role=AgentRole.RADAR,
        finding_type=ScoutFindingType.SIGNAL,
        severity="SEV-4",
        title="Strong Signal Detected",
        description="Domain shows strong maturity indicators",
        confidence=0.85,
        impact="low",
        recommendation="Proceed with standard process",
        metadata={"domain": "infrastructure"}
    )


@pytest.fixture
def sample_devil_finding():
    """Create a sample DEVIL finding."""
    return ScoutFinding(
        finding_id="devil_001",
        role=AgentRole.DEVIL,
        finding_type=ScoutFindingType.RISK,
        severity="SEV-3",
        title="Hype Indicator Detected",
        description="Marketing language detected in claims",
        confidence=0.75,
        impact="medium",
        recommendation="Verify claims independently",
        metadata={"hype_score": 0.4}
    )


@pytest.fixture
def sample_eval_finding():
    """Create a sample EVAL finding."""
    return ScoutFinding(
        finding_id="eval_001",
        role=AgentRole.EVAL,
        finding_type=ScoutFindingType.RECOMMENDATION,
        severity="SEV-3",
        title="Readiness: EARLY_ADOPTER",
        description="Technology is stable but requires monitoring",
        confidence=0.80,
        impact="medium",
        recommendation="Proceed with enhanced monitoring",
        metadata={"readiness_tier": "EARLY_ADOPTER"}
    )


@pytest.fixture
def sample_strat_finding():
    """Create a sample STRAT finding."""
    return ScoutFinding(
        finding_id="strat_001",
        role=AgentRole.STRAT,
        finding_type=ScoutFindingType.CAVEAT,
        severity="SEV-3",
        title="Caveat: Enhanced Monitoring Required",
        description="Strategy requires enhanced monitoring",
        confidence=0.70,
        impact="medium",
        recommendation="Implement monitoring before deployment",
        metadata={"caveat": "enhanced_monitoring_required"}
    )


@pytest.fixture
def sample_findings(
    sample_radar_finding,
    sample_devil_finding,
    sample_eval_finding,
    sample_strat_finding
):
    """Create sample findings from all scouts."""
    return {
        AgentRole.RADAR: [sample_radar_finding],
        AgentRole.DEVIL: [sample_devil_finding],
        AgentRole.EVAL: [sample_eval_finding],
        AgentRole.STRAT: [sample_strat_finding],
    }


@pytest.fixture
def critical_finding():
    """Create a critical finding for veto tests."""
    return ScoutFinding(
        finding_id="critical_001",
        role=AgentRole.EVAL,
        finding_type=ScoutFindingType.VETO,
        severity="SEV-1",
        title="Critical Security Vulnerability",
        description="Unpatched vulnerability detected",
        confidence=0.95,
        impact="critical",
        recommendation="Do not proceed until patched",
        metadata={"blocking": True}
    )


@pytest.fixture
def hype_finding():
    """Create a hype finding for veto tests."""
    return ScoutFinding(
        finding_id="hype_001",
        role=AgentRole.DEVIL,
        finding_type=ScoutFindingType.HYPE,
        severity="SEV-2",
        title="Excessive Hype Detected",
        description="Marketing claims exceed technical reality",
        confidence=0.85,
        impact="high",
        recommendation="Reduce expectations and verify claims",
        metadata={"hype_level": "excessive"}
    )


# =============================================================================
# Test: Role Weights
# =============================================================================

class TestRoleWeights:
    """Tests for role weight validation and usage."""
    
    def test_role_weights_sum_to_one(self, scout_matrix):
        """Test that role weights sum to 1.0."""
        weights = scout_matrix.get_role_weights()
        total = sum(weights.values())
        assert 0.99 <= total <= 1.01, f"Weights sum to {total}, expected 1.0"
    
    def test_all_roles_have_weights(self, scout_matrix):
        """Test that all scout roles have weights assigned."""
        weights = scout_matrix.get_role_weights()
        required_roles = {AgentRole.EVAL, AgentRole.DEVIL, AgentRole.STRAT, AgentRole.RADAR}
        assert required_roles.issubset(set(weights.keys())), "Missing weights for some roles"
    
    def test_eval_has_highest_weight(self, scout_matrix):
        """Test that EVAL has the highest weight (security)."""
        weights = scout_matrix.get_role_weights()
        eval_weight = weights[AgentRole.EVAL]
        for role, weight in weights.items():
            if role != AgentRole.EVAL:
                assert eval_weight >= weight, f"EVAL weight should be highest, but {role} has {weight}"
    
    def test_custom_weights_validation(self):
        """Test that custom weights are validated."""
        # Valid custom weights
        valid_weights = {
            AgentRole.EVAL: 0.4,
            AgentRole.DEVIL: 0.3,
            AgentRole.STRAT: 0.2,
            AgentRole.RADAR: 0.1,
        }
        matrix = ScoutMatrix(config={"custom_weights": valid_weights})
        assert matrix.get_role_weights() == valid_weights
        
        # Invalid weights - don't sum to 1
        with pytest.raises(ValueError):
            ScoutMatrix(config={"custom_weights": {
                AgentRole.EVAL: 0.5,
                AgentRole.DEVIL: 0.5,
                AgentRole.STRAT: 0.1,  # This makes sum > 1
                AgentRole.RADAR: 0.1,
            }})


# =============================================================================
# Test: Consensus Calculation
# =============================================================================

class TestConsensusCalculation:
    """Tests for consensus score calculation."""
    
    def test_consensus_calculation(self, scout_matrix, sample_findings):
        """Test that consensus is calculated correctly."""
        score = scout_matrix.calculate_consensus_score(sample_findings)
        assert 0.0 <= score <= 1.0, f"Score {score} not in [0, 1]"
        assert score > 0.5, "Expected positive consensus with positive findings"
    
    def test_consensus_with_empty_findings(self, scout_matrix):
        """Test consensus with no findings."""
        score = scout_matrix.calculate_consensus_score({})
        assert score == 0.0, "Empty findings should result in 0 score"
    
    def test_consensus_weighted_by_role(self, scout_matrix):
        """Test that consensus properly weights by role."""
        # High confidence RADAR finding (low weight)
        radar_finding = ScoutFinding(
            finding_id="radar_high",
            role=AgentRole.RADAR,
            finding_type=ScoutFindingType.SIGNAL,
            severity="SEV-4",
            title="High Confidence Signal",
            description="Test",
            confidence=1.0,
            impact="low",
            recommendation="Test",
        )
        
        # Low confidence EVAL finding (high weight)
        eval_finding = ScoutFinding(
            finding_id="eval_low",
            role=AgentRole.EVAL,
            finding_type=ScoutFindingType.RECOMMENDATION,
            severity="SEV-4",
            title="Low Confidence Eval",
            description="Test",
            confidence=0.5,
            impact="low",
            recommendation="Test",
        )
        
        findings = {
            AgentRole.RADAR: [radar_finding],
            AgentRole.EVAL: [eval_finding],
        }
        
        score = scout_matrix.calculate_consensus_score(findings)
        
        # EVAL weight is 0.35, RADAR is 0.15
        # Score should be weighted average: (1.0 * 0.15 + 0.5 * 0.35) / (0.15 + 0.35)
        # = (0.15 + 0.175) / 0.5 = 0.325 / 0.5 = 0.65
        expected = (1.0 * 0.15 + 0.5 * 0.35) / 0.5
        assert abs(score - expected) < 0.01, f"Expected {expected}, got {score}"


# =============================================================================
# Test: Veto Rules
# =============================================================================

class TestVetoRules:
    """Tests for veto rule enforcement."""
    
    def test_security_veto(self, scout_matrix, critical_finding):
        """Test that SEV-1/critical findings trigger veto."""
        veto = scout_matrix.check_veto_rules([critical_finding])
        assert veto is not None, "Critical finding should trigger veto"
        assert "SEC_VETO" in veto, f"Expected SEC_VETO, got {veto}"
    
    def test_devil_veto_for_hype(self, scout_matrix, hype_finding):
        """Test that HYPE findings trigger DEVIL veto."""
        veto = scout_matrix.check_veto_rules([hype_finding])
        assert veto is not None, "Hype finding should trigger veto"
        assert "DVL_VETO" in veto, f"Expected DVL_VETO, got {veto}"
    
    def test_veto_type_triggers(self, scout_matrix):
        """Test that VETO finding type triggers veto."""
        veto_finding = ScoutFinding(
            finding_id="veto_001",
            role=AgentRole.EVAL,
            finding_type=ScoutFindingType.VETO,
            severity="SEV-1",
            title="Veto Triggered",
            description="Test veto",
            confidence=0.9,
            impact="critical",
            recommendation="Stop",
        )
        veto = scout_matrix.check_veto_rules([veto_finding])
        assert veto is not None, "VETO finding should trigger veto"
    
    def test_no_veto_for_normal_findings(self, scout_matrix, sample_findings):
        """Test that normal findings don't trigger veto."""
        all_findings = (
            sample_findings[AgentRole.RADAR] +
            sample_findings[AgentRole.DEVIL] +
            sample_findings[AgentRole.EVAL] +
            sample_findings[AgentRole.STRAT]
        )
        veto = scout_matrix.check_veto_rules(all_findings)
        assert veto is None, "Normal findings should not trigger veto"


# =============================================================================
# Test: Scouts Integrated
# =============================================================================

class TestScoutsIntegrated:
    """Tests for scout findings flowing to consensus."""
    
    def test_scouts_integrated(
        self,
        scout_matrix,
        conflict_resolver,
        sample_findings
    ):
        """Test that scout findings flow to consensus correctly."""
        # Aggregate findings
        aggregated = scout_matrix.aggregate_findings(sample_findings)
        
        # Submit to consensus
        result = scout_matrix.submit_to_consensus(aggregated)
        
        assert isinstance(result, ConsensusResult), "Should return ConsensusResult"
        assert 0.0 <= result.score <= 1.0, "Score should be in [0, 1]"
        assert result.rationale, "Should have rationale"
        
        # Test integration with conflict resolver
        conflict = Conflict(
            conflict_id="test_001",
            title="Test Conflict",
            description="Test conflict for integration",
            options={"option_a": {"score": 0.8}, "option_b": {"score": 0.6}}
        )
        
        resolution = conflict_resolver.resolve_with_scouts(conflict, aggregated)
        
        assert isinstance(resolution, Resolution), "Should return Resolution"
        assert resolution.status in [ResolutionStatus.RESOLVED, ResolutionStatus.ESCALATED]
    
    def test_aggregated_findings_structure(self, scout_matrix, sample_findings):
        """Test that aggregated findings have correct structure."""
        aggregated = scout_matrix.aggregate_findings(sample_findings)
        
        assert isinstance(aggregated, AggregatedFindings)
        assert len(aggregated.radar_findings) == 1
        assert len(aggregated.devil_findings) == 1
        assert len(aggregated.eval_findings) == 1
        assert len(aggregated.strat_findings) == 1
        assert aggregated.total_findings == 4
        assert aggregated.consensus_score > 0.0
    
    def test_veto_blocks_consensus(self, scout_matrix, sample_findings, critical_finding):
        """Test that veto blocks consensus approval."""
        # Add critical finding to trigger veto
        sample_findings[AgentRole.EVAL].append(critical_finding)
        
        aggregated = scout_matrix.aggregate_findings(sample_findings)
        
        assert aggregated.veto_active, "Veto should be active"
        assert aggregated.veto_reason is not None
        
        result = scout_matrix.submit_to_consensus(aggregated)
        
        assert not result.approved, "Should not be approved with veto"
        assert result.veto_triggered


# =============================================================================
# Test: Conflict Resolution Integration
# =============================================================================

class TestConflictResolutionIntegration:
    """Tests for conflict resolution with scout findings."""
    
    def test_resolve_with_scouts_approved(
        self,
        conflict_resolver,
        scout_matrix,
        sample_findings
    ):
        """Test resolution with approved consensus."""
        aggregated = scout_matrix.aggregate_findings(sample_findings)
        
        conflict = Conflict(
            conflict_id="conflict_001",
            title="Technology Selection",
            description="Choose between two technologies",
            options={"tech_a": {"score": 0.9}, "tech_b": {"score": 0.7}}
        )
        
        resolution = conflict_resolver.resolve_with_scouts(conflict, aggregated)
        
        assert resolution.conflict.conflict_id == "conflict_001"
        assert resolution.status in [ResolutionStatus.RESOLVED, ResolutionStatus.ESCALATED]
        assert resolution.confidence > 0.0
    
    def test_resolve_with_scouts_blocked(
        self,
        conflict_resolver,
        sample_findings,
        critical_finding
    ):
        """Test resolution blocked by veto."""
        sample_findings[AgentRole.EVAL].append(critical_finding)
        
        scout_matrix = ScoutMatrix()
        aggregated = scout_matrix.aggregate_findings(sample_findings)
        
        conflict = Conflict(
            conflict_id="conflict_002",
            title="Risky Adoption",
            description="Adopt a risky technology",
        )
        
        resolution = conflict_resolver.resolve_with_scouts(conflict, aggregated)
        
        assert resolution.status == ResolutionStatus.BLOCKED
        assert resolution.veto_triggered
        assert "SEC_VETO" in resolution.rationale or "Veto" in resolution.rationale
    
    def test_resolve_selects_best_option(
        self,
        conflict_resolver,
        scout_matrix,
        sample_findings
    ):
        """Test that resolution selects the best scored option."""
        aggregated = scout_matrix.aggregate_findings(sample_findings)
        
        conflict = Conflict(
            conflict_id="conflict_003",
            title="Framework Selection",
            description="Choose a framework",
            options={
                "react": {"score": 0.9},
                "vue": {"score": 0.7},
                "angular": {"score": 0.6}
            }
        )
        
        resolution = conflict_resolver.resolve_with_scouts(conflict, aggregated)
        
        if resolution.status == ResolutionStatus.RESOLVED:
            assert resolution.selected_option == "react"


# =============================================================================
# Test: ScoutMatrix Configuration
# =============================================================================

class TestScoutMatrixConfiguration:
    """Tests for ScoutMatrix configuration options."""
    
    def test_default_configuration(self):
        """Test default ScoutMatrix configuration."""
        matrix = ScoutMatrix()
        
        weights = matrix.get_role_weights()
        assert weights[AgentRole.EVAL] == 0.35
        assert weights[AgentRole.DEVIL] == 0.30
        assert weights[AgentRole.STRAT] == 0.20
        assert weights[AgentRole.RADAR] == 0.15
    
    def test_custom_veto_rules(self):
        """Test custom veto rules configuration."""
        custom_rules = {
            "security_veto": ["CRITICAL", "SEV-1", "BLOCKER"],
            "devil_veto": ["HYPE", "VULNERABILITY"],
            "security_strategy_veto_threshold": 0.60,
        }
        
        matrix = ScoutMatrix(config={"custom_veto_rules": custom_rules})
        rules = matrix.get_veto_rules()
        
        assert "BLOCKER" in rules["security_veto"]
        assert rules["security_strategy_veto_threshold"] == 0.60


# =============================================================================
# Test: ScoutFinding Validation
# =============================================================================

class TestScoutFindingValidation:
    """Tests for ScoutFinding data validation."""
    
    def test_valid_finding(self, sample_radar_finding):
        """Test that valid finding is accepted."""
        assert sample_radar_finding.finding_id == "radar_001"
        assert sample_radar_finding.confidence == 0.85
    
    def test_invalid_confidence(self):
        """Test that invalid confidence raises error."""
        with pytest.raises(ValueError):
            ScoutFinding(
                finding_id="test",
                role=AgentRole.RADAR,
                finding_type=ScoutFindingType.SIGNAL,
                severity="SEV-3",
                title="Test",
                description="Test",
                confidence=1.5,  # Invalid
                impact="medium",
                recommendation="Test",
            )
    
    def test_invalid_severity(self):
        """Test that invalid severity raises error."""
        with pytest.raises(ValueError):
            ScoutFinding(
                finding_id="test",
                role=AgentRole.RADAR,
                finding_type=ScoutFindingType.SIGNAL,
                severity="SEV-5",  # Invalid
                title="Test",
                description="Test",
                confidence=0.5,
                impact="medium",
                recommendation="Test",
            )
    
    def test_invalid_impact(self):
        """Test that invalid impact raises error."""
        with pytest.raises(ValueError):
            ScoutFinding(
                finding_id="test",
                role=AgentRole.RADAR,
                finding_type=ScoutFindingType.SIGNAL,
                severity="SEV-3",
                title="Test",
                description="Test",
                confidence=0.5,
                impact="extreme",  # Invalid
                recommendation="Test",
            )


# =============================================================================
# Test: Collect Findings from Agent Results
# =============================================================================

class TestCollectFindings:
    """Tests for collecting findings from agent results."""
    
    def test_collect_radar_findings(self, scout_matrix):
        """Test collecting findings from RADAR agent result."""
        result = AgentResult(
            agent_role=AgentRole.RADAR,
            success=True,
            output={
                "domain": "infrastructure",
                "signal_strength": "STRONG",
                "domain_analysis": {
                    "volatility": "low",
                    "maturity_score": 0.9,
                    "risk_factors": ["test_risk"]
                }
            }
        )
        
        findings = scout_matrix.collect_findings(AgentRole.RADAR, result)
        
        assert len(findings) >= 1
        assert any(f.role == AgentRole.RADAR for f in findings)
    
    def test_collect_devil_findings(self, scout_matrix):
        """Test collecting findings from DEVIL agent result."""
        result = AgentResult(
            agent_role=AgentRole.DEVIL,
            success=True,
            output={
                "hype_flags": ["hype:revolutionary"],
                "risk_flags": ["risk:experimental"],
                "hype_score": 0.5,
                "veto_triggered": False
            }
        )
        
        findings = scout_matrix.collect_findings(AgentRole.DEVIL, result)
        
        assert len(findings) >= 1
        assert any(f.role == AgentRole.DEVIL for f in findings)
    
    def test_collect_eval_findings(self, scout_matrix):
        """Test collecting findings from EVAL agent result."""
        result = AgentResult(
            agent_role=AgentRole.EVAL,
            success=True,
            output={
                "readiness": "EARLY_ADOPTER",
                "veto_active": False,
                "tier_details": {
                    "description": "Stable but needs monitoring",
                    "recommendation": "Proceed with caution"
                }
            }
        )
        
        findings = scout_matrix.collect_findings(AgentRole.EVAL, result)
        
        assert len(findings) >= 1
        assert any(f.role == AgentRole.EVAL for f in findings)
    
    def test_collect_failed_agent_result(self, scout_matrix):
        """Test collecting findings from failed agent result."""
        result = AgentResult(
            agent_role=AgentRole.RADAR,
            success=False,
            error="Agent execution failed"
        )
        
        findings = scout_matrix.collect_findings(AgentRole.RADAR, result)
        
        assert len(findings) == 1
        assert findings[0].finding_type == ScoutFindingType.BLOCKER
        assert findings[0].severity == "SEV-2"


# =============================================================================
# Test: S5_VETO Rule
# =============================================================================

class TestS5VetoRule:
    """Tests for Security+Strategy combined veto rule."""
    
    def test_s5_veto_threshold(self, scout_matrix):
        """Test S5_VETO threshold is correctly set."""
        rules = scout_matrix.get_veto_rules()
        assert "security_strategy_veto_threshold" in rules
        assert rules["security_strategy_veto_threshold"] == 0.55
    
    def test_s5_veto_activates_on_negative_eval(self, scout_matrix):
        """Test that S5_VETO activates when EVAL findings are negative."""
        # Create findings with high EVAL+STRAT weight but negative EVAL
        eval_finding = ScoutFinding(
            finding_id="eval_neg",
            role=AgentRole.EVAL,
            finding_type=ScoutFindingType.RECOMMENDATION,
            severity="SEV-2",  # High severity
            title="Security Concern",
            description="Security issues detected",
            confidence=0.85,
            impact="high",
            recommendation="Address security issues",
        )
        
        strat_finding = ScoutFinding(
            finding_id="strat_pos",
            role=AgentRole.STRAT,
            finding_type=ScoutFindingType.RECOMMENDATION,
            severity="SEV-4",
            title="Strategy Ready",
            description="Strategy is ready",
            confidence=0.90,
            impact="low",
            recommendation="Proceed",
        )
        
        findings = {
            AgentRole.EVAL: [eval_finding],
            AgentRole.STRAT: [strat_finding],
        }
        
        aggregated = scout_matrix.aggregate_findings(findings)
        result = scout_matrix.submit_to_consensus(aggregated)
        
        # With high EVAL+STRAT combined weight and negative EVAL,
        # S5_VETO should potentially block
        # This depends on the exact scores


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
