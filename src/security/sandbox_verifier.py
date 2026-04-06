"""
Sandbox verification for INVAR-05.
Verifies sandbox is actually active, not just configured.
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Dict


class SandboxVerifier:
    """Verify sandbox environment is active."""
    
    def __init__(self, config: Dict):
        self.config = config
        self.execution_mode = config.get("security", {}).get("execution_mode", "trusted")
    
    def verify(self) -> Dict:
        """Run all sandbox verification checks."""
        if self.execution_mode == "trusted":
            return {
                "verified": True,
                "mode": "trusted",
                "checks": [{"name": "execution_mode", "status": "PASS", "message": "Trusted mode - no sandbox required"}]
            }
        
        checks = []
        all_passed = True
        
        # Check Docker
        docker_check = self._check_docker()
        checks.append(docker_check)
        if docker_check["status"] == "FAIL":
            all_passed = False
        
        # Check venv
        venv_check = self._check_venv()
        checks.append(venv_check)
        
        # Check permissions
        perm_check = self._check_permissions()
        checks.append(perm_check)
        
        return {
            "verified": all_passed,
            "mode": self.execution_mode,
            "checks": checks
        }
    
    def _check_docker(self) -> Dict:
        """Check if Docker is available and running."""
        if self.execution_mode != "sandbox_docker":
            return {"name": "docker", "status": "SKIP", "message": "Docker mode not configured"}
        
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return {"name": "docker", "status": "PASS", "message": "Docker daemon running"}
            else:
                return {"name": "docker", "status": "FAIL", "message": "Docker daemon not running"}
        except FileNotFoundError:
            return {"name": "docker", "status": "FAIL", "message": "Docker not installed"}
        except subprocess.TimeoutExpired:
            return {"name": "docker", "status": "FAIL", "message": "Docker check timeout"}
    
    def _check_venv(self) -> Dict:
        """Check if virtual environment is active."""
        in_venv = hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
        )
        
        if in_venv:
            return {"name": "venv", "status": "PASS", "message": f"Virtual environment: {sys.prefix}"}
        else:
            return {"name": "venv", "status": "WARN", "message": "No virtual environment active"}
    
    def _check_permissions(self) -> Dict:
        """Check filesystem permissions."""
        workspace = self.config.get("security", {}).get("workspace_path", ".")
        workspace_path = Path(workspace)
        
        can_read = workspace_path.exists() and os.access(workspace_path, os.R_OK)
        can_write = workspace_path.exists() and os.access(workspace_path, os.W_OK)
        
        if can_read and can_write:
            return {"name": "permissions", "status": "PASS", "message": "Read/write access to workspace"}
        else:
            return {"name": "permissions", "status": "FAIL", "message": f"Missing permissions: read={can_read}, write={can_write}"}


def verify_sandbox(config: Dict) -> Dict:
    """Verify sandbox configuration matches runtime state."""
    verifier = SandboxVerifier(config)
    return verifier.verify()
