"""
Secret scanning module for TITAN FUSE Protocol.

ITEM-115 Implementation:
- SecretScanner class with baseline support
- Detects credentials/API keys in input files
- Integration at session start
- Baseline file (.secrets.baseline) for known secrets

Detects:
- AWS keys
- GitHub tokens
- Generic API keys
- Private keys
- Database URLs
- JWT tokens

Author: TITAN FUSE Team
Version: 3.2.3
"""

import re
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from dataclasses import dataclass
import logging


@dataclass
class SecretFinding:
    """A single secret finding."""
    file: str
    line: int
    type: str
    match: str
    severity: str
    fingerprint: str
    is_baseline: bool = False
    
    def to_dict(self) -> Dict:
        return {
            'file': self.file,
            'line': self.line,
            'type': self.type,
            'match': self.match,
            'severity': self.severity,
            'fingerprint': self.fingerprint,
            'is_baseline': self.is_baseline
        }


# Common secret patterns
SECRET_PATTERNS = [
    # AWS
    (r'AKIA[0-9A-Z]{16}', 'AWS_ACCESS_KEY'),
    (r'aws_secret_access_key\s*=\s*["\']?([A-Za-z0-9/+=]{40})["\']?', 'AWS_SECRET_KEY'),
    # GitHub
    (r'ghp_[A-Za-z0-9]{36}', 'GITHUB_PAT'),
    (r'github_token\s*=\s*["\']?([A-Za-z0-9]{36,})["\']?', 'GITHUB_TOKEN'),
    # OpenAI
    (r'sk-[A-Za-z0-9]{20,}', 'OPENAI_KEY'),
    (r'sk-proj-[A-Za-z0-9]{20,}', 'OPENAI_PROJECT_KEY'),
    # Anthropic
    (r'sk-ant-[A-Za-z0-9]{20,}', 'ANTHROPIC_KEY'),
    # Generic API keys
    (r'api[_-]?key\s*=\s*["\']?([A-Za-z0-9_-]{20,})["\']?', 'API_KEY'),
    (r'secret[_-]?key\s*=\s*["\']?([A-Za-z0-9_-]{20,})["\']?', 'SECRET_KEY'),
    (r'access[_-]?token\s*=\s*["\']?([A-Za-z0-9_-]{20,})["\']?', 'ACCESS_TOKEN'),
    # Private keys
    (r'-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----', 'PRIVATE_KEY'),
    # Database URLs
    (r'(postgres|mysql|mongodb|redis)://[^:]+:[^@]+@[^/]+', 'DATABASE_URL'),
    # JWT
    (r'eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*', 'JWT_TOKEN'),
    # Slack
    (r'xox[baprs]-[0-9]{10,}-[0-9]{10,}-[A-Za-z0-9]{24}', 'SLACK_TOKEN'),
    # Stripe
    (r'sk_live_[A-Za-z0-9]{24,}', 'STRIPE_SECRET_KEY'),
    (r'rk_live_[A-Za-z0-9]{24,}', 'STRIPE_RESTRICTED_KEY'),
]


