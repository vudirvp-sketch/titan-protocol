"""
Diagnostic Rules Engine for TITAN FUSE Protocol.

Implements ITEM-FEAT-103: titan-doctor Diagnostic Rules Engine.

Provides automated diagnostic checks with configurable rules,
auto-fix capabilities, and CLI integration.

Author: TITAN FUSE Team
Version: 4.0.0
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
import json
import os
import shutil


class Severity(str, Enum):
    """Diagnostic severity levels."""
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class DiagnosticRule:
    """
    A single diagnostic rule definition.
    
    Attributes:
        rule_id: Unique identifier for the rule
        name: Human-readable name
        description: Detailed description of what the rule checks
        severity: Severity level (INFO, WARN, ERROR, CRITICAL)
        check: Callable that returns True if check passes, False if issue found
        remediation: Description of how to fix the issue
        auto_fix: Optional callable to automatically fix the issue
        enabled: Whether the rule is active
        tags: Optional tags for categorization
    """
    rule_id: str
    name: str
    description: str
    severity: str  # INFO | WARN | ERROR | CRITICAL
    check: Callable[[], bool]
    remediation: str
    auto_fix: Optional[Callable[[], bool]] = None
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Validate severity is valid."""
        valid_severities = ["INFO", "WARN", "ERROR", "CRITICAL"]
        if self.severity not in valid_severities:
            raise ValueError(f"Invalid severity '{self.severity}'. Must be one of {valid_severities}")


@dataclass
class DoctorDiagnosticResult:
    """
    Result of running a diagnostic rule.
    
    Attributes:
        rule_id: ID of the rule that was run
        passed: True if the check passed (no issue found)
        severity: Severity level of the rule
        message: Human-readable result message
        remediation: Suggested fix if not passed
        auto_fix_available: Whether auto-fix is available
        auto_fix_applied: Whether auto-fix was successfully applied
        timestamp: When the check was run
        details: Additional details about the check
    """
    rule_id: str
    passed: bool
    severity: str
    message: str
    remediation: Optional[str] = None
    auto_fix_available: bool = False
    auto_fix_applied: bool = False
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "rule_id": self.rule_id,
            "passed": self.passed,
            "severity": self.severity,
            "message": self.message,
            "remediation": self.remediation,
            "auto_fix_available": self.auto_fix_available,
            "auto_fix_applied": self.auto_fix_applied,
            "timestamp": self.timestamp,
            "details": self.details
        }
    
    def to_sarif(self) -> Dict:
        """Convert to SARIF format for CI/CD integration."""
        return {
            "ruleId": self.rule_id,
            "level": self.severity.lower() if not self.passed else "none",
            "message": {
                "text": self.message
            },
            "locations": [],
            "fixes": [{
                "description": {"text": self.remediation}
            }] if self.remediation else []
        }


# Aliased for compatibility with requirements
DiagnosticResult = DoctorDiagnosticResult


