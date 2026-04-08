"""
Tests for Sandbox Health Checker (ITEM-VAL-65).
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import subprocess

from src.validation.sandbox_health import (
    SandboxHealthChecker,
    SandboxType,
    HealthStatus,
    HealthReport,
    create_health_checker
)


class TestHealthStatus:
    """Tests for HealthStatus enum."""
    
    def test_status_values(self):
        """Test that all status values exist."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"
        assert HealthStatus.TIMEOUT.value == "timeout"


class TestHealthReport:
    """Tests for HealthReport dataclass."""
    
    def test_report_creation(self):
        """Test creating a health report."""
        report = HealthReport(
            sandbox_type=SandboxType.DOCKER,
            status=HealthStatus.HEALTHY,
            message="Docker is healthy"
        )
        
        assert report.sandbox_type == SandboxType.DOCKER
        assert report.status == HealthStatus.HEALTHY
        assert report.message == "Docker is healthy"
        assert report.is_healthy is True
    
    def test_report_to_dict(self):
        """Test converting report to dictionary."""
        report = HealthReport(
            sandbox_type=SandboxType.DOCKER,
            status=HealthStatus.UNHEALTHY,
            message="Docker not running",
            latency_ms=150,
            recommendations=["Start Docker"]
        )
        
        data = report.to_dict()
        
        assert data["sandbox_type"] == "docker"
        assert data["status"] == "unhealthy"
        assert data["message"] == "Docker not running"
        assert data["latency_ms"] == 150
        assert "Start Docker" in data["recommendations"]
    
    def test_is_healthy_property(self):
        """Test is_healthy property."""
        healthy_report = HealthReport(
            sandbox_type=SandboxType.DOCKER,
            status=HealthStatus.HEALTHY,
            message="OK"
        )
        assert healthy_report.is_healthy is True
        
        unhealthy_report = HealthReport(
            sandbox_type=SandboxType.DOCKER,
            status=HealthStatus.UNHEALTHY,
            message="Not OK"
        )
        assert unhealthy_report.is_healthy is False


