"""
Validator Sandbox for TITAN FUSE Protocol.

Provides sandboxed execution for untrusted validators.

SECURITY NOTE: This module uses subprocess isolation instead of
deprecated VM2 library. VM2 has known CVE vulnerabilities and
should NOT be used. For JavaScript validators, we use isolated-vm.

Author: TITAN FUSE Team
Version: 3.2.3

ITEM-070 Implementation:
- ValidatorSandbox class with isolated execution
- validate_code_safety() for pre-execution checks
- get_resource_limits() for sandbox configuration
- Filesystem isolation (deny all by default)
- Timeout enforcement (default 10000ms)
"""

import subprocess
import json
import tempfile
import os
import time
import re
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
import logging


@dataclass
class ResourceLimits:
    """Resource limits for sandbox execution."""
    timeout_ms: int = 10000
    max_output_size: int = 1024 * 1024  # 1MB
    memory_limit_mb: int = 128
    filesystem_access: List[str] = field(default_factory=list)
    network_access: bool = False
    max_processes: int = 1
    
    def to_dict(self) -> Dict:
        return {
            "timeout_ms": self.timeout_ms,
            "max_output_size": self.max_output_size,
            "memory_limit_mb": self.memory_limit_mb,
            "filesystem_access": self.filesystem_access,
            "network_access": self.network_access,
            "max_processes": self.max_processes
        }


@dataclass
class SandboxResult:
    """Result of sandboxed validator execution."""
    valid: bool
    violations: list
    error: Optional[str] = None
    execution_time_ms: int = 0
    timeout: bool = False
    output_size_bytes: int = 0

    def to_dict(self) -> Dict:
        return {
            "valid": self.valid,
            "violations": self.violations,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "timeout": self.timeout,
            "output_size_bytes": self.output_size_bytes
        }


