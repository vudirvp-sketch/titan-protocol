"""
Sandbox Health Checker for TITAN FUSE Protocol.

ITEM-VAL-65: Runtime sandbox health verification.

Verifies that Docker, gVisor, or WASM runtime is actually functional
before code execution. This prevents silent failures when sandbox
is assumed active but not actually working.

Integration:
- ExecutionGate: check_health() before EXECUTE event
- EventBus: emits SANDBOX_UNHEALTHY if check fails

Author: TITAN FUSE Team
Version: 4.1.0
"""

import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, TYPE_CHECKING
import logging
import os
import tempfile

if TYPE_CHECKING:
    from ..events.event_bus import EventBus


class SandboxType(Enum):
    """Supported sandbox types."""
    DOCKER = "docker"
    GVISOOR = "gvisor"
    WASM = "wasm"
    VENV = "venv"
    RESTRICTED_SUBPROCESS = "restricted_subprocess"
    NONE = "none"


class HealthStatus(Enum):
    """Health check result status."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"


@dataclass
class HealthReport:
    """
    Result of a sandbox health check.
    
    Attributes:
        sandbox_type: Type of sandbox checked
        status: Health status
        message: Human-readable message
        checked_at: Timestamp of check
        latency_ms: Time taken for check
        details: Additional details about the check
        recommendations: List of recommendations if unhealthy
    """
    sandbox_type: SandboxType
    status: HealthStatus
    message: str
    checked_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    latency_ms: int = 0
    details: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "sandbox_type": self.sandbox_type.value,
            "status": self.status.value,
            "message": self.message,
            "checked_at": self.checked_at,
            "latency_ms": self.latency_ms,
            "details": self.details,
            "recommendations": self.recommendations
        }
    
    @property
    def is_healthy(self) -> bool:
        """Returns True if sandbox is healthy."""
        return self.status == HealthStatus.HEALTHY


class SandboxHealthChecker:
    """
    ITEM-VAL-65: Verify sandbox health before code execution.
    
    This checker verifies that the configured sandbox environment is
    actually functional, not just assumed to be. It performs runtime
    tests to ensure isolation is working correctly.
    
    Usage:
        checker = SandboxHealthChecker(config)
        
        # Check Docker health
        report = checker.check_docker()
        if not report.is_healthy:
            print(f"Docker unhealthy: {report.message}")
            for rec in report.recommendations:
                print(f"  - {rec}")
        
        # Check all configured sandboxes
        report = checker.verify_isolation()
        if report.is_healthy:
            # Safe to execute code
            execute_sandboxed(code)
    """
    
    # Default timeouts for health checks
    DEFAULT_TIMEOUT_SECONDS = 5
    DEFAULT_CACHE_SECONDS = 60
    
    def __init__(self, config: Dict = None, event_bus: 'EventBus' = None):
        """
        Initialize the health checker.
        
        Args:
            config: Configuration dictionary from config.yaml
            event_bus: Optional EventBus for emitting health events
        """
        self._config = config or {}
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)
        
        # Health check cache
        self._cache: Dict[SandboxType, HealthReport] = {}
        self._cache_timestamp: Dict[SandboxType, datetime] = {}
        self._cache_ttl = timedelta(
            seconds=self._config.get("sandbox", {}).get(
                "health_check_cache_seconds", 
                self.DEFAULT_CACHE_SECONDS
            )
        )
        
        # Configuration
        sandbox_config = self._config.get("sandbox", {})
        self._health_check_enabled = sandbox_config.get("health_check", True)
        self._check_interval = sandbox_config.get("check_interval_seconds", 60)
        self._unhealthy_action = sandbox_config.get("unhealthy_action", "block")
    
    def set_event_bus(self, event_bus: 'EventBus') -> None:
        """Set the EventBus for emitting health events."""
        self._event_bus = event_bus
        self._logger.info("EventBus attached to SandboxHealthChecker")
    
    def check_docker(self, timeout_seconds: int = None) -> HealthReport:
        """
        Check if Docker is available and running.
        
        Args:
            timeout_seconds: Maximum time for check
            
        Returns:
            HealthReport with Docker health status
        """
        timeout = timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS
        start_time = time.time()
        
        # Check cache
        cached = self._get_cached(SandboxType.DOCKER)
        if cached:
            return cached
        
        details = {}
        recommendations = []
        
        try:
            # Check if docker command exists
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode != 0:
                report = HealthReport(
                    sandbox_type=SandboxType.DOCKER,
                    status=HealthStatus.UNHEALTHY,
                    message="Docker command failed",
                    details={"error": result.stderr},
                    recommendations=["Install Docker", "Ensure Docker is in PATH"]
                )
                self._cache_report(SandboxType.DOCKER, report)
                return report
            
            details["version"] = result.stdout.strip()
            
            # Check if Docker daemon is running
            info_result = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if info_result.returncode != 0:
                report = HealthReport(
                    sandbox_type=SandboxType.DOCKER,
                    status=HealthStatus.UNHEALTHY,
                    message="Docker daemon not running",
                    details=details,
                    recommendations=["Start Docker daemon", "Run: sudo systemctl start docker"]
                )
                self._cache_report(SandboxType.DOCKER, report)
                self._emit_unhealthy(report)
                return report
            
            details["server_version"] = info_result.stdout.strip()
            
            # Try to run a simple container
            test_result = subprocess.run(
                ["docker", "run", "--rm", "hello-world"],
                capture_output=True,
                text=True,
                timeout=timeout * 2
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            if test_result.returncode == 0:
                report = HealthReport(
                    sandbox_type=SandboxType.DOCKER,
                    status=HealthStatus.HEALTHY,
                    message="Docker is healthy and can run containers",
                    latency_ms=latency_ms,
                    details=details
                )
            else:
                details["test_error"] = test_result.stderr
                report = HealthReport(
                    sandbox_type=SandboxType.DOCKER,
                    status=HealthStatus.UNHEALTHY,
                    message="Docker cannot run containers",
                    latency_ms=latency_ms,
                    details=details,
                    recommendations=[
                        "Check Docker configuration",
                        "Ensure user has Docker permissions",
                        "Run: sudo usermod -aG docker $USER"
                    ]
                )
                self._emit_unhealthy(report)
            
            self._cache_report(SandboxType.DOCKER, report)
            return report
            
        except subprocess.TimeoutExpired:
            latency_ms = int((time.time() - start_time) * 1000)
            report = HealthReport(
                sandbox_type=SandboxType.DOCKER,
                status=HealthStatus.TIMEOUT,
                message="Docker health check timed out",
                latency_ms=latency_ms,
                details={"timeout_seconds": timeout},
                recommendations=[
                    "Docker may be hung",
                    "Restart Docker daemon",
                    "Check system resources"
                ]
            )
            self._cache_report(SandboxType.DOCKER, report)
            self._emit_unhealthy(report)
            return report
            
        except FileNotFoundError:
            report = HealthReport(
                sandbox_type=SandboxType.DOCKER,
                status=HealthStatus.UNHEALTHY,
                message="Docker not installed",
                recommendations=[
                    "Install Docker: https://docs.docker.com/get-docker/",
                    "Use alternative sandbox (gVisor, venv)"
                ]
            )
            self._cache_report(SandboxType.DOCKER, report)
            self._emit_unhealthy(report)
            return report
            
        except Exception as e:
            report = HealthReport(
                sandbox_type=SandboxType.DOCKER,
                status=HealthStatus.UNKNOWN,
                message=f"Docker health check error: {e}",
                details={"error": str(e)}
            )
            self._cache_report(SandboxType.DOCKER, report)
            return report
    
    def check_gvisor(self, timeout_seconds: int = None) -> HealthReport:
        """
        Check if gVisor (runsc) is available and functional.
        
        Args:
            timeout_seconds: Maximum time for check
            
        Returns:
            HealthReport with gVisor health status
        """
        timeout = timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS
        start_time = time.time()
        
        # Check cache
        cached = self._get_cached(SandboxType.GVISOOR)
        if cached:
            return cached
        
        details = {}
        recommendations = []
        
        try:
            # Check if runsc exists
            result = subprocess.run(
                ["runsc", "--version"],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode != 0:
                report = HealthReport(
                    sandbox_type=SandboxType.GVISOOR,
                    status=HealthStatus.UNHEALTHY,
                    message="gVisor runsc command failed",
                    details={"error": result.stderr},
                    recommendations=[
                        "Install gVisor: https://gvisor.dev/docs/user_guide/install/",
                        "Configure Docker to use gVisor runtime"
                    ]
                )
                self._cache_report(SandboxType.GVISOOR, report)
                return report
            
            details["version"] = result.stdout.strip()
            
            # Check if Docker has gVisor runtime configured
            docker_check = subprocess.run(
                ["docker", "info", "--format", "{{.Runtimes}}"],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if "runsc" in docker_check.stdout:
                details["docker_runtime"] = "configured"
            else:
                details["docker_runtime"] = "not_configured"
                recommendations.append("Configure Docker to use gVisor runtime")
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            report = HealthReport(
                sandbox_type=SandboxType.GVISOOR,
                status=HealthStatus.HEALTHY,
                message="gVisor is available",
                latency_ms=latency_ms,
                details=details,
                recommendations=recommendations if recommendations else None
            )
            
            self._cache_report(SandboxType.GVISOOR, report)
            return report
            
        except FileNotFoundError:
            report = HealthReport(
                sandbox_type=SandboxType.GVISOOR,
                status=HealthStatus.UNHEALTHY,
                message="gVisor (runsc) not installed",
                recommendations=[
                    "Install gVisor: https://gvisor.dev/docs/user_guide/install/"
                ]
            )
            self._cache_report(SandboxType.GVISOOR, report)
            self._emit_unhealthy(report)
            return report
            
        except Exception as e:
            report = HealthReport(
                sandbox_type=SandboxType.GVISOOR,
                status=HealthStatus.UNKNOWN,
                message=f"gVisor health check error: {e}",
                details={"error": str(e)}
            )
            self._cache_report(SandboxType.GVISOOR, report)
            return report
    
    def check_wasm(self, timeout_seconds: int = None) -> HealthReport:
        """
        Check if WASM runtime (wasmtime) is available.
        
        Args:
            timeout_seconds: Maximum time for check
            
        Returns:
            HealthReport with WASM health status
        """
        timeout = timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS
        start_time = time.time()
        
        # Check cache
        cached = self._get_cached(SandboxType.WASM)
        if cached:
            return cached
        
        details = {}
        
        try:
            # Check Python wasmtime package
            try:
                import wasmtime
                details["wasmtime_module"] = "available"
            except ImportError:
                details["wasmtime_module"] = "not_available"
                
                # Check for wasmtime CLI
                cli_result = subprocess.run(
                    ["wasmtime", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                
                if cli_result.returncode == 0:
                    details["wasmtime_cli"] = cli_result.stdout.strip()
                else:
                    report = HealthReport(
                        sandbox_type=SandboxType.WASM,
                        status=HealthStatus.UNHEALTHY,
                        message="WASM runtime not available",
                        details=details,
                        recommendations=[
                            "Install wasmtime: pip install wasmtime",
                            "Or install wasmtime CLI: https://wasmtime.dev/"
                        ]
                    )
                    self._cache_report(SandboxType.WASM, report)
                    self._emit_unhealthy(report)
                    return report
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            report = HealthReport(
                sandbox_type=SandboxType.WASM,
                status=HealthStatus.HEALTHY,
                message="WASM runtime is available",
                latency_ms=latency_ms,
                details=details
            )
            
            self._cache_report(SandboxType.WASM, report)
            return report
            
        except Exception as e:
            report = HealthReport(
                sandbox_type=SandboxType.WASM,
                status=HealthStatus.UNKNOWN,
                message=f"WASM health check error: {e}",
                details={"error": str(e)}
            )
            self._cache_report(SandboxType.WASM, report)
            return report
    
    def check_venv(self) -> HealthReport:
        """
        Check if running in a virtual environment.
        
        Returns:
            HealthReport with venv health status
        """
        import sys
        
        # Check cache
        cached = self._get_cached(SandboxType.VENV)
        if cached:
            return cached
        
        details = {
            "sys_prefix": sys.prefix,
            "sys_base_prefix": getattr(sys, 'base_prefix', sys.prefix),
            "in_venv": False
        }
        
        # Check if in venv
        in_venv = (
            hasattr(sys, 'real_prefix') or
            (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
        )
        
        details["in_venv"] = in_venv
        
        if in_venv:
            report = HealthReport(
                sandbox_type=SandboxType.VENV,
                status=HealthStatus.HEALTHY,
                message="Running in virtual environment",
                details=details
            )
        else:
            report = HealthReport(
                sandbox_type=SandboxType.VENV,
                status=HealthStatus.UNHEALTHY,
                message="Not running in virtual environment",
                details=details,
                recommendations=[
                    "Create a virtual environment: python -m venv .venv",
                    "Activate: source .venv/bin/activate"
                ]
            )
            self._emit_unhealthy(report)
        
        self._cache_report(SandboxType.VENV, report)
        return report
    
    def check_restricted_subprocess(self) -> HealthReport:
        """
        Check if restricted subprocess is available.
        
        This is always available as a fallback.
        
        Returns:
            HealthReport with restricted subprocess status
        """
        # Check cache first
        cached = self._get_cached(SandboxType.RESTRICTED_SUBPROCESS)
        if cached:
            return cached
        
        report = HealthReport(
            sandbox_type=SandboxType.RESTRICTED_SUBPROCESS,
            status=HealthStatus.HEALTHY,
            message="Restricted subprocess is available (built-in)"
        )
        self._cache_report(SandboxType.RESTRICTED_SUBPROCESS, report)
        return report
    
    def verify_isolation(self, sandbox_type: SandboxType = None) -> HealthReport:
        """
        Verify isolation for the configured or specified sandbox type.
        
        This is the main entry point for health verification.
        
        Args:
            sandbox_type: Specific sandbox to check, or None for configured default
            
        Returns:
            HealthReport with isolation verification result
        """
        if not self._health_check_enabled:
            return HealthReport(
                sandbox_type=SandboxType.NONE,
                status=HealthStatus.UNKNOWN,
                message="Health check disabled by configuration"
            )
        
        # Determine sandbox type to check
        if sandbox_type is None:
            sandbox_type_str = self._config.get("security", {}).get("sandbox_type", "none")
            try:
                sandbox_type = SandboxType(sandbox_type_str)
            except ValueError:
                sandbox_type = SandboxType.NONE
        
        # Route to appropriate checker
        checkers = {
            SandboxType.DOCKER: self.check_docker,
            SandboxType.GVISOOR: self.check_gvisor,
            SandboxType.WASM: self.check_wasm,
            SandboxType.VENV: self.check_venv,
            SandboxType.RESTRICTED_SUBPROCESS: self.check_restricted_subprocess,
        }
        
        checker = checkers.get(sandbox_type)
        if checker:
            return checker()
        
        return HealthReport(
            sandbox_type=SandboxType.NONE,
            status=HealthStatus.UNHEALTHY,
            message="No sandbox configured",
            recommendations=[
                "Configure sandbox_type in config.yaml",
                "Options: docker, gvisor, wasm, venv, restricted_subprocess"
            ]
        )
    
    def should_block_execution(self, report: HealthReport = None) -> bool:
        """
        Determine if execution should be blocked based on health and config.
        
        Args:
            report: HealthReport to evaluate, or None to check current
            
        Returns:
            True if execution should be blocked
        """
        if report is None:
            report = self.verify_isolation()
        
        if report.is_healthy:
            return False
        
        # Check configured action
        if self._unhealthy_action == "block":
            return True
        elif self._unhealthy_action == "warn":
            return False
        elif self._unhealthy_action == "allow":
            return False
        
        # Default: block on unhealthy
        return True
    
    def _get_cached(self, sandbox_type: SandboxType) -> Optional[HealthReport]:
        """Get cached report if still valid."""
        if sandbox_type not in self._cache:
            return None
        
        cached_time = self._cache_timestamp.get(sandbox_type)
        if cached_time and datetime.utcnow() - cached_time < self._cache_ttl:
            return self._cache[sandbox_type]
        
        return None
    
    def _cache_report(self, sandbox_type: SandboxType, report: HealthReport) -> None:
        """Cache a health report."""
        self._cache[sandbox_type] = report
        self._cache_timestamp[sandbox_type] = datetime.utcnow()
    
    def _emit_unhealthy(self, report: HealthReport) -> None:
        """Emit SANDBOX_UNHEALTHY event if event bus is configured."""
        if self._event_bus:
            try:
                from ..events.event_bus import Event, EventSeverity
                event = Event(
                    event_type="SANDBOX_UNHEALTHY",
                    data=report.to_dict(),
                    severity=EventSeverity.WARN,
                    source="SandboxHealthChecker"
                )
                self._event_bus.emit(event)
            except Exception as e:
                self._logger.error(f"Failed to emit SANDBOX_UNHEALTHY event: {e}")
    
    def clear_cache(self) -> None:
        """Clear the health check cache."""
        self._cache.clear()
        self._cache_timestamp.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get health checker statistics."""
        return {
            "health_check_enabled": self._health_check_enabled,
            "check_interval_seconds": self._check_interval,
            "unhealthy_action": self._unhealthy_action,
            "cache_ttl_seconds": self._cache_ttl.total_seconds(),
            "cached_types": list(self._cache.keys())
        }


def create_health_checker(config: Dict = None, event_bus: 'EventBus' = None) -> SandboxHealthChecker:
    """
    Factory function to create a SandboxHealthChecker.
    
    Args:
        config: Configuration dictionary
        event_bus: Optional EventBus for events
        
    Returns:
        Configured SandboxHealthChecker instance
    """
    return SandboxHealthChecker(config, event_bus)
