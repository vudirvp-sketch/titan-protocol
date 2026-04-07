"""
Tests for ITEM-CFG-01: Config Schema Validation.

Tests JSON Schema validation for TITAN Protocol configuration.

Author: TITAN FUSE Team
Version: 3.3.0
"""

import pytest
import tempfile
from pathlib import Path
import json

from src.config.schema_validator import (
    ConfigSchemaValidator,
    ValidationResult,
    validate_config,
    validate_config_file,
    get_config_with_validation
)


class TestValidationResult:
    """Tests for ValidationResult dataclass."""
    
    def test_valid_result(self):
        """Test valid result creation."""
        result = ValidationResult(valid=True)
        
        assert result.valid is True
        assert len(result.errors) == 0
        assert len(result.warnings) == 0
    
    def test_add_error(self):
        """Test adding error to result."""
        result = ValidationResult(valid=True)
        
        result.add_error("field", "error message", "[gap: test]")
        
        assert result.valid is False
        assert len(result.errors) == 1
        assert "[gap: test]" in result.gap_tags
    
    def test_add_warning(self):
        """Test adding warning to result."""
        result = ValidationResult(valid=True)
        
        result.add_warning("field", "warning message")
        
        assert result.valid is True  # Warnings don't affect validity
        assert len(result.warnings) == 1
    
    def test_to_dict(self):
        """Test result serialization."""
        result = ValidationResult(valid=False)
        result.add_error("field1", "error1")
        result.add_warning("field2", "warning1")
        
        data = result.to_dict()
        
        assert data["valid"] is False
        assert len(data["errors"]) == 1
        assert len(data["warnings"]) == 1


