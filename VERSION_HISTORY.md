# TITAN Protocol Version History

## Version 3.3.0 - TIER_2_COMPLETE

### PHASE_1 (SECURITY_CRITICAL):
- ITEM-SEC-01: VM2 Sandbox Replacement (WASM/gVisor)
- ITEM-SEC-02: Serialization Safety Fix (JSON+zstd)
- ITEM-SEC-03: SecretStore Implementation
- ITEM-SEC-04: Secret Scanning Integration (GATE-00)
- ITEM-SEC-05: Tamper-Evident Logging (Ed25519)

### PHASE_2 (ARCHITECTURE_CRITICAL):
- ITEM-ARCH-02: EventBus WAL for Crash Recovery
  - EventJournal with sync/async writes
  - RecoveryManager for state rebuild
  - EventBus integration
- ITEM-ARCH-03: Distributed Locking with TTL
  - LockBackend abstract interface
  - FileLockBackend implementation
  - RedisLockBackend implementation
  - EtcdLockBackend implementation
  - DeadlockDetector
- ITEM-ARCH-04: Gate-04 SEV-1 Override Fix
  - Gate04Evaluator with severity-based blocking
  - SEV-1 always blocks
  - SEV-2 threshold blocking
  - SEV-3/SEV-4 advisory pass
- ITEM-ARCH-07: Release-on-Wait Pattern
  - ApprovalLoop with cursor validation
  - Lock release during wait
  - CursorDriftError detection

### PHASE_3 (GATES_ENHANCEMENT):
- ITEM-GATE-01: Gate-04 Early Exit Fix
  - Confidence check before Phase 4
  - should_early_exit() method
  - evaluate_with_early_exit() method
  - GateLinter for validation
- ITEM-GATE-02: Mode-Based Gate Sensitivity
  - GateBehaviorModifier class
  - Sensitivity configs per mode (deterministic, guided_autonomy, fast_prototype)
  - apply_mode_rules() for result modification
- ITEM-GATE-03: Pre-Intent Token Budget
  - Token counting in IntentRouter
  - Budget check before classification
  - Fallback to MANUAL mode on budget exceeded
- ITEM-GATE-04: Split Pre/Post Exec Gates
  - GateManager class
  - Pre-exec gates: Policy Check, Access Control, Resource Availability, etc.
  - Post-exec gates: Output Structure, Invariant Validation, etc.
- ITEM-GATE-05: Model Downgrade Determinism
  - ExecutionStrictness enum
  - BudgetExhaustedError for deterministic mode
  - Mode-aware downgrade control in ModelRouter

### PHASE_4 (STORAGE_ENHANCEMENT):
- ITEM-STOR-01: StorageBackend Abstraction
  - StorageBackend abstract base class
  - LocalStorageBackend, S3StorageBackend, GCSStorageBackend
  - Factory function get_storage_backend()
  - Test suite: tests/test_storage.py (34 tests)
- ITEM-STOR-02: Checkpoint Session Isolation
  - CheckpointManager class for session-isolated storage
  - Namespace-based path isolation
  - Test suite: tests/test_checkpoint_manager.py (25 tests)
- ITEM-STOR-03: Checkpoint Encryption
  - CheckpointEncryption class with AES-256-GCM
  - Key generation and derivation (PBKDF2)
  - AEAD support with associated_data
  - Test suite: tests/test_checkpoint_encryption.py (31 tests)
- ITEM-STOR-05: Cursor Hash for Drift Detection
  - CursorTracker class with SHA-256 hash computation
  - EventBus integration for CURSOR_DRIFT events
  - Test suite: tests/test_cursor_tracking.py (34 tests)

### PHASE_5 (CONFIG_AND_OBSERVABILITY):
- ITEM-CFG-01: Config Schema Validation
  - ConfigSchemaValidator class with JSON Schema draft-07
  - Semantic validation for storage backends
  - Test suite: tests/test_config_validation.py (21 tests)
- ITEM-OBS-02: Event Severity Filtering
  - EventSeverity enum (CRITICAL, WARN, INFO, DEBUG)
  - Event type to severity mapping (EVENT_SEVERITY_MAP)
  - DispatchBehavior enum (SYNC_BLOCK, SYNC_TIMEOUT, ASYNC_FIRE, ASYNC_DROP)
  - Hybrid dispatch based on severity
  - subscribe_severity() and subscribe_min_severity() methods
  - Test suite: tests/test_event_bus.py (33 tests)
- ITEM-OBS-06: Event-State Transition Contract
  - schemas/event_state_map.json with full state machine definitions
  - StateTransitionValidator class
  - Test suite: tests/test_state_transitions.py (25 tests)

### Total Tests: 200+ tests across all modules

---

## Version 3.2.2
- Initial modular architecture
- CLI Interface
- State Manager
- Event Bus
- Checkpoint System with partial recovery

## Version 3.2.1
- FILE_INVENTORY module
- CURSOR_TRACKING module
- ISSUE_DEPENDENCY_GRAPH
- CROSSREF_VALIDATOR
- DIAGNOSTICS_MODULE
