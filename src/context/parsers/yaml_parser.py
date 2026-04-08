"""
YAML Parser for Semantic Checksums.

ITEM-SAE-006: AST Checksum System - YAML Parser

Extracts semantic elements from YAML configuration files.
Uses structure-aware parsing to detect meaningful changes.

Extracted Elements:
- Top-level keys
- Nested key paths
- List structures
- Value types (not values themselves, by default)

Ignored Elements:
- Comments
- Whitespace
- Ordering differences (for maps)
- Literal value changes (configurable)

Author: TITAN FUSE Team
Version: 1.0.0
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from enum import Enum
import yaml


class SemanticElementType(Enum):
    """Types of semantic elements."""
    KEY = "key"
    NESTED_KEY = "nested_key"
    LIST_ITEM = "list_item"
    ANCHOR = "anchor"
    ALIAS = "alias"


@dataclass
class SemanticElement:
    """A semantic element extracted from YAML."""
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
    """Result of parsing YAML for semantic elements."""
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


class YAMLParser:
    """
    Parser for YAML configuration files.
    
    Extracts structural elements from YAML, detecting schema-level
    changes rather than value-level changes.
    
    Usage:
        parser = YAMLParser()
        result = parser.parse(yaml_content)
        semantic_hash = result.semantic_hash
    """
    
    def __init__(
        self,
        include_values: bool = False,
        include_list_indices: bool = False,
    ):
        """
        Initialize the YAML parser.
        
        Args:
            include_values: Whether to include values in hash
            include_list_indices: Whether to include list indices
        """
        self.include_values = include_values
        self.include_list_indices = include_list_indices
    
    def parse(self, source: str) -> SemanticParseResult:
        """
        Parse YAML content.
        
        Args:
            source: YAML content string
            
        Returns:
            SemanticParseResult with extracted elements
        """
        result = SemanticParseResult()
        
        try:
            data = yaml.safe_load(source)
        except yaml.YAMLError as e:
            result.parse_errors.append(f"YAML parse error: {e}")
            return result
        
        # Extract elements from parsed data
        self._extract_elements(data, result, path="", line_number=1)
        
        # Also extract from raw source for line numbers
        self._extract_from_source(source, result)
        
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
        path: str,
        line_number: int
    ) -> None:
        """Recursively extract elements from parsed YAML data."""
        
        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{path}.{key}" if path else key
                result.keys.append(key)
                result.key_paths.append(current_path)
                
                # Determine value type
                value_type = type(value).__name__
                signature = f"{key}: {value_type}"
                
                if self.include_values and not isinstance(value, (dict, list)):
                    signature = f"{key}: {repr(value)[:50]}"
                
                element = SemanticElement(
                    element_type=SemanticElementType.KEY if not path else SemanticElementType.NESTED_KEY,
                    name=current_path,
                    signature=signature,
                    line_number=line_number,
                    metadata={"value_type": value_type},
                )
                result.elements.append(element)
                
                # Recurse into nested structures
                self._extract_elements(value, result, current_path, line_number)
        
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                if self.include_list_indices:
                    current_path = f"{path}[{idx}]"
                else:
                    current_path = f"{path}[]"
                
                item_type = type(item).__name__
                signature = f"[{idx}]: {item_type}"
                
                element = SemanticElement(
                    element_type=SemanticElementType.LIST_ITEM,
                    name=current_path,
                    signature=signature,
                    line_number=line_number,
                    metadata={"index": idx, "item_type": item_type},
                )
                result.elements.append(element)
                
                # Recurse into list items
                self._extract_elements(item, result, current_path, line_number)
    
    def _extract_from_source(
        self,
        source: str,
        result: SemanticParseResult
    ) -> None:
        """Extract additional info from raw source."""
        # Extract anchors and aliases
        anchor_pattern = re.compile(r'(\w+):\s*&(\w+)')
        alias_pattern = re.compile(r'\*(\w+)')
        
        for i, line in enumerate(source.split('\n'), 1):
            # Check for anchors
            for match in anchor_pattern.finditer(line):
                key = match.group(1)
                anchor = match.group(2)
                
                element = SemanticElement(
                    element_type=SemanticElementType.ANCHOR,
                    name=f"anchor:{anchor}",
                    signature=f"&{anchor} on {key}",
                    line_number=i,
                )
                result.elements.append(element)
            
            # Check for aliases
            for match in alias_pattern.finditer(line):
                alias = match.group(1)
                
                element = SemanticElement(
                    element_type=SemanticElementType.ALIAS,
                    name=f"alias:{alias}",
                    signature=f"*{alias}",
                    line_number=i,
                )
                result.elements.append(element)
    
    def compute_semantic_hash(self, source: str) -> str:
        """Compute semantic hash for YAML content."""
        result = self.parse(source)
        return result.semantic_hash
    
    def diff_semantic(
        self,
        old_source: str,
        new_source: str
    ) -> Dict[str, Any]:
        """
        Compute semantic diff between two YAML documents.
        
        Args:
            old_source: Original YAML content
            new_source: New YAML content
            
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
