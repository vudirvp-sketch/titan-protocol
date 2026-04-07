"""
Config Schema Validator for TITAN FUSE Protocol.

ITEM-CFG-01: Config Schema Validation

Provides JSON Schema validation for config.yaml with detailed
error messages and gap tag emission on validation failures.

Features:
- JSON Schema draft-07 validation
- Detailed error messages with field paths
- Gap tag emission for invalid configs
- CLI integration for startup validation
- Backward compatibility with v3.2.x configs

Author: TITAN FUSE Team
Version: 3.3.0
"""

import json
import yaml
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

try:
    import jsonschema
    from jsonschema import Draft7Validator, ValidationError
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    Draft7Validator = None
    ValidationError = Exception


@dataclass
class ValidationResult:
    """
    Result of config validation.
    """
    valid: bool
    errors: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[Dict[str, str]] = field(default_factory=list)
    gap_tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "gap_tags": self.gap_tags
        }
    
    def add_error(self, field: str, message: str, gap_tag: str = None) -> None:
        """Add a validation error."""
        self.errors.append({
            "field": field,
            "message": message
        })
        if gap_tag:
            self.gap_tags.append(gap_tag)
        self.valid = False
    
    def add_warning(self, field: str, message: str) -> None:
        """Add a validation warning."""
        self.warnings.append({
            "field": field,
            "message": message
        })


