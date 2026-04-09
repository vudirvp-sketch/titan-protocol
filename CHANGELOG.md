# TITAN FUSE Protocol Changelog

All notable changes to this project will be documented in this file.

## [5.1.0] - 2026-04-10

### TIER_7 Exit Criteria Progress

#### Documentation
- **README.md v5.1.0 Sync**: Full documentation synchronization
  - Added AGENT_METADATA block for LLM navigation
  - Updated version badges (4.1.0 → 5.1.0)
  - Updated test count (1100+ → 2796+)
- **SKILL.md**: Updated protocol_version to 5.1.0
- **nav_map.json**: Version synchronized to 5.1.0

#### Gap Resolution
- **GAP-VERSION-01**: Fixed version mismatch between VERSION and README.md
- **GAP-META-01**: Added AGENT_METADATA block to README.md

### Status
- TIER_7_IN_PROGRESS: 6/20 exit criteria met (30%)
- 2796+ tests passing
- Security hardening: INVAR-05, secret scanning, workspace isolation
- Multi-agent orchestration: SCOUT roles (RADAR/DEVIL/EVAL/STRAT)
- Observability: OpenTelemetry, structured logging, token attribution

### Files Modified
```
README.md (v5.1.0 sync, AGENT_METADATA block)
SKILL.md (protocol version update)
CHANGELOG.md (this entry)
outputs/preflight_report.md (new)
```

## [4.1.0] - 2026-04-08

### TIER_7 Production Features

#### Planning & DAG
- **CycleDetector**: Prevent infinite loops in execution plan DAG
  - New `src/planning/cycle_detector.py` module
  - Gap tag: `[gap: dag_cycle_detected]`
- **Plan Amendment Gate**: Root model cannot bypass GATE-02
  - New `src/policy/plan_amendment_gate.py` module
  - Enforcement of GATE-PLAN and GATE-AMENDMENT

#### Multi-Agent Architecture
- **SCOUT Roles Matrix**: RADAR/DEVIL/EVAL/STRAT for quality assurance
  - New `src/agents/scout_matrix.py` module
  - Adaptive scoring and hype detection
- **Multi-Agent Orchestrator**: TaskQueue, AgentRegistry, conflict resolution
  - New `src/agents/multi_agent_orchestrator.py` module
  - Priority dispatch and heartbeat monitoring

#### Observability
- **Distributed Tracing**: OpenTelemetry integration
  - New `src/observability/distributed_tracing.py` module
  - W3C Trace Context support
- **Structured Logging**: JSON output with component-level levels
  - New `src/observability/structured_logging.py` module
- **Token Attribution**: Per-gate token tracking
  - New `src/observability/token_attribution.py` module
- **Budget Forecast**: Proactive warnings for token limits
  - New `src/observability/budget_forecast.py` module

#### Documentation
- **README v4.1.0 Sync**: Full documentation synchronization
  - Project Scale metrics section
  - Requirements block (YAML format)
  - Migration guide v3.2.x → v4.1.0
  - Version Authority section
  - Security, Multi-Agent, Observability sections
  - Production Features table
  - Agent Navigation table with priorities
  - Automation section

### Test Coverage
- Total tests: 1100+ passing
- New module coverage: >80%
- Integration tests: All phases covered

### Files Created
```
scripts/sync_readme_version.py
scripts/check_version_sync.py
src/planning/cycle_detector.py
src/policy/plan_amendment_gate.py
src/agents/scout_matrix.py
src/agents/multi_agent_orchestrator.py
src/observability/distributed_tracing.py
src/observability/structured_logging.py
src/observability/token_attribution.py
src/observability/budget_forecast.py
```

### Files Modified
```
README.md (v4.1.0 sync, all new sections)
AGENTS.md (TIER 7 addition)
SKILL.md (version compatibility update)
CHANGELOG.md (this entry)
```

## [4.0.0] - 2026-04-08

### Breaking Changes
- Minimum Python version: 3.10 (was 3.8)
- Checkpoint format: JSON+zstd mandatory (pickle requires --unsafe)
- GATE-05 expanded: metrics.json-valid AND audit_trail.sig-verified

### Architecture
- TIER_7 framework established
- Multi-agent orchestration foundation
- Observability stack integration
- Planning DAG infrastructure

### Security Enhancements
- INVAR-05 enforcement: Code execution gate mandatory
- Workspace isolation: All file operations sandboxed
- Secret scanning: AWS/GitHub/API key detection
- Session-scoped checkpoint isolation

### Configuration
- New `planning.cycle_detection.enabled` option
- New `observability.prometheus_enabled` option
- Extended GATE configuration options

---

## [3.2.2] - 2026-04-07

