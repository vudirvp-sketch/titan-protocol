"""
TITAN Protocol Configuration Module.

ITEM-CFG-01: Config Schema Validation
ITEM-CFG-04: Runtime Config Overlay
ITEM-ARCH-18: Config Precedence Pyramid

This module provides configuration management for the TITAN Protocol,
including schema validation, runtime overlays, and precedence resolution.

Version: 3.7.0
"""

from src.config.schema_validator import (
    ConfigSchemaValidator,
    ValidationResult,
    validate_config,
    validate_config_file,
    get_config_with_validation
)

from src.config.runtime_overlay import (
    RuntimeConfigOverlay,
    OverlayEntry,
    deep_merge,
    get_runtime_overlay
)

from src.config.precedence import (
    PRECEDENCE_ORDER,
    ORIGIN_DISPLAY_NAMES,
    ResolvedValue,
    ConfigPrecedenceConfig,
    ConfigPrecedenceResolver,
    get_precedence_resolver,
    reset_precedence_resolver
)

from src.config.cache_invalidation import (
    ManifestCacheManager,
    CacheEntry,
    get_cache_manager
)

__all__ = [
    # Schema Validation (ITEM-CFG-01)
    "ConfigSchemaValidator",
    "ValidationResult",
    "validate_config",
    "validate_config_file",
    "get_config_with_validation",
    
    # Runtime Overlay (ITEM-CFG-04)
    "RuntimeConfigOverlay",
    "OverlayEntry",
    "deep_merge",
    "get_runtime_overlay",
    
    # Config Precedence (ITEM-ARCH-18)
    "PRECEDENCE_ORDER",
    "ORIGIN_DISPLAY_NAMES",
    "ResolvedValue",
    "ConfigPrecedenceConfig",
    "ConfigPrecedenceResolver",
    "get_precedence_resolver",
    "reset_precedence_resolver",
    
    # Cache Invalidation (ITEM-CFG-05)
    "ManifestCacheManager",
    "CacheEntry",
    "get_cache_manager"
]
