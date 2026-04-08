"""
ITEM-SEC-121: Timestamp Timezone Awareness.

This module provides timezone-aware datetime utilities to replace
the deprecated datetime.utcnow() function (deprecated in Python 3.12+).

All timestamps in TITAN Protocol should use these utilities to ensure:
1. Forward compatibility with Python 3.12+
2. Consistent UTC timezone handling
3. Unambiguous timestamps for distributed deployments

Usage:
    from src.utils.timezone import now_utc, to_iso8601
    
    # Get current UTC time (timezone-aware)
    timestamp = now_utc()
    
    # Convert to ISO8601 string with 'Z' suffix
    iso_string = to_iso8601(timestamp)
    
    # Or use the convenience function for ISO strings directly
    iso_string = now_utc_iso()
"""

from datetime import datetime, timezone
from typing import Optional, Union
import hashlib


class TimezoneManager:
    """
    Manager for timezone-aware timestamp operations.
    
    Provides utilities for creating, formatting, and parsing
    timezone-aware timestamps. Replaces deprecated datetime.utcnow()
    with datetime.now(timezone.utc) for Python 3.12+ compatibility.
    
    Attributes:
        DEFAULT_TIMEZONE: The default timezone (UTC)
        ISO_FORMAT: Standard ISO8601 format string
    """
    
    DEFAULT_TIMEZONE = timezone.utc
    ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"
    
    _instance: Optional["TimezoneManager"] = None
    _session_timezone: Optional[str] = None
    
    def __new__(cls) -> "TimezoneManager":
        """Singleton pattern for consistent timezone management."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def now_utc(cls) -> datetime:
        """
        Get the current UTC time as a timezone-aware datetime.
        
        This replaces datetime.utcnow() which is deprecated in Python 3.12+.
        
        Returns:
            datetime: Current UTC time with timezone info attached.
        
        Example:
            >>> ts = TimezoneManager.now_utc()
            >>> ts.tzinfo
            datetime.timezone.utc
        """
        return datetime.now(cls.DEFAULT_TIMEZONE)
    
    @classmethod
    def now_utc_iso(cls) -> str:
        """
        Get the current UTC time as an ISO8601 string with 'Z' suffix.
        
        This is the most common use case for timestamp generation
        in the TITAN Protocol.
        
        Returns:
            str: ISO8601 formatted string with 'Z' suffix.
        
        Example:
            >>> TimezoneManager.now_utc_iso()
            '2026-04-08T12:34:56.789012Z'
        """
        return cls.to_iso8601(cls.now_utc())
    
    @classmethod
    def to_iso8601(cls, dt: datetime) -> str:
        """
        Convert a datetime to ISO8601 string with 'Z' suffix.
        
        If the datetime is timezone-aware and not UTC, it will be
        converted to UTC before formatting.
        
        Args:
            dt: The datetime to convert.
        
        Returns:
            str: ISO8601 formatted string with 'Z' suffix.
        
        Example:
            >>> from datetime import datetime, timezone
            >>> dt = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)
            >>> TimezoneManager.to_iso8601(dt)
            '2026-04-08T12:00:00.000000Z'
        """
        if dt.tzinfo is not None and dt.tzinfo != cls.DEFAULT_TIMEZONE:
            # Convert to UTC if timezone is different
            dt = dt.astimezone(cls.DEFAULT_TIMEZONE)
        
        # Format with microseconds and 'Z' suffix
        return dt.strftime(cls.ISO_FORMAT)[:-3] + "Z"
    
    @classmethod
    def from_iso8601(cls, s: str) -> datetime:
        """
        Parse an ISO8601 string to a timezone-aware datetime.
        
        Handles strings with or without 'Z' suffix, and with or
        without timezone offset.
        
        Args:
            s: The ISO8601 string to parse.
        
        Returns:
            datetime: Timezone-aware datetime in UTC.
        
        Raises:
            ValueError: If the string cannot be parsed.
        
        Example:
            >>> TimezoneManager.from_iso8601('2026-04-08T12:00:00Z')
            datetime.datetime(2026, 4, 8, 12, 0, tzinfo=datetime.timezone.utc)
        """
        # Handle 'Z' suffix
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        
        # Try parsing with timezone
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=cls.DEFAULT_TIMEZONE)
            return dt.astimezone(cls.DEFAULT_TIMEZONE)
        except ValueError:
            pass
        
        # Try common formats
        formats = [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(s, fmt)
                return dt.replace(tzinfo=cls.DEFAULT_TIMEZONE)
            except ValueError:
                continue
        
        raise ValueError(f"Cannot parse ISO8601 string: {s}")
    
    @classmethod
    def generate_seed(cls, session_id: str) -> int:
        """
        Generate a deterministic seed from session ID.
        
        Used for deterministic mode to ensure reproducible results.
        
        Args:
            session_id: The session identifier.
        
        Returns:
            int: A deterministic seed value.
        """
        hash_bytes = hashlib.sha256(session_id.encode()).digest()
        return int.from_bytes(hash_bytes[:8], byteorder='big')
    
    @classmethod
    def set_session_timezone(cls, tz_name: str) -> None:
        """
        Set the session timezone for display purposes.
        
        Note: All internal timestamps remain in UTC.
        
        Args:
            tz_name: IANA timezone name (e.g., 'America/New_York').
        """
        cls._session_timezone = tz_name
    
    @classmethod
    def get_session_timezone(cls) -> Optional[str]:
        """
        Get the session timezone.
        
        Returns:
            Optional[str]: The session timezone name or None.
        """
        return cls._session_timezone
    
    @classmethod
    def timestamp_for_id(cls) -> str:
        """
        Generate a timestamp suitable for use in IDs.
        
        Format: YYYYMMDDHHMMSSffffff (no separators)
        
        Returns:
            str: Compact timestamp string.
        
        Example:
            >>> TimezoneManager.timestamp_for_id()
            '20260408123456789012'
        """
        return cls.now_utc().strftime("%Y%m%d%H%M%S%f")
    
    @classmethod
    def timestamp_for_filename(cls) -> str:
        """
        Generate a timestamp suitable for filenames.
        
        Format: YYYYMMDD_HHMMSS
        
        Returns:
            str: Filename-safe timestamp string.
        
        Example:
            >>> TimezoneManager.timestamp_for_filename()
            '20260408_123456'
        """
        return cls.now_utc().strftime("%Y%m%d_%H%M%S")


# Module-level convenience functions (most commonly used)

def now_utc() -> datetime:
    """
    Get the current UTC time as a timezone-aware datetime.
    
    This is a convenience function that delegates to TimezoneManager.now_utc().
    
    Returns:
        datetime: Current UTC time with timezone info.
    """
    return TimezoneManager.now_utc()


def now_utc_iso() -> str:
    """
    Get the current UTC time as an ISO8601 string with 'Z' suffix.
    
    This is the primary replacement for datetime.utcnow().isoformat() + "Z".
    
    Returns:
        str: ISO8601 formatted string.
    """
    return TimezoneManager.now_utc_iso()


def to_iso8601(dt: datetime) -> str:
    """
    Convert a datetime to ISO8601 string with 'Z' suffix.
    
    Args:
        dt: The datetime to convert.
    
    Returns:
        str: ISO8601 formatted string.
    """
    return TimezoneManager.to_iso8601(dt)


def from_iso8601(s: str) -> datetime:
    """
    Parse an ISO8601 string to a timezone-aware datetime.
    
    Args:
        s: The ISO8601 string to parse.
    
    Returns:
        datetime: Timezone-aware datetime in UTC.
    """
    return TimezoneManager.from_iso8601(s)


def timestamp_for_id() -> str:
    """
    Generate a timestamp suitable for use in IDs.
    
    Returns:
        str: Compact timestamp string.
    """
    return TimezoneManager.timestamp_for_id()


def timestamp_for_filename() -> str:
    """
    Generate a timestamp suitable for filenames.
    
    Returns:
        str: Filename-safe timestamp string.
    """
    return TimezoneManager.timestamp_for_filename()
