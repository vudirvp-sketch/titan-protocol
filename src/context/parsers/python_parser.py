"""
Python Parser for Semantic Checksums.

ITEM-SAE-006: AST Checksum System - Python Parser

Extracts semantic elements from Python source code using the built-in AST module.

Extracted Elements:
- Function definitions (name, args, returns, decorators)
- Class definitions (name, bases, methods)
- Import statements (module, names, aliases)
- Variable assignments at module level
- Type hints

Ignored Elements:
- Comments
- Whitespace
- Docstrings (configurable)
- Expression statements
- Pass statements

Author: TITAN FUSE Team
Version: 1.0.0
"""

import ast
import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set, Tuple
from enum import Enum


class SemanticElementType(Enum):
    """Types of semantic elements."""
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    IMPORT = "import"
    VARIABLE = "variable"
    CONSTANT = "constant"
    TYPE_ALIAS = "type_alias"


@dataclass
class SemanticElement:
    """
    A semantic element extracted from source code.
    
    Attributes:
        element_type: Type of the element
        name: Name of the element
        signature: Signature string (for functions/methods)
        line_number: Line number in source
        hash: Hash of the element's semantic content
        metadata: Additional metadata
    """
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
    """
    Result of parsing source code for semantic elements.
    
    Attributes:
        elements: List of extracted semantic elements
        imports: List of import statements
        exports: List of exported symbols
        semantic_hash: Combined hash of all semantic elements
        element_count: Number of elements extracted
        parse_errors: Any errors encountered during parsing
    """
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
        
        # Sort elements by type and name for consistent hashing
        sorted_elements = sorted(
            self.elements,
            key=lambda e: (e.element_type.value, e.name)
        )
        
        content = "|".join(e.hash for e in sorted_elements if e.hash)
        self.semantic_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
        return self.semantic_hash


