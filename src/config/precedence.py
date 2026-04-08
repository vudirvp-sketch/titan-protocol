"""
Config Precedence Pyramid for TITAN FUSE Protocol.

ITEM-ARCH-18: Config Precedence Pyramid

Provides explicit precedence ordering for conflicting config sources.
Each config value knows its source and can report override history.

Precedence Order (highest to lowest):
1. ENV - Environment variables always win
2. CLI - Command-line flags override config files
3. USER_CONSTRAINTS - User-defined constraints from constraints.yaml
4. LOCAL_CONFIG - Project-level config.yaml
5. GLOBAL_DEFAULTS - System defaults (lowest)

Author: TITAN FUSE Team
Version: 3.7.0
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import logging
from pathlib import Path
import copy

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


# Precedence order from highest to lowest priority
PRECEDENCE_ORDER: List[str] = [
    "ENV",           # Environment variables always win
    "CLI",           # Command-line flags override config files
    "USER_CONSTRAINTS",  # User-defined constraints from constraints.yaml
    "LOCAL_CONFIG",  # Project-level config.yaml
    "GLOBAL_DEFAULTS"    # System defaults (lowest)
]

# Mapping from origin codes to display names
ORIGIN_DISPLAY_NAMES: Dict[str, str] = {
    "ENV": "Environment Variable",
    "CLI": "Command-Line Flag",
    "USER_CONSTRAINTS": "User Constraints",
    "LOCAL_CONFIG": "Local Config",
    "GLOBAL_DEFAULTS": "Global Defaults"
}


@dataclass
class ResolvedValue:
    """
    A resolved configuration value with origin tracking.
    
    Each config value knows its source and can report what it overrode.
    
    Attributes:
        value: The actual configuration value
        origin: Source origin code ("ENV", "CLI", "USER_CONSTRAINTS", "LOCAL_CONFIG", "GLOBAL_DEFAULTS")
        source_path: Optional path to the source file (for LOCAL_CONFIG, USER_CONSTRAINTS)
        overridden_by: List of origins this value was overridden by (higher priority sources)
        timestamp: When this value was resolved
    """
    value: Any
    origin: str  # "ENV", "CLI", "USER_CONSTRAINTS", "LOCAL_CONFIG", "GLOBAL_DEFAULTS"
    source_path: Optional[str] = None
    overridden_by: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    
    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "value": self.value,
            "origin": self.origin,
            "source_path": self.source_path,
            "overridden_by": self.overridden_by,
            "timestamp": self.timestamp
        }
    
    def __repr__(self) -> str:
        """String representation."""
        return f"ResolvedValue(value={self.value!r}, origin={self.origin})"


@dataclass
class ConfigPrecedenceConfig:
    """
    Configuration for the precedence resolver.
    
    Attributes:
        log_overrides: Whether to log when values are overridden
        strict_mode: If True, warn on conflicts
        env_prefix: Prefix for environment variables (default: "TITAN_")
        cli_prefix: Prefix for CLI flags (default: "--")
        constraints_file: Path to constraints file
        local_file: Path to local config file
    """
    log_overrides: bool = True
    strict_mode: bool = False
    env_prefix: str = "TITAN_"
    cli_prefix: str = "--"
    constraints_file: str = "constraints.yaml"
    local_file: str = "config.yaml"


class ConfigPrecedenceResolver:
    """
    Resolves configuration values with explicit precedence ordering.
    
    ITEM-ARCH-18: Implements the config precedence pyramid.
    
    Each configuration value is resolved based on the following precedence
    (highest to lowest):
    
    1. ENV - Environment variables (TITAN_* prefix)
    2. CLI - Command-line flags
    3. USER_CONSTRAINTS - User-defined constraints
    4. LOCAL_CONFIG - Project config.yaml
    5. GLOBAL_DEFAULTS - System defaults
    
    Features:
    - Origin tracking for each resolved value
    - Override history tracking
    - Conflict detection and logging
    - Support for TITAN_ env prefix
    
    Usage:
        resolver = ConfigPrecedenceResolver()
        
        # Resolve a single key
        resolved = resolver.resolve("session.max_tokens", sources)
        print(f"Value: {resolved.value}, Origin: {resolved.origin}")
        
        # Get override history
        history = resolver.get_override_history("session.max_tokens")
        
        # Resolve all keys
        all_resolved = resolver.resolve_all(sources_list)
    """
    
    # Default global defaults
    DEFAULTS: Dict[str, Any] = {
        "session.max_tokens": 100000,
        "session.max_time_minutes": 60,
        "session.checkpoint_enabled": True,
        "chunking.default_size": 1500,
        "validation.max_patch_iterations": 2,
        "logging.level": "info",
        "security.execution_mode": "trusted",
        "mode.current": "direct"
    }
    
    def __init__(self, config: Optional[ConfigPrecedenceConfig] = None):
        """
        Initialize the precedence resolver.
        
        Args:
            config: Optional configuration for the resolver
        """
        self.config = config or ConfigPrecedenceConfig()
        self._logger = logging.getLogger(__name__)
        self._resolved_cache: Dict[str, ResolvedValue] = {}
        self._override_history: Dict[str, List[Dict]] = {}
        
        # Log precedence order on startup
        if self.config.log_overrides:
            self._log_precedence_order()
    
    def _log_precedence_order(self) -> None:
        """Log the precedence order on initialization."""
        self._logger.info("Config Precedence Order (highest to lowest):")
        for i, origin in enumerate(PRECEDENCE_ORDER, 1):
            self._logger.info(f"  {i}. {ORIGIN_DISPLAY_NAMES.get(origin, origin)}")
    
    def resolve(self, key: str, sources: Dict[str, Dict[str, Any]]) -> ResolvedValue:
        """
        Resolve a configuration key from multiple sources.
        
        Args:
            key: Configuration key (dot-notation supported)
            sources: Dict mapping origin names to their config dicts
                     e.g., {"ENV": {...}, "CLI": {...}, ...}
        
        Returns:
            ResolvedValue with the winning value and metadata
        """
        # Track what values were found and from where
        found_values: List[tuple] = []  # (origin, value, source_path)
        
        for origin in PRECEDENCE_ORDER:
            if origin in sources and sources[origin] is not None:
                value = self._get_nested_value(sources[origin], key)
                if value is not None:
                    source_path = self._get_source_path(origin)
                    found_values.append((origin, value, source_path))
        
        # If no value found, use defaults
        if not found_values:
            default_value = self.DEFAULTS.get(key)
            return ResolvedValue(
                value=default_value,
                origin="GLOBAL_DEFAULTS",
                source_path=None,
                overridden_by=[]
            )
        
        # Winner is the first found (highest precedence)
        winning_origin, winning_value, source_path = found_values[0]
        
        # Track what was overridden
        overridden_by = [origin for origin, _, _ in found_values[1:]]
        
        # Create resolved value
        resolved = ResolvedValue(
            value=winning_value,
            origin=winning_origin,
            source_path=source_path,
            overridden_by=overridden_by
        )
        
        # Log override if configured
        if self.config.log_overrides and overridden_by:
            self._logger.debug(
                f"Config '{key}' resolved from {winning_origin}, "
                f"overriding: {', '.join(overridden_by)}"
            )
        
        # Cache the result
        self._resolved_cache[key] = resolved
        
        # Track override history
        if key not in self._override_history:
            self._override_history[key] = []
        
        self._override_history[key].append({
            "timestamp": resolved.timestamp,
            "origin": resolved.origin,
            "value": resolved.value,
            "overridden": overridden_by
        })
        
        # Warn on conflicts if strict mode
        if self.config.strict_mode and len(found_values) > 1:
            self._logger.warning(
                f"[strict_mode] Config key '{key}' has conflicting values from "
                f"{len(found_values)} sources: {[o for o, _, _ in found_values]}"
            )
        
        return resolved
    
    def get_origin(self, key: str) -> str:
        """
        Get the origin of a resolved configuration key.
        
        Args:
            key: Configuration key
        
        Returns:
            Origin code or "GLOBAL_DEFAULTS" if not found
        """
        if key in self._resolved_cache:
            return self._resolved_cache[key].origin
        return "GLOBAL_DEFAULTS"
    
    def get_precedence_order(self) -> List[str]:
        """
        Get the precedence order (highest to lowest).
        
        Returns:
            List of origin codes in precedence order
        """
        return list(PRECEDENCE_ORDER)
    
    def get_override_history(self, key: str) -> List[Dict]:
        """
        Get the override history for a configuration key.
        
        Args:
            key: Configuration key
        
        Returns:
            List of override records
        """
        return self._override_history.get(key, [])
    
    def resolve_all(
        self, 
        sources_list: List[Dict[str, Any]], 
        keys: Optional[List[str]] = None
    ) -> Dict[str, ResolvedValue]:
        """
        Resolve all configuration keys from multiple sources.
        
        Args:
            sources_list: List of config dicts from various sources
            keys: Optional list of specific keys to resolve
                  If None, resolves all keys from all sources
        
        Returns:
            Dict mapping keys to ResolvedValue objects
        """
        # Flatten sources into origin-keyed dict
        sources: Dict[str, Dict[str, Any]] = {}
        
        for source_dict in sources_list:
            if source_dict is None:
                continue
            # Infer origin from dict if present
            origin = source_dict.pop("_origin", None)
            if origin:
                sources[origin] = source_dict
        
        # Collect all keys if not specified
        if keys is None:
            keys = set()
            for origin_dict in sources.values():
                keys.update(self._flatten_keys(origin_dict))
            keys.update(self.DEFAULTS.keys())
            keys = list(keys)
        
        # Resolve each key
        result: Dict[str, ResolvedValue] = {}
        for key in keys:
            result[key] = self.resolve(key, sources)
        
        return result
    
    def _get_nested_value(self, config: Dict, key: str) -> Any:
        """
        Get a nested value from a config dict using dot notation.
        
        Args:
            config: Configuration dictionary
            key: Dot-notation key (e.g., "session.max_tokens")
        
        Returns:
            Value if found, None otherwise
        """
        if config is None:
            return None
        
        parts = key.split('.')
        current = config
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        return current
    
    def _flatten_keys(self, config: Dict, prefix: str = "") -> List[str]:
        """
        Flatten a nested dict into a list of dot-notation keys.
        
        Args:
            config: Configuration dictionary
            prefix: Current key prefix
        
        Returns:
            List of flattened keys
        """
        keys: List[str] = []
        
        if not isinstance(config, dict):
            return keys
        
        for key, value in config.items():
            full_key = f"{prefix}.{key}" if prefix else key
            
            if isinstance(value, dict):
                keys.extend(self._flatten_keys(value, full_key))
            else:
                keys.append(full_key)
        
        return keys
    
    def _get_source_path(self, origin: str) -> Optional[str]:
        """
        Get the source file path for an origin.
        
        Args:
            origin: Origin code
        
        Returns:
            Source file path or None
        """
        if origin == "LOCAL_CONFIG":
            return self.config.local_file
        elif origin == "USER_CONSTRAINTS":
            return self.config.constraints_file
        return None
    
    def _load_env_overrides(self) -> Dict[str, Any]:
        """
        Load configuration from environment variables.
        
        Environment variables with TITAN_ prefix are converted to config keys.
        Example: TITAN_SESSION_MAX_TOKENS -> session.max_tokens
        
        Returns:
            Dict of configuration values from environment
        """
        result: Dict[str, Any] = {}
        prefix = self.config.env_prefix
        
        for env_key, env_value in os.environ.items():
            if env_key.startswith(prefix):
                # Convert TITAN_SESSION_MAX_TOKENS to session.max_tokens
                config_key = env_key[len(prefix):].lower().replace('_', '.')
                
                # Try to parse as JSON, fall back to string
                try:
                    import json
                    result[config_key] = json.loads(env_value)
                except (json.JSONDecodeError, ValueError):
                    # Try to parse as boolean
                    if env_value.lower() in ('true', 'yes', '1'):
                        result[config_key] = True
                    elif env_value.lower() in ('false', 'no', '0'):
                        result[config_key] = False
                    else:
                        # Try to parse as number
                        try:
                            if '.' in env_value:
                                result[config_key] = float(env_value)
                            else:
                                result[config_key] = int(env_value)
                        except ValueError:
                            result[config_key] = env_value
        
        # Reconstruct nested structure
        return self._unflatten_dict(result)
    
    def _load_cli_overrides(self, cli_args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Load configuration from CLI arguments.
        
        Args:
            cli_args: Optional dict of CLI arguments
                     If None, returns empty dict
        
        Returns:
            Dict of configuration values from CLI
        """
        if cli_args is None:
            return {}
        
        result: Dict[str, Any] = {}
        
        for key, value in cli_args.items():
            # Remove CLI prefix if present
            if key.startswith(self.config.cli_prefix):
                key = key[len(self.config.cli_prefix):]
            
            # Convert kebab-case to dot-notation
            config_key = key.replace('-', '.')
            result[config_key] = value
        
        return self._unflatten_dict(result)
    
    def _load_user_constraints(self, constraints_path: Optional[Path] = None) -> Dict[str, Any]:
        """
        Load user constraints from constraints.yaml.
        
        Args:
            constraints_path: Optional path to constraints file
                            If None, uses config.constraints_file
        
        Returns:
            Dict of user constraint values
        """
        if not YAML_AVAILABLE:
            self._logger.warning("YAML not available, cannot load constraints")
            return {}
        
        path = constraints_path or Path(self.config.constraints_file)
        
        if not path.exists():
            self._logger.debug(f"Constraints file not found: {path}")
            return {}
        
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            self._logger.error(f"Invalid YAML in constraints file: {e}")
            return {}
    
    def _load_local_config(self, config_path: Optional[Path] = None) -> Dict[str, Any]:
        """
        Load local configuration from config.yaml.
        
        Args:
            config_path: Optional path to config file
                        If None, uses config.local_file
        
        Returns:
            Dict of local configuration values
        """
        if not YAML_AVAILABLE:
            self._logger.warning("YAML not available, cannot load config")
            return {}
        
        path = config_path or Path(self.config.local_file)
        
        if not path.exists():
            self._logger.debug(f"Config file not found: {path}")
            return {}
        
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            self._logger.error(f"Invalid YAML in config file: {e}")
            return {}
    
    def _load_defaults(self) -> Dict[str, Any]:
        """
        Load global defaults.
        
        Returns:
            Dict of default configuration values
        """
        return self._unflatten_dict(self.DEFAULTS)
    
    def _unflatten_dict(self, flat: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a flattened dict (with dot keys) to a nested dict.
        
        Args:
            flat: Flattened dictionary
        
        Returns:
            Nested dictionary
        """
        result: Dict[str, Any] = {}
        
        for key, value in flat.items():
            parts = key.split('.')
            current = result
            
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            
            current[parts[-1]] = value
        
        return result
    
    def load_all_sources(
        self,
        cli_args: Optional[Dict[str, Any]] = None,
        constraints_path: Optional[Path] = None,
        config_path: Optional[Path] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Load configuration from all sources.
        
        Args:
            cli_args: Optional CLI arguments dict
            constraints_path: Optional path to constraints file
            config_path: Optional path to local config file
        
        Returns:
            Dict mapping origin names to their config dicts
        """
        return {
            "ENV": self._load_env_overrides(),
            "CLI": self._load_cli_overrides(cli_args),
            "USER_CONSTRAINTS": self._load_user_constraints(constraints_path),
            "LOCAL_CONFIG": self._load_local_config(config_path),
            "GLOBAL_DEFAULTS": self._load_defaults()
        }
    
    def resolve_full_config(
        self,
        cli_args: Optional[Dict[str, Any]] = None,
        constraints_path: Optional[Path] = None,
        config_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Resolve the full configuration with proper precedence.
        
        This loads all sources and merges them according to precedence.
        
        Args:
            cli_args: Optional CLI arguments dict
            constraints_path: Optional path to constraints file
            config_path: Optional path to local config file
        
        Returns:
            Fully merged configuration dict
        """
        sources = self.load_all_sources(cli_args, constraints_path, config_path)
        
        # Merge from lowest to highest precedence
        result: Dict[str, Any] = {}
        
        for origin in reversed(PRECEDENCE_ORDER):
            if origin in sources and sources[origin]:
                result = self._deep_merge(result, sources[origin])
        
        return result
    
    def _deep_merge(self, base: Dict, overlay: Dict) -> Dict:
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
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        
        return result
    
    def get_config_origin_report(self) -> Dict[str, Any]:
        """
        Generate a report of config origins.
        
        Returns:
            Dict with origin information for all resolved keys
        """
        return {
            "precedence_order": self.get_precedence_order(),
            "resolved_keys": {
                key: {
                    "origin": resolved.origin,
                    "overridden_by": resolved.overridden_by,
                    "source_path": resolved.source_path
                }
                for key, resolved in self._resolved_cache.items()
            },
            "override_history": dict(self._override_history)
        }
    
    def clear_cache(self) -> None:
        """Clear the resolved cache."""
        self._resolved_cache.clear()
        self._override_history.clear()


# Singleton instance
_resolver_instance: Optional[ConfigPrecedenceResolver] = None


def get_precedence_resolver(
    config: Optional[ConfigPrecedenceConfig] = None
) -> ConfigPrecedenceResolver:
    """
    Get the global ConfigPrecedenceResolver instance.
    
    Args:
        config: Optional configuration (only used on first call)
    
    Returns:
        ConfigPrecedenceResolver singleton
    """
    global _resolver_instance
    
    if _resolver_instance is None:
        _resolver_instance = ConfigPrecedenceResolver(config)
    
    return _resolver_instance


def reset_precedence_resolver() -> None:
    """Reset the global resolver instance."""
    global _resolver_instance
    _resolver_instance = None
