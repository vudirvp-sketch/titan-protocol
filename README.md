---
purpose: "Human-friendly overview and documentation for TITAN FUSE Protocol"
audience: ["developers", "users", "agents"]
when_to_read: "First document for human readers; after AGENTS.md for agents"
related_files: ["AGENTS.md", "SKILL.md", "PROTOCOL.md", "config.yaml"]
stable_sections: ["quick-start", "protocol-architecture", "verification-gates", "troubleshooting"]
emotional_tone: "informative, welcoming, technical"
ideal_reader_state: "learning about the protocol"
---

<!-- version-header -->
# TITAN FUSE Protocol

**Production-Grade Large-File Agent Protocol v4.1.0**

A deterministic LLM agent protocol for processing large files (5k–50k+ lines) with verification gates, rollback safety, and session persistence.

<!-- badges -->
![Version](https://img.shields.io/badge/version-4.1.0-blue)
![Tier](https://img.shields.io/badge/tier-TIER_7_IN_PROGRESS-orange)
![Tests](https://img.shields.io/badge/tests-1100+-brightgreen)
![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)
![Contributing](https://img.shields.io/badge/contributing-welcome-brightgreen)

---

## Project Scale

| Metric | Value |
|--------|-------|
| Python Modules | 175 files |
| Lines of Code | 73,800+ |
| Test Coverage | 1,100+ tests |
| Architecture Tiers | 8 (TIER -1..7) |
| Production Status | TIER_7_IN_PROGRESS |

---

## Requirements

```yaml
requirements:
  python: ">=3.10"
  node: ">=18"  # for JS validators
  cli_tools: [gh, git, python3]
  env_vars: [TITAN_API_KEY, TITAN_TOKEN_LIMIT]
```

---

## Quick Start

```bash
# Clone the repository
git clone https://github.com/vudirvp-sketch/titan-protocol.git
cd titan-protocol

# Assemble the protocol
./scripts/assemble_protocol.sh

# Place input files
cp your-large-file.md inputs/

# Run the agent (example - actual implementation depends on your LLM platform)
# The agent will read PROTOCOL.md, SKILL.md, and process files in inputs/
```

---

## Features

### Core Capabilities
- **Large File Processing**: Handle files up to 50k+ lines via chunking
- **Deterministic Execution**: Every action is verifiable and traceable
- **Session Persistence**: Resume interrupted sessions via checkpoints
- **Anti-Fabrication**: Hard invariants prevent hallucination
- **Zero-Drift Guarantee**: Preserve original formatting and structure

### TIER -1 Bootstrap (NEW in v3.0)
- Repository navigation and self-initialization
- Entry point classification (repo URL, file path, repomix)
- Git-backed rollback points
- Multi-file coordination stub

### Enhanced Features (NEW in v3.2)
- **Chunk-level checkpoint recovery**: Resume even after source file changes
- **Enhanced llm_query fallback**: 4-attempt progressive fallback chain
- **Metrics export**: JSON output for monitoring integration
- **Custom validators**: Extensible validation framework

### New Modules (NEW in v3.2.1)
- **FILE_INVENTORY**: File metadata collection before chunking (binary detection, encoding, checksums)
- **CURSOR_TRACKING**: Enhanced position tracking with offset delta
- **ISSUE_DEPENDENCY_GRAPH**: DAG for issue dependencies with topological ordering
- **CROSSREF_VALIDATOR**: Reference validation module (section, anchor, code, import refs)
- **DIAGNOSTICS_MODULE**: Systematic troubleshooting (Symptom → Root Cause → Solution matrix)

### TIER 7 Production Features (NEW in v4.1.0)
- **Planning DAG**: CycleDetector prevents infinite loops in execution plans
- **Amendment Control**: GATE-PLAN and GATE-AMENDMENT enforcement
- **Multi-Agent Orchestration**: SCOUT roles (RADAR/DEVIL/EVAL/STRAT) for quality assurance
- **Observability**: OpenTelemetry tracing, structured logging, token attribution
- **Production Ready**: 1100+ tests, security hardening, checkpoint isolation

---

## Repository Structure

```
titan-protocol/
├── AGENTS.md               # 🧭 Agent entry point (NEW)
├── AI_MISSION.md           # System prompt bridge (NEW)
├── PROTOCOL.md             # Assembled protocol (generated)
├── PROTOCOL.base.md        # Base protocol (TIER 0-6)
├── PROTOCOL.ext.md         # TIER -1 extension
├── SKILL.md                # Agent configuration
├── README.md               # This file
├── VERSION                 # Semantic version
├── CHANGELOG.md            # Version history
├── config.yaml             # Configurable defaults
├── inputs/                 # Files to process
│   └── README.md
├── outputs/                # Generated artifacts
├── checkpoints/            # Session persistence
│   └── checkpoint.schema.json
├── skills/
│   ├── validators/         # Custom validation rules
│   │   ├── no-todos.js
│   │   ├── api-version.js
│   │   └── security.js
│   └── templates/          # Output templates
├── examples/
│   ├── small/              # <5000 line examples
│   └── large/              # >5000 line examples
├── scripts/
│   ├── assemble_protocol.sh
│   ├── validate_checkpoint.py
│   ├── enhanced_llm_query.py
│   ├── generate_metrics.py
│   └── test_navigation.py  # Navigation tests (NEW)
├── .ai/                    # Agent navigation files (NEW)
│   ├── nav_map.json
│   ├── context_hints.md
│   ├── shortcuts.yaml
│   └── agent_interface.md
├── .agentignore            # Files to skip (NEW)
├── DECISION_TREE.json      # State machine (NEW)
└── .titan_index.json       # Semantic index (NEW)
```

---

## Protocol Architecture

### TIER Structure

| Tier | Name | Purpose | Key Modules |
|------|------|---------|-------------|
| -1 | Bootstrap | Repository navigation, self-initialization | PROTOCOL.ext.md |
| 0 | Invariants | Non-negotiable rules (anti-fabrication, zero-drift) | PROTOCOL.base.md |
| 1 | Core Principles | Deterministic execution, tool-first navigation | PROTOCOL.base.md |
| 2 | Execution Protocol | Phased processing (Phase 0-5) | orchestrator.py |
| 3 | Output Format | Mandatory structure and artifacts | src/output/ |
| 4 | Rollback Protocol | Backup and recovery | checkpoint_manager.py |
| 5 | Failsafe Protocol | Edge case handling | recovery_manager.py |
| 6 | Verification Gates | GATE-00 through GATE-05 | guardian.py |
| 7 | Production | Multi-agent, observability, planning | multi_agent_orchestrator.py, cycle_detector.py |

> **Note**: TIER_7 status is IN_PROGRESS (NOT STABLE). See `docs/tiers/TIER_7_EXIT_CRITERIA.md` for production readiness gates.

### Processing Pipeline

```mermaid
flowchart TD
    subgraph Phase0["PHASE 0: INITIALIZATION"]
        A1[Quick Orient Header]
        A2[Environment Offload]
        A3[Navigation Map]
        A4[Workspace Isolation]
        A5[Session Checkpoint]
    end

    subgraph Phase1["PHASE 1: SEARCH & DISCOVERY"]
        B1[Pattern Detection]
    end

    subgraph Phase2["PHASE 2: ANALYSIS & CLASSIFICATION"]
        C1[Issue Classification<br/>SEV-1..4]
    end

    subgraph Phase3["PHASE 3: PLANNING"]
        D1[Execution Plan]
        D2[Pathology Registry]
        D3[Operation Budget]
    end

    subgraph Phase4["PHASE 4: EXECUTION & VALIDATION"]
        E1[Surgical Patch Engine]
        E2[Validation Loop]
    end

    subgraph Phase5["PHASE 5: DELIVERY & HYGIENE"]
        F1[Document Hygiene]
        F2[Artifact Generation]
        F3[Optional Full Merge]
    end

    A5 -->|GATE-00 PASS| B1
    B1 -->|GATE-01 PASS| C1
    C1 -->|GATE-02 PASS| D1
    D3 -->|GATE-03 PASS| E1
    E2 -->|GATE-04 PASS/WARN| F1
    F2 -->|GATE-05 PASS| F3

    E2 -->|FAIL| E1
    E2 -->|ROLLBACK| A4
```

### State Machine

```mermaid
stateDiagram-v2
    [*] --> INIT
    INIT --> BOOTSTRAP: REPO_HOST
    INIT --> PHASE_0: FILE_DIRECT

    BOOTSTRAP --> PHASE_0: GATE_REPO_01
    PHASE_0 --> PHASE_1: GATE_00
    PHASE_1 --> PHASE_2: GATE_01
    PHASE_2 --> PHASE_3: GATE_02
    PHASE_3 --> PHASE_4: GATE_03
    PHASE_4 --> PHASE_5: GATE_04
    PHASE_5 --> [*]: GATE_05

    PHASE_4 --> ROLLBACK: VALIDATION_FAIL
    ROLLBACK --> PHASE_4: RETRY
    ROLLBACK --> [*]: ABORT
```

---

## Verification Gates

```mermaid
flowchart LR
    subgraph Gates["VERIFICATION GATES"]
        G00[GATE-00<br/>NAV_MAP]
        G01[GATE-01<br/>Patterns]
        G02[GATE-02<br/>Issues]
        G03[GATE-03<br/>Plan]
        G04[GATE-04<br/>Validation]
        G05[GATE-05<br/>Artifacts]
    end

    G00 -->|PASS| G01
    G01 -->|PASS| G02
    G02 -->|PASS| G03
    G03 -->|PASS| G04
    G04 -->|PASS/WARN| G05

    G04 -->|BLOCK| X[❌ STOP]
```

| Gate | Condition | On Fail |
|------|-----------|---------|
| GATE-00 | NAV_MAP exists, all chunks indexed | BLOCK |
| GATE-01 | All target patterns scanned | BLOCK |
| GATE-02 | All issues classified with ISSUE_ID | BLOCK |
| GATE-03 | Plan validated, no KEEP_VETO violations | BLOCK |
| GATE-04 | Validations pass OR gaps within threshold | BLOCK/WARN |
| GATE-05 | artifacts-generated AND metrics.json-valid AND audit_trail.sig-verified | BLOCK |

### GATE-04 Threshold Rules

- **BLOCK**: SEV-1 gaps > 0, SEV-2 gaps > 2, or total gaps > 20%
- **WARN**: SEV-3 gaps > 5, SEV-4 gaps > 10
- **PASS**: All above conditions false

---

## Security

### Invariants (Non-Negotiable)

| ID | Name | Enforcement |
|----|------|-------------|
| INVAR-01 | Anti-Fabrication | `[gap: not in sources]` for missing data |
| INVAR-02 | S-5 VETO | `<!-- KEEP -->` blocks modification |
| INVAR-03 | Zero-Drift | Preserve formatting, structure, tone |
| INVAR-04 | Patch Idempotency | Same result on re-application |
| INVAR-05 | Code Execution Gate | sandbox/human_gate required |

### Security Modules

- `src/security/secret_scanner.py` — AWS/GitHub/API key detection
- `src/security/workspace_isolation.py` — Sandboxed file operations
- `src/security/sandbox_verifier.py` — Runtime sandbox health check
- `src/security/execution_gate.py` — LLM code execution control
- `src/state/checkpoint_serialization.py` — JSON+zstd default, pickle requires `--unsafe`

---

## Multi-Agent Architecture

### SCOUT Roles Matrix

| Role | Function | Trigger |
|------|----------|---------|
| RADAR | Signal detection | All tasks |
| DEVIL | Adversarial review | EVALUATE, COMPARE, AUDIT |
| EVAL | Quality veto | EXPERIMENTAL, VAPORWARE detection |
| STRAT | Strategic synthesis | Final recommendation |

### Modules

- `src/agents/multi_agent_orchestrator.py` — TaskQueue, AgentRegistry, conflict resolution
- `src/agents/scout_matrix.py` — RADAR/DEVIL/EVAL/STRAT pipeline
- `src/agents/agent_protocol.py` — Communication protocol
- `src/skills/skill_library.py` — YAML catalog with synergy tracking

---

## Observability

### Modules

- `src/observability/distributed_tracing.py` — OpenTelemetry, W3C Trace Context
- `src/observability/structured_logging.py` — JSON output, component-level levels
- `src/observability/realtime_metrics.py` — p50/p95 latency export
- `src/observability/token_attribution.py` — Per-gate token tracking
- `src/observability/budget_forecast.py` — Proactive warnings

### Configuration

```yaml
tracing:
  enabled: true
  provider: opentelemetry
  sampling_rate: 1.0
structured_logging:
  enabled: true
  format: json
```

---

## Production Features

| Feature | Module | Purpose |
|---------|--------|---------|
| SARIF Output | src/output/sarif_exporter.py | GitHub Code Scanning compatible |
| Interactive Mode | src/interactive/repl.py | REPL debugging, breakpoints, rollback |
| Streaming | src/llm/streaming.py | Chunk callbacks, early termination |
| Dead Letter Queue | src/events/dead_letter_queue.py | Failed event recovery |
| Cycle Detection | src/planning/cycle_detector.py | DAG infinite loop prevention |

---

## Agent Navigation

For LLM agents, the repository now includes navigation aids:

| File | Purpose | Priority |
|------|---------|----------|
| AGENTS.md | Primary LLM entry point | HIGH |
| .ai/nav_map.json | Machine-readable navigation graph | HIGH |
| PROTOCOL.md | Full assembled specification | MEDIUM |
| SKILL.md | Agent configuration v2.1.0 | MEDIUM |
| config.yaml | Runtime defaults | MEDIUM |
| VERSION | Single source of truth | MEDIUM |
| docs/tiers/TIER_7_EXIT_CRITERIA.md | Production readiness gates | LOW |
| CHANGELOG.md | Human history (agent ignores unless --changelog) | LOW |

**For agents:** Start with `AGENTS.md`, use `nav_map.json` for graph traversal.

---

## Migration v3.2.x → v4.1.0

1. Add to `config.yaml`:
   ```yaml
   planning:
     cycle_detection:
       enabled: true
   ```
2. Run migration preview:
   ```bash
   python scripts/migrate_checkpoints.py --from 3.2.2 --to 4.1.0 --dry-run
   ```
3. GATE-PLAN and GATE-AMENDMENT are now enforced
4. Enable observability:
   ```yaml
   observability:
     prometheus_enabled: true
   ```

---

## Version Authority

- **Single Source of Truth**: `./VERSION` file
- **Sync Script**: `scripts/sync_readme_version.py`
- **Check Script**: `scripts/check_version_sync.py --strict`
- **Rule**: No hardcoded versions — use `src/core/version.py::get_version()`
- **Violation**: Hardcoded version = S-5 VETO (invariant breach)

---

## Configuration

### SKILL.md

Override protocol defaults in `SKILL.md`:

```yaml
---
skill_version: 2.1.0
protocol_version: 4.1.0
constraints:
  max_files_per_session: 3
  max_tokens_per_session: 100000
---
```

### config.yaml

Configure runtime defaults:

```yaml
session:
  max_tokens: 100000
  max_time_minutes: 60

chunking:
  default_size: 1500

llm_query:
  fallback_enabled: true
```

---

## Custom Validators

Create validators in `skills/validators/`:

```javascript
// skills/validators/my-validator.js
module.exports = {
  name: 'my-validator',
  version: '1.0.0',

  validate(content, context) {
    // Return { valid: boolean, violations: [] }
  }
};
```

Validators are auto-loaded during Phase 2.

---

## Checkpoint Recovery

### Resume Full Session

```bash
python scripts/validate_checkpoint.py checkpoints/checkpoint.json
# Status: VALID → Full resumption possible
```

### Partial Recovery

When source file changed:

```bash
python scripts/validate_checkpoint.py checkpoints/checkpoint.json
# Status: PARTIAL → Some chunks recoverable
# Recoverable Chunks: C1, C2, C3
# Lost Chunks: C4, C5
```

---

## Navigation Tests

Run navigation integrity tests:

```bash
python scripts/test_navigation.py
# Tests: AGENTS.md, nav_map.json, shortcuts.yaml, internal links
```

---

## Metrics Integration

The protocol generates `metrics.json` for monitoring:

```json
{
  "session": {
    "id": "uuid",
    "duration_seconds": 1847,
    "status": "COMPLETE"
  },
  "processing": {
    "issues_found": 47,
    "issues_fixed": 42,
    "gaps": 2
  },
  "gates": {
    "GATE-00": "PASS",
    "GATE-04": "WARN"
  }
}
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Agent ignores SKILL.md | Wrong filename | Use exactly `SKILL.md` |
| inputs/ not visible | Empty directory | Add `.gitkeep` |
| Checkpoint rejected | Source file changed | Use partial recovery or fresh start |
| GATE-04 BLOCK | Too many gaps | Fix critical issues first |
| Budget exceeded | Token limit reached | Increase budget in config |
| llm_query timeout | Chunk too large | Use smaller chunk size |
| Circular dependency | Files reference each other | Process in queue order |
| gh CLI not found | Not installed | Use git manually or install gh |
| Version mismatch | Protocol > agent version | Update agent or use older protocol |
| Navigation test fails | Missing AGENTS.md | Run from repo root |

---

## Automation

### Pre-Commit Hook

The repository includes a pre-commit configuration for automatic version sync:

```yaml
# .pre-commit-config.yaml (already configured)
repos:
  - repo: local
    hooks:
      - id: version-sync
        name: Check VERSION sync
        entry: bash -c 'python3 scripts/check_version_sync.py --strict'
        language: system
        files: '^(VERSION|README\.md|\.ai/nav_map\.json|\.github/README_META\.yaml)$'
```

### CI Workflow

```yaml
# .github/workflows/sync-readme.yml
on:
  push:
    paths: ['VERSION']
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python scripts/sync_readme_version.py
      - run: python scripts/check_version_sync.py --strict
```

### Post-Update Validation

```yaml
validation_gates:
  GATE-00: [nav_map.json parseable, VERSION file exists, README.md version == VERSION]
  GATE-01: [All #anchor links resolve, All internal refs valid]
  GATE-02: [No hardcoded versions except VERSION file, Badges machine-parseable]
  GATE-03: [Repository structure matches actual files, Clone URL correct]
  GATE-04: [Migration guide includes --dry-run, Requirements block present]
  GATE-05: [metrics.json schema valid, All sections present]
```

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run validation: `./scripts/assemble_protocol.sh && python scripts/validate_checkpoint.py`
4. Run navigation tests: `python scripts/test_navigation.py`
5. Submit a pull request

---

## License

MIT License - See LICENSE file for details.

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 4.1.0 | 2026-04-08 | TIER_7_IN_PROGRESS: Planning DAG, Amendment Control, CycleDetector, 1100+ tests |
| 3.2.2 | 2026-04-07 | Security hardening, checkpoint isolation, gap objects, secret scanning |
| 3.2.1 | 2026-04-07 | FILE_INVENTORY, CURSOR_TRACKING, ISSUE_DEPENDENCY_GRAPH, CROSSREF_VALIDATOR, DIAGNOSTICS_MODULE |
| 3.2.0 | 2024-01-15 | Chunk-level recovery, enhanced llm_query, metrics |
| 3.1.0 | 2024-01-01 | Session persistence, budget tracking |
| 3.0.0 | 2023-12-15 | TIER -1 Bootstrap, environment offload |
| 2.0.0 | 2023-11-01 | Patch engine, validation loop |
| 1.0.0 | 2023-10-01 | Initial release |

---

**Protocol Status**: TIER_7_IN_PROGRESS

> ⚠️ **Status Notice**: This protocol is in TIER_7_IN_PROGRESS stage (NOT STABLE). Architecture is production-ready with:
> - 1100+ tests passing
> - Security hardening (INVAR-05, secret scanning, workspace isolation)
> - Multi-agent orchestration (SCOUT roles)
> - Observability stack (OpenTelemetry, structured logging)
> - Exit criteria documented in `docs/tiers/TIER_7_EXIT_CRITERIA.md`
>
> **Use when**: Files >5000 lines, deterministic output required, human-in-the-loop validation available.
> **Use alternatives when**: Simple file processing (<1000 lines), rapid prototyping, automatic execution without gates.

**Maintainer**: TITAN FUSE Team

**Documentation**: Full protocol specification in `PROTOCOL.md`

**Agent Entry Point**: `AGENTS.md`

