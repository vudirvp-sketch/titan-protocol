---
purpose: "Context-aware hints for agents with STOP/PROCEED/GO signals"
audience: ["agents"]
when_to_read: "When encountering signals or gates in processing"
related_files: ["PROTOCOL.md", "AGENTS.md"]
stable_sections: ["stop-signals", "proceed-signals", "go-signals"]
emotional_tone: "directive, cautionary, clear"
---

# Context Hints — TITAN FUSE Protocol

> Signals and hints for agent navigation and decision-making.

---

## 🔴 STOP SIGNALS

**HALT execution and wait for resolution:**

| Signal | When You See It | What To Do |
|--------|----------------|------------|
| `GATE-00` FAIL | After Phase 0 | NAV_MAP missing — rebuild index before proceeding |
| `GATE-01` FAIL | After Phase 1 | Not all patterns scanned — complete pattern detection |
| `GATE-02` FAIL | After Phase 2 | Issues not classified — assign ISSUE_ID to all issues |
| `GATE-03` FAIL | After Phase 3 | Plan not validated OR KEEP_VETO violation |
| `GATE-04` BLOCK | After Phase 4 | SEV-1 gaps > 0 OR SEV-2 gaps > 2 OR total gaps > 20% |
| `GATE-05` FAIL | After Phase 5 | Artifacts missing or hygiene incomplete |
| `SEV-1` issue | In classification | Halt, request human review before proceeding |
| `KEEP_VETO: TRUE` | In issue classification | Cannot modify this section — exclude from batch |
| `BUDGET_EXCEEDED` | During processing | Stop all operations, write checkpoint, report status |
| `source_checksum` mismatch | On checkpoint resume | Source file changed — cannot resume, start fresh |
| `INVAR-01` violation | Any time | Fabrication detected — mark [gap: ...] and correct |
| `INVAR-02` violation | Any time | Attempted to modify protected content — ABORT batch |

---

## 🟡 PROCEED WITH CAUTION

**Continue but with awareness:**

| Signal | When You See It | What To Do |
|--------|----------------|------------|
| `GATE-04` WARN | After Phase 4 | SEV-3 gaps > 5 OR SEV-4 gaps > 10 — proceed with human acknowledgement |
| `BUDGET_WARNING` | At 90% budget | Suspend SEV-3/4 batches, report remaining budget |
| `skill_version > agent_version` | On bootstrap | Some directives may be unsupported — log and proceed |
| `protocol_version mismatch` | On bootstrap | Verify compatibility manually, require acknowledgement |
| `[gap: ...]` in output | Any time | Mark explicitly, continue processing |
| `partial_resumption` | Checkpoint recovery | Some chunks lost — recover what's available |
| `circular_dependency` | Multi-file processing | Process in queue order, flag for review |
| `no write access` | Bootstrap phase | Use IN_MEMORY_BUFFER, disable git rollback |
| `llm_query_failed` | During processing | Mark gap, continue without that result |

---

## 🟢 GO SIGNALS

**Proceed normally:**

| Signal | When You See It | What To Do |
|--------|----------------|------------|
| `GATE-00` PASS | After Phase 0 | Proceed to Phase 1 |
| `GATE-01` PASS | After Phase 1 | Proceed to Phase 2 |
| `GATE-02` PASS | After Phase 2 | Proceed to Phase 3 |
| `GATE-03` PASS | After Phase 3 | Proceed to Phase 4 |
| `GATE-04` PASS | After Phase 4 | Proceed to Phase 5 |
| `GATE-05` PASS | After Phase 5 | Deliver output |
| `GATE-REPO-00` PASS | Repo navigation | Proceed to bootstrap |
| `GATE-REPO-01` PASS | Bootstrap complete | Proceed to TIER 0 |
| `GATE-REPO-02` PASS | Multi-file ready | Proceed with processing |
| `VALIDATION: PASS` | After any check | Continue to next step |
| `checkpoint VALID` | Resume session | Restore state and continue |
| `PATCH: SKIPPED` | Patch engine | Already applied — no-op, continue |
| `BATCH COMPLETE` | After batch | Update STATE_SNAPSHOT, continue |

---

## 📊 GATE-04 Threshold Reference

```
BLOCK if ANY of:
├─ open SEV-1 gaps > 0        (zero tolerance for critical)
├─ open SEV-2 gaps > 2        (max 2 high-severity)
└─ total open gaps > 20% of issues

WARN if ANY of:
├─ open SEV-3 gaps > 5
└─ open SEV-4 gaps > 10

PASS if:
└─ all above conditions false
```

---

## 🔄 State Transitions

### Chunk Status

| From | To | Trigger |
|------|-----|---------|
| PENDING | IN_PROGRESS | Start processing |
| IN_PROGRESS | COMPLETE | Processing done, validated |
| IN_PROGRESS | FAILED | Validation failed after 2 retries |
| FAILED | PENDING | Manual retry requested |

### Issue Status

| From | To | Trigger |
|------|-----|---------|
| OPEN | CLOSED | Fix applied and validated |
| OPEN | DEFERRED | Marked for later resolution |
| DEFERRED | OPEN | Re-prioritized |

### Gate Status

| From | To | Trigger |
|------|-----|---------|
| PENDING | PASS | All conditions met |
| PENDING | BLOCK | Blocking condition found |
| PENDING | WARN | Warning condition found |
| BLOCK | PASS | Issue resolved |
| WARN | PASS | Human acknowledgement |

---

## ⚡ Quick Decision Flow

```
Is there a SEV-1 issue?
├─ YES → STOP → Request human review
└─ NO ↓

Is there a KEEP_VETO section?
├─ YES → Exclude from batch
└─ NO ↓

Is budget > 90%?
├─ YES → WARN → Suspend low-priority
└─ NO ↓

All patterns scanned?
├─ NO → STOP → Complete scanning
└─ YES ↓

All issues classified?
├─ NO → STOP → Assign ISSUE_ID
└─ YES ↓

GATE conditions met?
├─ NO → STOP → Resolve blockers
└─ YES → PROCEED
```

---

## 📝 Gap Marking Convention

When marking gaps, use this format:

```
[gap: <type> — <description> — <optional context>]
```

**Types:**
- `not_in_sources` — Data absent from input
- `validation_incomplete` — Could not validate after 2 retries
- `llm_query_failed` — Sub-query failed
- `binary_file` — Cannot process binary
- `encoding_unresolvable` — Cannot read file encoding
- `circular_dependency` — Dependency cycle detected
- `cross_file_patch_not_supported` — Feature not available
- `repo_unreachable` — Cannot access repository

---

## 🎯 Context-Aware Recommendations

| Context | Recommendation |
|---------|----------------|
| Processing file > 30k lines | Reduce chunk size to 500-800 |
| SEV-1 gap found | Stop, document, request review |
| Multiple SEV-2 issues | Prioritize by impact |
| Budget at 50% | Check remaining work |
| Session interrupted | Load checkpoint, verify source_checksum |
| New validator added | Auto-loaded in Phase 2 |

---

**Related:** `.ai/nav_map.json` for semantic lookup
**Full Protocol:** `PROTOCOL.md`
**Entry Point:** `AGENTS.md`
