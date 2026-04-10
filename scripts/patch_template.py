#!/usr/bin/env python3
"""
Apply .j2patch files to Jinja2 templates with backup and revert support.

Usage:
    python scripts/patch_template.py --patch template.j2patch --target templates/skill_auto.md.jinja2
    python scripts/patch_template.py --patch template.j2patch --target templates/skill_auto.md.jinja2 --revert
"""
import argparse
import os
import re
import shutil
import sys


def apply_j2patch(patch_path: str, target_path: str) -> bool:
    """Apply a .j2patch file to a target template."""
    if not os.path.exists(patch_path):
        print(f"ERROR: Patch file not found: {patch_path}", file=sys.stderr)
        return False
    if not os.path.exists(target_path):
        print(f"ERROR: Target file not found: {target_path}", file=sys.stderr)
        return False

    # Backup original before patching
    backup_path = target_path + ".orig"
    if not os.path.exists(backup_path):
        shutil.copy2(target_path, backup_path)
        print(f"Backup created: {backup_path}")

    with open(patch_path, "r") as f:
        patch_content = f.read()
    with open(target_path, "r") as f:
        target_content = f.read()

    # Parse patch directives
    # Format: @@ SEARCH\n...content...\n@@ REPLACE\n...content...
    patches = re.findall(
        r"@@ SEARCH\n(.*?)\n@@ REPLACE\n(.*?)(?=@@ SEARCH|\Z)",
        patch_content,
        re.DOTALL,
    )

    modified = target_content
    applied = 0
    for search_str, replace_str in patches:
        if search_str in modified:
            modified = modified.replace(search_str, replace_str, 1)
            applied += 1
        else:
            print(f"WARNING: Search string not found in target: {search_str[:60]}...")

    with open(target_path, "w") as f:
        f.write(modified)
    print(f"Applied {applied}/{len(patches)} patches to {target_path}")
    return applied > 0


def revert_template(target_path: str) -> bool:
    """Revert a template to its original backup."""
    backup_path = target_path + ".orig"
    if not os.path.exists(backup_path):
        print(f"ERROR: No backup found at {backup_path}", file=sys.stderr)
        return False
    shutil.copy2(backup_path, target_path)
    os.remove(backup_path)
    print(f"Reverted {target_path} from backup")
    return True


def main():
    parser = argparse.ArgumentParser(description="Apply .j2patch to templates")
    parser.add_argument("--patch", "-p", help="Path to .j2patch file")
    parser.add_argument("--target", "-t", required=True, help="Target template file")
    parser.add_argument("--revert", action="store_true", help="Revert to original backup")
    args = parser.parse_args()

    if args.revert:
        success = revert_template(args.target)
        sys.exit(0 if success else 1)
    elif args.patch:
        success = apply_j2patch(args.patch, args.target)
        sys.exit(0 if success else 1)
    else:
        print("ERROR: Specify --patch or --revert", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
