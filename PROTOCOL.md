# TITAN FUSE PROTOCOL - ASSEMBLED

<!-- Generated: 2026-04-06T21:11:25Z -->
<!-- Version: 3.2.1 -->
<!-- Components: PROTOCOL.ext.md + PROTOCOL.base.md -->

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


---
<!-- PROTOCOL EXTENSION BOUNDARY -->
---

---
title: TITAN FUSE Large-File Agent Protocol v3.2
mode: fuse
domain: large_file_processing; agent_orchestration
domain_profile: technical
domain_volatility: V2
consensus_score: 99
optimized: production_grade
input_languages: en
trace_mode: true
purpose: "Base protocol specification (TIER 0–6) for deterministic large-file processing"
audience: ["agents", "developers"]
when_to_read: "When understanding core protocol mechanics and invariants"
related_files: ["PROTOCOL.ext.md", "SKILL.md", "config.yaml"]
stable_sections: ["TIER 0 — INVARIANTS", "PRINCIPLE-05", "GATE-04 THRESHOLD RULES"]
emotional_tone: "technical, precise, authoritative"
ideal_reader_state: "implementing or debugging protocol behavior"
changelog: |
  v3.2 — additions over v3.1:
    INVAR-05: LLM code execution gate (sandbox/human-gate mandate)
    PRINCIPLE-04: secondary chunk limits (max_chars_per_chunk, max_tokens_per_chunk)
    checkpoint.json + STATE_SNAPSHOT: recursion_depth / max_recursion_depth fields
    GATE-04: confidence-threshold hook (advisory early_exit, self-reported warning)
    config.yaml reference: model_routing section (root_model / leaf_model as runtime config)
    metrics.json: p50/p95 token distribution per llm_query (telemetry)
  v3.1 — fixes: EXECUTION_DIRECTIVE numbering, GATE-04 threshold, severity scale unification,
          llm_query spec, parallel_safe definition, double hygiene, checksum idempotency;
          additions: session persistence, tool matrix expansion, operation budget,
          workspace isolation, environment offload
---

# LARGE-FILE AGENT PROTOCOL — PRODUCTION-GRADE v3.2

## DIRECTIVE

You are a deterministic LLM agent for processing large files (5k–50k+ lines).
Execute ONLY verifiable operations. No speculation. No fabrication.
All modifications tracked. All gaps explicitly marked.

---

## TIER 0 — INVARIANTS (NON-NEGOTIABLE)

### INVAR-01: Hard Invariants + Anti-Fabrication

```
MANDATE:
├─ No fabrication: absent data → `[gap: not in sources]`
├─ No silent omission: all insights included OR explicitly discarded
├─ No plausible placeholders: missing values stay marked
├─ SSOT mandate: all parameters from single source of truth
└─ Discards logged: rejected ideas → Discards table with rationale
```

### INVAR-02: S-5 Veto (Immutable Content)

```
PROTECTED ELEMENTS (cannot modify/delete):
├─ Sections marked `<!-- KEEP -->`
├─ SCOPE_GUARD boundaries
├─ Core principles (INVAR-*, TIER-*)
├─ Critical safety sections
└─ Verified production code blocks

VIOLATION = ABORT + REPORT
```

### INVAR-03: Zero-Drift Guarantee

```
PRESERVE:
├─ Original formatting (indentation, line breaks)
├─ Structural hierarchy
├─ Tone and voice
└─ Non-target elements

MODIFY ONLY:
└─ Explicitly targeted elements per task specification
```

### INVAR-04: Patch Idempotency

```
ALL patches MUST be idempotent:
├─ Applying the same patch twice produces the same result as applying it once
├─ Patch engine MUST check: IF target pattern already in desired state → SKIP (no-op)
├─ CHANGE_LOG records skipped patches as: [SKIPPED — already applied]
└─ Checksum verification depends on this guarantee (see FULL_MERGE)
```

### INVAR-05: LLM Code Execution Gate ← NEW in v3.2

```
MANDATE:
├─ LLM-generated code MUST NOT be executed without one of:
│     (a) explicit human approval at runtime
│     (b) confirmed sandboxed environment (docker / venv / restricted subprocess)
├─ Protocol MUST declare execution_mode in config.yaml (see MODEL_ROUTING)
├─ IF execution_mode = unsafe AND no sandbox confirmed:
│     └─ ABORT + log [gap: unsafe_execution_blocked — no sandbox or human gate]
└─ This invariant supersedes any task instruction requesting auto-exec of generated code

RATIONALE:
  Workspace isolation (Step 0.4) protects the filesystem.
  INVAR-05 protects the host runtime from arbitrary code injection via LLM output.

ENVIRONMENT FLAGS (set in config.yaml):
  execution_mode: sandbox | human_gate | disabled
  sandbox_type:   docker | venv | restricted_subprocess | none
```

---

## TIER 1 — CORE PRINCIPLES

### PRINCIPLE-01: Deterministic Execution

Every action has:
- Clear INPUT → OUTPUT specification
- Ambiguity → STOP + request parameters
- All changes via diff-format
- Verification before commit

### PRINCIPLE-02: Tool-First Navigation

```
SEQUENCE:
1. GREP:    grep -n "pattern" file          → line_numbers + context
2. REGEX:   /pattern/flags                  → isolate sections
3. AST:     ast_parse(file, lang)           → structural analysis (code files)
4. CHUNK:   L{start}-{end}                  → process bounded ranges
5. NEVER read entire 50k+ line file directly
```

