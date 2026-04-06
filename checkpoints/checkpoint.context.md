---
purpose: "Context and usage guide for checkpoint system"
audience: ["agents", "developers"]
when_to_read: "When working with session persistence or resumption"
related_files: ["PROTOCOL.base.md#Step-0.5", "scripts/validate_checkpoint.py"]
stable_sections: ["philosophy", "anti-patterns", "resumption-workflow"]
emotional_tone: "technical, practical, restorative"
---

# checkpoint.context.md

## Philosophy

The checkpoint system enables **session persistence across context resets and interruptions**. It captures the complete state of a processing session, allowing resumption without loss of progress.

**Why this exists:**
- LLM sessions have token/context limits
- Processing large files takes multiple sessions
- Network interruptions happen
- Human review may pause work

**Key principle:** Checkpoints are write-only-append for gates_passed and completed_batches. Never delete entries, only add.

---

## Checkpoint Structure

```json
{
  "session_id": "uuid-v4-string",
  "protocol_version": "3.2.0",
  "source_file": "/path/to/source.md",
  "source_checksum": "sha256-hash",
  "gates_passed": ["GATE-00", "GATE-01", "GATE-02"],
  "completed_batches": ["BATCH_001", "BATCH_002"],
  "open_issues": ["ISSUE-003", "ISSUE-007"],
  "chunk_cursor": "C3",
  "chunk_checksums": {
    "C1": "sha256-of-chunk-c1",
    "C2": "sha256-of-chunk-c2"
  },
  "timestamp": "2026-04-06T12:00:00Z",
  "status": "IN_PROGRESS | COMPLETE | PARTIAL"
}
```

---

## Anti-Patterns

### ❌ DO NOT:

1. **Resume after source_checksum mismatch without warning**
   ```python
   # WRONG
   if checkpoint['source_checksum'] != current_checksum:
       restore_anyway()  # Dangerous!
   ```
   Source may have changed; warn user.

2. **Delete completed batches from checkpoint**
   ```python
   # WRONG
   checkpoint['completed_batches'] = []  # Lost history!
   ```
   Checkpoint is append-only for batches and gates.

3. **Skip chunk_checksums for large files**
   ```python
   # WRONG
   checkpoint['chunk_checksums'] = {}  # No recovery possible!
   ```
   Chunk checksums enable partial recovery.

4. **Continue with stale checkpoint**
   ```python
   # WRONG
   if checkpoint_age > 30 days:
       restore(checkpoint)  # May be inconsistent!
   ```
   Respect max_checkpoint_age_days setting.

5. **Write checkpoint only at end**
   ```python
   # WRONG
   # ... all processing ...
   write_checkpoint(final_state)  # No recovery if crash!
   ```
   Write after each GATE and batch.

---

## Example Invocation

### Writing Checkpoint

```python
import json
import hashlib
from datetime import datetime

def write_checkpoint(
    session_id: str,
    source_file: str,
    gates_passed: list,
    completed_batches: list,
    chunk_cursor: str,
    chunk_checksums: dict
):
    with open(source_file, 'rb') as f:
        source_checksum = hashlib.sha256(f.read()).hexdigest()

    checkpoint = {
        "session_id": session_id,
        "protocol_version": "3.2.0",
        "source_file": source_file,
        "source_checksum": source_checksum,
        "gates_passed": gates_passed,
        "completed_batches": completed_batches,
        "chunk_cursor": chunk_cursor,
        "chunk_checksums": chunk_checksums,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "IN_PROGRESS"
    }

    with open("checkpoints/checkpoint.json", 'w') as f:
        json.dump(checkpoint, f, indent=2)

# Call after each GATE passage
write_checkpoint(
    session_id="abc-123",
    source_file="inputs/large_file.md",
    gates_passed=["GATE-00", "GATE-01"],
    completed_batches=["BATCH_001"],
    chunk_cursor="C2",
    chunk_checksums={"C1": "hash1", "C2": "hash2"}
)
```

### Validating Checkpoint

```bash
python scripts/validate_checkpoint.py checkpoints/checkpoint.json
```

Output:
```
Checkpoint Status: VALID
Session ID: abc-123
Protocol Version: 3.2.0
Source Checksum: matches
Gates Passed: GATE-00, GATE-01, GATE-02
Completed Batches: BATCH_001, BATCH_002
Chunk Cursor: C3
Recoverable Chunks: C1, C2, C3
```

