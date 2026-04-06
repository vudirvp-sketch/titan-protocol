# TITAN FUSE Protocol — Единый План Актуализации v3.2.1

**Дата:** 2026-04-07
**Статус:** INTEGRATION_READY
**На основе:** TITAN_PROTOCOL_AUDIT_RESULTS, ENHANCEMENT_PROPOSAL, VERIFICATION_ANALYSIS

---

## 1. EXECUTIVE SUMMARY

### 1.1 Текущее состояние

| Метрика | Значение |
|---------|----------|
| **Версия** | 3.2.0 (README) / 3.1 (PROTOCOL.base frontmatter) — **INCONSISTENCY** |
| **TIER структура** | -1..6 — полностью реализована |
| **Verification Gates** | GATE-00..05 + GATE-REPO-00..02 — полностью реализованы |
| **Инварианты** | INVAR-01..04 — полностью реализованы |
| **Test Coverage** | ❌ Отсутствует |
| **CI/CD** | ❌ Отсутствует |

### 1.2 Результаты аудита

| Категория | Процент | Действие |
|-----------|---------|----------|
| Полные дубликаты (уже есть) | 48% | ✅ Подтверждено |
| TITAN лучше | 15% | ✅ Сохранить |
| Новые приемлемые идеи | 24% | 🔄 Интегрировать |
| Неприемлемый контент | 13% | ❌ Отклонено |

### 1.3 Критические проблемы

```
🚨 BLOCKERS:
├─ VERSION INCONSISTENCY: README=3.2.0, PROTOCOL.base=3.1
├─ NO TEST COVERAGE: Surgical Patch Engine, Validation Loop untested
├─ MISSING BUILD SCRIPT: assemble_protocol.sh not verified
└─ SECURITY: Workspace uses /tmp/ without sanitization

⚠️ WARNINGS:
├─ ZERO-DRIFT GUARANTEE: Explicitly bypassed in FULL_MERGE mode
├─ ANTI-FABRICATION: Cannot guarantee all hallucinations prevented
└─ MULTI-FILE COORDINATION: Only stub in Phase -1D
```

---

## 2. УТВЕРЖДЁННЫЕ ИЗМЕНЕНИЯ

### 2.1 P0 — КРИТИЧЕСКИЕ (немедленное внедрение)

#### 2.1.1 VERSION_UNIFICATION
**Проблема:** Несогласованность версий между файлами.
**Решение:** Установить единую версию 3.2.1 для всех файлов.

```
FILES TO UPDATE:
├─ PROTOCOL.base.md frontmatter: v3.1 → v3.2.1
├─ VERSION file: 3.2.0 → 3.2.1
├─ SKILL.md protocol_version: 3.2.0 → v3.2.1
└─ CHANGELOG.md: Add v3.2.1 entry
```

#### 2.1.2 FILE_INVENTORY (Step 0.2.5)
**Проблема:** TITAN начинает обработку без инвентаризации файлов.
**Решение:** Добавить FILE_INVENTORY между Step 0.2 и Step 0.3.

```yaml
STEP 0.2.5: FILE_INVENTORY

BEFORE chunking:
  1. Detect file type: text | binary | repomix | unknown
  2. Detect encoding: UTF-8 first, fallback to chardet
  3. Calculate checksum: SHA-256[:16]
  4. Record metadata: size_bytes, size_lines, mtime

OUTPUT:
  file_inventory.json → WORK_DIR/

RULES:
  ├─ Binary files → skip + log [gap: binary_file — {path}]
  ├─ Encoding failure → log [gap: encoding_unresolvable — {path}]
  └─ Include in final artifacts
```

**Риски и митигация:**
- chardet неточен для mixed encodings → использовать UTF-8 first, log confidence
- Checksum для больших файлов → streaming SHA-256, не загружать в память

#### 2.1.3 CURSOR_TRACKING
**Проблема:** Нет явного отслеживания позиции при multi-chunk обработке.
**Решение:** Добавить cursor state в STATE_SNAPSHOT.

