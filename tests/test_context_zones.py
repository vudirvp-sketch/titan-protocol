"""
Tests for Context Zones with Differential Compression (ITEM-CTX-92).

Tests the context zone functionality for:
- Zone classification
- Differential compression
- Pattern matching
- Statistics tracking

Author: TITAN FUSE Team
Version: 3.8.0
"""

import pytest
import sys
import os
from datetime import datetime, timedelta

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from context.context_zones import (
    ContextZone,
    ZoneClassification,
    ZoneStats,
    ContextZoneManager,
    create_zone_manager
)
from utils.timezone import now_utc, now_utc_iso


class TestContextZone:
    """Tests for ContextZone enum."""
    
    def test_zone_values(self):
        """Test that all required zones exist."""
        assert ContextZone.CORE.value == "core"
        assert ContextZone.PERIPHERY.value == "periphery"
        assert ContextZone.ANOMALY.value == "anomaly"
    
    def test_compression_ratios(self):
        """Test compression ratios for each zone."""
        assert ContextZone.CORE.compression_ratio == 0.0
        assert ContextZone.PERIPHERY.compression_ratio == 0.2
        assert ContextZone.ANOMALY.compression_ratio == 0.5
    
    def test_retention_ratios(self):
        """Test retention ratios (inverse of compression)."""
        assert ContextZone.CORE.retention_ratio == 1.0
        assert ContextZone.PERIPHERY.retention_ratio == 0.8
        assert ContextZone.ANOMALY.retention_ratio == 0.5


class TestZoneClassification:
    """Tests for ZoneClassification dataclass."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        classification = ZoneClassification(zone=ContextZone.CORE)
        
        assert classification.zone == ContextZone.CORE
        assert classification.confidence == 1.0
        assert classification.reasons == []
        assert classification.original_size == 0
        assert classification.compressed_size == 0
        assert classification.metadata == {}
    
    def test_init_with_values(self):
        """Test initialization with values."""
        classification = ZoneClassification(
            zone=ContextZone.PERIPHERY,
            confidence=0.75,
            reasons=["Contains history references"],
            original_size=1000,
            compressed_size=800,
            metadata={"key": "value"}
        )
        
        assert classification.zone == ContextZone.PERIPHERY
        assert classification.confidence == 0.75
        assert classification.reasons == ["Contains history references"]
        assert classification.original_size == 1000
        assert classification.compressed_size == 800
        assert classification.metadata == {"key": "value"}
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        classification = ZoneClassification(
            zone=ContextZone.ANOMALY,
            confidence=0.9,
            reasons=["Debug content", "Old data"],
            original_size=500,
            compressed_size=250,
            metadata={"score": 0.85}
        )
        
        d = classification.to_dict()
        
        assert d["zone"] == "anomaly"
        assert d["confidence"] == 0.9
        assert d["reasons"] == ["Debug content", "Old data"]
        assert d["original_size"] == 500
        assert d["compressed_size"] == 250
        assert d["metadata"]["score"] == 0.85
    
    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "zone": "core",
            "confidence": 0.95,
            "reasons": ["Gate reference found"],
            "original_size": 2000,
            "compressed_size": 2000,
            "metadata": {"has_gates": True}
        }
        
        classification = ZoneClassification.from_dict(data)
        
        assert classification.zone == ContextZone.CORE
        assert classification.confidence == 0.95
        assert classification.reasons == ["Gate reference found"]
        assert classification.original_size == 2000
        assert classification.compressed_size == 2000
        assert classification.metadata["has_gates"] is True


class TestZoneStats:
    """Tests for ZoneStats dataclass."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        stats = ZoneStats()
        
        assert stats.total_classifications == 0
        assert stats.core_count == 0
        assert stats.periphery_count == 0
        assert stats.anomaly_count == 0
        assert stats.total_original_bytes == 0
        assert stats.total_compressed_bytes == 0
        assert stats.total_bytes_saved == 0
    
    def test_update_core(self):
        """Test updating stats with CORE classification."""
        stats = ZoneStats()
        classification = ZoneClassification(
            zone=ContextZone.CORE,
            original_size=1000,
            compressed_size=1000  # No compression for CORE
        )
        
        stats.update(classification)
        
        assert stats.total_classifications == 1
        assert stats.core_count == 1
        assert stats.total_original_bytes == 1000
        assert stats.total_compressed_bytes == 1000
        assert stats.total_bytes_saved == 0
    
    def test_update_periphery(self):
        """Test updating stats with PERIPHERY classification."""
        stats = ZoneStats()
        classification = ZoneClassification(
            zone=ContextZone.PERIPHERY,
            original_size=1000,
            compressed_size=800  # 20% compression
        )
        
        stats.update(classification)
        
        assert stats.total_classifications == 1
        assert stats.periphery_count == 1
        assert stats.total_bytes_saved == 200
    
    def test_update_anomaly(self):
        """Test updating stats with ANOMALY classification."""
        stats = ZoneStats()
        classification = ZoneClassification(
            zone=ContextZone.ANOMALY,
            original_size=1000,
            compressed_size=500  # 50% compression
        )
        
        stats.update(classification)
        
        assert stats.total_classifications == 1
        assert stats.anomaly_count == 1
        assert stats.total_bytes_saved == 500
    
    def test_to_dict(self):
        """Test serialization."""
        stats = ZoneStats(
            total_classifications=10,
            core_count=4,
            periphery_count=4,
            anomaly_count=2,
            total_original_bytes=10000,
            total_compressed_bytes=7000,
            total_bytes_saved=3000
        )
        
        d = stats.to_dict()
        
        assert d["total_classifications"] == 10
        assert d["core_count"] == 4
        assert d["periphery_count"] == 4
        assert d["anomaly_count"] == 2
        assert d["total_original_bytes"] == 10000
        assert d["total_compressed_bytes"] == 7000
        assert d["total_bytes_saved"] == 3000
        assert d["average_compression_ratio"] == 0.3


