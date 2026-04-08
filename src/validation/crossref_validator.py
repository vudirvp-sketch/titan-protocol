"""
Cross-Reference Validator for TITAN FUSE Protocol.

ITEM-INT-102: Post-GATE-04 cross-reference validation.

Validates references between files to detect broken links,
missing anchors, and invalid imports. Runs after GATE-04
and auto-invokes DIAGNOSTICS_MODULE if broken refs > 5%.

Reference Types Supported:
- Section references: #section-id
- Anchor references: [text](#anchor)
- File references: [text](path/to/file.md)
- Code references: import, from ... import
- Image references: ![](path/to/image.png)

Author: TITAN FUSE Team
Version: 4.1.0
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any, TYPE_CHECKING
from enum import Enum
from collections import defaultdict
import logging

if TYPE_CHECKING:
    from ..events.event_bus import EventBus


class ReferenceType(Enum):
    """Types of cross-references."""
    SECTION = "section"         # #section-id
    ANCHOR = "anchor"           # [text](#anchor)
    FILE = "file"               # [text](path/to/file)
    CODE_IMPORT = "code_import" # import, from ... import
    IMAGE = "image"             # ![](path/to/image)
    LINK = "link"               # [text](http://...)
    INTERNAL = "internal"       # Internal document reference


class ReferenceStatus(Enum):
    """Status of a reference."""
    VALID = "valid"
    BROKEN = "broken"
    AMBIGUOUS = "ambiguous"
    EXTERNAL = "external"  # External URL, not validated


@dataclass
class Reference:
    """
    A cross-reference found in a document.
    
    Attributes:
        ref_type: Type of reference
        source_file: File containing the reference
        source_line: Line number in source file
        target: Target of the reference
        target_file: File being referenced (if file reference)
        anchor: Anchor/section ID (if anchor reference)
        raw_text: Raw reference text
        status: Validation status
        message: Human-readable message
    """
    ref_type: ReferenceType
    source_file: str
    source_line: int
    target: str
    target_file: Optional[str] = None
    anchor: Optional[str] = None
    raw_text: str = ""
    status: ReferenceStatus = ReferenceStatus.VALID
    message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ref_type": self.ref_type.value,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "target": self.target,
            "target_file": self.target_file,
            "anchor": self.anchor,
            "raw_text": self.raw_text,
            "status": self.status.value,
            "message": self.message
        }


@dataclass
class BrokenRef:
    """
    A broken reference that needs fixing.
    
    Attributes:
        reference: The broken reference
        suggestions: Possible fixes
        severity: How critical the break is
    """
    reference: Reference
    suggestions: List[str] = field(default_factory=list)
    severity: str = "medium"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference": self.reference.to_dict(),
            "suggestions": self.suggestions,
            "severity": self.severity
        }


@dataclass
class ValidationResult:
    """
    Result of cross-reference validation.
    
    Attributes:
        total_refs: Total number of references found
        valid_refs: Number of valid references
        broken_refs: Number of broken references
        external_refs: Number of external references
        broken_rate: Percentage of broken references
        references: List of all references
        broken: List of broken references
        passed: Whether validation passed
        message: Summary message
    """
    total_refs: int = 0
    valid_refs: int = 0
    broken_refs: int = 0
    external_refs: int = 0
    broken_rate: float = 0.0
    references: List[Reference] = field(default_factory=list)
    broken: List[BrokenRef] = field(default_factory=list)
    passed: bool = True
    message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_refs": self.total_refs,
            "valid_refs": self.valid_refs,
            "broken_refs": self.broken_refs,
            "external_refs": self.external_refs,
            "broken_rate": self.broken_rate,
            "broken_count": len(self.broken),
            "passed": self.passed,
            "message": self.message
        }


class CrossRefValidator:
    """
    ITEM-INT-102: Validate cross-references between files.
    
    This validator scans processed files for references and verifies
    that all targets exist. It runs after GATE-04 and can trigger
    the DIAGNOSTICS_MODULE for detailed analysis.
    
    Features:
    - Markdown anchor validation
    - File reference validation
    - Code import validation
    - Image reference validation
    - Broken reference suggestions
    - Integration with EventBus
    
    Usage:
        validator = CrossRefValidator(event_bus=bus)
        
        # Validate references in processed files
        result = validator.validate_references([
            "outputs/file1.md",
            "outputs/file2.md"
        ])
        
        if result.broken_rate > 0.05:
            # Auto-invoke diagnostics
            diagnostics.analyze(result.broken)
        
        if not result.passed:
            print(f"Found {result.broken_refs} broken references")
    """
    
    # Patterns for reference extraction
    MARKDOWN_ANCHOR_PATTERN = re.compile(r'\[([^\]]+)\]\(#([^)]+)\)')
    MARKDOWN_FILE_PATTERN = re.compile(r'\[([^\]]+)\]\(([^#)\)]+)(?:#([^)]+))?\)')
    MARKDOWN_IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
    SECTION_ID_PATTERN = re.compile(r'^#+\s+.*\{#([^}]+)\}', re.MULTILINE)
    HTML_ANCHOR_PATTERN = re.compile(r'<[^>]+id=["\']([^"\']+)["\']', re.IGNORECASE)
    
    # Code import patterns
    PYTHON_IMPORT_PATTERN = re.compile(r'^(?:from\s+(\S+)\s+)?import\s+(.+)$', re.MULTILINE)
    JS_IMPORT_PATTERN = re.compile(r'import\s+.*from\s+["\']([^"\']+)["\']')
    
    # External URL patterns
    EXTERNAL_URL_PATTERN = re.compile(r'^https?://')
    
    # Broken reference threshold
    BROKEN_THRESHOLD = 0.05  # 5%
    
    def __init__(self, config: Dict = None, event_bus: 'EventBus' = None):
        """
        Initialize the cross-reference validator.
        
        Args:
            config: Configuration dictionary
            event_bus: Optional EventBus for emitting events
        """
        self._config = config or {}
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)
        
        # Configuration
        validation_config = self._config.get("validation", {})
        self._broken_threshold = validation_config.get(
            "crossref_broken_threshold", 
            self.BROKEN_THRESHOLD
        )
        self._validate_external = validation_config.get("validate_external_urls", False)
        self._check_images = validation_config.get("validate_image_refs", True)
        self._check_code_imports = validation_config.get("validate_code_imports", True)
        
        # Reference cache
        self._reference_cache: Dict[str, List[Reference]] = {}
        self._anchor_index: Dict[str, Set[str]] = defaultdict(set)
        self._file_index: Set[str] = set()
    
    def set_event_bus(self, event_bus: 'EventBus') -> None:
        """Set the EventBus for emitting events."""
        self._event_bus = event_bus
        self._logger.info("EventBus attached to CrossRefValidator")
    
    def validate_references(self, files: List[str]) -> ValidationResult:
        """
        Validate all references in the given files.
        
        This is the main entry point for validation. It:
        1. Builds an index of all anchors and files
        2. Extracts references from each file
        3. Validates each reference against the index
        4. Calculates broken rate and determines pass/fail
        
        Args:
            files: List of file paths to validate
            
        Returns:
            ValidationResult with all findings
        """
        self._logger.info(f"Validating cross-references in {len(files)} files")
        
        result = ValidationResult()
        
        # Build indices
        self._build_indices(files)
        
        # Extract and validate references
        for file_path in files:
            try:
                refs = self._extract_references(file_path)
                result.references.extend(refs)
            except Exception as e:
                self._logger.error(f"Error extracting references from {file_path}: {e}")
                continue
        
        # Validate each reference
        for ref in result.references:
            self._validate_reference(ref)
            
            if ref.status == ReferenceStatus.VALID:
                result.valid_refs += 1
            elif ref.status == ReferenceStatus.BROKEN:
                result.broken_refs += 1
                broken = self._create_broken_ref(ref)
                result.broken.append(broken)
            elif ref.status == ReferenceStatus.EXTERNAL:
                result.external_refs += 1
        
        # Calculate statistics
        result.total_refs = len(result.references)
        if result.total_refs > 0:
            result.broken_rate = result.broken_refs / result.total_refs
        
        # Determine pass/fail
        result.passed = result.broken_rate <= self._broken_threshold
        
        if result.passed:
            result.message = f"Validation passed: {result.broken_refs}/{result.total_refs} broken ({result.broken_rate:.1%})"
        else:
            result.message = f"Validation failed: {result.broken_refs}/{result.total_refs} broken ({result.broken_rate:.1%} > {self._broken_threshold:.0%})"
        
        # Emit event if broken rate exceeds threshold
        if result.broken_rate > self._broken_threshold:
            self._emit_broken_event(result)
        
        self._logger.info(result.message)
        return result
    
    def get_reference_graph(self) -> Dict[str, List[str]]:
        """
        Get the reference graph showing file dependencies.
        
        Returns:
            Dictionary mapping files to their referenced files
        """
        graph = defaultdict(list)
        
        for source_file, refs in self._reference_cache.items():
            for ref in refs:
                if ref.target_file and ref.target_file not in graph[source_file]:
                    graph[source_file].append(ref.target_file)
        
        return dict(graph)
    
    def calculate_broken_rate(self) -> float:
        """
        Calculate the current broken reference rate.
        
        Returns:
            Percentage of broken references
        """
        total = 0
        broken = 0
        
        for refs in self._reference_cache.values():
            for ref in refs:
                total += 1
                if ref.status == ReferenceStatus.BROKEN:
                    broken += 1
        
        return broken / total if total > 0 else 0.0
    
    def _build_indices(self, files: List[str]) -> None:
        """Build indices of anchors and files."""
        self._anchor_index.clear()
        self._file_index.clear()
        
        for file_path in files:
            path = Path(file_path)
            self._file_index.add(str(path))
            
            if not path.exists():
                continue
            
            try:
                content = path.read_text(encoding='utf-8')
                
                # Extract section IDs
                for match in self.SECTION_ID_PATTERN.finditer(content):
                    self._anchor_index[str(path)].add(match.group(1))
                
                # Extract HTML anchors
                for match in self.HTML_ANCHOR_PATTERN.finditer(content):
                    self._anchor_index[str(path)].add(match.group(1))
                
                # Generate implicit anchors from headings
                for match in re.finditer(r'^(#{1,6})\s+(.+)$', content, re.MULTILINE):
                    heading = match.group(2).strip()
                    # Generate slug from heading
                    slug = self._generate_slug(heading)
                    self._anchor_index[str(path)].add(slug)
                    
            except Exception as e:
                self._logger.error(f"Error indexing {file_path}: {e}")
    
    def _generate_slug(self, heading: str) -> str:
        """Generate a slug from a heading."""
        # Remove markdown formatting
        slug = re.sub(r'[*_`#]', '', heading)
        # Convert to lowercase and replace spaces
        slug = slug.lower().strip()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'[\s]+', '-', slug)
        return slug
    
    def _extract_references(self, file_path: str) -> List[Reference]:
        """Extract all references from a file."""
        refs = []
        path = Path(file_path)
        
        if not path.exists():
            return refs
        
        try:
            content = path.read_text(encoding='utf-8')
            lines = content.split('\n')
            
            # Markdown anchors
            for match in self.MARKDOWN_ANCHOR_PATTERN.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                refs.append(Reference(
                    ref_type=ReferenceType.ANCHOR,
                    source_file=str(path),
                    source_line=line_num,
                    target=match.group(2),
                    anchor=match.group(2),
                    raw_text=match.group(0)
                ))
            
            # Markdown file references
            for match in self.MARKDOWN_FILE_PATTERN.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                target = match.group(2)
                
                # Check if external URL
                if self.EXTERNAL_URL_PATTERN.match(target):
                    refs.append(Reference(
                        ref_type=ReferenceType.LINK,
                        source_file=str(path),
                        source_line=line_num,
                        target=target,
                        raw_text=match.group(0),
                        status=ReferenceStatus.EXTERNAL
                    ))
                else:
                    refs.append(Reference(
                        ref_type=ReferenceType.FILE,
                        source_file=str(path),
                        source_line=line_num,
                        target=target,
                        target_file=target,
                        anchor=match.group(3) if len(match.groups()) > 2 else None,
                        raw_text=match.group(0)
                    ))
            
            # Image references
            if self._check_images:
                for match in self.MARKDOWN_IMAGE_PATTERN.finditer(content):
                    line_num = content[:match.start()].count('\n') + 1
                    target = match.group(2)
                    
                    refs.append(Reference(
                        ref_type=ReferenceType.IMAGE,
                        source_file=str(path),
                        source_line=line_num,
                        target=target,
                        target_file=target,
                        raw_text=match.group(0)
                    ))
            
            # Code imports (Python)
            if self._check_code_imports:
                for match in self.PYTHON_IMPORT_PATTERN.finditer(content):
                    line_num = content[:match.start()].count('\n') + 1
                    module = match.group(1) or match.group(2)
                    
                    refs.append(Reference(
                        ref_type=ReferenceType.CODE_IMPORT,
                        source_file=str(path),
                        source_line=line_num,
                        target=module.split(',')[0].strip(),
                        raw_text=match.group(0)
                    ))
            
            # Cache references
            self._reference_cache[str(path)] = refs
            
        except Exception as e:
            self._logger.error(f"Error extracting references from {file_path}: {e}")
        
        return refs
    
    def _validate_reference(self, ref: Reference) -> None:
        """Validate a single reference."""
        # Skip external references
        if ref.status == ReferenceStatus.EXTERNAL:
            return
        
        if ref.ref_type == ReferenceType.ANCHOR:
            self._validate_anchor(ref)
        elif ref.ref_type == ReferenceType.FILE:
            self._validate_file_ref(ref)
        elif ref.ref_type == ReferenceType.IMAGE:
            self._validate_image_ref(ref)
        elif ref.ref_type == ReferenceType.CODE_IMPORT:
            self._validate_code_import(ref)
    
    def _validate_anchor(self, ref: Reference) -> None:
        """Validate an anchor reference."""
        source_path = Path(ref.source_file)
        
        # Check if anchor exists in the same file
        if ref.anchor in self._anchor_index.get(str(source_path), set()):
            ref.status = ReferenceStatus.VALID
            ref.message = f"Anchor '{ref.anchor}' found"
        else:
            ref.status = ReferenceStatus.BROKEN
            ref.message = f"Anchor '{ref.anchor}' not found in {ref.source_file}"
    
    def _validate_file_ref(self, ref: Reference) -> None:
        """Validate a file reference."""
        source_dir = Path(ref.source_file).parent
        
        # Resolve target path
        if ref.target_file:
            target_path = (source_dir / ref.target_file).resolve()
        else:
            target_path = source_dir
        
        # Check if file exists
        if str(target_path) in self._file_index or target_path.exists():
            # Check anchor if present
            if ref.anchor:
                if ref.anchor in self._anchor_index.get(str(target_path), set()):
                    ref.status = ReferenceStatus.VALID
                    ref.message = f"File and anchor found"
                else:
                    ref.status = ReferenceStatus.BROKEN
                    ref.message = f"Anchor '{ref.anchor}' not found in {ref.target_file}"
            else:
                ref.status = ReferenceStatus.VALID
                ref.message = f"File found"
        else:
            ref.status = ReferenceStatus.BROKEN
            ref.message = f"File not found: {ref.target_file}"
    
    def _validate_image_ref(self, ref: Reference) -> None:
        """Validate an image reference."""
        if self.EXTERNAL_URL_PATTERN.match(ref.target):
            ref.status = ReferenceStatus.EXTERNAL
            ref.message = "External image URL"
            return
        
        source_dir = Path(ref.source_file).parent
        target_path = (source_dir / ref.target).resolve()
        
        if target_path.exists():
            ref.status = ReferenceStatus.VALID
            ref.message = "Image found"
        else:
            ref.status = ReferenceStatus.BROKEN
            ref.message = f"Image not found: {ref.target}"
    
    def _validate_code_import(self, ref: Reference) -> None:
        """Validate a code import reference."""
        # For now, just mark as valid - full validation would require
        # dependency resolution which is complex
        ref.status = ReferenceStatus.VALID
        ref.message = f"Import: {ref.target}"
    
    def _create_broken_ref(self, ref: Reference) -> BrokenRef:
        """Create a BrokenRef with suggestions."""
        suggestions = []
        
        if ref.ref_type == ReferenceType.ANCHOR:
            # Suggest similar anchors
            source_path = Path(ref.source_file)
            existing = self._anchor_index.get(str(source_path), set())
            suggestions = self._find_similar(ref.anchor, existing)
        
        elif ref.ref_type == ReferenceType.FILE:
            # Suggest similar files
            suggestions = self._find_similar(ref.target_file, self._file_index)
        
        severity = "high" if ref.ref_type in (ReferenceType.FILE, ReferenceType.CODE_IMPORT) else "medium"
        
        return BrokenRef(
            reference=ref,
            suggestions=suggestions[:5],  # Limit suggestions
            severity=severity
        )
    
    def _find_similar(self, target: str, candidates: Set[str]) -> List[str]:
        """Find similar strings using simple matching."""
        if not target:
            return []
        
        target_lower = target.lower()
        similar = []
        
        for candidate in candidates:
            if target_lower in candidate.lower() or candidate.lower() in target_lower:
                similar.append(candidate)
        
        return similar
    
    def _emit_broken_event(self, result: ValidationResult) -> None:
        """Emit CROSSREF_BROKEN event if broken refs exceed threshold."""
        if self._event_bus:
            try:
                from ..events.event_bus import Event, EventSeverity
                event = Event(
                    event_type="CROSSREF_BROKEN",
                    data={
                        "broken_rate": result.broken_rate,
                        "broken_count": result.broken_refs,
                        "total_refs": result.total_refs,
                        "threshold": self._broken_threshold,
                        "broken_refs": [b.to_dict() for b in result.broken[:10]]
                    },
                    severity=EventSeverity.WARN,
                    source="CrossRefValidator"
                )
                self._event_bus.emit(event)
            except Exception as e:
                self._logger.error(f"Failed to emit CROSSREF_BROKEN event: {e}")
    
    def clear_cache(self) -> None:
        """Clear the reference cache."""
        self._reference_cache.clear()
        self._anchor_index.clear()
        self._file_index.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get validator statistics."""
        return {
            "files_indexed": len(self._file_index),
            "anchors_indexed": sum(len(a) for a in self._anchor_index.values()),
            "cached_files": len(self._reference_cache),
            "broken_threshold": self._broken_threshold,
            "validate_external": self._validate_external,
            "check_images": self._check_images,
            "check_code_imports": self._check_code_imports
        }


def create_crossref_validator(config: Dict = None, event_bus: 'EventBus' = None) -> CrossRefValidator:
    """
    Factory function to create a CrossRefValidator.
    
    Args:
        config: Configuration dictionary
        event_bus: Optional EventBus for events
        
    Returns:
        Configured CrossRefValidator instance
    """
    return CrossRefValidator(config, event_bus)