class SecretScanner:
    """
    Scan files for secrets and credentials.
    
    Features:
    - Pattern-based detection
    - Baseline support for known secrets
    - Fingerprinting for tracking
    - Severity classification
    
    Usage:
        scanner = SecretScanner()
        scanner.load_baseline('.secrets.baseline')
        findings = scanner.scan_file(Path('config.yaml'))
        result = scanner.scan_directory(Path('inputs/'))
    """
    
    def __init__(self, patterns: List[Tuple[str, str]] = None, config: Dict = None):
        """
        Initialize secret scanner.
        
        Args:
            patterns: Custom patterns list (uses defaults if not provided)
            config: Configuration dictionary
        """
        self.patterns = patterns or SECRET_PATTERNS
        self.compiled = [(re.compile(p, re.IGNORECASE), name) for p, name in self.patterns]
        self.baseline: Dict[str, Dict] = {}  # fingerprint -> finding
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
    
    def load_baseline(self, baseline_path: Path) -> int:
        """
        Load baseline file with known secrets to ignore.
        
        Args:
            baseline_path: Path to .secrets.baseline file
            
        Returns:
            Number of baseline entries loaded
        """
        if not baseline_path.exists():
            self._logger.info(f"Baseline file not found: {baseline_path}")
            return 0
        
        try:
            with open(baseline_path) as f:
                data = json.load(f)
            
            # Support both list and dict formats
            if isinstance(data, list):
                for entry in data:
                    fingerprint = entry.get('fingerprint') or self._compute_fingerprint(entry)
                    self.baseline[fingerprint] = entry
            elif isinstance(data, dict):
                self.baseline = data
            
            self._logger.info(f"Loaded {len(self.baseline)} baseline entries")
            return len(self.baseline)
            
        except Exception as e:
            self._logger.error(f"Failed to load baseline: {e}")
            return 0
    
    def save_baseline(self, baseline_path: Path, findings: List[SecretFinding] = None) -> bool:
        """
        Save current baseline to file.
        
        Args:
            baseline_path: Path to save baseline
            findings: Optional additional findings to add
            
        Returns:
            True if saved successfully
        """
        try:
            baseline_data = self.baseline.copy()
            
            if findings:
                for finding in findings:
                    if finding.fingerprint not in baseline_data:
                        baseline_data[finding.fingerprint] = finding.to_dict()
            
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            with open(baseline_path, 'w') as f:
                json.dump(baseline_data, f, indent=2)
            
            self._logger.info(f"Saved baseline with {len(baseline_data)} entries")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to save baseline: {e}")
            return False
    
    def scan_file(self, file_path: Path, baseline_path: Path = None) -> List[SecretFinding]:
        """
        Scan a single file for secrets.
        
        Args:
            file_path: Path to file to scan
            baseline_path: Optional baseline file to load first
            
        Returns:
            List of SecretFinding objects
        """
        findings = []
        
        # Load baseline if provided
        if baseline_path:
            self.load_baseline(baseline_path)
        
        try:
            content = file_path.read_text(errors='ignore')
            lines = content.split('\n')
            
            for pattern, name in self.compiled:
                for match in pattern.finditer(content):
                    # Find line number
                    line_num = content[:match.start()].count('\n') + 1
                    
                    # Create finding
                    finding = SecretFinding(
                        file=str(file_path.name),
                        line=line_num,
                        type=name,
                        match=match.group()[:50] + "..." if len(match.group()) > 50 else match.group(),
                        severity=self._get_severity(name),
                        fingerprint=self._compute_match_fingerprint(file_path, match.group(), line_num)
                    )
                    
                    # Check if in baseline
                    if finding.fingerprint in self.baseline:
                        finding.is_baseline = True
                    else:
                        findings.append(finding)
                        
        except Exception as e:
            findings.append(SecretFinding(
                file=str(file_path.name),
                line=0,
                type="SCAN_ERROR",
                match=str(e),
                severity="WARN",
                fingerprint=""
            ))
        
        return findings
    
    def scan_directory(self, dir_path: Path, baseline_path: Path = None) -> Dict:
        """
        Scan all files in directory.
        
        Args:
            dir_path: Directory to scan
            baseline_path: Optional baseline file
            
        Returns:
            Dict with scan results
        """
        all_findings: List[SecretFinding] = []
        baseline_findings: List[SecretFinding] = []
        files_scanned = 0
        errors = []
        
        # Load baseline if provided
        if baseline_path:
            self.load_baseline(baseline_path)
        
        # Get excluded patterns from config
        excluded_patterns = self.config.get('excluded_files', [])
        excluded_dirs = set(self.config.get('excluded_dirs', ['.git', 'node_modules', '__pycache__', '.venv']))
        
        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue
            
            # Skip excluded directories
            if any(part in excluded_dirs for part in file_path.parts):
                continue
            
            # Skip excluded file patterns
            if any(re.match(p, file_path.name) for p in excluded_patterns):
                continue
            
            # Skip binary files
            try:
                if file_path.suffix in ['.pyc', '.so', '.dll', '.exe', '.bin', '.png', '.jpg', '.gif']:
                    continue
            except:
                continue
            
            try:
                findings = self.scan_file(file_path)
                
                for f in findings:
                    if f.is_baseline:
                        baseline_findings.append(f)
                    else:
                        all_findings.append(f)
                
                files_scanned += 1
                
            except Exception as e:
                errors.append(f"{file_path}: {str(e)}")
        
        # Determine if blocked
        critical_count = sum(1 for f in all_findings if f.severity == 'CRITICAL')
        high_count = sum(1 for f in all_findings if f.severity == 'HIGH')
        
        blocked = critical_count > 0 or (self.config.get('block_on_high', True) and high_count > 0)
        
        return {
            'files_scanned': files_scanned,
            'secrets_found': len(all_findings),
            'baseline_count': len(baseline_findings),
            'findings': [f.to_dict() for f in all_findings],
            'baseline_findings': [f.to_dict() for f in baseline_findings],
            'summary': {
                'critical': critical_count,
                'high': high_count,
                'medium': sum(1 for f in all_findings if f.severity == 'MEDIUM'),
                'low': sum(1 for f in all_findings if f.severity == 'LOW')
            },
            'blocked': blocked,
            'errors': errors
        }
    
    def scan_content(self, content: str, source_name: str = "content") -> List[SecretFinding]:
        """
        Scan string content for secrets.
        
        Args:
            content: String content to scan
            source_name: Name to use for source in findings
            
        Returns:
            List of SecretFinding objects
        """
        findings = []
        lines = content.split('\n')
        
        for pattern, name in self.compiled:
            for match in pattern.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                
                finding = SecretFinding(
                    file=source_name,
                    line=line_num,
                    type=name,
                    match=match.group()[:50] + "..." if len(match.group()) > 50 else match.group(),
                    severity=self._get_severity(name),
                    fingerprint=self._compute_match_fingerprint(Path(source_name), match.group(), line_num)
                )
                
                if finding.fingerprint not in self.baseline:
                    findings.append(finding)
        
        return findings
    
    def add_to_baseline(self, finding: SecretFinding) -> None:
        """Add a finding to the baseline."""
        self.baseline[finding.fingerprint] = finding.to_dict()
    
    def _get_severity(self, secret_type: str) -> str:
        """Determine severity for secret type."""
        critical_types = [
            'AWS_ACCESS_KEY', 'AWS_SECRET_KEY', 'PRIVATE_KEY',
            'OPENAI_KEY', 'ANTHROPIC_KEY', 'STRIPE_SECRET_KEY'
        ]
        high_types = [
            'GITHUB_PAT', 'GITHUB_TOKEN', 'API_KEY', 'SECRET_KEY',
            'ACCESS_TOKEN', 'DATABASE_URL', 'SLACK_TOKEN'
        ]
        
        if secret_type in critical_types:
            return 'CRITICAL'
        elif secret_type in high_types:
            return 'HIGH'
        elif 'KEY' in secret_type or 'TOKEN' in secret_type:
            return 'HIGH'
        else:
            return 'MEDIUM'
    
    def _compute_fingerprint(self, finding: Dict) -> str:
        """Compute fingerprint for a finding."""
        content = f"{finding.get('file', '')}:{finding.get('line', 0)}:{finding.get('type', '')}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _compute_match_fingerprint(self, file_path: Path, match: str, line: int) -> str:
        """Compute fingerprint for a match."""
        # Use hash of match + file + line for stable fingerprint
        content = f"{file_path}:{line}:{hashlib.md5(match.encode(), usedforsecurity=False).hexdigest()[:8]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


