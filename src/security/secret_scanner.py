"""
Secret scanning module for TITAN FUSE Protocol.
Detects credentials and API keys in input files.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple

# Common secret patterns
SECRET_PATTERNS = [
    # AWS
    (r'AKIA[0-9A-Z]{16}', 'AWS_ACCESS_KEY'),
    (r'aws_secret_access_key\s*=\s*["\']?([A-Za-z0-9/+=]{40})["\']?', 'AWS_SECRET_KEY'),
    # GitHub
    (r'ghp_[A-Za-z0-9]{36}', 'GITHUB_PAT'),
    (r'github_token\s*=\s*["\']?([A-Za-z0-9]{36,})["\']?', 'GITHUB_TOKEN'),
    # Generic API keys
    (r'api[_-]?key\s*=\s*["\']?([A-Za-z0-9_-]{20,})["\']?', 'API_KEY'),
    (r'secret[_-]?key\s*=\s*["\']?([A-Za-z0-9_-]{20,})["\']?', 'SECRET_KEY'),
    # Private keys
    (r'-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----', 'PRIVATE_KEY'),
    # Database URLs
    (r'(postgres|mysql|mongodb)://[^:]+:[^@]+@[^/]+', 'DATABASE_URL'),
    # JWT
    (r'eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*', 'JWT_TOKEN'),
]


class SecretScanner:
    """Scan files for secrets and credentials."""
    
    def __init__(self, patterns: List[Tuple[str, str]] = None):
        self.patterns = patterns or SECRET_PATTERNS
        self.compiled = [(re.compile(p, re.IGNORECASE), name) for p, name in self.patterns]
    
    def scan_file(self, file_path: Path) -> List[Dict]:
        """Scan a single file for secrets."""
        findings = []
        
        try:
            content = file_path.read_text(errors='ignore')
            lines = content.split('\n')
            
            for pattern, name in self.compiled:
                for match in pattern.finditer(content):
                    # Find line number
                    line_num = content[:match.start()].count('\n') + 1
                    
                    findings.append({
                        "file": str(file_path.name),
                        "line": line_num,
                        "type": name,
                        "match": match.group()[:50] + "..." if len(match.group()) > 50 else match.group(),
                        "severity": "CRITICAL" if "KEY" in name or "TOKEN" in name else "HIGH"
                    })
        except Exception as e:
            findings.append({
                "file": str(file_path.name),
                "error": str(e),
                "type": "SCAN_ERROR",
                "severity": "WARN"
            })
        
        return findings
    
    def scan_directory(self, dir_path: Path) -> Dict:
        """Scan all files in directory."""
        all_findings = []
        files_scanned = 0
        
        for file_path in dir_path.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith("."):
                findings = self.scan_file(file_path)
                all_findings.extend(findings)
                files_scanned += 1
        
        return {
            "files_scanned": files_scanned,
            "secrets_found": len(all_findings),
            "findings": all_findings,
            "blocked": any(f["severity"] == "CRITICAL" for f in all_findings)
        }


def run_secret_scan(inputs_dir: Path) -> Dict:
    """Run secret scan on inputs directory."""
    scanner = SecretScanner()
    return scanner.scan_directory(inputs_dir)