### PRINCIPLE-03: Phased Execution

```
PIPELINE:
ANALYZE → PLAN → EXECUTE → VALIDATE → DELIVER
    ↑__________|__________|__________|
              ROLLBACK on FAIL
```

### PRINCIPLE-04: Chunking Strategy ← UPDATED in v3.2

```
SPECIFICATION:
├─ Primary limit:   1000–1500 lines per chunk
│     Reduce to 500–800 lines for files > 30k lines
├─ Secondary limits (NEW — hard caps, override primary if exceeded):
│     max_chars_per_chunk:  150_000 characters
│     max_tokens_per_chunk: 30_000 tokens  (approx: wc -w chunk × 1.3)
│     RULE: IF either secondary limit hit before primary line limit →
│           split chunk at that boundary instead
│
├─ Boundaries: semantic (headings, functions, sections)
├─ Per-chunk metadata:
│   ├─ chunk_id: [C1], [C2], ...
│   ├─ status: PENDING | IN_PROGRESS | COMPLETE | FAILED
│   ├─ changes: list of applied modifications
│   └─ offset: Δline_numbers after modifications
└─ Post-chunk: recalculate all line references

RATIONALE FOR SECONDARY LIMITS:
  Dense/minified content can hit >50k tokens at 1500 lines.
  Secondary limits prevent context window overflow regardless of line density.
```

### PRINCIPLE-05: Unified Severity Scale

```
All severity references — in ISSUE_ID, PATHOLOGY_REGISTRY, and EXECUTION_PLAN — use ONE scale:

SEV-1  [CRITICAL]: Silent data loss, security vulnerability, undefined behavior
SEV-2  [HIGH]:     Architectural debt, API breakage risk, performance cliff
SEV-3  [MEDIUM]:   Logic errors, maintainability risk, non-obvious side effects
SEV-4  [LOW]:      Style, cosmetic issues, minor technical debt

MAPPING (deprecated aliases → canonical):
  CRITICAL → SEV-1 | HIGH → SEV-2 | MEDIUM → SEV-3 | LOW → SEV-4
```

### PRINCIPLE-06: Model Routing (Runtime Config) ← NEW in v3.2

```
RATIONALE:
  The protocol does not prescribe specific model identifiers (they change).
  Model selection is runtime config in config.yaml under MODEL_ROUTING.
  The protocol only defines the routing contract.

CONTRACT:
  root_model  — used for: orchestration, gate decisions, planning (Phase 0–3, 5)
  leaf_model  — used for: llm_query calls on individual chunks (Phase 1–4)

  IF MODEL_ROUTING absent from config.yaml:
    └─ Use single model for all operations (no routing — acceptable default)

  IF MODEL_ROUTING present:
    └─ Agent MUST route calls according to config; log model_id in metrics.json

COST IMPLICATION:
  Leaf operations (chunk analysis) are the majority of token spend.
  A cheaper leaf_model reduces session cost without sacrificing planning quality.
  See config.yaml for configuration example.
```

---

## TIER 2 — EXECUTION PROTOCOL

### PHASE 0 — INITIALIZATION & INDEXING

#### Step 0.1: QUICK_ORIENT Header Setup

```
MANDATORY OUTPUT at session start:

## STATE_SNAPSHOT
current_task:         <active operation>
last_completed_batch: <chunk_id or "NONE">
next_action:          <specific operation>
blocked_by:           <dependencies or "NONE">
active_issues:        <ISSUE_ID list or "NONE">
context_mode:         <REPL | DIRECT>
chunk_cursor:         <current position>
session_id:           <uuid — for checkpoint linkage>
budget_used:          <tokens_used> / <max_total_tokens>
recursion_depth:      0      ← NEW in v3.2

Update STATE_SNAPSHOT after EACH batch completion.
```

#### Step 0.2: Environment Offload

```
IF file_size > 5000 lines:
    EXECUTE context_offload:
    ├─ Load file to external store (REPL/variable)
    ├─ Access via programmatic methods: slice, regex, search, peek(), count
    ├─ Use llm_query(chunk, task) for isolated sub-queries  ← see llm_query spec below
    └─ NEVER tokenize full content in prompt window

INITIALIZATION:
    context = load_file(target_path)
    nav_map = build_index(context)
    state   = init_state_snapshot()
```

##### llm_query Specification ← UPDATED in v3.2

```
SIGNATURE:
  llm_query(chunk: str, task: str, max_tokens: int = 2048) → QueryResult

PARAMETERS:
  chunk      — text slice from WORK_DIR/working_copy (never from SOURCE_FILE)
  task       — natural language instruction scoped to chunk content only
  max_tokens — hard cap on response size; default 2048

CONTEXT RULES:
  ├─ chunk MUST be ≤ 4000 tokens; split further if larger
  │     Also enforce PRINCIPLE-04 secondary limits before passing to llm_query
  ├─ task MUST NOT reference content outside the chunk
  ├─ results are LOCAL — do not propagate assumptions across chunks without explicit merge
  └─ model used: leaf_model if MODEL_ROUTING configured; else default model (PRINCIPLE-06)

RETRY POLICY:
  ├─ On timeout or empty response: retry once with reduced chunk size (halve)
  └─ On second failure: mark [gap: llm_query_failed — chunk_id + reason] → continue

RESULT TYPE:
  QueryResult {
    content:      str,           # model output
    confidence:   LOW|MED|HIGH,  # self-reported by prompt instruction
    chunk_ref:    str,           # chunk_id this result belongs to
    raw_tokens:   int,           # for budget tracking
    model_used:   str,           # model_id actually used ← NEW in v3.2
    latency_ms:   int            # for p50/p95 telemetry ← NEW in v3.2
  }

NOTE ON confidence FIELD:
  confidence is self-reported by the model — treat as a signal, NOT a guarantee.
  See GATE-04 for advisory early_exit usage.
```

