"""
ITEM-CTX-92: Context Zones with Differential Compression.

This module implements context zones with differential compression
based on content importance. Instead of compressing all context equally,
different zones receive different compression levels:

- CORE (0% compression): Active gates, current chunk, decisions
- PERIPHERY (20% compression): Related chunks, history
- ANOMALY (50% compression): Unrelated, old data

Author: TITAN FUSE Team
Version: 3.8.0
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta
import re
import logging

from src.utils.timezone import now_utc, now_utc_iso, from_iso8601


class ContextZone(Enum):
    """
    Zone classification for context content.
    
    Each zone has a different compression level:
    - CORE: 0% compression - preserve all detail
    - PERIPHERY: 20% compression - summarize, keep key points
    - ANOMALY: 50% compression - heavy compression, keep markers only
    """
    CORE = "core"
    PERIPHERY = "periphery"
    ANOMALY = "anomaly"
    
    @property
    def compression_ratio(self) -> float:
        """Get the compression ratio for this zone."""
        ratios = {
            ContextZone.CORE: 0.0,
            ContextZone.PERIPHERY: 0.2,
            ContextZone.ANOMALY: 0.5
        }
        return ratios[self]
    
    @property
    def retention_ratio(self) -> float:
        """Get the retention ratio for this zone (inverse of compression)."""
        return 1.0 - self.compression_ratio


@dataclass
class ZoneClassification:
    """
    Classification result for context content.
    
    Attributes:
        zone: The assigned context zone
        confidence: Confidence level of the classification (0.0-1.0)
        reasons: List of reasons for the classification
        original_size: Original content size in bytes
        compressed_size: Size after compression (set after compression)
        metadata: Additional metadata about the classification
    """
    zone: ContextZone
    confidence: float = 1.0
    reasons: List[str] = field(default_factory=list)
    original_size: int = 0
    compressed_size: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "zone": self.zone.value,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "original_size": self.original_size,
            "compressed_size": self.compressed_size,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ZoneClassification":
        """Create from dictionary representation."""
        return cls(
            zone=ContextZone(data["zone"]),
            confidence=data.get("confidence", 1.0),
            reasons=data.get("reasons", []),
            original_size=data.get("original_size", 0),
            compressed_size=data.get("compressed_size", 0),
            metadata=data.get("metadata", {})
        )


@dataclass
class ZoneStats:
    """Statistics for zone classification and compression."""
    
    total_classifications: int = 0
    core_count: int = 0
    periphery_count: int = 0
    anomaly_count: int = 0
    total_original_bytes: int = 0
    total_compressed_bytes: int = 0
    total_bytes_saved: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "total_classifications": self.total_classifications,
            "core_count": self.core_count,
            "periphery_count": self.periphery_count,
            "anomaly_count": self.anomaly_count,
            "total_original_bytes": self.total_original_bytes,
            "total_compressed_bytes": self.total_compressed_bytes,
            "total_bytes_saved": self.total_bytes_saved,
            "average_compression_ratio": (
                self.total_bytes_saved / self.total_original_bytes 
                if self.total_original_bytes > 0 else 0.0
            )
        }
    
    def update(self, classification: ZoneClassification) -> None:
        """Update stats with a new classification."""
        self.total_classifications += 1
        self.total_original_bytes += classification.original_size
        self.total_compressed_bytes += classification.compressed_size
        self.total_bytes_saved += (
            classification.original_size - classification.compressed_size
        )
        
        if classification.zone == ContextZone.CORE:
            self.core_count += 1
        elif classification.zone == ContextZone.PERIPHERY:
            self.periphery_count += 1
        else:
            self.anomaly_count += 1


class ContextZoneManager:
    """
    Manager for context zone classification and differential compression.
    
    ITEM-CTX-92: Implements context zones with differential compression
    based on content importance.
    
    Zone Classification Logic:
    - CORE indicators:
      - Gate names (GATE-00, GATE-01, etc.)
      - Decision/result/action markers
      - Current chunk data
      - Active session state
      - Recent timestamps (within last hour)
    
    - PERIPHERY indicators:
      - Historical chunks
      - Related file references
      - Previous decisions
      - Context summaries
    
    - ANOMALY indicators:
      - Very old data (older than session)
      - Unrelated file types
      - Debug/traces
      - Cached data
    
    Usage:
        manager = ContextZoneManager()
        
        # Classify content
        classification = manager.classify_content(content)
        
        # Apply compression
        compressed = manager.apply_compression(content, classification.zone)
        
        # Or do both at once
        result = manager.compress_context({
            "gate_output": "...",
            "history": "...",
            "cache": "..."
        })
    """
    
    # Default patterns for classification
    DEFAULT_CORE_PATTERNS = [
        r"GATE-\d{2}",                    # Gate names
        r"decision:",                     # Decision markers
        r"result:",                       # Result markers
        r"action:",                       # Action markers
        r"current_chunk",                 # Current chunk references
        r"active_session",                # Active session state
        r"CHUNK_\d+",                     # Chunk identifiers
        r"status:\s*(pending|active)",    # Active statuses
        r"priority:\s*(high|critical)",   # High priority items
    ]
    
    DEFAULT_PERIPHERY_PATTERNS = [
        r"history",                       # Historical references
        r"previous_chunk",                # Previous chunks
        r"related_file",                  # Related files
        r"context_summary",               # Context summaries
        r"previous_decision",             # Previous decisions
        r"dependency",                    # Dependencies
        r"reference:",                    # References
    ]
    
    DEFAULT_ANOMALY_PATTERNS = [
        r"debug:",                        # Debug output
        r"trace:",                        # Trace data
        r"cached_data",                   # Cached data
        r"temp:",                         # Temporary data
        r"legacy:",                       # Legacy content
        r"deprecated:",                   # Deprecated items
        r"backup:",                       # Backup data
    ]
    
    # Time thresholds for age-based classification
    CORE_AGE_THRESHOLD_HOURS = 1
    PERIPHERY_AGE_THRESHOLD_HOURS = 24
    ANOMALY_AGE_THRESHOLD_DAYS = 7
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the ContextZoneManager.
        
        Args:
            config: Optional configuration dictionary with:
                - core_patterns: Additional patterns for CORE zone
                - periphery_patterns: Additional patterns for PERIPHERY zone
                - anomaly_patterns: Additional patterns for ANOMALY zone
                - compression_enabled: Whether compression is enabled (default: True)
                - session_start: ISO timestamp of session start
        """
        self._config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # Initialize patterns
        self._core_patterns: List[str] = list(self.DEFAULT_CORE_PATTERNS)
        self._periphery_patterns: List[str] = list(self.DEFAULT_PERIPHERY_PATTERNS)
        self._anomaly_patterns: List[str] = list(self.DEFAULT_ANOMALY_PATTERNS)
        
        # Compiled regex patterns (cached for performance)
        # Initialize before adding custom patterns
        self._compiled_core: List[re.Pattern] = []
        self._compiled_periphery: List[re.Pattern] = []
        self._compiled_anomaly: List[re.Pattern] = []
        
        # Session tracking
        self._session_start: Optional[datetime] = None
        session_start_str = self._config.get("session_start")
        if session_start_str:
            try:
                self._session_start = from_iso8601(session_start_str)
            except (ValueError, TypeError):
                self._session_start = now_utc()
        else:
            self._session_start = now_utc()
        
        # Compression settings
        self._compression_enabled = self._config.get("compression_enabled", True)
        
        # Statistics
        self._stats = ZoneStats()
        
        # Compile default patterns first
        self._compile_patterns()
        
        # Add custom patterns from config (they will compile and append)
        for pattern in self._config.get("core_patterns", []):
            self.add_core_pattern(pattern)
        
        for pattern in self._config.get("periphery_patterns", []):
            self.add_periphery_pattern(pattern)
        
        for pattern in self._config.get("anomaly_patterns", []):
            self.add_anomaly_pattern(pattern)
        
        self._logger.info(
            f"ContextZoneManager initialized: "
            f"core_patterns={len(self._core_patterns)}, "
            f"periphery_patterns={len(self._periphery_patterns)}, "
            f"anomaly_patterns={len(self._anomaly_patterns)}"
        )
    
    def _compile_patterns(self) -> None:
        """Compile regex patterns for efficient matching."""
        self._compiled_core = [
            re.compile(p, re.IGNORECASE) for p in self._core_patterns
        ]
        self._compiled_periphery = [
            re.compile(p, re.IGNORECASE) for p in self._periphery_patterns
        ]
        self._compiled_anomaly = [
            re.compile(p, re.IGNORECASE) for p in self._anomaly_patterns
        ]
    
    def classify_content(
        self, 
        content: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> ZoneClassification:
        """
        Classify content into a context zone.
        
        Args:
            content: The content to classify
            context: Optional context dictionary with additional info:
                - timestamp: ISO timestamp of content creation
                - file_type: Type of file being processed
                - is_current: Whether this is current/active content
                - references: List of referenced items
        
        Returns:
            ZoneClassification with zone assignment and reasoning
        """
        if not content:
            return ZoneClassification(
                zone=ContextZone.ANOMALY,
                confidence=1.0,
                reasons=["Empty content"],
                original_size=0,
                compressed_size=0
            )
        
        original_size = len(content)
        context = context or {}
        reasons: List[str] = []
        scores = {
            ContextZone.CORE: 0.0,
            ContextZone.PERIPHERY: 0.0,
            ContextZone.ANOMALY: 0.0
        }
        
        # Check pattern matches
        core_matches = self._count_pattern_matches(content, self._compiled_core)
        periphery_matches = self._count_pattern_matches(content, self._compiled_periphery)
        anomaly_matches = self._count_pattern_matches(content, self._compiled_anomaly)
        
        # Score based on pattern matches
        if core_matches > 0:
            scores[ContextZone.CORE] += core_matches * 0.3
            reasons.append(f"Contains {core_matches} core indicators")
        
        if periphery_matches > 0:
            scores[ContextZone.PERIPHERY] += periphery_matches * 0.2
            reasons.append(f"Contains {periphery_matches} periphery indicators")
        
        if anomaly_matches > 0:
            scores[ContextZone.ANOMALY] += anomaly_matches * 0.25
            reasons.append(f"Contains {anomaly_matches} anomaly indicators")
        
        # Check timestamp if provided
        timestamp_str = context.get("timestamp")
        if timestamp_str:
            age_score = self._score_by_age(timestamp_str)
            if age_score["zone"]:
                scores[age_score["zone"]] += age_score["weight"]
                reasons.append(age_score["reason"])
        
        # Check if explicitly marked as current
        if context.get("is_current"):
            scores[ContextZone.CORE] += 0.5
            reasons.append("Marked as current/active content")
        
        # Check file type context
        file_type = context.get("file_type", "")
        if file_type:
            type_score = self._score_by_file_type(file_type)
            scores[type_score["zone"]] += type_score["weight"]
            if type_score["reason"]:
                reasons.append(type_score["reason"])
        
        # Check for gate names (strong CORE indicator)
        gate_matches = len(re.findall(r"GATE-\d{2}", content))
        if gate_matches > 0:
            scores[ContextZone.CORE] += gate_matches * 0.4
            reasons.append(f"Contains {gate_matches} gate references")
        
        # Determine final zone
        best_zone = max(scores, key=scores.get)
        total_score = sum(scores.values())
        
        # Calculate confidence
        if total_score > 0:
            confidence = scores[best_zone] / total_score
        else:
            # Default to PERIPHERY if no indicators found
            best_zone = ContextZone.PERIPHERY
            confidence = 0.5
            reasons.append("No strong indicators, defaulting to periphery")
        
        # Ensure confidence is in valid range
        confidence = min(1.0, max(0.0, confidence))
        
        return ZoneClassification(
            zone=best_zone,
            confidence=confidence,
            reasons=reasons,
            original_size=original_size,
            compressed_size=original_size,  # Will be updated after compression
            metadata={
                "scores": {z.value: s for z, s in scores.items()},
                "context_provided": bool(context)
            }
        )
    
    def _count_pattern_matches(
        self, 
        content: str, 
        patterns: List[re.Pattern]
    ) -> int:
        """Count total pattern matches in content."""
        count = 0
        for pattern in patterns:
            count += len(pattern.findall(content))
        return count
    
    def _score_by_age(self, timestamp_str: str) -> Dict[str, Any]:
        """Score content based on its age."""
        try:
            content_time = from_iso8601(timestamp_str)
            now = now_utc()
            age = now - content_time
            
            if age < timedelta(hours=self.CORE_AGE_THRESHOLD_HOURS):
                return {
                    "zone": ContextZone.CORE,
                    "weight": 0.3,
                    "reason": f"Content is recent (within {self.CORE_AGE_THRESHOLD_HOURS}h)"
                }
            elif age < timedelta(hours=self.PERIPHERY_AGE_THRESHOLD_HOURS):
                return {
                    "zone": ContextZone.PERIPHERY,
                    "weight": 0.2,
                    "reason": f"Content is moderately recent (within {self.PERIPHERY_AGE_THRESHOLD_HOURS}h)"
                }
            elif age > timedelta(days=self.ANOMALY_AGE_THRESHOLD_DAYS):
                return {
                    "zone": ContextZone.ANOMALY,
                    "weight": 0.3,
                    "reason": f"Content is old (> {self.ANOMALY_AGE_THRESHOLD_DAYS} days)"
                }
        except (ValueError, TypeError):
            pass
        
        return {"zone": None, "weight": 0, "reason": None}
    
    def _score_by_file_type(self, file_type: str) -> Dict[str, Any]:
        """Score content based on file type."""
        file_type_lower = file_type.lower()
        
        # Core file types
        if file_type_lower in ("gate", "decision", "action", "current"):
            return {
                "zone": ContextZone.CORE,
                "weight": 0.4,
                "reason": f"File type '{file_type}' indicates core content"
            }
        
        # Anomaly file types
        if file_type_lower in ("cache", "temp", "debug", "trace", "backup", "log"):
            return {
                "zone": ContextZone.ANOMALY,
                "weight": 0.3,
                "reason": f"File type '{file_type}' indicates anomaly content"
            }
        
        # Periphery file types
        if file_type_lower in ("history", "reference", "summary", "archive"):
            return {
                "zone": ContextZone.PERIPHERY,
                "weight": 0.3,
                "reason": f"File type '{file_type}' indicates periphery content"
            }
        
        return {"zone": None, "weight": 0, "reason": None}
    
    def apply_compression(self, content: str, zone: ContextZone) -> str:
        """
        Apply zone-appropriate compression to content.
        
        Args:
            content: The content to compress
            zone: The zone to apply compression for
        
        Returns:
            Compressed content string
        """
        if not content:
            return content
        
        if not self._compression_enabled:
            return content
        
        original_size = len(content)
        
        if zone == ContextZone.CORE:
            # 0% compression - preserve everything
            compressed = self._compress_core(content)
        elif zone == ContextZone.PERIPHERY:
            # 20% compression - summarize, keep key points
            compressed = self._compress_periphery(content)
        else:
            # 50% compression - heavy compression
            compressed = self._compress_anomaly(content)
        
        # Log compression stats
        compressed_size = len(compressed)
        actual_ratio = 1 - (compressed_size / original_size) if original_size > 0 else 0
        
        self._logger.debug(
            f"Compression applied: zone={zone.value}, "
            f"original={original_size}, compressed={compressed_size}, "
            f"ratio={actual_ratio:.2%}"
        )
        
        return compressed
    
    def _compress_core(self, content: str) -> str:
        """
        Compress CORE content (0% compression).
        
        For CORE content, we preserve everything but may add markers
        for easier navigation.
        """
        # No actual compression, just mark it
        return content
    
    def _compress_periphery(self, content: str) -> str:
        """
        Compress PERIPHERY content (20% compression).
        
        Strategy:
        - Remove redundant whitespace
        - Summarize repeated patterns
        - Keep section headers
        - Preserve key-value pairs
        """
        if not content:
            return content
        
        lines = content.split('\n')
        compressed_lines = []
        seen_content = set()  # Track seen content to reduce redundancy
        
        for line in lines:
            stripped = line.strip()
            
            # Keep empty lines for structure (but reduce multiple)
            if not stripped:
                if compressed_lines and compressed_lines[-1].strip():
                    compressed_lines.append("")
                continue
            
            # Keep headers and key-value pairs
            if stripped.startswith('#') or ':' in stripped:
                compressed_lines.append(line.rstrip())
                continue
            
            # Reduce repetition
            content_hash = hash(stripped)
            if content_hash in seen_content:
                continue
            seen_content.add(content_hash)
            
            # Compress whitespace in the line
            compressed_line = ' '.join(stripped.split())
            compressed_lines.append(compressed_line)
        
        # Remove trailing empty lines
        while compressed_lines and not compressed_lines[-1].strip():
            compressed_lines.pop()
        
        return '\n'.join(compressed_lines)
    
    def _compress_anomaly(self, content: str) -> str:
        """
        Compress ANOMALY content (50% compression).
        
        Strategy:
        - Keep only essential markers
        - Replace content with summaries
        - Preserve structure indicators
        - Ensure output is never larger than input
        """
        if not content:
            return content
        
        original_size = len(content)
        lines = content.split('\n')
        line_count = len(lines)
        
        # Extract key markers
        gate_pattern = re.compile(r'GATE-\d{2}')
        decision_pattern = re.compile(r'(decision|result|action):', re.IGNORECASE)
        
        gates_found = set()
        decisions_found = []
        
        for line in lines:
            # Extract gate references
            gates = gate_pattern.findall(line)
            gates_found.update(gates)
            
            # Extract decision/result/action markers
            dec_match = decision_pattern.search(line)
            if dec_match:
                decisions_found.append(line.strip()[:50])  # Truncate
        
        # Build compressed summary - keep it minimal
        summary_parts = [f"[ANOMALY:{line_count}L]"]
        
        if gates_found:
            summary_parts.append(f"[G:{','.join(sorted(gates_found)[:3])}]")  # Max 3 gates
        
        if decisions_found:
            # Keep only first decision marker
            summary_parts.append(f"[M:{decisions_found[0][:30]}]")
        
        compressed = ' '.join(summary_parts)
        
        # Ensure compressed is actually smaller
        if len(compressed) >= original_size:
            # Fall back to truncation for small content
            target_size = max(10, int(original_size * 0.5))
            compressed = content[:target_size] + "..."
        
        return compressed
    
    def compress_context(
        self, 
        context_dict: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Compress an entire context dictionary with zone-based compression.
        
        Args:
            context_dict: Dictionary of context_key -> content
        
        Returns:
            Dictionary with:
            - compressed: Dict of compressed content
            - classifications: Dict of classifications per key
            - stats: Overall compression statistics
        """
        compressed = {}
        classifications = {}
        total_original = 0
        total_compressed = 0
        
        for key, content in context_dict.items():
            # Classify
            classification = self.classify_content(content)
            
            # Compress
            compressed_content = self.apply_compression(content, classification.zone)
            
            # Update sizes
            classification.compressed_size = len(compressed_content)
            
            # Update stats
            self._stats.update(classification)
            
            compressed[key] = compressed_content
            classifications[key] = classification
            
            total_original += classification.original_size
            total_compressed += classification.compressed_size
        
        # Calculate overall stats
        stats = {
            "total_keys": len(context_dict),
            "total_original_bytes": total_original,
            "total_compressed_bytes": total_compressed,
            "bytes_saved": total_original - total_compressed,
            "compression_ratio": (
                1 - (total_compressed / total_original) if total_original > 0 else 0
            )
        }
        
        return {
            "compressed": compressed,
            "classifications": {k: c.to_dict() for k, c in classifications.items()},
            "stats": stats
        }
    
    def get_zone_stats(self) -> Dict[str, Any]:
        """
        Get statistics about zone classifications and compression.
        
        Returns:
            Dictionary with classification counts, byte savings, etc.
        """
        return self._stats.to_dict()
    
    def add_core_pattern(self, pattern: str) -> None:
        """
        Add a custom pattern for CORE zone classification.
        
        Args:
            pattern: Regex pattern string to add
        """
        if pattern and pattern not in self._core_patterns:
            self._core_patterns.append(pattern)
            self._compiled_core.append(re.compile(pattern, re.IGNORECASE))
            self._logger.debug(f"Added CORE pattern: {pattern}")
    
    def add_periphery_pattern(self, pattern: str) -> None:
        """
        Add a custom pattern for PERIPHERY zone classification.
        
        Args:
            pattern: Regex pattern string to add
        """
        if pattern and pattern not in self._periphery_patterns:
            self._periphery_patterns.append(pattern)
            self._compiled_periphery.append(re.compile(pattern, re.IGNORECASE))
            self._logger.debug(f"Added PERIPHERY pattern: {pattern}")
    
    def add_anomaly_pattern(self, pattern: str) -> None:
        """
        Add a custom pattern for ANOMALY zone classification.
        
        Args:
            pattern: Regex pattern string to add
        """
        if pattern and pattern not in self._anomaly_patterns:
            self._anomaly_patterns.append(pattern)
            self._compiled_anomaly.append(re.compile(pattern, re.IGNORECASE))
            self._logger.debug(f"Added ANOMALY pattern: {pattern}")
    
    def reset_stats(self) -> None:
        """Reset all statistics counters."""
        self._stats = ZoneStats()
        self._logger.info("Zone statistics reset")
    
    def set_session_start(self, timestamp: datetime) -> None:
        """
        Set the session start time for age-based classification.
        
        Args:
            timestamp: The session start timestamp
        """
        self._session_start = timestamp
        self._logger.info(f"Session start set to: {timestamp.isoformat()}")
    
    def enable_compression(self, enabled: bool = True) -> None:
        """
        Enable or disable compression.
        
        Args:
            enabled: Whether compression should be enabled
        """
        self._compression_enabled = enabled
        self._logger.info(f"Compression {'enabled' if enabled else 'disabled'}")
    
    def get_patterns(self) -> Dict[str, List[str]]:
        """
        Get all patterns currently configured.
        
        Returns:
            Dictionary with core, periphery, and anomaly pattern lists
        """
        return {
            "core": list(self._core_patterns),
            "periphery": list(self._periphery_patterns),
            "anomaly": list(self._anomaly_patterns)
        }
    
    def estimate_compression(self, content: str) -> Dict[str, Any]:
        """
        Estimate compression for content without actually compressing.
        
        Args:
            content: Content to estimate compression for
        
        Returns:
            Dictionary with estimated compression info
        """
        classification = self.classify_content(content)
        estimated_size = int(len(content) * classification.zone.retention_ratio)
        
        return {
            "zone": classification.zone.value,
            "original_size": len(content),
            "estimated_compressed_size": estimated_size,
            "estimated_savings": len(content) - estimated_size,
            "compression_ratio": classification.zone.compression_ratio,
            "confidence": classification.confidence
        }


def create_zone_manager(
    config: Optional[Dict[str, Any]] = None
) -> ContextZoneManager:
    """
    Factory function to create a ContextZoneManager.
    
    Args:
        config: Optional configuration dictionary
    
    Returns:
        ContextZoneManager instance
    """
    return ContextZoneManager(config)