### Resuming from Checkpoint

```python
def resume_session(checkpoint_path: str, source_path: str):
    with open(checkpoint_path) as f:
        checkpoint = json.load(f)

    # Verify source unchanged
    with open(source_path, 'rb') as f:
        current_checksum = hashlib.sha256(f.read()).hexdigest()

    if current_checksum != checkpoint['source_checksum']:
        return {
            "status": "SOURCE_CHANGED",
            "message": "Source file modified since last session",
            "action": "Start fresh or use partial recovery"
        }

    # Restore state
    return {
        "status": "VALID",
        "session_id": checkpoint['session_id'],
        "gates_passed": checkpoint['gates_passed'],
        "completed_batches": checkpoint['completed_batches'],
        "resume_from": checkpoint['chunk_cursor']
    }
```

---

## Resumption Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    CHECKPOINT RESUMPTION                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Load checkpoint.json                                    │
│     ↓                                                       │
│  2. Verify source_checksum                                  │
│     ├─ MATCH → Full resumption                              │
│     └─ MISMATCH ↓                                           │
│  3. Check chunk_checksums                                   │
│     ├─ Some match → Partial resumption                      │
│     └─ None match → Start fresh                             │
│     ↓                                                       │
│  4. Restore STATE_SNAPSHOT                                  │
│     ↓                                                       │
│  5. Skip completed batches                                  │
│     ↓                                                       │
│  6. Continue from chunk_cursor                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Partial Recovery

When source file has changed but some chunks are recoverable:

```python
def partial_recovery(checkpoint: dict, new_source: str):
    """Recover what we can from changed source."""
    new_chunks = chunk_file(new_source)
    recoverable = []

    for chunk_id, old_checksum in checkpoint['chunk_checksums'].items():
        # Find corresponding chunk in new file
        new_chunk = find_chunk_by_content_hash(new_chunks, old_checksum)
        if new_chunk:
            recoverable.append({
                "chunk_id": chunk_id,
                "status": "RECOVERED",
                "new_location": new_chunk.location
            })
        else:
            recoverable.append({
                "chunk_id": chunk_id,
                "status": "LOST",
                "reason": "Content changed"
            })

    return recoverable
```

---

## Status Values

| Status | Meaning | Action |
|--------|---------|--------|
| `IN_PROGRESS` | Session active, not complete | Resume or continue |
| `COMPLETE` | All phases done, delivered | Archive or start new |
| `PARTIAL` | Some chunks recoverable | Partial resumption |

---

## Configuration

From `config.yaml`:

```yaml
checkpoint:
  format_version: "2.0"
  chunk_checksums: true      # Enable chunk-level recovery
  partial_resumption: true   # Allow partial recovery
  max_age_days: 30           # Max checkpoint age
  path: checkpoints/checkpoint.json
```

---

## Protocol Integration

| Phase | Checkpoint Action |
|-------|-------------------|
| Phase 0 (Step 0.5) | Initialize checkpoint |
| After each GATE | Update gates_passed |
| After each batch | Update completed_batches |
| Phase 5 | Set status to COMPLETE |
| On ROLLBACK | Restore from checkpoint |
| On session start | Check for existing checkpoint |

---

## Connections to Other Protocol Parts

| Component | Connection |
|-----------|------------|
| `PROTOCOL.base.md#Step-0.5` | Checkpoint specification |
| `scripts/validate_checkpoint.py` | Validation utility |
| `TIER 4 — ROLLBACK` | Recovery via checkpoint |
| `TIER 5 — FAILSAFE` | session_interrupted handling |
| `config.yaml#checkpoint` | Configuration source |

---

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| Checkpoint rejected | source_checksum mismatch | Start fresh or use partial recovery |
| Partial recovery unavailable | chunk_checksums disabled | Enable in config.yaml |
| Checkpoint too old | Age > max_age_days | Start fresh session |
| Missing chunk_checksums | Old format checkpoint | Upgrade format_version |
| Session ID mismatch | Wrong checkpoint file | Verify session_id |

---

**Checkpoint Format Version:** 2.0
**Protocol Version:** 3.2.0
**Author:** TITAN FUSE Team
