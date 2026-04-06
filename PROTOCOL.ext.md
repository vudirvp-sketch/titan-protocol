---
title: TITAN FUSE — BOOTSTRAP EXTENSION v1.0
extends: Large-File Agent Protocol v3.1
tier: -1
domain: repo_bootstrap; self_initialization; repo_navigation
status: DRAFT — append to main protocol before TIER 0
purpose: "TIER -1 Bootstrap extension for repository navigation and self-initialization"
audience: ["agents"]
when_to_read: "When agent enters repository or needs to self-initialize"
related_files: ["PROTOCOL.base.md", "SKILL.md", "AGENTS.md"]
stable_sections: ["PHASE -1 — ENTRY DETECTION", "Step -1.2: Bootstrap Sequence"]
emotional_tone: "directive, bootstrapping, initialization"
ideal_reader_state: "starting a new session or entering a repository"
changelog: v1.0 — initial bootstrap phase; repo navigation patterns; repo-as-host model; .gitignore; multi-file coordination stub
---

# TIER -1 — BOOTSTRAP PHASE

> **Когда активируется**: агент получает ссылку на репозиторий ИЛИ обнаруживает `SKILL.md` / `PROTOCOL.md` в корне рабочей директории вместо конкретного файла для обработки.
>
> **Порядок выполнения**: TIER -1 → TIER 0 → TIER 1 → TIER 2 (стандартный пайплайн).
>
> **Инвариант**: Bootstrap НЕ модифицирует никаких файлов репозитория. Только чтение и инициализация.

---

## PHASE -1 — ENTRY DETECTION

### Step -1.0: Entry Point Classification

```
DETECT entry type:

  IF input is a URL matching github.com/{user}/{repo}:
    → MODE: REPO_NAVIGATE
    → goto Step -1.1 (Repo Navigation)

  IF input is a raw file path or raw.githubusercontent.com URL:
    → MODE: FILE_DIRECT
    → skip TIER -1, goto TIER 0 directly (standard pipeline)

  IF input is a repomix file (XML/plaintext, typically >5000 lines):
    → MODE: REPOMIX
    → skip TIER -1, goto TIER 0 (Environment Offload will activate)

  IF current directory contains SKILL.md or PROTOCOL.md:
    → MODE: REPO_HOST
    → goto Step -1.2 (Self-Init from Repo)

  IF no clear input detected:
    → STOP: request clarification
    → output: "Specify: repo URL / file path / repomix / task description"
```

---

## PHASE -1A — REPO NAVIGATION (MODE: REPO_NAVIGATE)

### Step -1.1: Repository Orientation

```
GOAL: understand repo structure WITHOUT loading everything into context.

SEQUENCE:
  1. Fetch UI page: github.com/{user}/{repo}
     → extract: README summary, top-level file tree, default branch name
     → DO NOT parse raw HTML; use web_fetch → markdown extraction

  2. Scan for bootstrap anchors (in order of priority):
     ├─ README.md         → "start here" instructions
     ├─ SKILL.md          → agent initialization directives
     ├─ PROTOCOL.md       → processing rules override
     └─ inputs/           → candidate files for processing

  3. Build REPO_MAP:
     {
       "repo":          "{user}/{repo}",
       "branch":        "<default_branch>",
       "bootstrap_doc": "<SKILL.md | README.md | null>",
       "input_targets": ["<path>", ...],   // files to process
       "output_dir":    "<outputs/ | null>",
       "checkpoint_dir":"<checkpoints/ | null>"
     }

GATE-REPO-00: REPO_MAP built AND bootstrap_doc identified → PROCEED to Step -1.2
              IF bootstrap_doc = null → warn + use README.md as fallback
```

### Step -1.1.1: URL Resolution Rules

```
RULE: UI vs Raw — choose based on purpose.

  github.com/{user}/{repo}/blob/{branch}/{path}
    → USE FOR: navigation, structure overview, PR/Issues inspection
    → NEVER feed raw HTML to llm_query

  raw.githubusercontent.com/{user}/{repo}/{branch}/{path}
    → USE FOR: loading file content into context / WORK_DIR
    → This is load_file(target_path) input for Step 0.2
    → Valid for: scripts, configs, YAML, JSON, PROTOCOL.md, repomix output

  CONVERSION:
    github.com/{user}/{repo}/blob/{branch}/{path}
    → raw.githubusercontent.com/{user}/{repo}/{branch}/{path}
    (replace domain, remove /blob/)
```

---

## PHASE -1B — SELF-INITIALIZATION (MODE: REPO_HOST)

### Step -1.2: Bootstrap Sequence