def run_secret_scan(inputs_dir: Path, config: Dict = None) -> Dict:
    """
    Run secret scan on inputs directory.
    
    This is the main entry point for session-start scanning (ITEM-115 step 03).
    
    Args:
        inputs_dir: Directory to scan
        config: Optional configuration
        
    Returns:
        Scan result dictionary
    """
    scanner = SecretScanner(config=config)
    
    # Check for baseline file
    baseline_path = inputs_dir.parent / '.secrets.baseline'
    
    result = scanner.scan_directory(inputs_dir, baseline_path)
    
    # Log results
    if result['secrets_found'] > 0:
        logging.getLogger(__name__).warning(
            f"[gap: secrets_detected_in_inputs] Found {result['secrets_found']} potential secrets"
        )
    
    return result


def create_baseline_from_findings(findings: List[Dict], output_path: Path) -> bool:
    """
    Create baseline file from findings.
    
    Use this to acknowledge and suppress known secrets.
    
    Args:
        findings: List of finding dictionaries
        output_path: Path to save baseline
        
    Returns:
        True if saved successfully
    """
    scanner = SecretScanner()
    
    for f in findings:
        finding = SecretFinding(
            file=f.get('file', ''),
            line=f.get('line', 0),
            type=f.get('type', ''),
            match=f.get('match', ''),
            severity=f.get('severity', 'MEDIUM'),
            fingerprint=f.get('fingerprint', '')
        )
        scanner.add_to_baseline(finding)
    
    return scanner.save_baseline(output_path)
