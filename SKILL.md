---
title: TITAN FUSE Agent Skill Configuration
skill_version: 2.1.0
protocol_version: 5.3.0
extends: Large-File Agent Protocol v5.3.0
domain: large_file_processing; repo_bootstrap; agent_orchestration
constraints:
  max_files_per_session: 3
  max_tokens_per_session: 100000
  require_approval_for_exceed_limits: true
output_format: structured_markdown
approval_handler: interactive  # interactive | callback | auto-reject
callback_url: null
---

# SKILL.md — TITAN FUSE Agent Configuration

## Purpose

This file configures agent behavior for the TITAN FUSE Protocol. The agent reads this file during the TIER -1 bootstrap phase to initialize its operating parameters.

## Agent Directives

### Domain Profile

```
domain_profile: technical
domain_volatility: V2
consensus_score: 96
input_languages: en, ru
```

### Processing Constraints

| Constraint | Value | Override Mechanism |
|------------|-------|-------------------|
| Max files per session | 3 | Interactive approval required |
| Max tokens per session | 100,000 | Configurable in config.yaml |
| Max chunk size | 1,500 lines | Auto-reduced for >30k files |
| Max batches without checkpoint | 5 | Hard limit |
| Max patch iterations | 2 | Per defect |

### Tool Permissions

```
PERMITTED TOOLS:
├─ grep, sed, awk (text processing)
├─ python (scripting)
├─ sha256sum (checksums)
├─ git (read-only operations)
└─ llm_query (isolated sub-queries)

RESTRICTED TOOLS:
├─ rm -rf (no recursive delete)
├─ curl/wget (external network - requires approval)
└─ gh (GitHub CLI - requires auth check)
```

### Output Format Configuration

```yaml
output_structure:
  state_snapshot: required
  execution_plan: required
  change_log: required
  validation_report: required
  navigation_index: required
  pathology_registry: required
  known_gaps: required
  final_status: required

clean_output:
  strip_frontmatter: true
  strip_debug_annotations: true
  strip_iteration_history: true
  preserve_keep_markers: true

full_merge:
  enabled: true
  max_lines: 8000
  require_override: false
```

## Approval Handler Configuration

### Interactive Mode (Default)

When limits are exceeded, the agent will pause and request approval:

```
APPROVAL REQUEST FORMAT:
┌─────────────────────────────────────────────────────────────┐
│ APPROVAL REQUIRED                                           │
│ ─────────────────────────────────────────────────────────── │
│ Reason: [description of limit exceeded]                      │
│ Current: [current value]                                     │
│ Requested: [requested value]                                 │
│ Impact: [what will happen if approved]                       │
│ ─────────────────────────────────────────────────────────── │
│ Options: [Y]es / [N]o / [A]lways for session / [C]ancel     │
└─────────────────────────────────────────────────────────────┘
```

### Callback Mode

For automated pipelines, configure a callback URL:

```yaml
approval_handler: callback
callback_url: https://your-service.com/approval-endpoint
callback_timeout: 300  # seconds
callback_retries: 3
```

Callback payload:
```json
{
  "session_id": "<uuid>",
  "request_type": "limit_exceeded",
  "constraint": "max_files_per_session",
  "current_value": 3,
  "requested_value": 5,
  "timestamp": "<ISO-8601>"
}
```

Expected response:
```json
{
  "approved": true,
  "session_id": "<uuid>",
  "new_limit": 5
}
```

## Multi-File Processing Configuration

```yaml
multi_file:
  enabled: true
  default_limit: 3
  hard_limit: 10
  require_explicit_approval: true

  dependency_resolution:
    enabled: true
    max_depth: 5
    circular_detection: true

  cross_file_patches:
    enabled: false  # BLOCKED in v1.0
    planned_version: "2.0"
```

## Checkpoint Configuration

```yaml
checkpoint:
  enabled: true
  format_version: "2.0"
  chunk_level_checksums: true
  partial_resumption: true
  max_checkpoint_age_days: 30

  validation:
    verify_source_checksum: true
    verify_protocol_version: true
    allow_stale_checkpoint: warn  # warn | reject | accept
```

## Validator Integration

Custom validators in `skills/validators/` are automatically loaded:

```
validators/
├── no-todos.js      # Reject TODO/FIXME markers
├── api-version.js   # Enforce version format
└── security.js      # Detect secrets/credentials
```

To disable a validator temporarily:
```yaml
disabled_validators:
  - no-todos  # Disable during development
```

## Fallback Configuration

```yaml
llm_query_fallback:
  enabled: true
  max_attempts: 4
  size_reduction_factor: 0.5
  min_chunk_size: 500
  timeout_seconds: 30

  model_fallback:
    enabled: true
    models:
      - primary
      - alternative-1
      - alternative-2
```

## Metrics Export

```yaml
metrics:
  enabled: true
  output_path: outputs/metrics.json
  format: json

  prometheus:
    enabled: false
    port: 9090

  webhook:
    enabled: false
    url: null
```

## Troubleshooting

If the agent ignores SKILL.md:
1. Verify file name is exactly `SKILL.md` (case-sensitive)
2. Check YAML frontmatter syntax
3. Ensure file is in repository root
4. Check protocol version compatibility

## New Modules (v3.2.1)

### FILE_INVENTORY
```yaml
file_inventory:
  enabled: true
  output_path: WORK_DIR/file_inventory.json
  include_in_artifacts: true
```

### CURSOR_TRACKING
```yaml
cursor_tracking:
  enabled: true
  validate_post_patch: true
  atomic_update: true
```

### ISSUE_DEPENDENCY_GRAPH
```yaml
issue_dependency_graph:
  enabled: true
  method: ast  # ast | regex
  max_depth: 10
  visualization: ascii  # ascii | graphviz
```

### CROSSREF_VALIDATOR
```yaml
crossref_validator:
  enabled: true
  run_post_gate00: true
  run_post_chunk: true
  run_gate04: true
  cache_ref_index: true
```

### DIAGNOSTICS_MODULE
```yaml
diagnostics_module:
  enabled: true
  human_review_fallback: true
  matrix_version: "3.2.1"
```

## Version Compatibility

| SKILL Version | Protocol Version | Compatible |
|---------------|------------------|------------|
| 2.1.0 | 5.3.0 | ✅ Full |
| 2.1.0 | 5.1.0 | ✅ Full |
| 2.1.0 | 4.1.0 | ✅ Full |
| 2.1.0 | 3.2.2 | ✅ Full |
| 2.0.0 | 3.2.0 | ✅ Full |
| 1.5.0 | 3.1.0 | ✅ Full |
| 1.0.0 | 3.0.0 | ⚠️ Partial |

---

*This configuration file extends and overrides protocol defaults where explicitly stated. It cannot override TIER 0 invariants (INVAR-01 through INVAR-04).*

