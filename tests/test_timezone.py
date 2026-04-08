"""
Tests for ITEM-SEC-121: Timestamp Timezone Awareness.

This test module verifies the timezone utilities that replace
the deprecated datetime.utcnow() function.
"""

import pytest
from datetime import datetime, timezone, timedelta
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.timezone import (
    TimezoneManager,
    now_utc,
    now_utc_iso,
    to_iso8601,
    from_iso8601,
    timestamp_for_id,
    timestamp_for_filename,
)


class TestTimezoneManager:
    """Tests for TimezoneManager class."""
    
    def test_now_utc_returns_timezone_aware_datetime(self):
        """Test that now_utc returns a timezone-aware datetime."""
        result = TimezoneManager.now_utc()
        assert isinstance(result, datetime)
        assert result.tzinfo is not None
        assert result.tzinfo == timezone.utc
    
    def test_now_utc_iso_returns_correct_format(self):
        """Test that now_utc_iso returns correct ISO8601 format with Z suffix."""
        result = TimezoneManager.now_utc_iso()
        assert isinstance(result, str)
        assert result.endswith('Z')
        # Should be parseable
        parsed = datetime.fromisoformat(result.replace('Z', '+00:00'))
        assert parsed.tzinfo is not None
    
    def test_to_iso8601_with_utc_datetime(self):
        """Test converting a UTC datetime to ISO8601 string."""
        dt = datetime(2026, 4, 8, 12, 30, 45, 123456, tzinfo=timezone.utc)
        result = TimezoneManager.to_iso8601(dt)
        assert '2026-04-08' in result
        assert '12:30:45' in result
        assert result.endswith('Z')
    
    def test_to_iso8601_with_naive_datetime(self):
        """Test converting a naive datetime to ISO8601 string."""
        dt = datetime(2026, 4, 8, 12, 30, 45, 123456)
        result = TimezoneManager.to_iso8601(dt)
        assert result.endswith('Z')
        parsed = from_iso8601(result)
        assert parsed.tzinfo == timezone.utc
    
    def test_from_iso8601_with_z_suffix(self):
        """Test parsing ISO8601 string with Z suffix."""
        iso_string = '2026-04-08T12:30:45.123456Z'
        result = from_iso8601(iso_string)
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 8
    
    def test_from_iso8601_without_z_suffix(self):
        """Test parsing ISO8601 string without Z suffix."""
        iso_string = '2026-04-08T12:30:45.123456'
        result = from_iso8601(iso_string)
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
    
    def test_from_iso8601_with_timezone_offset(self):
        """Test parsing ISO8601 string with timezone offset."""
        iso_string = '2026-04-08T12:30:45+02:00'
        result = from_iso8601(iso_string)
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        # Should be converted to UTC (2 hours earlier)
        assert result.hour == 10
    
    def test_from_iso8601_invalid_string_raises_error(self):
        """Test that invalid string raises ValueError."""
        with pytest.raises(ValueError):
            from_iso8601('not-a-valid-date')
    
    def test_timestamp_for_id_format(self):
        """Test that timestamp_for_id returns correct format."""
        result = timestamp_for_id()
        assert isinstance(result, str)
        assert len(result) == 20  # YYYYMMDDHHMMSSffffff
        assert result.isdigit()
    
    def test_timestamp_for_filename_format(self):
        """Test that timestamp_for_filename returns correct format."""
        result = timestamp_for_filename()
        assert isinstance(result, str)
        assert len(result) == 15  # YYYYMMDD_HHMMSS
        assert '_' in result
    
    def test_generate_seed_deterministic(self):
        """Test that generate_seed produces deterministic results."""
        session_id = "test-session-123"
        seed1 = TimezoneManager.generate_seed(session_id)
        seed2 = TimezoneManager.generate_seed(session_id)
        assert seed1 == seed2
        assert isinstance(seed1, int)
    
    def test_generate_seed_different_for_different_sessions(self):
        """Test that different sessions produce different seeds."""
        seed1 = TimezoneManager.generate_seed("session-1")
        seed2 = TimezoneManager.generate_seed("session-2")
        assert seed1 != seed2
    
    def test_singleton_pattern(self):
        """Test that TimezoneManager is a singleton."""
        instance1 = TimezoneManager()
        instance2 = TimezoneManager()
        assert instance1 is instance2
    
    def test_session_timezone(self):
        """Test setting and getting session timezone."""
        TimezoneManager.set_session_timezone('America/New_York')
        assert TimezoneManager.get_session_timezone() == 'America/New_York'
        TimezoneManager.set_session_timezone(None)
        assert TimezoneManager.get_session_timezone() is None


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def test_now_utc_function(self):
        """Test now_utc convenience function."""
        result = now_utc()
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
    
    def test_now_utc_iso_function(self):
        """Test now_utc_iso convenience function."""
        result = now_utc_iso()
        assert isinstance(result, str)
        assert result.endswith('Z')
    
    def test_to_iso8601_function(self):
        """Test to_iso8601 convenience function."""
        dt = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)
        result = to_iso8601(dt)
        assert result.endswith('Z')
    
    def test_from_iso8601_function(self):
        """Test from_iso8601 convenience function."""
        result = from_iso8601('2026-04-08T12:00:00Z')
        assert result.tzinfo == timezone.utc


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing code."""
    
    def test_replaces_datetime_utcnow_isoformat(self):
        """Test that now_utc_iso replaces datetime.utcnow().isoformat() + 'Z'."""
        # Old pattern
        old_pattern = datetime.utcnow().isoformat() + "Z"
        
        # New pattern
        new_pattern = now_utc_iso()
        
        # Both should end with Z
        assert old_pattern.endswith('Z')
        assert new_pattern.endswith('Z')
        
        # Both should be valid ISO8601
        old_parsed = from_iso8601(old_pattern)
        new_parsed = from_iso8601(new_pattern)
        
        # Times should be very close (within 1 second)
        diff = abs((new_parsed - old_parsed).total_seconds())
        assert diff < 1.0
    
    def test_replaces_datetime_utcnow_for_timestamps(self):
        """Test that now_utc replaces datetime.utcnow() for timestamp usage."""
        # Old pattern
        old_ts = datetime.utcnow()
        
        # New pattern
        new_ts = now_utc()
        
        # Both should be datetime objects
        assert isinstance(old_ts, datetime)
        assert isinstance(new_ts, datetime)
        
        # New should be timezone-aware
        assert new_ts.tzinfo is not None
        
        # Times should be very close
        diff = abs((new_ts.replace(tzinfo=None) - old_ts).total_seconds())
        assert diff < 1.0
    
    def test_replaces_datetime_utcnow_strftime(self):
        """Test that timestamp_for_filename replaces datetime.utcnow().strftime()."""
        # Old pattern
        old_pattern = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        # New pattern
        new_pattern = timestamp_for_filename()
        
        # Both should have same format
        assert len(old_pattern) == len(new_pattern)
        assert '_' in new_pattern


class TestPython312Compatibility:
    """Tests specific to Python 3.12+ compatibility."""
    
    def test_no_deprecation_warning(self):
        """Test that using the new utilities doesn't produce deprecation warnings."""
        import warnings
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            
            # Use new utilities
            _ = now_utc()
            _ = now_utc_iso()
            _ = to_iso8601(datetime.now(timezone.utc))
            _ = from_iso8601('2026-04-08T12:00:00Z')
            
            # Should not have deprecation warnings
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) == 0


class TestDistributedDeployments:
    """Tests for distributed deployment scenarios."""
    
    def test_consistent_utc_timestamps(self):
        """Test that all timestamps are consistently in UTC."""
        timestamps = [now_utc() for _ in range(10)]
        
        for ts in timestamps:
            assert ts.tzinfo == timezone.utc
    
    def test_iso_string_unambiguous(self):
        """Test that ISO strings are unambiguous."""
        iso_string = now_utc_iso()
        
        # Should have Z suffix indicating UTC
        assert iso_string.endswith('Z')
        
        # Should be parseable to UTC
        parsed = from_iso8601(iso_string)
        assert parsed.tzinfo == timezone.utc


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
