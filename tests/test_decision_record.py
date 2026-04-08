"""
Tests for ITEM-ART-002: Decision Record Enforcement.

Tests cover:
- DecisionRecordManager functionality
- Decision recording
- Artifact generation
- Integration with ConflictResolver
- GATE-05 blocking behavior
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from src.decision.decision_record import (
    DecisionType,
    Decision,
    DecisionRecordArtifact,
    DecisionRecordManager,
    create_decision_record_manager,
    write_decision_record,
)


class TestDecisionType:
    """Tests for DecisionType enum."""
    
    def test_decision_type_values(self):
        """Test that all decision types have correct values."""
        assert DecisionType.CONFLICT_RESOLUTION.value == "conflict_resolution"
        assert DecisionType.GATE_DECISION.value == "gate_decision"
        assert DecisionType.ROUTING_DECISION.value == "routing_decision"
        assert DecisionType.POLICY_DECISION.value == "policy_decision"
        assert DecisionType.MERGE_DECISION.value == "merge_decision"
        assert DecisionType.SCALING_DECISION.value == "scaling_decision"
        assert DecisionType.ABORT_DECISION.value == "abort_decision"
        assert DecisionType.ROLLBACK_DECISION.value == "rollback_decision"
    
    def test_decision_type_count(self):
        """Test that we have expected number of decision types."""
        assert len(DecisionType) == 8


class TestDecision:
    """Tests for Decision dataclass."""
    
    def test_decision_creation(self):
        """Test creating a decision."""
        decision = Decision(
            decision_id="DEC-test1234-0001",
            decision_type=DecisionType.CONFLICT_RESOLUTION,
            timestamp="2024-01-15T10:30:00Z",
            context={"file": "test.py"},
            options_considered=[{"label": "A"}, {"label": "B"}],
            selected_option="A",
            rationale="Better option",
            confidence=0.85,
            session_id="test-session"
        )
        
        assert decision.decision_id == "DEC-test1234-0001"
        assert decision.decision_type == DecisionType.CONFLICT_RESOLUTION
        assert decision.confidence == 0.85
        assert decision.gate_id is None
        assert decision.conflict_id is None
    
    def test_decision_with_gate_id(self):
        """Test decision with gate ID."""
        decision = Decision(
            decision_id="DEC-test-0001",
            decision_type=DecisionType.GATE_DECISION,
            timestamp="2024-01-15T10:30:00Z",
            context={},
            options_considered=[],
            selected_option="pass",
            rationale="All checks passed",
            confidence=1.0,
            session_id="test-session",
            gate_id="GATE-03"
        )
        
        assert decision.gate_id == "GATE-03"
    
    def test_decision_confidence_validation(self):
        """Test that confidence must be in valid range."""
        # Valid confidence
        decision = Decision(
            decision_id="DEC-test-0001",
            decision_type=DecisionType.CONFLICT_RESOLUTION,
            timestamp="2024-01-15T10:30:00Z",
            context={},
            options_considered=[],
            selected_option="A",
            rationale="Test",
            confidence=0.5,
            session_id="test-session"
        )
        assert decision.confidence == 0.5
        
        # Invalid confidence - too high
        with pytest.raises(ValueError, match="confidence"):
            Decision(
                decision_id="DEC-test-0001",
                decision_type=DecisionType.CONFLICT_RESOLUTION,
                timestamp="2024-01-15T10:30:00Z",
                context={},
                options_considered=[],
                selected_option="A",
                rationale="Test",
                confidence=1.5,
                session_id="test-session"
            )
        
        # Invalid confidence - negative
        with pytest.raises(ValueError, match="confidence"):
            Decision(
                decision_id="DEC-test-0001",
                decision_type=DecisionType.CONFLICT_RESOLUTION,
                timestamp="2024-01-15T10:30:00Z",
                context={},
                options_considered=[],
                selected_option="A",
                rationale="Test",
                confidence=-0.1,
                session_id="test-session"
            )
    
    def test_decision_to_dict(self):
        """Test converting decision to dictionary."""
        decision = Decision(
            decision_id="DEC-test-0001",
            decision_type=DecisionType.MERGE_DECISION,
            timestamp="2024-01-15T10:30:00Z",
            context={"file": "module.py"},
            options_considered=[{"label": "A"}, {"label": "B"}],
            selected_option="A",
            rationale="Test rationale",
            confidence=0.75,
            session_id="test-session",
            conflict_id="conf-001",
            metadata={"extra": "data"}
        )
        
        result = decision.to_dict()
        
        assert result["decision_id"] == "DEC-test-0001"
        assert result["decision_type"] == "merge_decision"
        assert result["timestamp"] == "2024-01-15T10:30:00Z"
        assert result["context"] == {"file": "module.py"}
        assert len(result["options_considered"]) == 2
        assert result["selected_option"] == "A"
        assert result["confidence"] == 0.75
        assert result["conflict_id"] == "conf-001"
        assert result["metadata"] == {"extra": "data"}


class TestDecisionRecordArtifact:
    """Tests for DecisionRecordArtifact dataclass."""
    
    def test_artifact_creation(self):
        """Test creating a decision record artifact."""
        decisions = [
            Decision(
                decision_id="DEC-test-0001",
                decision_type=DecisionType.CONFLICT_RESOLUTION,
                timestamp="2024-01-15T10:30:00Z",
                context={},
                options_considered=[],
                selected_option="A",
                rationale="Test",
                confidence=0.8,
                session_id="test-session"
            )
        ]
        
        artifact = DecisionRecordArtifact(
            session_id="test-session",
            created_at="2024-01-15T10:35:00Z",
            decisions=decisions,
            summary={"conflict_resolution": 1}
        )
        
        assert artifact.session_id == "test-session"
        assert len(artifact.decisions) == 1
        assert artifact.summary == {"conflict_resolution": 1}
    
    def test_artifact_to_dict(self):
        """Test converting artifact to dictionary."""
        decisions = [
            Decision(
                decision_id="DEC-test-0001",
                decision_type=DecisionType.GATE_DECISION,
                timestamp="2024-01-15T10:30:00Z",
                context={},
                options_considered=[],
                selected_option="pass",
                rationale="Test",
                confidence=1.0,
                session_id="test-session",
                gate_id="GATE-03"
            )
        ]
        
        artifact = DecisionRecordArtifact(
            session_id="test-session",
            created_at="2024-01-15T10:35:00Z",
            decisions=decisions,
            summary={"gate_decision": 1}
        )
        
        result = artifact.to_dict()
        
        assert result["session_id"] == "test-session"
        assert result["created_at"] == "2024-01-15T10:35:00Z"
        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["decision_type"] == "gate_decision"
        assert result["summary"] == {"gate_decision": 1}


class TestDecisionRecordManager:
    """Tests for DecisionRecordManager class."""
    
    def test_manager_creation(self):
        """Test creating a decision record manager."""
        manager = DecisionRecordManager(session_id="test-session-123")
        
        assert manager._session_id == "test-session-123"
        assert manager.empty() is True
        assert manager.get_decision_count() == 0
    
    def test_record_decision(self):
        """Test recording a decision."""
        manager = DecisionRecordManager(session_id="test-session")
        
        decision = manager.record_decision(
            decision_type=DecisionType.CONFLICT_RESOLUTION,
            context={"file": "test.py", "conflict_type": "merge"},
            options_considered=[
                {"label": "keep_ours", "score": 0.8},
                {"label": "keep_theirs", "score": 0.6}
            ],
            selected_option="keep_ours",
            rationale="Higher accuracy score",
            confidence=0.85,
            conflict_id="conf-001"
        )
        
        assert decision.decision_id.startswith("DEC-test-ses-")
        assert decision.decision_type == DecisionType.CONFLICT_RESOLUTION
        assert decision.selected_option == "keep_ours"
        assert decision.conflict_id == "conf-001"
        assert manager.empty() is False
        assert manager.get_decision_count() == 1
    
    def test_record_multiple_decisions(self):
        """Test recording multiple decisions."""
        manager = DecisionRecordManager(session_id="test-session")
        
        # Record first decision
        manager.record_decision(
            decision_type=DecisionType.CONFLICT_RESOLUTION,
            context={},
            options_considered=[],
            selected_option="A",
            rationale="Test",
            confidence=0.8
        )
        
        # Record second decision
        manager.record_decision(
            decision_type=DecisionType.GATE_DECISION,
            context={},
            options_considered=[],
            selected_option="pass",
            rationale="All checks passed",
            confidence=1.0,
            gate_id="GATE-03"
        )
        
        assert manager.get_decision_count() == 2
        
        # Check decisions by type
        conflict_decisions = manager.get_decisions_by_type(DecisionType.CONFLICT_RESOLUTION)
        assert len(conflict_decisions) == 1
        
        gate_decisions = manager.get_decisions_by_type(DecisionType.GATE_DECISION)
        assert len(gate_decisions) == 1
    
    def test_get_decisions_by_gate(self):
        """Test filtering decisions by gate."""
        manager = DecisionRecordManager(session_id="test-session")
        
        manager.record_decision(
            decision_type=DecisionType.GATE_DECISION,
            context={},
            options_considered=[],
            selected_option="pass",
            rationale="Test",
            confidence=1.0,
            gate_id="GATE-03"
        )
        
        manager.record_decision(
            decision_type=DecisionType.GATE_DECISION,
            context={},
            options_considered=[],
            selected_option="pass",
            rationale="Test",
            confidence=1.0,
            gate_id="GATE-04"
        )
        
        gate_03_decisions = manager.get_decisions_by_gate("GATE-03")
        assert len(gate_03_decisions) == 1
        
        gate_04_decisions = manager.get_decisions_by_gate("GATE-04")
        assert len(gate_04_decisions) == 1
    
    def test_generate_artifact(self):
        """Test generating the decision record artifact."""
        manager = DecisionRecordManager(session_id="test-session")
        
        # Record some decisions
        manager.record_decision(
            decision_type=DecisionType.CONFLICT_RESOLUTION,
            context={},
            options_considered=[],
            selected_option="A",
            rationale="Test",
            confidence=0.8
        )
        
        manager.record_decision(
            decision_type=DecisionType.GATE_DECISION,
            context={},
            options_considered=[],
            selected_option="pass",
            rationale="Test",
            confidence=1.0,
            gate_id="GATE-03"
        )
        
        manager.record_decision(
            decision_type=DecisionType.CONFLICT_RESOLUTION,
            context={},
            options_considered=[],
            selected_option="B",
            rationale="Test",
            confidence=0.7
        )
        
        artifact = manager.generate_artifact()
        
        assert artifact.session_id == "test-session"
        assert len(artifact.decisions) == 3
        assert artifact.summary == {
            "conflict_resolution": 2,
            "gate_decision": 1
        }
    
    def test_to_json(self):
        """Test exporting to JSON."""
        manager = DecisionRecordManager(session_id="test-session")
        
        manager.record_decision(
            decision_type=DecisionType.CONFLICT_RESOLUTION,
            context={"test": "data"},
            options_considered=[{"label": "A"}],
            selected_option="A",
            rationale="Test rationale",
            confidence=0.9
        )
        
        json_str = manager.to_json()
        
        # Should be valid JSON
        data = json.loads(json_str)
        assert data["session_id"] == "test-session"
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["selected_option"] == "A"
    
    def test_clear(self):
        """Test clearing all decisions."""
        manager = DecisionRecordManager(session_id="test-session")
        
        manager.record_decision(
            decision_type=DecisionType.CONFLICT_RESOLUTION,
            context={},
            options_considered=[],
            selected_option="A",
            rationale="Test",
            confidence=0.8
        )
        
        assert manager.get_decision_count() == 1
        
        manager.clear()
        
        assert manager.empty() is True
        assert manager.get_decision_count() == 0


class TestFactoryFunctions:
    """Tests for factory functions."""
    
    def test_create_decision_record_manager(self):
        """Test the factory function."""
        manager = create_decision_record_manager("test-session")
        
        assert isinstance(manager, DecisionRecordManager)
        assert manager._session_id == "test-session"
    
    def test_write_decision_record(self):
        """Test writing decision record to file."""
        manager = DecisionRecordManager(session_id="test-session")
        
        manager.record_decision(
            decision_type=DecisionType.CONFLICT_RESOLUTION,
            context={},
            options_considered=[],
            selected_option="A",
            rationale="Test",
            confidence=0.8
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "decision_record.json"
            
            result = write_decision_record(manager, str(output_path))
            
            assert result["success"] is True
            assert result["decision_count"] == 1
            assert result["summary"] == {"conflict_resolution": 1}
            
            # Verify file exists and is valid JSON
            assert output_path.exists()
            with open(output_path) as f:
                data = json.load(f)
            assert data["session_id"] == "test-session"


class TestConflictResolverIntegration:
    """Tests for ConflictResolver integration with DecisionRecordManager."""
    
    def test_conflict_resolver_records_decision(self):
        """Test that ConflictResolver records decisions when manager is provided."""
        from src.decision.conflict_resolver import (
            ConflictResolver,
            ConflictMetrics,
        )
        
        manager = DecisionRecordManager(session_id="test-session")
        resolver = ConflictResolver()
        
        option_a = ConflictMetrics(
            accuracy=0.9,
            utility=0.8,
            efficiency=0.7,
            consensus=0.6
        )
        option_b = ConflictMetrics(
            accuracy=0.5,
            utility=0.5,
            efficiency=0.5,
            consensus=0.5
        )
        
        # Resolve without manager - no decision recorded
        decision1 = resolver.resolve(option_a, option_b, "A", "B")
        assert manager.get_decision_count() == 0
        
        # Resolve with manager - decision should be recorded
        decision2 = resolver.resolve(
            option_a,
            option_b,
            "Option A",
            "Option B",
            decision_record_manager=manager,
            conflict_id="conf-001"
        )
        
        assert manager.get_decision_count() == 1
        
        recorded = manager.get_decisions()[0]
        assert recorded.decision_type == DecisionType.CONFLICT_RESOLUTION
        assert recorded.selected_option == "Option A"
        assert recorded.conflict_id == "conf-001"
    
    def test_conflict_resolver_context_passed(self):
        """Test that context is passed to decision record."""
        from src.decision.conflict_resolver import (
            ConflictResolver,
            ConflictMetrics,
        )
        
        manager = DecisionRecordManager(session_id="test-session")
        resolver = ConflictResolver()
        
        option_a = ConflictMetrics(0.9, 0.8, 0.7, 0.6)
        option_b = ConflictMetrics(0.5, 0.5, 0.5, 0.5)
        
        context = {"file": "module.py", "line": 42}
        
        resolver.resolve(
            option_a,
            option_b,
            "A",
            "B",
            decision_record_manager=manager,
            context=context
        )
        
        recorded = manager.get_decisions()[0]
        assert "file" in recorded.context
        assert recorded.context["file"] == "module.py"


class TestOrchestratorIntegration:
    """Tests for Orchestrator integration with DecisionRecordManager."""
    
    @patch('src.harness.orchestrator.DECISION_RECORD_AVAILABLE', True)
    def test_orchestrator_initializes_manager(self):
        """Test that Orchestrator initializes DecisionRecordManager."""
        from src.harness.orchestrator import Orchestrator
        
        orchestrator = Orchestrator(
            repo_root=None,
            mode="direct",
            config={"decision_record": {"enabled": True}}
        )
        
        # Initialize with session
        manager = orchestrator.get_decision_record_manager("test-session")
        
        assert manager is not None
        assert manager._session_id == "test-session"
    
    @patch('src.harness.orchestrator.DECISION_RECORD_AVAILABLE', True)
    def test_orchestrator_records_decisions(self):
        """Test that Orchestrator can record decisions."""
        from src.harness.orchestrator import Orchestrator
        
        orchestrator = Orchestrator(
            repo_root=None,
            mode="direct",
            config={"decision_record": {"enabled": True}}
        )
        
        # Initialize manager
        orchestrator.get_decision_record_manager("test-session")
        
        # Record a decision
        orchestrator.record_decision(
            decision_type=DecisionType.GATE_DECISION,
            context={"gate": "GATE-03"},
            options_considered=[{"pass": True}, {"pass": False}],
            selected_option="pass",
            rationale="All checks passed",
            confidence=1.0,
            gate_id="GATE-03"
        )
        
        stats = orchestrator.get_decision_stats()
        assert stats["decision_count"] == 1
    
    @patch('src.harness.orchestrator.DECISION_RECORD_AVAILABLE', True)
    @patch('src.harness.orchestrator.write_decision_record')
    def test_delivery_blocks_on_empty_decision_record(self, mock_write):
        """Test that DELIVERY blocks when decision record is empty."""
        from src.harness.orchestrator import Orchestrator
        
        orchestrator = Orchestrator(
            repo_root=None,
            mode="direct",
            config={
                "decision_record": {
                    "enabled": True,
                    "require_for_delivery": True
                },
                "output": {"directory": "outputs/"}
            }
        )
        
        # Initialize manager but don't record any decisions
        orchestrator.get_decision_record_manager("test-session")
        
        # Attempt delivery
        result = orchestrator._deliver_artifacts({"session_id": "test-session"})
        
        assert result.get("decision_record_blocked") is True
        assert "required" in result.get("error", "").lower()
    
    @patch('src.harness.orchestrator.DECISION_RECORD_AVAILABLE', True)
    @patch('src.harness.orchestrator.write_decision_record')
    def test_delivery_allows_when_decisions_recorded(self, mock_write):
        """Test that DELIVERY succeeds when decisions are recorded."""
        from src.harness.orchestrator import Orchestrator
        
        mock_write.return_value = {
            "success": True,
            "decision_count": 1,
            "summary": {"conflict_resolution": 1}
        }
        
        orchestrator = Orchestrator(
            repo_root=None,
            mode="direct",
            config={
                "decision_record": {
                    "enabled": True,
                    "require_for_delivery": True
                },
                "output": {"directory": "outputs/"}
            }
        )
        
        # Initialize manager and record a decision
        orchestrator.get_decision_record_manager("test-session")
        orchestrator.record_decision(
            decision_type=DecisionType.CONFLICT_RESOLUTION,
            context={},
            options_considered=[],
            selected_option="A",
            rationale="Test",
            confidence=0.8
        )
        
        # Attempt delivery
        result = orchestrator._deliver_artifacts({"session_id": "test-session"})
        
        assert result.get("decision_record_blocked") is not True
        assert result.get("decision_record_delivered") is True


class TestSummaryGeneration:
    """Tests for summary generation in artifacts."""
    
    def test_summary_counts_by_type(self):
        """Test that summary correctly counts decisions by type."""
        manager = DecisionRecordManager(session_id="test-session")
        
        # Add various decisions
        for _ in range(3):
            manager.record_decision(
                decision_type=DecisionType.CONFLICT_RESOLUTION,
                context={},
                options_considered=[],
                selected_option="A",
                rationale="Test",
                confidence=0.8
            )
        
        for _ in range(2):
            manager.record_decision(
                decision_type=DecisionType.GATE_DECISION,
                context={},
                options_considered=[],
                selected_option="pass",
                rationale="Test",
                confidence=1.0
            )
        
        manager.record_decision(
            decision_type=DecisionType.MERGE_DECISION,
            context={},
            options_considered=[],
            selected_option="merge",
            rationale="Test",
            confidence=0.9
        )
        
        artifact = manager.generate_artifact()
        
        assert artifact.summary == {
            "conflict_resolution": 3,
            "gate_decision": 2,
            "merge_decision": 1
        }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
