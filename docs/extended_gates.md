# Extended Gates Documentation

> **Version:** 3.2.3  
> **Purpose:** Comprehensive documentation of GATE-SECURITY and GATE-EXEC conditions, examples, and gap tags.

---

## GATE-SECURITY

**Purpose:** Security validation before execution. Ensures no secrets are exposed, workspace boundaries are enforced, and configuration is valid.

### PASS Conditions (ALL must be true)

| Condition | Description | Validation Method |
|-----------|-------------|-------------------|
| No secrets in inputs | Secret scanner returns clean | `SecretScanner.scan_directory("inputs/")` returns `secrets_found: 0` |
| Workspace enforced | All file paths within workspace root | `Path.is_relative_to(workspace_path)` for all operations |
| Config valid | Configuration passes JSON schema validation | `jsonschema.validate(config, config.schema.json)` succeeds |
| Execution mode allowed | Mode is permitted in environment | `security.execution_mode` in `["sandbox", "trusted", "human_gate"]` |
| Credentials isolated | No API keys in session state | `CredentialManager.validate_no_key_in_state(session)` returns `True` |

### FAIL Conditions (ANY triggers failure)

| Condition | GAP Tag | Example |
|-----------|---------|---------|
| Secrets detected | `[gap: secrets_detected_in_inputs]` | File contains `api_key: sk-xxxx` pattern |
| Workspace violation | `[gap: workspace_boundary_violation]` | Attempted access to `/etc/passwd` |
| Config schema mismatch | `[gap: config_schema_mismatch]` | Unknown key `chunking.invalid_option` in config.yaml |
| Sandbox unavailable | `[gap: sandbox_required_but_unavailable]` | `execution_mode: sandbox` but Docker not running |
| Credential leak | `[gap: credential_leak_detected]` | `session_state.api_key` field present |

### Input/Output Examples

#### Example 1: PASS - Clean inputs

**Input:**
```json
{
  "inputs_dir": "inputs/",
  "config": {
    "security": {
      "execution_mode": "trusted",
      "secrets_scan": true
    }
  }
}
```

**Output:**
```json
{
  "gate": "GATE-SECURITY",
  "status": "PASS",
  "checks": {
    "secrets_scan": {"status": "PASS", "files_scanned": 5, "secrets_found": 0},
    "workspace": {"status": "PASS", "root": "/workspace/project"},
    "config_validation": {"status": "PASS"},
    "execution_mode": {"status": "PASS", "mode": "trusted"}
  }
}
```

#### Example 2: FAIL - Secrets detected

**Input:**
```json
{
  "inputs_dir": "inputs/",
  "config": {
    "security": {
      "execution_mode": "trusted",
      "secrets_scan": true
    }
  }
}
```

**File content (inputs/config.local):**
```yaml
database:
  host: localhost
  api_key: sk-proj-xxxxxxxxxxxx
```

**Output:**
```json
{
  "gate": "GATE-SECURITY",
  "status": "FAIL",
  "gap_tag": "[gap: secrets_detected_in_inputs]",
  "checks": {
    "secrets_scan": {
      "status": "FAIL",
      "files_scanned": 5,
      "secrets_found": 1,
      "findings": [
        {
          "file": "config.local",
          "line": 3,
          "type": "API_KEY",
          "severity": "CRITICAL"
        }
      ]
    }
  },
  "remediation": "Remove credentials from inputs/ or add to .secrets.baseline"
}
```

#### Example 3: WARN - Sandbox unavailable

**Input:**
```json
{
  "config": {
    "security": {
      "execution_mode": "sandbox",
      "sandbox_type": "docker"
    }
  }
}
```

**Output (Docker not running):**
```json
{
  "gate": "GATE-SECURITY",
  "status": "WARN",
  "gap_tag": "[gap: sandbox_required_but_unavailable]",
  "checks": {
    "execution_mode": {
      "status": "WARN",
      "requested": "sandbox",
      "fallback": "trusted",
      "reason": "Docker daemon not responding"
    }
  }
}
```

---

## GATE-EXEC

**Purpose:** Validate execution safety during processing. Ensures sandbox is active, operations are approved, and rate limits are respected.

### PASS Conditions (ALL must be true)

