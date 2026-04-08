"""
ITEM-RES-143: DeterministicSeed Injection Enforcement for TITAN Protocol.

This module provides seed injection functionality to ensure reproducible
LLM outputs in deterministic mode. When enabled, it:

1. Injects deterministic seeds into LLM call parameters
2. Enforces temperature=0 for deterministic mode
3. Integrates with checkpoint system for reproducibility
4. Validates that all LLM calls have proper seed configuration

Integration Points:
- ModelRouter: Uses ExecutionStrictness to determine mode
- TimezoneManager: Uses generate_seed() for deterministic seed generation
- CheckpointManager: Stores seed in checkpoint for session reproducibility

Author: TITAN FUSE Team
Version: 4.1.0
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
import logging
import hashlib

from src.utils.timezone import TimezoneManager


class SeedInjectionError(Exception):
    """Raised when seed injection fails validation."""
    pass


class TemperatureViolationError(SeedInjectionError):
    """Raised when temperature is not zero in deterministic mode."""
    pass


class MissingSeedError(SeedInjectionError):
    """Raised when seed is missing in deterministic mode."""
    pass


@dataclass
class SeedInjectionConfig:
    """
    Configuration for seed injection behavior.
    
    Attributes:
        enforce: Whether to enforce seed injection in deterministic mode
        require_temperature_zero: Whether to require temperature=0
        inject_on_all_calls: Whether to inject seed on all LLM calls
    """
    enforce: bool = True
    require_temperature_zero: bool = True
    inject_on_all_calls: bool = True


@dataclass
class SeedInjectionStats:
    """
    Statistics for seed injection operations.
    
    Tracks injection counts, validations, and violations for monitoring.
    """
    total_injections: int = 0
    successful_injections: int = 0
    validation_checks: int = 0
    validation_failures: int = 0
    temperature_violations: int = 0
    missing_seed_violations: int = 0
    last_seed: Optional[int] = None
    last_session_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert stats to dictionary."""
        return {
            "total_injections": self.total_injections,
            "successful_injections": self.successful_injections,
            "validation_checks": self.validation_checks,
            "validation_failures": self.validation_failures,
            "temperature_violations": self.temperature_violations,
            "missing_seed_violations": self.missing_seed_violations,
            "last_seed": self.last_seed,
            "last_session_id": self.last_session_id
        }


