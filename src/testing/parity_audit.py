"""
TITAN FUSE Protocol - Parity Audit

Verifies that implementation matches PROTOCOL.base.md specification.
"""

from typing import Dict, List, Tuple
from pathlib import Path
import re
import json


class ParityAudit:
    """
    Verifies that implementation matches PROTOCOL.base.md specification.

    Checks:
    - All TIER sections implemented
    - All GATE validators present
    - All INVAR invariants enforced
    - Output format compliance
    """

    def __init__(self, protocol_path: Path, implementation_path: Path):
        self.protocol_path = protocol_path
        self.implementation_path = implementation_path
        self.protocol_sections = self._parse_protocol()
        self.results = []

    def _parse_protocol(self) -> Dict:
        """Parse PROTOCOL.base.md for required sections."""
        if not self.protocol_path.exists():
            return {
                "tiers": [],
                "gates": [],
                "invariants": [],
                "principles": [],
                "phases": []
            }

        content = self.protocol_path.read_text()

        sections = {
            "tiers": list(set(re.findall(r'## TIER (-?\d+)', content))),
            "gates": list(set(re.findall(r'GATE-(\d+)', content))),
            "invariants": list(set(re.findall(r'INVAR-(\d+)', content))),
            "principles": list(set(re.findall(r'PRINCIPLE-(\d+)', content))),
            "phases": list(set(re.findall(r'PHASE (-?\d+)', content)))
        }

        return sections

    def audit(self) -> Dict:
        """
        Run parity audit.

        Returns:
            Audit result with pass/fail status and details
        """
        self.results = []

        # Check TIER implementation
        self._check_tiers()

        # Check GATE implementation
        self._check_gates()

        # Check INVAR implementation
        self._check_invariants()

        # Check output format
        self._check_output_format()

        # Check required files
        self._check_required_files()

        passed = all(r["status"] == "PASS" for r in self.results)

        return {
            "passed": passed,
            "total_checks": len(self.results),
            "passed_count": sum(1 for r in self.results if r["status"] == "PASS"),
            "failed_count": sum(1 for r in self.results if r["status"] == "FAIL"),
            "warn_count": sum(1 for r in self.results if r["status"] == "WARN"),
            "results": self.results
        }

    def _check_tiers(self) -> None:
        """Verify all TIER sections are implemented."""
        required_tiers = ["-1", "0", "1", "2", "3", "4", "5"]

        for tier in required_tiers:
            impl_has_tier = self._implementation_has_tier(tier)

            self.results.append({
                "check": f"TIER {tier}",
                "category": "tier",
                "status": "PASS" if impl_has_tier else "FAIL",
                "details": f"Implementation {'has' if impl_has_tier else 'missing'} TIER {tier}"
            })

    def _implementation_has_tier(self, tier: str) -> bool:
        """Check if implementation has tier support."""
        tier_names = {
            "-1": ["bootstrap", "tier_-1", "tier_minus_1", "phase_bootstrap"],
            "0": ["invariant", "tier_0", "phase_init", "initialization"],
            "1": ["core", "principle", "tier_1", "phase_search", "discovery"],
            "2": ["execution", "tier_2", "phase_analysis", "classification"],
            "3": ["output", "format", "tier_3", "delivery"],
            "4": ["rollback", "tier_4", "recovery"],
            "5": ["failsafe", "tier_5", "edge_case"]
        }

        for name in tier_names.get(tier, []):
            for py_file in self.implementation_path.rglob("*.py"):
                content = py_file.read_text().lower()
                if name.lower() in content:
                    return True

        return False

    def _check_gates(self) -> None:
        """Verify all GATE validators are implemented."""
        required_gates = ["00", "01", "02", "03", "04", "05"]

        for gate in required_gates:
            impl_has_gate = self._implementation_has_gate(gate)

            self.results.append({
                "check": f"GATE-{gate}",
                "category": "gate",
                "status": "PASS" if impl_has_gate else "FAIL",
                "details": f"Gate validator {'present' if impl_has_gate else 'missing'}"
            })

    def _implementation_has_gate(self, gate: str) -> bool:
        """Check if gate validator exists."""
        gate_patterns = [
            f"gate_{gate}",
            f"GATE-{gate}",
            f"validate_gate_{gate}",
            f"_validate_gate_{gate}",
            f'"GATE-{gate}"',
            f"'GATE-{gate}'"
        ]

        for py_file in self.implementation_path.rglob("*.py"):
            content = py_file.read_text()
            for pattern in gate_patterns:
                if pattern in content:
                    return True

        return False

    def _check_invariants(self) -> None:
        """Verify INVAR invariants are enforced."""
        required_invars = ["01", "02", "03", "04"]

        for invar in required_invars:
            impl_has_invar = self._implementation_has_invariant(invar)

            self.results.append({
                "check": f"INVAR-{invar}",
                "category": "invariant",
                "status": "PASS" if impl_has_invar else "WARN",
                "details": f"Invariant {'enforced' if impl_has_invar else 'not found'}"
            })

    def _implementation_has_invariant(self, invar: str) -> bool:
        """Check if invariant is enforced."""
        patterns = [
            f"INVAR-{invar}",
            f"invar_{invar}",
            f"INVARIANT_{invar}",
            "anti_fabrication",
            "zero_drift",
            "patch_idempotent",
            "keep_veto"
        ]

        for py_file in self.implementation_path.rglob("*.py"):
            content = py_file.read_text().upper()
            for pattern in patterns:
                if pattern.upper() in content:
                    return True

        return False

    def _check_output_format(self) -> None:
        """Verify output format matches specification."""
        required_outputs = [
            "STATE_SNAPSHOT",
            "EXECUTION_PLAN",
            "CHANGE_LOG",
            "VALIDATION_REPORT",
            "NAVIGATION_INDEX",
            "PATHOLOGY_REGISTRY",
            "KNOWN_GAPS",
            "FINAL_STATUS"
        ]

        for output in required_outputs:
            found = False
            for py_file in self.implementation_path.rglob("*.py"):
                content = py_file.read_text()
                if output.lower() in content.lower():
                    found = True
                    break

            self.results.append({
                "check": f"OUTPUT_{output}",
                "category": "output",
                "status": "PASS" if found else "WARN",
                "details": f"Output section {'found' if found else 'missing'}"
            })

    def _check_required_files(self) -> None:
        """Verify required files exist."""
        required_files = [
            "PROTOCOL.md",
            "PROTOCOL.base.md",
            "SKILL.md",
            "config.yaml",
            "VERSION"
        ]

        for filename in required_files:
            file_path = self.protocol_path.parent / filename
            exists = file_path.exists()

            self.results.append({
                "check": f"FILE_{filename}",
                "category": "file",
                "status": "PASS" if exists else "WARN",
                "details": f"File {'exists' if exists else 'missing'}: {filename}"
            })

    def get_missing_implementations(self) -> List[str]:
        """Get list of missing implementations."""
        return [
            r["check"] for r in self.results
            if r["status"] == "FAIL"
        ]

    def get_warnings(self) -> List[str]:
        """Get list of warnings."""
        return [
            r["check"] for r in self.results
            if r["status"] == "WARN"
        ]

    def print_report(self) -> None:
        """Print a formatted audit report."""
        result = self.audit()

        print("=" * 60)
        print("TITAN FUSE Protocol - Parity Audit Report")
        print("=" * 60)
        print()

        # Summary
        status = "✅ PASSED" if result["passed"] else "❌ FAILED"
        print(f"Status: {status}")
        print(f"Total checks: {result['total_checks']}")
        print(f"  Passed: {result['passed_count']}")
        print(f"  Failed: {result['failed_count']}")
        print(f"  Warnings: {result['warn_count']}")
        print()

        # Group by category
        categories = {}
        for r in result["results"]:
            cat = r.get("category", "other")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(r)

        for cat, checks in categories.items():
            print(f"### {cat.upper()}")
            for check in checks:
                symbol = "✓" if check["status"] == "PASS" else ("⚠" if check["status"] == "WARN" else "✗")
                print(f"  {symbol} {check['check']}: {check['details']}")
            print()

        if result["failed_count"] > 0:
            print("Missing implementations:")
            for missing in self.get_missing_implementations():
                print(f"  - {missing}")
            print()


def run_parity_audit(repo_root: Path = None) -> Dict:
    """
    Run parity audit from repository root.

    Args:
        repo_root: Repository root path (defaults to current directory)

    Returns:
        Audit result dictionary
    """
    if repo_root is None:
        repo_root = Path.cwd()

    protocol_path = repo_root / "PROTOCOL.base.md"
    implementation_path = repo_root / "src"

    audit = ParityAudit(protocol_path, implementation_path)
    return audit.audit()


if __name__ == "__main__":
    result = run_parity_audit()
    print(json.dumps(result, indent=2))
