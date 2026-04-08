"""
JavaScript/TypeScript Parser for Semantic Checksums.

ITEM-SAE-006: AST Checksum System - JavaScript Parser

Extracts semantic elements from JavaScript/TypeScript source code.
Uses a regex-based approach for simplicity without external dependencies.

Extracted Elements:
- Function declarations
- Class declarations
- Arrow functions (assigned to variables)
- Import statements
- Export statements
- Variable declarations (const/let/var)

Ignored Elements:
- Comments
- Whitespace
- Console.log statements
- String literals (in most cases)

Author: TITAN FUSE Team
Version: 1.0.0
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from enum import Enum


class SemanticElementType(Enum):
    """Types of semantic elements."""
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    ARROW_FUNCTION = "arrow_function"
    IMPORT = "import"
    EXPORT = "export"
    VARIABLE = "variable"
    CONSTANT = "constant"
    INTERFACE = "interface"
    TYPE = "type"


@dataclass
class SemanticElement:
    """A semantic element extracted from source code."""
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
    """Result of parsing source code for semantic elements."""
    elements: List[SemanticElement] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
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
            key=lambda e: (e.element_type.value, e.name)
        )
        
        content = "|".join(e.hash for e in sorted_elements if e.hash)
        self.semantic_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
        return self.semantic_hash


class JavaScriptParser:
    """
    Parser for JavaScript/TypeScript source code.
    
    Uses regex-based parsing for simplicity. For more accurate parsing,
    consider integrating a proper JS/TS parser like esprima or babel.
    
    Usage:
        parser = JavaScriptParser()
        result = parser.parse(source_code)
        semantic_hash = result.semantic_hash
    """
    
    def __init__(
        self,
        include_private: bool = False,
        typescript: bool = False,
    ):
        """
        Initialize the JavaScript parser.
        
        Args:
            include_private: Whether to include private members (starting with _)
            typescript: Whether to parse TypeScript-specific syntax
        """
        self.include_private = include_private
        self.typescript = typescript
        
        # Regex patterns for different constructs
        self._patterns = {
            # Function declarations
            "function": re.compile(
                r'(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)',
                re.MULTILINE
            ),
            # Arrow functions assigned to variables
            "arrow_function": re.compile(
                r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>',
                re.MULTILINE
            ),
            # Class declarations
            "class": re.compile(
                r'class\s+(\w+)(?:\s+extends\s+(\w+))?',
                re.MULTILINE
            ),
            # Method definitions
            "method": re.compile(
                r'(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*\{',
                re.MULTILINE
            ),
            # Import statements
            "import": re.compile(
                r'import\s+(?:(\{[^}]+\})|(\w+))\s+from\s+[\'"]([^\'"]+)[\'"]',
                re.MULTILINE
            ),
            # Export statements
            "export": re.compile(
                r'export\s+(?:default\s+)?(?:function\s+(\w+)|class\s+(\w+)|const\s+(\w+))',
                re.MULTILINE
            ),
            # Variable declarations
            "const": re.compile(
                r'const\s+(\w+)\s*=',
                re.MULTILINE
            ),
            # TypeScript interface
            "interface": re.compile(
                r'interface\s+(\w+)(?:\s+extends\s+(\w+))?',
                re.MULTILINE
            ),
            # TypeScript type
            "type_alias": re.compile(
                r'type\s+(\w+)\s*=',
                re.MULTILINE
            ),
        }
    
    def parse(self, source: str) -> SemanticParseResult:
        """
        Parse JavaScript/TypeScript source code.
        
        Args:
            source: Source code string
            
        Returns:
            SemanticParseResult with extracted elements
        """
        result = SemanticParseResult()
        
        # Remove comments
        source = self._remove_comments(source)
        
        # Extract functions
        self._extract_functions(source, result)
        
        # Extract arrow functions
        self._extract_arrow_functions(source, result)
        
        # Extract classes
        self._extract_classes(source, result)
        
        # Extract imports
        self._extract_imports(source, result)
        
        # Extract exports
        self._extract_exports(source, result)
        
        # Extract constants
        self._extract_constants(source, result)
        
        # TypeScript-specific
        if self.typescript:
            self._extract_interfaces(source, result)
            self._extract_types(source, result)
        
        # Compute hashes
        for element in result.elements:
            element.compute_hash()
        
        result.compute_semantic_hash()
        result.element_count = len(result.elements)
        
        return result
    
    def _remove_comments(self, source: str) -> str:
        """Remove comments from source."""
        # Remove single-line comments
        source = re.sub(r'//.*$', '', source, flags=re.MULTILINE)
        # Remove multi-line comments
        source = re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)
        return source
    
    def _extract_functions(self, source: str, result: SemanticParseResult) -> None:
        """Extract function declarations."""
        for match in self._patterns["function"].finditer(source):
            name = match.group(1)
            args = match.group(2) if match.group(2) else ""
            
            if not self.include_private and name.startswith("_"):
                continue
            
            signature = f"function {name}({args})"
            line_num = source[:match.start()].count('\n') + 1
            
            element = SemanticElement(
                element_type=SemanticElementType.FUNCTION,
                name=name,
                signature=signature,
                line_number=line_num,
            )
            result.elements.append(element)
            result.exports.append(name)
    
    def _extract_arrow_functions(self, source: str, result: SemanticParseResult) -> None:
        """Extract arrow functions."""
        for match in self._patterns["arrow_function"].finditer(source):
            name = match.group(1)
            
            if not self.include_private and name.startswith("_"):
                continue
            
            signature = f"const {name} = (...) => {{ ... }}"
            line_num = source[:match.start()].count('\n') + 1
            
            element = SemanticElement(
                element_type=SemanticElementType.ARROW_FUNCTION,
                name=name,
                signature=signature,
                line_number=line_num,
            )
            result.elements.append(element)
    
    def _extract_classes(self, source: str, result: SemanticParseResult) -> None:
        """Extract class declarations."""
        for match in self._patterns["class"].finditer(source):
            name = match.group(1)
            extends = match.group(2) if match.lastindex >= 2 else None
            
            if not self.include_private and name.startswith("_"):
                continue
            
            signature = f"class {name}"
            if extends:
                signature += f" extends {extends}"
            
            line_num = source[:match.start()].count('\n') + 1
            
            element = SemanticElement(
                element_type=SemanticElementType.CLASS,
                name=name,
                signature=signature,
                line_number=line_num,
                metadata={"extends": extends} if extends else {},
            )
            result.elements.append(element)
            result.exports.append(name)
    
    def _extract_imports(self, source: str, result: SemanticParseResult) -> None:
        """Extract import statements."""
        for match in self._patterns["import"].finditer(source):
            named_imports = match.group(1)  # { a, b, c }
            default_import = match.group(2)  # import X from
            module = match.group(3)
            
            line_num = source[:match.start()].count('\n') + 1
            
            if named_imports:
                # Parse named imports
                names = re.findall(r'\w+', named_imports)
                for imp_name in names:
                    signature = f"import {{ {imp_name} }} from '{module}'"
                    element = SemanticElement(
                        element_type=SemanticElementType.IMPORT,
                        name=imp_name,
                        signature=signature,
                        line_number=line_num,
                        metadata={"module": module},
                    )
                    result.elements.append(element)
                    result.imports.append(f"{module}:{imp_name}")
            
            if default_import:
                signature = f"import {default_import} from '{module}'"
                element = SemanticElement(
                    element_type=SemanticElementType.IMPORT,
                    name=default_import,
                    signature=signature,
                    line_number=line_num,
                    metadata={"module": module, "default": True},
                )
                result.elements.append(element)
                result.imports.append(f"{module}:{default_import}")
    
    def _extract_exports(self, source: str, result: SemanticParseResult) -> None:
        """Extract export statements."""
        for match in self._patterns["export"].finditer(source):
            func_name = match.group(1)
            class_name = match.group(2)
            const_name = match.group(3)
            
            line_num = source[:match.start()].count('\n') + 1
            
            name = func_name or class_name or const_name
            if name:
                if not self.include_private and name.startswith("_"):
                    continue
                
                elem_type = (
                    SemanticElementType.FUNCTION if func_name
                    else SemanticElementType.CLASS if class_name
                    else SemanticElementType.CONSTANT
                )
                
                signature = f"export {elem_type.value} {name}"
                element = SemanticElement(
                    element_type=SemanticElementType.EXPORT,
                    name=name,
                    signature=signature,
                    line_number=line_num,
                    metadata={"exported_type": elem_type.value},
                )
                result.elements.append(element)
                result.exports.append(name)
    
    def _extract_constants(self, source: str, result: SemanticParseResult) -> None:
        """Extract const declarations."""
        for match in self._patterns["const"].finditer(source):
            name = match.group(1)
            
            # Skip if already captured as arrow function
            if any(e.name == name for e in result.elements):
                continue
            
            if not self.include_private and name.startswith("_"):
                continue
            
            line_num = source[:match.start()].count('\n') + 1
            
            element_type = (
                SemanticElementType.CONSTANT
                if name.isupper() or name[0].isupper()
                else SemanticElementType.VARIABLE
            )
            
            signature = f"const {name} = ..."
            element = SemanticElement(
                element_type=element_type,
                name=name,
                signature=signature,
                line_number=line_num,
            )
            result.elements.append(element)
    
    def _extract_interfaces(self, source: str, result: SemanticParseResult) -> None:
        """Extract TypeScript interface declarations."""
        for match in self._patterns["interface"].finditer(source):
            name = match.group(1)
            extends = match.group(2) if match.lastindex >= 2 else None
            
            if not self.include_private and name.startswith("_"):
                continue
            
            signature = f"interface {name}"
            if extends:
                signature += f" extends {extends}"
            
            line_num = source[:match.start()].count('\n') + 1
            
            element = SemanticElement(
                element_type=SemanticElementType.INTERFACE,
                name=name,
                signature=signature,
                line_number=line_num,
            )
            result.elements.append(element)
    
    def _extract_types(self, source: str, result: SemanticParseResult) -> None:
        """Extract TypeScript type aliases."""
        for match in self._patterns["type_alias"].finditer(source):
            name = match.group(1)
            
            if not self.include_private and name.startswith("_"):
                continue
            
            line_num = source[:match.start()].count('\n') + 1
            
            signature = f"type {name} = ..."
            element = SemanticElement(
                element_type=SemanticElementType.TYPE,
                name=name,
                signature=signature,
                line_number=line_num,
            )
            result.elements.append(element)
    
    def compute_ast_hash(self, source: str) -> str:
        """Compute AST-based hash for JavaScript source."""
        result = self.parse(source)
        return result.semantic_hash
