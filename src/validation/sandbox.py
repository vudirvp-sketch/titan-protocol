"""
Validator Sandbox for TITAN FUSE Protocol.

Provides sandboxed execution for untrusted validators.

SECURITY NOTE: This module uses subprocess isolation instead of
deprecated VM2 library. VM2 has known CVE vulnerabilities and
should NOT be used. For JavaScript validators, we use isolated-vm.

Author: TITAN FUSE Team
Version: 3.2.3
"""

import subprocess
import json
import tempfile
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging


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

    def __init__(self, timeout_ms: int = 5000, max_output_size: int = 1024 * 1024):
        """
        Initialize sandbox.

        Args:
            timeout_ms: Maximum execution time in milliseconds
            max_output_size: Maximum output size in bytes
        """
        self.timeout_ms = timeout_ms
        self.max_output_size = max_output_size
        self._logger = logging.getLogger(__name__)

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