class TestSandboxHealthChecker:
    """Tests for SandboxHealthChecker class."""
    
    def test_initialization(self):
        """Test checker initialization."""
        checker = SandboxHealthChecker()
        
        assert checker._health_check_enabled is True
        assert checker._unhealthy_action == "block"
    
    def test_initialization_with_config(self):
        """Test checker initialization with config."""
        config = {
            "sandbox": {
                "health_check": False,
                "unhealthy_action": "warn"
            }
        }
        
        checker = SandboxHealthChecker(config)
        
        assert checker._health_check_enabled is False
        assert checker._unhealthy_action == "warn"
    
    @patch('subprocess.run')
    def test_check_docker_healthy(self, mock_run):
        """Test Docker health check when Docker is healthy."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Docker version 24.0.0\n"
        )
        
        checker = SandboxHealthChecker()
        report = checker.check_docker()
        
        assert report.status == HealthStatus.HEALTHY
        assert "healthy" in report.message.lower()
    
    @patch('subprocess.run')
    def test_check_docker_not_installed(self, mock_run):
        """Test Docker health check when Docker is not installed."""
        mock_run.side_effect = FileNotFoundError("docker not found")
        
        checker = SandboxHealthChecker()
        report = checker.check_docker()
        
        assert report.status == HealthStatus.UNHEALTHY
        assert "not installed" in report.message.lower()
    
    @patch('subprocess.run')
    def test_check_docker_timeout(self, mock_run):
        """Test Docker health check timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("docker", 5)
        
        checker = SandboxHealthChecker()
        report = checker.check_docker()
        
        assert report.status == HealthStatus.TIMEOUT
    
    def test_check_restricted_subprocess(self):
        """Test restricted subprocess health check (always available)."""
        checker = SandboxHealthChecker()
        report = checker.check_restricted_subprocess()
        
        assert report.status == HealthStatus.HEALTHY
        assert "available" in report.message.lower()
    
    def test_verify_isolation_with_configured_type(self):
        """Test verify_isolation with configured sandbox type."""
        config = {
            "security": {
                "sandbox_type": "restricted_subprocess"
            }
        }
        
        checker = SandboxHealthChecker(config)
        report = checker.verify_isolation()
        
        assert report.sandbox_type == SandboxType.RESTRICTED_SUBPROCESS
        assert report.is_healthy is True
    
    def test_verify_isolation_no_config(self):
        """Test verify_isolation with no sandbox configured."""
        checker = SandboxHealthChecker()
        report = checker.verify_isolation()
        
        assert report.sandbox_type == SandboxType.NONE
        assert report.status == HealthStatus.UNHEALTHY
    
    def test_should_block_execution_healthy(self):
        """Test should_block_execution with healthy report."""
        checker = SandboxHealthChecker()
        
        report = HealthReport(
            sandbox_type=SandboxType.DOCKER,
            status=HealthStatus.HEALTHY,
            message="OK"
        )
        
        assert checker.should_block_execution(report) is False
    
    def test_should_block_execution_unhealthy_block(self):
        """Test should_block_execution with unhealthy report in block mode."""
        config = {"sandbox": {"unhealthy_action": "block"}}
        checker = SandboxHealthChecker(config)
        
        report = HealthReport(
            sandbox_type=SandboxType.DOCKER,
            status=HealthStatus.UNHEALTHY,
            message="Failed"
        )
        
        assert checker.should_block_execution(report) is True
    
    def test_should_block_execution_unhealthy_warn(self):
        """Test should_block_execution with unhealthy report in warn mode."""
        config = {"sandbox": {"unhealthy_action": "warn"}}
        checker = SandboxHealthChecker(config)
        
        report = HealthReport(
            sandbox_type=SandboxType.DOCKER,
            status=HealthStatus.UNHEALTHY,
            message="Failed"
        )
        
        assert checker.should_block_execution(report) is False
    
    def test_cache(self):
        """Test health check caching."""
        checker = SandboxHealthChecker()
        
        # First check - will run actual check
        report1 = checker.check_restricted_subprocess()
        
        # Second check - should return cached result (same object or same timestamp)
        report2 = checker.check_restricted_subprocess()
        
        # Verify caching by checking the object is the same or timestamp is within cache TTL
        assert report1.status == report2.status
        assert report1.message == report2.message
        # Check that second call returned the cached report
        assert report1 is report2 or report1.checked_at == report2.checked_at
    
    def test_clear_cache(self):
        """Test clearing the cache."""
        checker = SandboxHealthChecker()
        
        checker.check_restricted_subprocess()
        assert len(checker._cache) > 0
        
        checker.clear_cache()
        assert len(checker._cache) == 0
    
    def test_get_stats(self):
        """Test getting statistics."""
        checker = SandboxHealthChecker()
        stats = checker.get_stats()
        
        assert "health_check_enabled" in stats
        assert "unhealthy_action" in stats
        assert "cached_types" in stats
    
    def test_set_event_bus(self):
        """Test setting event bus."""
        checker = SandboxHealthChecker()
        mock_bus = Mock()
        
        checker.set_event_bus(mock_bus)
        
        assert checker._event_bus == mock_bus


class TestFactoryFunction:
    """Tests for factory function."""
    
    def test_create_health_checker_default(self):
        """Test creating health checker with defaults."""
        checker = create_health_checker()
        
        assert isinstance(checker, SandboxHealthChecker)
    
    def test_create_health_checker_with_config(self):
        """Test creating health checker with config."""
        config = {"sandbox": {"unhealthy_action": "warn"}}
        checker = create_health_checker(config)
        
        assert checker._unhealthy_action == "warn"
    
    def test_create_health_checker_with_event_bus(self):
        """Test creating health checker with event bus."""
        mock_bus = Mock()
        checker = create_health_checker(event_bus=mock_bus)
        
        assert checker._event_bus == mock_bus