class TestContextZoneManager:
    """Tests for ContextZoneManager class."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        manager = ContextZoneManager()
        
        assert manager is not None
        assert manager._compression_enabled is True
        assert len(manager._core_patterns) > 0
        assert len(manager._periphery_patterns) > 0
        assert len(manager._anomaly_patterns) > 0
    
    def test_init_with_config(self):
        """Test initialization with config."""
        config = {
            "compression_enabled": False,
            "core_patterns": [r"custom_core"],
            "periphery_patterns": [r"custom_periphery"],
            "anomaly_patterns": [r"custom_anomaly"]
        }
        
        manager = ContextZoneManager(config)
        
        assert manager._compression_enabled is False
        assert r"custom_core" in manager._core_patterns
        assert r"custom_periphery" in manager._periphery_patterns
        assert r"custom_anomaly" in manager._anomaly_patterns
    
    # ========================================
    # Classification Tests
    # ========================================
    
    def test_classify_core_content(self):
        """Test classification of CORE content."""
        manager = ContextZoneManager()
        
        # Content with gate references
        content = "GATE-00 passed successfully.\nGATE-01 pending review."
        
        classification = manager.classify_content(content)
        
        assert classification.zone == ContextZone.CORE
        assert classification.confidence > 0
        assert any("gate" in r.lower() for r in classification.reasons)
    
    def test_classify_core_with_decision(self):
        """Test CORE classification with decision markers."""
        manager = ContextZoneManager()
        
        content = "decision: approved\nresult: success\naction: continue"
        
        classification = manager.classify_content(content)
        
        assert classification.zone == ContextZone.CORE
        assert classification.original_size == len(content)
    
    def test_classify_periphery_content(self):
        """Test classification of PERIPHERY content."""
        manager = ContextZoneManager()
        
        content = "history: previous operations\nrelated_file: config.yaml"
        
        classification = manager.classify_content(content)
        
        assert classification.zone == ContextZone.PERIPHERY
    
    def test_classify_anomaly_content(self):
        """Test classification of ANOMALY content."""
        manager = ContextZoneManager()
        
        content = "debug: verbose output\ntrace: stack trace here\ncached_data: old values"
        
        classification = manager.classify_content(content)
        
        assert classification.zone == ContextZone.ANOMALY
    
    def test_classify_empty_content(self):
        """Test classification of empty content."""
        manager = ContextZoneManager()
        
        classification = manager.classify_content("")
        
        assert classification.zone == ContextZone.ANOMALY
        assert classification.confidence == 1.0
        assert "Empty content" in classification.reasons
    
    def test_classify_with_context_timestamp(self):
        """Test classification with timestamp context."""
        manager = ContextZoneManager()
        
        # Recent timestamp
        recent = (now_utc() - timedelta(minutes=30)).isoformat()
        
        classification = manager.classify_content(
            "Some content",
            context={"timestamp": recent}
        )
        
        # Should have recent indicator
        assert any("recent" in r.lower() for r in classification.reasons)
    
    def test_classify_with_context_is_current(self):
        """Test classification with is_current context."""
        manager = ContextZoneManager()
        
        classification = manager.classify_content(
            "Some content",
            context={"is_current": True}
        )
        
        assert classification.zone == ContextZone.CORE
        assert any("current" in r.lower() for r in classification.reasons)
    
    def test_classify_with_file_type(self):
        """Test classification with file_type context."""
        manager = ContextZoneManager()
        
        classification = manager.classify_content(
            "Some content",
            context={"file_type": "gate"}
        )
        
        assert classification.zone == ContextZone.CORE
    
    def test_classify_default_to_periphery(self):
        """Test that content with no indicators defaults to PERIPHERY."""
        manager = ContextZoneManager()
        
        # Content with no matching patterns
        content = "This is plain content with no special markers or indicators."
        
        classification = manager.classify_content(content)
        
        assert classification.zone == ContextZone.PERIPHERY
        assert any("default" in r.lower() for r in classification.reasons)
    
    # ========================================
    # Compression Tests
    # ========================================
    
    def test_compress_core_no_compression(self):
        """Test that CORE content is not compressed."""
        manager = ContextZoneManager()
        
        content = "GATE-00: Important gate data\ndecision: critical choice"
        
        compressed = manager.apply_compression(content, ContextZone.CORE)
        
        # CORE should not be compressed
        assert compressed == content
        assert len(compressed) == len(content)
    
    def test_compress_periphery(self):
        """Test PERIPHERY content compression."""
        manager = ContextZoneManager()
        
        # Content with redundant whitespace
        content = "Line 1\n\n\n\nLine 2\n\n\n\nLine 3"
        
        compressed = manager.apply_compression(content, ContextZone.PERIPHERY)
        
        # Should reduce multiple blank lines
        assert "\n\n\n" not in compressed
        assert len(compressed) < len(content)
    
    def test_compress_anomaly(self):
        """Test ANOMALY content compression."""
        manager = ContextZoneManager()
        
        content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        
        compressed = manager.apply_compression(content, ContextZone.ANOMALY)
        
        # Should be heavily compressed
        assert "[ANOMALY:" in compressed or len(compressed) < len(content)
        assert len(compressed) < len(content), "ANOMALY content should be compressed"
    
    def test_compress_with_gates_preserved(self):
        """Test that gate references are preserved in ANOMALY compression."""
        manager = ContextZoneManager()
        
        content = "GATE-00 data\nGATE-01 info\nother content"
        
        compressed = manager.apply_compression(content, ContextZone.ANOMALY)
        
        # Gates should be preserved in summary (format: [G:GATE-00,GATE-01])
        assert "GATE-00" in compressed or "[G:" in compressed
    
    def test_compress_empty_content(self):
        """Test compression of empty content."""
        manager = ContextZoneManager()
        
        for zone in ContextZone:
            compressed = manager.apply_compression("", zone)
            assert compressed == ""
    
    def test_compress_when_disabled(self):
        """Test that no compression occurs when disabled."""
        manager = ContextZoneManager({"compression_enabled": False})
        
        content = "Line 1\nLine 2\nLine 3"
        
        for zone in ContextZone:
            compressed = manager.apply_compression(content, zone)
            assert compressed == content
    
    # ========================================
    # compress_context Tests
    # ========================================
    
    def test_compress_context_dict(self):
        """Test compressing a context dictionary."""
        manager = ContextZoneManager()
        
        context = {
            "current_gate": "GATE-00 processing",
            "history": "Previous operations history",
            "debug": "debug: verbose output"
        }
        
        result = manager.compress_context(context)
        
        assert "compressed" in result
        assert "classifications" in result
        assert "stats" in result
        
        # Check that all keys are present
        assert "current_gate" in result["compressed"]
        assert "history" in result["compressed"]
        assert "debug" in result["compressed"]
    
    def test_compress_context_preserves_core(self):
        """Test that CORE content is preserved in context compression."""
        manager = ContextZoneManager()
        
        context = {
            "core_data": "GATE-00: Important data"
        }
        
        result = manager.compress_context(context)
        
        # CORE should be preserved
        assert result["compressed"]["core_data"] == context["core_data"]
    
    def test_compress_context_stats(self):
        """Test compression stats calculation."""
        manager = ContextZoneManager()
        
        # Use content that will definitely compress
        context = {
            "core": "GATE-00: " + "x" * 200,  # Will be CORE, no compression
            "periphery": "history\n" + "x" * 200 + "\n\n\ncontent",  # Will be compressed
            "anomaly": "debug: " + "x" * 200  # Will be heavily compressed
        }
        
        result = manager.compress_context(context)
        
        assert result["stats"]["total_keys"] == 3
        assert result["stats"]["bytes_saved"] > 0
    
    # ========================================
    # Statistics Tests
    # ========================================
    
    def test_get_zone_stats(self):
        """Test getting zone statistics."""
        manager = ContextZoneManager()
        
        # Use compress_context to update stats
        manager.compress_context({
            "item1": "GATE-00",
            "item2": "history",
            "item3": "debug:"
        })
        
        stats = manager.get_zone_stats()
        
        assert "total_classifications" in stats
        assert stats["total_classifications"] == 3
    
    def test_reset_stats(self):
        """Test resetting statistics."""
        manager = ContextZoneManager()
        
        # Compress to update stats
        manager.compress_context({"item": "GATE-00"})
        
        # Stats should have data
        assert manager.get_zone_stats()["total_classifications"] == 1
        
        manager.reset_stats()
        
        # Stats should be reset
        assert manager.get_zone_stats()["total_classifications"] == 0
    
    # ========================================
    # Pattern Management Tests
    # ========================================
    
    def test_add_core_pattern(self):
        """Test adding a custom CORE pattern."""
        manager = ContextZoneManager()
        
        initial_count = len(manager._core_patterns)
        
        manager.add_core_pattern(r"MY_CORE_PATTERN")
        
        assert len(manager._core_patterns) == initial_count + 1
        assert r"MY_CORE_PATTERN" in manager._core_patterns
    
    def test_add_periphery_pattern(self):
        """Test adding a custom PERIPHERY pattern."""
        manager = ContextZoneManager()
        
        initial_count = len(manager._periphery_patterns)
        
        manager.add_periphery_pattern(r"MY_PERIPHERY_PATTERN")
        
        assert len(manager._periphery_patterns) == initial_count + 1
    
    def test_add_anomaly_pattern(self):
        """Test adding a custom ANOMALY pattern."""
        manager = ContextZoneManager()
        
        initial_count = len(manager._anomaly_patterns)
        
        manager.add_anomaly_pattern(r"MY_ANOMALY_PATTERN")
        
        assert len(manager._anomaly_patterns) == initial_count + 1
    
    def test_add_duplicate_pattern(self):
        """Test that duplicate patterns are not added."""
        manager = ContextZoneManager()
        
        pattern = r"UNIQUE_PATTERN"
        manager.add_core_pattern(pattern)
        
        initial_count = len(manager._core_patterns)
        
        # Add same pattern again
        manager.add_core_pattern(pattern)
        
        assert len(manager._core_patterns) == initial_count
    
    def test_get_patterns(self):
        """Test getting all patterns."""
        manager = ContextZoneManager()
        
        patterns = manager.get_patterns()
        
        assert "core" in patterns
        assert "periphery" in patterns
        assert "anomaly" in patterns
        assert len(patterns["core"]) > 0
    
    # ========================================
    # Utility Method Tests
    # ========================================
    
    def test_estimate_compression(self):
        """Test compression estimation."""
        manager = ContextZoneManager()
        
        content = "GATE-00: Some content here"
        
        estimate = manager.estimate_compression(content)
        
        assert "zone" in estimate
        assert "original_size" in estimate
        assert "estimated_compressed_size" in estimate
        assert "estimated_savings" in estimate
        assert "compression_ratio" in estimate
    
    def test_enable_compression(self):
        """Test enabling/disabling compression."""
        manager = ContextZoneManager()
        
        assert manager._compression_enabled is True
        
        manager.enable_compression(False)
        assert manager._compression_enabled is False
        
        manager.enable_compression(True)
        assert manager._compression_enabled is True
    
    def test_set_session_start(self):
        """Test setting session start time."""
        manager = ContextZoneManager()
        
        new_time = now_utc() - timedelta(hours=2)
        manager.set_session_start(new_time)
        
        assert manager._session_start == new_time


class TestContextZoneManagerIntegration:
    """Integration tests for ContextZoneManager."""
    
    def test_full_workflow(self):
        """Test a complete classification and compression workflow."""
        manager = ContextZoneManager()
        
        # Add custom pattern
        manager.add_core_pattern(r"CRITICAL_SECTION")
        
        # Create context
        context = {
            "active_gate": "GATE-00: Processing checkpoint",
            "decision_log": "decision: approved\nresult: success",
            "history": "Previous operations and context history",
            "debug_trace": "debug: verbose\ndebug: more verbose",
            "cache": "cached_data: stale values from yesterday"
        }
        
        # Compress context
        result = manager.compress_context(context)
        
        # Verify results
        assert result["stats"]["total_keys"] == 5
        
        # Core content should be preserved
        assert result["compressed"]["active_gate"] == context["active_gate"]
        assert result["compressed"]["decision_log"] == context["decision_log"]
        
        # Anomaly content should be compressed
        assert len(result["compressed"]["debug_trace"]) < len(context["debug_trace"])
        
        # Check classifications
        classifications = result["classifications"]
        assert classifications["active_gate"]["zone"] == "core"
        assert classifications["debug_trace"]["zone"] == "anomaly"
    
    def test_validation_criteria_zones_classified(self):
        """Test validation criterion: zones_classified."""
        manager = ContextZoneManager()
        
        # Test various content types
        test_cases = [
            ("GATE-00: Active gate", ContextZone.CORE),
            ("history: previous data", ContextZone.PERIPHERY),
            ("debug: trace output", ContextZone.ANOMALY),
        ]
        
        for content, expected_zone in test_cases:
            classification = manager.classify_content(content)
            assert classification.zone == expected_zone, \
                f"Content '{content}' should be {expected_zone}, got {classification.zone}"
    
    def test_validation_criteria_compression_applied(self):
        """Test validation criterion: compression_applied."""
        manager = ContextZoneManager()
        
        # CORE: No compression
        core_content = "GATE-00: Important data"
        core_compressed = manager.apply_compression(core_content, ContextZone.CORE)
        assert core_compressed == core_content, "CORE should not be compressed"
        
        # PERIPHERY: Some compression
        periphery_content = "history: " + "x" * 100
        periphery_compressed = manager.apply_compression(
            periphery_content, ContextZone.PERIPHERY
        )
        # Periphery compression depends on content structure
        
        # ANOMALY: Heavy compression
        anomaly_content = "debug: " + "\n".join(["line"] * 100)
        anomaly_compressed = manager.apply_compression(anomaly_content, ContextZone.ANOMALY)
        assert len(anomaly_compressed) < len(anomaly_content), \
            "ANOMALY should be compressed"
    
    def test_multiple_gate_references(self):
        """Test classification with multiple gate references."""
        manager = ContextZoneManager()
        
        content = """
        GATE-00: Initial setup complete
        GATE-01: Validation passed
        GATE-02: Processing started
        decision: continue with processing
        """
        
        classification = manager.classify_content(content)
        
        assert classification.zone == ContextZone.CORE
        assert classification.confidence > 0.5
    
    def test_timestamp_age_classification(self):
        """Test age-based classification."""
        manager = ContextZoneManager()
        
        now = now_utc()
        
        # Recent content (within 1 hour) -> CORE
        recent_ts = (now - timedelta(minutes=30)).isoformat()
        recent_class = manager.classify_content(
            "content", context={"timestamp": recent_ts}
        )
        # Should have recent indicator
        
        # Old content (> 7 days) -> ANOMALY
        old_ts = (now - timedelta(days=10)).isoformat()
        old_class = manager.classify_content(
            "content", context={"timestamp": old_ts}
        )
        # Should have old indicator
        
        # Verify classifications
        assert any("recent" in r.lower() for r in recent_class.reasons)
        assert any("old" in r.lower() for r in old_class.reasons)


class TestFactoryFunction:
    """Tests for factory function."""
    
    def test_create_zone_manager(self):
        """Test create_zone_manager factory."""
        manager = create_zone_manager()
        
        assert isinstance(manager, ContextZoneManager)
    
    def test_create_zone_manager_with_config(self):
        """Test factory with configuration."""
        config = {
            "compression_enabled": False
        }
        
        manager = create_zone_manager(config)
        
        assert manager._compression_enabled is False


class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_none_content(self):
        """Test handling of None content."""
        manager = ContextZoneManager()
        
        # Should handle gracefully
        classification = manager.classify_content(None)
        assert classification.zone == ContextZone.ANOMALY
    
    def test_very_long_content(self):
        """Test handling of very long content."""
        manager = ContextZoneManager()
        
        content = "GATE-00: " + "x" * 10000
        
        classification = manager.classify_content(content)
        compressed = manager.apply_compression(content, classification.zone)
        
        assert classification.original_size == len(content)
    
    def test_special_characters(self):
        """Test handling of special characters."""
        manager = ContextZoneManager()
        
        content = "GATE-00: \n\t\r\n特殊字符 emoji 🎉"
        
        classification = manager.classify_content(content)
        compressed = manager.apply_compression(content, classification.zone)
        
        # Should handle without errors
        assert classification is not None
    
    def test_invalid_timestamp(self):
        """Test handling of invalid timestamp."""
        manager = ContextZoneManager()
        
        classification = manager.classify_content(
            "content",
            context={"timestamp": "invalid-timestamp"}
        )
        
        # Should handle gracefully and still classify
        assert classification.zone in ContextZone
    
    def test_nested_patterns(self):
        """Test content with nested patterns."""
        manager = ContextZoneManager()
        
        content = """
        GATE-00 processing
        history: previous GATE-01 results
        debug: trace of GATE-02
        """
        
        classification = manager.classify_content(content)
        
        # Gate references should dominate
        assert classification.zone == ContextZone.CORE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