@dataclass
class CheckpointSeedData:
    """
    Seed data stored in checkpoint for reproducibility.
    
    This data structure should be stored in the checkpoint to enable
    reproducible session resumption.
    """
    seed: int
    session_id: str
    mode: str
    timestamp: str
    temperature: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for checkpoint serialization."""
        return {
            "seed": self.seed,
            "session_id": self.session_id,
            "mode": self.mode,
            "timestamp": self.timestamp,
            "temperature": self.temperature,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'CheckpointSeedData':
        """Create from dictionary (checkpoint deserialization)."""
        return cls(
            seed=data["seed"],
            session_id=data["session_id"],
            mode=data["mode"],
            timestamp=data["timestamp"],
            temperature=data.get("temperature", 0.0),
            metadata=data.get("metadata", {})
        )


class SeedInjector:
    """
    Manages deterministic seed injection for LLM calls.
    
    ITEM-RES-143: Provides seed injection enforcement for reproducible
    LLM outputs in deterministic mode.
    
    Usage:
        config = {
            "deterministic_seed": {
                "enforce": True,
                "require_temperature_zero": True,
                "inject_on_all_calls": True
            }
        }
        
        injector = SeedInjector(config)
        
        # Generate seed from session ID
        seed = injector.generate_seed("session-123")
        
        # Inject seed into LLM params
        params = {"model": "gpt-4", "messages": [...]}
        injected_params = injector.inject_seed(params, mode="deterministic")
        
        # Verify params are properly configured
        is_valid = injector.verify_deterministic(injected_params)
        
        # Get checkpoint data for storage
        checkpoint_data = injector.get_checkpoint_seed_data()
    
    Integration with ModelRouter:
        The injector should be called before LLM API calls when mode is
        "deterministic". The router's ExecutionStrictness enum values
        should be checked to determine the mode.
    
    Integration with CheckpointManager:
        Store the result of get_checkpoint_seed_data() in the checkpoint
        to enable reproducible session resumption. On resume, use
        set_seed_from_checkpoint() to restore the exact seed.
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize SeedInjector with configuration.
        
        Args:
            config: Configuration dictionary containing deterministic_seed settings
        """
        self._logger = logging.getLogger(__name__)
        
        # Parse configuration
        seed_config = (config or {}).get("deterministic_seed", {})
        self.config = SeedInjectionConfig(
            enforce=seed_config.get("enforce", True),
            require_temperature_zero=seed_config.get("require_temperature_zero", True),
            inject_on_all_calls=seed_config.get("inject_on_all_calls", True)
        )
        
        # State tracking
        self._current_seed: Optional[int] = None
        self._current_session_id: Optional[str] = None
        self._stats = SeedInjectionStats()
        
        self._logger.info(
            f"SeedInjector initialized: enforce={self.config.enforce}, "
            f"require_temperature_zero={self.config.require_temperature_zero}, "
            f"inject_on_all_calls={self.config.inject_on_all_calls}"
        )
    
    def generate_seed(self, session_id: str) -> int:
        """
        Generate a deterministic seed from session ID.
        
        Uses TimezoneManager.generate_seed() for consistent seed generation
        across the TITAN Protocol.
        
        Args:
            session_id: The session identifier to generate seed from
        
        Returns:
            int: A deterministic seed value
        
        Example:
            >>> injector = SeedInjector()
            >>> seed = injector.generate_seed("session-123")
            >>> seed
            12345678901234567890  # Deterministic based on session_id
        """
        seed = TimezoneManager.generate_seed(session_id)
        
        # Track current seed
        self._current_seed = seed
        self._current_session_id = session_id
        self._stats.last_seed = seed
        self._stats.last_session_id = session_id
        
        self._logger.debug(
            f"Generated seed {seed} for session {session_id}"
        )
        
        return seed
    
    def inject_seed(self, params: Dict, mode: str, 
                    session_id: Optional[str] = None) -> Dict:
        """
        Inject seed into LLM call parameters if in deterministic mode.
        
        ITEM-RES-143 Step 02: If mode == "deterministic", inject seed and
        verify temperature=0.
        
        Args:
            params: The LLM call parameters dictionary
            mode: The execution mode ("deterministic", "guided_autonomy", "fast_prototype")
            session_id: Optional session ID for seed generation. If not provided,
                       uses the last session_id if available.
        
        Returns:
            Dict: Modified parameters with seed injected if applicable
        
        Raises:
            SeedInjectionError: If injection fails in deterministic mode
            TemperatureViolationError: If temperature != 0 in deterministic mode
        """
        self._stats.total_injections += 1
        
        # Make a copy to avoid mutating original
        result = params.copy()
        
        # Only inject in deterministic mode or if inject_on_all_calls is True
        is_deterministic = mode.lower() in ("deterministic", "deterministic_mode")
        
        if not is_deterministic and not self.config.inject_on_all_calls:
            self._logger.debug(
                f"Skipping seed injection: mode={mode}, inject_on_all_calls=False"
            )
            return result
        
        # Ensure we have a seed
        if self._current_seed is None or (session_id and session_id != self._current_session_id):
            if session_id:
                self.generate_seed(session_id)
            elif self._current_session_id:
                # Regenerate from existing session ID
                self.generate_seed(self._current_session_id)
            else:
                if is_deterministic and self.config.enforce:
                    raise SeedInjectionError(
                        "No session ID provided for deterministic mode. "
                        "Call generate_seed() first or provide session_id."
                    )
                return result
        
        # Inject seed
        result["seed"] = self._current_seed
        
        # Handle temperature for deterministic mode
        # Always set temperature to 0 in deterministic mode when required
        if is_deterministic and self.config.require_temperature_zero:
            current_temp = result.get("temperature")
            
            if current_temp is not None and current_temp != 0:
                self._stats.temperature_violations += 1
                self._logger.warning(
                    f"[ITEM-RES-143] Overriding temperature {current_temp} to 0 "
                    f"for deterministic mode"
                )
            
            # Always set temperature to 0 in deterministic mode
            result["temperature"] = 0
        
        # Add metadata for tracking
        if "metadata" not in result:
            result["metadata"] = {}
        result["metadata"]["seed_injected"] = True
        result["metadata"]["seed_mode"] = mode
        result["metadata"]["seed_value"] = self._current_seed
        
        self._stats.successful_injections += 1
        
        self._logger.debug(
            f"Injected seed {self._current_seed} into params for mode={mode}"
        )
        
        return result
    
    def verify_deterministic(self, params: Dict) -> bool:
        """
        Verify that parameters are properly configured for deterministic mode.
        
        ITEM-RES-143 Step 03: On DETERMINISTIC mode, verify all LLM calls have seed.
        
        Args:
            params: The LLM call parameters to verify
        
        Returns:
            bool: True if parameters are valid for deterministic mode
        
        Raises:
            MissingSeedError: If seed is missing
            TemperatureViolationError: If temperature is not zero
        """
        self._stats.validation_checks += 1
        
        # Check for seed
        has_seed = "seed" in params
        if not has_seed:
            self._stats.missing_seed_violations += 1
            self._stats.validation_failures += 1
            if self.config.enforce:
                raise MissingSeedError(
                    "Missing 'seed' parameter in deterministic mode. "
                    "Use inject_seed() to add seed to parameters."
                )
            return False
        
        # Check temperature
        temperature = params.get("temperature", 0)
        if self.config.require_temperature_zero and temperature != 0:
            self._stats.temperature_violations += 1
            self._stats.validation_failures += 1
            if self.config.enforce:
                raise TemperatureViolationError(
                    f"Temperature must be 0 in deterministic mode, got {temperature}. "
                    "Use inject_seed() to set temperature to 0."
                )
            return False
        
        return True
    
    def get_checkpoint_seed_data(self, mode: str = "deterministic",
                                  metadata: Optional[Dict] = None) -> Optional[CheckpointSeedData]:
        """
        Get seed data for checkpoint storage.
        
        ITEM-RES-143 Step 04: Store seed in checkpoint for reproducibility.
        
        Args:
            mode: The execution mode
            metadata: Optional additional metadata to store
        
        Returns:
            CheckpointSeedData if seed has been generated, None otherwise
        """
        if self._current_seed is None:
            self._logger.warning(
                "Cannot create checkpoint seed data: no seed generated yet"
            )
            return None
        
        return CheckpointSeedData(
            seed=self._current_seed,
            session_id=self._current_session_id or "unknown",
            mode=mode,
            timestamp=TimezoneManager.now_utc_iso(),
            temperature=0.0,
            metadata=metadata or {}
        )
    
    def set_seed_from_checkpoint(self, checkpoint_data: Dict) -> None:
        """
        Restore seed state from checkpoint data.
        
        Used when resuming a session to ensure reproducibility.
        
        Args:
            checkpoint_data: Dictionary containing CheckpointSeedData fields
        """
        data = CheckpointSeedData.from_dict(checkpoint_data)
        
        self._current_seed = data.seed
        self._current_session_id = data.session_id
        self._stats.last_seed = data.seed
        self._stats.last_session_id = data.session_id
        
        self._logger.info(
            f"Restored seed {data.seed} from checkpoint for session {data.session_id}"
        )
    
    def get_stats(self) -> Dict:
        """
        Get seed injection statistics.
        
        Returns:
            Dict containing injection statistics
        """
        return self._stats.to_dict()
    
    def reset(self) -> None:
        """
        Reset injector state for a new session.
        
        Clears the current seed and session ID, but preserves statistics.
        """
        self._current_seed = None
        self._current_session_id = None
        self._logger.debug("SeedInjector state reset")
    
    def get_current_seed(self) -> Optional[int]:
        """
        Get the current seed value.
        
        Returns:
            int if seed has been generated, None otherwise
        """
        return self._current_seed
    
    def get_current_session_id(self) -> Optional[str]:
        """
        Get the current session ID.
        
        Returns:
            str if session has been set, None otherwise
        """
        return self._current_session_id
    
    def is_deterministic_mode(self, mode: str) -> bool:
        """
        Check if a mode string represents deterministic mode.
        
        Args:
            mode: The mode string to check
        
        Returns:
            bool: True if mode is deterministic
        """
        return mode.lower() in ("deterministic", "deterministic_mode")


def create_seed_injector(config: Optional[Dict] = None) -> SeedInjector:
    """
    Factory function to create a SeedInjector.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        SeedInjector instance
    """
    return SeedInjector(config)


def inject_deterministic_seed(params: Dict, mode: str, 
                               session_id: str,
                               config: Optional[Dict] = None) -> Dict:
    """
    Convenience function for one-shot seed injection.
    
    Creates a temporary SeedInjector, generates seed from session_id,
    and injects it into params.
    
    Args:
        params: LLM call parameters
        mode: Execution mode
        session_id: Session identifier for seed generation
        config: Optional configuration
        
    Returns:
        Dict: Parameters with seed injected
    """
    injector = SeedInjector(config)
    injector.generate_seed(session_id)
    return injector.inject_seed(params, mode)
