#!/usr/bin/env python3
"""
TITAN Protocol - Version Synchronization Script

ITEM-SAE-001: Version Synchronization Fix

Synchronizes version references across all project files.
Ensures consistency between VERSION file and all version references.

Usage:
    python scripts/sync_versions.py [--check] [--fix]

    --check: Only check for mismatches, don't fix
    --fix:   Automatically fix all mismatches

Author: TITAN FUSE Team
Version: 1.0.0
"""

import argparse
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class VersionSource:
    """A source of version information in the project."""
    file_path: str
    key_path: str  # JSON path like "metadata.version" or "version"
    current_value: str
    line_number: Optional[int] = None
    
    def __str__(self) -> str:
        return f"{self.file_path}:{self.key_path} = {self.current_value}"


@dataclass
class VersionMismatch:
    """A detected version mismatch."""
    expected: str
    actual: str
    source: VersionSource
    
    def __str__(self) -> str:
        return f"Mismatch in {self.source.file_path}: expected {self.expected}, got {self.actual}"


@dataclass
class SyncReport:
    """Report from version synchronization."""
    canonical_version: str
    sources: List[VersionSource] = field(default_factory=list)
    mismatches: List[VersionMismatch] = field(default_factory=list)
    fixed: List[VersionSource] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @property
    def is_consistent(self) -> bool:
        return len(self.mismatches) == 0