```yaml
CURSOR_STATE:
  current_file: <file_path>
  current_line: <int>
  current_chunk: <chunk_id>
  current_section: <section_name>
  offset_delta: <int>  # lines added/removed

UPDATE_RULES:
  ├─ Update after each patch (atomic: state + checkpoint)
  ├─ Validate: cursor.line MUST match actual file line post-patch
  └─ On mismatch → ROLLBACK + log inconsistency
```

**Риски и митигация:**
- offset_delta может рассинхронизироваться при parallel patches → запретить parallel для overlapping ranges
- Требует atomic update → cursor как immutable snapshot per chunk

### 2.2 P1 — ВЫСОКИЙ ПРИОРИТЕТ (Phase 2)

#### 2.2.1 ISSUE_DEPENDENCY_GRAPH
**Проблема:** DEPENDENCY_GRAPH есть для batches, но не для issues.
**Решение:** Добавить ISSUE_DEPENDENCY_GRAPH в PHASE 3.

```yaml
ISSUE_DEPENDENCY_GRAPH:
  format: DAG (Directed Acyclic Graph)

  construction:
    method: AST-based static analysis
    fallback: FILE_ORDER priority if AST unavailable

  CYCLE_DETECTION:
    IF cycle detected:
      ├─ Log: [gap: circular_dependency — {issue_A} ↔ {issue_B}]
      ├─ Break by: SEV priority → FILE_ORDER
      └─ Flag for human review

  output:
    ├─ Topological order for processing
    ├─ Visualization (ASCII/GraphViz)
    └─ Include in EXECUTION_PLAN
```

**Риски и митигация:**
- AST resource-intensive → опционально, fallback на regex-based
- Cycle detection NP-hard → limit depth to 10, flag complex cases

#### 2.2.2 CROSSREF_VALIDATOR
**Проблема:** Cross-reference check есть в VALIDATION_CHECKLIST, но не как модуль.
**Решение:** Вынести в отдельный модуль с REF_INDEX.

```yaml
CROSSREF_VALIDATOR:

SCOPE:
  ├─ Section references: "→ Section X"
  ├─ Anchor links: "#anchor-id", "[text](#anchor)"
  ├─ Code references: function_name (via SYMBOL_MAP)
  ├─ Import references: "from module import X"
  └─ External references: URLs, file paths

VALIDATION_SEQUENCE:
  STEP 1: Extract references (regex + AST for code)
  STEP 2: Build REF_INDEX with source → target mapping
  STEP 3: Validate each reference
  STEP 4: Generate CROSSREF_REPORT

INTEGRATION:
  ├─ Run after GATE-00 (NAV_MAP construction)
  ├─ Run after each chunk completion
  └─ Run in GATE-04 validation
```

**Риски и митигация:**
- Regex может пропустить dynamic links → добавить AST для code refs
- Performance → кэшировать REF_INDEX per chunk

#### 2.2.3 DIAGNOSTICS_MODULE
**Проблема:** Нет систематического troubleshooting модуля.
**Решение:** Добавить DIAGNOSTICS_MODULE как расширение TIER 5.

```yaml
DIAGNOSTICS_MODULE:

MATRIX_FORMAT: Symptom → Root Cause → Solution

ENTRIES:
  - symptom: "grep confirms old pattern present after patch"
    root_causes:
      - "Regex pattern too greedy"
      - "Multiple occurrences → wrong instance"
    solutions:
      - "Narrow regex with line anchors"
      - "Add context lines to patch spec"

  - symptom: "Cross-reference check fails"
    root_causes:
      - "Target section renamed"
      - "ANCHOR_ID collision"
    solutions:
      - "Run ANCHOR_INVENTORY after each chunk"
      - "Use unique ANCHOR_PREFIX per chunk"

VERSIONING:
  ├─ Matrix version in config.yaml
  ├─ Update triggers: protocol version change
  └─ Human-review fallback for complex cases
```

