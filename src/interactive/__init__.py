"""
Interactive Mode for TITAN Protocol v4.0.0.

ITEM-PROD-02: REPL-like debugging interface for TITAN Protocol.

This module provides:
- InteractiveSession: Core debugging session management
- TitanREPL: Command-line interface for interactive debugging

Features:
- Step-by-step execution
- Breakpoint management
- State inspection and modification
- Rollback support via checkpoints
- EventBus integration for event-driven pausing

Configuration (config.yaml):
    interactive:
        enabled: false  # Default: disabled
        prompt: "titan> "
        history_file: ".titan/repl_history"
        auto_pause_on:
            - "GATE_FAIL"
            - "CLARITY_LOW"

Usage:
    from src.interactive import InteractiveSession, TitanREPL
    
    # Programmatic usage
    session = InteractiveSession(event_bus, state_manager, checkpoint_manager)
    session.add_breakpoint("GATE_FAIL")
    session.start()
    
    # REPL usage
    repl = TitanREPL(event_bus, state_manager, checkpoint_manager)
    repl.run()

Author: TITAN FUSE Team
Version: 4.0.0
"""

from .session import (
    InteractiveSession,
    SessionStatus,
    Breakpoint,
    SessionConfig,
)
from .repl import (
    TitanREPL,
    CommandResult,
    CommandType,
)

__all__ = [
    # Session management
    "InteractiveSession",
    "SessionStatus",
    "Breakpoint",
    "SessionConfig",
    
    # REPL interface
    "TitanREPL",
    "CommandResult",
    "CommandType",
]

__version__ = "4.0.0"
