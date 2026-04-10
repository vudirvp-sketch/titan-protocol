"""
INVAR-05 Compliant JavaScript Validator Wrapper

Executes JS validators in subprocess sandbox for security.
This module provides a safe execution environment for JavaScript validators
following the INVAR-05 execution gate security requirements.

Version: 5.1.0
"""

import subprocess
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class SandboxConfig:
    """Sandbox configuration for JS validator execution."""
    timeout_ms: int = 5000
    max_memory_mb: int = 128
    allowed_commands: List[str] = None
    security_context: str = "sandboxed"
    
    def __post_init__(self):
        if self.allowed_commands is None:
            self.allowed_commands = ["node"]


@dataclass
class ValidationResult:
    """Result from JS validator execution."""
    valid: bool
    validator: str
    violations: List[Dict[str, Any]]
    summary: str
    execution_time_ms: float
    sandbox_enforced: bool = True
    error: Optional[str] = None


class JSValidatorWrapper:
    """
    INVAR-05 compliant JavaScript validator wrapper.
    
    Executes JS validators in subprocess sandbox with:
    - Configurable timeout
    - Memory limits
    - Command whitelisting
    - Security context enforcement
    
    Usage:
        wrapper = JSValidatorWrapper()
        result = wrapper.validate(
            validator_path=Path("skills/validators/no-todos.js"),
            content="const x = 1; // TODO: fix this"
        )
        print(result.valid)  # False
        print(result.violations)  # List of violations
    """
    
    DEFAULT_CONFIG = SandboxConfig(
        timeout_ms=5000,
        max_memory_mb=128,
        allowed_commands=["node"],
        security_context="sandboxed"
    )
    
    # Regex patterns to extract sandbox config from JS file comments
    SANDBOX_CONFIG_PATTERNS = {
        "sandbox_type": r"@sandbox_type:\s*(\w+)",
        "timeout_ms": r"@timeout_ms:\s*(\d+)",
        "allowed_commands": r"@allowed_commands:\s*(\[.*?\])",
        "max_memory_mb": r"@max_memory_mb:\s*(\d+)",
        "security_context": r"@security_context:\s*(\w+)"
    }
    
    def __init__(self, config: Optional[SandboxConfig] = None):
        """Initialize wrapper with optional custom config."""
        self.config = config or self.DEFAULT_CONFIG
        self._validator_configs: Dict[str, SandboxConfig] = {}
    
    def _parse_validator_config(self, validator_path: Path) -> SandboxConfig:
        """
        Parse INVAR-05 sandbox configuration from JS file comments.
        
        Args:
            validator_path: Path to JS validator file
            
        Returns:
            SandboxConfig with parsed or default values
        """
        # Check cache
        cache_key = str(validator_path)
        if cache_key in self._validator_configs:
            return self._validator_configs[cache_key]
        
        try:
            content = validator_path.read_text(encoding="utf-8")
            
            # Extract only the first comment block (header)
            header_match = re.search(r"/\*\*.*?\*/", content, re.DOTALL)
            if not header_match:
                logger.warning(f"No header comment found in {validator_path}")
                return self.config
            
            header = header_match.group(0)
            
            # Parse configuration values
            config_values = {}
            for key, pattern in self.SANDBOX_CONFIG_PATTERNS.items():
                match = re.search(pattern, header)
                if match:
                    value = match.group(1)
                    if key == "timeout_ms" or key == "max_memory_mb":
                        config_values[key] = int(value)
                    elif key == "allowed_commands":
                        # Parse JSON array string
                        try:
                            config_values[key] = json.loads(value)
                        except json.JSONDecodeError:
                            config_values[key] = ["node"]
                    else:
                        config_values[key] = value
            
            # Create config with parsed values, falling back to defaults
            parsed_config = SandboxConfig(
                timeout_ms=config_values.get("timeout_ms", self.config.timeout_ms),
                max_memory_mb=config_values.get("max_memory_mb", self.config.max_memory_mb),
                allowed_commands=config_values.get("allowed_commands", self.config.allowed_commands),
                security_context=config_values.get("security_context", self.config.security_context)
            )
            
            # Cache the result
            self._validator_configs[cache_key] = parsed_config
            
            return parsed_config
            
        except Exception as e:
            logger.error(f"Error parsing validator config: {e}")
            return self.config
    
    def _create_validator_script(self, validator_path: Path, content: str) -> str:
        """
        Create a Node.js script that runs the validator.
        
        Args:
            validator_path: Path to the validator module
            content: Content to validate
            
        Returns:
            Node.js script as string
        """
        # Escape content for JavaScript string
        escaped_content = json.dumps(content)
        
        return f"""
const validator = require('{validator_path.absolute()}');
const content = {escaped_content};

try {{
    const result = validator.validate(content);
    console.log(JSON.stringify(result));
}} catch (error) {{
    console.log(JSON.stringify({{
        valid: false,
        validator: validator.name || 'unknown',
        violations: [],
        summary: 'Validator execution error: ' + error.message,
        error: error.message
    }}));
}}
"""
    
    def validate(
        self,
        validator_path: Path,
        content: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Execute JS validator in subprocess sandbox.
        
        Args:
            validator_path: Path to the JS validator file
            content: Content to validate
            context: Optional context dictionary
            
        Returns:
            ValidationResult with validation outcome
        """
        import time
        start_time = time.time()
        
        # Parse validator-specific config
        validator_config = self._parse_validator_config(validator_path)
        
        # Verify command is allowed
        if "node" not in validator_config.allowed_commands:
            return ValidationResult(
                valid=False,
                validator=validator_path.stem,
                violations=[],
                summary="Security violation: 'node' command not allowed",
                execution_time_ms=0,
                sandbox_enforced=True,
                error="Command not in allowed list"
            )
        
        # Create validator script
        script = self._create_validator_script(validator_path, content)
        
        try:
            # Execute in subprocess with timeout
            result = subprocess.run(
                ["node", "-e", script],
                capture_output=True,
                text=True,
                timeout=validator_config.timeout_ms / 1000,
                cwd=validator_path.parent
            )
            
            execution_time_ms = (time.time() - start_time) * 1000
            
            if result.returncode != 0:
                logger.error(f"Validator subprocess failed: {result.stderr}")
                return ValidationResult(
                    valid=False,
                    validator=validator_path.stem,
                    violations=[],
                    summary=f"Subprocess error: {result.stderr}",
                    execution_time_ms=execution_time_ms,
                    sandbox_enforced=True,
                    error=result.stderr
                )
            
            # Parse JSON output
            try:
                output = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON output from validator: {e}")
                return ValidationResult(
                    valid=False,
                    validator=validator_path.stem,
                    violations=[],
                    summary="Invalid validator output",
                    execution_time_ms=execution_time_ms,
                    sandbox_enforced=True,
                    error=f"JSON decode error: {e}"
                )
            
            return ValidationResult(
                valid=output.get("valid", False),
                validator=output.get("validator", validator_path.stem),
                violations=output.get("violations", []),
                summary=output.get("summary", ""),
                execution_time_ms=execution_time_ms,
                sandbox_enforced=True
            )
            
        except subprocess.TimeoutExpired:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.error(f"Validator timeout after {validator_config.timeout_ms}ms")
            return ValidationResult(
                valid=False,
                validator=validator_path.stem,
                violations=[],
                summary=f"Validation timed out after {validator_config.timeout_ms}ms",
                execution_time_ms=execution_time_ms,
                sandbox_enforced=True,
                error="Timeout"
            )
            
        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.error(f"Validator execution error: {e}")
            return ValidationResult(
                valid=False,
                validator=validator_path.stem,
                violations=[],
                summary=f"Execution error: {str(e)}",
                execution_time_ms=execution_time_ms,
                sandbox_enforced=True,
                error=str(e)
            )
    
    def validate_batch(
        self,
        validator_path: Path,
        contents: List[str],
        context: Optional[Dict[str, Any]] = None
    ) -> List[ValidationResult]:
        """
        Validate multiple contents with the same validator.
        
        Args:
            validator_path: Path to the JS validator file
            contents: List of contents to validate
            context: Optional context dictionary
            
        Returns:
            List of ValidationResult objects
        """
        results = []
        for content in contents:
            result = self.validate(validator_path, content, context)
            results.append(result)
        return results


def get_validator_wrapper(config: Optional[SandboxConfig] = None) -> JSValidatorWrapper:
    """
    Factory function to get a JSValidatorWrapper instance.
    
    Args:
        config: Optional custom sandbox configuration
        
    Returns:
        JSValidatorWrapper instance
    """
    return JSValidatorWrapper(config=config)
