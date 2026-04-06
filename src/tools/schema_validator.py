"""
TITAN FUSE Protocol - Schema Validator

JSON Schema validation for tool inputs and outputs.
Provides comprehensive validation with detailed error messages.

TASK-001: Tool Orchestration & Capability Registry
"""

import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum


class ValidationErrorType(Enum):
    """Types of validation errors."""
    MISSING_REQUIRED = "missing_required"
    TYPE_MISMATCH = "type_mismatch"
    VALUE_CONSTRAINT = "value_constraint"
    PATTERN_MISMATCH = "pattern_mismatch"
    SCHEMA_ERROR = "schema_error"
    CUSTOM_ERROR = "custom_error"


@dataclass
class ValidationError:
    """
    Represents a validation error.

    Attributes:
        path: JSON path to the error location
        message: Human-readable error message
        error_type: Type of validation error
        expected: Expected value/schema
        actual: Actual value found
    """
    path: str
    message: str
    error_type: ValidationErrorType
    expected: Optional[Any] = None
    actual: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "path": self.path,
            "message": self.message,
            "error_type": self.error_type.value,
            "expected": self.expected,
            "actual": self.actual
        }


@dataclass
class ValidationResult:
    """
    Result of schema validation.

    Attributes:
        valid: Whether validation passed
        errors: List of validation errors (if any)
        warnings: List of validation warnings
    """
    valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": self.warnings
        }


