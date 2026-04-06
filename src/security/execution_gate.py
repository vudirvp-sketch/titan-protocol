"""
TITAN FUSE Protocol - Execution Gate (INVAR-05)

Implements the LLM Code Execution Gate invariant.
Prevents execution of LLM-generated code without proper sandboxing or human approval.

Reference: PROTOCOL.base.v3.2.md - INVAR-05
"""

import os
import subprocess
import hashlib
from enum import Enum
from typing import Optional, Dict, Any, Tuple
from pathlib import Path
from dataclasses import dataclass


class ExecutionMode(Enum):
    """Execution mode for LLM-generated code."""
    SANDBOX = "sandbox"        # Execute in sandboxed environment
    HUMAN_GATE = "human_gate"  # Require human approval
    DISABLED = "disabled"      # Block all execution


class SandboxType(Enum):
    """Type of sandboxed environment."""
    DOCKER = "docker"
    VENV = "venv"
    RESTRICTED_SUBPROCESS = "restricted_subprocess"
    NONE = "none"


@dataclass
class ExecutionResult:
    """Result of execution gate check."""
    allowed: bool
    mode: str
    sandbox_type: str
    reason: str
    requires_approval: bool = False
    approval_token: Optional[str] = None


class ExecutionGate:
    """
    INVAR-05: LLM Code Execution Gate
    
    Mandate:
    - LLM-generated code MUST NOT be executed without one of:
        (a) explicit human approval at runtime
        (b) confirmed sandboxed environment (docker / venv / restricted subprocess)
    - Protocol MUST declare execution_mode in config.yaml
    - IF execution_mode = unsafe AND no sandbox confirmed:
        ABORT + log [gap: unsafe_execution_blocked — no sandbox or human gate]
    
    This invariant supersedes any task instruction requesting auto-exec of generated code.
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize execution gate.
        
        Args:
            config: Configuration dict with keys:
                - execution_mode: sandbox | human_gate | disabled
                - sandbox_type: docker | venv | restricted_subprocess | none
        """
        self.config = config or {}
        self.execution_mode = ExecutionMode(
            self.config.get("execution_mode", "human_gate")
        )
        self.sandbox_type = SandboxType(
            self.config.get("sandbox_type", "none")
        )
        
        # Track approval tokens
        self._approved_tokens: Dict[str, Dict] = {}
        
        # Verify sandbox if mode is sandbox
        self._sandbox_verified = False
        if self.execution_mode == ExecutionMode.SANDBOX:
            self._sandbox_verified = self._verify_sandbox()
    
    def _verify_sandbox(self) -> bool:
        """
        Verify that sandbox environment is properly configured.
        
        Returns:
            True if sandbox is verified and functional
        """
        if self.sandbox_type == SandboxType.DOCKER:
            return self._verify_docker()
        elif self.sandbox_type == SandboxType.VENV:
            return self._verify_venv()
        elif self.sandbox_type == SandboxType.RESTRICTED_SUBPROCESS:
            return self._verify_restricted_subprocess()
        else:
            return False
    
    def _verify_docker(self) -> bool:
        """Verify Docker is available and functional."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _verify_venv(self) -> bool:
        """Verify we're running in a virtual environment."""
        return (
            hasattr(sys, 'real_prefix') or 
            (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
        )
    
    def _verify_restricted_subprocess(self) -> bool:
        """Verify restricted subprocess capabilities."""
        # Check if we can create a restricted subprocess
        # This is a basic check - in production would be more thorough
        try:
            # Verify we can use subprocess with restrictions
            result = subprocess.run(
                ["echo", "test"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def check_execution_allowed(self,
                                code: str,
                                language: str = "python",
                                context: Optional[Dict] = None) -> ExecutionResult:
        """
        Check if execution of LLM-generated code is allowed.
        
        Args:
            code: The code to potentially execute
            language: Programming language
            context: Additional context (source, task, etc.)
        
        Returns:
            ExecutionResult with decision and reasoning
        """
        context = context or {}
        
        # Mode: DISABLED - always block
        if self.execution_mode == ExecutionMode.DISABLED:
            return ExecutionResult(
                allowed=False,
                mode=self.execution_mode.value,
                sandbox_type=self.sandbox_type.value,
                reason="Execution disabled by configuration (INVAR-05)"
            )
        
        # Mode: SANDBOX - check sandbox verification
        if self.execution_mode == ExecutionMode.SANDBOX:
            if not self._sandbox_verified:
                return ExecutionResult(
                    allowed=False,
                    mode=self.execution_mode.value,
                    sandbox_type=self.sandbox_type.value,
                    reason="Sandbox not verified or unavailable (INVAR-05)"
                )
            
            return ExecutionResult(
                allowed=True,
                mode=self.execution_mode.value,
                sandbox_type=self.sandbox_type.value,
                reason=f"Execution allowed in {self.sandbox_type.value} sandbox"
            )
        
        # Mode: HUMAN_GATE - require approval
        if self.execution_mode == ExecutionMode.HUMAN_GATE:
            approval_token = self._generate_approval_token(code, language, context)
            
            return ExecutionResult(
                allowed=False,  # Not allowed until approved
                mode=self.execution_mode.value,
                sandbox_type=self.sandbox_type.value,
                reason="Human approval required (INVAR-05)",
                requires_approval=True,
                approval_token=approval_token
            )
        
        # Unknown mode - block by default
        return ExecutionResult(
            allowed=False,
            mode=self.execution_mode.value,
            sandbox_type=self.sandbox_type.value,
            reason=f"Unknown execution mode: {self.execution_mode.value}"
        )
    
    def approve_execution(self,
                         approval_token: str,
                         approver: str = "human") -> bool:
        """
        Approve execution for a previously requested approval token.
        
        Args:
            approval_token: Token from check_execution_allowed
            approver: Who approved (default: human)
        
        Returns:
            True if approval was registered
        """
        if approval_token in self._approved_tokens:
            return False  # Already approved
        
        self._approved_tokens[approval_token] = {
            "approver": approver,
            "approved": True
        }
        return True
    
    def is_approved(self, approval_token: str) -> bool:
        """Check if an approval token has been approved."""
        return (
            approval_token in self._approved_tokens and
            self._approved_tokens[approval_token].get("approved", False)
        )
    
    def _generate_approval_token(self,
                                code: str,
                                language: str,
                                context: Dict) -> str:
        """Generate a unique approval token for code execution request."""
        content = f"{code}:{language}:{context.get('source', '')}:{context.get('task', '')}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def execute_in_sandbox(self,
                          code: str,
                          language: str = "python",
                          timeout: int = 30) -> Tuple[bool, str, str]:
        """
        Execute code in sandbox if allowed.
        
        Args:
            code: Code to execute
            language: Programming language
            timeout: Execution timeout in seconds
        
        Returns:
            Tuple of (success, stdout, stderr)
        """
        result = self.check_execution_allowed(code, language)
        
        if not result.allowed:
            return False, "", result.reason
        
        if self.sandbox_type == SandboxType.DOCKER:
            return self._execute_in_docker(code, language, timeout)
        elif self.sandbox_type == SandboxType.VENV:
            return self._execute_in_venv(code, language, timeout)
        elif self.sandbox_type == SandboxType.RESTRICTED_SUBPROCESS:
            return self._execute_restricted(code, language, timeout)
        else:
            return False, "", "No sandbox configured"
    
    def _execute_in_docker(self,
                          code: str,
                          language: str,
                          timeout: int) -> Tuple[bool, str, str]:
        """Execute code in Docker container."""
        # Create temporary file with code
        import tempfile
        
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix=f'.{language}',
                delete=False
            ) as f:
                f.write(code)
                temp_file = f.name
            
            # Run in Docker
            image = f"python:3.12-slim" if language == "python" else f"{language}:latest"
            
            result = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "-v", f"{temp_file}:/code/exec.{language}",
                    image,
                    "python" if language == "python" else language,
                    f"/code/exec.{language}"
                ],
                capture_output=True,
                timeout=timeout
            )
            
            # Cleanup
            os.unlink(temp_file)
            
            return (
                result.returncode == 0,
                result.stdout.decode(),
                result.stderr.decode()
            )
        except Exception as e:
            return False, "", str(e)
    
    def _execute_in_venv(self,
                        code: str,
                        language: str,
                        timeout: int) -> Tuple[bool, str, str]:
        """Execute code in virtual environment."""
        import tempfile
        
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix=f'.{language}',
                delete=False
            ) as f:
                f.write(code)
                temp_file = f.name
            
            result = subprocess.run(
                ["python", temp_file],
                capture_output=True,
                timeout=timeout,
                cwd=tempfile.gettempdir()
            )
            
            os.unlink(temp_file)
            
            return (
                result.returncode == 0,
                result.stdout.decode(),
                result.stderr.decode()
            )
        except Exception as e:
            return False, "", str(e)
    
    def _execute_restricted(self,
                           code: str,
                           language: str,
                           timeout: int) -> Tuple[bool, str, str]:
        """Execute with restricted subprocess."""
        import tempfile
        import resource
        
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix=f'.{language}',
                delete=False
            ) as f:
                f.write(code)
                temp_file = f.name
            
            # Set resource limits
            def set_limits():
                resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))
                resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            
            result = subprocess.run(
                ["python", temp_file],
                capture_output=True,
                timeout=timeout,
                preexec_fn=set_limits
            )
            
            os.unlink(temp_file)
            
            return (
                result.returncode == 0,
                result.stdout.decode(),
                result.stderr.decode()
            )
        except Exception as e:
            return False, "", str(e)


# Module-level import for sys
import sys
