"""
Tiered Validator for TITAN FUSE Protocol.

ITEM-VAL-69: Validation Tiering by Severity.

Optimizes validation performance by sampling SEV-3/4 validators
on large files while ensuring SEV-1/2 validators always run.

Sampling Rules:
- SEV-1/SEV-2: Always run (100%)
- SEV-3: Run 100% for files <50KB, sample 50% for larger
- SEV-4: Run 100% for files <10KB, sample 20% for larger

Author: TITAN FUSE Team
Version: 4.1.0
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
    ITEM-VAL-69: Tiered validation with severity-based sampling.

    Optimizes validation performance by sampling lower-priority validators
    (SEV-3/SEV-4) on large files while ensuring critical validators
    (SEV-1/SEV-2) always run.

    Configuration is loaded from config.yaml under the validation_tiering section:
        validation_tiering:
          enabled: true
          thresholds:
            sev1_sev2: 1.0
            sev3_large_file_threshold: 50000
            sev3_sampling_rate: 0.5
            sev4_sampling_rate: 0.2

    Usage:
        tiered = TieredValidator(config)
        
        # Check if a validator should run
        if tiered.should_run(validator, file_size=75000):
            validator.execute(content)
        
        # Get sampling rate for a specific case
        rate = tiered.get_sampling_rate(file_size=75000, severity="SEV-3")
        
        # Get statistics
        stats = tiered.get_stats()

    The tiering ensures:
    - Critical validators (SEV-1/SEV-2) always execute for correctness
    - Standard validators (SEV-3) are sampled on large files (>50KB)
    - Optional validators (SEV-4) are heavily sampled on large files (>10KB)
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
                    thresholds:
                        sev1_sev2: float (should be 1.0)
                        sev3_large_file_threshold: int (bytes)
                        sev3_sampling_rate: float (0.0-1.0)
                        sev4_sampling_rate: float (0.0-1.0)
            seed: Optional random seed for deterministic testing.
        """
        self._config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # Extract validation tiering configuration
        tiering_config = self._config.get("validation_tiering", {})
        self._enabled = tiering_config.get("enabled", True)
        
        # Get thresholds from config or use defaults
        thresholds = tiering_config.get("thresholds", {})
        self._sev3_large_file_threshold = thresholds.get(
            "sev3_large_file_threshold",
            self.DEFAULT_SEV3_LARGE_FILE_THRESHOLD
        )
        self._sev3_sampling_rate = thresholds.get(
            "sev3_sampling_rate",
            self.DEFAULT_SEV3_SAMPLING_RATE
        )
        self._sev4_sampling_rate = thresholds.get(
            "sev4_sampling_rate",
            self.DEFAULT_SEV4_SAMPLING_RATE
        )
        
        # SEV-4 large file threshold is not in config, use default
        # (can be overridden in thresholds if provided)
        self._sev4_large_file_threshold = thresholds.get(
            "sev4_large_file_threshold",
            self.DEFAULT_SEV4_LARGE_FILE_THRESHOLD
        )
        
        # Initialize random number generator
        self._rng = random.Random(seed)
        
        # Statistics tracking
        self._stats = TieredValidatorStats()
        
        self._logger.info(
            f"TieredValidator initialized: enabled={self._enabled}, "
            f"sev3_threshold={self._sev3_large_file_threshold}, "
            f"sev3_rate={self._sev3_sampling_rate}, "
            f"sev4_threshold={self._sev4_large_file_threshold}, "
            f"sev4_rate={self._sev4_sampling_rate}"
        )

    @property
    def enabled(self) -> bool:
        """Check if tiered validation is enabled."""
        return self._enabled

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

    def get_sampling_rate(self, file_size: int, severity: str) -> float:
        """
        Get the sampling rate for a validator based on file size and severity.

        Args:
            file_size: Size of the file in bytes
            severity: Severity level of the validator

        Returns:
            Sampling rate as a float between 0.0 and 1.0
        """
        if not self._enabled:
            return self.ALWAYS_RUN_RATE
        
        tier = self.get_tier_for_severity(severity)
        
        if tier in (SeverityTier.TIER_1, SeverityTier.TIER_2):
            # SEV-1/SEV-2 always run
            return self.ALWAYS_RUN_RATE
        
        if tier == SeverityTier.TIER_3:
            # SEV-3: 100% for small files, sampled for large files
            if file_size < self._sev3_large_file_threshold:
                return self.ALWAYS_RUN_RATE
            return self._sev3_sampling_rate
        
        if tier == SeverityTier.TIER_4:
            # SEV-4: 100% for small files, heavily sampled for large files
            if file_size < self._sev4_large_file_threshold:
                return self.ALWAYS_RUN_RATE
            return self._sev4_sampling_rate
        
        # Default to always run for unknown tiers
        return self.ALWAYS_RUN_RATE

    def should_run(self, validator: ValidatorProtocol, file_size: int) -> bool:
        """
        Determine if a validator should run based on severity and file size.

        This is the main method for making sampling decisions. It:
        1. Gets the severity tier for the validator
        2. Calculates the sampling rate
        3. Makes a probabilistic decision
        4. Records the decision in statistics

        Args:
            validator: Validator object with severity and name attributes
            file_size: Size of the file in bytes

        Returns:
            True if the validator should run, False to skip
        """
        # Extract validator properties
        severity = getattr(validator, "severity", "SEV-3")
        name = getattr(validator, "name", validator.__class__.__name__)
        
        # Get sampling rate
        sampling_rate = self.get_sampling_rate(file_size, severity)
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
                f"Validator '{name}' (severity={severity}) will run: "
                f"file_size={file_size}, rate={sampling_rate:.2f}"
            )
        else:
            self._stats.validators_skipped += 1
            self._logger.debug(
                f"Validator '{name}' (severity={severity}) skipped: "
                f"file_size={file_size}, rate={sampling_rate:.2f}"
            )
        
        return should_run

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
            "sev3_large_file_threshold": self._sev3_large_file_threshold,
            "sev3_sampling_rate": self._sev3_sampling_rate,
            "sev4_large_file_threshold": self._sev4_large_file_threshold,
            "sev4_sampling_rate": self._sev4_sampling_rate,
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