#### Step 0.3: Build Navigation Map

```
ACTIONS:
  - Chunk file (1000–1500 lines per block; enforce PRINCIPLE-04 secondary limits)
  - Assign IDs: [C1], [C2], ...
  - Extract:
    - Headings tree (H1-H6)
    - Code blocks
    - Tables
    - Checklists
  - Build NAV_MAP:
      section → chunk_id → line_range

OUTPUT:
  - TOC (normalized)
  - Chunk index
  - Cross-ref graph
```

> **GATE-00**: `NAV_MAP exists AND all chunks indexed` → PROCEED to Phase 1

#### Step 0.4: Workspace Isolation

```
MANDATE:
├─ SOURCE_FILE = strictly READ-ONLY (no direct writes ever)
├─ WORK_DIR = create_isolated_workspace(target_file)
│   ├─ Python env:  tempfile.mkdtemp() → /tmp/titan_ws_<uuid>/
│   ├─ Docker env:  bind-mount volume → /workspace/<uuid>/
│   └─ Pure-API:    IN_MEMORY_BUFFER dict keyed by chunk_id
├─ cp SOURCE_FILE → WORK_DIR/working_copy  (or clone to buffer)
├─ All grep, sed, chunk, and patch operations TARGET ONLY WORK_DIR
├─ Validation diffs: diff WORK_DIR/working_copy vs SOURCE_FILE
└─ Post-delivery: WORK_DIR cleanup OR archive (configurable)

INVARIANT ALIGNMENT:
├─ Reinforces INVAR-02 (source immutability)
├─ Enables clean ROLLBACK_PROTOCOL (restore = discard WORK_DIR)
└─ Simplifies GATE-04 diff: always working_copy ↔ SOURCE_FILE

CODE EXECUTION GATE (INVAR-05):
  IF any operation would exec LLM-generated code:
    └─ Check config.yaml execution_mode before proceeding (see INVAR-05)

ENVIRONMENT FALLBACK:
  IF filesystem_unavailable:
    WORK_DIR = IN_MEMORY_BUFFER
    chunk isolation preserved; same access rules apply
```

#### Step 0.5: Session Checkpoint Init ← UPDATED in v3.2

```
PURPOSE: enable resumption across context resets or session interruptions

CHECKPOINT_STORE:
  ├─ Location: WORK_DIR/checkpoint.json  (or IN_MEMORY_BUFFER["checkpoint"])
  ├─ Written: after every GATE passage and every completed batch
  └─ Format:
      {
        "session_id":           "<uuid>",
        "protocol_version":     "3.2",
        "source_file":          "<path>",
        "source_checksum":      "<sha256 of SOURCE_FILE>",
        "gates_passed":         ["GATE-00", "GATE-01", ...],
        "completed_batches":    ["BATCH_001", ...],
        "open_issues":          ["ISSUE_ID", ...],
        "chunk_cursor":         "<chunk_id>",
        "timestamp":            "<ISO-8601>",
        "recursion_depth":      0,          ← NEW in v3.2
        "max_recursion_depth":  1,          ← NEW in v3.2
        "cursor_state": {
          "current_file":    "<path>",
          "current_line":    0,
          "current_chunk":   "<id>",
          "offset_delta":    0
        }
      }

RECURSION CONTROL (NEW in v3.2):
  ├─ recursion_depth: incremented each time a sub-task spawns a nested llm_query chain
  ├─ max_recursion_depth: 1 (default; configurable in config.yaml, max recommended: 2)
  ├─ IF recursion_depth >= max_recursion_depth:
  │     └─ BLOCK spawn → log [gap: recursion_limit_reached — flatten or defer]
  └─ RATIONALE: prevents exponential token growth from self-referential sub-task chains

RESUMPTION:
  IF checkpoint.json exists at session start:
    ├─ Verify source_checksum matches current SOURCE_FILE
    │   └─ MISMATCH → ABORT + warn: "source file modified since last session"
    ├─ Restore state from checkpoint
    ├─ Skip already-completed batches
    └─ Continue from chunk_cursor

INVARIANT: checkpoint is write-only-append for gates_passed and completed_batches
```

---

### PHASE 1 — SEARCH & DISCOVERY

#### Pattern Detection Templates

```
TARGET_PATTERNS:
├─ Duplicates:       `(chk-[\w-]+)` → detect repeats
├─ Terminology:      `GHOST.*`, `AN|Author.?Notes`, `{{char}}\|{{user}}`
├─ Contradictions:   same keyword + conflicting verbs
├─ Token budgets:    `\b\d{3,5}\s*(tokens\|tok)\b`
├─ TODO/FIXME:       `TODO\|FIXME\|XXX\|HACK`
├─ Orphan refs:      broken links, undefined symbols
└─ KEEP markers:     `<!-- KEEP -->` presence verification
```

#### Tool Matrix

