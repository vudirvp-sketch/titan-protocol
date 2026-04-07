"""
Type-Aware Fusion Engine for TITAN Protocol.

Implements ITEM-CAT-03: Content fusion with type isolation and density prioritization.
Enforces strict type-matching merge rules and transparent discard logging.

Core Principles:
1. TYPE isolation: Never merge different content types mid-step
2. DENSITY prioritization: HIGH_DENSITY always included, LOW_DENSITY filtered
3. Transparency: All discards logged with reason and context

Author: TITAN FUSE Team
Version: 3.2.3
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
import logging
import uuid

# Configure module logger
logger = logging.getLogger(__name__)


class ContentType(Enum):
    """
    Content type classification for fusion operations.
    
    Each type represents a distinct category of content that should
    not be merged with other types during the fusion process.
    
    Attributes:
        FACT: Objective, verifiable statements
        OPINION: Subjective interpretations or viewpoints
        CODE: Source code or code snippets
        WARNING: Alerts about potential issues or risks
        STEP: Sequential instructions or procedures
        EXAMPLE: Illustrative examples or demonstrations
        METADATA: Structural or contextual information
    """
    FACT = "FACT"
    OPINION = "OPINION"
    CODE = "CODE"
    WARNING = "WARNING"
    STEP = "STEP"
    EXAMPLE = "EXAMPLE"
    METADATA = "METADATA"


class ContentDensity(Enum):
    """
    Content density classification for filtering decisions.
    
    Density determines inclusion priority during fusion:
    - HIGH_DENSITY: Always included in output (critical content)
    - LOW_DENSITY: Included only with unique_context or risk_caveat
    
    Attributes:
        HIGH: High-information density, essential content
        LOW: Low-information density, supplemental content
    """
    HIGH = "HIGH"
    LOW = "LOW"


class TypeMismatchError(Exception):
    """
    Exception raised when attempting to merge content of different types.
    
    The Type-Aware Fusion Engine strictly prohibits cross-type merging
    to maintain content integrity and semantic coherence.
    
    Attributes:
        source_type: The type of the source content unit
        target_type: The type of the target content unit
        message: Human-readable error description
    """
    
    def __init__(
        self, 
        source_type: ContentType, 
        target_type: ContentType,
        message: Optional[str] = None
    ) -> None:
        """
        Initialize TypeMismatchError.
        
        Args:
            source_type: The content type being merged from
            target_type: The content type being merged to
            message: Optional custom error message
        """
        self.source_type = source_type
        self.target_type = target_type
        self.message = message or (
            f"Cannot merge content of type '{source_type.value}' with "
            f"type '{target_type.value}'. Cross-type merging is prohibited."
        )
        super().__init__(self.message)
        
        logger.error(
            "TypeMismatchError raised: source=%s, target=%s",
            source_type.value,
            target_type.value
        )


@dataclass
class ContentUnit:
    """
    A unit of content for fusion processing.
    
    Represents a discrete piece of content with type classification,
    density rating, and optional metadata for fusion decisions.
    
    Attributes:
        content_type: Classification of content type
        density: Information density rating
        text: The actual content text
        unique_context: Whether this content provides unique context
        risk_caveat: Optional warning about content risks
        source: Optional source identifier
        relevance_score: Relevance score (0.0 - 1.0)
        id: Unique identifier for tracking
    
    Example:
        >>> unit = ContentUnit(
        ...     content_type=ContentType.FACT,
        ...     density=ContentDensity.HIGH,
        ...     text="The function returns an integer.",
        ...     unique_context=False,
        ...     risk_caveat=None,
        ...     source="api_docs",
        ...     relevance_score=0.95
        ... )
    """
    content_type: ContentType
    density: ContentDensity
    text: str
    unique_context: bool = False
    risk_caveat: Optional[str] = None
    source: Optional[str] = None
    relevance_score: float = 1.0
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    def __post_init__(self) -> None:
        """Validate content unit after initialization."""
        if not 0.0 <= self.relevance_score <= 1.0:
            raise ValueError(
                f"relevance_score must be between 0.0 and 1.0, "
                f"got {self.relevance_score}"
            )
        
        if not self.text or not self.text.strip():
            raise ValueError("text cannot be empty or whitespace")
    
    def should_include(self) -> bool:
        """
        Determine if this content unit should be included in output.
        
        HIGH_DENSITY: Always included
        LOW_DENSITY: Included only if has unique_context or risk_caveat
        
        Returns:
            True if the unit should be included in merged output
        """
        if self.density == ContentDensity.HIGH:
            return True
        
        # LOW_DENSITY: check for inclusion criteria
        return self.unique_context or self.risk_caveat is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "content_type": self.content_type.value,
            "density": self.density.value,
            "text": self.text,
            "unique_context": self.unique_context,
            "risk_caveat": self.risk_caveat,
            "source": self.source,
            "relevance_score": self.relevance_score
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ContentUnit':
        """Create ContentUnit from dictionary."""
        return cls(
            content_type=ContentType(data["content_type"]),
            density=ContentDensity(data["density"]),
            text=data["text"],
            unique_context=data.get("unique_context", False),
            risk_caveat=data.get("risk_caveat"),
            source=data.get("source"),
            relevance_score=data.get("relevance_score", 1.0),
            id=data.get("id", str(uuid.uuid4())[:8])
        )


@dataclass
class DiscardLog:
    """
    Log entry for discarded content units.
    
    Records the reason and context for why a content unit was
    excluded from the final merged output.
    
    Attributes:
        unit_id: ID of the discarded content unit
        content_type: Type of the discarded content
        density: Density classification of the discarded content
        reason: Human-readable reason for discard
        text_preview: Preview of the discarded text (truncated)
        timestamp: When the discard occurred
        source: Source of the discarded content
    """
    unit_id: str
    content_type: ContentType
    density: ContentDensity
    reason: str
    text_preview: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Truncate text preview to reasonable length."""
        max_preview_length = 100
        if len(self.text_preview) > max_preview_length:
            self.text_preview = self.text_preview[:max_preview_length - 3] + "..."
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "unit_id": self.unit_id,
            "content_type": self.content_type.value,
            "density": self.density.value,
            "reason": self.reason,
            "text_preview": self.text_preview,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source
        }


