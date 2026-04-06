"""
TITAN FUSE Protocol - Source Package

Production-Grade Large-File Agent Protocol v3.2.3

A deterministic LLM agent protocol for processing large files (5k–50k+ lines)
with verification gates, rollback safety, and session persistence.
"""

__version__ = "3.2.3"

from .state import (
    AssessmentScore,
    SignalStrength,
    ReadinessTier,
    SessionState,
    ReasoningStep,
    EvidenceType,
    BudgetManager,
    BudgetAllocation,
    CursorTracker
)

from .events import EventBus, Event, EventSeverity, EventTypes

from .harness import ModeAdapter, ModeConfig

from .policy import IntentRouter, IntentResult, INTENT_CHAINS

from .llm import ModelRouter, ModelConfig, FallbackState

from .validation import ValidatorDAG, ValidationResult, ValidatorSandbox, SandboxResult

from .diagnostics import DiagnosticsListener, DiagnosticResult

from .planning import StateSnapshot, SnapshotManager

__all__ = [
    # Version
    '__version__',

    # State
    'AssessmentScore',
    'SignalStrength',
    'ReadinessTier',
    'SessionState',
    'ReasoningStep',
    'EvidenceType',
    'BudgetManager',
    'BudgetAllocation',
    'CursorTracker',

    # Events
    'EventBus',
    'Event',
    'EventSeverity',
    'EventTypes',

    # Harness
    'ModeAdapter',
    'ModeConfig',

    # Policy
    'IntentRouter',
    'IntentResult',
    'INTENT_CHAINS',

    # LLM
    'ModelRouter',
    'ModelConfig',
    'FallbackState',

    # Validation
    'ValidatorDAG',
    'ValidationResult',
    'ValidatorSandbox',
    'SandboxResult',

    # Diagnostics
    'DiagnosticsListener',
    'DiagnosticResult',

    # Planning
    'StateSnapshot',
    'SnapshotManager',
]
