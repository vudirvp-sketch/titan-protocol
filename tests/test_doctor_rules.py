"""
Tests for Diagnostic Rules Engine.

ITEM-FEAT-103: titan-doctor Diagnostic Rules Engine

Tests cover:
- DiagnosticRule dataclass
- DiagnosticRulesEngine functionality
- Auto-fix capabilities
- CLI integration
"""

import pytest
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from diagnostics.doctor_rules import (
    DiagnosticRule,
    DiagnosticRulesEngine,
    DoctorDiagnosticResult,
    Severity,
    run_doctor_command
)


class TestDiagnosticRule:
    """Tests for DiagnosticRule dataclass."""
    
    def test_create_diagnostic_rule(self):
        """Test creating a diagnostic rule."""
        rule = DiagnosticRule(
            rule_id="TEST_RULE",
            name="Test Rule",
            description="A test diagnostic rule",
            severity="WARN",
            check=lambda: True,
            remediation="Fix the test issue",
            tags=["test"]
        )
        
        assert rule.rule_id == "TEST_RULE"
        assert rule.name == "Test Rule"
        assert rule.severity == "WARN"
        assert rule.enabled is True
        assert rule.auto_fix is None
        assert "test" in rule.tags
    
    def test_invalid_severity_raises_error(self):
        """Test that invalid severity raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            DiagnosticRule(
                rule_id="BAD_SEVERITY",
                name="Bad Rule",
                description="Invalid severity",
                severity="INVALID",
                check=lambda: True,
                remediation="Fix"
            )
        
        assert "Invalid severity" in str(exc_info.value)
    
    def test_valid_severities(self):
        """Test all valid severity levels."""
        for severity in ["INFO", "WARN", "ERROR", "CRITICAL"]:
            rule = DiagnosticRule(
                rule_id=f"RULE_{severity}",
                name=f"Rule {severity}",
                description="Test",
                severity=severity,
                check=lambda: True,
                remediation="Fix"
            )
            assert rule.severity == severity
    
    def test_rule_with_auto_fix(self):
        """Test rule with auto-fix function."""
        fix_called = []
        
        def auto_fix():
            fix_called.append(True)
            return True
        
        rule = DiagnosticRule(
            rule_id="AUTO_FIXABLE",
            name="Auto Fixable",
            description="Can be auto-fixed",
            severity="WARN",
            check=lambda: False,
            remediation="Fix",
            auto_fix=auto_fix
        )
        
        assert rule.auto_fix is not None
        result = rule.auto_fix()
        assert result is True
        assert len(fix_called) == 1


class TestDiagnosticResult:
    """Tests for DoctorDiagnosticResult dataclass."""
    
    def test_create_passed_result(self):
        """Test creating a passed result."""
        result = DoctorDiagnosticResult(
            rule_id="TEST_RULE",
            passed=True,
            severity="INFO",
            message="Check passed"
        )
        
        assert result.passed is True
        assert result.remediation is None
        assert result.auto_fix_available is False
        assert result.auto_fix_applied is False
    
    def test_create_failed_result(self):
        """Test creating a failed result."""
        result = DoctorDiagnosticResult(
            rule_id="TEST_RULE",
            passed=False,
            severity="ERROR",
            message="Check failed",
            remediation="Fix the issue",
            auto_fix_available=True
        )
        
        assert result.passed is False
        assert result.remediation == "Fix the issue"
        assert result.auto_fix_available is True
    
    def test_to_dict(self):
        """Test converting result to dictionary."""
        result = DoctorDiagnosticResult(
            rule_id="TEST_RULE",
            passed=False,
            severity="WARN",
            message="Test message",
            remediation="Test fix"
        )
        
        d = result.to_dict()
        
        assert d["rule_id"] == "TEST_RULE"
        assert d["passed"] is False
        assert d["severity"] == "WARN"
        assert d["message"] == "Test message"
        assert d["remediation"] == "Test fix"
        assert "timestamp" in d
    
    def test_to_sarif(self):
        """Test converting result to SARIF format."""
        result = DoctorDiagnosticResult(
            rule_id="SARIF_TEST",
            passed=False,
            severity="ERROR",
            message="SARIF test message",
            remediation="Fix for SARIF"
        )
        
        sarif = result.to_sarif()
        
        assert sarif["ruleId"] == "SARIF_TEST"
        assert sarif["level"] == "error"
        assert sarif["message"]["text"] == "SARIF test message"
        assert len(sarif["fixes"]) == 1
        assert sarif["fixes"][0]["description"]["text"] == "Fix for SARIF"
    
    def test_to_sarif_passed(self):
        """Test SARIF output for passed result."""
        result = DoctorDiagnosticResult(
            rule_id="PASS_TEST",
            passed=True,
            severity="INFO",
            message="Passed"
        )
        
        sarif = result.to_sarif()
        
        assert sarif["level"] == "none"


class TestDiagnosticRulesEngine:
    """Tests for DiagnosticRulesEngine."""
    
    @pytest.fixture
    def temp_repo(self, tmp_path):
        """Create a temporary repository structure."""
        repo = tmp_path / "test_repo"
        repo.mkdir()
        
        # Create required directories
        (repo / "checkpoints").mkdir()
        (repo / "sessions").mkdir()
        (repo / ".titan" / "locks").mkdir(parents=True)
        (repo / ".titan" / "dlq").mkdir(parents=True)
        (repo / "schemas").mkdir(parents=True)
        
        # Create VERSION file
        (repo / "VERSION").write_text("4.0.0\n")
        
        # Create minimal config.yaml
        config = {
            "metrics": {"schema_version": "3.4.0"},
            "secrets": {"backend": "env"},
            "storage": {"backend": "local", "local": {"base_path": ".titan/storage"}}
        }
        with open(repo / "config.yaml", "w") as f:
            import yaml
            yaml.dump(config, f)
        
        return repo
    
    def test_engine_initialization(self, temp_repo):
        """Test engine initialization."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        assert engine.repo_root == temp_repo
        assert len(engine._rules) == 0  # No rules loaded yet
    
    def test_load_default_rules(self, temp_repo):
        """Test loading default rules."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine._load_default_rules()
        
        rules = engine.list_rules()
        
        assert "PROTOCOL_VERSION_MISMATCH" in rules
        assert "ORPHANED_CHECKPOINT" in rules
        assert "STALE_LOCK_FILE" in rules
        assert "MISSING_DEPENDENCY" in rules
        assert "CONFIG_SCHEMA_INVALID" in rules
        assert "SECRET_STORE_UNREACHABLE" in rules
        assert "EVENTBUS_DLQ_FULL" in rules
        assert "STORAGE_BACKEND_UNREACHABLE" in rules
    
    def test_load_rules_from_yaml(self, temp_repo):
        """Test loading rules from YAML file."""
        # Create a custom rules file
        rules_file = temp_repo / "custom_rules.yaml"
        rules_content = {
            "config": {"lock_ttl_seconds": 600},
            "rules": [
                {
                    "rule_id": "CUSTOM_RULE",
                    "name": "Custom Rule",
                    "description": "A custom rule",
                    "severity": "INFO",
                    "remediation": "Fix custom issue"
                }
            ]
        }
        import yaml
        with open(rules_file, "w") as f:
            yaml.dump(rules_content, f)
        
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine.load_rules(str(rules_file))
        
        assert "CUSTOM_RULE" in engine.list_rules()
        assert engine._config.get("lock_ttl_seconds") == 600
    
    def test_load_rules_missing_file(self, temp_repo):
        """Test loading rules from missing file falls back to defaults."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine.load_rules("nonexistent.yaml")
        
        # Should load default rules
        assert len(engine.list_rules()) > 0
    
    def test_run_all_rules(self, temp_repo):
        """Test running all rules."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine._load_default_rules()
        
        results = engine.run_all()
        
        assert len(results) == 8  # 8 default rules
        for result in results:
            assert isinstance(result, DoctorDiagnosticResult)
            assert result.rule_id in engine.list_rules()
    
    def test_run_specific_rule(self, temp_repo):
        """Test running a specific rule."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine._load_default_rules()
        
        result = engine.run_rule("MISSING_DEPENDENCY")
        
        assert result.rule_id == "MISSING_DEPENDENCY"
        assert result.passed is True  # yaml and jsonschema should be installed
    
    def test_run_nonexistent_rule(self, temp_repo):
        """Test running a nonexistent rule raises error."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine._load_default_rules()
        
        with pytest.raises(ValueError) as exc_info:
            engine.run_rule("NONEXISTENT_RULE")
        
        assert "Rule not found" in str(exc_info.value)
    
    def test_suggest_remediation_passed(self, temp_repo):
        """Test remediation suggestion for passed result."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = DoctorDiagnosticResult(
            rule_id="TEST",
            passed=True,
            severity="INFO",
            message="Passed"
        )
        
        suggestion = engine.suggest_remediation(result)
        
        assert "No remediation needed" in suggestion
    
    def test_suggest_remediation_failed(self, temp_repo):
        """Test remediation suggestion for failed result."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine._load_default_rules()
        
        result = DoctorDiagnosticResult(
            rule_id="MISSING_DEPENDENCY",
            passed=False,
            severity="ERROR",
            message="Missing dependency",
            remediation="Install the dependency"
        )
        
        suggestion = engine.suggest_remediation(result)
        
        assert "Install" in suggestion
    
    def test_apply_auto_fix_success(self, temp_repo):
        """Test successful auto-fix application."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine._load_default_rules()
        
        # Create a stale lock file
        lock_dir = temp_repo / ".titan" / "locks"
        lock_file = lock_dir / "test.lock"
        lock_file.write_text("{}")
        
        # Set old modification time
        import os
        old_time = datetime.now().timestamp() - 600  # 10 minutes ago
        os.utime(lock_file, (old_time, old_time))
        
        result = DoctorDiagnosticResult(
            rule_id="STALE_LOCK_FILE",
            passed=False,
            severity="WARN",
            message="Stale lock found",
            auto_fix_available=True
        )
        
        fixed = engine.apply_auto_fix(result)
        
        assert fixed is True
        assert result.auto_fix_applied is True
    
    def test_apply_auto_fix_not_available(self, temp_repo):
        """Test auto-fix when not available."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = DoctorDiagnosticResult(
            rule_id="NO_AUTO_FIX",
            passed=False,
            severity="ERROR",
            message="No auto-fix",
            auto_fix_available=False
        )
        
        fixed = engine.apply_auto_fix(result)
        
        assert fixed is False
    
    def test_enable_disable_rule(self, temp_repo):
        """Test enabling and disabling rules."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine._load_default_rules()
        
        engine.disable_rule("MISSING_DEPENDENCY")
        assert engine.get_rule("MISSING_DEPENDENCY").enabled is False
        
        engine.enable_rule("MISSING_DEPENDENCY")
        assert engine.get_rule("MISSING_DEPENDENCY").enabled is True
    
    def test_get_summary(self, temp_repo):
        """Test getting results summary."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        results = [
            DoctorDiagnosticResult("R1", True, "INFO", "OK"),
            DoctorDiagnosticResult("R2", False, "WARN", "Issue", auto_fix_available=True),
            DoctorDiagnosticResult("R3", False, "ERROR", "Error"),
        ]
        
        summary = engine.get_summary(results)
        
        assert summary["total"] == 3
        assert summary["passed"] == 1
        assert summary["failed"] == 2
        assert summary["pass_rate"] == pytest.approx(1/3, rel=0.01)
        assert summary["auto_fix_available"] == 1


class TestBuiltInChecks:
    """Tests for built-in diagnostic checks."""
    
    @pytest.fixture
    def temp_repo(self, tmp_path):
        """Create a temporary repository structure."""
        repo = tmp_path / "test_repo"
        repo.mkdir()
        (repo / "checkpoints").mkdir()
        (repo / "sessions").mkdir()
        (repo / ".titan" / "locks").mkdir(parents=True)
        (repo / ".titan" / "dlq").mkdir(parents=True)
        (repo / "schemas").mkdir(parents=True)
        (repo / "VERSION").write_text("4.0.0\n")
        
        config = {
            "metrics": {"schema_version": "4.0.0"},
            "secrets": {"backend": "env"},
            "storage": {"backend": "local", "local": {"base_path": ".titan/storage", "create_dirs": True}}
        }
        import yaml
        with open(repo / "config.yaml", "w") as f:
            yaml.dump(config, f)
        
        return repo
    
    def test_check_protocol_version_match(self, temp_repo):
        """Test protocol version check when versions match."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._check_protocol_version()
        
        assert result is True
    
    def test_check_protocol_version_mismatch(self, temp_repo):
        """Test protocol version check when versions don't match."""
        # Change VERSION to different major
        (temp_repo / "VERSION").write_text("3.0.0\n")
        
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._check_protocol_version()
        
        assert result is False
    
    def test_check_orphaned_checkpoint_no_checkpoint(self, temp_repo):
        """Test orphaned checkpoint check when no checkpoint exists."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._check_orphaned_checkpoint()
        
        assert result is True  # No checkpoint = pass
    
    def test_check_orphaned_checkpoint_with_session(self, temp_repo):
        """Test orphaned checkpoint check with active session."""
        # Create checkpoint and session
        checkpoint = {"session_id": "test-session-123", "timestamp": datetime.utcnow().isoformat() + "Z"}
        with open(temp_repo / "checkpoints" / "checkpoint.json", "w") as f:
            json.dump(checkpoint, f)
        
        session = {"id": "test-session-123", "status": "active"}
        with open(temp_repo / "sessions" / "current.json", "w") as f:
            json.dump(session, f)
        
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._check_orphaned_checkpoint()
        
        # Should pass since session exists
        assert result is True
    
    def test_check_stale_lock_no_locks(self, temp_repo):
        """Test stale lock check when no locks exist."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._check_stale_lock()
        
        assert result is True
    
    def test_check_stale_lock_fresh_lock(self, temp_repo):
        """Test stale lock check with fresh lock."""
        lock_file = temp_repo / ".titan" / "locks" / "test.lock"
        lock_file.write_text("{}")
        
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._check_stale_lock()
        
        assert result is True  # Fresh lock passes
    
    def test_check_stale_lock_stale(self, temp_repo):
        """Test stale lock check with stale lock."""
        import os
        lock_file = temp_repo / ".titan" / "locks" / "stale.lock"
        lock_file.write_text("{}")
        
        # Set old modification time
        old_time = datetime.now().timestamp() - 600  # 10 minutes ago
        os.utime(lock_file, (old_time, old_time))
        
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine._config["lock_ttl_seconds"] = 300  # 5 minutes
        
        result = engine._check_stale_lock()
        
        assert result is False  # Stale lock fails
    
    def test_check_missing_dependency_installed(self, temp_repo):
        """Test missing dependency check when all installed."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._check_missing_dependency()
        
        assert result is True  # yaml and jsonschema should be installed
    
    def test_check_config_schema_valid(self, temp_repo):
        """Test config schema check with valid config."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._check_config_schema()
        
        # No schema file = pass (graceful degradation)
        assert result is True
    
    def test_check_secret_store_env(self, temp_repo):
        """Test secret store check with env backend."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._check_secret_store()
        
        assert result is True  # env backend is always reachable
    
    def test_check_dlq_empty(self, temp_repo):
        """Test DLQ check when empty."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._check_dlq_status()
        
        assert result is True
    
    def test_check_dlq_nearly_full(self, temp_repo):
        """Test DLQ check when nearly full."""
        dlq_file = temp_repo / ".titan" / "dlq" / "events.json"
        events = {"events": [{"id": i, "timestamp": datetime.utcnow().isoformat() + "Z"} for i in range(8500)]}
        with open(dlq_file, "w") as f:
            json.dump(events, f)
        
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine._config["dlq_max_size"] = 10000
        engine._config["dlq_warning_threshold"] = 0.8
        
        result = engine._check_dlq_status()
        
        assert result is False  # Over 80% threshold
    
    def test_check_storage_backend_local(self, temp_repo):
        """Test storage backend check for local storage."""
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._check_storage_backend()
        
        assert result is True  # Local storage creates dirs


