#!/usr/bin/env python3
"""
sync_versions.py - Comprehensive version synchronization across TITAN Protocol

This script ensures all version references in the codebase stay synchronized
with the VERSION file, which is the Single Source of Truth (SSOT).

Usage:
    python scripts/sync_versions.py [--check] [--fix] [--verbose]
    python scripts/sync_versions.py --report

Exit Codes:
    0 - Success (all versions synced)
    1 - Error (file not found, parse error, etc.)
    2 - Mismatches detected in check mode

Author: TITAN FUSE Team
Version: 1.0.0
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any

# Repository root (script is in scripts/ directory)
REPO_ROOT = Path(__file__).parent.parent

# File paths
VERSION_FILE = REPO_ROOT / "VERSION"

# Version source definitions - files that contain version references
VERSION_SOURCES = {
    "VERSION": {
        "path": "VERSION",
        "type": "ssot",
        "pattern": None,  # Direct file content
        "description": "Single Source of Truth for version"
    },
    "nav_map.json": {
        "path": ".ai/nav_map.json",
        "type": "json",
        "json_path": "version",
        "description": "Navigation map version"
    },
    "README.md": {
        "path": "README.md",
        "type": "regex",
        "pattern": r'(?:version-header[^\n]*\n)?#\s*TITAN\s+FUSE\s+Protocol[^\n]*v([0-9]+\.[0-9]+\.[0-9]+)',
        "description": "README header version"
    },
    "README_badge": {
        "path": "README.md",
        "type": "regex",
        "pattern": r'!\[Version\]\([^)]*badge/version-([0-9]+\.[0-9]+\.[0-9]+)',
        "description": "README version badge"
    },
    "README_tier": {
        "path": "README.md",
        "type": "regex",
        "pattern": r'!\[Tier\]\([^)]*tier-([A-Z_0-9]+)',
        "description": "README tier badge"
    },
    "SKILL.md": {
        "path": "SKILL.md",
        "type": "yaml_frontmatter",
        "key": "protocol_version",
        "description": "SKILL.md protocol version"
    },
    "PROTOCOL.base.md": {
        "path": "PROTOCOL.base.md",
        "type": "regex",
        "pattern": r'Protocol\s+v([0-9]+\.[0-9]+\.[0-9]+)',
        "description": "PROTOCOL.base.md version"
    },
    "PROTOCOL.ext.md": {
        "path": "PROTOCOL.ext.md",
        "type": "regex",
        "pattern": r'Protocol\s+v([0-9]+\.[0-9]+\.[0-9]+)',
        "description": "PROTOCOL.ext.md version"
    },
    "config.yaml": {
        "path": "config.yaml",
        "type": "yaml_key",
        "key": "protocol_version",
        "description": "config.yaml protocol version"
    }
}


class MismatchSeverity(Enum):
    """Severity level for version mismatches."""
    CRITICAL = "CRITICAL"  # SSOT mismatch
    HIGH = "HIGH"         # Core file mismatch
    MEDIUM = "MEDIUM"     # Documentation mismatch
    LOW = "LOW"           # Optional file mismatch


@dataclass
class VersionSource:
    """Represents a source of version information."""
    name: str
    path: Path
    source_type: str
    description: str
    current_version: Optional[str] = None
    expected_version: Optional[str] = None
    exists: bool = True
    error: Optional[str] = None


@dataclass
class VersionMismatch:
    """Represents a version mismatch."""
    source: VersionSource
    expected: str
    actual: Optional[str]
    severity: MismatchSeverity
    can_fix: bool = True
    message: str = ""


@dataclass
class SyncReport:
    """Report from version synchronization."""
    timestamp: str
    ssot_version: str
    sources_checked: int
    mismatches: List[VersionMismatch] = field(default_factory=list)
    fixed: List[VersionMismatch] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def is_synced(self) -> bool:
        return len(self.mismatches) == 0

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


@dataclass
class FixReport:
    """Report from fixing version mismatches."""
    timestamp: str
    fixed_count: int
    failed_count: int
    details: List[Dict[str, Any]] = field(default_factory=list)


class VersionSynchronizer:
    """
    Comprehensive version synchronizer for TITAN Protocol.
    
    Ensures all version references across the codebase stay synchronized
    with the VERSION file (Single Source of Truth).
    """
    
    def __init__(self, repo_root: Optional[Path] = None):
        """Initialize the version synchronizer."""
        self.repo_root = repo_root or REPO_ROOT
        self._ssot_version: Optional[str] = None
        self._sources: Dict[str, VersionSource] = {}
        
    def get_ssot_version(self) -> str:
        """Get the Single Source of Truth version from VERSION file."""
        if self._ssot_version is not None:
            return self._ssot_version
            
        version_file = self.repo_root / "VERSION"
        try:
            content = version_file.read_text().strip()
            # Extract first token (handles comments, etc.)
            version = content.split()[0] if content.split() else content
            # Validate semver format
            if not re.match(r'^[0-9]+\.[0-9]+\.[0-9]+$', version):
                raise ValueError(f"Invalid semver format: {version}")
            self._ssot_version = version
            return version
        except FileNotFoundError:
            raise FileNotFoundError(f"VERSION file not found at {version_file}")
        except Exception as e:
            raise RuntimeError(f"Failed to read VERSION file: {e}")
    
    def get_version_sources(self) -> List[VersionSource]:
        """
        Get all version sources and their current versions.
        
        Returns:
            List of VersionSource objects with current versions populated.
        """
        ssot = self.get_ssot_version()
        sources = []
        
        for name, config in VERSION_SOURCES.items():
            path = self.repo_root / config["path"]
            source = VersionSource(
                name=name,
                path=path,
                source_type=config["type"],
                description=config["description"],
                expected_version=ssot
            )
            
            if not path.exists():
                source.exists = False
                source.error = "File not found"
                sources.append(source)
                continue
                
            try:
                version = self._extract_version(path, config)
                source.current_version = version
            except Exception as e:
                source.error = str(e)
                
            sources.append(source)
            self._sources[name] = source
            
        return sources
    
    def _extract_version(self, path: Path, config: Dict) -> Optional[str]:
        """Extract version from a file based on its type."""
        source_type = config["type"]
        content = path.read_text()
        
        if source_type == "ssot":
            return content.strip().split()[0]
            
        elif source_type == "json":
            data = json.loads(content)
            json_path = config.get("json_path", "version")
            keys = json_path.split(".")
            for key in keys:
                if isinstance(data, dict) and key in data:
                    data = data[key]
                else:
                    return None
            return str(data) if data else None
            
        elif source_type == "regex":
            pattern = config.get("pattern")
            if not pattern:
                return None
            match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
            if match:
                return match.group(1)
            return None
            
        elif source_type == "yaml_frontmatter":
            # Extract YAML frontmatter
            match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
            if match:
                import yaml
                frontmatter = yaml.safe_load(match.group(1))
                key = config.get("key", "protocol_version")
                return str(frontmatter.get(key, ""))
            return None
            
        elif source_type == "yaml_key":
            import yaml
            data = yaml.safe_load(content)
            key = config.get("key", "protocol_version")
            return str(data.get(key, ""))
            
        return None
    
    def detect_mismatches(self) -> List[VersionMismatch]:
        """
        Detect all version mismatches against SSOT.
        
        Returns:
            List of VersionMismatch objects.
        """
        ssot = self.get_ssot_version()
        sources = self.get_version_sources()
        mismatches = []
        
        for source in sources:
            if not source.exists:
                # Missing files are only errors for critical sources
                if source.name in ["VERSION", "nav_map.json", "README.md"]:
                    mismatches.append(VersionMismatch(
                        source=source,
                        expected=ssot,
                        actual=None,
                        severity=MismatchSeverity.CRITICAL,
                        can_fix=False,
                        message=f"Critical file missing: {source.path}"
                    ))
                continue
                
            if source.error:
                continue
                
            if source.current_version != ssot:
                # Determine severity
                if source.name == "VERSION":
                    severity = MismatchSeverity.CRITICAL
                elif source.name in ["nav_map.json", "SKILL.md", "config.yaml"]:
                    severity = MismatchSeverity.HIGH
                elif source.name.startswith("README"):
                    severity = MismatchSeverity.MEDIUM
                else:
                    severity = MismatchSeverity.LOW
                    
                mismatches.append(VersionMismatch(
                    source=source,
                    expected=ssot,
                    actual=source.current_version,
                    severity=severity,
                    message=f"{source.name}: {source.current_version} != {ssot}"
                ))
                
        return mismatches
    
    def fix_mismatches(self, mismatches: Optional[List[VersionMismatch]] = None) -> FixReport:
        """
        Fix version mismatches by updating files to match SSOT.
        
        Args:
            mismatches: List of mismatches to fix. If None, detects all mismatches.
            
        Returns:
            FixReport with details of fixes applied.
        """
        if mismatches is None:
            mismatches = self.detect_mismatches()
            
        ssot = self.get_ssot_version()
        fixed = []
        failed = []
        details = []
        
        for mismatch in mismatches:
            if not mismatch.can_fix:
                failed.append(mismatch)
                details.append({
                    "source": mismatch.source.name,
                    "status": "skipped",
                    "reason": mismatch.message
                })
                continue
                
            try:
                success = self._fix_version(mismatch.source, ssot)
                if success:
                    fixed.append(mismatch)
                    details.append({
                        "source": mismatch.source.name,
                        "status": "fixed",
                        "old_version": mismatch.actual,
                        "new_version": ssot
                    })
                else:
                    failed.append(mismatch)
                    details.append({
                        "source": mismatch.source.name,
                        "status": "failed",
                        "reason": "Fix method returned False"
                    })
            except Exception as e:
                failed.append(mismatch)
                details.append({
                    "source": mismatch.source.name,
                    "status": "error",
                    "reason": str(e)
                })
                
        return FixReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            fixed_count=len(fixed),
            failed_count=len(failed),
            details=details
        )
    
    def _fix_version(self, source: VersionSource, new_version: str) -> bool:
        """Fix version in a single file."""
        config = VERSION_SOURCES.get(source.name, {})
        path = source.path
        
        if not path.exists():
            return False
            
        content = path.read_text()
        original = content
        
        source_type = config["type"]
        
        if source_type == "json":
            data = json.loads(content)
            json_path = config.get("json_path", "version")
            keys = json_path.split(".")
            target = data
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = new_version
            content = json.dumps(data, indent=2) + "\n"
            
        elif source_type == "regex":
            pattern = config.get("pattern")
            if not pattern:
                return False
            # Replace version in matched pattern
            def replace_version(match):
                full_match = match.group(0)
                return full_match.replace(match.group(1), new_version)
            content = re.sub(pattern, replace_version, content, count=1)
            
        elif source_type == "yaml_frontmatter":
            # Update protocol_version in frontmatter
            def update_frontmatter(match):
                import yaml
                fm = yaml.safe_load(match.group(1))
                key = config.get("key", "protocol_version")
                fm[key] = new_version
                return f"---\n{yaml.dump(fm, default_flow_style=False).strip()}\n---"
            content = re.sub(r'^---\s*\n(.*?)\n---', update_frontmatter, content, count=1, flags=re.DOTALL)
            
        elif source_type == "yaml_key":
            import yaml
            data = yaml.safe_load(content)
            key = config.get("key", "protocol_version")
            data[key] = new_version
            import io
            stream = io.StringIO()
            yaml.dump(data, stream, default_flow_style=False)
            content = stream.getvalue()
            
        else:
            return False
            
        if content != original:
            path.write_text(content)
            return True
            
        return False
    
    def sync_all(self) -> SyncReport:
        """
        Check all version sources and optionally fix mismatches.
        
        Returns:
            SyncReport with full synchronization status.
        """
        ssot = self.get_ssot_version()
        sources = self.get_version_sources()
        mismatches = self.detect_mismatches()
        
        return SyncReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            ssot_version=ssot,
            sources_checked=len(sources),
            mismatches=mismatches
        )


def print_report(report: SyncReport, verbose: bool = False):
    """Print a human-readable synchronization report."""
    print(f"\n{'='*60}")
    print(f"TITAN Protocol Version Sync Report")
    print(f"{'='*60}")
    print(f"Timestamp:       {report.timestamp}")
    print(f"SSOT Version:    v{report.ssot_version}")
    print(f"Sources Checked: {report.sources_checked}")
    print(f"\n{'─'*60}")
    
    if report.mismatches:
        print(f"\n⚠️  Version Mismatches Detected: {len(report.mismatches)}\n")
        for m in report.mismatches:
            severity_icon = {
                MismatchSeverity.CRITICAL: "🔴",
                MismatchSeverity.HIGH: "🟠",
                MismatchSeverity.MEDIUM: "🟡",
                MismatchSeverity.LOW: "⚪"
            }.get(m.severity, "⚪")
            
            print(f"  {severity_icon} {m.source.name}")
            print(f"     Expected: v{m.expected}")
            print(f"     Actual:   {f'v{m.actual}' if m.actual else 'NOT FOUND'}")
            if verbose and m.message:
                print(f"     Message:  {m.message}")
            print()
    else:
        print(f"\n✅ All versions synchronized!\n")
        
    if report.errors:
        print(f"\n❌ Errors: {len(report.errors)}\n")
        for e in report.errors:
            print(f"  - {e}")
            
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Synchronize all version references with VERSION file (SSOT)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/sync_versions.py              # Check all versions
  python scripts/sync_versions.py --check      # Exit with error if mismatches
  python scripts/sync_versions.py --fix        # Fix all mismatches
  python scripts/sync_versions.py --report     # Show detailed report
        """
    )
    parser.add_argument(
        "--check", "-c",
        action="store_true",
        help="Check mode: exit with error if mismatches detected"
    )
    parser.add_argument(
        "--fix", "-f",
        action="store_true",
        help="Fix all detected mismatches"
    )
    parser.add_argument(
        "--report", "-r",
        action="store_true",
        help="Show detailed report"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed information"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )
    
    args = parser.parse_args()
    
    synchronizer = VersionSynchronizer()
    
    try:
        ssot = synchronizer.get_ssot_version()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    
    if args.verbose:
        print(f"SSOT version: v{ssot}")
    
    # Detect mismatches
    mismatches = synchronizer.detect_mismatches()
    report = synchronizer.sync_all()
    
    # Fix if requested
    if args.fix and mismatches:
        if args.verbose:
            print(f"Fixing {len(mismatches)} mismatches...")
        fix_report = synchronizer.fix_mismatches(mismatches)
        report.fixed = [m for m in mismatches if any(
            d["source"] == m.source.name and d["status"] == "fixed"
            for d in fix_report.details
        )]
        if args.verbose:
            print(f"Fixed: {fix_report.fixed_count}, Failed: {fix_report.failed_count}")
    
    # Output
    if args.json:
        output = {
            "timestamp": report.timestamp,
            "ssot_version": report.ssot_version,
            "sources_checked": report.sources_checked,
            "mismatches_count": len(report.mismatches),
            "mismatches": [
                {
                    "source": m.source.name,
                    "expected": m.expected,
                    "actual": m.actual,
                    "severity": m.severity.value,
                    "message": m.message
                }
                for m in report.mismatches
            ],
            "fixed_count": len(report.fixed),
            "is_synced": report.is_synced
        }
        print(json.dumps(output, indent=2))
    elif args.report or args.verbose:
        print_report(report, args.verbose)
    else:
        # Summary output
        if report.mismatches:
            print(f"⚠️  Version mismatches detected: {len(report.mismatches)}")
            for m in report.mismatches:
                print(f"   - {m.source.name}: v{m.actual} != v{m.expected}")
        else:
            print("✅ All versions synchronized")
    
    # Exit codes
    if args.check and report.mismatches:
        sys.exit(2)
    elif report.has_errors:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