```
PURPOSE: agent reads its own operating instructions from the repo it lives in.

SEQUENCE (strict order — do not skip):

  STEP 1: Read README.md
    → extract: "start here" block, task list, contact / escalation path
    → if no README: log [gap: no README — repo not self-describing]

  STEP 2: Read SKILL.md
    → load agent directives: domain, constraints, tool permissions, output format
    → SKILL.md overrides defaults from main protocol where explicitly stated
    → SKILL.md CANNOT override TIER 0 invariants (INVAR-01..04)

  STEP 3: Read PROTOCOL.md (if present)
    → check frontmatter: protocol_version, extends field
    → verify compatibility: IF protocol_version > current agent version → warn
    → load any phase/gate overrides

  STEP 4: Discover inputs/
    → list files in inputs/ directory
    → classify each: text | binary | repomix | unknown
    → binary → skip + log [gap: binary_file — {path}]
    → build INPUT_QUEUE: [{path, type, priority}]

  STEP 5: Check checkpoints/
    → IF checkpoint.json exists → attempt resumption (see Step 0.5 logic)
    → IF source_checksum mismatch → ABORT resumption + start fresh + warn

  STEP 6: Init STATE_SNAPSHOT with repo context:
    repo_url:        {user}/{repo}
    branch:          <branch>
    skill_version:   <from SKILL.md frontmatter>
    protocol_source: REPO_HOST | EXTERNAL | INLINE
    input_queue:     [<paths>]
    output_target:   outputs/
    checkpoint_path: checkpoints/checkpoint.json

GATE-REPO-01: all 6 steps complete AND INPUT_QUEUE non-empty → PROCEED to TIER 0
              IF INPUT_QUEUE empty → STOP + report: "No processable inputs found in inputs/"
```

### Step -1.3: Version Compatibility Check

```
COMPATIBILITY MATRIX:

  skill_version vs agent_version:
    EQUAL          → full compatibility
    SKILL > AGENT  → warn: [gap: skill version ahead of agent — some directives may be unsupported]
                     → proceed with best-effort, log unsupported directives
    AGENT > SKILL  → safe: newer agent is backward compatible by default

  protocol_extends field:
    IF extends ≠ "Large-File Agent Protocol v3.1":
      → warn: [gap: protocol base mismatch — verify compatibility manually]
      → require human acknowledgement before proceeding

INVARIANT: version warnings do NOT block execution unless INVAR-01 (anti-fabrication) is at risk.
```

---

## PHASE -1C — REPO-AWARE ROLLBACK EXTENSION

### Step -1.4: Git-Backed Rollback Points

```
EXTENDS: TIER 4 — ROLLBACK PROTOCOL

WHEN repo has git access (MODE: REPO_NAVIGATE or REPO_HOST):

  ROLLBACK_POINTS augmented with:
    {
      "type":   "git_commit",
      "ref":    "<commit_hash or branch@HEAD>",
      "note":   "pre-session baseline",
      "fetch":  "raw.githubusercontent.com/{user}/{repo}/{hash}/{path}"
    }

  RECOVERY via git ref:
    IF ROLLBACK triggered AND git_commit ref available:
      → fetch SOURCE_FILE at rollback ref via raw URL
      → replace WORK_DIR/working_copy
      → log: "Rolled back to commit {hash}"
      → continue from Step 0.4

  BRANCH AS ROLLBACK POINT (optional, requires write access):
    CREATE branch: titan-ws-{session_id}
    PUSH checkpoint artifacts to branch
    ON ROLLBACK: reset to branch base
```

---

## PHASE -1D — MULTI-FILE COORDINATION STUB

### Step -1.5: Multi-File Input Handling

```
STATUS: partial implementation — single-file processing is primary mode.

WHEN INPUT_QUEUE contains > 1 file:

  STEP 1: Classify relationships
    → for each pair (A, B): check SYMBOL_MAP.json for cross-references
    → build DEPENDENCY_GRAPH: {file → [files it depends on]}

  STEP 2: Determine processing order
    → topological sort of DEPENDENCY_GRAPH
    → independent files → process in INPUT_QUEUE order (no guaranteed parallelism)

  STEP 3: Per-file processing
    → for each file in sorted order:
        ├─ run standard TIER 0–5 pipeline
        ├─ on GATE-05 PASS: commit outputs to outputs/{filename}_merged.md
        └─ update shared SYMBOL_MAP.json with this file's symbols

  COORDINATION RULES:
    ├─ Each file gets its own WORK_DIR / IN_MEMORY_BUFFER
    ├─ SYMBOL_MAP.json is shared state — write-lock per file
    ├─ Cross-file patches BLOCKED in v1.0 — log [gap: cross-file-patch-not-supported]
    └─ Max 3 files per session without explicit human approval

GATE-REPO-02: DEPENDENCY_GRAPH built AND processing order confirmed → PROCEED
              (skip if INPUT_QUEUE has exactly 1 file)
```

---

## TIER -1: VERIFICATION GATES SUMMARY