class TestRunDoctorCommand:
    """Tests for CLI command helper."""
    
    @pytest.fixture
    def temp_repo(self, tmp_path):
        """Create a temporary repository structure."""
        repo = tmp_path / "test_repo"
        repo.mkdir()
        (repo / "checkpoints").mkdir()
        (repo / ".titan" / "locks").mkdir(parents=True)
        (repo / "VERSION").write_text("4.0.0\n")
        
        import yaml
        config = {"storage": {"backend": "local"}}
        with open(repo / "config.yaml", "w") as f:
            yaml.dump(config, f)
        
        return repo
    
    def test_run_doctor_all_rules(self, temp_repo):
        """Test running doctor with all rules."""
        result = run_doctor_command(repo_root=temp_repo)
        
        assert "results" in result
        assert "summary" in result
        assert len(result["results"]) == 8
    
    def test_run_doctor_specific_rule(self, temp_repo):
        """Test running doctor with specific rule."""
        result = run_doctor_command(
            repo_root=temp_repo,
            rule_id="MISSING_DEPENDENCY"
        )
        
        assert len(result["results"]) == 1
        assert result["results"][0]["rule_id"] == "MISSING_DEPENDENCY"
    
    def test_run_doctor_invalid_rule(self, temp_repo):
        """Test running doctor with invalid rule ID."""
        result = run_doctor_command(
            repo_root=temp_repo,
            rule_id="INVALID_RULE"
        )
        
        assert result["success"] is False
        assert "error" in result
    
    def test_run_doctor_with_fix(self, temp_repo):
        """Test running doctor with auto-fix enabled."""
        # Create a stale lock
        import os
        lock_dir = temp_repo / ".titan" / "locks"
        lock_file = lock_dir / "stale.lock"
        lock_file.write_text("{}")
        old_time = datetime.now().timestamp() - 600
        os.utime(lock_file, (old_time, old_time))
        
        result = run_doctor_command(
            repo_root=temp_repo,
            fix=True,
            rule_id="STALE_LOCK_FILE"
        )
        
        # Lock should be removed
        assert not lock_file.exists()


