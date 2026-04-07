"""
Checksum Prefix Handler for TITAN FUSE Protocol.

ITEM-CONFLICT-K: Handles checksum prefix collision detection
and configurable prefix lengths for different environments.

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from datetime import datetime
import logging
import hashlib
import math


@dataclass
class PrefixConfig:
    """Checksum prefix configuration."""
    prefix_length: int
    production_min_length: int
    
    def to_dict(self) -> Dict:
        return {
            "prefix_length": self.prefix_length,
            "production_min_length": self.production_min_length
        }


class ChecksumPrefixHandler:
    """
    Handle checksum prefixes with collision detection.
    
    ITEM-CONFLICT-K: Checksum prefix collision handling.
    
    Provides:
    - Configurable prefix length for different environments
    - Collision detection and reporting
    - Safe prefix length calculation based on chunk count
    
    Collision probability estimation:
    - With 16-char hex prefix (64 bits): ~1% at 6.1M chunks
    - With 32-char hex prefix (128 bits): negligible for practical use
    
    Usage:
        config = {
            "prefix_length": 16,
            "production_min_length": 32
        }
        
        handler = ChecksumPrefixHandler(config)
        
        # Compute prefix
        prefix = handler.compute_prefix(full_hash)
        
        # Check for collisions
        collisions = handler.detect_collision(prefixes)
        
        # Get safe length for chunk count
        safe_length = handler.get_safe_prefix_length(1000)
    """
    
    DEFAULT_CONFIG = PrefixConfig(
        prefix_length=16,
        production_min_length=32
    )
    
    def __init__(self, config: Dict = None, production_mode: bool = False):
        """
        Initialize prefix handler.
        
        Args:
            config: Prefix configuration dictionary
            production_mode: If True, enforce production minimum
        """
        if config is None:
            config = {}
        
        self._config = PrefixConfig(
            prefix_length=config.get("prefix_length", self.DEFAULT_CONFIG.prefix_length),
            production_min_length=config.get(
                "production_min_length", 
                self.DEFAULT_CONFIG.production_min_length
            )
        )
        
        self._production_mode = production_mode
        self._logger = logging.getLogger(__name__)
        self._seen_prefixes: Set[str] = set()
        self._collision_log: List[Dict] = []
    
    def compute_prefix(self, full_hash: str, override_length: int = None) -> str:
        """
        Compute checksum prefix.
        
        Args:
            full_hash: Full checksum hash
            override_length: Override configured prefix length
            
        Returns:
            Prefix of appropriate length
        """
        length = override_length or self._get_effective_length()
        
        # Ensure we don't exceed hash length
        length = min(length, len(full_hash))
        
        prefix = full_hash[:length]
        
        # Track for collision detection
        if prefix in self._seen_prefixes:
            self._record_collision(prefix, full_hash)
        else:
            self._seen_prefixes.add(prefix)
        
        return prefix
    
    def _get_effective_length(self) -> int:
        """Get effective prefix length based on mode."""
        if self._production_mode:
            return max(self._config.prefix_length, self._config.production_min_length)
        return self._config.prefix_length
    
    def _record_collision(self, prefix: str, new_hash: str) -> None:
        """Record a collision event."""
        collision_record = {
            "prefix": prefix,
            "new_hash": new_hash,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        self._collision_log.append(collision_record)
        
        self._logger.warning(
            f"[gap: checksum_prefix_collision_detected] "
            f"Collision for prefix {prefix}"
        )
    
    def detect_collision(self, prefixes: List[str]) -> List[str]:
        """
        Detect colliding prefixes in a list.
        
        Args:
            prefixes: List of prefixes to check
            
        Returns:
            List of prefixes that have collisions
        """
        seen: Dict[str, int] = {}
        collisions: List[str] = []
        
        for prefix in prefixes:
            if prefix in seen:
                seen[prefix] += 1
                if prefix not in collisions:
                    collisions.append(prefix)
            else:
                seen[prefix] = 1
        
        if collisions:
            self._logger.warning(
                f"[gap: checksum_prefix_collision_detected] "
                f"Found {len(collisions)} colliding prefixes"
            )
        
        return collisions
    
    def get_safe_prefix_length(self, chunk_count: int) -> int:
        """
        Calculate safe prefix length for a given chunk count.
        
        Uses birthday problem approximation to ensure
        collision probability stays below 0.1%.
        
        Args:
            chunk_count: Expected number of chunks
            
        Returns:
            Recommended minimum prefix length
        """
        if chunk_count <= 0:
            return self._config.prefix_length
        
        # Birthday problem: P(collision) ≈ 1 - e^(-n²/2k)
        # For hex prefix, k = 16^length
        # We want P < 0.001 (0.1%)
        
        # Approximation: length ≈ log2(n²) + log2(1/P)
        # For P = 0.001: log2(1000) ≈ 10
        # So length ≈ log2(n²) + 10 bits
        
        n = chunk_count
        bits_needed = 2 * math.log2(max(n, 1)) + 10
        
        # Each hex char = 4 bits
        hex_chars = math.ceil(bits_needed / 4)
        
        # Apply minimum from config
        safe_length = max(hex_chars, self._config.prefix_length)
        
        # Apply production minimum if needed
        if self._production_mode:
            safe_length = max(safe_length, self._config.production_min_length)
        
        self._logger.debug(
            f"Safe prefix length for {chunk_count} chunks: {safe_length} chars"
        )
        
        return safe_length
    
    def estimate_collision_probability(
        self, prefix_length: int, chunk_count: int
    ) -> float:
        """
        Estimate collision probability.
        
        Args:
            prefix_length: Length of prefix in hex chars
            chunk_count: Number of chunks
            
        Returns:
            Estimated collision probability (0.0 - 1.0)
        """
        if chunk_count <= 1:
            return 0.0
        
        # Number of possible values
        n_values = 16 ** prefix_length
        
        # Birthday problem approximation
        n = chunk_count
        probability = 1 - math.exp(-(n * n) / (2 * n_values))
        
        return min(probability, 1.0)
    
    def get_collision_stats(self) -> Dict:
        """Get collision statistics."""
        return {
            "total_prefixes_seen": len(self._seen_prefixes),
            "total_collisions": len(self._collision_log),
            "collision_rate": (
                len(self._collision_log) / max(len(self._seen_prefixes), 1)
            ),
            "config": self._config.to_dict(),
            "production_mode": self._production_mode,
            "effective_length": self._get_effective_length()
        }
    
    def get_collision_log(self, limit: int = 100) -> List[Dict]:
        """Get recent collision log entries."""
        return self._collision_log[-limit:]
    
    def clear_tracking(self) -> None:
        """Clear prefix tracking (for new session)."""
        self._seen_prefixes.clear()
        self._collision_log.clear()
        self._logger.info("Prefix tracking cleared")
    
    def set_production_mode(self, enabled: bool) -> None:
        """Enable or disable production mode."""
        self._production_mode = enabled
        self._logger.info(f"Production mode: {enabled}")
    
    def validate_config(self) -> Tuple[bool, List[str]]:
        """
        Validate current configuration.
        
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        
        if self._config.prefix_length < 8:
            issues.append(
                f"prefix_length ({self._config.prefix_length}) is too short. "
                f"Minimum 8 recommended."
            )
        
        if self._config.production_min_length < 24:
            issues.append(
                f"production_min_length ({self._config.production_min_length}) "
                f"should be at least 24 for production use."
            )
        
        if self._config.prefix_length > self._config.production_min_length:
            issues.append(
                f"prefix_length ({self._config.prefix_length}) is greater than "
                f"production_min_length ({self._config.production_min_length}). "
                f"This is unusual."
            )
        
        return len(issues) == 0, issues
    
    def get_config(self) -> PrefixConfig:
        """Get current configuration."""
        return self._config
    
    def update_config(self, config: Dict) -> None:
        """Update configuration."""
        if "prefix_length" in config:
            self._config.prefix_length = config["prefix_length"]
        if "production_min_length" in config:
            self._config.production_min_length = config["production_min_length"]
        
        self._logger.info(f"Config updated: {config}")


def compute_checksum(data: str) -> str:
    """
    Compute SHA-256 checksum for data.
    
    Args:
        data: String data to hash
        
    Returns:
        Hex checksum string
    """
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def create_prefix_handler(config: Dict = None, 
                         production_mode: bool = False) -> ChecksumPrefixHandler:
    """
    Factory function to create a ChecksumPrefixHandler.
    
    Args:
        config: Configuration dictionary
        production_mode: Production mode flag
        
    Returns:
        ChecksumPrefixHandler instance
    """
    return ChecksumPrefixHandler(config, production_mode)
