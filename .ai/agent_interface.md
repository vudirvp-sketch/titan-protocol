---
purpose: "Specification for agent-to-repository communication via natural language"
audience: ["agents", "developers"]
when_to_read: "When implementing agent commands or queries"
related_files: [".ai/shortcuts.yaml", ".ai/nav_map.json"]
stable_sections: ["supported-commands", "response-format"]
emotional_tone: "technical, structured, clear"
---

# Agent Interface — TITAN FUSE Protocol

> Specification for agent-to-repository "communication" via natural language commands.

---

## Supported Commands

### Navigation Commands

```
Command: "nav: find <concept>"
Purpose: Locate concept in repository
Response: Jump to location + show summary

Example:
  Agent: "nav: find verification gates"
  → Response: Jump to PROTOCOL.md#verification-gates
             + Show GATE-00..05 summary table
```

```
Command: "nav: where is <file/section>"
Purpose: Find file or section location
Response: Path + related files

Example:
  Agent: "nav: where is chunking strategy"
  → Response: PROTOCOL.base.md#PRINCIPLE-04
             Related: config.yaml#chunking
```

```
Command: "nav: shortcuts"
Purpose: List available shortcuts
Response: All shortcuts from .ai/shortcuts.yaml
```

### Status Commands

```
Command: "status" or "what now?"
Purpose: Get current state and suggested action
Response: STATE_SNAPSHOT + next recommended action

Example:
  Agent: "what now?"
  → Response: {
               "current_phase": "PHASE_2",
               "next_action": "Classify remaining issues",
               "gates_passed": ["GATE-00", "GATE-01"],
               "pending_issues": 12
             }
```

```
Command: "checkpoint status"
Purpose: Check checkpoint validity
Response: VALID/PARTIAL/INVALID + recoverable chunks

Example:
  Agent: "checkpoint status"
  → Response: {
               "status": "PARTIAL",
               "recoverable_chunks": ["C1", "C2", "C3"],
               "lost_chunks": ["C4", "C5"],
               "reason": "source_checksum mismatch"
             }
```

### Configuration Commands

```
Command: "config get <setting>"
Purpose: Retrieve configuration value
Response: Value from config.yaml or SKILL.md

Example:
  Agent: "config get max_tokens"
  → Response: 100000 (from config.yaml#session.max_tokens)
```

```
Command: "config limits"
Purpose: Show all session limits
Response: Table of limits and current values

Example:
  Agent: "config limits"
  → Response: | Setting | Value | Current |
             |---------|-------|---------|
             | max_tokens | 100000 | 45000 |
             | max_time_minutes | 60 | 23 |
```

### Debug Commands

```
Command: "debug <error_type>"
Purpose: Get troubleshooting guidance
Response: Steps from README.md#troubleshooting

Example:
  Agent: "debug GATE-04 BLOCK"
  → Response: "GATE-04 blocks when:
               - SEV-1 gaps > 0 → Fix critical issues first
               - SEV-2 gaps > 2 → Resolve high-severity issues
               - Total gaps > 20% → Review classification"
```

```
Command: "explain <concept>"
Purpose: Get detailed explanation
Response: Definition + examples + related concepts

Example:
  Agent: "explain parallel_safe"
  → Response: "A batch is parallel_safe if:
               [P1] No overlapping line ranges
               [P2] No output dependencies
               [P3] No KEEP markers touched
               [P4] No shared symbols modified"
```

### Action Commands

```
Command: "start processing"
Purpose: Initialize processing pipeline
Response: STATE_SNAPSHOT with next actions

Triggers:
  - Read SKILL.md
  - Read config.yaml
  - Check inputs/ for files
  - Initialize checkpoint
```

```
Command: "resume session"
Purpose: Resume from checkpoint
Response: Restored STATE_SNAPSHOT or error

Preconditions:
  - checkpoint.json exists
  - source_checksum matches (for full resume)
```

---

## Response Format

### Standard Response Structure

```
┌─────────────────────────────────────────────────────────────┐
│ COMMAND: <command>                                          │
│ STATUS: SUCCESS | PARTIAL | FAILED                          │
│ ─────────────────────────────────────────────────────────── │
│ RESULT:                                                     │
│   <response content>                                        │
│                                                             │
│ NEXT ACTIONS:                                               │
│   - <suggested action 1>                                    │
│   - <suggested action 2>                                    │
│                                                             │
│ RELATED:                                                    │
│   - <related file/section 1>                                │
│   - <related file/section 2>                                │
└─────────────────────────────────────────────────────────────┘
```

### Error Response Structure

```
┌─────────────────────────────────────────────────────────────┐
│ COMMAND: <command>                                          │
│ STATUS: FAILED                                              │
│ ─────────────────────────────────────────────────────────── │
│ ERROR: <error type>                                         │
│ MESSAGE: <human-readable message>                           │
│                                                             │
│ RECOVERY OPTIONS:                                           │
│   1. <option 1>                                             │
│   2. <option 2>                                             │
│                                                             │
│ DOCUMENTATION:                                              │
│   See <file#section> for more information                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Emotional Tone Guide

| Situation | Tone | Example |
|-----------|------|---------|
| Successful navigation | Confident, concise | "Found: PROTOCOL.md#verification-gates" |
| Error encountered | Calm, helpful | "GATE-04 blocked. Here's how to resolve..." |
| Critical issue | Urgent, clear | "⚠️ SEV-1 issue detected. Stop and review." |
| Configuration | Neutral, factual | "max_tokens: 100000 (default)" |
| Debugging | Analytical, supportive | "Let's diagnose this step by step..." |
| Completion | Satisfied, informative | "✅ Phase 3 complete. Proceeding to Phase 4." |

---

## Command Aliases

| Canonical | Aliases |
|-----------|---------|
| `nav: find` | `find`, `locate`, `where`, `goto` |
| `status` | `what now`, `current state`, `progress` |
| `config get` | `get config`, `setting`, `value` |
| `debug` | `troubleshoot`, `help`, `fix` |
| `explain` | `what is`, `define`, `describe` |
| `start processing` | `begin`, `init`, `start` |
| `resume session` | `resume`, `continue`, `restore` |

---

## Batch Mode

For programmatic access, commands can be batched:

```
BATCH:
  - "nav: find verification_gates"
  - "config get max_tokens"
  - "status"

RESPONSE:
  - result_1: "PROTOCOL.md#verification-gates"
  - result_2: 100000
  - result_3: { "phase": "PHASE_2", "next": "classify issues" }
```

---

## Integration Notes

- Commands are case-insensitive
- Partial matches are supported for concept names
- Aliases are resolved via `.ai/nav_map.json` semantic_index
- Shortcuts are resolved via `.ai/shortcuts.yaml`
- Context hints are applied from `.ai/context_hints.md`

---

**Version:** 1.0.0
**Protocol Version:** 3.2.0
**Related:** `.ai/shortcuts.yaml`, `.ai/nav_map.json`, `.ai/context_hints.md`
