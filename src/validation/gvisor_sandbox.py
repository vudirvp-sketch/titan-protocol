"""
gVisor-based Sandbox for TITAN FUSE Protocol.

ITEM-SEC-01 Implementation:
- GVisorSandbox class using container-based isolation
- Alternative to WASM sandbox for heavier workloads
- Runsc container runtime integration
- Strong isolation via user-space kernel

This provides container-level isolation as an alternative to WASM.

Author: TITAN FUSE Team
Version: 3.3.0
"""

import json
import time
import subprocess
import tempfile
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from .sandbox import ResourceLimits, SandboxResult


@dataclass
class GVisorConfig:
    """Configuration for gVisor sandbox."""
    
    def __init__(self,
                 memory_limit_mb: int = 256,
                 timeout_ms: int = 30000,
                 max_output_size: int = 10 * 1024 * 1024,
                 cpu_limit: str = "1.0",
                 network_enabled: bool = False,
                 rootfs_path: str = None):
        self.memory_limit_mb = memory_limit_mb
        self.timeout_ms = timeout_ms
        self.max_output_size = max_output_size
        self.cpu_limit = cpu_limit
        self.network_enabled = network_enabled
        self.rootfs_path = rootfs_path or "/var/lib/titan/rootfs"


class GVisorSandbox:
    """
    Container-based sandbox using gVisor (runsc).
    
    Features:
    - Strong isolation via user-space kernel
    - Memory and CPU limits
    - No root required (unprivileged containers)
    - Network isolation
    - Filesystem isolation
    
    SECURITY MODEL:
    - Each execution runs in isolated container
    - gVisor provides kernel-level isolation
    - No shared kernel state between executions
    - Resource limits enforced by container runtime
    
    Requirements:
    - runsc (gVisor runtime) must be installed
    - Docker or containerd configured with runsc
    
    Usage:
        sandbox = GVisorSandbox(GVisorConfig(memory_limit_mb=256))
        result = sandbox.execute_python(python_code, context)
    """
    
    # GAP tag for sandbox violations
    GAP_TAG = "[gap: gvisor_sandbox_violation]"
    
    # Container image for execution
    DEFAULT_IMAGE = "python:3.11-slim"
    
    def __init__(self, config: GVisorConfig = None):
        """
        Initialize gVisor sandbox.
        
        Args:
            config: Sandbox configuration
        """
        self.config = config or GVisorConfig()
        self._logger = logging.getLogger(__name__)
        self._runsc_available = self._check_runsc_available()
        self._docker_available = self._check_docker_available()
    
    def _check_runsc_available(self) -> bool:
        """Check if gVisor runsc is available."""
        try:
            result = subprocess.run(
                ['runsc', '--version'],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    def _check_docker_available(self) -> bool:
        """Check if Docker is available."""
        try:
            result = subprocess.run(
                ['docker', '--version'],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    def execute_python(self, code: str, context: Dict = None) -> SandboxResult:
        """
        Execute Python code in gVisor container.
        
        Args:
            code: Python source code
            context: Execution context dictionary
            
        Returns:
            SandboxResult with execution results
        """
        start_time = time.time()
        context = context or {}
        
        if not self._docker_available:
            return SandboxResult(
                valid=False,
                violations=[],
                error="[gap: docker_not_available] Docker is required for gVisor sandbox"
            )
        
        # Create wrapper script
        wrapper = self._create_python_wrapper(code, context)
        
        try:
            # Create temp directory for I/O
            with tempfile.TemporaryDirectory() as tmpdir:
                # Write wrapper script
                wrapper_path = Path(tmpdir) / "executor.py"
                wrapper_path.write_text(wrapper)
                
                # Prepare output file
                output_path = Path(tmpdir) / "output.json"
                output_path.write_text("{}")
                
                # Build docker run command with gVisor runtime
                cmd = [
                    'docker', 'run', '--rm',
                    '--runtime=runsc',  # Use gVisor runtime
                    f'--memory={self.config.memory_limit_mb}m',
                    f'--cpus={self.config.cpu_limit}',
                    '-v', f'{tmpdir}:/sandbox:ro',
                    '-v', f'{tmpdir}:/output:rw',
                    '--network=none' if not self.config.network_enabled else '',
                    self.DEFAULT_IMAGE,
                    'python', '/sandbox/executor.py'
                ]
                
                # Remove empty strings
                cmd = [c for c in cmd if c]
                
                # Execute with timeout
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.config.timeout_ms / 1000
                )
                
                execution_time = int((time.time() - start_time) * 1000)
                
                # Read output
                try:
                    output = json.loads(output_path.read_text())
                except:
                    output = {}
                
                if result.returncode != 0:
                    return SandboxResult(
                        valid=False,
                        violations=[],
                        error=f"Container execution failed: {result.stderr}",
                        execution_time_ms=execution_time
                    )
                
                return SandboxResult(
                    valid=output.get('valid', True),
                    violations=output.get('violations', []),
                    execution_time_ms=execution_time
                )
                
        except subprocess.TimeoutExpired:
            execution_time = int((time.time() - start_time) * 1000)
            return SandboxResult(
                valid=False,
                violations=[],
                error="Execution timeout",
                timeout=True,
                execution_time_ms=execution_time
            )
            
        except Exception as e:
            self._logger.error(f"gVisor execution error: {e}")
            return SandboxResult(
                valid=False,
                violations=[],
                error=str(e)
            )
    
    def execute_script(self, script_path: Path, context: Dict = None) -> SandboxResult:
        """
        Execute a script file in gVisor container.
        
        Args:
            script_path: Path to script file
            context: Execution context dictionary
            
        Returns:
            SandboxResult with execution results
        """
        try:
            code = script_path.read_text()
            return self.execute_python(code, context)
        except Exception as e:
            return SandboxResult(
                valid=False,
                violations=[],
                error=f"Failed to read script: {e}"
            )
    
    def validate_code_safety(self, code: str) -> Dict[str, Any]:
        """
        Validate code for safety before execution.
        
        Performs static analysis for dangerous patterns.
        This is a pre-check before container execution.
        
        Args:
            code: Source code to validate
            
        Returns:
            Dict with 'safe' boolean and 'findings' list
        """
        import re
        
        findings = []
        
        # Dangerous patterns
        dangerous_patterns = [
            (r'import\s+os\b', 'OS_IMPORT', 'HIGH'),
            (r'import\s+subprocess\b', 'SUBPROCESS_IMPORT', 'HIGH'),
            (r'import\s+socket\b', 'SOCKET_IMPORT', 'HIGH'),
            (r'__import__\s*\(', 'DYNAMIC_IMPORT', 'HIGH'),
            (r'eval\s*\(', 'EVAL_USAGE', 'CRITICAL'),
            (r'exec\s*\(', 'EXEC_USAGE', 'CRITICAL'),
            (r'compile\s*\(', 'COMPILE_USAGE', 'HIGH'),
            (r'open\s*\(["\']/', 'ABSOLUTE_PATH', 'MEDIUM'),
            (r'shutil\.rmtree', 'DIR_DELETE', 'HIGH'),
            (r'os\.system', 'SYSTEM_CALL', 'CRITICAL'),
        ]
        
        for pattern, name, severity in dangerous_patterns:
            matches = re.findall(pattern, code)
            if matches:
                findings.append({
                    'pattern': name,
                    'matches': matches[:3],
                    'severity': severity
                })
        
        return {
            'safe': len(findings) == 0,
            'findings': findings,
            'reason': '; '.join(f['pattern'] for f in findings) if findings else None
        }
    
    def get_resource_limits(self) -> ResourceLimits:
        """Get current resource limits."""
        return ResourceLimits(
            timeout_ms=self.config.timeout_ms,
            max_output_size=self.config.max_output_size,
            memory_limit_mb=self.config.memory_limit_mb,
            filesystem_access=[],  # No filesystem access by default
            network_access=self.config.network_enabled
        )
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check if gVisor sandbox is properly configured.
        
        Returns:
            Dict with health check results
        """
        checks = []
        
        # Check Docker
        checks.append({
            'name': 'docker',
            'available': self._docker_available,
            'message': 'Docker installed' if self._docker_available else 'Docker not found'
        })
        
        # Check gVisor runsc
        checks.append({
            'name': 'runsc',
            'available': self._runsc_available,
            'message': 'gVisor runsc installed' if self._runsc_available else 'gVisor runsc not found'
        })
        
        # Check Docker runtime configuration
        if self._docker_available:
            try:
                result = subprocess.run(
                    ['docker', 'info', '--format', '{{.Runtimes}}'],
                    capture_output=True,
                    text=True
                )
                has_runsc = 'runsc' in result.stdout
                checks.append({
                    'name': 'docker_runsc_runtime',
                    'available': has_runsc,
                    'message': 'runsc runtime configured' if has_runsc else 'runsc not configured in Docker'
                })
            except:
                checks.append({
                    'name': 'docker_runsc_runtime',
                    'available': False,
                    'message': 'Could not check Docker runtime configuration'
                })
        
        all_ok = self._docker_available
        
        return {
            'healthy': all_ok,
            'checks': checks,
            'recommendations': [
                'Install Docker: https://docs.docker.com/get-docker/',
                'Install gVisor: https://gvisor.dev/docs/user_guide/install/',
                'Configure Docker with runsc: docker daemon config'
            ] if not all_ok else []
        }
    
    def _create_python_wrapper(self, code: str, context: Dict) -> str:
        """Create Python wrapper script for isolated execution."""
        context_json = json.dumps(context)
        
        return f'''
import json
import sys
import os

# Disable dangerous builtins
del __builtins__.__dict__['__import__']
del __builtins__.__dict__['eval']
del __builtins__.__dict__['exec']
del __builtins__.__dict__['compile']
del __builtins__.__dict__['open']

# Context
context = {context_json}

# Restricted globals
restricted_globals = {{
    "__builtins__": {{
        "True": True, "False": False, "None": None,
        "len": len, "str": str, "int": int, "float": float,
        "list": list, "dict": dict, "set": set, "tuple": tuple,
        "range": range, "enumerate": enumerate, "zip": zip,
        "isinstance": isinstance, "hasattr": hasattr,
        "abs": abs, "min": min, "max": max, "sum": sum,
        "sorted": sorted, "reversed": reversed, "any": any, "all": all,
        "print": print, "json": json
    }},
    "context": context
}}

# Execute validator code
try:
    exec("""
{code}
""", restricted_globals)
    
    # Get result
    if "validator" in restricted_globals:
        result = restricted_globals["validator"](context)
    elif "validate" in restricted_globals:
        result = restricted_globals["validate"](context)
    else:
        result = {{"valid": True, "violations": []}}
    
    # Write result
    with open("/output/output.json", "w") as f:
        json.dump(result, f)

except Exception as e:
    with open("/output/output.json", "w") as f:
        json.dump({{"valid": False, "violations": [str(e)]}}, f)
'''


def create_gvisor_sandbox(config: Dict = None) -> GVisorSandbox:
    """
    Factory function to create configured gVisor sandbox.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Configured GVisorSandbox instance
    """
    sandbox_config = GVisorConfig()
    
    if config:
        sandbox_config.memory_limit_mb = config.get('memory_limit_mb', 256)
        sandbox_config.timeout_ms = config.get('timeout_ms', 30000)
        sandbox_config.max_output_size = config.get('max_output_size', 10 * 1024 * 1024)
        sandbox_config.cpu_limit = config.get('cpu_limit', '1.0')
        sandbox_config.network_enabled = config.get('network_enabled', False)
    
    return GVisorSandbox(sandbox_config)
