# TITAN FUSE Agent Interface

## Command Specification

### Navigation Commands

```
READ <file>           — Load file into context
NAVIGATE <directory>  — Change working context
LIST <directory>      — List contents
```

### Processing Commands

```
PROCESS <file>        — Begin processing target file
RESUME <checkpoint>   — Resume from checkpoint
VALIDATE              — Run validation checks
COMMIT                — Commit current batch
ROLLBACK              — Revert to last checkpoint
```

### Query Commands

```
STATUS                — Return STATE_SNAPSHOT
GATES                 — Return gate status
BUDGET                — Return budget status
GAPS                  — Return open gaps
```

### Output Commands

```
OUTPUT <artifact>     — Generate specific artifact
MERGE                 — Generate full merge
CLEAN                 — Apply document hygiene
```

## Response Format

### Success Response

```
✅ <operation> complete
  - Result: <description>
  - Next: <suggested action>
```

### Error Response

```
❌ <operation> failed
  - Reason: <error description>
  - Recovery: <suggested fix>
```

### Blocked Response

```
⛔ BLOCKED at <GATE-XX>
  - Condition: <failed condition>
  - Required: <what needs to be fixed>
  - Action: STOP + await instruction
```

## Session Lifecycle

```
INIT → BOOTSTRAP → PHASE_0 → PHASE_1 → PHASE_2 → PHASE_3 → PHASE_4 → PHASE_5 → COMPLETE
         ↓            ↓         ↓         ↓         ↓         ↓         ↓
      GATE-REPO    GATE-00   GATE-01   GATE-02   GATE-03   GATE-04   GATE-05
```

## Checkpoint Protocol

### Write Checkpoint
```
CHECKPOINT WRITE
  - Triggered by: gate passage, batch completion, timeout
  - Location: checkpoints/checkpoint.json
  - Atomic: full write or none
```

### Read Checkpoint
```
CHECKPOINT READ <path>
  - Validate: protocol_version, source_checksum
  - Restore: gates_passed, completed_batches, chunk_cursor
  - Resume: continue from last state
```

## Interactive Approval

```
┌─────────────────────────────────────────────────────────────┐
│ APPROVAL REQUIRED                                           │
│ ─────────────────────────────────────────────────────────── │
│ Reason: [description]                                       │
│ Current: [current value]                                    │
│ Requested: [requested value]                                │
│ Impact: [consequences]                                      │
│ ─────────────────────────────────────────────────────────── │
│ Options: [Y]es / [N]o / [A]lways / [C]ancel                │
└─────────────────────────────────────────────────────────────┘
```

## Error Codes

| Code | Meaning | Action |
|------|---------|--------|
| E001 | Source file not found | Verify path |
| E002 | Checksum mismatch | Source modified |
| E003 | Budget exceeded | Increase limit or split |
| E004 | Gate blocked | Fix condition |
| E005 | Validation failed | Apply patch or rollback |
| E006 | Recursion limit | Flatten or defer |
| E007 | Binary file | Skip file |
| E008 | Malformed config | Fix YAML/JSON |
