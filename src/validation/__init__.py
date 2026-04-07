# TITAN FUSE Protocol - Validation Module
"""
Validator dependency management and sandboxing.

ITEM-SEC-01: Multiple sandbox implementations:
- ValidatorSandbox: Subprocess isolation (default for Python)
- WASMSandbox: WebAssembly-based isolation for JS validators
- GVisorSandbox: Container-based isolation for heavy workloads
"""

from .validator_dag import ValidatorDAG, ValidationResult
from .sandbox import ValidatorSandbox, SandboxResult, ResourceLimits, get_sandbox

# ITEM-SEC-01: WASM and gVisor sandbox implementations
try:
    from .wasm_sandbox import WASMSandbox, WASMConfig, WASMModule, create_wasm_sandbox
    WASM_AVAILABLE = True
except ImportError:
    WASM_AVAILABLE = False
    WASMSandbox = None
    WASMConfig = None
    WASMModule = None
    create_wasm_sandbox = None

try:
    from .gvisor_sandbox import GVisorSandbox, GVisorConfig, create_gvisor_sandbox
    GVSIOR_AVAILABLE = True
except ImportError:
    GVSIOR_AVAILABLE = False
    GVisorSandbox = None
    GVisorConfig = None
    create_gvisor_sandbox = None


def get_sandbox_by_type(sandbox_type: str, config: dict = None):
    """
    Factory function to get sandbox by type.
    
    Args:
        sandbox_type: Type of sandbox ('wasm', 'gvisor', 'subprocess', 'none')
        config: Configuration dictionary
        
    Returns:
        Sandbox instance or None if 'none'
    """
    if sandbox_type == 'wasm':
        if WASM_AVAILABLE:
            return create_wasm_sandbox(config)
        else:
            raise ImportError("WASM sandbox requires wasmtime: pip install wasmtime>=8.0.0")
    elif sandbox_type == 'gvisor':
        if GVSIOR_AVAILABLE:
            return create_gvisor_sandbox(config)
        else:
            raise ImportError("gVisor sandbox requires Docker with runsc runtime")
    elif sandbox_type == 'subprocess':
        return get_sandbox(config)
    elif sandbox_type == 'none':
        return None
    else:
        # Default to subprocess sandbox
        return get_sandbox(config)


__all__ = [
    # Core validation
    'ValidatorDAG',
    'ValidationResult',
    'ValidatorSandbox',
    'SandboxResult',
    'ResourceLimits',
    'get_sandbox',
    
    # WASM sandbox (ITEM-SEC-01)
    'WASMSandbox',
    'WASMConfig', 
    'WASMModule',
    'create_wasm_sandbox',
    'WASM_AVAILABLE',
    
    # gVisor sandbox (ITEM-SEC-01)
    'GVisorSandbox',
    'GVisorConfig',
    'create_gvisor_sandbox',
    'GVSIOR_AVAILABLE',
    
    # Factory function
    'get_sandbox_by_type'
]
