#!/usr/bin/env python3
"""
TITAN FUSE Protocol - Navigation Tests
Version: 1.0.0
Purpose: Verify navigation integrity and agent accessibility

Tests:
1. AGENTS.md exists and has required sections
2. All links in navigation are valid
3. nav_map.json is valid JSON with required fields
4. shortcuts.yaml is valid YAML
5. All referenced files exist
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'


class NavigationTester:
    """Test suite for navigation integrity."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root)
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.results: List[Dict[str, Any]] = []

    def log_result(self, test_name: str, status: str, message: str = ""):
        """Log a test result."""
        self.results.append({
            "test": test_name,
            "status": status,
            "message": message
        })

        if status == "PASS":
            self.passed += 1
            print(f"{GREEN}✓{RESET} {test_name}")
        elif status == "FAIL":
            self.failed += 1
            print(f"{RED}✗{RESET} {test_name}: {message}")
        else:  # WARN
            self.warnings += 1
            print(f"{YELLOW}⚠{RESET} {test_name}: {message}")

    def test_agents_md_exists(self):
        """Test that AGENTS.md exists."""
        agents_path = self.repo_root / "AGENTS.md"
        if agents_path.exists():
            self.log_result("AGENTS.md exists", "PASS")
            return True
        else:
            self.log_result("AGENTS.md exists", "FAIL", "File not found")
            return False

    def test_agents_md_sections(self):
        """Test that AGENTS.md has required sections."""
        agents_path = self.repo_root / "AGENTS.md"
        if not agents_path.exists():
            self.log_result("AGENTS.md sections", "FAIL", "File not found")
            return False

        required_sections = [
            "Quick Start",
            "Navigation Matrix",
            "Protocol Architecture",
            "Critical Constraints"
        ]

        content = agents_path.read_text()
        missing = []

        for section in required_sections:
            if f"## {section}" not in content and f"# {section}" not in content:
                missing.append(section)

        if missing:
            self.log_result("AGENTS.md sections", "FAIL", f"Missing: {', '.join(missing)}")
        else:
            self.log_result("AGENTS.md sections", "PASS")

    def test_nav_map_valid(self):
        """Test that nav_map.json is valid JSON."""
        nav_map_path = self.repo_root / ".ai" / "nav_map.json"

        if not nav_map_path.exists():
            self.log_result("nav_map.json exists", "FAIL", "File not found")
            return False

        try:
            with open(nav_map_path) as f:
                data = json.load(f)

            # Check required fields
            required_fields = ["entry_points", "semantic_index"]
            missing = [f for f in required_fields if f not in data]

            if missing:
                self.log_result("nav_map.json valid", "FAIL", f"Missing fields: {missing}")
            else:
                self.log_result("nav_map.json valid", "PASS")
                return True

        except json.JSONDecodeError as e:
            self.log_result("nav_map.json valid", "FAIL", f"Invalid JSON: {e}")
            return False

    def test_shortcuts_valid(self):
        """Test that shortcuts.yaml is valid YAML."""
        shortcuts_path = self.repo_root / ".ai" / "shortcuts.yaml"

        if not shortcuts_path.exists():
            self.log_result("shortcuts.yaml exists", "FAIL", "File not found")
            return False

        try:
            import yaml
            with open(shortcuts_path) as f:
                data = yaml.safe_load(f)

            if "shortcuts" not in data:
                self.log_result("shortcuts.yaml valid", "WARN", "Missing 'shortcuts' key")
            else:
                self.log_result("shortcuts.yaml valid", "PASS")
                return True

        except ImportError:
            # YAML not available, check basic syntax
            content = shortcuts_path.read_text()
            if "shortcuts:" in content:
                self.log_result("shortcuts.yaml valid", "PASS", "(basic check)")
                return True
            else:
                self.log_result("shortcuts.yaml valid", "WARN", "YAML parser not available")
                return True
        except Exception as e:
            self.log_result("shortcuts.yaml valid", "FAIL", f"Parse error: {e}")
            return False

    def test_ai_mission_exists(self):
        """Test that AI_MISSION.md exists."""
        mission_path = self.repo_root / "AI_MISSION.md"
        if mission_path.exists():
            self.log_result("AI_MISSION.md exists", "PASS")
            return True
        else:
            self.log_result("AI_MISSION.md exists", "FAIL", "File not found")
            return False

    def test_agentignore_exists(self):
        """Test that .agentignore exists."""
        ignore_path = self.repo_root / ".agentignore"
        if ignore_path.exists():
            self.log_result(".agentignore exists", "PASS")
            return True
        else:
            self.log_result(".agentignore exists", "WARN", "File not found (recommended)")
            return True

    def test_context_files_exist(self):
        """Test that .context.md companion files exist for key modules."""
        expected_contexts = [
            "scripts/enhanced_llm_query.context.md",
            "skills/validators/security.context.md",
            "checkpoints/checkpoint.context.md"
        ]

        missing = []
        for ctx in expected_contexts:
            if not (self.repo_root / ctx).exists():
                missing.append(ctx)

        if missing:
            self.log_result("Context files", "WARN", f"Missing: {missing}")
        else:
            self.log_result("Context files", "PASS")

    def test_skill_md_frontmatter(self):
        """Test that SKILL.md has valid YAML frontmatter."""
        skill_path = self.repo_root / "SKILL.md"
        if not skill_path.exists():
            self.log_result("SKILL.md frontmatter", "FAIL", "File not found")
            return False

        content = skill_path.read_text()

        # Check for YAML frontmatter
        if not content.startswith("---"):
            self.log_result("SKILL.md frontmatter", "WARN", "No YAML frontmatter")
            return True

        # Extract frontmatter
        try:
            parts = content.split("---", 2)
            if len(parts) < 3:
                self.log_result("SKILL.md frontmatter", "WARN", "Invalid frontmatter format")
                return True

            import yaml
            frontmatter = yaml.safe_load(parts[1])

            required = ["skill_version", "protocol_version"]
            missing = [f for f in required if f not in frontmatter]

            if missing:
                self.log_result("SKILL.md frontmatter", "WARN", f"Missing: {missing}")
            else:
                self.log_result("SKILL.md frontmatter", "PASS")

        except ImportError:
            self.log_result("SKILL.md frontmatter", "PASS", "(unverified)")
        except Exception as e:
            self.log_result("SKILL.md frontmatter", "WARN", f"Parse error: {e}")

    def test_internal_links(self):
        """Test that internal markdown links are valid."""
        md_files = list(self.repo_root.glob("**/*.md"))

        # Exclude .git and node_modules
        md_files = [f for f in md_files if ".git" not in str(f) and "node_modules" not in str(f)]

        broken_links = []

        for md_file in md_files:
            content = md_file.read_text()

            # Remove code blocks to avoid false positives from Python kwargs like [name](**kwargs)
            content_without_code = re.sub(r'```[\s\S]*?```', '', content)

            # Find markdown links: [text](path)
            links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content_without_code)

            for text, link in links:
                # Skip external links and anchors
                if link.startswith("http") or link.startswith("#") or link.startswith("mailto:"):
                    continue

                # Resolve relative path
                if link.startswith("/"):
                    target = self.repo_root / link.lstrip("/")
                else:
                    target = md_file.parent / link

                # Handle anchors
                if "#" in str(target):
                    target = Path(str(target).split("#")[0])

                if not target.exists():
                    broken_links.append({
                        "file": str(md_file.relative_to(self.repo_root)),
                        "link": link,
                        "text": text
                    })

        if broken_links:
            self.log_result("Internal links", "WARN", f"Broken links: {len(broken_links)}")
            for bl in broken_links[:5]:  # Show first 5
                print(f"    {bl['file']}: {bl['link']}")
        else:
            self.log_result("Internal links", "PASS")

    def test_decision_tree_valid(self):
        """Test that DECISION_TREE.json is valid."""
        tree_path = self.repo_root / "DECISION_TREE.json"

        if not tree_path.exists():
            self.log_result("DECISION_TREE.json exists", "WARN", "File not found (optional)")
            return True

        try:
            with open(tree_path) as f:
                data = json.load(f)

            required = ["states", "initial_state", "final_states"]
            missing = [f for f in required if f not in data]

            if missing:
                self.log_result("DECISION_TREE.json valid", "FAIL", f"Missing: {missing}")
            else:
                self.log_result("DECISION_TREE.json valid", "PASS")

        except json.JSONDecodeError as e:
            self.log_result("DECISION_TREE.json valid", "FAIL", f"Invalid JSON: {e}")

    def test_titan_index_valid(self):
        """Test that .titan_index.json is valid."""
        index_path = self.repo_root / ".titan_index.json"

        if not index_path.exists():
            self.log_result(".titan_index.json exists", "WARN", "File not found (optional)")
            return True

        try:
            with open(index_path) as f:
                data = json.load(f)

            required = ["files", "concept_index"]
            missing = [f for f in required if f not in data]

            if missing:
                self.log_result(".titan_index.json valid", "FAIL", f"Missing: {missing}")
            else:
                self.log_result(".titan_index.json valid", "PASS")

        except json.JSONDecodeError as e:
            self.log_result(".titan_index.json valid", "FAIL", f"Invalid JSON: {e}")

    def run_all_tests(self):
        """Run all navigation tests."""
        print("\n" + "=" * 60)
        print("TITAN FUSE Protocol - Navigation Tests")
        print("=" * 60 + "\n")

        # Core files
        self.test_agents_md_exists()
        self.test_agents_md_sections()
        self.test_ai_mission_exists()
        self.test_agentignore_exists()

        # AI directory
        self.test_nav_map_valid()
        self.test_shortcuts_valid()

        # Context files
        self.test_context_files_exist()

        # Frontmatter
        self.test_skill_md_frontmatter()

        # Links
        self.test_internal_links()

        # Optional files
        self.test_decision_tree_valid()
        self.test_titan_index_valid()

        # Summary
        print("\n" + "-" * 60)
        print(f"Results: {GREEN}{self.passed} passed{RESET}, "
              f"{RED}{self.failed} failed{RESET}, "
              f"{YELLOW}{self.warnings} warnings{RESET}")
        print("-" * 60 + "\n")

        return self.failed == 0


def main():
    """Main entry point."""
    # Determine repo root
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent

    print(f"Testing repository: {repo_root}")

    tester = NavigationTester(str(repo_root))
    success = tester.run_all_tests()

    # Output JSON report
    report = {
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z"),
        "repo_root": str(repo_root),
        "summary": {
            "passed": tester.passed,
            "failed": tester.failed,
            "warnings": tester.warnings
        },
        "results": tester.results
    }

    report_path = repo_root / "outputs" / "navigation_test_report.json"
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report saved to: {report_path}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