class DiagnosticRulesEngine:
    """
    Engine for running diagnostic rules with auto-fix capabilities.
    
    Usage:
        engine = DiagnosticRulesEngine()
        engine.load_rules("diagnostics/rules.yaml")
        
        # Run all rules
        results = engine.run_all()
        
        # Run specific rule
        result = engine.run_rule("PROTOCOL_VERSION_MISMATCH")
        
        # Apply auto-fix
        if not result.passed and result.auto_fix_available:
            engine.apply_auto_fix(result)
    """
    
    DEFAULT_RULES_PATH = "diagnostics/rules.yaml"
    
    def __init__(self, repo_root: Optional[Path] = None):
        """
        Initialize the diagnostic rules engine.
        
        Args:
            repo_root: Root directory of the TITAN repository
        """
        self.repo_root = repo_root or Path.cwd()
        self._rules: Dict[str, DiagnosticRule] = {}
        self._logger = logging.getLogger(__name__)
        self._config: Dict[str, Any] = {}
        self._check_functions: Dict[str, Callable[[], bool]] = {}
        self._auto_fix_functions: Dict[str, Callable[[], bool]] = {}
        
        # Initialize built-in check functions
        self._init_builtin_checks()
    
    def _init_builtin_checks(self) -> None:
        """Initialize built-in diagnostic check functions."""
        self._check_functions = {
            "PROTOCOL_VERSION_MISMATCH": self._check_protocol_version,
            "ORPHANED_CHECKPOINT": self._check_orphaned_checkpoint,
            "STALE_LOCK_FILE": self._check_stale_lock,
            "MISSING_DEPENDENCY": self._check_missing_dependency,
            "CONFIG_SCHEMA_INVALID": self._check_config_schema,
            "SECRET_STORE_UNREACHABLE": self._check_secret_store,
            "EVENTBUS_DLQ_FULL": self._check_dlq_status,
            "STORAGE_BACKEND_UNREACHABLE": self._check_storage_backend,
        }
        
        self._auto_fix_functions = {
            "ORPHANED_CHECKPOINT": self._auto_fix_orphaned_checkpoint,
            "STALE_LOCK_FILE": self._auto_fix_stale_lock,
            "EVENTBUS_DLQ_FULL": self._auto_fix_dlq_purge,
        }
    
    def load_rules(self, path: str) -> None:
        """
        Load diagnostic rules from a YAML file.
        
        Args:
            path: Path to the YAML rules file
        """
        rules_path = Path(path)
        
        if not rules_path.is_absolute():
            rules_path = self.repo_root / path
        
        if not rules_path.exists():
            self._logger.warning(f"Rules file not found: {rules_path}, using defaults")
            self._load_default_rules()
            return
        
        try:
            with open(rules_path) as f:
                data = yaml.safe_load(f) or {}
            
            self._config = data.get("config", {})
            
            for rule_data in data.get("rules", []):
                rule_id = rule_data["rule_id"]
                check_fn = self._check_functions.get(rule_id, lambda: True)
                auto_fix_fn = self._auto_fix_functions.get(rule_id)
                
                rule = DiagnosticRule(
                    rule_id=rule_id,
                    name=rule_data.get("name", rule_id),
                    description=rule_data.get("description", ""),
                    severity=rule_data.get("severity", "WARN"),
                    check=check_fn,
                    remediation=rule_data.get("remediation", ""),
                    auto_fix=auto_fix_fn,
                    enabled=rule_data.get("enabled", True),
                    tags=rule_data.get("tags", [])
                )
                self._rules[rule_id] = rule
            
            self._logger.info(f"Loaded {len(self._rules)} diagnostic rules from {rules_path}")
            
        except Exception as e:
            self._logger.error(f"Failed to load rules from {rules_path}: {e}")
            self._load_default_rules()
    
    def _load_default_rules(self) -> None:
        """Load built-in default rules."""
        default_rules = [
            DiagnosticRule(
                rule_id="PROTOCOL_VERSION_MISMATCH",
                name="Protocol Version Mismatch",
                description="Checks if the protocol version in VERSION file matches config",
                severity="WARN",
                check=self._check_protocol_version,
                remediation="Update VERSION file or config.yaml to match expected version",
                tags=["version", "config"]
            ),
            DiagnosticRule(
                rule_id="ORPHANED_CHECKPOINT",
                name="Orphaned Checkpoint",
                description="Detects checkpoint files without active sessions",
                severity="INFO",
                check=self._check_orphaned_checkpoint,
                remediation="Remove orphaned checkpoint files or resume the session",
                auto_fix=self._auto_fix_orphaned_checkpoint,
                tags=["checkpoint", "cleanup"]
            ),
            DiagnosticRule(
                rule_id="STALE_LOCK_FILE",
                name="Stale Lock File",
                description="Detects lock files older than configured TTL",
                severity="WARN",
                check=self._check_stale_lock,
                remediation="Remove stale lock files",
                auto_fix=self._auto_fix_stale_lock,
                tags=["locks", "cleanup"]
            ),
            DiagnosticRule(
                rule_id="MISSING_DEPENDENCY",
                name="Missing Dependency",
                description="Checks for required Python dependencies",
                severity="ERROR",
                check=self._check_missing_dependency,
                remediation="Install missing dependencies: pip install -r requirements.txt",
                tags=["dependencies"]
            ),
            DiagnosticRule(
                rule_id="CONFIG_SCHEMA_INVALID",
                name="Config Schema Invalid",
                description="Validates config.yaml against schema",
                severity="ERROR",
                check=self._check_config_schema,
                remediation="Fix config.yaml validation errors",
                tags=["config", "validation"]
            ),
            DiagnosticRule(
                rule_id="SECRET_STORE_UNREACHABLE",
                name="Secret Store Unreachable",
                description="Checks if the secret store backend is accessible",
                severity="CRITICAL",
                check=self._check_secret_store,
                remediation="Verify secret store configuration and connectivity",
                tags=["security", "secrets"]
            ),
            DiagnosticRule(
                rule_id="EVENTBUS_DLQ_FULL",
                name="EventBus Dead Letter Queue Full",
                description="Checks if DLQ is approaching capacity",
                severity="WARN",
                check=self._check_dlq_status,
                remediation="Purge old DLQ entries or investigate failed events",
                auto_fix=self._auto_fix_dlq_purge,
                tags=["events", "dlq"]
            ),
            DiagnosticRule(
                rule_id="STORAGE_BACKEND_UNREACHABLE",
                name="Storage Backend Unreachable",
                description="Checks if the storage backend is accessible",
                severity="ERROR",
                check=self._check_storage_backend,
                remediation="Verify storage backend configuration and connectivity",
                tags=["storage"]
            ),
        ]
        
        for rule in default_rules:
            self._rules[rule.rule_id] = rule
        
        self._logger.info(f"Loaded {len(self._rules)} default diagnostic rules")
    
    def run_all(self) -> List[DiagnosticResult]:
        """
        Run all loaded diagnostic rules.
        
        Returns:
            List of DiagnosticResult objects for each rule
        """
        results = []
        
        for rule_id, rule in self._rules.items():
            if rule.enabled:
                try:
                    result = self.run_rule(rule_id)
                    results.append(result)
                except Exception as e:
                    self._logger.error(f"Error running rule {rule_id}: {e}")
                    results.append(DiagnosticResult(
                        rule_id=rule_id,
                        passed=False,
                        severity=rule.severity,
                        message=f"Rule execution error: {str(e)}",
                        remediation="Check logs for details"
                    ))
        
        return results
    
    def run_rule(self, rule_id: str) -> DiagnosticResult:
        """
        Run a specific diagnostic rule.
        
        Args:
            rule_id: ID of the rule to run
            
        Returns:
            DiagnosticResult for the rule
            
        Raises:
            ValueError: If rule_id is not found
        """
        if rule_id not in self._rules:
            raise ValueError(f"Rule not found: {rule_id}")
        
        rule = self._rules[rule_id]
        
        if not rule.enabled:
            return DiagnosticResult(
                rule_id=rule_id,
                passed=True,
                severity=rule.severity,
                message="Rule is disabled",
                details={"enabled": False}
            )
        
        try:
            passed = rule.check()
            
            return DiagnosticResult(
                rule_id=rule_id,
                passed=passed,
                severity=rule.severity,
                message=self._get_result_message(rule, passed),
                remediation=None if passed else rule.remediation,
                auto_fix_available=rule.auto_fix is not None,
                details={"rule_name": rule.name, "description": rule.description}
            )
            
        except Exception as e:
            self._logger.error(f"Error executing check for {rule_id}: {e}")
            return DiagnosticResult(
                rule_id=rule_id,
                passed=False,
                severity=rule.severity,
                message=f"Check execution failed: {str(e)}",
                remediation="Check logs for details",
                details={"error": str(e)}
            )
    
    def _get_result_message(self, rule: DiagnosticRule, passed: bool) -> str:
        """Generate result message based on pass/fail status."""
        if passed:
            return f"{rule.name}: OK"
        return f"{rule.name}: Issue detected - {rule.description}"
    
    def suggest_remediation(self, result: DiagnosticResult) -> str:
        """
        Get remediation suggestion for a diagnostic result.
        
        Args:
            result: DiagnosticResult to get remediation for
            
        Returns:
            Remediation suggestion string
        """
        if result.passed:
            return "No remediation needed - check passed"
        
        if result.remediation:
            return result.remediation
        
        rule = self._rules.get(result.rule_id)
        if rule:
            return rule.remediation
        
        return "No remediation available - consult documentation"
    
    def apply_auto_fix(self, result: DiagnosticResult) -> bool:
        """
        Apply automatic fix for a diagnostic result.
        
        Args:
            result: DiagnosticResult to apply fix for
            
        Returns:
            True if fix was applied successfully, False otherwise
        """
        if result.passed:
            self._logger.info(f"No fix needed for {result.rule_id} - check passed")
            return True
        
        if not result.auto_fix_available:
            self._logger.warning(f"No auto-fix available for {result.rule_id}")
            return False
        
        rule = self._rules.get(result.rule_id)
        if not rule or not rule.auto_fix:
            return False
        
        try:
            fixed = rule.auto_fix()
            if fixed:
                self._logger.info(f"Auto-fix applied successfully for {result.rule_id}")
                result.auto_fix_applied = True
            else:
                self._logger.warning(f"Auto-fix failed for {result.rule_id}")
            return fixed
            
        except Exception as e:
            self._logger.error(f"Error applying auto-fix for {result.rule_id}: {e}")
            return False
    
    def get_rule(self, rule_id: str) -> Optional[DiagnosticRule]:
        """Get a specific rule by ID."""
        return self._rules.get(rule_id)
    
    def list_rules(self) -> List[str]:
        """List all loaded rule IDs."""
        return list(self._rules.keys())
    
    def enable_rule(self, rule_id: str) -> None:
        """Enable a specific rule."""
        if rule_id in self._rules:
            self._rules[rule_id].enabled = True
    
    def disable_rule(self, rule_id: str) -> None:
        """Disable a specific rule."""
        if rule_id in self._rules:
            self._rules[rule_id].enabled = False
    
    def get_summary(self, results: List[DiagnosticResult]) -> Dict:
        """
        Get summary statistics from results.
        
        Args:
            results: List of diagnostic results
            
        Returns:
            Dictionary with summary statistics
        """
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        
        by_severity = {}
        for sev in ["INFO", "WARN", "ERROR", "CRITICAL"]:
            by_severity[sev] = {
                "total": sum(1 for r in results if r.severity == sev),
                "passed": sum(1 for r in results if r.severity == sev and r.passed),
                "failed": sum(1 for r in results if r.severity == sev and not r.passed)
            }
        
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / total if total > 0 else 0,
            "by_severity": by_severity,
            "auto_fix_available": sum(1 for r in results if r.auto_fix_available),
            "auto_fix_applied": sum(1 for r in results if r.auto_fix_applied)
        }
    
    # =========================================================================
    # Built-in Check Functions
    # =========================================================================
    
    def _check_protocol_version(self) -> bool:
        """Check if protocol version matches config."""
        version_file = self.repo_root / "VERSION"
        config_file = self.repo_root / "config.yaml"
        
        if not version_file.exists():
            return True  # No version file, skip check
        
        try:
            with open(version_file) as f:
                version = f.read().strip()
            
            with open(config_file) as f:
                config = yaml.safe_load(f) or {}
            
            # Check if version matches metrics schema version
            schema_version = config.get("metrics", {}).get("schema_version", "")
            
            # Major version should match
            if schema_version and version:
                major_file = version.split(".")[0]
                major_schema = schema_version.split(".")[0]
                return major_file == major_schema
            
            return True
            
        except Exception:
            return True  # On error, pass
    
    def _check_orphaned_checkpoint(self) -> bool:
        """Check for orphaned checkpoint files."""
        checkpoint_dir = self.repo_root / "checkpoints"
        
        if not checkpoint_dir.exists():
            return True
        
        # Check for checkpoint files without session
        sessions_dir = self.repo_root / "sessions"
        active_sessions = set()
        
        if sessions_dir.exists():
            for session_file in sessions_dir.glob("*.json"):
                try:
                    with open(session_file) as f:
                        session = json.load(f)
                    active_sessions.add(session.get("id", ""))
                except Exception:
                    pass
        
        # Check checkpoints
        checkpoint_file = checkpoint_dir / "checkpoint.json"
        if checkpoint_file.exists():
            try:
                with open(checkpoint_file) as f:
                    cp = json.load(f)
                session_id = cp.get("session_id", "")
                
                # If no active sessions exist, checkpoint is orphaned
                if not active_sessions:
                    # Check if checkpoint is old (older than max_age_days)
                    max_age = self._config.get("max_checkpoint_age_days", 30)
                    cp_time = datetime.fromisoformat(cp.get("timestamp", "2000-01-01T00:00:00Z").replace("Z", "+00:00"))
                    age = (datetime.utcnow().replace(tzinfo=None) - cp_time.replace(tzinfo=None)).days
                    
                    return age < max_age
                    
            except Exception:
                pass
        
        return True
    
    def _check_stale_lock(self) -> bool:
        """Check for stale lock files."""
        lock_dir = self.repo_root / ".titan" / "locks"
        
        if not lock_dir.exists():
            return True
        
        lock_ttl = self._config.get("lock_ttl_seconds", 300)
        now = datetime.utcnow().timestamp()
        
        for lock_file in lock_dir.glob("*.lock"):
            try:
                # Check file modification time
                mtime = lock_file.stat().st_mtime
                age = now - mtime
                
                if age > lock_ttl:
                    return False  # Stale lock found
                    
            except Exception:
                pass
        
        return True
    
    def _check_missing_dependency(self) -> bool:
        """Check for missing Python dependencies."""
        required_modules = ["yaml", "jsonschema"]
        
        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                return False
        
        return True
    
    def _check_config_schema(self) -> bool:
        """Validate config against schema."""
        config_path = self.repo_root / "config.yaml"
        schema_path = self.repo_root / "schemas" / "config.schema.json"
        
        if not config_path.exists():
            return False
        
        if not schema_path.exists():
            return True  # No schema to validate against
        
        try:
            import jsonschema
            from jsonschema import validate, ValidationError
            
            with open(config_path) as f:
                config = yaml.safe_load(f)
            
            with open(schema_path) as f:
                schema = json.load(f)
            
            validate(instance=config, schema=schema)
            return True
            
        except ImportError:
            return True  # jsonschema not installed
        except Exception:
            return False
    
    def _check_secret_store(self) -> bool:
        """Check if secret store is reachable."""
        config_path = self.repo_root / "config.yaml"
        
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
        except Exception:
            return True
        
        secrets_config = config.get("secrets", {})
        backend = secrets_config.get("backend", "env")
        
        if backend == "env":
            # Environment backend is always reachable
            return True
        
        if backend == "keyring":
            try:
                import keyring
                # Test keyring availability
                keyring.get_keyring()
                return True
            except Exception:
                return False
        
        if backend == "vault":
            # Check if Vault is reachable
            vault_url = secrets_config.get("vault", {}).get("url")
            if vault_url:
                try:
                    import requests
                    response = requests.get(f"{vault_url}/v1/sys/health", timeout=5)
                    return response.status_code in (200, 429, 472, 473)
                except Exception:
                    return False
        
        return True
    
    def _check_dlq_status(self) -> bool:
        """Check dead letter queue status."""
        dlq_path = self.repo_root / ".titan" / "dlq"
        
        if not dlq_path.exists():
            return True
        
        max_size = self._config.get("dlq_max_size", 10000)
        warning_threshold = self._config.get("dlq_warning_threshold", 0.8)
        
        # Count entries
        entry_count = 0
        for dlq_file in dlq_path.glob("*.json"):
            try:
                with open(dlq_file) as f:
                    data = json.load(f)
                entry_count += len(data.get("events", []))
            except Exception:
                pass
        
        return entry_count < (max_size * warning_threshold)
    
    def _check_storage_backend(self) -> bool:
        """Check if storage backend is reachable."""
        config_path = self.repo_root / "config.yaml"
        
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
        except Exception:
            return True
        
        storage_config = config.get("storage", {})
        backend = storage_config.get("backend", "local")
        
        if backend == "local":
            base_path = storage_config.get("local", {}).get("base_path", ".titan/storage")
            storage_path = self.repo_root / base_path
            
            if storage_config.get("local", {}).get("create_dirs", True):
                storage_path.mkdir(parents=True, exist_ok=True)
            
            return storage_path.exists()
        
        if backend == "s3":
            try:
                import boto3
                bucket = storage_config.get("s3", {}).get("bucket")
                if bucket:
                    s3 = boto3.client("s3")
                    s3.head_bucket(Bucket=bucket)
                    return True
            except Exception:
                return False
        
        if backend == "gcs":
            try:
                from google.cloud import storage
                bucket = storage_config.get("gcs", {}).get("bucket")
                if bucket:
                    client = storage.Client()
                    client.get_bucket(bucket)
                    return True
            except Exception:
                return False
        
        return True
    
    # =========================================================================
    # Auto-Fix Functions
    # =========================================================================
    
    def _auto_fix_orphaned_checkpoint(self) -> bool:
        """Remove orphaned checkpoint files."""
        checkpoint_file = self.repo_root / "checkpoints" / "checkpoint.json"
        
        if checkpoint_file.exists():
            try:
                # Archive instead of delete
                archive_dir = self.repo_root / "checkpoints" / "archive"
                archive_dir.mkdir(parents=True, exist_ok=True)
                
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                archive_path = archive_dir / f"checkpoint_{timestamp}.json"
                
                shutil.move(str(checkpoint_file), str(archive_path))
                self._logger.info(f"Archived orphaned checkpoint to {archive_path}")
                return True
                
            except Exception as e:
                self._logger.error(f"Failed to archive checkpoint: {e}")
                return False
        
        return True
    
    def _auto_fix_stale_lock(self) -> bool:
        """Remove stale lock files."""
        lock_dir = self.repo_root / ".titan" / "locks"
        
        if not lock_dir.exists():
            return True
        
        lock_ttl = self._config.get("lock_ttl_seconds", 300)
        now = datetime.utcnow().timestamp()
        removed = 0
        
        for lock_file in lock_dir.glob("*.lock"):
            try:
                mtime = lock_file.stat().st_mtime
                age = now - mtime
                
                if age > lock_ttl:
                    lock_file.unlink()
                    removed += 1
                    
            except Exception:
                pass
        
        self._logger.info(f"Removed {removed} stale lock files")
        return True
    
    def _auto_fix_dlq_purge(self) -> bool:
        """Purge old entries from dead letter queue."""
        dlq_path = self.repo_root / ".titan" / "dlq"
        
        if not dlq_path.exists():
            return True
        
        max_age_hours = self._config.get("dlq_max_age_hours", 72)
        purged = 0
        
        for dlq_file in dlq_path.glob("*.json"):
            try:
                with open(dlq_file) as f:
                    data = json.load(f)
                
                # Filter old events
                cutoff = datetime.utcnow().timestamp() - (max_age_hours * 3600)
                
                if "events" in data:
                    original_count = len(data["events"])
                    data["events"] = [
                        e for e in data["events"]
                        if datetime.fromisoformat(e.get("timestamp", "2000-01-01T00:00:00Z").replace("Z", "+00:00")).timestamp() > cutoff
                    ]
                    purged += original_count - len(data["events"])
                    
                    with open(dlq_file, 'w') as f:
                        json.dump(data, f)
                        
            except Exception:
                pass
        
        self._logger.info(f"Purged {purged} old DLQ entries")
        return True


# =============================================================================
# CLI Integration Helpers
# =============================================================================

def run_doctor_command(
    repo_root: Optional[Path] = None,
    fix: bool = False,
    rule_id: Optional[str] = None,
    output_format: str = "json"
) -> Dict:
    """
    Run the doctor command from CLI.
    
    Args:
        repo_root: Repository root directory
        fix: Apply auto-fixes where available
        rule_id: Run specific rule only (None for all)
        output_format: Output format (json, text, markdown)
        
    Returns:
        Dictionary with results
    """
    engine = DiagnosticRulesEngine(repo_root=repo_root)
    engine.load_rules(DiagnosticRulesEngine.DEFAULT_RULES_PATH)
    
    if rule_id:
        try:
            result = engine.run_rule(rule_id)
            results = [result]
        except ValueError as e:
            return {
                "success": False,
                "error": str(e),
                "results": []
            }
    else:
        results = engine.run_all()
    
    # Apply auto-fixes if requested
    if fix:
        for result in results:
            if not result.passed and result.auto_fix_available:
                engine.apply_auto_fix(result)
    
    summary = engine.get_summary(results)
    
    return {
        "success": summary["failed"] == 0,
        "results": [r.to_dict() for r in results],
        "summary": summary
    }
