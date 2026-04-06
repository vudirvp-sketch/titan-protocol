# Extended Gates Documentation

## GATE-INTENT

**Purpose:** Validate intent classification before processing.

| Condition | Status | Details |
|-----------|--------|---------|
| intent_classification set | REQUIRED | Must be one of: `code_review`, `refactor`, `documentation`, `debugging`, `feature_add` |
| intent_confidence >= 0.7 | REQUIRED | Low confidence triggers human confirmation |
| success_criteria defined | REQUIRED | At least one measurable criterion |

**PASS:** All conditions met
**FAIL:** Missing classification or confidence < 0.7 without human ack
**WARN:** Confidence 0.5-0.7

---

## GATE-PLAN

**Purpose:** Validate execution plan before Phase 4.

| Condition | Status | Details |
|-----------|--------|---------|
| execution_plan exists | REQUIRED | Non-empty plan structure |
| batches defined | REQUIRED | At least one batch |
| no KEEP_VETO violations | REQUIRED | Plan respects <!-- KEEP --> markers |
| budget headroom > 10% | REQUIRED | Enough tokens for execution |

**PASS:** All conditions met
**FAIL:** KEEP_VETO violation or budget exceeded
**WARN:** Budget headroom 5-10%

---

## GATE-SKILL

**Purpose:** Validate agent skill configuration.

| Condition | Status | Details |
|-----------|--------|---------|
| SKILL.md exists | REQUIRED | Agent configuration file |
| skill_version compatible | REQUIRED | Matches protocol version range |
| max_files limit respected | REQUIRED | Input count <= max_files_per_session |
| max_tokens limit respected | REQUIRED | Budget within configured limit |

**PASS:** All conditions met
**FAIL:** Limit exceeded
**WARN:** Within 90% of any limit

---

## GATE-SECURITY

**Purpose:** Security validation before execution.

| Condition | Status | Details |
|-----------|--------|---------|
| No secrets in inputs | REQUIRED | Secret scanner returns clean |
| Workspace enforced | REQUIRED | All paths within workspace |
| Config valid | REQUIRED | Schema validation passed |
| Execution mode allowed | REQUIRED | Mode is permitted (sandbox/trusted) |

**PASS:** All conditions met
**FAIL:** Secrets detected, workspace violation, or invalid config
**WARN:** Sandbox not available, falling back to trusted mode

---

## GATE-EXEC

**Purpose:** Validate execution safety.

| Condition | Status | Details |
|-----------|--------|---------|
| Sandbox active (if configured) | CONDITIONAL | Verify Docker/venv status |
| Code execution approved | REQUIRED | Human ack for risky operations |
| Rate limits not exceeded | REQUIRED | API call rate within limits |

**PASS:** All conditions met
**FAIL:** Sandbox required but unavailable, or rate limit exceeded
**WARN:** Approaching rate limit

---

## GATE-REPO-00 (TIER -1)

**Purpose:** Repository bootstrap validation.

| Condition | Status | Details |
|-----------|--------|---------|
| AGENTS.md exists | REQUIRED | Entry point for agents |
| .titan_index.json valid | REQUIRED | Semantic index |
| Git repository detected | OPTIONAL | Enables rollback |

**PASS:** All required conditions met
**FAIL:** Missing AGENTS.md or invalid index

---

## GATE-REPO-01 (TIER -1)

**Purpose:** Repository structure validation.

| Condition | Status | Details |
|-----------|--------|---------|
| inputs/ directory exists | REQUIRED | Files to process |
| outputs/ directory exists | REQUIRED | Generated artifacts |
| checkpoints/ directory exists | REQUIRED | Session persistence |
| Write permissions | REQUIRED | Can create files |

**PASS:** All conditions met
**FAIL:** Missing directory or no write permission

---

## GATE-00 (TIER 0)

**Purpose:** Navigation map validation.

| Condition | Status | Details |
|-----------|--------|---------|
| Source file loaded | REQUIRED | File exists and readable |
| NAV_MAP exists | REQUIRED | Chunks indexed |
| All chunks have IDs | REQUIRED | No orphan chunks |

**PASS:** All conditions met
**FAIL:** Missing source or no chunks

---

## GATE-01 through GATE-05

See PROTOCOL.md for standard gate definitions.