### Security (Critical)
- **Config Schema Validation**: Invalid config keys now detected via JSON Schema
  - New `schemas/config.schema.json` for validation
  - Gap tag: `[gap: config_validation_failed]`
- **Input File Size DoS Protection**: Max 100MB per file, 500MB total
  - Gap tags: `[gap: input_file_too_large]`, `[gap: total_input_size_exceeded]`
- **Secret Scanning Integration**: Detect AWS/GitHub/API keys in inputs
  - New `src/security/secret_scanner.py` module
  - Gap tag: `[gap: secrets_detected]`
- **Provider Credential Isolation**: No API keys stored in SessionState
  - Environment variable pattern: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- **Workspace Path Enforcement**: All file operations sandboxed
  - Gap tag: `[gap: workspace_violation]`
- **Safe Checkpoint Serialization**: JSON+zstd default, pickle requires `--unsafe`
  - New `src/state/checkpoint_serialization.py` module

### Checkpoints
- **Session-Scoped Isolation**: Parallel sessions supported
  - Checkpoints stored in `checkpoints/<session_id>/`
  - `latest.json` symlink for easy access
- **Schema Migration Framework**: Auto-upgrade old checkpoints
  - New `src/schema/migrations.py` module
  - Migrations: 3.2.0 → 3.2.1 → 3.2.2
- **Checkpoint Frequency Tuning**: Token/time based intervals
  - `interval_tokens: 5000`, `interval_seconds: 60`

### Gates
- **Extended Gates Documentation**: GATE-SECURITY, GATE-EXEC, GATE-INTENT, GATE-PLAN, GATE-SKILL
  - New `docs/extended_gates.md`
- **Sandbox Health Check (INVAR-05)**: Runtime verification
  - New `src/security/sandbox_verifier.py` module
- **Configurable Recursion Limit**: Default 3 (was 1)
  - `policy.max_recursion_depth: 3` in config.yaml
- **GATE-04 Early Exit Enhancement**: Confidence before SEV-4 checks
  - SEV-1/SEV-2 checked first (non-negotiable)

### DAG & Planning
- **CycleDetector**: Prevent infinite loops in execution plan
  - New `src/planning/cycle_detector.py` module
  - Gap tag: `[gap: dag_cycle_detected]`
- **Plan Amendment Gate**: Root model cannot bypass GATE-02
  - New `src/policy/plan_amendment_gate.py` module
- **Per-Node Rollback**: Partial recovery from failures
  - State snapshots in `outputs/snapshots/`

### Observability
- **Structured Gap Objects**: Machine-parseable gap data
  - New `src/state/gap.py` module
  - `Gap` dataclass with severity, source refs, checksums
- **Parity Tests**: Full test coverage for v3.2.2 modules
  - New `tests/test_v322_modules.py`

### Resolved Conflicts
- A: Checkpoint format → JSON+zstd default
- B: GATE-04 confidence → SEV-1/2 non-negotiable
- D: DECISION_TREE → code is source of truth
- G: EventBus → sync for CRITICAL, async for TELEMETRY
- I: Async I/O → sync default, adapter opt-in

### Files Created
```
schemas/config.schema.json
src/security/__init__.py
src/security/secret_scanner.py
src/security/sandbox_verifier.py
src/schema/__init__.py
src/schema/migrations.py
src/state/gap.py
src/state/checkpoint_serialization.py
src/planning/__init__.py
src/planning/cycle_detector.py
src/policy/plan_amendment_gate.py
docs/extended_gates.md
tests/test_v322_modules.py
SECURITY.md
```

### Files Modified
```
config.yaml (security, checkpoint, policy sections)
VERSION (3.2.1 → 3.2.2)
CHANGELOG.md (this entry)
src/harness/orchestrator.py (workspace isolation, safe I/O)
src/state/state_manager.py (session-scoped checkpoints)
```

## [3.2.0] - 2026-04-07

### Added - NEW in v3.2 (Protocol Implementation)

#### Security (INVAR-05)
- **LLM Code Execution Gate**: New security invariant preventing LLM-generated code execution
  - Execution modes: `sandbox`, `human_gate`, `disabled`
  - Sandbox types: `docker`, `venv`, `restricted_subprocess`
  - Approval token system for human gate mode
  - `src/security/execution_gate.py` module

#### Chunking (PRINCIPLE-04)
- **Secondary Chunk Limits**: Hard caps to prevent context overflow
  - `max_chars_per_chunk: 150000` characters
  - `max_tokens_per_chunk: 30000` tokens
  - Override primary line limit if exceeded

#### Recursion Control
- **Recursion Depth Tracking**: Prevent exponential token growth
  - `recursion_depth` field in STATE_SNAPSHOT
  - `max_recursion_depth` configurable (default: 1)
  - `recursion_depth_peak` for reporting
  - Methods: `increment_recursion_depth()`, `check_recursion_limit()`