@dataclass
class MergedResult:
    """
    Result of a type-aware fusion merge operation.
    
    Contains the merged content organized by type, along with
    statistics and discard logs for transparency.
    
    Attributes:
        merged_content: Dictionary mapping content types to merged text
        total_units_processed: Total number of units input to merge
        total_units_included: Number of units included in output
        total_units_discarded: Number of units discarded
        discard_logs: List of discard log entries
        type_counts: Count of units per content type
        merge_timestamp: When the merge was performed
        fusion_id: Unique identifier for this fusion operation
    """
    merged_content: Dict[ContentType, str] = field(default_factory=dict)
    total_units_processed: int = 0
    total_units_included: int = 0
    total_units_discarded: int = 0
    discard_logs: List[DiscardLog] = field(default_factory=list)
    type_counts: Dict[ContentType, int] = field(default_factory=dict)
    merge_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fusion_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    
    def get_combined_output(self, separator: str = "\n\n") -> str:
        """
        Get combined output from all content types.
        
        Args:
            separator: String to separate content type sections
            
        Returns:
            Combined string of all merged content
        """
        sections = []
        for content_type, text in self.merged_content.items():
            if text.strip():
                sections.append(f"[{content_type.value}]\n{text}")
        return separator.join(sections)
    
    def get_content_by_type(self, content_type: ContentType) -> Optional[str]:
        """
        Get merged content for a specific type.
        
        Args:
            content_type: The content type to retrieve
            
        Returns:
            Merged text for the type, or None if not present
        """
        return self.merged_content.get(content_type)
    
    def get_discard_rate(self) -> float:
        """
        Calculate the discard rate as a percentage.
        
        Returns:
            Discard rate (0.0 - 1.0), or 0.0 if no units processed
        """
        if self.total_units_processed == 0:
            return 0.0
        return self.total_units_discarded / self.total_units_processed
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "fusion_id": self.fusion_id,
            "merged_content": {
                ct.value: text for ct, text in self.merged_content.items()
            },
            "total_units_processed": self.total_units_processed,
            "total_units_included": self.total_units_included,
            "total_units_discarded": self.total_units_discarded,
            "discard_rate": round(self.get_discard_rate(), 3),
            "discard_logs": [log.to_dict() for log in self.discard_logs],
            "type_counts": {
                ct.value: count for ct, count in self.type_counts.items()
            },
            "merge_timestamp": self.merge_timestamp.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MergedResult':
        """Create MergedResult from dictionary."""
        merged_content = {
            ContentType(ct): text 
            for ct, text in data.get("merged_content", {}).items()
        }
        type_counts = {
            ContentType(ct): count 
            for ct, count in data.get("type_counts", {}).items()
        }
        discard_logs = [
            DiscardLog(
                unit_id=log["unit_id"],
                content_type=ContentType(log["content_type"]),
                density=ContentDensity(log["density"]),
                reason=log["reason"],
                text_preview=log["text_preview"],
                source=log.get("source"),
                timestamp=datetime.fromisoformat(log["timestamp"])
            )
            for log in data.get("discard_logs", [])
        ]
        
        return cls(
            merged_content=merged_content,
            total_units_processed=data.get("total_units_processed", 0),
            total_units_included=data.get("total_units_included", 0),
            total_units_discarded=data.get("total_units_discarded", 0),
            discard_logs=discard_logs,
            type_counts=type_counts,
            fusion_id=data.get("fusion_id", str(uuid.uuid4())[:12]),
            merge_timestamp=datetime.fromisoformat(data["merge_timestamp"])
            if "merge_timestamp" in data else datetime.now(timezone.utc)
        )