class ConfigSchemaValidator:
    """
    JSON Schema validator for TITAN Protocol configuration.
    
    ITEM-CFG-01 Implementation:
    - Validates config.yaml against JSON Schema
    - Provides detailed error messages
    - Emits gap tags for invalid configurations
    
    Usage:
        validator = ConfigSchemaValidator()
        result = validator.validate(config_dict)
        
        if not result.valid:
            for error in result.errors:
                print(f"{error['field']}: {error['message']}")
            # Exit with error
    """
    
    GAP_TAG_SCHEMA_MISMATCH = "[gap: config_schema_mismatch]"
    GAP_TAG_MISSING_REQUIRED = "[gap: config_missing_required_field]"
    GAP_TAG_INVALID_VALUE = "[gap: config_invalid_value]"
    GAP_TAG_UNKNOWN_FIELD = "[gap: config_unknown_field]"
    
    def __init__(self, schema_path: Path = None):
        """
        Initialize validator.
        
        Args:
            schema_path: Path to JSON Schema file (default: schemas/config.schema.json)
        """
        self.logger = logging.getLogger(__name__)
        self.schema_path = schema_path or Path("schemas/config.schema.json")
        self._schema: Dict = None
        self._validator: Draft7Validator = None
        
        self._load_schema()
    
    def _load_schema(self) -> None:
        """Load JSON Schema from file."""
        if not self.schema_path.exists():
            self.logger.warning(f"Schema file not found: {self.schema_path}")
            return
        
        try:
            with open(self.schema_path, 'r') as f:
                self._schema = json.load(f)
            
            if JSONSCHEMA_AVAILABLE:
                # Validate schema itself
                Draft7Validator.check_schema(self._schema)
                self._validator = Draft7Validator(self._schema)
                self.logger.info(f"Loaded schema from {self.schema_path}")
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in schema file: {e}")
        except Exception as e:
            self.logger.error(f"Failed to load schema: {e}")
    
    def validate(self, config: Dict, strict: bool = False) -> ValidationResult:
        """
        Validate configuration against schema.
        
        Args:
            config: Configuration dictionary to validate
            strict: If True, reject unknown fields
            
        Returns:
            ValidationResult with errors, warnings, and gap tags
        """
        result = ValidationResult(valid=True)
        
        if self._schema is None:
            result.add_warning("schema", "Schema not loaded, skipping validation")
            return result
        
        if not JSONSCHEMA_AVAILABLE:
            result.add_warning("schema", "jsonschema package not available, skipping validation")
            return result
        
        # Validate against JSON Schema
        try:
            errors = list(self._validator.iter_errors(config))
            
            for error in errors:
                field_path = ".".join(str(p) for p in error.absolute_path)
                
                # Determine gap tag based on error type
                if error.validator == "required":
                    gap_tag = self.GAP_TAG_MISSING_REQUIRED
                elif error.validator in ["enum", "minimum", "maximum", "type"]:
                    gap_tag = self.GAP_TAG_INVALID_VALUE
                else:
                    gap_tag = self.GAP_TAG_SCHEMA_MISMATCH
                
                result.add_error(
                    field=field_path or "root",
                    message=error.message,
                    gap_tag=gap_tag
                )
        except Exception as e:
            result.add_error(
                field="validation",
                message=f"Validation error: {str(e)}",
                gap_tag=self.GAP_TAG_SCHEMA_MISMATCH
            )
        
        # Check for unknown fields if strict mode
        if strict:
            self._check_unknown_fields(config, self._schema, result, "")
        
        # Additional semantic validation
        self._semantic_validation(config, result)
        
        return result
    
    def _check_unknown_fields(self, config: Dict, schema: Dict, 
                               result: ValidationResult, path: str) -> None:
        """
        Check for unknown fields not in schema.
        
        Args:
            config: Config dict to check
            schema: Schema dict to check against
            result: ValidationResult to update
            path: Current path in config
        """
        if not isinstance(config, dict) or not isinstance(schema, dict):
            return
        
        schema_props = schema.get("properties", {})
        
        for key in config.keys():
            if key not in schema_props:
                field_path = f"{path}.{key}" if path else key
                result.add_warning(
                    field=field_path,
                    message=f"Unknown field not in schema"
                )
                
                if path == "" and key not in self._get_known_top_level_fields():
                    result.add_error(
                        field=field_path,
                        message=f"Unknown top-level field: {key}",
                        gap_tag=self.GAP_TAG_UNKNOWN_FIELD
                    )
    
    def _get_known_top_level_fields(self) -> set:
        """Get set of known top-level config fields."""
        return {
            "session", "chunking", "chunking_limits", "llm_query", "validation",
            "checkpoint", "output", "multi_file", "approval", "metrics", "validators",
            "mode", "model_routing", "model_fallback", "budget", "sandbox", 
            "confidence", "recursion", "telemetry", "security", "development",
            "logging", "repository", "secrets", "audit", "policy", "intent_classifier",
            "anomaly_detection", "event_journal", "locks", "gate04", "gate_sensitivity",
            "pre_intent", "storage", "model_downgrade_allowed"
        }
    
    def _semantic_validation(self, config: Dict, result: ValidationResult) -> None:
        """
        Perform semantic validation beyond JSON Schema.
        
        Args:
            config: Configuration dictionary
            result: ValidationResult to update
        """
        # Check model routing
        model_routing = config.get("model_routing", {})
        if model_routing:
            root_model = model_routing.get("root_model", "")
            leaf_model = model_routing.get("leaf_model", "")
            
            validation = model_routing.get("validation", {})
            
            if validation.get("require_root_model") and not root_model:
                result.add_error(
                    field="model_routing.root_model",
                    message="Root model is required but not configured",
                    gap_tag=self.GAP_TAG_MISSING_REQUIRED
                )
            
            if validation.get("require_leaf_model") and not leaf_model:
                result.add_error(
                    field="model_routing.leaf_model",
                    message="Leaf model is required but not configured",
                    gap_tag=self.GAP_TAG_MISSING_REQUIRED
                )
            
            if validation.get("warn_on_empty") and (not root_model or not leaf_model):
                result.add_warning(
                    field="model_routing",
                    message="Model configuration is empty"
                )
        
        # Check storage backend configuration
        storage = config.get("storage", {})
        if storage:
            backend = storage.get("backend", "local")
            
            if backend == "s3":
                s3_config = storage.get("s3", {})
                if not s3_config.get("bucket"):
                    result.add_error(
                        field="storage.s3.bucket",
                        message="S3 bucket is required when backend is s3",
                        gap_tag=self.GAP_TAG_MISSING_REQUIRED
                    )
            
            elif backend == "gcs":
                gcs_config = storage.get("gcs", {})
                if not gcs_config.get("bucket"):
                    result.add_error(
                        field="storage.gcs.bucket",
                        message="GCS bucket is required when backend is gcs",
                        gap_tag=self.GAP_TAG_MISSING_REQUIRED
                    )
        
        # Check secrets backend configuration
        secrets = config.get("secrets", {})
        if secrets:
            backend = secrets.get("backend", "env")
            
            if backend == "vault":
                # Vault doesn't require config here, uses env vars
                pass
        
        # Check security configuration
        security = config.get("security", {})
        if security.get("secrets_scan"):
            baseline = security.get("secrets_baseline")
            if baseline and not Path(baseline).exists():
                result.add_warning(
                    field="security.secrets_baseline",
                    message=f"Secrets baseline file does not exist: {baseline}"
                )
        
        # Check gate sensitivity configuration
        gate_sensitivity = config.get("gate_sensitivity", {})
        mode = config.get("mode", {}).get("current", "direct")
        
        if mode in gate_sensitivity:
            mode_config = gate_sensitivity[mode]
            
            # Validate that deterministic mode has strict settings
            if mode == "deterministic":
                if not mode_config.get("fail_on_any_gap"):
                    result.add_warning(
                        field="gate_sensitivity.deterministic.fail_on_any_gap",
                        message="Deterministic mode should have fail_on_any_gap=true"
                    )
                if mode_config.get("allow_unsafe"):
                    result.add_warning(
                        field="gate_sensitivity.deterministic.allow_unsafe",
                        message="Deterministic mode should not allow_unsafe"
                    )
    
    def validate_file(self, config_path: Path, strict: bool = False) -> ValidationResult:
        """
        Validate configuration file.
        
        Args:
            config_path: Path to config.yaml
            strict: If True, reject unknown fields
            
        Returns:
            ValidationResult with errors, warnings, and gap tags
        """
        if not config_path.exists():
            result = ValidationResult(valid=False)
            result.add_error(
                field="config_file",
                message=f"Configuration file not found: {config_path}",
                gap_tag=self.GAP_TAG_MISSING_REQUIRED
            )
            return result
        
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            result = ValidationResult(valid=False)
            result.add_error(
                field="config_file",
                message=f"Invalid YAML: {str(e)}",
                gap_tag=self.GAP_TAG_SCHEMA_MISMATCH
            )
            return result
        
        return self.validate(config, strict=strict)


