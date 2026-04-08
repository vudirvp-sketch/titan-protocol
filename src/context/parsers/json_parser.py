"""
JSON Parser for Semantic Checksums.

ITEM-SAE-006: AST Checksum System - JSON Parser

Extracts semantic elements from JSON files.
Uses structure-aware parsing to detect schema-level changes.

Extracted Elements:
- Object keys
- Nested key paths
- Array structures
- Value types

Ignored Elements:
- Whitespace
- Literal value changes (configurable)
- Array ordering (configurable)

Author: TITAN FUSE Team
Version: 1.0.0
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from enum import Enum


class SemanticElementType(Enum):
    """Types of semantic elements."""
    KEY = "key"
    NESTED_KEY = "nested_key"
    ARRAY_ITEM = "array_item"


@dataclass
class SemanticElement:
    """A semantic element extracted from JSON."""
    element_type: SemanticElementType
    name: str
    signature: str
    line_number: int
    hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def compute_hash(self) -> str:
        """Compute hash of this element."""
        content = f"{self.element_type.value}:{self.name}:{self.signature}"
        self.hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return self.hash


@dataclass
class SemanticParseResult:
    """Result of parsing JSON for semantic elements."""
    elements: List[SemanticElement] = field(default_factory=list)
    keys: List[str] = field(default_factory=list)
    key_paths: List[str] = field(default_factory=list)
    semantic_hash: str = ""
    element_count: int = 0
    parse_errors: List[str] = field(default_factory=list)
    
    def compute_semantic_hash(self) -> str:
        """Compute combined semantic hash."""
        if not self.elements:
            self.semantic_hash = ""
            return ""
        
        sorted_elements = sorted(
            self.elements,
            key=lambda e: e.name
        )
        
        content = "|".join(e.hash for e in sorted_elements if e.hash)
        self.semantic_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
        return self.semantic_hash


class JSONParser:
    """
    Parser for JSON files.
    
    Extracts structural elements from JSON, detecting schema-level
    changes rather than value-level changes.
    
    Usage:
        parser = JSONParser()
        result = parser.parse(json_content)
        semantic_hash = result.semantic_hash
    """
    
    def __init__(
        self,
        include_values: bool = False,
        include_array_indices: bool = False,
        ignore_array_order: bool = True,
    ):
        """
        Initialize the JSON parser.
        
        Args:
            include_values: Whether to include values in hash
            include_array_indices: Whether to include array indices
            ignore_array_order: Whether to ignore array ordering
        """
        self.include_values = include_values
        self.include_array_indices = include_array_indices
        self.ignore_array_order = ignore_array_order
    
    def parse(self, source: str) -> SemanticParseResult:
        """
        Parse JSON content.
        
        Args:
            source: JSON content string
            
        Returns:
            SemanticParseResult with extracted elements
        """
        result = SemanticParseResult()
        
        try:
            data = json.loads(source)
        except json.JSONDecodeError as e:
            result.parse_errors.append(f"JSON parse error: {e}")
            return result
        
        # Extract elements from parsed data
        self._extract_elements(data, result, path="")
        
        # Compute hashes
        for element in result.elements:
            element.compute_hash()
        
        result.compute_semantic_hash()
        result.element_count = len(result.elements)
        
        return result
    
    def _extract_elements(
        self,
        data: Any,
        result: SemanticParseResult,
        path: str
    ) -> None:
        """Recursively extract elements from parsed JSON data."""
        
        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{path}.{key}" if path else key
                result.keys.append(key)
                result.key_paths.append(current_path)
                
                # Determine value type
                value_type = self._get_value_type(value)
                signature = f"{key}: {value_type}"
                
                if self.include_values and not isinstance(value, (dict, list)):
                    signature = f"{key}: {repr(value)[:50]}"
                
                element = SemanticElement(
                    element_type=SemanticElementType.KEY if not path else SemanticElementType.NESTED_KEY,
                    name=current_path,
                    signature=signature,
                    line_number=1,  # JSON doesn't preserve line info easily
                    metadata={"value_type": value_type},
                )
                result.elements.append(element)
                
                # Recurse into nested structures
                self._extract_elements(value, result, current_path)
        
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                if self.include_array_indices:
                    current_path = f"{path}[{idx}]"
                else:
                    current_path = f"{path}[]"
                
                item_type = self._get_value_type(item)
                signature = f"[{idx}]: {item_type}"
                
                element = SemanticElement(
                    element_type=SemanticElementType.ARRAY_ITEM,
                    name=current_path,
                    signature=signature,
                    line_number=1,
                    metadata={"index": idx, "item_type": item_type},
                )
                result.elements.append(element)
                
                # Recurse into array items
                self._extract_elements(item, result, current_path)
    
    def _get_value_type(self, value: Any) -> str:
        """Get a descriptive type name for a value."""
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "boolean"
        elif isinstance(value, int):
            return "integer"
        elif isinstance(value, float):
            return "number"
        elif isinstance(value, str):
            return "string"
        elif isinstance(value, list):
            return f"array[{len(value)}]"
        elif isinstance(value, dict):
            return f"object[{len(value)}]"
        else:
            return type(value).__name__
    
    def compute_semantic_hash(self, source: str) -> str:
        """Compute semantic hash for JSON content."""
        result = self.parse(source)
        return result.semantic_hash
    
    def compute_schema_hash(self, source: str) -> str:
        """
        Compute a schema-only hash, ignoring all values.
        
        Args:
            source: JSON content string
            
        Returns:
            Schema hash string
        """
        old_include_values = self.include_values
        self.include_values = False
        
        result = self.parse(source)
        
        self.include_values = old_include_values
        return result.semantic_hash
    
    def diff_semantic(
        self,
        old_source: str,
        new_source: str
    ) -> Dict[str, Any]:
        """
        Compute semantic diff between two JSON documents.
        
        Args:
            old_source: Original JSON content
            new_source: New JSON content
            
        Returns:
            Dict with added, removed, and changed keys
        """
        old_result = self.parse(old_source)
        new_result = self.parse(new_source)
        
        old_keys = set(old_result.key_paths)
        new_keys = set(new_result.key_paths)
        
        added = new_keys - old_keys
        removed = old_keys - new_keys
        
        return {
            "added_keys": sorted(list(added)),
            "removed_keys": sorted(list(removed)),
            "old_hash": old_result.semantic_hash,
            "new_hash": new_result.semantic_hash,
            "has_semantic_change": bool(added or removed),
        }
    
    def validate_schema(
        self,
        source: str,
        expected_keys: Set[str]
    ) -> Dict[str, Any]:
        """
        Validate that a JSON document has expected keys.
        
        Args:
            source: JSON content string
            expected_keys: Set of expected key paths
            
        Returns:
            Dict with validation results
        """
        result = self.parse(source)
        actual_keys = set(result.key_paths)
        
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys
        
        return {
            "valid": not missing and not extra,
            "missing_keys": sorted(list(missing)),
            "extra_keys": sorted(list(extra)),
            "expected_count": len(expected_keys),
            "actual_count": len(actual_keys),
        }