class TestAutoFixFunctions:
    """Tests for auto-fix functions."""
    
    @pytest.fixture
    def temp_repo(self, tmp_path):
        """Create a temporary repository structure."""
        repo = tmp_path / "test_repo"
        repo.mkdir()
        (repo / "checkpoints" / "archive").mkdir(parents=True)
        (repo / ".titan" / "locks").mkdir(parents=True)
        (repo / ".titan" / "dlq").mkdir(parents=True)
        return repo
    
    def test_auto_fix_orphaned_checkpoint(self, temp_repo):
        """Test auto-fix for orphaned checkpoint."""
        checkpoint_file = temp_repo / "checkpoints" / "checkpoint.json"
        checkpoint_file.write_text('{"session_id": "old-session"}')
        
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        
        result = engine._auto_fix_orphaned_checkpoint()
        
        assert result is True
        assert not checkpoint_file.exists()
        
        # Check archive
        archive_dir = temp_repo / "checkpoints" / "archive"
        assert len(list(archive_dir.glob("*.json"))) == 1
    
    def test_auto_fix_stale_lock(self, temp_repo):
        """Test auto-fix for stale lock."""
        import os
        lock_file = temp_repo / ".titan" / "locks" / "stale.lock"
        lock_file.write_text("{}")
        old_time = datetime.now().timestamp() - 600
        os.utime(lock_file, (old_time, old_time))
        
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine._config["lock_ttl_seconds"] = 300
        
        result = engine._auto_fix_stale_lock()
        
        assert result is True
        assert not lock_file.exists()
    
    def test_auto_fix_dlq_purge(self, temp_repo):
        """Test auto-fix for DLQ purge."""
        dlq_file = temp_repo / ".titan" / "dlq" / "events.json"
        
        # Create old and new events
        old_time = (datetime.utcnow() - timedelta(hours=100)).isoformat() + "Z"
        new_time = datetime.utcnow().isoformat() + "Z"
        
        events = {
            "events": [
                {"id": "old", "timestamp": old_time},
                {"id": "new", "timestamp": new_time}
            ]
        }
        with open(dlq_file, "w") as f:
            json.dump(events, f)
        
        engine = DiagnosticRulesEngine(repo_root=temp_repo)
        engine._config["dlq_max_age_hours"] = 72
        
        result = engine._auto_fix_dlq_purge()
        
        assert result is True
        
        # Check only new event remains
        with open(dlq_file) as f:
            data = json.load(f)
        
        assert len(data["events"]) == 1
        assert data["events"][0]["id"] == "new"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