class VersionSynchronizer:
    """
    Synchronizes version references across the project.
    
    Checks and fixes version references in:
    - VERSION file (canonical source)
    - nav_map.json
    - package.json (if exists)
    - pyproject.toml (if exists)
    - __init__.py files
    - Schema files
    
    Usage:
        sync = VersionSynchronizer(project_root=".")
        report = sync.sync_all(fix=True)
        
        if report.is_consistent:
            print("All versions are consistent!")
        else:
            print(f"Found {len(report.mismatches)} mismatches")
    """
    
    # Files to check for version references
    # PLAN A ITEM_A002: Added PROTOCOL.md, PROTOCOL.base.md, fixed paths
    VERSION_FILES = [
        ("VERSION", "file", None),  # Canonical source
        (".ai/nav_map.json", "json", "version"),
        (".ai/context_graph.json", "json", "metadata.protocol_version"),
        ("package.json", "json", "version"),
        ("pyproject.toml", "toml", "project.version"),
        ("src/__init__.py", "py", "__version__"),
        ("schemas/config.schema.json", "json", "properties.version.default"),
        # PLAN A additions:
        ("src/orchestrator/chain_composer.py", "py", "__version__"),
        ("src/orchestrator/universal_router.py", "py", "__version__"),
        ("PROTOCOL.md", "markdown_version", None),  # Version in comment
        ("PROTOCOL.base.md", "markdown_frontmatter", "protocol_version"),
    ]
    
    # Patterns for extracting versions from different file types
    VERSION_PATTERNS = {
        "py": r'__version__\s*=\s*["\']([^"\']+)["\']',
        "toml": r'version\s*=\s*["\']([^"\']+)["\']',
        "markdown_version": r'<!--\s*Version:\s*([0-9]+\.[0-9]+\.[0-9]+)',
        "markdown_frontmatter": r'protocol_version:\s*["\']?([0-9]+\.[0-9]+\.[0-9]+)["\']?',
    }
    
    def __init__(self, project_root: str = "."):
        """Initialize synchronizer with project root."""
        self._root = Path(project_root).resolve()
        self._canonical_version: Optional[str] = None
        
    def get_canonical_version(self) -> str:
        """Get the canonical version from VERSION file."""
        if self._canonical_version is not None:
            return self._canonical_version
        
        version_file = self._root / "VERSION"
        
        if not version_file.exists():
            raise FileNotFoundError(f"VERSION file not found at {version_file}")
        
        self._canonical_version = version_file.read_text().strip()
        return self._canonical_version
    
    def get_version_sources(self) -> List[VersionSource]:
        """Find all version sources in the project."""
        sources = []
        
        for file_pattern, file_type, key_path in self.VERSION_FILES:
            file_path = self._root / file_pattern
            
            if not file_path.exists():
                continue
            
            try:
                source = self._extract_version_source(file_path, file_type, key_path)
                if source:
                    sources.append(source)
            except Exception as e:
                logger.warning(f"Failed to extract version from {file_path}: {e}")
        
        return sources
    
    def _extract_version_source(
        self,
        file_path: Path,
        file_type: str,
        key_path: Optional[str]
    ) -> Optional[VersionSource]:
        """Extract version from a file."""
        rel_path = str(file_path.relative_to(self._root))
        
        if file_type == "file":
            # Just read the whole file as version
            return VersionSource(
                file_path=rel_path,
                key_path="content",
                current_value=file_path.read_text().strip()
            )
        
        elif file_type == "json":
            content = file_path.read_text()
            data = json.loads(content)
            value = self._get_nested_value(data, key_path)
            
            if value:
                return VersionSource(
                    file_path=rel_path,
                    key_path=key_path or "root",
                    current_value=str(value)
                )
        
        elif file_type == "py" or file_type == "toml" or file_type == "markdown_version" or file_type == "markdown_frontmatter":
            content = file_path.read_text()
            pattern = self.VERSION_PATTERNS.get(file_type)
            
            if pattern:
                match = re.search(pattern, content)
                if match:
                    return VersionSource(
                        file_path=rel_path,
                        key_path="version",
                        current_value=match.group(1),
                        line_number=content[:match.start()].count('\n') + 1
                    )
        
        return None
    
    def _get_nested_value(self, data: dict, key_path: str) -> Optional[str]:
        """Get nested value from dict using dot notation."""
        if not key_path:
            return None
        
        keys = key_path.split('.')
        value = data
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        
        return str(value) if value else None
    
    def detect_mismatches(self) -> List[VersionMismatch]:
        """Detect all version mismatches."""
        mismatches = []
        canonical = self.get_canonical_version()
        sources = self.get_version_sources()
        
        for source in sources:
            if source.current_value != canonical:
                mismatches.append(VersionMismatch(
                    expected=canonical,
                    actual=source.current_value,
                    source=source
                ))
        
        return mismatches
    
    def fix_mismatches(self, mismatches: List[VersionMismatch]) -> List[VersionSource]:
        """Fix all version mismatches."""
        fixed = []
        canonical = self.get_canonical_version()
        
        for mismatch in mismatches:
            try:
                self._fix_mismatch(mismatch.source, canonical)
                fixed.append(mismatch.source)
                logger.info(f"Fixed: {mismatch.source.file_path}")
            except Exception as e:
                logger.error(f"Failed to fix {mismatch.source.file_path}: {e}")
        
        return fixed
    
    def _fix_mismatch(self, source: VersionSource, new_version: str) -> None:
        """Fix a single version mismatch."""
        file_path = self._root / source.file_path
        
        if source.key_path == "content":
            # Whole file is the version
            file_path.write_text(new_version + '\n')
        
        elif source.key_path == "version" and file_path.suffix == ".json":
            # JSON root version
            content = file_path.read_text()
            data = json.loads(content)
            data["version"] = new_version
            file_path.write_text(json.dumps(data, indent=2) + '\n')
        
        elif source.key_path.startswith("metadata."):
            # Nested JSON update
            content = file_path.read_text()
            data = json.loads(content)
            
            keys = source.key_path.split('.')
            value = data
            for key in keys[:-1]:
                value = value.setdefault(key, {})
            value[keys[-1]] = new_version
            
            file_path.write_text(json.dumps(data, indent=2) + '\n')
        
        elif file_path.suffix in ('.py', '.toml'):
            # Pattern-based replacement
            content = file_path.read_text()
            old_pattern = re.escape(source.current_value)
            
            if file_path.suffix == '.py':
                content = re.sub(
                    rf'(__version__\s*=\s*["\']){old_pattern}(["\'])',
                    rf'\g<1>{new_version}\g<2>',
                    content
                )
            else:  # toml
                content = re.sub(
                    rf'(version\s*=\s*["\']){old_pattern}(["\'])',
                    rf'\g<1>{new_version}\g<2>',
                    content
                )
            
            file_path.write_text(content)
    
    def sync_all(self, fix: bool = False) -> SyncReport:
        """
        Perform full version synchronization.
        
        Args:
            fix: Whether to fix mismatches automatically
            
        Returns:
            SyncReport with results
        """
        report = SyncReport(canonical_version=self.get_canonical_version())
        
        # Get all sources
        report.sources = self.get_version_sources()
        
        # Detect mismatches
        report.mismatches = self.detect_mismatches()
        
        # Fix if requested
        if fix and report.mismatches:
            report.fixed = self.fix_mismatches(report.mismatches)
        
        return report
    
    def check_only(self) -> SyncReport:
        """Check for mismatches without fixing."""
        return self.sync_all(fix=False)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Synchronize version references across TITAN Protocol project"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check for mismatches, don't fix"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Automatically fix all mismatches"
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory (default: current directory)"
    )
    
    args = parser.parse_args()
    
    sync = VersionSynchronizer(project_root=args.project_root)
    
    if args.check:
        report = sync.check_only()
    else:
        report = sync.sync_all(fix=args.fix)
    
    # Print report
    print(f"\n{'='*60}")
    print(f"TITAN Protocol Version Sync Report")
    print(f"{'='*60}")
    print(f"\nCanonical version: {report.canonical_version}")
    print(f"Sources found: {len(report.sources)}")
    print(f"Mismatches: {len(report.mismatches)}")
    
    if report.sources:
        print(f"\nVersion sources:")
        for source in report.sources:
            status = "✓" if source.current_value == report.canonical_version else "✗"
            print(f"  {status} {source.file_path}: {source.current_value}")
    
    if report.mismatches:
        print(f"\nMismatches detected:")
        for mismatch in report.mismatches:
            print(f"  ✗ {mismatch.source.file_path}: {mismatch.actual} → {mismatch.expected}")
    
    if report.fixed:
        print(f"\nFixed {len(report.fixed)} files")
    
    if report.errors:
        print(f"\nErrors:")
        for error in report.errors:
            print(f"  ! {error}")
    
    print(f"\n{'='*60}")
    
    if report.is_consistent:
        print("✓ All versions are consistent!")
        return 0
    else:
        print("✗ Version inconsistencies detected!")
        if not args.fix:
            print("  Run with --fix to automatically fix mismatches")
        return 1


if __name__ == "__main__":
    exit(main())