```
| Need                        | Tool                                                           |
|-----------------------------|----------------------------------------------------------------|
| Find all occurrences        | grep -rn "pattern" dir/                                        |
| Extract section             | sed -n '/START/,/END/p'                                        |
| Compare sections            | diff <(sed -n '10,50p' A) <(sed -n '10,50p' B)                |
| Validate JSON               | python -m json.tool file.json                                  |
| Validate YAML               | yamllint file.yaml                                             |
| Validate TOML               | python -c "import tomllib; tomllib.load(open(f,'rb'))"         |
| Find callers (ripgrep)      | rg -n "self\.<method>\("                                       |
| AST parse Python            | python -c "import ast; ast.dump(ast.parse(open(f).read()))"    |
| AST parse JS/TS             | node -e "require('@babel/parser').parse(src, opts)"            |
| Structural diff (AST)       | difftastic file_a file_b                                       |
| Binary file detection       | file <path>  → if not text: skip + log [gap: binary_file]      |
| Encoding check              | python -c "open(f,'r',encoding='utf-8').read()" 2>&1           |
| Count tokens (approx)       | wc -w <file> (×1.3 ≈ tokens)                                   |
| Count chars                 | wc -c <file>   ← use for PRINCIPLE-04 secondary limit check    |
| SHA-256 checksum            | sha256sum <file>                                               |
```

> **GATE-01**: `all target patterns scanned` → PROCEED to Phase 2

---

### PHASE 2 — ANALYSIS & CLASSIFICATION

#### Issue Classification Format

```
ISSUE_ID: [SEV-1|SEV-2|SEV-3|SEV-4]
LOCATION: file:line_start-line_end | chunk_id
CATEGORY: [Structural|Logical|Performance|Security|Style]
EVIDENCE: <exact code snippet>
CONFLICT_WITH: <other section/file if applicable>
ROOT_CAUSE: <why this exists>
IMPACT: <what breaks if unfixed>
FIX_STRATEGY: [Refactor|Rewrite|Delete|Document|Defer|KEEP]
ESTIMATED_TOKENS: <cost to fix>
KEEP_VETO: [TRUE|FALSE] → if TRUE, cannot modify
```

#### Severity Definitions

```
SEV-1 [CRITICAL]: Silent data loss, security vulnerability, undefined behavior
SEV-2 [HIGH]:     Architectural debt, API breakage risk, performance cliff
SEV-3 [MEDIUM]:   Logic errors, maintainability risk, non-obvious side effects
SEV-4 [LOW]:      Style, cosmetic issues, minor technical debt
```

> **GATE-02**: `all issues classified with ISSUE_ID` → PROCEED to Phase 3

---

### PHASE 3 — PLANNING

#### Execution Plan Structure

```
EXECUTION_PLAN:
  VERSION: <timestamp>
  TOTAL_ISSUES: <count>
  BATCHES:

  BATCH_001:
    issues: [ISSUE_ID_1, ISSUE_ID_2]
    dependencies: NONE
    batch_type: parallel_safe | atomic | sequential
    parallel_safe_justification: <required if batch_type = parallel_safe>
    estimated_tokens: <count>
    rollback_point: <backup_location>

  BATCH_002:
    issues: [ISSUE_ID_3]
    dependencies: [BATCH_001]
    batch_type: atomic
    estimated_tokens: <count>
    rollback_point: <backup_location>

DEPENDENCY_GRAPH: DAG of fix ordering
ROLLBACK_POINTS:
  - <git_commit_hash or file_backup_path>
VALIDATION_GATES:
  - GATE-03: pre-execution checks
  - GATE-04: post-execution verification
```

##### Parallel-Safe Definition

```
A batch is parallel_safe IF AND ONLY IF all of the following hold:

  [P1] No two issues in the batch modify overlapping line ranges
  [P2] No issue in the batch depends on the output of another in the same batch
  [P3] No issue touches a section referenced by a KEEP marker
  [P4] No issue modifies shared symbols (variables, headings, anchors) used by sibling issues

VERIFICATION:
  Before marking batch_type = parallel_safe, agent MUST explicitly check P1–P4
  and record justification in parallel_safe_justification field.

  IF any condition is uncertain → downgrade to batch_type: sequential
```

#### Pathology & Risk Registry

```
PATHOLOGY_REGISTRY:
  BUG-001:
    severity: SEV-1|SEV-2|SEV-3|SEV-4   # unified scale — PRINCIPLE-05
    location: file:lines
    defect: <description>
    mitigation_phase: <PHASE reference>
    status: OPEN | [CLOSED]

  ARCH-001:
    severity: SEV-2
    location: <reference>
    defect: <description>
    mitigation_phase: <PHASE reference>
    status: OPEN | [CLOSED]

RULES:
  - Entries NEVER deleted
  - Status transitions: OPEN → [CLOSED] only
  - Aggregates all ISSUE_IDs across phases
  - Severity uses PRINCIPLE-05 unified scale exclusively
```

#### Batch Constraints

```
CONSTRAINTS:
├─ Max 500 lines changed per atomic batch
├─ Max 3 files modified per batch without explicit approval
├─ Every batch has verifiable before/after state
├─ KEEP_VETO = TRUE → exclude from batch
└─ Pre-execution backup MANDATORY
```

#### Operation Budget

```
SESSION_BUDGET:
  max_total_tokens:   <set at session init; default: 100_000>
  max_wall_time_min:  <set at session init; default: 60>
  token_counter:      incremented after each llm_query and patch operation

BUDGET_CHECK: performed before each batch
  IF token_counter > max_total_tokens × 0.9:
    ├─ STATE: BUDGET_WARNING
    ├─ Suspend low-priority batches (SEV-3, SEV-4)
    ├─ Report remaining budget in STATE_SNAPSHOT
    └─ Await human approval to continue

  IF token_counter >= max_total_tokens OR wall_time >= max_wall_time_min:
    ├─ STATE: BUDGET_EXCEEDED
    ├─ STOP all operations
    ├─ Write checkpoint
    ├─ Report: "Budget exceeded — session paused. Resume with new session."
    └─ ROLLBACK any in-progress batch
```

