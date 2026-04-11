---
purpose: "System prompt bridge for LLM context initialization"
audience: ["agents"]
when_to_read: "After AGENTS.md, before SKILL.md"
protocol_version: "5.3.0"
tier_status: "TIER_7_STABLE"
last_updated: "2026-04-11"
---

# TITAN FUSE — AI Mission Context

## Mission Statement

```
Execute ONLY verifiable operations.
No speculation. No fabrication.
All modifications tracked. All gaps explicitly marked.
```

You are operating under the **TITAN FUSE Protocol v5.3.0** — a production-grade deterministic large-file agent protocol for processing files with 5k–50k+ lines, now at **TIER_7_STABLE** status.

---

## Quick Context

| Aspect | Value |
|--------|-------|
| **Protocol Version** | 5.3.0 |
| **Tier Status** | TIER_7_STABLE (Production Ready) |
| **Test Coverage** | 3,117+ tests |
| **Python Version** | ≥3.10 |
| **Architecture Tiers** | 8 (TIER -1 through TIER 7) |
| **Entry Point** | `AGENTS.md` |

---

## File Reading Order

```
START → AGENTS.md (navigation & intent routing)
      → AI_MISSION.md (THIS FILE — mission & context)
      → SKILL.md (agent configuration & constraints)
      → PROTOCOL.md (full protocol specification)
      → config.yaml (runtime defaults)
```

**After reading this file:**
1. Read `SKILL.md` for agent configuration
2. Read `PROTOCOL.md` for full protocol specification
3. Check `inputs/` for files to process
4. Check `checkpoints/` for resumption state

---

## Core Invariants (Non-Negotiable)

These invariants CANNOT be overridden by SKILL.md or any configuration:

| ID | Name | Enforcement |
|----|------|-------------|
| **INVAR-01** | Anti-Fabrication | Mark missing data as `[gap: not in sources]` |
| **INVAR-02** | S-5 Veto | `<!-- KEEP -->` blocks modification |
| **INVAR-03** | Zero-Drift | Preserve formatting, structure, tone |
| **INVAR-04** | Patch Idempotency | Same result on re-application |
| **INVAR-05** | Code Execution Gate | sandbox/human_gate required for LLM-generated code |

> **Details**: See `PROTOCOL.base.md` → TIER 0 — INVARIANTS

---

## Processing Pipeline

```
PHASE 0: INIT         → Build NAV_MAP, workspace isolation, checkpoint
PHASE 1: DISCOVER     → Pattern detection, search
PHASE 2: ANALYZE      → Issue classification (SEV-1..4)
PHASE 3: PLAN         → Execution plan, budget allocation
PHASE 4: EXEC         → Surgical patches, validation loop
PHASE 5: DELIVER      → Hygiene, artifact generation
```

Each phase ends with a verification gate (GATE-00 through GATE-05).

> **Details**: See `PROTOCOL.base.md` → TIER 2 — EXECUTION PROTOCOL

---

## Verification Gates

| Gate | Condition | On Fail |
|------|-----------|---------|
| GATE-00 | NAV_MAP exists, all chunks indexed | BLOCK |
| GATE-01 | All target patterns scanned | BLOCK |
| GATE-02 | All issues classified with ISSUE_ID | BLOCK |
| GATE-03 | Plan validated, no KEEP_VETO violations | BLOCK |
| GATE-04 | Validations pass OR gaps within threshold | BLOCK/WARN |
| GATE-05 | Artifacts complete, hygiene done | BLOCK |

> **Details**: See `PROTOCOL.base.md` → TIER 6 — VERIFICATION GATES

---

## TIER Architecture

| Tier | Name | Key Modules |
|------|------|-------------|
| -1 | Bootstrap | `PROTOCOL.ext.md` — repository navigation, self-init |
| 0 | Invariants | `PROTOCOL.base.md` — non-negotiable rules |
| 1 | Core Principles | Deterministic execution, tool-first navigation |
| 2 | Execution Protocol | Phase 0-5 pipeline |
| 3 | Output Format | Mandatory structure |
| 4 | Rollback Protocol | Backup and recovery |
| 5 | Failsafe Protocol | Edge case handling |
| 6 | Verification Gates | GATE-00 through GATE-05 |
| **7** | **Production** | Multi-agent, observability, planning |

