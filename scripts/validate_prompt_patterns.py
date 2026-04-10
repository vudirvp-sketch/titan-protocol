#!/usr/bin/env python3
"""
Validate all patterns in prompt_registry.yaml.
CI/CD compatible with JSON output and proper exit codes.

Usage:
    python scripts/validate_prompt_patterns.py config/prompt_registry.yaml
    python scripts/validate_prompt_patterns.py config/prompt_registry.yaml --json
"""
import argparse
import json
import sys

import yaml


REQUIRED_PATTERN_FIELDS = [
    "version",
    "description",
    "activation_triggers",
    "titan_mapping",
]

VALID_TITAN_MAPPING_PATHS = [
    "pipeline.init",
    "pipeline.discover",
    "pipeline.analyze",
    "pipeline.plan",
    "pipeline.exec",
    "pipeline.deliver",
    "router.classify",
    "router.route",
    "events.gap",
    "events.emit",
]


def validate_pattern(pattern_id: str, pattern: dict) -> list:
    """Validate a single pattern definition. Returns list of errors."""
    errors = []

    # Check required fields
    for field in REQUIRED_PATTERN_FIELDS:
        if field not in pattern:
            errors.append(f"Missing required field: {field}")

    # Check version format
    version = pattern.get("version", "")
    if version and not any(c.isdigit() for c in str(version)):
        errors.append(f"Invalid version format: {version}")

    # Check activation_triggers is non-empty list
    triggers = pattern.get("activation_triggers", [])
    if not isinstance(triggers, list) or len(triggers) == 0:
        errors.append("activation_triggers must be a non-empty list")

    # Check titan_mapping paths are valid
    titan_mapping = pattern.get("titan_mapping", {})
    if isinstance(titan_mapping, dict):
        for key in titan_mapping:
            if not any(key.startswith(vp.split(".")[0]) for vp in VALID_TITAN_MAPPING_PATHS):
                errors.append(f"Suspicious titan_mapping path: {key}")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate prompt patterns")
    parser.add_argument("registry_path", help="Path to prompt_registry.yaml")
    parser.add_argument("--json", action="store_true", help="Output as JSON for CI")
    args = parser.parse_args()

    try:
        with open(args.registry_path, "r") as f:
            registry = yaml.safe_load(f)
    except (FileNotFoundError, yaml.YAMLError) as exc:
        if args.json:
            print(json.dumps({"valid": False, "error": str(exc)}))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    results = {"valid": True, "patterns": {}, "total_errors": 0}

    for pid, pattern in registry.get("patterns", {}).items():
        errors = validate_pattern(pid, pattern)
        results["patterns"][pid] = {
            "valid": len(errors) == 0,
            "errors": errors,
        }
        if errors:
            results["valid"] = False
            results["total_errors"] += len(errors)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for pid, res in results["patterns"].items():
            status = "PASS" if res["valid"] else "FAIL"
            print(f"[{status}] {pid}")
            for err in res["errors"]:
                print(f"  - {err}")

    sys.exit(0 if results["valid"] else 1)


if __name__ == "__main__":
    main()
