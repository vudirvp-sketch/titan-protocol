"""
Runtime Config Overlay for TITAN FUSE Protocol.

ITEM-CFG-04: Provides in-memory configuration overrides that:
- Never persist to config.yaml
- Export to evals.jsonl on session exit
- Never auto-apply on next session

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
from pathlib import Path
import copy


@dataclass
class OverlayEntry:
    """A single overlay configuration entry."""
    key: str
    value: Any
    timestamp: str
    source: str  # "runtime", "cli_override", "test"
    reason: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "key": self.key,
            "value": self.value,
            "timestamp": self.timestamp,
            "source": self.source,
            "reason": self.reason
        }


class RuntimeConfigOverlay:
    """
    In-memory configuration overlay for runtime modifications.
    
    ITEM-CFG-04: Runtime config overlay system.
    
    Provides a way to temporarily override configuration values
    without modifying the persistent config.yaml file. This is
    useful for:
    - CLI parameter overrides
    - Test configuration changes
    - Runtime adjustments
    
    Key features:
    - Volatile: Never persisted to config.yaml
    - Exportable: Can export to evals.jsonl on session exit
    - Non-auto-apply: Previous session overlays are NOT auto-applied
    
    Usage:
        overlay = RuntimeConfigOverlay()
        
        # Set runtime override
        overlay.set("session.max_tokens", 200000)
        
        # Get effective config (overlay takes precedence)
        max_tokens = overlay.get("session.max_tokens", base_config)
        
        # Export on session exit
        overlay.export(Path("outputs/evals.jsonl"))
        
        # Reset for new session
        overlay.reset()
    """
    
    _instance: Optional['RuntimeConfigOverlay'] = None
    
    def __init__(self):
        """Initialize runtime overlay."""
        self._overlay: Dict[str, OverlayEntry] = {}
        self._logger = logging.getLogger(__name__)
        self._session_start = datetime.utcnow().isoformat() + "Z"
    
    @classmethod
    def get_instance(cls) -> 'RuntimeConfigOverlay':
        """Get singleton instance of RuntimeConfigOverlay."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance."""
        if cls._instance is not None:
            cls._instance.reset()
        cls._instance = None
    
    def set(self, key: str, value: Any, source: str = "runtime",
            reason: str = "") -> None:
        """
        Set an overlay value.
        
        Args:
            key: Configuration key (dot-notation supported)
            value: Value to set
            source: Source of the override
            reason: Reason for the override
        """
        entry = OverlayEntry(
            key=key,
            value=value,
            timestamp=datetime.utcnow().isoformat() + "Z",
            source=source,
            reason=reason
        )
        
        self._overlay[key] = entry
        self._logger.debug(f"Overlay set: {key} = {value} (source={source})")
    
    def get(self, key: str, base_value: Any = None) -> Any:
        """
        Get value with overlay precedence.
        
        Args:
            key: Configuration key
            base_value: Base value from config.yaml
            
        Returns:
            Overlay value if set, otherwise base_value
        """
        if key in self._overlay:
            return self._overlay[key].value
        return base_value
    
    def has(self, key: str) -> bool:
        """Check if overlay has a value for key."""
        return key in self._overlay
    
    def delete(self, key: str) -> bool:
        """Remove an overlay entry."""
        if key in self._overlay:
            del self._overlay[key]
            self._logger.debug(f"Overlay deleted: {key}")
            return True
        return False
    
    def reset(self) -> None:
        """Clear all overlay values."""
        self._overlay.clear()
        self._session_start = datetime.utcnow().isoformat() + "Z"
        self._logger.info("Runtime overlay reset")
    
    def get_all(self) -> Dict[str, OverlayEntry]:
        """Get all overlay entries."""
        return dict(self._overlay)
    
    def export(self) -> Dict:
        """
        Export overlay state for serialization.
        
        Returns:
            Dict with all overlay entries
        """
        return {
            "session_start": self._session_start,
            "session_end": datetime.utcnow().isoformat() + "Z",
            "overlay_count": len(self._overlay),
            "entries": [e.to_dict() for e in self._overlay.values()]
        }
    
    def export_to_file(self, path: Path, append: bool = True) -> None:
        """
        Export overlay to evals.jsonl file.
        
        ITEM-CFG-04: Export on session exit.
        
        Args:
            path: Path to evals.jsonl file
            append: If True, append to existing file
        """
        export_data = self.export()
        
        mode = 'a' if append else 'w'
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, mode) as f:
            f.write(json.dumps(export_data) + '\n')
        
        self._logger.info(f"Overlay exported to {path}")
    
    def merge_with_base(self, base_config: Dict) -> Dict:
        """
        Merge overlay with base configuration.
        
        Overlay values take precedence over base config.
        
        Args:
            base_config: Base configuration dict
            
        Returns:
            Merged configuration dict
        """
        result = copy.deepcopy(base_config)
        
        for key, entry in self._overlay.items():
            self._set_nested(result, key, entry.value)
        
        return result
    
    def _set_nested(self, config: Dict, key: str, value: Any) -> None:
        """
        Set a nested configuration value using dot notation.
        
        Args:
            config: Configuration dict to modify
            key: Dot-notation key (e.g., "session.max_tokens")
            value: Value to set
        """
        parts = key.split('.')
        current = config
        
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        
        current[parts[-1]] = value
    
    def get_overlay_keys(self) -> List[str]:
        """Get list of all overlay keys."""
        return list(self._overlay.keys())
    
    def get_entry(self, key: str) -> Optional[OverlayEntry]:
        """Get overlay entry for a key."""
        return self._overlay.get(key)
    
    def get_by_source(self, source: str) -> List[OverlayEntry]:
        """Get all entries from a specific source."""
        return [
            entry for entry in self._overlay.values()
            if entry.source == source
        ]
    
    def get_stats(self) -> Dict:
        """Get overlay statistics."""
        by_source: Dict[str, int] = {}
        for entry in self._overlay.values():
            by_source[entry.source] = by_source.get(entry.source, 0) + 1
        
        return {
            "session_start": self._session_start,
            "total_overrides": len(self._overlay),
            "by_source": by_source,
            "keys": list(self._overlay.keys())
        }


def deep_merge(base: Dict, overlay: Dict) -> Dict:
    """
    Deep merge two dictionaries with overlay taking precedence.
    
    Args:
        base: Base dictionary
        overlay: Overlay dictionary (values take precedence)
        
    Returns:
        Merged dictionary
    """
    result = copy.deepcopy(base)
    
    for key, value in overlay.items():
        if (
            key in result and 
            isinstance(result[key], dict) and 
            isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    
    return result


def get_runtime_overlay() -> RuntimeConfigOverlay:
    """
    Get the global RuntimeConfigOverlay instance.
    
    Returns:
        RuntimeConfigOverlay singleton
    """
    return RuntimeConfigOverlay.get_instance()
