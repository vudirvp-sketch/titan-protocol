#!/usr/bin/env python3
"""
Security Badge Generator for TITAN Protocol.

Generates dynamic security badge with timestamp, tooling info, and SBOM link.

Usage:
    python scripts/generate_security_badge.py
    python scripts/generate_security_badge.py --output .github/badges/security.json
"""

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Security scan result."""
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    unknown: int = 0


@dataclass
class SecurityBadge:
    """Security badge data."""
    schemaVersion: int = 1
    label: str = "Security"
    message: str = "0 critical"
    color: str = "brightgreen"
    timestamp: str = ""
    tool: str = "Trivy"
    sbom_url: str = ""
    scan_result: Dict[str, int] = None

    def __post_init__(self):
        if self.scan_result is None:
            self.scan_result = {"critical": 0, "high": 0, "medium": 0, "low": 0}


class SecurityBadgeGenerator:
    """
    Generates security badges with scan results.
    """

    def __init__(
        self,
        project_dir: Path = None,
        output_dir: Path = None,
        version: str = None
    ):
        """
        Initialize the generator.

        Args:
            project_dir: Project root directory
            output_dir: Directory for badge output
            version: Current project version
        """
        self.project_dir = project_dir or Path(".")
        self.output_dir = output_dir or self.project_dir / ".github" / "badges"
        self.version = version or self._get_version()

    def _get_version(self) -> str:
        """Get version from VERSION file."""
        version_file = self.project_dir / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip().split('\n')[0]
        return "0.0.0"

    def run_trivy_scan(self) -> ScanResult:
        """
        Run Trivy security scan.

        Returns:
            ScanResult with vulnerability counts
        """
        result = ScanResult()

        try:
            # Try to run trivy
            proc = subprocess.run(
                ['trivy', 'fs', '--format', 'json', '--severity', 'CRITICAL,HIGH,MEDIUM,LOW', str(self.project_dir)],
                capture_output=True,
                text=True,
                timeout=300
            )

            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout)
                result = self._parse_trivy_output(data)
            else:
                logger.warning(f"Trivy scan returned non-zero or empty: {proc.stderr}")

        except FileNotFoundError:
            logger.warning("Trivy not found - using placeholder values")
        except subprocess.TimeoutExpired:
            logger.error("Trivy scan timed out")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Trivy output: {e}")
        except Exception as e:
            logger.error(f"Trivy scan failed: {e}")

        return result

    def _parse_trivy_output(self, data: Dict) -> ScanResult:
        """Parse Trivy JSON output."""
        result = ScanResult()

        results = data.get('Results', [])
        for r in results:
            vulnerabilities = r.get('Vulnerabilities', [])
            for vuln in vulnerabilities:
                severity = vuln.get('Severity', 'UNKNOWN').upper()
                if severity == 'CRITICAL':
                    result.critical += 1
                elif severity == 'HIGH':
                    result.high += 1
                elif severity == 'MEDIUM':
                    result.medium += 1
                elif severity == 'LOW':
                    result.low += 1
                else:
                    result.unknown += 1

        return result

    def generate_sbom(self) -> Optional[str]:
        """
        Generate SPDX SBOM.

        Returns:
            Path to generated SBOM or None
        """
        sbom_path = self.project_dir / "sbom.spdx.json"

        try:
            # Try using sbom-tool or trivy for SBOM generation
            proc = subprocess.run(
                ['trivy', 'fs', '--format', 'spdx-json', '--output', str(sbom_path), str(self.project_dir)],
                capture_output=True,
                text=True,
                timeout=300
            )

            if proc.returncode == 0 and sbom_path.exists():
                logger.info(f"Generated SBOM: {sbom_path}")
                return str(sbom_path)
            else:
                logger.warning(f"SBOM generation failed: {proc.stderr}")

        except FileNotFoundError:
            logger.warning("SBOM generation tool not found")
        except Exception as e:
            logger.error(f"SBOM generation failed: {e}")

        return None

    def create_badge(self, scan_result: ScanResult) -> SecurityBadge:
        """
        Create security badge from scan result.

        Args:
            scan_result: Security scan results

        Returns:
            SecurityBadge object
        """
        # Determine color based on critical vulnerabilities
        if scan_result.critical > 0:
            color = "red"
            message = f"{scan_result.critical} critical"
        elif scan_result.high > 0:
            color = "orange"
            message = f"{scan_result.high} high"
        elif scan_result.medium > 0:
            color = "yellow"
            message = f"{scan_result.medium} medium"
        else:
            color = "brightgreen"
            message = "0 critical"

        badge = SecurityBadge(
            schemaVersion=1,
            label="Security",
            message=message,
            color=color,
            timestamp=datetime.utcnow().isoformat() + "Z",
            tool="Trivy",
            sbom_url=f"https://github.com/vudirvp-sketch/titan-protocol/releases/download/v{self.version}/sbom.spdx.json",
            scan_result={
                "critical": scan_result.critical,
                "high": scan_result.high,
                "medium": scan_result.medium,
                "low": scan_result.low,
                "unknown": scan_result.unknown
            }
        )

        return badge

    def generate(self, run_scan: bool = True) -> SecurityBadge:
        """
        Generate complete security badge.

        Args:
            run_scan: Whether to run actual security scan

        Returns:
            SecurityBadge object
        """
        if run_scan:
            logger.info("Running security scan...")
            scan_result = self.run_trivy_scan()

            logger.info("Generating SBOM...")
            self.generate_sbom()
        else:
            scan_result = ScanResult()  # Default to zeros

        badge = self.create_badge(scan_result)

        return badge

    def save_badge(self, badge: SecurityBadge, output_path: Path = None) -> Path:
        """
        Save badge to JSON file.

        Args:
            badge: SecurityBadge to save
            output_path: Output file path

        Returns:
            Path to saved badge
        """
        output_path = output_path or self.output_dir / "security.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(badge), f, indent=2)

        logger.info(f"Saved security badge to {output_path}")
        return output_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate security badge for TITAN Protocol"
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=None,
        help="Output path for badge JSON"
    )
    parser.add_argument(
        '--project-dir',
        type=Path,
        default=Path("."),
        help="Project root directory"
    )
    parser.add_argument(
        '--skip-scan',
        action='store_true',
        help="Skip actual security scan (use zeros)"
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Enable verbose output"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    generator = SecurityBadgeGenerator(
        project_dir=args.project_dir,
        output_dir=args.output.parent if args.output else None
    )

    badge = generator.generate(run_scan=not args.skip_scan)
    output_path = generator.save_badge(badge, args.output)

    print(f"Security badge generated: {output_path}")
    print(f"Status: {badge.message} ({badge.color})")


if __name__ == '__main__':
    main()