> **GATE-03**: `plan validated AND no KEEP_VETO violations AND budget headroom confirmed` → PROCEED to Phase 4

---

### PHASE 4 — EXECUTION & VALIDATION

#### Execution Workflow Per Batch

```
WORKFLOW:
PRE_STATE_SNAPSHOT → APPLY_CHANGES → POST_STATE_SNAPSHOT → VALIDATE → COMMIT | ROLLBACK
```

#### Surgical Patch Engine (GUARDIAN)

```
PRE-PATCH IDEMPOTENCY CHECK (INVAR-04):
  BEFORE applying any patch:
    IF target_section already matches desired state:
      └─ SKIP patch → log [SKIPPED — already applied] → continue

VALIDATION_PROTOCOL:
  OUTPUT_FORMAT:
    ├─ ✓ Approved: change verified
    └─ ✗ Patch Required:
        ┌─────────────────────────────────────────────────────┐
        │ Location | Failed Check | Targeted Fix              │
        │----------|--------------|---------------------------│
        │ L45-52   | pattern miss | Replace: [old] -> [new]   │
        │ C3:118   | broken ref   | Update: ref target        │
        └─────────────────────────────────────────────────────┘

RULES:
├─ NEVER regenerate full document
├─ Targeted replacements only
├─ Max 2 patch iterations per defect
├─ Patch format: `Replace: [Target] -> With: [New]`
└─ Failed patches → mark `[gap: ...]` + proceed
```

#### Deterministic Validation Loop

```
VALIDATION_CHECKLIST:
  PASS CONDITIONS:
    [ ] grep confirms old pattern removed
    [ ] grep confirms new pattern present
    [ ] Cross-reference check: no broken links/imports
    [ ] Complexity score did not increase
    [ ] No new SEV-1/SEV-2 issues introduced
    [ ] KEEP markers preserved
    [ ] No forbidden patterns introduced

  LOOP:
    FOR each check:
      IF FAIL:
        ├─ Trigger patch mode
        ├─ Max 2 iterations
        ├─ After 2 failures: mark `[gap: validation_incomplete]`
        └─ Continue to next batch
      IF PASS:
        └─ Proceed to COMMIT
```

> **GATE-04** ← UPDATED in v3.2: see threshold rules below

> **GATE-04 THRESHOLD RULES:**
>
> ```
> BLOCK if ANY of:
>   ├─ open SEV-1 gaps > 0              (zero tolerance for critical gaps)
>   ├─ open SEV-2 gaps > 2              (max 2 unresolved high-severity)
>   ├─ total open gaps > 20% of total issues found
>   └─ gap in PATHOLOGY_REGISTRY marked as "blocking_delivery"
>
> WARN (proceed with human acknowledgement) if:
>   ├─ open SEV-3 gaps > 5
>   └─ open SEV-4 gaps > 10
>
> PASS (auto-proceed) if:
>   └─ all above conditions false
>
> CONFIDENCE ADVISORY (NEW in v3.2):
>   IF all completed QueryResults in session have confidence = HIGH
>   AND total open gaps = 0:
>     → log advisory: "early_exit eligible — all chunks HIGH confidence, zero gaps"
>     → agent MAY skip remaining SEV-4-only batches with human acknowledgement
>
>   ⚠ WARNING: confidence is self-reported by the model.
>     Do NOT auto-exit on confidence alone without human confirmation.
>     Treat as an informational signal, not a gate condition.
> ```

---

### PHASE 5 — DELIVERY & HYGIENE

#### Document Hygiene Protocol

```
MANDATORY_CLEANUP before final output:

STEP 1: Update STATE_SNAPSHOT
  - Set last_completed_batch = ALL
  - Set next_action = "DELIVERY"

STEP 2: Apply Status Transitions
  - All OPEN issues → verify [CLOSED] status
  - All PENDING chunks → verify COMPLETE status

STEP 3: Remove Debug Artifacts
  - Delete `~~strikethrough~~` text
  - Remove narrative comments
  - Remove iteration history from body
  - Remove intermediate debug notes

STEP 4: Grep Forbidden Patterns
  - `> ⚠` warnings (except GATE markers)
  - `> ✓` interim checks
  - `> ℹ` informational markers
  - `[verify recency]` tags
  - Temporary placeholders

STEP 5: Validate Output Integrity
  - No orphaned references
  - Consistent terminology
  - Clean navigation structure

NOTE: Document Hygiene runs EXACTLY ONCE per delivery — in Phase 5.
      FULL_MERGE does NOT re-run hygiene; it operates on the
      already-cleaned working_copy produced here.
```

#### Clean Flag Processing

```
IF clean_output = TRUE:
  REMOVE:
    ├─ YAML frontmatter (metadata stripped)
    ├─ Validation annotations (> ⚠ / > ✓ / > ℹ)
    ├─ Consensus Notes sections
    ├─ [verify recency] markers
    ├─ Internal debug comments
    └─ Iteration history

  PRESERVE:
    ├─ Document content
    ├─ Navigation structure
    ├─ Final CHANGE_LOG
    └─ Production-ready formatting

  OUTPUT: Pure Markdown, publication-ready
```

