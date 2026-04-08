"""
Tiered Validator for TITAN FUSE Protocol.

ITEM-VAL-001: TieredValidatorSampling Enhancement.
ITEM-VAL-69: Validation Tiering by Severity.

Optimizes validation performance by sampling SEV-3/4 validators
on large files while ensuring SEV-1/2 validators always run.

Sampling Rules:
- SEV-1/SEV-2: Always run (100%)
- SEV-3: Run 100% for files <50KB, sample 50% for larger
- SEV-4: Run 100% for files <10KB, sample 20% for larger

Enhanced with content-type heuristics for critical file types
(config, schema, manifest) which receive increased sampling rates.

Author: TITAN FUSE Team
Version: 5.0.0
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from src.utils.timezone import now_utc, now_utc_iso


class SeverityTier(Enum):
    """
    Severity tier classification for validators.

    Attributes:
        TIER_1: Critical validators (SEV-1) - always run
        TIER_2: Important validators (SEV-2) - always run
        TIER_3: Standard validators (SEV-3) - sampled on large files
        TIER_4: Optional validators (SEV-4) - heavily sampled on large files
    """
    TIER_1 = 1  # SEV-1: Critical, always run
    TIER_2 = 2  # SEV-2: Important, always run
    TIER_3 = 3  # SEV-3: Standard, sampled on large files
    TIER_4 = 4  # SEV-4: Optional, heavily sampled on large files


@runtime_checkable
class ValidatorProtocol(Protocol):
    """Protocol defining the interface for validators."""
    
    @property
    def severity(self) -> str:
        """Return the severity level (SEV-1, SEV-2, SEV-3, SEV-4)."""
        ...
    
    @property
    def name(self) -> str:
        """Return the validator name."""
        ...


@dataclass
class SamplingDecision:
    """
    Record of a sampling decision made by the TieredValidator.

    Attributes:
        validator_name: Name of the validator
        severity: Severity level of the validator
        file_size: Size of the file being validated
        sampling_rate: Applied sampling rate
        should_run: Whether the validator should run
        tier: Severity tier classification
        timestamp: When the decision was made
    """
    validator_name: str
    severity: str
    file_size: int
    sampling_rate: float
    should_run: bool
    tier: SeverityTier
    timestamp: str = field(default_factory=now_utc_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "validator_name": self.validator_name,
            "severity": self.severity,
            "file_size": self.file_size,
            "sampling_rate": self.sampling_rate,
            "should_run": self.should_run,
            "tier": self.tier.value,
            "timestamp": self.timestamp,
        }


@dataclass
class SamplingConfig:
    """
    ITEM-VAL-001: Sampling configuration by severity.
    
    Configuration dataclass for controlling sampling behavior
    across different severity tiers and file characteristics.

    Attributes:
        sev1_rate: Sampling rate for SEV-1 validators (always 1.0)
        sev2_rate: Sampling rate for SEV-2 validators (always 1.0)
        sev3_small_file_rate: Rate for SEV-3 on files < sev3_size_threshold
        sev3_large_file_rate: Rate for SEV-3 on files >= sev3_size_threshold
        sev3_size_threshold: File size threshold for SEV-3 sampling (bytes)
        sev4_small_file_rate: Rate for SEV-4 on files < sev4_size_threshold
        sev4_large_file_rate: Rate for SEV-4 on files >= sev4_size_threshold
        sev4_size_threshold: File size threshold for SEV-4 sampling (bytes)
        critical_content_multiplier: Multiplier for critical content types
        critical_content_types: List of content types considered critical
    """
    # SEV-1 and SEV-2 always run (100%)
    sev1_rate: float = 1.0
    sev2_rate: float = 1.0
    
    # SEV-3: file size based
    sev3_small_file_rate: float = 1.0  # < 50KB
    sev3_large_file_rate: float = 0.5  # >= 50KB
    sev3_size_threshold: int = 50000  # bytes
    
    # SEV-4: file size based
    sev4_small_file_rate: float = 1.0  # < 10KB
    sev4_large_file_rate: float = 0.2  # >= 10KB
    sev4_size_threshold: int = 10000  # bytes
    
    # Content type heuristics
    critical_content_multiplier: float = 1.5  # config, schema files
    critical_content_types: List[str] = field(
        default_factory=lambda: ["config", "schema", "manifest"]
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "sev1_rate": self.sev1_rate,
            "sev2_rate": self.sev2_rate,
            "sev3_small_file_rate": self.sev3_small_file_rate,
            "sev3_large_file_rate": self.sev3_large_file_rate,
            "sev3_size_threshold": self.sev3_size_threshold,
            "sev4_small_file_rate": self.sev4_small_file_rate,
            "sev4_large_file_rate": self.sev4_large_file_rate,
            "sev4_size_threshold": self.sev4_size_threshold,
            "critical_content_multiplier": self.critical_content_multiplier,
            "critical_content_types": self.critical_content_types,
        }


@dataclass
class TieredValidatorStats:
    """
    Statistics for the TieredValidator.

    Attributes:
        validators_run: Number of validators that were run
        validators_skipped: Number of validators that were skipped
        sampling_decisions: List of all sampling decisions made
        total_decisions: Total number of decisions made
        skip_rate: Percentage of validators skipped
    """
    validators_run: int = 0
    validators_skipped: int = 0
    sampling_decisions: List[SamplingDecision] = field(default_factory=list)
    
    @property
    def total_decisions(self) -> int:
        """Total number of decisions made."""
        return self.validators_run + self.validators_skipped
    
    @property
    def skip_rate(self) -> float:
        """Percentage of validators skipped."""
        if self.total_decisions == 0:
            return 0.0
        return self.validators_skipped / self.total_decisions
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "validators_run": self.validators_run,
            "validators_skipped": self.validators_skipped,
            "total_decisions": self.total_decisions,
            "skip_rate": self.skip_rate,
            "sampling_decisions_count": len(self.sampling_decisions),
        }
    
    def reset(self) -> None:
        """Reset statistics."""
        self.validators_run = 0
        self.validators_skipped = 0
        self.sampling_decisions.clear()


class TieredValidator:
    """
    ITEM-VAL-001: Enhanced tiered validation with severity-based sampling.
    ITEM-VAL-69: Tiered validation with severity-based sampling.

    Optimizes validation performance by sampling lower-priority validators
    (SEV-3/SEV-4) on large files while ensuring critical validators
    (SEV-1/SEV-2) always run.

    Enhanced with content-type heuristics for critical file types
    (config, schema, manifest) which receive increased sampling rates.

    Configuration is loaded from config.yaml under the validation_tiering section:
        validation_tiering:
          enabled: true
          sampling:
            sev3_large_file_threshold: 50000
            sev3_large_file_rate: 0.5
            sev4_small_file_threshold: 10000
            sev4_small_file_rate: 1.0
            sev4_large_file_rate: 0.2
            critical_content_types:
              - config
              - schema
              - manifest
            critical_content_multiplier: 1.5

    Usage:
        tiered = TieredValidator(config)
        
        # Check if a validator should run
        if tiered.should_run(validator, file_size=75000, content_type="config"):
            validator.execute(content)
        
        # Get sampling rate for a specific case
        rate = tiered.get_sampling_rate(file_size=75000, severity="SEV-3", content_type="config")
        
        # Sample content for validation
        sampled = tiered.sample_content(content, rate=0.5)
        
        # Get statistics
        stats = tiered.get_stats()

    The tiering ensures:
    - Critical validators (SEV-1/SEV-2) always execute for correctness
    - Standard validators (SEV-3) are sampled on large files (>50KB)
    - Optional validators (SEV-4) are heavily sampled on large files (>10KB)
    - Critical content types get increased sampling rates
    """

    # Default thresholds (in bytes)
    DEFAULT_SEV3_LARGE_FILE_THRESHOLD = 50_000  # 50KB
    DEFAULT_SEV4_LARGE_FILE_THRESHOLD = 10_000  # 10KB
    
    # Default sampling rates
    DEFAULT_SEV3_SAMPLING_RATE = 0.5  # 50%
    DEFAULT_SEV4_SAMPLING_RATE = 0.2  # 20%
    
    # SEV-1/SEV-2 always run
    ALWAYS_RUN_RATE = 1.0

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        seed: Optional[int] = None,
    ) -> None:
        """
        Initialize the TieredValidator.

        Args:
            config: Configuration dictionary. Expected structure:
                validation_tiering:
                    enabled: bool
                    sampling:
                        sev3_large_file_threshold: int (bytes)
                        sev3_large_file_rate: float (0.0-1.0)
                        sev4_small_file_threshold: int (bytes)
                        sev4_small_file_rate: float (0.0-1.0)
                        sev4_large_file_rate: float (0.0-1.0)
                        critical_content_types: list
                        critical_content_multiplier: float
            seed: Optional random seed for deterministic testing.
        """
        self._config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # Extract validation tiering configuration
        tiering_config = self._config.get("validation_tiering", {})
        self._enabled = tiering_config.get("enabled", True)
        
        # Initialize sampling configuration
        self._sampling_config = self._build_sampling_config(tiering_config)
        
        # Initialize random number generator
        self._rng = random.Random(seed)
        
        # Statistics tracking
        self._stats = TieredValidatorStats()
        
        self._logger.info(
            f"[ITEM-VAL-001] TieredValidator initialized: enabled={self._enabled}, "
            f"sev3_threshold={self._sampling_config.sev3_size_threshold}, "
            f"sev3_rate={self._sampling_config.sev3_large_file_rate}, "
            f"sev4_threshold={self._sampling_config.sev4_size_threshold}, "
            f"sev4_rate={self._sampling_config.sev4_large_file_rate}, "
            f"critical_types={self._sampling_config.critical_content_types}"
        )

    def _build_sampling_config(self, tiering_config: Dict[str, Any]) -> SamplingConfig:
        """
        Build SamplingConfig from configuration dictionary.
        
        Supports both old 'thresholds' format and new 'sampling' format.
        
        Args:
            tiering_config: The validation_tiering section from config
            
        Returns:
            Configured SamplingConfig instance
        """
        # Check for new 'sampling' section first
        sampling = tiering_config.get("sampling", {})
        
        # Fall back to old 'thresholds' format for backward compatibility
        thresholds = tiering_config.get("thresholds", {})
        
        # Build config with precedence: sampling > thresholds > defaults
        return SamplingConfig(
            sev1_rate=1.0,
            sev2_rate=1.0,
            sev3_small_file_rate=sampling.get("sev3_small_file_rate", 1.0),
            sev3_large_file_rate=sampling.get(
                "sev3_large_file_rate",
                thresholds.get("sev3_sampling_rate", self.DEFAULT_SEV3_SAMPLING_RATE)
            ),
            sev3_size_threshold=sampling.get(
                "sev3_large_file_threshold",
                thresholds.get(
                    "sev3_large_file_threshold",
                    self.DEFAULT_SEV3_LARGE_FILE_THRESHOLD
                )
            ),
            sev4_small_file_rate=sampling.get("sev4_small_file_rate", 1.0),
            sev4_large_file_rate=sampling.get(
                "sev4_large_file_rate",
                thresholds.get("sev4_sampling_rate", self.DEFAULT_SEV4_SAMPLING_RATE)
            ),
            sev4_size_threshold=sampling.get(
                "sev4_small_file_threshold",
                thresholds.get(
                    "sev4_large_file_threshold",
                    self.DEFAULT_SEV4_LARGE_FILE_THRESHOLD
                )
            ),
            critical_content_multiplier=sampling.get("critical_content_multiplier", 1.5),
            critical_content_types=sampling.get(
                "critical_content_types",
                ["config", "schema", "manifest"]
            ),
        )

    @property
    def enabled(self) -> bool:
        """Check if tiered validation is enabled."""
        return self._enabled
    
    @property
    def sampling_config(self) -> SamplingConfig:
        """Get the current sampling configuration."""
        return self._sampling_config

    def get_tier_for_severity(self, severity: str) -> SeverityTier:
        """
        Map severity string to SeverityTier.

        Args:
            severity: Severity string (e.g., "SEV-1", "SEV-2", etc.)

        Returns:
            SeverityTier enum value

        Raises:
            ValueError: If severity is not recognized
        """
        severity_upper = severity.upper().strip()
        
        tier_map = {
            "SEV-1": SeverityTier.TIER_1,
            "SEV1": SeverityTier.TIER_1,
            "SEV-2": SeverityTier.TIER_2,
            "SEV2": SeverityTier.TIER_2,
            "SEV-3": SeverityTier.TIER_3,
            "SEV3": SeverityTier.TIER_3,
            "SEV-4": SeverityTier.TIER_4,
            "SEV4": SeverityTier.TIER_4,
        }
        
        if severity_upper not in tier_map:
            raise ValueError(
                f"Unknown severity: {severity}. "
                f"Expected one of: {list(tier_map.keys())}"
            )
        
        return tier_map[severity_upper]

    def get_sampling_rate(
        self,
        file_size: int,
        severity: str,
        content_type: Optional[str] = None,
    ) -> float:
        """
        Get the sampling rate for a validator based on file size, severity,
        and optional content type.

        ITEM-VAL-001: Enhanced with content type heuristics.

        Args:
            file_size: Size of the file in bytes
            severity: Severity level of the validator
            content_type: Optional content type (e.g., "config", "schema", "manifest")

        Returns:
            Sampling rate as a float between 0.0 and 1.0
        """
        if not self._enabled:
            return self.ALWAYS_RUN_RATE
        
        tier = self.get_tier_for_severity(severity)
        config = self._sampling_config
        
        if tier in (SeverityTier.TIER_1, SeverityTier.TIER_2):
            # SEV-1/SEV-2 always run
            return self.ALWAYS_RUN_RATE
        
        rate: float
        
        if tier == SeverityTier.TIER_3:
            # SEV-3: file size based sampling
            if file_size < config.sev3_size_threshold:
                rate = config.sev3_small_file_rate
            else:
                rate = config.sev3_large_file_rate
        elif tier == SeverityTier.TIER_4:
            # SEV-4: file size based sampling
            if file_size < config.sev4_size_threshold:
                rate = config.sev4_small_file_rate
            else:
                rate = config.sev4_large_file_rate
        else:
            # Default to always run for unknown tiers
            rate = self.ALWAYS_RUN_RATE
        
        # ITEM-VAL-001: Apply content type heuristic for critical content
        if content_type and content_type in config.critical_content_types:
            original_rate = rate
            rate *= config.critical_content_multiplier
            rate = min(rate, 1.0)  # Cap at 100%
            self._logger.debug(
                f"[ITEM-VAL-001] Critical content type '{content_type}': "
                f"rate increased from {original_rate:.2f} to {rate:.2f}"
            )
        
        return rate

    def should_run(
        self,
        validator: ValidatorProtocol,
        file_size: int,
        content_type: Optional[str] = None,
    ) -> bool:
        """
        Determine if a validator should run based on severity, file size,
        and optional content type.

        ITEM-VAL-001: Enhanced with content type support.

        This is the main method for making sampling decisions. It:
        1. Gets the severity tier for the validator
        2. Calculates the sampling rate (with content type heuristic)
        3. Makes a probabilistic decision
        4. Records the decision in statistics

        Args:
            validator: Validator object with severity and name attributes
            file_size: Size of the file in bytes
            content_type: Optional content type (e.g., "config", "schema", "manifest")

        Returns:
            True if the validator should run, False to skip
        """
        # Extract validator properties
        severity = getattr(validator, "severity", "SEV-3")
        name = getattr(validator, "name", validator.__class__.__name__)
        
        # Get sampling rate (with content type heuristic)
        sampling_rate = self.get_sampling_rate(file_size, severity, content_type)
        tier = self.get_tier_for_severity(severity)
        
        # Make decision
        if sampling_rate >= self.ALWAYS_RUN_RATE:
            should_run = True
        elif sampling_rate <= 0.0:
            should_run = False
        else:
            # Probabilistic sampling
            should_run = self._rng.random() < sampling_rate
        
        # Record decision
        decision = SamplingDecision(
            validator_name=name,
            severity=severity,
            file_size=file_size,
            sampling_rate=sampling_rate,
            should_run=should_run,
            tier=tier,
        )
        self._stats.sampling_decisions.append(decision)
        
        # Update counters
        if should_run:
            self._stats.validators_run += 1
            self._logger.debug(
                f"[ITEM-VAL-001] Validator '{name}' (severity={severity}) will run: "
                f"file_size={file_size}, rate={sampling_rate:.2f}, "
                f"content_type={content_type}"
            )
        else:
            self._stats.validators_skipped += 1
            self._logger.debug(
                f"[ITEM-VAL-001] Validator '{name}' (severity={severity}) skipped: "
                f"file_size={file_size}, rate={sampling_rate:.2f}, "
                f"content_type={content_type}"
            )
        
        return should_run

    def sample_content(self, content: str, rate: float) -> str:
        """
        Sample content for validation when rate < 1.0.
        
        ITEM-VAL-001: Stratified sampling for large file validation.

        Uses stratified sampling to get representative portions from
        the beginning, middle, and end of the content.

        Args:
            content: The full content string to sample
            rate: Sampling rate (0.0 to 1.0)

        Returns:
            Sampled content string
        """
        if rate >= 1.0:
            return content
        
        if rate <= 0.0:
            return ""
        
        lines = content.split('\n')
        total_lines = len(lines)
        
        if total_lines == 0:
            return content
        
        sample_size = max(1, int(total_lines * rate))
        
        # Stratified sampling - get samples from beginning, middle, end
        sample: List[str] = []
        
        # Calculate segment sizes
        segment_size = sample_size // 3
        remainder = sample_size % 3
        
        # Beginning segment
        beginning_size = segment_size + (1 if remainder > 0 else 0)
        sample.extend(lines[:beginning_size])
        
        # Middle segment
        mid_start = (total_lines // 2) - (segment_size // 2)
        mid_end = mid_start + segment_size + (1 if remainder > 1 else 0)
        sample.extend(lines[mid_start:mid_end])
        
        # End segment
        end_size = segment_size
        sample.extend(lines[-end_size:] if end_size > 0 else [])
        
        # Reconstruct content with markers for clarity
        result_parts: List[str] = []
        if beginning_size > 0:
            result_parts.append('\n'.join(lines[:beginning_size]))
        if mid_start < mid_end and mid_start < total_lines:
            mid_segment = '\n'.join(lines[mid_start:mid_end])
            if mid_segment:
                result_parts.append(f"\n# ... [MIDDLE SECTION SAMPLED] ...\n{mid_segment}")
        if end_size > 0:
            end_segment = '\n'.join(lines[-end_size:])
            if end_segment:
                result_parts.append(f"\n# ... [END SECTION] ...\n{end_segment}")
        
        return '\n'.join(result_parts)

    def get_stats(self) -> TieredValidatorStats:
        """
        Get current statistics.

        Returns:
            TieredValidatorStats with current counters and decisions
        """
        return self._stats

    def reset_stats(self) -> None:
        """Reset all statistics counters."""
        self._stats.reset()
        self._logger.debug("TieredValidator statistics reset")

    def get_config(self) -> Dict[str, Any]:
        """
        Get the current configuration.

        Returns:
            Dictionary with current configuration values
        """
        return {
            "enabled": self._enabled,
            "sampling_config": self._sampling_config.to_dict(),
        }

    def get_recent_decisions(self, limit: int = 100) -> List[SamplingDecision]:
        """
        Get recent sampling decisions.

        Args:
            limit: Maximum number of decisions to return

        Returns:
            List of recent SamplingDecision objects
        """
        return self._stats.sampling_decisions[-limit:]

    def clear_decisions(self) -> None:
        """Clear the sampling decisions history."""
        self._stats.sampling_decisions.clear()


def create_tiered_validator(
    config: Optional[Dict[str, Any]] = None,
    seed: Optional[int] = None,
) -> TieredValidator:
    """
    Factory function to create a TieredValidator.

    Args:
        config: Configuration dictionary
        seed: Optional random seed for deterministic testing

    Returns:
        Configured TieredValidator instance
    """
    return TieredValidator(config=config, seed=seed)