class PythonParser:
    """
    Parser for Python source code.
    
    Extracts semantic elements from Python code using the AST module,
    ignoring non-semantic content like comments and whitespace.
    
    Usage:
        parser = PythonParser()
        
        # Parse source code
        result = parser.parse(source_code)
        
        # Get semantic hash
        semantic_hash = result.semantic_hash
        
        # Check if code changed semantically
        old_hash = "abc123..."
        if result.semantic_hash != old_hash:
            print("Semantic change detected!")
    """
    
    def __init__(
        self,
        include_docstrings: bool = False,
        include_private: bool = False,
        include_type_hints: bool = True,
    ):
        """
        Initialize the Python parser.
        
        Args:
            include_docstrings: Whether to include docstrings in hash
            include_private: Whether to include private members (starting with _)
            include_type_hints: Whether to include type hints in signatures
        """
        self.include_docstrings = include_docstrings
        self.include_private = include_private
        self.include_type_hints = include_type_hints
    
    def parse(self, source: str) -> SemanticParseResult:
        """
        Parse Python source code and extract semantic elements.
        
        Args:
            source: Python source code string
            
        Returns:
            SemanticParseResult with extracted elements and hash
        """
        result = SemanticParseResult()
        
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            result.parse_errors.append(f"Syntax error: {e}")
            return result
        
        # Extract elements from AST
        for node in ast.walk(tree):
            self._process_node(node, result)
        
        # Compute hashes for all elements
        for element in result.elements:
            element.compute_hash()
        
        # Compute combined semantic hash
        result.compute_semantic_hash()
        result.element_count = len(result.elements)
        
        return result
    
    def _process_node(
        self,
        node: ast.AST,
        result: SemanticParseResult
    ) -> None:
        """Process an AST node and extract semantic elements."""
        
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            self._process_function(node, result)
        
        elif isinstance(node, ast.ClassDef):
            self._process_class(node, result)
        
        elif isinstance(node, ast.Import):
            self._process_import(node, result)
        
        elif isinstance(node, ast.ImportFrom):
            self._process_import_from(node, result)
        
        elif isinstance(node, ast.Assign):
            self._process_assignment(node, result)
        
        elif isinstance(node, ast.AnnAssign):
            self._process_annotated_assignment(node, result)
    
    def _process_function(
        self,
        node: ast.FunctionDef,
        result: SemanticParseResult
    ) -> None:
        """Process a function definition."""
        # Skip private functions if configured
        if not self.include_private and node.name.startswith("_"):
            return
        
        # Build signature
        args = self._format_args(node.args)
        returns = ""
        
        if self.include_type_hints and node.returns:
            returns = f" -> {ast.unparse(node.returns)}"
        
        decorators = ""
        if node.decorator_list:
            decorators = "@" + " @".join(
                ast.unparse(d) for d in node.decorator_list
            ) + " "
        
        signature = f"{decorators}def {node.name}({args}){returns}"
        
        element = SemanticElement(
            element_type=SemanticElementType.FUNCTION,
            name=node.name,
            signature=signature,
            line_number=node.lineno,
            metadata={
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "decorators": [ast.unparse(d) for d in node.decorator_list],
            }
        )
        result.elements.append(element)
        
        # Add to exports if public
        if not node.name.startswith("_"):
            result.exports.append(node.name)
    
    def _process_class(
        self,
        node: ast.ClassDef,
        result: SemanticParseResult
    ) -> None:
        """Process a class definition."""
        # Skip private classes if configured
        if not self.include_private and node.name.startswith("_"):
            return
        
        # Build signature
        bases = ""
        if node.bases:
            bases = "(" + ", ".join(ast.unparse(b) for b in node.bases) + ")"
        
        signature = f"class {node.name}{bases}"
        
        element = SemanticElement(
            element_type=SemanticElementType.CLASS,
            name=node.name,
            signature=signature,
            line_number=node.lineno,
            metadata={
                "bases": [ast.unparse(b) for b in node.bases],
                "decorators": [ast.unparse(d) for d in node.decorator_list],
            }
        )
        result.elements.append(element)
        
        # Process methods
        for item in node.body:
            if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                self._process_method(item, node.name, result)
        
        # Add to exports if public
        if not node.name.startswith("_"):
            result.exports.append(node.name)
    
    def _process_method(
        self,
        node: ast.FunctionDef,
        class_name: str,
        result: SemanticParseResult
    ) -> None:
        """Process a method definition."""
        # Skip private methods if configured
        if not self.include_private and node.name.startswith("_"):
            return
        
        # Build signature
        args = self._format_args(node.args)
        returns = ""
        
        if self.include_type_hints and node.returns:
            returns = f" -> {ast.unparse(node.returns)}"
        
        signature = f"def {class_name}.{node.name}({args}){returns}"
        
        element = SemanticElement(
            element_type=SemanticElementType.METHOD,
            name=f"{class_name}.{node.name}",
            signature=signature,
            line_number=node.lineno,
            metadata={
                "class": class_name,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            }
        )
        result.elements.append(element)
    
    def _process_import(
        self,
        node: ast.Import,
        result: SemanticParseResult
    ) -> None:
        """Process an import statement."""
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            signature = f"import {alias.name}"
            if alias.asname:
                signature += f" as {alias.asname}"
            
            element = SemanticElement(
                element_type=SemanticElementType.IMPORT,
                name=name,
                signature=signature,
                line_number=node.lineno,
            )
            result.elements.append(element)
            result.imports.append(alias.name)
    
    def _process_import_from(
        self,
        node: ast.ImportFrom,
        result: SemanticParseResult
    ) -> None:
        """Process a from-import statement."""
        module = node.module or ""
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            signature = f"from {module} import {alias.name}"
            if alias.asname:
                signature += f" as {alias.asname}"
            
            element = SemanticElement(
                element_type=SemanticElementType.IMPORT,
                name=name,
                signature=signature,
                line_number=node.lineno,
                metadata={"module": module},
            )
            result.elements.append(element)
            result.imports.append(f"{module}.{alias.name}" if module else alias.name)
    
    def _process_assignment(
        self,
        node: ast.Assign,
        result: SemanticParseResult
    ) -> None:
        """Process a variable assignment."""
        # Only process module-level simple assignments
        for target in node.targets:
            if isinstance(target, ast.Name):
                name = target.id
                
                # Skip private variables
                if not self.include_private and name.startswith("_"):
                    continue
                
                # Determine if constant (UPPER_CASE)
                element_type = (
                    SemanticElementType.CONSTANT
                    if name.isupper()
                    else SemanticElementType.VARIABLE
                )
                
                signature = f"{name} = ..."
                
                element = SemanticElement(
                    element_type=element_type,
                    name=name,
                    signature=signature,
                    line_number=node.lineno,
                )
                result.elements.append(element)
    
    def _process_annotated_assignment(
        self,
        node: ast.AnnAssign,
        result: SemanticParseResult
    ) -> None:
        """Process an annotated assignment."""
        if isinstance(node.target, ast.Name):
            name = node.target.id
            
            if not self.include_private and name.startswith("_"):
                return
            
            annotation = ast.unparse(node.annotation) if node.annotation else ""
            signature = f"{name}: {annotation}"
            
            element = SemanticElement(
                element_type=SemanticElementType.VARIABLE,
                name=name,
                signature=signature,
                line_number=node.lineno,
                metadata={"annotation": annotation},
            )
            result.elements.append(element)
    
    def _format_args(self, args: ast.arguments) -> str:
        """Format function arguments as a string."""
        parts = []
        
        # Regular args
        for arg in args.args:
            arg_str = arg.arg
            if self.include_type_hints and arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            parts.append(arg_str)
        
        # Varargs (*args)
        if args.vararg:
            arg_str = f"*{args.vararg.arg}"
            if self.include_type_hints and args.vararg.annotation:
                arg_str += f": {ast.unparse(args.vararg.annotation)}"
            parts.append(arg_str)
        
        # Keyword-only args
        for arg in args.kwonlyargs:
            arg_str = arg.arg
            if self.include_type_hints and arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            parts.append(arg_str)
        
        # Kwargs (**kwargs)
        if args.kwarg:
            arg_str = f"**{args.kwarg.arg}"
            if self.include_type_hints and args.kwarg.annotation:
                arg_str += f": {ast.unparse(args.kwarg.annotation)}"
            parts.append(arg_str)
        
        return ", ".join(parts)
    
    def compute_ast_hash(self, source: str) -> str:
        """
        Compute AST-based hash for Python source.
        
        Args:
            source: Python source code
            
        Returns:
            Hash string, or empty string on parse error
        """
        result = self.parse(source)
        return result.semantic_hash
    
    def compute_signature_hash(
        self,
        source: str,
        function_name: str
    ) -> Optional[str]:
        """
        Compute hash for a specific function's signature.
        
        Args:
            source: Python source code
            function_name: Name of function to hash
            
        Returns:
            Hash string, or None if function not found
        """
        result = self.parse(source)
        
        for element in result.elements:
            if (element.element_type in (SemanticElementType.FUNCTION, SemanticElementType.METHOD)
                and element.name == function_name):
                return element.hash
        
        return None
    
    def compute_class_hash(
        self,
        source: str,
        class_name: str
    ) -> Optional[str]:
        """
        Compute hash for a specific class.
        
        Args:
            source: Python source code
            class_name: Name of class to hash
            
        Returns:
            Hash string, or None if class not found
        """
        result = self.parse(source)
        
        # Get all elements for this class
        class_elements = []
        found_class = False
        
        for element in result.elements:
            if (element.element_type == SemanticElementType.CLASS
                and element.name == class_name):
                class_elements.append(element)
                found_class = True
            elif element.element_type == SemanticElementType.METHOD:
                if element.name.startswith(f"{class_name}."):
                    class_elements.append(element)
        
        if not found_class:
            return None
        
        # Compute combined hash
        content = "|".join(e.hash for e in class_elements if e.hash)
        return hashlib.sha256(content.encode()).hexdigest()[:32] if content else ""
    
    def diff_semantic(
        self,
        old_source: str,
        new_source: str
    ) -> Dict[str, Any]:
        """
        Compute semantic diff between two versions of source code.
        
        Args:
            old_source: Original source code
            new_source: New source code
            
        Returns:
            Dict with added, removed, and changed elements
        """
        old_result = self.parse(old_source)
        new_result = self.parse(new_source)
        
        old_elements = {e.name: e for e in old_result.elements}
        new_elements = {e.name: e for e in new_result.elements}
        
        old_names = set(old_elements.keys())
        new_names = set(new_elements.keys())
        
        added = new_names - old_names
        removed = old_names - new_names
        common = old_names & new_names
        
        changed = set()
        for name in common:
            if old_elements[name].hash != new_elements[name].hash:
                changed.add(name)
        
        return {
            "added": sorted(list(added)),
            "removed": sorted(list(removed)),
            "changed": sorted(list(changed)),
            "added_imports": [i for i in new_result.imports if i not in old_result.imports],
            "removed_imports": [i for i in old_result.imports if i not in new_result.imports],
            "old_hash": old_result.semantic_hash,
            "new_hash": new_result.semantic_hash,
            "has_semantic_change": bool(added or removed or changed),
        }