class TypeAwareFusion:
    """
    Type-Aware Fusion Engine for content merging.
    
    Implements the TITAN FUSE protocol for intelligent content fusion
    with strict type isolation and density-based filtering.
    
    Core Rules:
    1. GROUP BY TYPE: Content is grouped by type before any merging
    2. DENSITY FILTER: LOW_DENSITY filtered unless unique_context or risk_caveat
    3. DISCARD LOGGING: All discards recorded with reason
    
    Example:
        >>> fusion = TypeAwareFusion()
        >>> units = [
        ...     ContentUnit(ContentType.FACT, ContentDensity.HIGH, "Fact 1"),
        ...     ContentUnit(ContentType.FACT, ContentDensity.LOW, "Fact 2"),
        ...     ContentUnit(ContentType.CODE, ContentDensity.HIGH, "code()"),
        ... ]
        >>> result = fusion.merge_units(units)
        >>> print(result.get_combined_output())
    """
    
    def __init__(self, min_relevance_threshold: float = 0.0) -> None:
        """
        Initialize the Type-Aware Fusion Engine.
        
        Args:
            min_relevance_threshold: Minimum relevance score for inclusion
                                    (default: 0.0, include all relevant content)
        """
        self.min_relevance_threshold = min_relevance_threshold
        self._logger = logging.getLogger(f"{__name__}.TypeAwareFusion")
        
        self._logger.info(
            "TypeAwareFusion initialized with min_relevance_threshold=%.2f",
            min_relevance_threshold
        )
    
    def merge_units(self, units: List[ContentUnit]) -> MergedResult:
        """
        Merge content units with type isolation and density filtering.
        
        Process flow:
        1. Validate input units
        2. Group units by content type
        3. Apply density filtering within each type group
        4. Merge filtered units by type
        5. Log all discards
        
        Args:
            units: List of ContentUnit objects to merge
            
        Returns:
            MergedResult containing merged content and discard logs
            
        Raises:
            TypeMismatchError: Never raised by this method (internal validation only)
        """
        self._logger.info("Starting merge of %d content units", len(units))
        
        result = MergedResult()
        result.total_units_processed = len(units)
        
        if not units:
            self._logger.warning("No units provided for merge")
            return result
        
        # Step 1: Group units by content type
        type_groups: Dict[ContentType, List[ContentUnit]] = {}
        for unit in units:
            if unit.content_type not in type_groups:
                type_groups[unit.content_type] = []
            type_groups[unit.content_type].append(unit)
        
        self._logger.debug(
            "Grouped units into %d content types: %s",
            len(type_groups),
            [ct.value for ct in type_groups.keys()]
        )
        
        # Step 2: Process each type group
        for content_type, group_units in type_groups.items():
            result.type_counts[content_type] = len(group_units)
            
            included_units: List[ContentUnit] = []
            
            for unit in group_units:
                # Check relevance threshold
                if unit.relevance_score < self.min_relevance_threshold:
                    self._log_discard(
                        result, unit,
                        f"Relevance score {unit.relevance_score} below threshold "
                        f"{self.min_relevance_threshold}"
                    )
                    continue
                
                # Apply density filtering
                if unit.should_include():
                    included_units.append(unit)
                    result.total_units_included += 1
                    self._logger.debug(
                        "Including unit %s: type=%s, density=%s",
                        unit.id, unit.content_type.value, unit.density.value
                    )
                else:
                    self._log_discard(
                        result, unit,
                        "LOW_DENSITY content without unique_context or risk_caveat"
                    )
            
            # Step 3: Merge included units of same type
            if included_units:
                merged_text = self._merge_same_type_units(included_units)
                result.merged_content[content_type] = merged_text
                
                self._logger.info(
                    "Merged %d %s units into %d characters",
                    len(included_units),
                    content_type.value,
                    len(merged_text)
                )
        
        result.total_units_discarded = len(result.discard_logs)
        
        self._logger.info(
            "Merge complete: %d processed, %d included, %d discarded (%.1f%% discard rate)",
            result.total_units_processed,
            result.total_units_included,
            result.total_units_discarded,
            result.get_discard_rate() * 100
        )
        
        return result
    
    def merge_cross_type(
        self, 
        units: List[ContentUnit], 
        force_type: ContentType
    ) -> MergedResult:
        """
        Attempt cross-type merge (prohibited - raises TypeMismatchError).
        
        This method exists to enforce the rule that cross-type merging
        is prohibited. It will always raise TypeMismatchError.
        
        Args:
            units: List of ContentUnit objects
            force_type: Target type to force (operation not permitted)
            
        Raises:
            TypeMismatchError: Always raised - cross-type merging prohibited
        """
        # Find first unit with different type to demonstrate error
        for unit in units:
            if unit.content_type != force_type:
                raise TypeMismatchError(
                    source_type=unit.content_type,
                    target_type=force_type,
                    message=(
                        f"Cross-type merging is prohibited. "
                        f"Cannot merge {unit.content_type.value} content into "
                        f"{force_type.value}. Use merge_units() for type-isolated merging."
                    )
                )
        
        # If all units are same type, still raise error to enforce API design
        raise TypeMismatchError(
            source_type=ContentType.METADATA,  # Default placeholder
            target_type=force_type,
            message=(
                "Cross-type merge operation not permitted. "
                "Use merge_units() for proper type-isolated merging."
            )
        )
    
    def _merge_same_type_units(self, units: List[ContentUnit]) -> str:
        """
        Merge units of the same content type.
        
        Args:
            units: List of ContentUnit objects (all same type)
            
        Returns:
            Merged text string
        """
        # Sort by relevance score (highest first)
        sorted_units = sorted(
            units, 
            key=lambda u: u.relevance_score, 
            reverse=True
        )
        
        # Merge texts with appropriate separator
        texts = []
        for unit in sorted_units:
            text = unit.text.strip()
            if text:
                # Add risk caveat if present
                if unit.risk_caveat:
                    text = f"{text} [CAVEAT: {unit.risk_caveat}]"
                texts.append(text)
        
        # Use double newline for separation
        merged = "\n\n".join(texts)
        
        return merged
    
    def _log_discard(
        self, 
        result: MergedResult, 
        unit: ContentUnit, 
        reason: str
    ) -> None:
        """
        Log a discarded content unit.
        
        Args:
            result: MergedResult to add discard log to
            unit: The discarded ContentUnit
            reason: Human-readable reason for discard
        """
        discard = DiscardLog(
            unit_id=unit.id,
            content_type=unit.content_type,
            density=unit.density,
            reason=reason,
            text_preview=unit.text,
            source=unit.source
        )
        result.discard_logs.append(discard)
        
        self._logger.debug(
            "Discarded unit %s: type=%s, density=%s, reason='%s'",
            unit.id,
            unit.content_type.value,
            unit.density.value,
            reason
        )
    
    def validate_type_consistency(self, units: List[ContentUnit]) -> bool:
        """
        Check if all units are of the same content type.
        
        Args:
            units: List of ContentUnit objects to check
            
        Returns:
            True if all units have the same content type
        """
        if not units:
            return True
        
        first_type = units[0].content_type
        return all(unit.content_type == first_type for unit in units)
    
    def get_type_distribution(self, units: List[ContentUnit]) -> Dict[ContentType, int]:
        """
        Get the distribution of content types in a list of units.
        
        Args:
            units: List of ContentUnit objects
            
        Returns:
            Dictionary mapping content types to counts
        """
        distribution: Dict[ContentType, int] = {}
        for unit in units:
            distribution[unit.content_type] = distribution.get(unit.content_type, 0) + 1
        return distribution


def create_fusion_engine(
    min_relevance_threshold: float = 0.0
) -> TypeAwareFusion:
    """
    Factory function to create a TypeAwareFusion instance.
    
    Args:
        min_relevance_threshold: Minimum relevance score for inclusion
        
    Returns:
        Configured TypeAwareFusion instance
        
    Example:
        >>> fusion = create_fusion_engine(min_relevance_threshold=0.5)
        >>> result = fusion.merge_units(units)
    """
    logger.info(
        "Creating TypeAwareFusion engine with threshold=%.2f",
        min_relevance_threshold
    )
    return TypeAwareFusion(min_relevance_threshold=min_relevance_threshold)


# Convenience exports
__all__ = [
    'ContentType',
    'ContentDensity',
    'ContentUnit',
    'MergedResult',
    'DiscardLog',
    'TypeAwareFusion',
    'TypeMismatchError',
    'create_fusion_engine',
]