### 2.3 P2 — СРЕДНИЙ ПРИОРИТЕТ (Phase 3)

#### 2.3.1 NAMED_REGEX_GROUPS
**Проблема:** Базовые regex patterns менее читаемы.
**Решение:** Использовать named capture groups с backward compatibility.

```yaml
TRANSITION:
  CURRENT: `(chk-[\w-]+)`
  ENHANCED: `(?P<check_id>chk-[\w-]+)`

COMPATIBILITY:
  ├─ Support both (?P<name>...) and legacy (...)
  ├─ Add migration guide to CHANGELOG
  └─ Deprecation timeline: 2 versions

PATTERNS TO UPDATE:
  ├─ duplicates: `(?P<check_id>chk-[\w-]+)`
  ├─ section_ref: `(?P<arrow>→)\s*(?P<section>Section\s+(?P<number>\d+(?:\.\d+)?))`
  ├─ issue_id: `(?P<prefix>[A-Z]+)-(?P<id>\d+):\s*\[(?P<severity>SEV-\d)\]`
  └─ anchor_link: `\[(?P<text>[^\]]+)\]\(#(?P<anchor>[^)]+)\)`
```

#### 2.3.2 COMPLEXITY_SCORE (ОПЦИОНАЛЬНО)
**Проблема:** Нет явной метрики сложности.
**Решение:** Добавить как опциональный plugin-модуль.

```yaml
COMPLEXITY_SCORING:

STATUS: OPTIONAL PLUGIN

METRICS:
  STRUCTURAL_COMPLEXITY:
    formula: nesting_depth * branch_count / section_count
    threshold: configurable in config.yaml (default: 15)

  REFERENCE_COMPLEXITY:
    formula: total_references / section_count
    threshold: configurable (default: 10)

USAGE:
  ├─ Calculate during PHASE 2 (Analysis)
  ├─ Include in ISSUE_ID classification
  └─ Flag sections exceeding threshold

CUSTOMIZATION:
  ├─ Allow custom metrics via skills/validators/
  └─ Define business metrics before activation
```

### 2.4 P3 — НИЗКИЙ ПРИОРИТЕТ (отложено)

#### 2.4.1 STREAMING_FALLBACK
**Статус:** ❌ НЕ ВНЕДРЯТЬ в текущей версии

**Причина:** Противоречит PRINCIPLE-02 (tool-first navigation).

**Альтернатива:**
```yaml
ADAPTIVE_CHUNKING:
  ├─ Reduce chunk_size to 300-500 lines for >50k files
  ├─ Use AST-boundary aware chunking
  └─ Maintain tool-first approach
```

---

## 3. ОТКЛОНЁННЫЕ ПРЕДЛОЖЕНИЯ

```
❌ НЕ ВНЕДРЯТЬ:
├─ GHOST activation logic — character cards specific
├─ {{char}}/{{user}} conventions — character card syntax
├─ Enneagram/OCEAN psychology mappings — not file processing
├─ presence_penalty settings — frontend specific
├─ CSS variable consolidation — not protocol level
├─ DOMContentLoaded optimization — JavaScript specific
├─ v5.3.1 → v5.4.0 upgrade path — external project
├─ STREAMING_FALLBACK — contradicts architecture
└─ CONFIDENCE_SCORE [0-100] — LOW|MED|HIGH sufficient
```

---

## 4. ЯВНЫЕ ОГРАНИЧЕНИЯ ГАРАНТИЙ

### 4.1 Zero-Drift Guarantee

```
✅ APPLIES TO:
├─ Patched sections via Surgical Patch Engine
├─ Targeted modifications per task specification
└─ Elements explicitly marked for change

❌ DOES NOT APPLY TO:
├─ FULL_MERGE mode (explicitly bypassed)
├─ Unchanged sections in full output
└─ Regenerated content
```

### 4.2 Anti-Fabrication Guarantee

```
✅ APPLIES TO:
├─ Data explicitly in source files
├─ Verifiable via grep/regex/AST
└─ Information with explicit source reference

❌ DOES NOT APPLY TO:
├─ Context insufficient scenarios
├─ Ambiguous source interpretations
└─ Plausible but unverified content
```

---

## 5. ПЛАН ВНЕДРЕНИЯ

### 5.1 Timeline

```
WEEK 1 (v3.2.1):
├─ [D1] VERSION_UNIFICATION
├─ [D2] FILE_INVENTORY (Step 0.2.5)
├─ [D3] CURSOR_TRACKING
└─ [D4] Update STATE_SNAPSHOT + checkpoint.schema.json

WEEK 2 (v3.2.2):
├─ [D1] ISSUE_DEPENDENCY_GRAPH
├─ [D2] CROSSREF_VALIDATOR
├─ [D3] DIAGNOSTICS_MODULE
└─ [D4] Integration testing

WEEK 3 (v3.3.0):
├─ [D1] NAMED_REGEX_GROUPS
├─ [D2] COMPLEXITY_SCORE (optional plugin)
├─ [D3] Test infrastructure setup
└─ [D4] Documentation update
```

### 5.2 Test Infrastructure

```
REQUIRED TESTS:
├─ tests/unit/patch_engine_test.py
├─ tests/unit/cursor_tracking_test.py
├─ tests/unit/file_inventory_test.py
├─ tests/integration/gate_validation_test.py
├─ tests/integration/crossref_validator_test.py
├─ tests/property/idempotency_test.py
└─ tests/e2e/full_pipeline_test.py
```

### 5.3 Security Hardening

```yaml
WORKSPACE_CONFIG:
  default: "${TMPDIR:-/tmp}/titan_${USER}_${SESSION_ID}"
  fallback: IN_MEMORY_BUFFER if filesystem unavailable

PATTERN_VALIDATION:
  regex_redos_check: true
  max_pattern_length: 1000
  timeout_ms: 5000
```

---

## 6. СОГЛАСОВАНИЕ

| Модуль | Риск | Митигация | Вердикт |
|--------|------|-----------|---------|
| FILE_INVENTORY | Низкий | Streaming checksum | ✅ APPROVED |
| CURSOR_TRACKING | Низкий | Atomic update | ✅ APPROVED |
| ISSUE_DEPENDENCY_GRAPH | Средний | AST fallback | ✅ APPROVED |
| CROSSREF_VALIDATOR | Низкий | REF_INDEX cache | ✅ APPROVED |
| DIAGNOSTICS_MODULE | Низкий | Versioning | ✅ APPROVED |
| NAMED_REGEX_GROUPS | Низкий | Backward compat | ✅ APPROVED |
| COMPLEXITY_SCORE | Средний | Optional plugin | ✅ APPROVED (optional) |
| STREAMING_FALLBACK | Высокий | Architecture conflict | ❌ DEFERRED |

---

## 7. КОНЕЧНЫЙ РЕЗУЛЬТАТ

### 7.1 Version 3.2.1 Deliverables

- [x] Unified version across all files
- [x] FILE_INVENTORY в PROTOCOL.base.md
- [x] CURSOR_TRACKING в STATE_SNAPSHOT
- [x] Updated checkpoint.schema.json
- [x] Updated CHANGELOG.md

### 7.2 Version 3.2.2 Deliverables

- [ ] ISSUE_DEPENDENCY_GRAPH в PHASE 3
- [ ] CROSSREF_VALIDATOR модуль
- [ ] DIAGNOSTICS_MODULE в TIER 5
- [ ] Test coverage ≥ 70%

### 7.3 Version 3.3.0 Deliverables

- [ ] NAMED_REGEX_GROUPS migration
- [ ] COMPLEXITY_SCORE plugin
- [ ] Test coverage ≥ 90%
- [ ] Security hardening complete

---

**Документ подготовлен:** TITAN FUSE Protocol Integration Team
**Дата:** 2026-04-07
**Статус:** APPROVED FOR IMPLEMENTATION
