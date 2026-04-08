"""
Deprecation Warning System for TITAN Protocol.

Manages deprecation warnings for legacy commands and features.

Usage:
    from src.cli.deprecation import get_deprecation_manager

    manager = get_deprecation_manager()
    if manager.check_and_warn("assemble_protocol.sh", "4.1.0"):
        # Feature still usable
        pass
"""

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class DeprecationWarning:
    """Represents a deprecation warning."""
    feature: str
    deprecated_in: str
    removed_in: str
    replacement: str
    migration_guide: str = ""


@dataclass
class Timeline:
    """Timeline for deprecation."""
    deprecated_date: str
    removal_date: str
    days_remaining: int


class DeprecationManager:
    """
    Manages deprecation warnings for TITAN Protocol.
    """

    DEFAULT_DEPRECATIONS = {
        "assemble_protocol.sh": DeprecationWarning(
            feature="assemble_protocol.sh",
            deprecated_in="4.0.0",
            removed_in="5.0.0",
            replacement="titan assemble",
            migration_guide="docs/migration/assemble_protocol.md"
        ),
        "pickle_checkpoints": DeprecationWarning(
            feature="pickle checkpoints",
            deprecated_in="3.2.0",
            removed_in="4.0.0",
            replacement="JSON+zstd checkpoints",
            migration_guide="docs/migration/checkpoints.md"
        ),
        "vm2_sandbox": DeprecationWarning(
            feature="VM2 sandbox",
            deprecated_in="4.0.0",
            removed_in="5.0.0",
            replacement="WASM/gVisor sandbox",
            migration_guide="docs/migration/sandbox.md"
        ),
    }

    def __init__(self, config_path: Path = None, metrics_collector: Any = None):
        self.config_path = config_path or Path("config/deprecations.yaml")
        self.metrics_collector = metrics_collector
        self._registry: Dict[str, DeprecationWarning] = {}
        self._usage_counts: Dict[str, int] = {}

        self._registry.update(self.DEFAULT_DEPRECATIONS)
        self._load_config()

    def _load_config(self) -> None:
        """Load deprecations from config file."""
        if not self.config_path.exists():
            return
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            for item in config.get('deprecations', []):
                warning = DeprecationWarning(
                    feature=item['feature'],
                    deprecated_in=item['deprecated_in'],
                    removed_in=item['removed_in'],
                    replacement=item['replacement'],
                    migration_guide=item.get('migration_guide', '')
                )
                self._registry[warning.feature] = warning
        except Exception as e:
            logger.warning(f"Failed to load deprecations config: {e}")

    def register_deprecated(self, feature: str, deprecated_in: str, removed_in: str,
                           replacement: str, migration_guide: str = "") -> None:
        """Register a deprecated feature."""
        warning = DeprecationWarning(
            feature=feature,
            deprecated_in=deprecated_in,
            removed_in=removed_in,
            replacement=replacement,
            migration_guide=migration_guide
        )
        self._registry[feature] = warning

    def check_deprecated(self, feature: str) -> Optional[DeprecationWarning]:
        """Check if a feature is deprecated."""
        return self._registry.get(feature)

    def check_and_warn(self, feature: str, current_version: str = None) -> bool:
        """Check feature and emit warning if deprecated."""
        warning = self.check_deprecated(feature)
        if not warning:
            return True

        self._usage_counts[feature] = self._usage_counts.get(feature, 0) + 1

        if current_version and self._is_removed(warning, current_version):
            self._emit_blocked(warning)
            return False

        self.emit_warning(warning, current_version)
        return True

    def _is_removed(self, warning: DeprecationWarning, current_version: str) -> bool:
        """Check if feature has been removed."""
        try:
            removed = [int(x) for x in warning.removed_in.split('.')]
            current = [int(x) for x in current_version.split('.')]
            for r, c in zip(removed, current):
                if c > r:
                    return True
                if c < r:
                    return False
            return len(current) >= len(removed)
        except (ValueError, TypeError):
            return False

    def emit_warning(self, warning: DeprecationWarning, current_version: str = None) -> None:
        """Emit a deprecation warning."""
        message = f"""
⚠️  DEPRECATION WARNING: {warning.feature}
    Deprecated in: v{warning.deprecated_in}
    Will be removed: v{warning.removed_in}
    Replacement: {warning.replacement}
"""
        if warning.migration_guide:
            message += f"    Migration guide: {warning.migration_guide}\n"

        print(message, file=sys.stderr)
        logger.warning(f"Deprecated feature used: {warning.feature}")

    def _emit_blocked(self, warning: DeprecationWarning) -> None:
        """Emit error for removed feature."""
        message = f"""
❌ ERROR: {warning.feature} has been REMOVED
    Removed in: v{warning.removed_in}
    Replacement: {warning.replacement}
    Migration guide: {warning.migration_guide}
"""
        print(message, file=sys.stderr)
        logger.error(f"Removed feature used: {warning.feature}")

    def get_timeline(self, feature: str, current_version: str = None) -> Optional[Timeline]:
        """Get deprecation timeline for a feature."""
        warning = self.check_deprecated(feature)
        if not warning:
            return None
        return Timeline(
            deprecated_date=f"v{warning.deprecated_in}",
            removal_date=f"v{warning.removed_in}",
            days_remaining=30
        )

    def get_all_deprecations(self) -> List[DeprecationWarning]:
        """Get all registered deprecations."""
        return list(self._registry.values())

    def get_usage_stats(self) -> Dict[str, int]:
        """Get usage statistics for deprecated features."""
        return dict(self._usage_counts)


_manager_instance: Optional[DeprecationManager] = None


def get_deprecation_manager() -> DeprecationManager:
    """Get the global deprecation manager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = DeprecationManager()
    return _manager_instance
