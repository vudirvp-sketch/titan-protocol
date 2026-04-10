#!/usr/bin/env python3
"""
Convert consolidated prompt analyses (markdown with YAML blocks) into
prompt_registry.yaml format.

Usage:
    python scripts/convert_prompt_analysis.py --input analyses/ --output config/prompt_registry.yaml
    python scripts/convert_prompt_analysis.py --dry-run --input analyses/
    python scripts/convert_prompt_analysis.py --validate config/prompt_registry.yaml
"""
import argparse
import hashlib
import os
import re
import sys
from datetime import datetime, timezone

import yaml


def extract_yaml_blocks(markdown_content: str) -> list:
    """Extract YAML code blocks from markdown content."""
    pattern = r"```yaml\n(.*?)```"
    matches = re.findall(pattern, markdown_content, re.DOTALL)
    blocks = []
    for match in matches:
        try:
            parsed = yaml.safe_load(match)
            if isinstance(parsed, dict):
                blocks.append(parsed)
        except yaml.YAMLError:
            continue
    return blocks


def extract_pattern_definitions(blocks: list) -> list:
    """Extract pattern definitions from parsed YAML blocks."""
    patterns = []
    for block in blocks:
        if "pattern_id" in block or "name" in block:
            pattern = {
                "pattern_id": block.get("pattern_id", block.get("name", "UNKNOWN")),
                "version": block.get("version", "1.0.0"),
                "description": block.get("description", ""),
                "activation_triggers": block.get("activation_triggers", []),
                "titan_mapping": block.get("titan_mapping", {}),
                "gates": block.get("gates", []),
                "gap_events": block.get("gap_events", []),
            }
            patterns.append(pattern)
    return patterns


def generate_registry_yaml(patterns: list) -> str:
    """Generate prompt_registry.yaml content from pattern definitions."""
    registry = {
        "version": "1.0.0",
        "generated": datetime.now(timezone.utc).isoformat(),
        "patterns": {},
    }
    for pattern in patterns:
        pid = pattern["pattern_id"]
        registry["patterns"][pid] = {
            "version": pattern["version"],
            "description": pattern["description"],
            "activation_triggers": pattern["activation_triggers"],
            "titan_mapping": pattern["titan_mapping"],
            "gates": pattern["gates"],
            "gap_events": pattern["gap_events"],
        }
    return yaml.dump(registry, default_flow_style=False, sort_keys=True)


def validate_registry(filepath: str) -> bool:
    """Validate a prompt_registry.yaml file."""
    with open(filepath, "r") as f:
        registry = yaml.safe_load(f)

    required_top = ["version", "patterns"]
    for field in required_top:
        if field not in registry:
            print(f"ERROR: Missing required field '{field}'", file=sys.stderr)
            return False

    for pid, pattern in registry.get("patterns", {}).items():
        required_pattern = ["version", "description", "activation_triggers", "titan_mapping"]
        for field in required_pattern:
            if field not in pattern:
                print(f"ERROR: Pattern '{pid}' missing field '{field}'", file=sys.stderr)
                return False

    print(f"VALID: {len(registry['patterns'])} patterns in {filepath}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Convert prompt analyses to registry format")
    parser.add_argument("--input", "-i", required=True, help="Input directory or file")
    parser.add_argument("--output", "-o", help="Output YAML file path")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing")
    parser.add_argument("--validate", action="store_true", help="Validate existing registry file")
    args = parser.parse_args()

    if args.validate:
        success = validate_registry(args.input)
        sys.exit(0 if success else 1)

    # Read input files
    all_blocks = []
    if os.path.isdir(args.input):
        for fname in sorted(os.listdir(args.input)):
            if fname.endswith((".md", ".yaml", ".yml")):
                fpath = os.path.join(args.input, fname)
                with open(fpath, "r") as f:
                    content = f.read()
                all_blocks.extend(extract_yaml_blocks(content))
    elif os.path.isfile(args.input):
        with open(args.input, "r") as f:
            content = f.read()
        all_blocks.extend(extract_yaml_blocks(content))

    patterns = extract_pattern_definitions(all_blocks)
    print(f"Extracted {len(patterns)} pattern definitions from {len(all_blocks)} YAML blocks")

    output = generate_registry_yaml(patterns)

    if args.dry_run:
        print(output)
    elif args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Written to {args.output}")
    else:
        print("ERROR: Specify --output or --dry-run", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