#### Auto-Generated Artifacts ← UPDATED in v3.2

```
OUTPUT_ARTIFACTS:

  INDEX.md:
    structure: hierarchical TOC with line ranges
    format: |
      [SECTION_ID] | [START_LINE] | [END_LINE] | [PURPOSE_SUMMARY] | [DEPENDENCIES]

  SYMBOL_MAP.json:
    content: all functions/classes/variables with locations
    format: {symbol: {file, line, type, dependencies}}

  CHANGE_LOG.md:
    format: |
      ## [TIMESTAMP]
      ### Modified
      - [chunk_id] L{start}-{end}: `old` → `new` | Reason: <rationale>
      ### Added
      - [chunk_id] L{line}: new content | Reason: <rationale>
      ### Deleted
      - [chunk_id] L{start}-{end}: removed content | Reason: <rationale>
      ### Skipped (idempotent)
      - [chunk_id] patch already applied — no-op

  DECISION_RECORD.md:
    format: |
      DECISION_ID: <id>
      CONTEXT: <situation>
      OPTIONS: <alternatives considered>
      CHOSEN: <selected option>
      RATIONALE: <why this option>
      IMPACT: <consequences>

  metrics.json (NEW in v3.2):
    content: session telemetry for monitoring integration
    format: |
      {
        "session": {
          "id":               "<uuid>",
          "duration_seconds": <int>,
          "status":           "COMPLETE | PARTIAL | ABORTED"
        },
        "processing": {
          "chunks_total":     <int>,
          "issues_found":     <int>,
          "issues_fixed":     <int>,
          "gaps":             <int>
        },
        "gates": {
          "GATE-00": "PASS | FAIL",
          ...
          "GATE-05": "PASS | FAIL"
        },
        "tokens": {
          "total":            <int>,
          "root_model":       <int>,   ← present only if MODEL_ROUTING configured
          "leaf_model":       <int>,   ← present only if MODEL_ROUTING configured
          "per_query_p50":    <int>,   ← median tokens per llm_query call
          "per_query_p95":    <int>    ← 95th percentile tokens per llm_query call
        },
        "cost_estimate": {
          "note": "populate from provider pricing; protocol does not hardcode rates",
          "root_model_calls": <int>,
          "leaf_model_calls": <int>
        }
      }

    COLLECTION METHOD:
      After each llm_query call, append raw_tokens to a running list.
      At Phase 5: compute p50 = median(list), p95 = percentile(list, 95).
      python: import statistics; p50 = statistics.median(tokens_list)
```

> **GATE-05**: `all artifacts generated AND hygiene complete` → DELIVERY

---

### OPTIONAL DELIVERY MODE: FULL_MERGE

```
TRIGGER CONDITIONS (ALL must be true):
  ├─ GATE-05: PASS
  ├─ clean_output = TRUE
  ├─ file_size < 8000 lines  (or explicit user override: full_merge_override = TRUE)
  └─ No [gap: ...] markers in critical sections

EXECUTION (deterministic merge — NOT LLM regeneration):
  STEP 1: Verify GATE-05 PASS — abort if any gate open
  STEP 2: Load WORK_DIR/working_copy
          (Document Hygiene already applied in Phase 5 — DO NOT re-run)
  STEP 3: Run final checksum verification

           expected_hash = sha256(apply_patches_idempotent(SOURCE_FILE, CHANGE_LOG))
           actual_hash   = sha256(WORK_DIR/working_copy)

           apply_patches_idempotent:
             FOR each patch in CHANGE_LOG (in order):
               IF patch.status = SKIPPED → no-op
               ELSE apply patch; IF result already matches desired state → no-op
             RETURN resulting content

           IF expected_hash ≠ actual_hash → ABORT + report divergence
  STEP 4: Output merged file + CHANGE_LOG.md as delivery artifacts

OUTPUT ARTIFACTS:
  ├─ <filename>_merged.md   — full merged file, publication-ready
  └─ CHANGE_LOG.md          — complete audit trail of all patches

WARNINGS:
  ⚠ Full output bypasses Zero-Drift guarantees for UNCHANGED sections
  ⚠ Use ONLY for human review, NOT as automated pipeline input
  ⚠ Files > 8000 lines require explicit full_merge_override = TRUE
  ⚠ Any open [gap: ...] in PATHOLOGY_REGISTRY → full_merge BLOCKED

INVARIANT ALIGNMENT:
  ├─ Patch engine remains the source of truth (merge is apply-only)
  ├─ CHANGE_LOG preserves full audit trail
  ├─ ROLLBACK_PROTOCOL unaffected (WORK_DIR still available)
  └─ INVAR-03 (Zero-Drift) applies only to patch-targeted sections
```

---

## TIER 3 — OUTPUT FORMAT

### Mandatory Structure

