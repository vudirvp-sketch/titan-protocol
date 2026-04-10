#!/usr/bin/env python3
"""
Update documentation files with canonical patterns information.

Usage:
    python scripts/update_docs.py --section canonical_patterns --target AI_MISSION.md
    python scripts/update_docs.py --section status --target IMPLEMENTATION_STATUS.md
"""
import argparse
import os
import sys
from datetime import datetime, timezone


CANONICAL_PATTERNS_SECTION = """## Canonical Patterns (v5.2.0)

The following 4 canonical patterns are registered and active:

| Pattern ID | Version | Purpose | Activation |
|---|---|---|---|
| TITAN_FUSE_v3.1 | 3.1 | Deep content fusion and synthesis | Intent: fuse, synthesize, merge |
| GUARDIAN_v1.1 | 1.1 | Quality validation and gate enforcement | Intent: validate, check, guard |
| AGENT_GEN_SPEC_v4.1 | 4.1 | Agent specification generation | Intent: generate, spec, define |
| DEP_AUDIT | 1.0 | Dependency structure analysis | Intent: audit, analyze, deps |

See `config/prompt_registry.yaml` for full pattern definitions.
See `docs/deferred_patterns_v5.3.0.md` for 11 deferred patterns.
"""

STATUS_UPDATE = """### v5.2.0-canonical-patterns
- [COMPLETE] ContentPipeline 6-phase execution (INIT→DELIVER)
- [COMPLETE] 4 canonical patterns registered and activatable
- [COMPLETE] Intent classifier pattern routing
- [COMPLETE] GapEvent PAT-06 compliance
- [COMPLETE] Determinism guard
- [COMPLETE] SLA benchmarking
- [COMPLETE] Rollback procedure
- [COMPLETE] CI/CD gates
- [DEFERRED] 11 additional patterns → v5.3.0
"""


def update_file(filepath: str, section: str, content: str) -> bool:
    """Update a markdown file by inserting or replacing a section."""
    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return False

    with open(filepath, "r") as f:
        file_content = f.read()

    # Check if section already exists
    section_header = f"## {section.replace('_', ' ').title()}"
    if "Canonical Patterns" in section or section == "canonical_patterns":
        section_header = "## Canonical Patterns"

    if section_header in file_content:
        # Replace existing section
        parts = file_content.split(section_header, 1)
        # Find next ## header
        remainder = parts[1]
        next_header = remainder.find("\n## ")
        if next_header >= 0:
            file_content = parts[0] + content.rstrip() + remainder[next_header:]
        else:
            file_content = parts[0] + content.rstrip() + "\n"
    else:
        # Append section
        file_content = file_content.rstrip() + "\n\n" + content

    with open(filepath, "w") as f:
        f.write(file_content)
    print(f"Updated {filepath} with section '{section}'")
    return True


def main():
    parser = argparse.ArgumentParser(description="Update documentation files")
    parser.add_argument("--section", "-s", required=True,
                        choices=["canonical_patterns", "status", "changelog"])
    parser.add_argument("--target", "-t", required=True, help="Target markdown file")
    args = parser.parse_args()

    content_map = {
        "canonical_patterns": CANONICAL_PATTERNS_SECTION,
        "status": STATUS_UPDATE,
    }
    content = content_map.get(args.section, "")
    if not content:
        print(f"ERROR: No content template for section '{args.section}'", file=sys.stderr)
        sys.exit(1)

    success = update_file(args.target, args.section, content)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
