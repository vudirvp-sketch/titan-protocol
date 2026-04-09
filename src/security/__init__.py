"""
TITAN FUSE Protocol - Security Module

Provides security features for TITAN Protocol v1.2.0:
- Secret scanning
- Sandbox verification
- Execution gates
- Input sanitization (ITEM_016)
- Session security (ITEM_017)

PHASE_3 Components:
- InputSanitizer: Sanitizes user inputs with prompt injection detection
- SessionSecurity: Secure session management with optional encryption

Author: TITAN FUSE Team
Version: 1.2.0
"""

from .secret_scanner import SecretScanner, run_secret_scan
from .sandbox_verifier import SandboxVerifier, verify_sandbox

from .input_sanitizer import (
    # Main class
    InputSanitizer,
    # Enums
    SanitizationAction,
    ThreatSeverity,
    # Data classes
    InputSanitizerConfig,
    SanitizationResult,
    InjectionResult,
    ModificationRecord,
    # Factory functions
    get_input_sanitizer,
    reset_input_sanitizer,
)

from .session_security import (
    # Main class
    SessionSecurity,
    # Enums
    SessionSecurityLevel,
    # Data classes
    SessionSecurityConfig,
    SessionSecurityStats,
    SessionSecurityError,
    # Factory functions
    get_session_security,
    reset_session_security,
)

__all__ = [
    # Legacy components
    'SecretScanner',
    'run_secret_scan',
    'SandboxVerifier',
    'verify_sandbox',
    
    # InputSanitizer (ITEM_016)
    'InputSanitizer',
    'SanitizationAction',
    'ThreatSeverity',
    'InputSanitizerConfig',
    'SanitizationResult',
    'InjectionResult',
    'ModificationRecord',
    'get_input_sanitizer',
    'reset_input_sanitizer',
    
    # SessionSecurity (ITEM_017)
    'SessionSecurity',
    'SessionSecurityLevel',
    'SessionSecurityConfig',
    'SessionSecurityStats',
    'SessionSecurityError',
    'get_session_security',
    'reset_session_security',
]
