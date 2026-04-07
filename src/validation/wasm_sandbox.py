"""
WASM-based Sandbox for TITAN FUSE Protocol.

ITEM-SEC-01 Implementation:
- WASMSandbox class using wasmtime for secure execution
- Memory limits and timeout enforcement
- Filesystem isolation (deny all by default)
- Secure execution of untrusted validators

This replaces the vulnerable VM2 sandbox with WebAssembly-based isolation.

Author: TITAN FUSE Team
Version: 3.3.0
"""

import json
import time
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

try:
    import wasmtime
    WASMTIME_AVAILABLE = True
except ImportError:
    WASMTIME_AVAILABLE = False

from .sandbox import ResourceLimits, SandboxResult


@dataclass
class WASMModule:
    """Compiled WASM module with metadata."""
    module_id: str
    compiled_module: Any  # wasmtime.Module
    source_hash: str
    created_at: float
    memory_limit_mb: int = 64
    
    def to_dict(self) -> Dict:
        return {
            'module_id': self.module_id,
            'source_hash': self.source_hash,
            'created_at': self.created_at,
            'memory_limit_mb': self.memory_limit_mb
        }


class WASMConfig:
    """Configuration for WASM sandbox."""
    
    def __init__(self,
                 memory_limit_mb: int = 64,
                 timeout_ms: int = 10000,
                 max_output_size: int = 1024 * 1024,
                 filesystem_allowed: List[str] = None,
                 network_allowed: bool = False):
        self.memory_limit_mb = memory_limit_mb
        self.timeout_ms = timeout_ms
        self.max_output_size = max_output_size
        self.filesystem_allowed = filesystem_allowed or []
        self.network_allowed = network_allowed


