"""
Context Parsers Package for TITAN FUSE Protocol.

ITEM-SAE-006: AST Checksum System - Language Parsers

This package provides language-specific parsers for extracting semantic
elements from source code and configuration files.

Each parser extracts:
- Function/method signatures
- Class definitions
- Import statements
- Configuration keys
- Other semantic elements

And ignores:
- Comments
- Whitespace
- Docstrings (configurable)

Available Parsers:
- python_parser: AST parsing for Python
- javascript_parser: AST parsing for JavaScript/TypeScript
- yaml_parser: Structure-aware parsing for YAML
- json_parser: Structure-aware parsing for JSON
"""

from src.context.parsers.python_parser import PythonParser
from src.context.parsers.javascript_parser import JavaScriptParser
from src.context.parsers.yaml_parser import YAMLParser
from src.context.parsers.json_parser import JSONParser

__all__ = [
    "PythonParser",
    "JavaScriptParser",
    "YAMLParser",
    "JSONParser",
]
