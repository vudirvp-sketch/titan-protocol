"""
Tests for Semantic Tainting.

ITEM-ARCH-19: Tests for taint tracking and propagation.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from validation.tainting import (
    SemanticTaintTracker, TaintSource, TaintRecord
)


class TestSemanticTaintTracker:
    """Tests for semantic taint tracking."""
    
    def test_mark_tainted(self):
        """Test marking data as tainted."""
        tracker = SemanticTaintTracker()
        tracker.mark_tainted("data_1", "GATE-04_ADVISORY", 0.7)
        
        assert tracker.is_tainted("data_1")
    
    def test_is_not_tainted_initially(self):
        """Test data is not tainted initially."""
        tracker = SemanticTaintTracker()
        assert not tracker.is_tainted("unknown_data")
    
    def test_get_taint_source(self):
        """Test getting taint source."""
        tracker = SemanticTaintTracker()
        tracker.mark_tainted("data_1", "LOW_CONFIDENCE_LLM", 0.5, "Low confidence output")
        
        source = tracker.get_taint_source("data_1")
        assert source is not None
        assert source["source"] == "LOW_CONFIDENCE_LLM"
        assert source["confidence"] == 0.5
    
    def test_propagate_taint(self):
        """Test taint propagation."""
        tracker = SemanticTaintTracker()
        tracker.mark_tainted("source_data", "GATE-04_ADVISORY", 0.6)
        tracker.propagate_taint("source_data", "derived_data")
        
        assert tracker.is_tainted("derived_data")
        source = tracker.get_taint_source("derived_data")
        assert "source_data" in source["propagation_path"]
    
    def test_no_propagation_from_validated(self):
        """Test no propagation from validated data."""
        tracker = SemanticTaintTracker()
        tracker.mark_tainted("source_data", "GATE-04_ADVISORY", 0.6)
        tracker.validate("source_data")
        
        result = tracker.propagate_taint("source_data", "derived_data")
        assert result is None
        assert not tracker.is_tainted("derived_data")
    
    def test_validate_tainted_data(self):
        """Test validating tainted data."""
        tracker = SemanticTaintTracker()
        tracker.mark_tainted("data_1", "GATE-04_ADVISORY", 0.7)
        
        tracker.validate("data_1")
        
        assert not tracker.is_tainted("data_1")
    
    def test_requires_validation(self):
        """Test validation requirement check."""
        tracker = SemanticTaintTracker()
        tracker.mark_tainted("data_1", "GATE-04_ADVISORY", 0.7)
        
        requires, reason = tracker.requires_validation("data_1")
        assert requires
        assert "GATE-04_ADVISORY" in reason
    
    def test_get_tainted_dependencies(self):
        """Test getting tainted dependencies."""
        tracker = SemanticTaintTracker()
        tracker.mark_tainted("source", "GATE-04_ADVISORY", 0.6)
        tracker.propagate_taint("source", "mid")
        tracker.propagate_taint("mid", "target")
        
        deps = tracker.get_tainted_dependencies("target")
        assert "source" in deps
        assert "mid" in deps
    
    def test_clear_taint(self):
        """Test clearing taint."""
        tracker = SemanticTaintTracker()
        tracker.mark_tainted("data_1", "GATE-04_ADVISORY", 0.7)
        
        result = tracker.clear_taint("data_1")
        assert result
        assert not tracker.is_tainted("data_1")
    
    def test_clear_all(self):
        """Test clearing all taints."""
        tracker = SemanticTaintTracker()
        tracker.mark_tainted("data_1", "GATE-04_ADVISORY", 0.7)
        tracker.mark_tainted("data_2", "LOW_CONFIDENCE_LLM", 0.5)
        
        count = tracker.clear_all()
        assert count == 2
        assert not tracker.is_tainted("data_1")
        assert not tracker.is_tainted("data_2")
    
    def test_get_stats(self):
        """Test getting statistics."""
        tracker = SemanticTaintTracker()
        tracker.mark_tainted("data_1", "GATE-04_ADVISORY", 0.7)
        tracker.mark_tainted("data_2", "LOW_CONFIDENCE_LLM", 0.5)
        tracker.validate("data_1")
        
        stats = tracker.get_stats()
        assert stats["total_tainted"] == 2
        assert stats["validated"] == 1
        assert stats["unvalidated"] == 1
    
    def test_export_import_state(self):
        """Test exporting and importing state."""
        tracker1 = SemanticTaintTracker()
        tracker1.mark_tainted("data_1", "GATE-04_ADVISORY", 0.7)
        tracker1.propagate_taint("data_1", "data_2")
        
        state = tracker1.export_state()
        
        tracker2 = SemanticTaintTracker()
        tracker2.import_state(state)
        
        assert tracker2.is_tainted("data_1")
        assert tracker2.is_tainted("data_2")


class TestTaintSource:
    """Tests for TaintSource enum."""
    
    def test_all_sources_exist(self):
        """Test all expected sources exist."""
        expected = [
            "GATE-04_ADVISORY",
            "LOW_CONFIDENCE_LLM",
            "EXTERNAL_INPUT",
            "UNVERIFIED_SOURCE",
            "MANUAL_OVERRIDE",
            "RECOVERED_STATE"
        ]
        
        for source in expected:
            assert hasattr(TaintSource, source) or source in [s.value for s in TaintSource]


class TestTaintRecord:
    """Tests for TaintRecord dataclass."""
    
    def test_to_dict(self):
        """Test serialization."""
        record = TaintRecord(
            data_id="test_data",
            source=TaintSource.GATE_04_ADVISORY,
            confidence=0.7,
            timestamp="2024-01-01T00:00:00Z",
            reason="Test reason",
            propagation_path=["a", "b"]
        )
        
        data = record.to_dict()
        assert data["data_id"] == "test_data"
        assert data["source"] == "GATE-04_ADVISORY"
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "data_id": "test",
            "source": "LOW_CONFIDENCE_LLM",
            "confidence": 0.5,
            "timestamp": "2024-01-01T00:00:00Z",
            "reason": "",
            "propagation_path": [],
            "validated": False
        }
        
        record = TaintRecord.from_dict(data)
        assert record.data_id == "test"
        assert record.source == TaintSource.LOW_CONFIDENCE_LLM


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