class SchemaValidator:
    """
    JSON Schema validator for tool inputs and outputs.

    Features:
    - Type validation (string, number, integer, boolean, array, object, null)
    - Required field checking
    - Pattern matching
    - Value constraints (min/max, enum)
    - Nested object validation
    - Array item validation
    - Custom validators

    Usage:
        validator = SchemaValidator()

        schema = {
            "type": "object",
            "required": ["name", "age"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "age": {"type": "integer", "minimum": 0}
            }
        }

        result = validator.validate({"name": "John", "age": 30}, schema)
        if result.valid:
            print("Valid!")
        else:
            for error in result.errors:
                print(f"Error at {error.path}: {error.message}")
    """

    def __init__(self):
        self._custom_validators: Dict[str, callable] = {}

    def register_validator(self, name: str, validator: callable) -> None:
        """Register a custom validator function."""
        self._custom_validators[name] = validator

    def validate(self, data: Any, schema: Dict[str, Any],
                 path: str = "$") -> ValidationResult:
        """
        Validate data against a JSON Schema.

        Args:
            data: Data to validate
            schema: JSON Schema to validate against
            path: Current path (for error messages)

        Returns:
            Validation result with any errors
        """
        errors: List[ValidationError] = []
        warnings: List[str] = []

        # Check schema type
        schema_type = schema.get("type")

        if schema_type:
            type_error = self._validate_type(data, schema_type, path)
            if type_error:
                errors.append(type_error)
                return ValidationResult(valid=False, errors=errors)

        # Validate based on type
        if schema_type == "object" or (isinstance(data, dict) and not schema_type):
            obj_errors = self._validate_object(data, schema, path)
            errors.extend(obj_errors)

        elif schema_type == "array" or (isinstance(data, list) and not schema_type):
            arr_errors = self._validate_array(data, schema, path)
            errors.extend(arr_errors)

        # Check constraints
        if schema_type in ["string", "number", "integer"]:
            constraint_errors = self._validate_constraints(data, schema, path)
            errors.extend(constraint_errors)

        # Check enum
        if "enum" in schema:
            if data not in schema["enum"]:
                errors.append(ValidationError(
                    path=path,
                    message=f"Value must be one of: {schema['enum']}",
                    error_type=ValidationErrorType.VALUE_CONSTRAINT,
                    expected=schema["enum"],
                    actual=data
                ))

        # Check pattern
        if "pattern" in schema and isinstance(data, str):
            if not re.match(schema["pattern"], data):
                errors.append(ValidationError(
                    path=path,
                    message=f"String does not match pattern: {schema['pattern']}",
                    error_type=ValidationErrorType.PATTERN_MISMATCH,
                    expected=schema["pattern"],
                    actual=data
                ))

        # Check custom validators
        if "custom" in schema:
            custom_name = schema["custom"]
            if custom_name in self._custom_validators:
                try:
                    custom_result = self._custom_validators[custom_name](data)
                    if custom_result is not True:
                        errors.append(ValidationError(
                            path=path,
                            message=str(custom_result),
                            error_type=ValidationErrorType.CUSTOM_ERROR
                        ))
                except Exception as e:
                    errors.append(ValidationError(
                        path=path,
                        message=f"Custom validator error: {e}",
                        error_type=ValidationErrorType.CUSTOM_ERROR
                    ))

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    def _validate_type(self, data: Any, expected_type: Union[str, List[str]],
                       path: str) -> Optional[ValidationError]:
        """Validate data type."""
        type_mapping = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None)
        }

        if isinstance(expected_type, list):
            # Union type
            for t in expected_type:
                python_type = type_mapping.get(t)
                if python_type and isinstance(data, python_type):
                    return None

            return ValidationError(
                path=path,
                message=f"Expected one of types: {expected_type}",
                error_type=ValidationErrorType.TYPE_MISMATCH,
                expected=expected_type,
                actual=type(data).__name__
            )

        python_type = type_mapping.get(expected_type)
        if not python_type:
            return None  # Unknown type, skip validation

        # Special case: number includes integer
        if expected_type == "number":
            if not isinstance(data, (int, float)):
                return ValidationError(
                    path=path,
                    message=f"Expected type: {expected_type}",
                    error_type=ValidationErrorType.TYPE_MISMATCH,
                    expected=expected_type,
                    actual=type(data).__name__
                )
            return None

        if not isinstance(data, python_type):
            return ValidationError(
                path=path,
                message=f"Expected type: {expected_type}",
                error_type=ValidationErrorType.TYPE_MISMATCH,
                expected=expected_type,
                actual=type(data).__name__
            )

        return None

    def _validate_object(self, data: Dict[str, Any], schema: Dict[str, Any],
                         path: str) -> List[ValidationError]:
        """Validate an object against schema."""
        errors = []

        # Check required fields
        required = schema.get("required", [])
        for field in required:
            if field not in data:
                errors.append(ValidationError(
                    path=f"{path}.{field}",
                    message=f"Missing required field: {field}",
                    error_type=ValidationErrorType.MISSING_REQUIRED,
                    expected=field
                ))

        # Validate properties
        properties = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            if prop_name in data:
                prop_path = f"{path}.{prop_name}"
                prop_result = self.validate(data[prop_name], prop_schema, prop_path)
                errors.extend(prop_result.errors)

        # Check additional properties
        additional_props = schema.get("additionalProperties", True)
        if additional_props is False:
            for key in data:
                if key not in properties:
                    errors.append(ValidationError(
                        path=f"{path}.{key}",
                        message=f"Additional property not allowed: {key}",
                        error_type=ValidationErrorType.SCHEMA_ERROR
                    ))

        return errors

    def _validate_array(self, data: List[Any], schema: Dict[str, Any],
                        path: str) -> List[ValidationError]:
        """Validate an array against schema."""
        errors = []

        # Check min/max items
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")

        if min_items is not None and len(data) < min_items:
            errors.append(ValidationError(
                path=path,
                message=f"Array must have at least {min_items} items",
                error_type=ValidationErrorType.VALUE_CONSTRAINT,
                expected=f">= {min_items}",
                actual=len(data)
            ))

        if max_items is not None and len(data) > max_items:
            errors.append(ValidationError(
                path=path,
                message=f"Array must have at most {max_items} items",
                error_type=ValidationErrorType.VALUE_CONSTRAINT,
                expected=f"<= {max_items}",
                actual=len(data)
            ))

        # Validate items
        items_schema = schema.get("items")
        if items_schema:
            for i, item in enumerate(data):
                item_path = f"{path}[{i}]"
                item_result = self.validate(item, items_schema, item_path)
                errors.extend(item_result.errors)

        return errors

    def _validate_constraints(self, data: Any, schema: Dict[str, Any],
                              path: str) -> List[ValidationError]:
        """Validate value constraints."""
        errors = []

        # String constraints
        if isinstance(data, str):
            min_length = schema.get("minLength")
            max_length = schema.get("maxLength")

            if min_length is not None and len(data) < min_length:
                errors.append(ValidationError(
                    path=path,
                    message=f"String length must be at least {min_length}",
                    error_type=ValidationErrorType.VALUE_CONSTRAINT,
                    expected=f">= {min_length}",
                    actual=len(data)
                ))

            if max_length is not None and len(data) > max_length:
                errors.append(ValidationError(
                    path=path,
                    message=f"String length must be at most {max_length}",
                    error_type=ValidationErrorType.VALUE_CONSTRAINT,
                    expected=f"<= {max_length}",
                    actual=len(data)
                ))

        # Number constraints
        if isinstance(data, (int, float)):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            exclusive_minimum = schema.get("exclusiveMinimum")
            exclusive_maximum = schema.get("exclusiveMaximum")

            if minimum is not None and data < minimum:
                errors.append(ValidationError(
                    path=path,
                    message=f"Value must be >= {minimum}",
                    error_type=ValidationErrorType.VALUE_CONSTRAINT,
                    expected=f">= {minimum}",
                    actual=data
                ))

            if maximum is not None and data > maximum:
                errors.append(ValidationError(
                    path=path,
                    message=f"Value must be <= {maximum}",
                    error_type=ValidationErrorType.VALUE_CONSTRAINT,
                    expected=f"<= {maximum}",
                    actual=data
                ))

            if exclusive_minimum is not None and data <= exclusive_minimum:
                errors.append(ValidationError(
                    path=path,
                    message=f"Value must be > {exclusive_minimum}",
                    error_type=ValidationErrorType.VALUE_CONSTRAINT,
                    expected=f"> {exclusive_minimum}",
                    actual=data
                ))

            if exclusive_maximum is not None and data >= exclusive_maximum:
                errors.append(ValidationError(
                    path=path,
                    message=f"Value must be < {exclusive_maximum}",
                    error_type=ValidationErrorType.VALUE_CONSTRAINT,
                    expected=f"< {exclusive_maximum}",
                    actual=data
                ))

        return errors


# Global validator instance
_global_validator: Optional[SchemaValidator] = None


def get_validator() -> SchemaValidator:
    """Get the global schema validator."""
    global _global_validator
    if _global_validator is None:
        _global_validator = SchemaValidator()
    return _global_validator


def validate_input(data: Any, schema: Dict[str, Any]) -> ValidationResult:
    """Validate input data against schema."""
    return get_validator().validate(data, schema)


def validate_output(data: Any, schema: Dict[str, Any]) -> ValidationResult:
    """Validate output data against schema."""
    return get_validator().validate(data, schema)