> **TIER_7 Modules**: `src/agents/`, `src/planning/`, `src/observability/`

---

## Key Capabilities (TIER_7)

### Multi-Agent Orchestration
- **SCOUT Pipeline**: RADAR → DEVIL → EVAL → STRAT
- **Veto Mechanism**: EVAL can block STRAT on quality threshold
- **Modules**: `src/agents/multi_agent_orchestrator.py`, `src/agents/scout_matrix.py`

### Observability Stack
- **Distributed Tracing**: OpenTelemetry integration
- **Structured Logging**: JSON format with correlated IDs
- **Token Attribution**: Per-gate tracking
- **Metrics**: p50/p95/p99 latency export
- **Module**: `src/observability/`

### Planning & DAG
- **Cycle Detection**: Prevents infinite loops in execution plans
- **Amendment Control**: GATE-PLAN and GATE-AMENDMENT enforcement
- **Modules**: `src/planning/cycle_detector.py`, `src/planning/amendment_control.py`

### Security
- **Secret Scanning**: AWS/GitHub/API key detection
- **Workspace Isolation**: Sandboxed file operations
- **Execution Gate**: LLM code execution control
- **Modules**: `src/security/`

---

## Severity Scale (Unified)

All severity references use ONE scale:

| Level | Name | Examples |
|-------|------|----------|
| SEV-1 | CRITICAL | Silent data loss, security vulnerability |
| SEV-2 | HIGH | Architectural debt, API breakage risk |
| SEV-3 | MEDIUM | Logic errors, maintainability risk |
| SEV-4 | LOW | Style, cosmetic issues |

---

## Tool Matrix (Quick Reference)

| Need | Tool |
|------|------|
| Find pattern | `grep -rn "pattern" dir/` |
| Extract section | `sed -n '/START/,/END/p'` |
| Validate JSON | `python -m json.tool file.json` |
| Checksum | `sha256sum <file>` |
| Binary detection | `file <path>` |
| AST parse Python | `python -c "import ast; ast.dump(...)"` |

> **Full Tool Matrix**: See `PROTOCOL.base.md` → TIER 2 → Tool Matrix

---

## Current State Summary

After reading this file, you should have:

- [x] Mission statement understood
- [x] Core invariants memorized (INVAR-01 through INVAR-05)
- [x] Processing pipeline overview (Phase 0-5)
- [x] Gate structure understood (GATE-00 through GATE-05)
- [x] TIER architecture mapped
- [x] TIER_7 capabilities known
- [x] File reading order clear

**Next Steps:**
1. Read `SKILL.md` for specific constraints and configuration
2. Read `PROTOCOL.md` for detailed specifications
3. Check `inputs/` for target files
4. Begin Phase 0: INITIALIZATION

---

## Related Files

| File | Purpose |
|------|---------|
| `AGENTS.md` | Entry point, navigation matrix |
| `SKILL.md` | Agent configuration v2.1.0 |
| `PROTOCOL.md` | Full assembled protocol |
| `PROTOCOL.base.md` | TIER 0-6 base specification |
| `PROTOCOL.ext.md` | TIER -1 bootstrap extension |
| `config.yaml` | Runtime defaults |
| `VERSION` | Single source of truth for version |
| `docs/tiers/TIER_7_EXIT_CRITERIA.md` | Production readiness gates |

---

## Metadata

```
Protocol Version: 5.3.0
Tier Status: TIER_7_STABLE
Test Coverage: 3,117+ tests
Last Updated: 2026-04-11
Entry Point: AGENTS.md
```

---

**Maintainer**: TITAN FUSE Team
**Full Documentation**: `PROTOCOL.md`
**Agent Entry Point**: `AGENTS.md`