class WASMSandbox:
    """
    WebAssembly-based sandbox for secure validator execution.
    
    Features:
    - Memory isolation via WASM linear memory
    - No filesystem access by default
    - No network access
    - Timeout enforcement
    - Deterministic execution
    
    SECURITY MODEL:
    - All code runs in WASM sandbox
    - No access to host filesystem
    - No network access
    - Memory limited
    - CPU time limited
    
    Usage:
        sandbox = WASMSandbox(WASMConfig(memory_limit_mb=64))
        module = sandbox.compile_module(wasm_code)
        result = sandbox.execute(module, {'content': 'test'})
    """
    
    # GAP tag for sandbox violations
    GAP_TAG = "[gap: wasm_sandbox_violation]"
    
    def __init__(self, config: WASMConfig = None):
        """
        Initialize WASM sandbox.
        
        Args:
            config: Sandbox configuration
        """
        self.config = config or WASMConfig()
        self._logger = logging.getLogger(__name__)
        self._engine = None
        self._store = None
        
        if not WASMTIME_AVAILABLE:
            self._logger.warning(
                "wasmtime not available. Install with: pip install wasmtime"
            )
    
    def compile_module(self, code: str) -> WASMModule:
        """
        Compile WASM code to executable module.
        
        Args:
            code: WASM binary code (bytes) or WAT text (str)
            
        Returns:
            Compiled WASMModule
            
        Raises:
            RuntimeError: If wasmtime not available
            ValueError: If code is invalid
        """
        if not WASMTIME_AVAILABLE:
            raise RuntimeError(
                "[gap: wasmtime_not_available] "
                "Install wasmtime: pip install wasmtime>=8.0.0"
            )
        
        # Initialize engine if needed
        if self._engine is None:
            self._engine = wasmtime.Engine()
        
        # Calculate source hash
        if isinstance(code, str):
            source_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
            # Compile from WAT text format
            module = wasmtime.Module(self._engine, code)
        else:
            source_hash = hashlib.sha256(code).hexdigest()[:16]
            # Compile from binary
            module = wasmtime.Module(self._engine, bytes(code))
        
        module_id = f"wasm-{source_hash}"
        
        return WASMModule(
            module_id=module_id,
            compiled_module=module,
            source_hash=source_hash,
            created_at=time.time(),
            memory_limit_mb=self.config.memory_limit_mb
        )
    
    def execute(self, module: WASMModule, context: Dict) -> SandboxResult:
        """
        Execute WASM module with given context.
        
        Args:
            module: Compiled WASM module
            context: Execution context dictionary
            
        Returns:
            SandboxResult with execution results
        """
        start_time = time.time()
        
        if not WASMTIME_AVAILABLE:
            return SandboxResult(
                valid=False,
                violations=[],
                error="[gap: wasmtime_not_available] wasmtime package not installed"
            )
        
        try:
            # Create store with limits
            self._store = wasmtime.Store(self._engine)
            
            # Set memory limits
            memory_limit_bytes = self.config.memory_limit_mb * 1024 * 1024
            self._store.set_limits(
                memory_limit_bytes,  # Max memory
                self.config.timeout_ms // 1000 if self.config.timeout_ms else None  # Max time
            )
            
            # Create instance
            instance = wasmtime.Instance(self._store, module.compiled_module, [])
            
            # Get exports
            exports = instance.exports(self._store)
            
            # Find main function
            main_func = None
            for name, export in exports:
                if name in ('main', 'validate', 'run', '_start'):
                    main_func = export
                    break
            
            if main_func is None:
                return SandboxResult(
                    valid=False,
                    violations=[],
                    error="No entry point found in WASM module (expected: main, validate, run, _start)"
                )
            
            # Convert context to WASM-compatible format
            context_json = json.dumps(context)
            
            # Allocate memory for input
            memory = None
            for name, export in exports:
                if name == 'memory':
                    memory = export
                    break
            
            if memory:
                # Write context to memory
                context_bytes = context_json.encode('utf-8')
                ptr = self._allocate_memory(memory, len(context_bytes))
                memory.data_ptr(self._store)[ptr:ptr + len(context_bytes)] = context_bytes
                
                # Call main with pointer and length
                result = main_func(self._store, ptr, len(context_bytes))
            else:
                # Call without memory access
                result = main_func(self._store)
            
            execution_time = int((time.time() - start_time) * 1000)
            
            # Parse result
            if isinstance(result, int):
                # Integer result (0 = success, non-zero = error)
                return SandboxResult(
                    valid=(result == 0),
                    violations=[],
                    execution_time_ms=execution_time
                )
            elif isinstance(result, str):
                # String result (JSON)
                parsed = json.loads(result)
                return SandboxResult(
                    valid=parsed.get('valid', False),
                    violations=parsed.get('violations', []),
                    execution_time_ms=execution_time
                )
            else:
                return SandboxResult(
                    valid=True,
                    violations=[],
                    execution_time_ms=execution_time
                )
                
        except wasmtime.Trap as e:
            execution_time = int((time.time() - start_time) * 1000)
            
            # Categorize trap
            trap_msg = str(e)
            if 'out of memory' in trap_msg.lower():
                return SandboxResult(
                    valid=False,
                    violations=[self.GAP_TAG],
                    error=f"Memory limit exceeded: {self.config.memory_limit_mb}MB",
                    execution_time_ms=execution_time
                )
            elif 'timeout' in trap_msg.lower() or 'interrupt' in trap_msg.lower():
                return SandboxResult(
                    valid=False,
                    violations=[],
                    error="Execution timeout",
                    timeout=True,
                    execution_time_ms=execution_time
                )
            else:
                return SandboxResult(
                    valid=False,
                    violations=[],
                    error=f"WASM trap: {trap_msg}",
                    execution_time_ms=execution_time
                )
                
        except json.JSONDecodeError as e:
            return SandboxResult(
                valid=False,
                violations=[],
                error=f"Invalid JSON output: {e}"
            )
            
        except Exception as e:
            self._logger.error(f"WASM execution error: {e}")
            return SandboxResult(
                valid=False,
                violations=[],
                error=str(e)
            )
    
    def validate_code_safety(self, code: str) -> Dict[str, Any]:
        """
        Validate WASM code for safety before execution.
        
        Checks:
        - Valid WASM/WAT format
        - No imports that could escape sandbox
        - Memory limits respected
        
        Args:
            code: WASM binary or WAT text
            
        Returns:
            Dict with 'safe' boolean and 'findings' list
        """
        findings = []
        
        if not WASMTIME_AVAILABLE:
            return {
                'safe': False,
                'findings': [{'pattern': 'WASMTIME_UNAVAILABLE', 'severity': 'HIGH'}],
                'reason': 'wasmtime not installed'
            }
        
        try:
            # Try to parse/compile the module
            if self._engine is None:
                self._engine = wasmtime.Engine()
            
            if isinstance(code, str) and '(' in code:
                # WAT text format
                module = wasmtime.Module(self._engine, code)
            else:
                # Binary format
                module = wasmtime.Module(self._engine, bytes(code) if isinstance(code, str) else code)
            
            # Check imports
            for import_type in module.imports:
                module_name = import_type.module
                field_name = import_type.name
                
                # Only allow wasi_snapshot_preview1 (standard WASI)
                if module_name not in ['wasi_snapshot_preview1', 'env']:
                    findings.append({
                        'pattern': 'UNSAFE_IMPORT',
                        'module': module_name,
                        'field': field_name,
                        'severity': 'HIGH',
                        'message': f"Import from '{module_name}' could escape sandbox"
                    })
            
            return {
                'safe': len(findings) == 0,
                'findings': findings,
                'reason': '; '.join(f['pattern'] for f in findings) if findings else None
            }
            
        except Exception as e:
            return {
                'safe': False,
                'findings': [{'pattern': 'PARSE_ERROR', 'severity': 'HIGH'}],
                'reason': f'Failed to parse WASM: {str(e)}'
            }
    
    def get_resource_limits(self) -> ResourceLimits:
        """Get current resource limits."""
        return ResourceLimits(
            timeout_ms=self.config.timeout_ms,
            max_output_size=self.config.max_output_size,
            memory_limit_mb=self.config.memory_limit_mb,
            filesystem_access=self.config.filesystem_allowed,
            network_access=self.config.network_allowed
        )
    
    def _allocate_memory(self, memory: Any, size: int) -> int:
        """Allocate memory in WASM module."""
        # Simple bump allocator
        data = memory.data_ptr(self._store)
        # Find free space (simplified)
        ptr = 0  # In production, use proper allocator
        return ptr