class TestConfigSchemaValidator:
    """Tests for ConfigSchemaValidator class."""
    
    def test_initialization(self):
        """Test validator initialization."""
        validator = ConfigSchemaValidator()
        
        assert validator.schema_path.name == "config.schema.json"
    
    def test_validate_valid_config(self):
        """Test validation of valid config."""
        validator = ConfigSchemaValidator()
        
        config = {
            "session": {
                "max_tokens": 100000
            },
            "storage": {
                "backend": "local"
            }
        }
        
        result = validator.validate(config)
        
        # Should pass or have only warnings
        assert result.valid or len([e for e in result.errors if "required" not in e["message"].lower()]) == 0
    
    def test_validate_invalid_type(self):
        """Test detection of invalid type."""
        validator = ConfigSchemaValidator()
        
        config = {
            "session": {
                "max_tokens": "not_an_integer"  # Should be integer
            }
        }
        
        result = validator.validate(config)
        
        assert result.valid is False
    
    def test_validate_invalid_enum(self):
        """Test detection of invalid enum value."""
        validator = ConfigSchemaValidator()
        
        config = {
            "storage": {
                "backend": "invalid_backend"  # Should be local/s3/gcs
            }
        }
        
        result = validator.validate(config)
        
        assert result.valid is False
    
    def test_semantic_validation_missing_s3_bucket(self):
        """Test semantic validation for missing S3 bucket."""
        validator = ConfigSchemaValidator()
        
        config = {
            "storage": {
                "backend": "s3",
                "s3": {
                    "bucket": None  # Required when backend is s3
                }
            }
        }
        
        result = validator.validate(config)
        
        # Should have error about missing bucket
        bucket_errors = [e for e in result.errors if "bucket" in e["field"]]
        assert len(bucket_errors) > 0
    
    def test_semantic_validation_missing_gcs_bucket(self):
        """Test semantic validation for missing GCS bucket."""
        validator = ConfigSchemaValidator()
        
        config = {
            "storage": {
                "backend": "gcs",
                "gcs": {
                    "bucket": None
                }
            }
        }
        
        result = validator.validate(config)
        
        bucket_errors = [e for e in result.errors if "bucket" in e["field"]]
        assert len(bucket_errors) > 0
    
    def test_warning_for_empty_model(self):
        """Test warning for empty model configuration."""
        validator = ConfigSchemaValidator()
        
        config = {
            "model_routing": {
                "root_model": "",
                "leaf_model": "",
                "validation": {
                    "warn_on_empty": True
                }
            }
        }
        
        result = validator.validate(config)
        
        model_warnings = [w for w in result.warnings if "model" in w["field"]]
        assert len(model_warnings) > 0
    
    def test_error_for_required_model(self):
        """Test error when model is required but missing."""
        validator = ConfigSchemaValidator()
        
        config = {
            "model_routing": {
                "root_model": "",
                "validation": {
                    "require_root_model": True
                }
            }
        }
        
        result = validator.validate(config)
        
        model_errors = [e for e in result.errors if "root_model" in e["field"]]
        assert len(model_errors) > 0
    
    def test_validate_file(self):
        """Test validation from file."""
        validator = ConfigSchemaValidator()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            
            # Write valid config
            config_content = """
session:
  max_tokens: 100000
storage:
  backend: local
"""
            with open(config_path, 'w') as f:
                f.write(config_content)
            
            result = validator.validate_file(config_path)
            
            assert result.valid or len(result.errors) == 0
    
    def test_validate_missing_file(self):
        """Test validation of missing file."""
        validator = ConfigSchemaValidator()
        
        result = validator.validate_file(Path("/nonexistent/config.yaml"))
        
        assert result.valid is False
        assert any("not found" in e["message"] for e in result.errors)
    
    def test_validate_invalid_yaml(self):
        """Test validation of invalid YAML."""
        validator = ConfigSchemaValidator()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            
            with open(config_path, 'w') as f:
                f.write("invalid: yaml: content: [")
            
            result = validator.validate_file(config_path)
            
            assert result.valid is False
            assert any("Invalid YAML" in e["message"] for e in result.errors)


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_validate_config(self):
        """Test validate_config function."""
        config = {
            "session": {
                "max_tokens": 100000
            }
        }
        
        result = validate_config(config)
        
        assert isinstance(result, ValidationResult)
    
    def test_validate_config_file(self):
        """Test validate_config_file function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            
            with open(config_path, 'w') as f:
                f.write("session:\n  max_tokens: 100000\n")
            
            result = validate_config_file(config_path)
            
            assert isinstance(result, ValidationResult)
    
    def test_get_config_with_validation(self):
        """Test get_config_with_validation function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            
            with open(config_path, 'w') as f:
                f.write("session:\n  max_tokens: 50000\nstorage:\n  backend: local\n")
            
            config, result = get_config_with_validation(config_path)
            
            assert isinstance(config, dict)
            assert isinstance(result, ValidationResult)
            assert config.get("session", {}).get("max_tokens") == 50000


class TestSchemaCoverage:
    """Tests for schema field coverage."""
    
    def test_schema_has_all_v3_3_fields(self):
        """Test that schema includes all v3.3.0 fields."""
        schema_path = Path("schemas/config.schema.json")
        
        with open(schema_path, 'r') as f:
            schema = json.load(f)
        
        required_fields = [
            "session", "chunking", "checkpoint", "output",
            "security", "storage", "secrets", "audit",
            "event_journal", "locks", "gate04", "gate_sensitivity",
            "pre_intent", "model_routing", "model_fallback",
            "model_downgrade_allowed"
        ]
        
        for field in required_fields:
            assert field in schema["properties"], f"Missing field: {field}"
    
    def test_storage_schema_complete(self):
        """Test that storage schema is complete."""
        schema_path = Path("schemas/config.schema.json")
        
        with open(schema_path, 'r') as f:
            schema = json.load(f)
        
        storage_props = schema["properties"]["storage"]["properties"]
        
        assert "backend" in storage_props
        assert "local" in storage_props
        assert "s3" in storage_props
        assert "gcs" in storage_props
        
        # Check S3 has bucket field
        assert "bucket" in storage_props["s3"]["properties"]
    
    def test_secrets_schema_complete(self):
        """Test that secrets schema is complete."""
        schema_path = Path("schemas/config.schema.json")
        
        with open(schema_path, 'r') as f:
            schema = json.load(f)
        
        secrets_props = schema["properties"]["secrets"]["properties"]
        
        assert "backend" in secrets_props
        assert secrets_props["backend"]["type"] == "string"
        assert "enum" in secrets_props["backend"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