def validate_config(config: Dict, strict: bool = False, 
                    schema_path: Path = None) -> ValidationResult:
    """
    Validate configuration dictionary.
    
    Convenience function for one-off validation.
    
    Args:
        config: Configuration dictionary
        strict: If True, reject unknown fields
        schema_path: Optional path to schema file
        
    Returns:
        ValidationResult
    """
    validator = ConfigSchemaValidator(schema_path)
    return validator.validate(config, strict=strict)


def validate_config_file(config_path: Path, strict: bool = False,
                         schema_path: Path = None) -> ValidationResult:
    """
    Validate configuration file.
    
    Convenience function for one-off validation.
    
    Args:
        config_path: Path to config.yaml
        strict: If True, reject unknown fields
        schema_path: Optional path to schema file
        
    Returns:
        ValidationResult
    """
    validator = ConfigSchemaValidator(schema_path)
    return validator.validate_file(config_path, strict=strict)


def get_config_with_validation(config_path: Path = None,
                               strict: bool = False) -> Tuple[Dict, ValidationResult]:
    """
    Load and validate configuration.
    
    Args:
        config_path: Path to config.yaml (default: config.yaml)
        strict: If True, reject unknown fields
        
    Returns:
        Tuple of (config_dict, ValidationResult)
    """
    config_path = config_path or Path("config.yaml")
    
    if not config_path.exists():
        result = ValidationResult(valid=False)
        result.add_error(
            field="config_file",
            message=f"Configuration file not found: {config_path}",
            gap_tag=ConfigSchemaValidator.GAP_TAG_MISSING_REQUIRED
        )
        return {}, result
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        result = ValidationResult(valid=False)
        result.add_error(
            field="config_file",
            message=f"Invalid YAML: {str(e)}",
            gap_tag=ConfigSchemaValidator.GAP_TAG_SCHEMA_MISMATCH
        )
        return {}, result
    
    result = validate_config(config, strict=strict)
    return config, result