#### Model Routing (PRINCIPLE-06)
- **Cost Optimization**: Route calls by model type
  - `root_model`: orchestration, gates, planning (Phase 0-3, 5)
  - `leaf_model`: llm_query chunk calls (Phase 1-4)
  - Model usage tracking in session state

#### GATE-04 Enhancement
- **Confidence Advisory**: Informational early exit signal
  - Check if all QueryResults have `confidence = HIGH`
  - Log advisory when zero gaps
  - Requires human acknowledgement (not auto-exit)

#### Telemetry
- **Token Distribution Metrics**: p50/p95 percentiles
  - Per-query token tracking
  - Latency tracking in milliseconds
  - Model-specific token counters
  - Enhanced `metrics.json` output

### Changed
- Updated `config.yaml` with new v3.2 sections
- Updated `SessionState` dataclass with new fields
- Enhanced `metrics.json` generation in Phase 5
- Updated `_validate_gate_04()` for confidence advisory

### Tests Added
- `TestRecursionControl`: 3 tests for recursion depth
- `TestTokenTelemetry`: 2 tests for p50/p95
- `TestConfidenceTracking`: 3 tests for confidence
- `TestExecutionGate`: 3 tests for INVAR-05
- `TestGate04ConfidenceAdvisory`: 2 tests for advisory

## [3.2.1] - 2026-04-07

### Added
- **FILE_INVENTORY (Step 0.2.5)**: File metadata collection before chunking
  - Binary file detection with skip and log
  - Encoding detection (UTF-8 first, chardet fallback)
  - SHA-256 checksum for resume verification
  - File inventory JSON artifact
- **CURSOR_TRACKING**: Enhanced position tracking in STATE_SNAPSHOT
  - current_file, current_line, current_chunk, current_section
  - offset_delta for lines added/removed
  - Atomic update with checkpoint
  - Post-patch validation
- **ISSUE_DEPENDENCY_GRAPH (PHASE 3)**: DAG for issue dependencies
  - AST-based static analysis (primary method)
  - Regex-based fallback
  - DFS cycle detection with max depth 10
  - Topological ordering for processing
  - ASCII/GraphViz visualization
- **CROSSREF_VALIDATOR**: Reference validation module
  - Section, anchor, code, import reference extraction
  - REF_INDEX caching per chunk
  - Integration with GATE-00 and GATE-04
- **DIAGNOSTICS_MODULE (TIER 5)**: Systematic troubleshooting
  - Symptom → Root Cause → Solution matrix
  - Test scenarios for validation
  - Human-review fallback

### Changed
- Unified version to 3.2.1 across all files
- Updated checkpoint.schema.json with new fields
- Updated SKILL.md to version 2.1.0
- Added Russian language support (input_languages: en, ru)

### Fixed
- Version inconsistency between README.md (v3.2.0) and PROTOCOL.base.md (v3.1)

### Security
- Added workspace isolation path configuration
- Added ReDoS validation for regex patterns

## [3.2.0] - 2024-01-15

### Added
- Chunk-level checkpoint recovery for partial resumption
- Enhanced llm_query fallback with 4-attempt progressive chain
- Metrics export in JSON format for monitoring integration
- Custom validators framework in `skills/validators/`
- Navigation files in `.ai/` directory

### Changed
- Unified severity scale across all registries (SEV-1..4)
- Improved GATE-04 threshold rules

### Fixed
- Patch idempotency guarantee (INVAR-04)
- Double hygiene issue in Phase 5

## [3.1.0] - 2024-01-01

### Added
- Session persistence via checkpoints
- Operation budget tracking (tokens + time)
- Expanded tool matrix (AST, binary detection, encoding)
- llm_query specification with typed results

### Changed
- Unified severity definitions
- Parallel-safe batch validation (P1-P4)

## [3.0.0] - 2023-12-15

### Added
- TIER -1 Bootstrap phase for repository navigation
- Entry point classification (REPO_NAVIGATE, FILE_DIRECT, REPOMIX, REPO_HOST)
- Git-backed rollback points
- Multi-file coordination stub

### Changed
- Environment Offload activated for files > 5000 lines
- Workspace Isolation mandatory

## [2.0.0] - 2023-11-01

### Added
- Surgical Patch Engine (GUARDIAN)
- Deterministic Validation Loop
- Verification Gate Protocol
- Pathology & Risk Registry

### Changed
- Patch format standardization

## [1.0.0] - 2023-10-01

### Added
- Initial release
- Large file processing (5k-50k+ lines)
- Chunking strategy
- Anti-fabrication invariants
- Zero-Drift Guarantee
