#!/usr/bin/env python3
"""
TITAN FUSE Protocol - INVAR-05 Execution Gate
Version: 1.0.0

Implements the execution_mode gate mandated by INVAR-05:
- human_gate: Requires explicit approval token before code execution
- sandbox: Requires confirmed sandboxed environment
- disabled: Blocks all code execution

This module prevents LLM-generated code from being executed without
proper authorization, protecting the host runtime from arbitrary code injection.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import uuid


class ExecutionMode(Enum):
    """Execution modes as defined in INVAR-05."""
    HUMAN_GATE = "human_gate"  # Requires approval token
    HUMAN = "human"            # Alias for human_gate (PLAN A compatibility)
    SANDBOX = "sandbox"         # Requires sandbox confirmation
    DISABLED = "disabled"       # No execution allowed
    TRUSTED = "trusted"         # No restrictions (development mode)


class SandboxType(Enum):
    """Supported sandbox types."""
    DOCKER = "docker"
    VENV = "venv"
    RESTRICTED_SUBPROCESS = "restricted_subprocess"
    NONE = "none"


@dataclass
class ApprovalToken:
    """Approval token for code execution."""
    token_id: str
    created_at: datetime
    expires_at: datetime
    code_hash: str
    approved_by: str  # "interactive" or callback identifier
    scope: str  # "single" or "session"
    used: bool = False


@dataclass
class ExecutionRequest:
    """Request to execute generated code."""
    request_id: str
    code: str
    language: str
    context: Dict
    requested_at: datetime
    source_chunk: Optional[str] = None


@dataclass
class ExecutionResult:
    """Result of an execution gate check."""
    allowed: bool
    reason: str
    token_id: Optional[str] = None
    sandbox_verified: bool = False
    warning: Optional[str] = None


class ExecutionGate:
    """
    INVAR-05 Execution Gate implementation.
    
    Usage:
        gate = ExecutionGate(config)
        
        # Before executing code
        result = gate.check_execution(code, language="python")
        if result.allowed:
            # Safe to execute
            output = gate.execute_sandboxed(code, language="python")
        else:
            # Log and block
            print(f"Execution blocked: {result.reason}")
    """
    
    MAX_TOKEN_AGE_HOURS = 24
    MAX_SINGLE_USE_TOKENS = 100  # Per session
    DANGEROUS_PATTERNS = [
        # Python
        r"import\s+os",
        r"import\s+subprocess",
        r"import\s+sys",
        r"exec\s*\(",
        r"eval\s*\(",
        r"__import__",
        r"open\s*\([^)]*,\s*['\"]w",
        r"shutil\.rmtree",
        r"os\.system",
        r"os\.popen",
        r"subprocess\.(run|call|Popen)",
        # Shell
        r"rm\s+-rf",
        r"sudo\s+",
        r"chmod\s+",
        r"chown\s+",
        r">\s*/dev/",
        r"mkfs",
        r"dd\s+if=",
        # JavaScript
        r"require\s*\(\s*['\"]child_process",
        r"eval\s*\(",
        r"Function\s*\(",
    ]
    
    # Mode aliases for backward compatibility
    MODE_ALIASES = {
        "human": "human_gate",
        "human_gate": "human_gate",
        "sandbox": "sandbox",
        "disabled": "disabled",
        "trusted": "trusted",
    }
    
    def __init__(self, config: Dict):
        """
        Initialize execution gate with configuration.
        
        Args:
            config: Configuration dict from config.yaml
        """
        mode_str = config.get("security", {}).get("execution_mode", "human_gate")
        # Resolve mode with alias support
        resolved_mode = self.MODE_ALIASES.get(mode_str, mode_str)
        try:
            self.mode = ExecutionMode(resolved_mode)
        except ValueError:
            # Fallback to human_gate for unknown modes
            self.mode = ExecutionMode.HUMAN_GATE
        self.sandbox_type = SandboxType(
            config.get("security", {}).get("sandbox_type", "none")
        )
        
        # Token storage (in production, use secure storage)
        self.tokens: Dict[str, ApprovalToken] = {}
        self.session_tokens_used = 0
        
        # Execution log
        self.execution_log: List[Dict] = []
        
        # Sandbox verification cache
        self._sandbox_verified = False
        self._sandbox_verification_time: Optional[datetime] = None
    
    def check_execution(self, 
                        code: str, 
                        language: str = "python",
                        context: Optional[Dict] = None) -> ExecutionResult:
        """
        Check if code execution is allowed per INVAR-05.
        
        Args:
            code: Code to execute
            language: Programming language
            context: Additional context (chunk_id, etc.)
            
        Returns:
            ExecutionResult with allow/deny decision
        """
        # Mode: DISABLED - Always block
        if self.mode == ExecutionMode.DISABLED:
            self._log_execution_attempt(code, language, blocked=True, reason="disabled_mode")
            return ExecutionResult(
                allowed=False,
                reason="Execution mode is DISABLED. No code execution permitted."
            )
        
        # Mode: TRUSTED - Allow all execution (development mode)
        if self.mode == ExecutionMode.TRUSTED:
            warning = self._check_dangerous_patterns(code, language)
            self._log_execution_attempt(code, language, blocked=False, reason="trusted_mode")
            return ExecutionResult(
                allowed=True,
                reason="Execution allowed in TRUSTED mode (development)",
                warning=warning
            )
        
        # Mode: HUMAN (alias for HUMAN_GATE)
        if self.mode == ExecutionMode.HUMAN:
            # Same as HUMAN_GATE
            self.mode = ExecutionMode.HUMAN_GATE
            # Fall through to HUMAN_GATE handling
        
        # Mode: SANDBOX - Verify sandbox
        if self.mode == ExecutionMode.SANDBOX:
            sandbox_ok, sandbox_msg = self._verify_sandbox()
            if not sandbox_ok:
                self._log_execution_attempt(code, language, blocked=True, reason="sandbox_not_verified")
                return ExecutionResult(
                    allowed=False,
                    reason=f"Sandbox verification failed: {sandbox_msg}",
                    sandbox_verified=False
                )
            
            # Sandbox verified, check for dangerous patterns
            warning = self._check_dangerous_patterns(code, language)
            self._log_execution_attempt(code, language, blocked=False, reason="sandbox_approved")
            return ExecutionResult(
                allowed=True,
                reason="Execution approved via sandbox",
                sandbox_verified=True,
                warning=warning
            )
        
        # Mode: HUMAN_GATE - Require approval token
        if self.mode == ExecutionMode.HUMAN_GATE:
            code_hash = self._hash_code(code, language)
            
            # Check for existing valid token
            existing_token = self._find_valid_token(code_hash)
            if existing_token:
                self._log_execution_attempt(code, language, blocked=False, reason="token_reused")
                return ExecutionResult(
                    allowed=True,
                    reason="Execution approved via existing token",
                    token_id=existing_token.token_id
                )
            
            # No valid token - need approval
            self._log_execution_attempt(code, language, blocked=True, reason="no_token")
            return ExecutionResult(
                allowed=False,
                reason="No valid approval token. Request approval before execution.",
                warning=self._check_dangerous_patterns(code, language)
            )
        
        # Unknown mode - fail safe with clear error
        return ExecutionResult(
            allowed=False,
            reason=f"Unknown execution mode: {self.mode}. Valid modes: human, human_gate, sandbox, disabled, trusted"
        )
    
    def request_approval(self,
                         code: str,
                         language: str = "python",
                         context: Optional[Dict] = None,
                         scope: str = "single") -> Dict:
        """
        Request approval for code execution.
        
        Returns approval request with token that needs to be confirmed.
        
        Args:
            code: Code to execute
            language: Programming language
            context: Additional context
            scope: "single" or "session"
            
        Returns:
            Dict with request details
        """
        if self.session_tokens_used >= self.MAX_SINGLE_USE_TOKENS:
            return {
                "success": False,
                "error": "Maximum tokens per session exceeded",
                "max_tokens": self.MAX_SINGLE_USE_TOKENS
            }
        
        code_hash = self._hash_code(code, language)
        request_id = str(uuid.uuid4())[:8]
        
        # Create pending token
        token = ApprovalToken(
            token_id=f"tok_{request_id}",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=self.MAX_TOKEN_AGE_HOURS),
            code_hash=code_hash,
            approved_by="",  # Will be set on confirm
            scope=scope
        )
        
        self.tokens[token.token_id] = token
        
        return {
            "success": True,
            "request_id": request_id,
            "token_id": token.token_id,
            "code_hash": code_hash,
            "code_preview": code[:200] + "..." if len(code) > 200 else code,
            "language": language,
            "scope": scope,
            "expires_at": token.expires_at.isoformat(),
            "warning": self._check_dangerous_patterns(code, language),
            "message": "Token created. Call confirm_approval() to activate."
        }
    
    def confirm_approval(self, 
                         token_id: str, 
                         approved_by: str = "interactive") -> Dict:
        """
        Confirm approval for a pending token.
        
        Args:
            token_id: Token to confirm
            approved_by: Who approved (interactive, callback_id, etc.)
            
        Returns:
            Dict with confirmation result
        """
        if token_id not in self.tokens:
            return {"success": False, "error": "Token not found"}
        
        token = self.tokens[token_id]
        
        if token.used:
            return {"success": False, "error": "Token already used"}
        
        if datetime.utcnow() > token.expires_at:
            return {"success": False, "error": "Token expired"}
        
        # Activate token
        token.approved_by = approved_by
        
        # For single-use tokens, increment counter
        if token.scope == "single":
            self.session_tokens_used += 1
        
        return {
            "success": True,
            "token_id": token_id,
            "approved_by": approved_by,
            "scope": token.scope,
            "message": "Token activated. Code execution now allowed."
        }
    
    def execute_sandboxed(self, 
                          code: str, 
                          language: str = "python",
                          timeout: int = 30) -> Dict:
        """
        Execute code in sandboxed environment.
        
        This method should only be called after check_execution() returns allowed=True.
        
        Args:
            code: Code to execute
            language: Programming language
            timeout: Execution timeout in seconds
            
        Returns:
            Dict with execution result
        """
        # Verify execution is allowed
        result = self.check_execution(code, language)
        if not result.allowed:
            return {
                "success": False,
                "error": f"Execution not allowed: {result.reason}",
                "output": None
            }
        
        # Mark token as used if applicable
        if result.token_id and result.token_id in self.tokens:
            token = self.tokens[result.token_id]
            if token.scope == "single":
                token.used = True
        
        try:
            if language == "python":
                return self._execute_python_sandboxed(code, timeout)
            elif language in ("bash", "shell", "sh"):
                return self._execute_shell_sandboxed(code, timeout)
            elif language == "javascript":
                return self._execute_javascript_sandboxed(code, timeout)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported language: {language}",
                    "output": None
                }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Execution timed out after {timeout} seconds",
                "output": None
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "output": None
            }
    
    def _execute_python_sandboxed(self, code: str, timeout: int) -> Dict:
        """Execute Python code in restricted environment."""
        if self.sandbox_type == SandboxType.DOCKER:
            # Docker execution
            return self._execute_in_docker(code, "python", timeout)
        elif self.sandbox_type == SandboxType.VENV:
            # Venv execution with restrictions
            return self._execute_in_venv(code, timeout)
        elif self.sandbox_type == SandboxType.RESTRICTED_SUBPROCESS:
            # Restricted subprocess
            return self._execute_restricted(code, "python", timeout)
        else:
            # No sandbox - this should have been caught by check_execution
            return {
                "success": False,
                "error": "No sandbox configured but mode is SANDBOX",
                "output": None
            }
    
    def _execute_shell_sandboxed(self, code: str, timeout: int) -> Dict:
        """Execute shell code with restrictions."""
        # Always use restricted subprocess for shell
        return self._execute_restricted(code, "bash", timeout)
    
    def _execute_javascript_sandboxed(self, code: str, timeout: int) -> Dict:
        """Execute JavaScript code in sandboxed environment."""
        if self.sandbox_type == SandboxType.DOCKER:
            return self._execute_in_docker(code, "node", timeout)
        else:
            return {
                "success": False,
                "error": "JavaScript execution requires Docker sandbox",
                "output": None
            }
    
    def _execute_in_docker(self, code: str, runtime: str, timeout: int) -> Dict:
        """Execute code in Docker container."""
        try:
            # Create temporary container
            container_name = f"titan_exec_{uuid.uuid4().hex[:8]}"
            
            # Write code to stdin
            result = subprocess.run(
                ["docker", "run", "--rm", "--network=none", 
                 "-i", f"{runtime}:alpine", runtime, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else None,
                "return_code": result.returncode
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": "Docker not available",
                "output": None
            }
    
    def _execute_in_venv(self, code: str, timeout: int) -> Dict:
        """Execute Python code in virtual environment."""
        # Restricted builtins
        safe_builtins = {
            'print': print,
            'len': len,
            'range': range,
            'str': str,
            'int': int,
            'float': float,
            'list': list,
            'dict': dict,
            'tuple': tuple,
            'bool': bool,
            'None': None,
            'True': True,
            'False': False,
        }
        
        try:
            # Create restricted globals
            restricted_globals = {'__builtins__': safe_builtins}
            
            # Execute with timeout (simplified - real impl would use signal or multiprocessing)
            exec_result = {}
            exec(code, restricted_globals, exec_result)
            
            return {
                "success": True,
                "output": str(exec_result) if exec_result else "No output",
                "error": None
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "output": None
            }
    
    def _execute_restricted(self, code: str, language: str, timeout: int) -> Dict:
        """Execute with restricted subprocess."""
        if language == "python":
            cmd = ["python3", "-c", code]
        elif language == "bash":
            cmd = ["bash", "-c", code]
        else:
            return {"success": False, "error": f"Unknown language: {language}"}
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                # Security restrictions
                env={},  # Empty environment
                cwd="/tmp",  # Safe working directory
            )
            
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else None,
                "return_code": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timeout", "output": None}
    
    def _verify_sandbox(self) -> Tuple[bool, str]:
        """Verify sandbox environment is properly configured."""
        if self._sandbox_verified and self._sandbox_verification_time:
            # Cache verification for 1 hour
            if datetime.utcnow() - self._sandbox_verification_time < timedelta(hours=1):
                return True, "Sandbox verified (cached)"
        
        if self.sandbox_type == SandboxType.NONE:
            return False, "No sandbox configured"
        
        if self.sandbox_type == SandboxType.DOCKER:
            try:
                result = subprocess.run(
                    ["docker", "info"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    self._sandbox_verified = True
                    self._sandbox_verification_time = datetime.utcnow()
                    return True, "Docker available and running"
                return False, "Docker not running"
            except FileNotFoundError:
                return False, "Docker not installed"
            except subprocess.TimeoutExpired:
                return False, "Docker not responding"
        
        if self.sandbox_type == SandboxType.VENV:
            # Check if we're in a venv
            in_venv = hasattr(sys, 'real_prefix') or (
                hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
            )
            if in_venv:
                self._sandbox_verified = True
                self._sandbox_verification_time = datetime.utcnow()
                return True, "Running in virtual environment"
            return False, "Not running in virtual environment"
        
        if self.sandbox_type == SandboxType.RESTRICTED_SUBPROCESS:
            # Restricted subprocess is always available
            self._sandbox_verified = True
            self._sandbox_verification_time = datetime.utcnow()
            return True, "Restricted subprocess available"
        
        return False, f"Unknown sandbox type: {self.sandbox_type}"
    
    def _hash_code(self, code: str, language: str) -> str:
        """Create hash of code for token verification."""
        combined = f"{language}:{code}"
        return hashlib.sha256(combined.encode()).hexdigest()[:32]
    
    def _find_valid_token(self, code_hash: str) -> Optional[ApprovalToken]:
        """Find a valid unused token for the given code hash."""
        now = datetime.utcnow()
        
        for token in self.tokens.values():
            if (token.code_hash == code_hash and 
                not token.used and 
                token.expires_at > now):
                return token
        
        return None
    
    def _check_dangerous_patterns(self, code: str, language: str) -> Optional[str]:
        """Check for potentially dangerous code patterns."""
        import re
        
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                return f"Warning: Potentially dangerous pattern detected: {pattern}"
        
        return None
    
    def _log_execution_attempt(self, 
                               code: str, 
                               language: str, 
                               blocked: bool, 
                               reason: str) -> None:
        """Log execution attempt for audit."""
        self.execution_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "code_hash": self._hash_code(code, language),
            "language": language,
            "blocked": blocked,
            "reason": reason,
            "mode": self.mode.value
        })
    
    def get_execution_log(self) -> List[Dict]:
        """Get execution log for audit."""
        return self.execution_log.copy()
    
    def get_stats(self) -> Dict:
        """Get execution gate statistics."""
        return {
            "mode": self.mode.value,
            "sandbox_type": self.sandbox_type.value,
            "sandbox_verified": self._sandbox_verified,
            "tokens_issued": len(self.tokens),
            "tokens_used": sum(1 for t in self.tokens.values() if t.used),
            "session_tokens_used": self.session_tokens_used,
            "execution_attempts": len(self.execution_log),
            "blocked_attempts": sum(1 for e in self.execution_log if e["blocked"])
        }


# GATE_MODES mapping for external reference (PLAN A ITEM_A001)
GATE_MODES = {
    "human": "human_gate",
    "human_gate": "human_gate",
    "sandbox": "sandbox",
    "disabled": "disabled",
    "trusted": "trusted",
}


def resolve_gate(mode: str) -> ExecutionMode:
    """
    Resolve a mode string to an ExecutionMode enum.
    
    PLAN A ITEM_A001: Provides proper gate resolution with fallback.
    
    Args:
        mode: Mode string (human, human_gate, sandbox, disabled, trusted)
        
    Returns:
        ExecutionMode enum value
        
    Raises:
        ValueError: If mode is not recognized and no fallback available
    """
    resolved = GATE_MODES.get(mode)
    if resolved:
        return ExecutionMode(resolved)
    # Fallback to human_gate for safety
    raise ValueError(
        f"Unknown execution mode: '{mode}'. "
        f"Valid modes: {list(GATE_MODES.keys())}"
    )


# Convenience function for quick execution check
def check_execution_allowed(config: Dict, code: str, language: str = "python") -> Tuple[bool, str]:
    """
    Quick check if execution is allowed.
    
    Args:
        config: Configuration dict
        code: Code to execute
        language: Programming language
        
    Returns:
        Tuple of (allowed, reason)
    """
    gate = ExecutionGate(config)
    result = gate.check_execution(code, language)
    return result.allowed, result.reason


if __name__ == "__main__":
    # Demo/test
    print("=" * 60)
    print("INVAR-05 Execution Gate Test")
    print("=" * 60)
    
    # Test config
    test_config = {
        "security": {
            "execution_mode": "human_gate",
            "sandbox_type": "none"
        }
    }
    
    gate = ExecutionGate(test_config)
    
    # Test 1: Check without token
    print("\n[TEST 1] Check execution without token:")
    code = "print('Hello, World!')"
    result = gate.check_execution(code, "python")
    print(f"  Allowed: {result.allowed}")
    print(f"  Reason: {result.reason}")
    
    # Test 2: Request approval
    print("\n[TEST 2] Request approval:")
    approval = gate.request_approval(code, "python")
    print(f"  Token ID: {approval.get('token_id')}")
    print(f"  Code Preview: {approval.get('code_preview')}")
    
    # Test 3: Confirm approval
    print("\n[TEST 3] Confirm approval:")
    if approval.get("success"):
        confirm = gate.confirm_approval(approval["token_id"], "test_user")
        print(f"  Confirmed: {confirm.get('success')}")
        print(f"  Message: {confirm.get('message')}")
    
    # Test 4: Check with token
    print("\n[TEST 4] Check execution with token:")
    result = gate.check_execution(code, "python")
    print(f"  Allowed: {result.allowed}")
    print(f"  Reason: {result.reason}")
    print(f"  Token: {result.token_id}")
    
    # Stats
    print("\n[STATS]")
    print(json.dumps(gate.get_stats(), indent=2))