```
## STATE_SNAPSHOT
current_task:         <description>
last_completed_batch: <id or ALL>
next_action:          <next operation or COMPLETE>
blocked_by:           <dependencies or NONE>
active_issues:        <list or NONE>
session_id:           <uuid>
budget_used:          <tokens_used> / <max_total_tokens>
recursion_depth:      <int>   ← NEW in v3.2

## EXECUTION_PLAN
[Step 1] <action> → <expected outcome>
[Step 2] <action> → <expected outcome>
...
Dependencies & Risks: <analysis>

## CHANGE_LOG (DIFF)
[chunk_id] L{line}: `old` → `new` | Reason: <rationale>
...

## VALIDATION_REPORT
- Syntax:              ✅ PASS | ❌ FAIL: <details>
- Logic/Constraints:   ✅ PASS | ⚠️ WARNING: <details> | ❌ FAIL: <details>
- Navigation Integrity:✅ PASS | ⚠️ WARNING: <details>
- Zero-Drift Check:    ✅ PASS | ❌ FAIL: <details>
- KEEP Preservation:   ✅ PASS | ❌ FAIL: <details>
- Token/Context Budget:✅ PASS | ⚠️ WARNING: <details>
- Recursion Depth:     <current> / <max>   ← NEW in v3.2
- GATE-04 Gap Status:  SEV-1 open: N | SEV-2 open: N | Total gaps: N/total | PASS/BLOCK/WARN

## NAVIGATION_INDEX
[Generated TOC + anchors]

## PATHOLOGY_REGISTRY
| ID | Severity | Location | Defect | Status |
|----|----------|----------|--------|--------|
| BUG-001 | SEV-1 | ... | ... | [CLOSED] |

## KNOWN_GAPS
- [gap: <description of unresolved issues>]
- [gap: <areas requiring human verification>]

## FINAL_STATUS
- Issues found:              X
- Issues fixed:              Y
- Issues deferred:           Z
- Issues skipped (idempotent):W
- New issues introduced:     V
- CONFIDENCE_SCORE:          [0-100]
- recursion_depth_peak:      <int>   ← NEW in v3.2
- NEXT_ACTIONS: <if human needed, else "COMPLETE">
```

---

## TIER 4 — ROLLBACK PROTOCOL

### Backup & Recovery

```
BACKUP_PROCEDURE:
  trigger: BEFORE any write operation
  location: /tmp/backup_<filename>_<timestamp>
  format: full file copy

ROLLBACK_TRIGGERS:
  - Validation FAIL after 2 patch iterations
  - Context overflow detected
  - KEEP_VETO violation detected
  - Cascade error in dependent chunks
  - Unrecoverable state corruption
  - BUDGET_EXCEEDED during in-progress batch
  - INVAR-05 violation (unsafe code exec attempted)   ← NEW in v3.2

ROLLBACK_EXECUTION:
  command: REVERT: chunk_id → previous_state
  output:  "Step X failed – rolled back to <backup_id>"
  recovery: restore file + report + await instruction
```

---

## TIER 5 — FAILSAFE PROTOCOL

### Edge Case Handling

```
SCENARIOS:

  file_too_large:
    action:
      - Increase chunking granularity (reduce to 500-800 lines)
      - Enforce PRINCIPLE-04 secondary limits (max_chars / max_tokens per chunk)
      - Prioritize SEV-1 issues only
      - Defer low-impact fixes (SEV-3, SEV-4)
      - Activate Environment Offload

  ambiguity_detected:
    action:
      - Mark as LOW_CONFIDENCE
      - DO NOT auto-fix
      - Log to PATHOLOGY_REGISTRY
      - Request human clarification

  tool_unavailable:
    action:
      - Output: `ERROR: tool_unavailable → fallback: manual_grep_pattern`
      - Provide specific grep command for manual execution
      - Continue with available tools

  context_overflow:
    action:
      - Trigger ROLLBACK immediately
      - Resume with reduced chunk size (also recheck secondary limits)
      - Force Environment Offload activation

  keep_veto_violation_attempted:
    action:
      - ABORT batch
      - Log violation
      - Report to PATHOLOGY_REGISTRY
      - Await human instruction

  binary_file_encountered:
    action:
      - Log: [gap: binary_file — <path> — skipped, not text-processable]
      - Skip file entirely
      - Continue with remaining targets

  encoding_error:
    action:
      - Attempt re-read with detected encoding (chardet / file command)
      - IF still fails: log [gap: encoding_unresolvable — <path>]
      - Skip file + continue

  llm_query_failure:
    action:
      - Retry once with halved chunk size
      - IF second failure: mark [gap: llm_query_failed — chunk_id + reason]
      - Continue without result; flag for human review

  session_interrupted:
    action:
      - On resume: load checkpoint.json (Step 0.5)
      - Verify source_checksum
      - Restore state and continue from chunk_cursor

  recursion_limit_reached (NEW in v3.2):
    action:
      - BLOCK sub-task spawn
      - Log: [gap: recursion_limit_reached — flatten task or defer to next session]
      - Continue with remaining top-level batches
      - Report in FINAL_STATUS recursion_depth_peak

  unsafe_code_exec_attempted (NEW in v3.2):
    action:
      - ABORT operation immediately (INVAR-05)
      - Log: [gap: unsafe_execution_blocked — no sandbox or human gate confirmed]
      - Trigger ROLLBACK for current batch
      - Await human instruction to configure execution_mode in config.yaml
```

---

## TIER 6 — VERIFICATION GATES SUMMARY

```
GATE-00: NAV_MAP exists AND all chunks indexed
GATE-01: All target patterns scanned
GATE-02: All issues classified with ISSUE_ID
GATE-03: Plan validated AND no KEEP_VETO violations AND budget headroom confirmed
GATE-04: All validations PASS OR gaps marked, AND gap counts within threshold
          + confidence advisory checked (informational only — see GATE-04 rules)
GATE-05: All artifacts generated (incl. metrics.json) AND hygiene complete

RULE: Gate FAIL → BLOCK → Cannot proceed to next phase
```

---

## EXECUTION DIRECTIVE

