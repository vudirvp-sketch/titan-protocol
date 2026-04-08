#!/usr/bin/env python3
"""
check_version_sync.py - Validate version synchronization across all files

This script checks that all version references in the repository are synchronized
with the VERSION file (SSOT - Single Source of Truth).

Files checked:
    - VERSION (SSOT)
    - README.md
    - .ai/nav_map.json
    - .github/README_META.yaml
    - SKILL.md (protocol_version in frontmatter)

Usage:
    python scripts/check_version_sync.py [--strict] [--json]

Exit Codes:
    0 - All versions synchronized
    1 - Error during execution
    2 - Version drift detected

Author: TITAN FUSE Team
Version: 1.0.0
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

# Repository root
REPO_ROOT = Path(__file__).parent.parent

# File paths
VERSION_FILE = REPO_ROOT / "VERSION"
README_FILE = REPO_ROOT / "README.md"
NAV_MAP_FILE = REPO_ROOT / ".ai" / "nav_map.json"
META_FILE = REPO_ROOT / ".github" / "README_META.yaml"
SKILL_FILE = REPO_ROOT / "SKILL.md"


@dataclass
class VersionCheck:
    """Result of a version check for a single file."""
    file: str
    expected: str
    actual: Optional[str]
    status: str  # 'ok', 'drift', 'error', 'not_found'
    message: str


def get_ssot_version() -> Optional[str]:
    """Get version from VERSION file (SSOT)."""
    try:
        version = VERSION_FILE.read_text().strip().split()[0]
        if re.match(r'^[0-9]+\.[0-9]+\.[0-9]+$', version):
            return version
        return None
    except Exception:
        return None


def check_readme_version(expected: str) -> VersionCheck:
    """Check version in README.md header."""
    try:
        if not README_FILE.exists():
            return VersionCheck(
                file="README.md",
                expected=expected,
                actual=None,
                status="not_found",
                message="README.md not found"
            )

        content = README_FILE.read_text()

        # Pattern for version in header
        pattern = re.compile(
            r'\*\*[^*]*v([0-9]+\.[0-9]+\.[0-9]+)\*\*',
            re.IGNORECASE
        )

        match = pattern.search(content)
        if match:
            actual = match.group(1)
            if actual == expected:
                return VersionCheck(
                    file="README.md",
                    expected=expected,
                    actual=actual,
                    status="ok",
                    message="Version synchronized"
                )
            else:
                return VersionCheck(
                    file="README.md",
                    expected=expected,
                    actual=actual,
                    status="drift",
                    message=f"Version drift: expected v{expected}, found v{actual}"
                )
        else:
            return VersionCheck(
                file="README.md",
                expected=expected,
                actual=None,
                status="error",
                message="Version not found in README.md"
            )

    except Exception as e:
        return VersionCheck(
            file="README.md",
            expected=expected,
            actual=None,
            status="error",
            message=f"Error reading file: {e}"
        )


def check_nav_map_version(expected: str) -> VersionCheck:
    """Check version in .ai/nav_map.json."""
    try:
        if not NAV_MAP_FILE.exists():
            return VersionCheck(
                file=".ai/nav_map.json",
                expected=expected,
                actual=None,
                status="not_found",
                message="nav_map.json not found"
            )

        data = json.loads(NAV_MAP_FILE.read_text())
        actual = data.get("version")

        if actual is None:
            return VersionCheck(
                file=".ai/nav_map.json",
                expected=expected,
                actual=None,
                status="error",
                message="Version key not found in nav_map.json"
            )

        if actual == expected:
            return VersionCheck(
                file=".ai/nav_map.json",
                expected=expected,
                actual=actual,
                status="ok",
                message="Version synchronized"
            )
        else:
            return VersionCheck(
                file=".ai/nav_map.json",
                expected=expected,
                actual=actual,
                status="drift",
                message=f"Version drift: expected v{expected}, found v{actual}"
            )

    except Exception as e:
        return VersionCheck(
            file=".ai/nav_map.json",
            expected=expected,
            actual=None,
            status="error",
            message=f"Error reading file: {e}"
        )


def check_meta_version(expected: str) -> VersionCheck:
    """Check version in .github/README_META.yaml."""
    try:
        if not META_FILE.exists():
            return VersionCheck(
                file=".github/README_META.yaml",
                expected=expected,
                actual=None,
                status="not_found",
                message="README_META.yaml not found"
            )

        content = META_FILE.read_text()

        # Look for version in YAML (simple regex, not full parser)
        pattern = re.compile(r'version:\s*["\']?([0-9]+\.[0-9]+\.[0-9]+)["\']?')
        match = pattern.search(content)

        if match:
            actual = match.group(1)
            if actual == expected:
                return VersionCheck(
                    file=".github/README_META.yaml",
                    expected=expected,
                    actual=actual,
                    status="ok",
                    message="Version synchronized"
                )
            else:
                return VersionCheck(
                    file=".github/README_META.yaml",
                    expected=expected,
                    actual=actual,
                    status="drift",
                    message=f"Version drift: expected v{expected}, found v{actual}"
                )
        else:
            return VersionCheck(
                file=".github/README_META.yaml",
                expected=expected,
                actual=None,
                status="error",
                message="Version not found in README_META.yaml"
            )

    except Exception as e:
        return VersionCheck(
            file=".github/README_META.yaml",
            expected=expected,
            actual=None,
            status="error",
            message=f"Error reading file: {e}"
        )


def check_skill_version(expected: str) -> VersionCheck:
    """Check protocol_version in SKILL.md frontmatter."""
    try:
        if not SKILL_FILE.exists():
            return VersionCheck(
                file="SKILL.md",
                expected=expected,
                actual=None,
                status="not_found",
                message="SKILL.md not found"
            )

        content = SKILL_FILE.read_text()

        # Look for protocol_version in YAML frontmatter
        pattern = re.compile(r'protocol_version:\s*["\']?([0-9]+\.[0-9]+\.[0-9]+)["\']?')
        match = pattern.search(content)

        if match:
            actual = match.group(1)
            if actual == expected:
                return VersionCheck(
                    file="SKILL.md",
                    expected=expected,
                    actual=actual,
                    status="ok",
                    message="protocol_version synchronized"
                )
            else:
                return VersionCheck(
                    file="SKILL.md",
                    expected=expected,
                    actual=actual,
                    status="drift",
                    message=f"protocol_version drift: expected v{expected}, found v{actual}"
                )
        else:
            return VersionCheck(
                file="SKILL.md",
                expected=expected,
                actual=None,
                status="error",
                message="protocol_version not found in SKILL.md"
            )

    except Exception as e:
        return VersionCheck(
            file="SKILL.md",
            expected=expected,
            actual=None,
            status="error",
            message=f"Error reading file: {e}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Check version synchronization across all files"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with error if any drift or error detected"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format"
    )

    args = parser.parse_args()

    # Get SSOT version
    ssot_version = get_ssot_version()
    if ssot_version is None:
        print("ERROR: Could not read VERSION file", file=sys.stderr)
        sys.exit(1)

    # Run all checks
    checks: List[VersionCheck] = [
        check_readme_version(ssot_version),
        check_nav_map_version(ssot_version),
        check_meta_version(ssot_version),
        check_skill_version(ssot_version),
    ]

    # Count statuses
    status_counts = {
        "ok": 0,
        "drift": 0,
        "error": 0,
        "not_found": 0
    }

    for check in checks:
        status_counts[check.status] += 1

    # Output results
    if args.json:
        result = {
            "ssot_version": ssot_version,
            "checks": [
                {
                    "file": c.file,
                    "expected": c.expected,
                    "actual": c.actual,
                    "status": c.status,
                    "message": c.message
                }
                for c in checks
            ],
            "summary": status_counts
        }
        print(json.dumps(result, indent=2))
    else:
        print(f"Version Sync Check (SSOT: v{ssot_version})")
        print("=" * 50)

        for check in checks:
            if check.status == "ok":
                symbol = "✓"
            elif check.status == "drift":
                symbol = "⚠"
            else:
                symbol = "✗"

            print(f"{symbol} {check.file}: {check.message}")

        print("=" * 50)
        print(f"Summary: {status_counts['ok']} OK, {status_counts['drift']} DRIFT, "
              f"{status_counts['error']} ERROR, {status_counts['not_found']} NOT_FOUND")

    # Determine exit code
    if args.strict and (status_counts["drift"] > 0 or status_counts["error"] > 0):
        sys.exit(2)

    if status_counts["ok"] == len(checks):
        print("✓ All versions synchronized")
        sys.exit(0)
    else:
        sys.exit(2 if status_counts["drift"] > 0 else 1)


if __name__ == "__main__":
    main()
