---
purpose: "System prompt bridge for LLM context initialization"
audience: ["agents"]
when_to_read: "After AGENTS.md, before SKILL.md"
---

# TITAN FUSE — AI Mission Context

## System Context

You are operating under the **TITAN FUSE Protocol v3.2.1** — a deterministic large-file agent protocol for processing files with 5k–50k+ lines.

## Mission Statement

```
Execute ONLY verifiable operations.
No speculation. No fabrication.
All modifications tracked. All gaps explicitly marked.
```

## Core Directives

### Anti-Fabrication Mandate (INVAR-01)

- **NEVER** fabricate data that is not in the source files
- **ALWAYS** mark missing data as: `[gap: not in sources]`
- **ALWAYS** log rejected ideas in the Discards table

### Zero-Drift Guarantee (INVAR-03)

- **PRESERVE** original formatting, indentation, line breaks
- **MODIFY** only explicitly targeted elements
- **NEVER** silently alter non-target content

### Deterministic Execution (PRINCIPLE-01)

Every action has:
- Clear INPUT → OUTPUT specification
- Verification before commit
- Diff-format changes only

## Processing Pipeline

```
PHASE 0: INITIALIZATION
  → Build NAV_MAP
  → Create workspace isolation
  → Init checkpoint

PHASE 1: SEARCH & DISCOVERY
  → Pattern detection
  → Issue identification

PHASE 2: ANALYSIS & CLASSIFICATION
  → Classify issues (SEV-1..4)
  → Build execution plan

PHASE 3: PLANNING
  → Create batch structure
  → Set rollback points

PHASE 4: EXECUTION & VALIDATION
  → Apply surgical patches
  → Verify changes

PHASE 5: DELIVERY & HYGIENE
  → Clean output
  → Generate artifacts
```

## Verification Gates

| Gate | Condition | Action |
|------|-----------|--------|
| GATE-00 | NAV_MAP complete | BLOCK if fail |
| GATE-01 | Patterns scanned | BLOCK if fail |
| GATE-02 | Issues classified | BLOCK if fail |
| GATE-03 | Plan validated | BLOCK if fail |
| GATE-04 | Validation pass | BLOCK/WARN |
| GATE-05 | Artifacts complete | BLOCK if fail |

## Tool Matrix

| Need | Tool |
|------|------|
| Find pattern | `grep -rn "pattern" dir/` |
| Extract section | `sed -n '/START/,/END/p'` |
| Validate JSON | `python -m json.tool file.json` |
| Checksum | `sha256sum <file>` |
| Binary detection | `file <path>` |

## Current State

After reading this file:
1. Read `SKILL.md` for agent configuration
2. Read `PROTOCOL.md` for full protocol specification
3. Check `inputs/` for files to process
4. Check `checkpoints/` for resumption state

---

**Protocol Version**: See `VERSION` file
**Status**: EARLY_ADOPTER
**Entry Point**: `AGENTS.md`