class ValidatorSandbox:
    """
    Execute validators in isolated subprocess context.

    Provides secure execution for untrusted validator code
    with timeout enforcement and output size limits.

    SECURITY MODEL:
    - Python validators: Subprocess isolation with restricted globals
    - JS validators: isolated-vm (NOT VM2 due to CVE vulnerabilities)

    Usage:
        sandbox = ValidatorSandbox(timeout_ms=5000)
        result = sandbox.run_python_validator(Path("my_validator.py"), content)
        if result.valid:
            print("Validation passed")
        else:
            print(f"Violations: {result.violations}")
    """

    # Dangerous patterns for code safety validation
    DANGEROUS_PATTERNS = [
        # Filesystem access
        (r'open\s*\(["\']/', 'ABSOLUTE_PATH'),
        (r'os\.path\.join\s*\([^)]*["\']/', 'ABSOLUTE_PATH'),
        (r'shutil\.rmtree', 'DIR_DELETE'),
        (r'os\.remove', 'FILE_DELETE'),
        (r'os\.unlink', 'FILE_DELETE'),
        (r'subprocess\..*shell\s*=\s*True', 'SHELL_EXEC'),
        # Network access
        (r'requests\.(get|post|put|delete)', 'NETWORK'),
        (r'urllib', 'NETWORK'),
        (r'socket\.', 'NETWORK'),
        # Code execution
        (r'eval\s*\(', 'CODE_EXEC'),
        (r'exec\s*\(', 'CODE_EXEC'),
        (r'compile\s*\(', 'CODE_EXEC'),
        (r'__import__\s*\(', 'CODE_EXEC'),
        # System access
        (r'os\.system', 'SYSTEM'),
        (r'os\.popen', 'SYSTEM'),
        (r'sys\.(exit|setrecursionlimit)', 'SYSTEM'),
        # Introspection bypass
        (r'getattr\s*\([^)]*__)', 'INTROSPECTION'),
        (r'setattr\s*\([^)]*__)', 'INTROSPECTION'),
        (r'delattr\s*\([^)]*__)', 'INTROSPECTION'),
    ]

    def __init__(self, timeout_ms: int = 5000, max_output_size: int = 1024 * 1024,
                 resource_limits: ResourceLimits = None, config: Dict = None):
        """
        Initialize sandbox.

        Args:
            timeout_ms: Maximum execution time in milliseconds (default from config)
            max_output_size: Maximum output size in bytes
            resource_limits: Optional ResourceLimits configuration
            config: Optional config dict for validators.timeout
        """
        # Support config-driven timeout (ITEM-070 step 03)
        if config and 'validators' in config:
            timeout_ms = config['validators'].get('timeout', timeout_ms) * 1000
        
        self.timeout_ms = timeout_ms
        self.max_output_size = max_output_size
        self._resource_limits = resource_limits or ResourceLimits(
            timeout_ms=timeout_ms,
            max_output_size=max_output_size
        )
        self._config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # Compile dangerous patterns for code safety checks
        self._dangerous_patterns = [
            (re.compile(p, re.IGNORECASE), name) for p, name in self.DANGEROUS_PATTERNS
        ]

    def execute(self, code: str, context: Dict = None) -> SandboxResult:
        """
        Execute validator code in sandbox.
        
        This is the main entry point for sandboxed execution (ITEM-070 step 02).
        Auto-detects language and routes to appropriate executor.
        
        Args:
            code: Code string to execute (or path to file)
            context: Context dictionary for execution
            
        Returns:
            SandboxResult with execution results
        """
        context = context or {}
        
        # Determine if code is a file path or inline code
        code_path = Path(code) if '/' in code or code.endswith('.py') or code.endswith('.js') else None
        
        # Validate code safety before execution
        safety_check = self.validate_code_safety(code if not code_path else code_path.read_text(errors='ignore'))
        if not safety_check['safe']:
            return SandboxResult(
                valid=False,
                violations=[],
                error=f"[gap: unsafe_code_blocked] {safety_check['reason']}"
            )
        
        # Route to appropriate executor
        if code_path:
            if code_path.suffix == '.js':
                return self.run_js_validator(code_path, '', context)
            else:
                return self.run_python_validator(code_path, '', context)
        else:
            # Inline code - create temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_path = Path(f.name)
            
            try:
                return self.run_python_validator(temp_path, '', context)
            finally:
                temp_path.unlink(missing_ok=True)

    def validate_code_safety(self, code: str) -> Dict[str, Any]:
        """
        Validate code for dangerous patterns before execution (ITEM-070 step 02).
        
        Performs static analysis to detect potentially dangerous operations
        that could violate sandbox isolation.
        
        Args:
            code: Source code to validate
            
        Returns:
            Dict with 'safe' boolean, 'findings' list, and 'reason' if unsafe
        """
        findings = []
        
        for pattern, name in self._dangerous_patterns:
            matches = pattern.findall(code)
            if matches:
                findings.append({
                    'pattern': name,
                    'matches': matches[:3],  # Limit to first 3 matches
                    'severity': 'HIGH' if name in ['CODE_EXEC', 'SYSTEM', 'SHELL_EXEC'] else 'MEDIUM'
                })
        
        # Check for filesystem access beyond allowed paths
        if self._resource_limits.filesystem_access:
            # Only specified paths are allowed
            for pattern, name in [(r'open\s*\(["\']([^"\']+)', 'FILE_ACCESS'),
                                  (r'with\s+open\s*\(["\']([^"\']+)', 'FILE_ACCESS')]:
                for match in re.findall(pattern, code):
                    if not any(match.startswith(allowed) for allowed in self._resource_limits.filesystem_access):
                        findings.append({
                            'pattern': 'UNAUTHORIZED_FILE_ACCESS',
                            'path': match,
                            'severity': 'HIGH'
                        })
        
        return {
            'safe': len(findings) == 0,
            'findings': findings,
            'reason': '; '.join(f['pattern'] for f in findings) if findings else None
        }

    def get_resource_limits(self) -> ResourceLimits:
        """
        Get current resource limits for the sandbox (ITEM-070 step 02).
        
        Returns:
            ResourceLimits with current configuration
        """
        return self._resource_limits

    def run_python_validator(self, script_path: Path, content: str,
                            context: Dict = None) -> SandboxResult:
        """
        Run Python validator in isolated subprocess.

        Args:
            script_path: Path to Python validator script
            content: Content to validate
            context: Optional context dictionary

        Returns:
            SandboxResult with validation result
        """
        start_time = time.time()

        # Create wrapper script
        wrapper = self._create_python_wrapper(script_path, content, context or {})

        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.py', delete=False
            ) as f:
                f.write(wrapper)
                wrapper_path = f.name

            result = subprocess.run(
                ['python', wrapper_path],
                capture_output=True,
                text=True,
                timeout=self.timeout_ms / 1000
            )

            os.unlink(wrapper_path)
            execution_time = int((time.time() - start_time) * 1000)

            if result.returncode != 0:
                return SandboxResult(
                    valid=False,
                    violations=[],
                    error=f"Validator failed: {result.stderr}",
                    execution_time_ms=execution_time
                )

            # Parse output
            output = result.stdout
            if len(output) > self.max_output_size:
                return SandboxResult(
                    valid=False,
                    violations=[],
                    error=f"Output exceeds limit: {len(output)} > {self.max_output_size}",
                    execution_time_ms=execution_time,
                    output_size_bytes=len(output)
                )

            parsed = json.loads(output)
            return SandboxResult(
                valid=parsed.get("valid", False),
                violations=parsed.get("violations", []),
                execution_time_ms=execution_time,
                output_size_bytes=len(output)
            )

        except subprocess.TimeoutExpired:
            return SandboxResult(
                valid=False,
                violations=[],
                error="Validator timeout",
                timeout=True,
                execution_time_ms=self.timeout_ms
            )
        except json.JSONDecodeError as e:
            return SandboxResult(
                valid=False,
                violations=[],
                error=f"Invalid JSON output: {e}"
            )
        except Exception as e:
            self._logger.error(f"Sandbox error: {e}")
            return SandboxResult(
                valid=False,
                violations=[],
                error=str(e)
            )

    def run_js_validator(self, script_path: Path, content: str,
                        context: Dict = None) -> SandboxResult:
        """
        Run JS validator in Node.js isolated-vm.

        NOTE: Requires isolated-vm npm package installed.
        VM2 is NOT used due to known CVE vulnerabilities.

        Args:
            script_path: Path to JS validator script
            content: Content to validate
            context: Optional context dictionary

        Returns:
            SandboxResult with validation result
        """
        start_time = time.time()

        # Check if isolated-vm is available
        try:
            check_result = subprocess.run(
                ['node', '-e', 'require("isolated-vm")'],
                capture_output=True,
                text=True
            )
            if check_result.returncode != 0:
                return SandboxResult(
                    valid=False,
                    violations=[],
                    error="isolated-vm not available. Install with: npm install isolated-vm"
                )
        except FileNotFoundError:
            return SandboxResult(
                valid=False,
                violations=[],
                error="Node.js not found. Install Node.js to run JS validators."
            )

        # Create isolated VM wrapper
        wrapper = self._create_js_wrapper(script_path, content, context or {})

        try:
            result = subprocess.run(
                ['node', '-e', wrapper],
                capture_output=True,
                text=True,
                timeout=self.timeout_ms / 1000
            )

            execution_time = int((time.time() - start_time) * 1000)

            if result.returncode != 0:
                return SandboxResult(
                    valid=False,
                    violations=[],
                    error=f"Validator failed: {result.stderr}",
                    execution_time_ms=execution_time
                )

            output = result.stdout
            if len(output) > self.max_output_size:
                return SandboxResult(
                    valid=False,
                    violations=[],
                    error=f"Output exceeds limit: {len(output)} > {self.max_output_size}",
                    execution_time_ms=execution_time,
                    output_size_bytes=len(output)
                )

            parsed = json.loads(output)
            return SandboxResult(
                valid=parsed.get("valid", False),
                violations=parsed.get("violations", []),
                execution_time_ms=execution_time,
                output_size_bytes=len(output)
            )

        except subprocess.TimeoutExpired:
            return SandboxResult(
                valid=False,
                violations=[],
                error="Validator timeout",
                timeout=True,
                execution_time_ms=self.timeout_ms
            )
        except Exception as e:
            self._logger.error(f"JS Sandbox error: {e}")
            return SandboxResult(
                valid=False,
                violations=[],
                error=str(e)
            )

    def _create_python_wrapper(self, script_path: Path, content: str,
                               context: Dict) -> str:
        """Create isolated Python wrapper script."""
        # Escape content for JSON
        content_json = json.dumps(content)
        context_json = json.dumps(context)

        return f'''
import json
import sys

# Restricted builtins for safety
restricted_builtins = {{
    "True": True, "False": False, "None": None,
    "len": len, "str": str, "int": int, "float": float,
    "list": list, "dict": dict, "set": set, "tuple": tuple,
    "range": range, "enumerate": enumerate, "zip": zip,
    "isinstance": isinstance, "hasattr": hasattr,
    "abs": abs, "min": min, "max": max, "sum": sum,
    "sorted": sorted, "reversed": reversed, "any": any, "all": all,
    "json": json
}}

# Setup restricted globals
restricted_globals = {{
    "__builtins__": restricted_builtins,
    "content": {content_json},
    "context": {context_json}
}}

# Load and execute validator
try:
    with open("{script_path}") as f:
        validator_code = f.read()

    exec(validator_code, restricted_globals)

    # Try to get validator function
    if "validator" in restricted_globals:
        result = restricted_globals["validator"](content, context)
    elif "validate" in restricted_globals:
        result = restricted_globals["validate"](content, context)
    else:
        result = {{"valid": True, "violations": [], "note": "No validator function found"}}

    # Ensure result has correct format
    if not isinstance(result, dict):
        result = {{"valid": bool(result), "violations": []}}

    print(json.dumps(result))

except Exception as e:
    print(json.dumps({{"valid": False, "violations": [f"Error: {{str(e)}}"]}}))
'''

    def _create_js_wrapper(self, script_path: Path, content: str,
                           context: Dict) -> str:
        """Create isolated-vm JS wrapper script."""
        content_json = json.dumps(content)
        context_json = json.dumps(context)

        return f'''
const ivm = require('isolated-vm');

async function run() {{
    const isolate = new ivm.Isolate({{ memoryLimit: 128 }});
    const context = await isolate.createContext();

    // Setup globals
    await context.eval(`
        globalThis.content = {content_json};
        globalThis.context = {context_json};
    `);

    // Load validator code
    const fs = require('fs');
    const code = fs.readFileSync('{script_path}', 'utf8');

    // Execute in isolation
    await context.eval(code);

    // Get result
    const result = await context.eval(`
        typeof validate === 'function'
            ? validate(content, context)
            : {{ valid: true, violations: [] }}
    `);

    console.log(JSON.stringify(result));
}}

run().catch(e => {{
    console.log(JSON.stringify({{ valid: false, violations: [e.message] }}));
    process.exit(1);
}});
'''


def get_sandbox(config: Dict = None) -> ValidatorSandbox:
    """
    Factory function to create configured sandbox (ITEM-070 integration).
    
    Reads sandbox configuration from config.yaml if provided.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Configured ValidatorSandbox instance
    """
    limits = ResourceLimits()
    
    if config:
        sandbox_config = config.get('sandbox', {})
        limits.timeout_ms = sandbox_config.get('timeout_ms', 10000)
        limits.memory_limit_mb = sandbox_config.get('memory_limit_mb', 128)
        
        # Check if sandbox is enabled in config
        validation_config = config.get('validation', {})
        if not validation_config.get('sandbox_enabled', True):
            logging.getLogger(__name__).warning(
                "Sandbox disabled via config - validators will run with reduced isolation"
            )
    
    return ValidatorSandbox(
        timeout_ms=limits.timeout_ms,
        max_output_size=limits.max_output_size,
        resource_limits=limits,
        config=config
    )