| Condition | Description | Validation Method |
|-----------|-------------|-------------------|
| Sandbox active | If configured, sandbox is verified operational | `SandboxVerifier.check_status()` returns `active: true` |
| Code execution approved | Risky operations have human acknowledgment | `approval_token` present for destructive operations |
| Rate limits not exceeded | API call rate within configured limits | `api_calls.minute < rate_limit.minute` |

### FAIL Conditions (ANY triggers failure)

| Condition | GAP Tag | Example |
|-----------|---------|---------|
| Sandbox required but unavailable | `[gap: sandbox_activation_failed]` | `sandbox_type: docker` but container crashed |
| Unapproved execution | `[gap: execution_requires_approval]` | `rm -rf` attempted without approval token |
| Rate limit exceeded | `[gap: rate_limit_exceeded]` | >100 API calls in 1 minute |
| Timeout exceeded | `[gap: execution_timeout]` | Operation took >300 seconds |

### WARN Conditions

| Condition | Description |
|-----------|-------------|
| Approaching rate limit | API call rate >80% of limit |
| Sandbox degraded | Sandbox responding slowly (>5s latency) |
| Memory pressure | Sandbox memory usage >90% |

### Input/Output Examples

#### Example 1: PASS - Normal execution

**Input:**
```json
{
  "operation": "file_write",
  "target": "outputs/result.md",
  "sandbox_config": {
    "enabled": true,
    "timeout_ms": 10000
  }
}
```

**Output:**
```json
{
  "gate": "GATE-EXEC",
  "status": "PASS",
  "checks": {
    "sandbox": {"status": "PASS", "type": "restricted_subprocess", "latency_ms": 23},
    "approval": {"status": "N/A", "reason": "non-destructive operation"},
    "rate_limit": {"status": "PASS", "calls_minute": 12, "limit": 100}
  }
}
```

#### Example 2: FAIL - Unapproved destructive operation

**Input:**
```json
{
  "operation": "file_delete",
  "target": "src/legacy/",
  "pattern": "*.old",
  "approval_token": null
}
```

**Output:**
```json
{
  "gate": "GATE-EXEC",
  "status": "FAIL",
  "gap_tag": "[gap: execution_requires_approval]",
  "checks": {
    "approval": {
      "status": "FAIL",
      "required": true,
      "operation": "file_delete",
      "reason": "Destructive operation requires approval token"
    }
  },
  "remediation": "Provide approval_token from 'titan approve' command"
}
```

#### Example 3: WARN - Approaching rate limit

**Output:**
```json
{
  "gate": "GATE-EXEC",
  "status": "WARN",
  "checks": {
    "rate_limit": {
      "status": "WARN",
      "calls_minute": 85,
      "limit": 100,
      "utilization": "85%",
      "recommendation": "Consider reducing batch size or enabling caching"
    }
  }
}
```

---

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

---

## Associated GAP Tags Reference

| GAP Tag | Gate | Severity | Auto-remediation |
|---------|------|----------|------------------|
| `[gap: secrets_detected_in_inputs]` | GATE-SECURITY | CRITICAL | Add to .secrets.baseline or remove |
| `[gap: workspace_boundary_violation]` | GATE-SECURITY | CRITICAL | Use relative paths |
| `[gap: config_schema_mismatch]` | GATE-SECURITY | HIGH | Fix config.yaml keys |
| `[gap: sandbox_required_but_unavailable]` | GATE-SECURITY | HIGH | Start Docker or change mode |
| `[gap: credential_leak_detected]` | GATE-SECURITY | CRITICAL | Use CredentialManager |
| `[gap: sandbox_activation_failed]` | GATE-EXEC | HIGH | Check sandbox logs |
| `[gap: execution_requires_approval]` | GATE-EXEC | MEDIUM | Run `titan approve` |
| `[gap: rate_limit_exceeded]` | GATE-EXEC | HIGH | Reduce concurrency |
| `[gap: execution_timeout]` | GATE-EXEC | MEDIUM | Increase timeout or simplify operation |

---

## Cross-References

- **PROTOCOL.md** - Core gate definitions and processing flow
- **src/security/execution_gate.py** - Implementation of GATE-EXEC
- **src/security/secret_scanner.py** - Secret detection implementation
- **src/security/sandbox_verifier.py** - Sandbox status verification
- **src/config/schema_validator.py** - Config schema validation
- **schemas/config.schema.json** - JSON Schema for configuration