```
GATE-REPO-00: REPO_MAP built AND bootstrap_doc identified
GATE-REPO-01: bootstrap sequence complete (Steps 1–6) AND INPUT_QUEUE non-empty
GATE-REPO-02: DEPENDENCY_GRAPH built AND processing order confirmed (multi-file only)

FAILURE HANDLING:
  GATE-REPO-00 FAIL → STOP + report repo structure issue + await instruction
  GATE-REPO-01 FAIL → STOP + report: specific step that failed
  GATE-REPO-02 FAIL → WARN + fall back to INPUT_QUEUE order (no dependency sorting)
```

---

## REPO STRUCTURE — REFERENCE LAYOUT

```
Рекомендуемая структура репозитория-хоста протокола:

/
├── README.md              ← "start here"; task list; escalation path
├── SKILL.md               ← agent directives (overrides protocol defaults)
├── PROTOCOL.md            ← this protocol (или ссылка на canonical source)
├── inputs/                ← входные файлы для обработки (text, repomix)
│   └── .gitkeep
├── outputs/               ← результаты (INDEX.md, CHANGE_LOG.md, merged files)
│   └── .gitkeep
├── checkpoints/           ← checkpoint.json для resumption
│   └── .gitkeep
├── skills/                ← дополнительные модули (валидаторы, шаблоны)
└── .gitignore
```

### .gitignore для репозитория-хоста

```gitignore
# Agent working directories
/tmp/titan_ws_*/
*.checkpoint.json.tmp

# Intermediate artifacts (keep final only)
WORK_DIR/
working_copy/

# Debug and draft outputs
*.debug.md
*_draft.md
*_iter*.md

# OS artifacts
.DS_Store
Thumbs.db
```

---

## FAILSAFE — BOOTSTRAP-SPECIFIC SCENARIOS

```yaml
EXTENDS: TIER 5 — FAILSAFE PROTOCOL

repo_unreachable:
  action:
    - Log: [gap: repo_unreachable — {url} — HTTP {status}]
    - IF raw URL fallback known → attempt raw.githubusercontent.com directly
    - IF no fallback: STOP + report + await instruction

skill_md_malformed:
  action:
    - Attempt partial parse: extract any valid directive blocks
    - Log: [gap: SKILL.md parse error — {lines} — partial load]
    - Proceed with partially-loaded directives + warn

no_inputs_found:
  action:
    - STOP execution (cannot proceed without target)
    - Report: "inputs/ is empty or missing. Add files to process."
    - Suggest: create inputs/ directory + add target files

circular_dependency_in_files:
  action:
    - Log: [gap: circular_dependency — {file_A} ↔ {file_B}]
    - Break cycle: process in INPUT_QUEUE order
    - Flag for human review post-delivery

write_access_unavailable:
  action:
    - Switch WORK_DIR to IN_MEMORY_BUFFER
    - Disable git-backed rollback (Step -1.4)
    - Log: [gap: no write access — git rollback disabled]
    - Continue with in-memory isolation
```

---

## UPDATED EXECUTION DIRECTIVE — PREPEND TO EXISTING

```
PRE-INITIALIZATION (TIER -1 — runs before standard Step 1):

0a. Classify entry point → Step -1.0
0b. IF MODE = FILE_DIRECT or REPOMIX → skip to standard Step 1
0c. IF MODE = REPO_NAVIGATE → execute Phase -1A (Steps -1.1, -1.1.1)
0d. IF MODE = REPO_HOST → execute Phase -1B (Steps -1.2, -1.3)
0e. Execute Phase -1C → init git-backed rollback points (if applicable)
0f. IF INPUT_QUEUE > 1 file → execute Phase -1D (Step -1.5)
0g. Verify all GATE-REPO-* gates → PROCEED to standard Step 1

→ Continue with standard INITIALIZATION (Steps 1–6 of EXECUTION DIRECTIVE)
```

---

## INTEGRATION NOTES — TIER -1

```
Tier -1 synthesizes:
- Entry Point Classification (MODE detection)
- Repo Navigation (UI vs Raw URL resolution)
- Self-Initialization from SKILL.md / README.md / PROTOCOL.md
- Version Compatibility Check (skill_version vs agent_version)
- Git-Backed Rollback Extension (augments TIER 4)
- Multi-File Coordination Stub (dependency graph, processing order)
- Bootstrap-Specific Failsafes (augments TIER 5)
- Repo Structure Reference (.gitignore, recommended layout)

Invariant: TIER -1 is read-only. No file modifications before GATE-REPO-01 PASS.
Invariant: SKILL.md overrides are scoped — cannot override INVAR-01..04 or GATE logic.
Invariant: MODE detection is deterministic — no ambiguous states permitted.

Architecture extension: bootstrap-safe, repo-aware, backward-compatible with v3.1.
```