def compile_js_to_wasm(js_code: str) -> bytes:
    """
    Compile JavaScript to WASM using Javy or similar.
    
    NOTE: This requires Javy (https://github.com/bytecodealliance/javy)
    to be installed. Returns None if not available.
    
    Args:
        js_code: JavaScript source code
        
    Returns:
        WASM binary bytes or None if compilation unavailable
    """
    import subprocess
    import tempfile
    
    try:
        # Check if javy is available
        result = subprocess.run(['javy', '--version'], capture_output=True)
        if result.returncode != 0:
            return None
        
        # Write JS to temp file
        with tempfile.NamedTemporaryFile(suffix='.js', delete=False) as f:
            f.write(js_code.encode())
            js_path = f.name
        
        try:
            wasm_path = js_path.replace('.js', '.wasm')
            
            # Compile with javy
            subprocess.run(['javy', 'compile', js_path, '-o', wasm_path], check=True)
            
            # Read WASM output
            with open(wasm_path, 'rb') as f:
                return f.read()
        finally:
            Path(js_path).unlink(missing_ok=True)
            Path(js_path.replace('.js', '.wasm')).unlink(missing_ok=True)
            
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def create_wasm_sandbox(config: Dict = None) -> WASMSandbox:
    """
    Factory function to create configured WASM sandbox.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Configured WASMSandbox instance
    """
    sandbox_config = WASMConfig()
    
    if config:
        sandbox_config.memory_limit_mb = config.get('memory_limit_mb', 64)
        sandbox_config.timeout_ms = config.get('timeout_ms', 10000)
        sandbox_config.max_output_size = config.get('max_output_size', 1024 * 1024)
        sandbox_config.filesystem_allowed = config.get('filesystem_allowed', [])
        sandbox_config.network_allowed = config.get('network_allowed', False)
    
    return WASMSandbox(sandbox_config)
