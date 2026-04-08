#!/usr/bin/env python3
"""
sync_readme_version.py - Synchronize README.md version with VERSION file (SSOT)

This script ensures README.md version header stays synchronized with the VERSION file,
which is the Single Source of Truth (SSOT) for version information.

Usage:
    python scripts/sync_readme_version.py [--dry-run] [--verbose]

Exit Codes:
    0 - Success (versions already synced or successfully updated)
    1 - Error (file not found, parse error, etc.)
    2 - Drift detected in dry-run mode

Author: TITAN FUSE Team
Version: 1.0.0
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

# Repository root (script is in scripts/ directory)
REPO_ROOT = Path(__file__).parent.parent

# File paths
VERSION_FILE = REPO_ROOT / "VERSION"
README_FILE = REPO_ROOT / "README.md"
NAV_MAP_FILE = REPO_ROOT / ".ai" / "nav_map.json"
META_FILE = REPO_ROOT / ".github" / "README_META.yaml"

# Version header anchor pattern
VERSION_HEADER_PATTERN = re.compile(
    r'(<!--\s*version-header\s*-->\s*\n)?'
    r'(#\s*TITAN\s+FUSE\s+Protocol\s*\n\s*\*\*[^*]*v)([0-9]+\.[0-9]+\.[0-9]+)(\*\*)',
    re.IGNORECASE | re.MULTILINE
)

# Alternative pattern for version in header without anchor
SIMPLE_VERSION_PATTERN = re.compile(
    r'(#\s*TITAN\s+FUSE\s+Protocol\s*\n\s*\*\*[^*]*v)([0-9]+\.[0-9]+\.[0-9]+)(\*\*)',
    re.IGNORECASE | re.MULTILINE
)


def get_version_from_file() -> Optional[str]:
    """Read version from VERSION file (SSOT)."""
    try:
        version = VERSION_FILE.read_text().strip().split()[0]  # First token only
        # Validate semver format
        if re.match(r'^[0-9]+\.[0-9]+\.[0-9]+$', version):
            return version
        print(f"ERROR: Invalid version format in VERSION file: {version}", file=sys.stderr)
        return None
    except FileNotFoundError:
        print(f"ERROR: VERSION file not found at {VERSION_FILE}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"ERROR: Failed to read VERSION file: {e}", file=sys.stderr)
        return None


def get_version_from_nav_map() -> Optional[str]:
    """Read version from nav_map.json."""
    try:
        if not NAV_MAP_FILE.exists():
            return None
        data = json.loads(NAV_MAP_FILE.read_text())
        return data.get("version")
    except Exception:
        return None


def find_readme_version() -> Tuple[Optional[str], Optional[re.Match]]:
    """Find current version in README.md and return with match object."""
    try:
        content = README_FILE.read_text()

        # Try with anchor first
        match = VERSION_HEADER_PATTERN.search(content)
        if match:
            # Group 3 has the version in the anchored pattern
            version = match.group(3)
            return version, match

        # Try simple pattern
        match = SIMPLE_VERSION_PATTERN.search(content)
        if match:
            version = match.group(2)
            return version, match

        return None, None
    except FileNotFoundError:
        print(f"ERROR: README.md not found at {README_FILE}", file=sys.stderr)
        return None, None
    except Exception as e:
        print(f"ERROR: Failed to read README.md: {e}", file=sys.stderr)
        return None, None


def add_version_anchor(content: str) -> str:
    """Add version-header anchor before H1 if not present."""
    if "<!-- version-header -->" in content:
        return content

    # Find the H1 line
    h1_pattern = re.compile(r'^(#\s*TITAN\s+FUSE\s+Protocol)', re.MULTILINE)
    match = h1_pattern.search(content)

    if match:
        # Insert anchor before H1
        insert_pos = match.start()
        anchor = "<!-- version-header -->\n"
        content = content[:insert_pos] + anchor + content[insert_pos:]

    return content


def sync_readme_version(ssot_version: str, dry_run: bool = False, verbose: bool = False) -> bool:
    """
    Synchronize README.md version with SSOT version.

    Args:
        ssot_version: Version from VERSION file (SSOT)
        dry_run: If True, only check without making changes
        verbose: If True, print detailed information

    Returns:
        True if successful or no changes needed, False on error
    """
    try:
        content = README_FILE.read_text()
        original_content = content

        # Add anchor if missing
        content = add_version_anchor(content)

        # Find and replace version
        current_version, match = find_readme_version()

        if current_version is None:
            print("ERROR: Could not find version in README.md", file=sys.stderr)
            return False

        if current_version == ssot_version:
            if verbose:
                print(f"✓ README.md version already synced: v{ssot_version}")

            # Check if anchor needs to be added
            if "<!-- version-header -->" not in original_content:
                if dry_run:
                    print(f"Would add version-header anchor to README.md")
                    return True
                README_FILE.write_text(content)
                if verbose:
                    print("✓ Added version-header anchor to README.md")
            return True

        if verbose or dry_run:
            print(f"Version drift detected:")
            print(f"  VERSION file (SSOT): v{ssot_version}")
            print(f"  README.md:           v{current_version}")

        if dry_run:
            print(f"Would update README.md: v{current_version} → v{ssot_version}")
            return True

        # Replace version in README.md
        # Pattern to match version in header with or without anchor
        version_replace_pattern = re.compile(
            r'(<!--\s*version-header\s*-->\s*\n)?'
            r'(#\s*TITAN\s+FUSE\s+Protocol\s*\n\s*\*\*[^*]*v)[0-9]+\.[0-9]+\.[0-9]+(\*\*)',
            re.IGNORECASE
        )

        new_content = version_replace_pattern.sub(
            f'<!-- version-header -->\n\\2{ssot_version}\\3',
            content
        )

        if new_content == content:
            # Fallback: simple replacement
            new_content = content.replace(
                f"v{current_version}",
                f"v{ssot_version}",
                1  # Only first occurrence
            )

        README_FILE.write_text(new_content)
        print(f"✓ Updated README.md: v{current_version} → v{ssot_version}")

        return True

    except Exception as e:
        print(f"ERROR: Failed to sync README.md: {e}", file=sys.stderr)
        return False


def sync_nav_map(ssot_version: str, dry_run: bool = False, verbose: bool = False) -> bool:
    """Synchronize nav_map.json version."""
    try:
        if not NAV_MAP_FILE.exists():
            if verbose:
                print("⚠ nav_map.json not found, skipping")
            return True

        data = json.loads(NAV_MAP_FILE.read_text())
        current_version = data.get("version")

        if current_version == ssot_version:
            if verbose:
                print(f"✓ nav_map.json version already synced: v{ssot_version}")
            return True

        if verbose or dry_run:
            print(f"nav_map.json drift: v{current_version} → v{ssot_version}")

        if dry_run:
            return True

        data["version"] = ssot_version
        NAV_MAP_FILE.write_text(json.dumps(data, indent=2) + "\n")
        print(f"✓ Updated nav_map.json: v{current_version} → v{ssot_version}")

        return True

    except Exception as e:
        print(f"ERROR: Failed to sync nav_map.json: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Synchronize README.md version with VERSION file (SSOT)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check for drift without making changes"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed information"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with error if any drift detected"
    )

    args = parser.parse_args()

    # Get SSOT version
    ssot_version = get_version_from_file()
    if ssot_version is None:
        sys.exit(1)

    if args.verbose:
        print(f"SSOT version from VERSION file: v{ssot_version}")

    # Track if any drift was found
    drift_found = False

    # Sync README.md
    readme_version, _ = find_readme_version()
    if readme_version != ssot_version:
        drift_found = True
        if args.verbose:
            print(f"README.md version: v{readme_version or 'NOT FOUND'}")

    if not sync_readme_version(ssot_version, args.dry_run, args.verbose):
        sys.exit(1)

    # Sync nav_map.json
    nav_version = get_version_from_nav_map()
    if nav_version and nav_version != ssot_version:
        drift_found = True

    if not sync_nav_map(ssot_version, args.dry_run, args.verbose):
        sys.exit(1)

    # Exit with error if strict mode and drift found
    if args.strict and drift_found and args.dry_run:
        print("ERROR: Version drift detected (strict mode)", file=sys.stderr)
        sys.exit(2)

    print("✓ Version sync complete")
    sys.exit(0)


if __name__ == "__main__":
    main()