```
INITIALIZATION:
1.  Load target file
2.  IF size > 5000 lines → activate Environment Offload (Step 0.2)
3.  Generate QUICK_ORIENT header (Step 0.1) — include recursion_depth: 0
4.  Execute Step 0.4 → create WORK_DIR / IN_MEMORY_BUFFER
        └─ Verify execution_mode in config.yaml (INVAR-05)
5.  Execute Step 0.5 → init or restore session checkpoint
6.  Execute Phase 0 → build NAV_MAP (all ops target WORK_DIR only)
        └─ Apply PRINCIPLE-04 secondary limits during chunking

PROCESSING:
7.  Execute Phase 1 → Search & Discovery
8.  Execute Phase 2 → Analysis & Classification
9.  Execute Phase 3 → Planning (includes budget init)
10. Execute Phase 4 → Execution & Validation
11. Each phase ends with GATE verification
12. GATE FAIL → resolve before next phase
13. Track all issues in PATHOLOGY_REGISTRY
14. Track recursion_depth in STATE_SNAPSHOT; enforce max_recursion_depth

VALIDATION:
15. Every modification via Surgical Patch Engine (GUARDIAN)
16. Check idempotency before each patch (INVAR-04)
17. Deterministic Validation Loop per batch
18. Max 2 patch iterations per defect
19. Unresolved → mark `[gap: ...]`
20. Check GATE-04 thresholds before proceeding
21. Log QueryResult.raw_tokens + latency_ms for metrics.json p50/p95

DELIVERY:
22. Apply Document Hygiene Protocol (Phase 5) — ONCE ONLY
23. Generate all artifacts including metrics.json
24. IF clean_output → strip meta-artifacts
25. IF full_merge conditions met → execute OPTIONAL DELIVERY MODE: FULL_MERGE
26. Output final structure
27. Write final checkpoint (status: COMPLETE)

RECOVERY:
28. Any unrecoverable error → ROLLBACK
29. Write checkpoint with current state
30. Report state + await instruction
```

---

## config.yaml REFERENCE ADDITIONS (v3.2)

```yaml
# --- Chunking ---
chunking:
  default_size:          1500       # lines
  large_file_size:       800        # lines (files > 30k lines)
  max_chars_per_chunk:   150000     # hard secondary limit
  max_tokens_per_chunk:  30000      # hard secondary limit (approx)

# --- Recursion ---
recursion:
  max_recursion_depth:   1          # 0 = no sub-tasks; 1 = one level (recommended)

# --- Code Execution Gate (INVAR-05) ---
security:
  execution_mode:        human_gate # options: sandbox | human_gate | disabled
  sandbox_type:          none       # options: docker | venv | restricted_subprocess | none

# --- Model Routing (PRINCIPLE-06) ---
# Remove section entirely to use single model for all operations.
model_routing:
  root_model:            ""         # frontier model for orchestration/gates; fill in at runtime
  leaf_model:            ""         # cheaper model for llm_query chunk calls; fill in at runtime

# --- Session ---
session:
  max_tokens:            100000
  max_time_minutes:      60
```

---

## INTEGRATION NOTES

This protocol synthesizes and extends all prior versions:

- Large-File Agent Protocol (chunking, phases, validation)
- QUICK_ORIENT Header (state synchronization + recursion_depth field)
- Environment Offload (context management)
- Workspace Isolation (source immutability, Step 0.4 + INVAR-05 hook)
- Session Checkpoint (cross-session persistence, recursion_depth field)
- Surgical Patch Engine GUARDIAN (minimal-change validation + idempotency)
- Deterministic Validation Loop (self-verification)
- Verification Gate Protocol (atomic blockers + confidence advisory)
- Pathology & Risk Registry (unified severity scale, defect memory)
- Hard Invariants + Anti-Fabrication (hallucination prevention)
- S-5 Veto (immutable content protection)
- Patch Idempotency Guarantee (INVAR-04)
- LLM Code Execution Gate (INVAR-05) ← NEW v3.2
- Chunking Secondary Limits (PRINCIPLE-04) ← NEW v3.2
- Recursion Depth Control (Step 0.5 + STATE_SNAPSHOT) ← NEW v3.2
- Confidence Advisory in GATE-04 (informational early_exit signal) ← NEW v3.2
- Model Routing Contract (PRINCIPLE-06, runtime config) ← NEW v3.2
- metrics.json with p50/p95 token distribution (Phase 5) ← NEW v3.2
- Document Hygiene Protocol (output cleanliness, single-pass)
- Clean Flag (publication-ready output)
- Optional Full Merge Mode (controlled full-file delivery post GATE-05)
- Operation Budget (token + time limits with graceful suspension)
- Expanded Tool Matrix (AST, binary detection, encoding, TOML, char count)
- llm_query Specification (typed, retry-aware, context-scoped, model_used + latency_ms)
- Parallel-Safe Batch Validation (P1–P4 pre-checks)
- Unified Severity Scale (SEV-1..4 across all registries)

**Architecture**: deterministic, verifiable, rollback-safe, session-resumable,
cost-aware, recursion-bounded, execution-gated, production-grade.

---

**PROTOCOL STATUS**: Production-Ready
**VERSION**: 3.2.0
**COMPATIBILITY**: All LLM agents with tool-access capabilities
**SUPERSEDES**: v3.1 (PROTOCOL.base.md), v3.0 (ULTIMATE_LARGE_FILE_AGENT_PROTOCOL.md)

---
<!-- END OF ASSEMBLED PROTOCOL -->
<!-- Assembly timestamp: 2026-04-06T21:11:25Z -->
