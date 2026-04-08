"""
Semantic Checksum System for TITAN FUSE Protocol.

ITEM-SAE-006: AST Checksum System Implementation

This module implements AST-based semantic checksums that only change when
the actual code structure changes, not formatting or comments.

Key Features:
- Multi-language support (Python, JavaScript, YAML, JSON)
- Signature-based hashing for functions/classes
- Change detection at semantic level
- Integration with Context Graph

Benefits over content-based hashing:
- Comment changes don't trigger invalidation
- Formatting changes don't trigger invalidation
- Only actual code changes trigger context refresh

Author: TITAN FUSE Team
Version: 1.0.0
"""

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple, Callable
import logging
import threading

from src.utils.timezone import now_utc, now_utc_iso
from src.context.parsers.python_parser import PythonParser
from src.context.parsers.javascript_parser import JavaScriptParser
from src.context.parsers.yaml_parser import YAMLParser
from src.context.parsers.json_parser import JSONParser


class Language(Enum):
    """Supported languages for semantic parsing."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    YAML = "yaml"
    JSON = "json"
    UNKNOWN = "unknown"


@dataclass
class ChecksumDiff:
    """
    Represents the difference between two checksums.
    
    Attributes:
        old_hash: Previous semantic hash
        new_hash: Current semantic hash
        has_semantic_change: Whether there's a semantic change
        added_elements: Elements added
        removed_elements: Elements removed
        changed_elements: Elements modified
        details: Additional details about the change
    """
    old_hash: str
    new_hash: str
    has_semantic_change: bool = False
    added_elements: List[str] = field(default_factory=list)
    removed_elements: List[str] = field(default_factory=list)
    changed_elements: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "has_semantic_change": self.has_semantic_change,
            "added_elements": self.added_elements,
            "removed_elements": self.removed_elements,
            "changed_elements": self.changed_elements,
            "details": self.details,
        }


@dataclass
class SemanticChecksumResult:
    """
    Result of computing semantic checksum.
    
    Attributes:
        file_path: Path to the file
        language: Detected language
        semantic_hash: Computed semantic hash
        content_hash: Traditional content hash (for comparison)
        element_count: Number of semantic elements
        parse_errors: Any errors during parsing
        timestamp: When the checksum was computed
    """
    file_path: str
    language: Language
    semantic_hash: str
    content_hash: str
    element_count: int
    parse_errors: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=now_utc_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "file_path": self.file_path,
            "language": self.language.value,
            "semantic_hash": self.semantic_hash,
            "content_hash": self.content_hash,
            "element_count": self.element_count,
            "parse_errors": self.parse_errors,
            "timestamp": self.timestamp,
        }


class SemanticChecksum:
    """
    AST-based semantic checksum calculator.
    
    Computes checksums based on semantic content of files, ignoring
    non-semantic elements like comments and whitespace.
    
    Supported Languages:
    - Python (.py)
    - JavaScript (.js, .mjs)
    - TypeScript (.ts, .tsx)
    - YAML (.yaml, .yml)
    - JSON (.json)
    
    Usage:
        checksummer = SemanticChecksum()
        
        # Compute semantic hash for a file
        result = checksummer.compute_file_hash("src/main.py")
        
        # Compute for content string
        result = checksummer.compute_ast_hash(source_code, Language.PYTHON)
        
        # Compare checksums
        diff = checksummer.compare_checksums(old_hash, new_hash, old_source, new_source)
    """
    
    # File extension to language mapping
    EXTENSION_MAP: Dict[str, Language] = {
        ".py": Language.PYTHON,
        ".js": Language.JAVASCRIPT,
        ".mjs": Language.JAVASCRIPT,
        ".cjs": Language.JAVASCRIPT,
        ".ts": Language.TYPESCRIPT,
        ".tsx": Language.TYPESCRIPT,
        ".yaml": Language.YAML,
        ".yml": Language.YAML,
        ".json": Language.JSON,
    }
    
    def __init__(
        self,
        fallback_to_content_hash: bool = True,
        include_docstrings: bool = False,
        include_private: bool = False,
    ):
        """
        Initialize the SemanticChecksum.
        
        Args:
            fallback_to_content_hash: Fall back to content hash for unsupported files
            include_docstrings: Include docstrings in Python hash
            include_private: Include private members in hash
        """
        self.fallback_to_content_hash = fallback_to_content_hash
        self.include_docstrings = include_docstrings
        self.include_private = include_private
        
        self._logger = logging.getLogger(__name__)
        
        # Initialize language parsers
        self._parsers: Dict[Language, Any] = {
            Language.PYTHON: PythonParser(
                include_docstrings=include_docstrings,
                include_private=include_private,
            ),
            Language.JAVASCRIPT: JavaScriptParser(include_private=include_private),
            Language.TYPESCRIPT: JavaScriptParser(include_private=include_private, typescript=True),
            Language.YAML: YAMLParser(),
            Language.JSON: JSONParser(),
        }
    
    def detect_language(self, file_path: str) -> Language:
        """
        Detect language from file extension.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Detected Language
        """
        ext = Path(file_path).suffix.lower()
        return self.EXTENSION_MAP.get(ext, Language.UNKNOWN)
    
    def compute_file_hash(
        self,
        file_path: str,
        language: Optional[Language] = None
    ) -> SemanticChecksumResult:
        """
        Compute semantic hash for a file.
        
        Args:
            file_path: Path to the file
            language: Optional language override
            
        Returns:
            SemanticChecksumResult with hash and metadata
        """
        # Read file content
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            self._logger.error(f"File not found: {file_path}")
            return SemanticChecksumResult(
                file_path=file_path,
                language=Language.UNKNOWN,
                semantic_hash="",
                content_hash="",
                element_count=0,
                parse_errors=["File not found"],
            )
        except UnicodeDecodeError:
            self._logger.error(f"Unable to decode file: {file_path}")
            return SemanticChecksumResult(
                file_path=file_path,
                language=Language.UNKNOWN,
                semantic_hash="",
                content_hash="",
                element_count=0,
                parse_errors=["Unable to decode as UTF-8"],
            )
        
        # Detect language if not provided
        if language is None:
            language = self.detect_language(file_path)
        
        return self.compute_ast_hash(content, language, file_path)
    
    def compute_ast_hash(
        self,
        content: str,
        language: Language,
        file_path: str = "<string>"
    ) -> SemanticChecksumResult:
        """
        Compute AST-based semantic hash for content.
        
        Args:
            content: Source code content
            language: Language of the content
            file_path: Optional file path for context
            
        Returns:
            SemanticChecksumResult with hash and metadata
        """
        # Compute content hash for comparison
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
        
        # Get parser for language
        parser = self._parsers.get(language)
        
        if parser is None:
            # Unsupported language
            if self.fallback_to_content_hash:
                self._logger.debug(
                    f"Unsupported language {language.value}, using content hash"
                )
                return SemanticChecksumResult(
                    file_path=file_path,
                    language=language,
                    semantic_hash=content_hash,
                    content_hash=content_hash,
                    element_count=0,
                    parse_errors=["Unsupported language, used content hash"],
                )
            else:
                return SemanticChecksumResult(
                    file_path=file_path,
                    language=language,
                    semantic_hash="",
                    content_hash=content_hash,
                    element_count=0,
                    parse_errors=["Unsupported language"],
                )
        
        # Parse and compute semantic hash
        try:
            result = parser.parse(content)
            
            return SemanticChecksumResult(
                file_path=file_path,
                language=language,
                semantic_hash=result.semantic_hash,
                content_hash=content_hash,
                element_count=result.element_count,
                parse_errors=result.parse_errors,
            )
        except Exception as e:
            self._logger.error(f"Parse error: {e}")
            
            if self.fallback_to_content_hash:
                return SemanticChecksumResult(
                    file_path=file_path,
                    language=language,
                    semantic_hash=content_hash,
                    content_hash=content_hash,
                    element_count=0,
                    parse_errors=[f"Parse error: {str(e)}, used content hash"],
                )
            else:
                return SemanticChecksumResult(
                    file_path=file_path,
                    language=language,
                    semantic_hash="",
                    content_hash=content_hash,
                    element_count=0,
                    parse_errors=[f"Parse error: {str(e)}"],
                )
    
    def compute_signature_hash(
        self,
        content: str,
        function_name: str,
        language: Language = Language.PYTHON
    ) -> Optional[str]:
        """
        Compute hash for a specific function's signature.
        
        Args:
            content: Source code content
            function_name: Name of the function
            language: Language of the content
            
        Returns:
            Signature hash, or None if function not found
        """
        parser = self._parsers.get(language)
        if parser is None:
            return None
        
        if language == Language.PYTHON:
            return parser.compute_signature_hash(content, function_name)
        
        # For other languages, parse and find the function
        result = parser.parse(content)
        for element in result.elements:
            if element.name == function_name:
                return element.hash
        
        return None
    
    def compute_class_hash(
        self,
        content: str,
        class_name: str,
        language: Language = Language.PYTHON
    ) -> Optional[str]:
        """
        Compute hash for a specific class.
        
        Args:
            content: Source code content
            class_name: Name of the class
            language: Language of the content
            
        Returns:
            Class hash, or None if class not found
        """
        parser = self._parsers.get(language)
        if parser is None:
            return None
        
        if language == Language.PYTHON:
            return parser.compute_class_hash(content, class_name)
        
        # For other languages, compute combined hash of class and methods
        result = parser.parse(content)
        class_elements = []
        
        for element in result.elements:
            if element.name == class_name or element.name.startswith(f"{class_name}."):
                class_elements.append(element)
        
        if not class_elements:
            return None
        
        content_hash = "|".join(e.hash for e in class_elements if e.hash)
        return hashlib.sha256(content_hash.encode()).hexdigest()[:32] if content_hash else ""
    
    def compare_checksums(
        self,
        old_hash: str,
        new_hash: str,
        old_source: Optional[str] = None,
        new_source: Optional[str] = None,
        language: Optional[Language] = None
    ) -> ChecksumDiff:
        """
        Compare two checksums and identify changes.
        
        Args:
            old_hash: Previous semantic hash
            new_hash: Current semantic hash
            old_source: Optional old source for detailed diff
            new_source: Optional new source for detailed diff
            language: Language for parsing (required for detailed diff)
            
        Returns:
            ChecksumDiff with change details
        """
        diff = ChecksumDiff(
            old_hash=old_hash,
            new_hash=new_hash,
            has_semantic_change=(old_hash != new_hash),
        )
        
        # If sources provided, compute detailed diff
        if old_source and new_source and language:
            parser = self._parsers.get(language)
            if parser and hasattr(parser, "diff_semantic"):
                details = parser.diff_semantic(old_source, new_source)
                diff.added_elements = details.get("added", [])
                diff.removed_elements = details.get("removed", [])
                diff.changed_elements = details.get("changed", [])
                diff.details = details
        
        return diff
    
    def has_semantic_change(
        self,
        old_content: str,
        new_content: str,
        language: Language
    ) -> bool:
        """
        Check if there's a semantic change between two versions.
        
        Args:
            old_content: Previous content
            new_content: New content
            language: Language of the content
            
        Returns:
            True if there's a semantic change
        """
        old_result = self.compute_ast_hash(old_content, language)
        new_result = self.compute_ast_hash(new_content, language)
        
        return old_result.semantic_hash != new_result.semantic_hash
    
    def compute_directory_hash(
        self,
        directory: str,
        extensions: Optional[Set[str]] = None,
        exclude_patterns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Compute semantic hashes for all files in a directory.
        
        Args:
            directory: Path to directory
            extensions: Set of file extensions to include
            exclude_patterns: Patterns to exclude
            
        Returns:
            Dict with file hashes and combined hash
        """
        extensions = extensions or set(self.EXTENSION_MAP.keys())
        exclude_patterns = exclude_patterns or []
        
        file_hashes: Dict[str, str] = {}
        total_elements = 0
        errors = []
        
        for root, dirs, files in os.walk(directory):
            # Skip excluded directories
            dirs[:] = [
                d for d in dirs
                if not any(
                    self._matches_pattern(os.path.join(root, d), exclude_patterns)
                    for _ in [1]
                )
            ]
            
            for file in files:
                file_path = os.path.join(root, file)
                ext = Path(file).suffix.lower()
                
                if ext not in extensions:
                    continue
                
                # Skip excluded files
                if any(self._matches_pattern(file_path, exclude_patterns) for _ in [1]):
                    continue
                
                result = self.compute_file_hash(file_path)
                
                if result.semantic_hash:
                    rel_path = os.path.relpath(file_path, directory)
                    file_hashes[rel_path] = result.semantic_hash
                    total_elements += result.element_count
                
                errors.extend(result.parse_errors)
        
        # Compute combined hash
        combined_content = "|".join(
            f"{k}:{v}" for k, v in sorted(file_hashes.items())
        )
        combined_hash = hashlib.sha256(combined_content.encode()).hexdigest()[:32] if combined_content else ""
        
        return {
            "directory": directory,
            "file_count": len(file_hashes),
            "total_elements": total_elements,
            "combined_hash": combined_hash,
            "file_hashes": file_hashes,
            "errors": errors[:10],  # Limit error output
        }
    
    def _matches_pattern(self, path: str, patterns: List[str]) -> bool:
        """Check if path matches any pattern."""
        import fnmatch
        return any(fnmatch.fnmatch(path, p) for p in patterns)


# =============================================================================
# Module-level convenience
# =============================================================================

_default_checksum: Optional[SemanticChecksum] = None


def get_semantic_checksum(**kwargs) -> SemanticChecksum:
    """Get or create default SemanticChecksum instance."""
    global _default_checksum
    
    if _default_checksum is None:
        _default_checksum = SemanticChecksum(**kwargs)
    
    return _default_checksum


def compute_semantic_hash(content: str, language: Language) -> str:
    """Convenience function to compute semantic hash."""
    checksummer = get_semantic_checksum()
    result = checksummer.compute_ast_hash(content, language)
    return result.semantic_hash
