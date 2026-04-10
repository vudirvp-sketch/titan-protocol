"""Tests for GapEvent Serializer (ITEM-B004)."""

import pytest
import yaml
from src.gap_events.serializer import (
    GapEvent, from_legacy_gap, to_legacy_gap, validate_round_trip,
    _load_mappings, _clear_cache
)


class TestGapEventBasic:
    def test_create_gap_event(self):
        event = GapEvent(
            gap_id="GAP-STRUCT-001", gap_type="GAP-STRUCT-001",
            category="STRUCT", severity="BLOCK",
            description="Test", source_component="test",
        )
        assert event.gap_id == "GAP-STRUCT-001"

    def test_serialization_formats(self):
        event = GapEvent(
            gap_id="GAP-STRUCT-001", gap_type="GAP-STRUCT-001",
            category="STRUCT", severity="BLOCK",
            description="Test", source_component="test",
        )
        assert "GAP-STRUCT-001" in event.to_json()
        assert "GAP-STRUCT-001" in event.to_yaml()
        d = event.to_dict()
        assert "gap_id" in d and "timestamp" in d


class TestFromLegacyGap:
    def test_mapped_legacy_type(self):
        legacy = {"type": "retry_exhausted", "message": "Max retries", "source": "retry"}
        event = from_legacy_gap(legacy)
        assert event.gap_type != ""
        assert event.description == "Max retries"

    def test_unmapped_type_returns_adapt_gap(self):
        legacy = {"type": "totally_unknown_xyz", "message": "Unknown", "source": "test"}
        event = from_legacy_gap(legacy)
        assert event.gap_type == "GAP-ADAPT-001"

    def test_all_20_mappings_load(self):
        """Verify all 20 adapter mappings are loaded and functional."""
        _clear_cache()
        mappings = _load_mappings()
        assert len(mappings) >= 20, f"Only {len(mappings)} mappings loaded"

    def test_from_legacy_with_gap_type_key(self):
        legacy = {"gap_type": "GAP-STRUCT-001", "message": "Structural issue", "source": "schema"}
        event = from_legacy_gap(legacy)
        assert event.gap_type == "GAP-STRUCT-001"

    def test_from_legacy_missing_type(self):
        legacy = {"message": "No type key", "source": "test"}
        event = from_legacy_gap(legacy)
        assert event.gap_type == "GAP-ADAPT-001"


class TestToLegacyGap:
    def test_reverse_conversion(self):
        event = GapEvent(
            gap_id="GAP-STRUCT-001", gap_type="GAP-STRUCT-001",
            category="STRUCT", severity="BLOCK",
            description="Test desc", source_component="test",
        )
        legacy = to_legacy_gap(event)
        assert "type" in legacy
        assert "gap_type" in legacy
        assert legacy["message"] == "Test desc"

    def test_legacy_keys_resolved(self):
        event = GapEvent(
            gap_id="GAP-BEHAV-001", gap_type="GAP-BEHAV-001",
            category="BEHAV", severity="WARN",
            description="Retry failed", source_component="retry",
        )
        legacy = to_legacy_gap(event)
        assert legacy["type"] == "retry_exhausted"


class TestRoundTrip:
    def test_round_trip_preserves_severity(self):
        legacy = {"type": "retry_exhausted", "message": "Failed", "source": "retry", "severity": "WARN"}
        assert validate_round_trip(legacy) is True

    def test_round_trip_block_severity(self):
        legacy = {"type": "gate_check_failed", "message": "Blocked", "source": "pipeline", "severity": "BLOCK"}
        assert validate_round_trip(legacy) is True

    def test_round_trip_struct(self):
        legacy = {"type": "workspace_violation", "message": "Isolation breach", "source": "security", "severity": "BLOCK"}
        assert validate_round_trip(legacy) is True
