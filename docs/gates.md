# Gate Reference Documentation

This document defines the canonical gate naming convention for TITAN FUSE Protocol.

## Canonical Gate Names

The TITAN Protocol uses a standardized 6-gate verification system:

| Gate | Name | Phase | Description |
|------|------|-------|-------------|
| GATE-00 | Initialization | Phase 0 | NAV_MAP exists AND all chunks indexed |
| GATE-01 | Search & Discovery | Phase 1 | All target patterns scanned |
| GATE-02 | Analysis & Classification | Phase 2 | All issues classified with ISSUE_ID |
| GATE-03 | Planning | Phase 3 | Plan validated AND no KEEP_VETO violations |
| GATE-04 | Execution & Validation | Phase 4 | Validations pass OR gaps within threshold |
| GATE-05 | Delivery & Hygiene | Phase 5 | All artifacts generated AND hygiene complete |

## Gate Aliases

For backward compatibility, the following aliases are supported:

### GATE-00 Aliases (Initialization)

| Alias | Context |
|-------|---------|
| GATE_REPO_00 | Repository initialization |
| GATE_REPO_01 | Bootstrap sequence complete |
| GATE_REPO_02 | Dependency graph built |
| GATE_INIT | Generic initialization |
| GATE_BOOTSTRAP | Bootstrap phase |

### GATE-01 Aliases (Discovery)

| Alias | Context |
|-------|---------|
| GATE_DISCOVERY | Discovery phase |
| GATE_PATTERN | Pattern detection |
| GATE_SCAN | Scanning operations |

### GATE-02 Aliases (Analysis)

| Alias | Context |
|-------|---------|
| GATE_ANALYSIS | Analysis phase |
| GATE_CLASSIFICATION | Issue classification |
| GATE_ISSUES | Issue management |

### GATE-03 Aliases (Planning)

| Alias | Context |
|-------|---------|
| GATE_PLANNING | Planning phase |
| GATE_PLAN | Execution plan |
| GATE_EXECUTION_PLAN | Plan validation |

### GATE-04 Aliases (Execution)

| Alias | Context |
|-------|---------|
| GATE_EXECUTION | Execution phase |
| GATE_VALIDATE | Validation |
| GATE_VALIDATION | Validation phase |
| GATE_PRE_EXEC | Pre-execution checks |
| GATE_POST_EXEC | Post-execution checks |

### GATE-05 Aliases (Delivery)

| Alias | Context |
|-------|---------|
| GATE_DELIVERY | Delivery phase |
| GATE_ARTIFACTS | Artifact generation |
| GATE_HYGIENE | Document hygiene |
| GATE_FINAL | Final checks |

## Usage

### In Code

```python
from src.policy.gate_manager import normalize_gate_name, get_gate_display_name

# Normalize an alias to canonical name
canonical = normalize_gate_name("GATE_REPO_01")  # Returns "GATE-00"

# Get human-readable name
display = get_gate_display_name("GATE_REPO_01")  # Returns "Initialization / Navigation Map"
```

### In Configuration

```yaml
# Both forms are acceptable
gates:
  - GATE-00
  - GATE_REPO_01  # Will be normalized to GATE-00
```

## GATE-04 Threshold Rules

GATE-04 has special threshold rules for pass/fail/warn:

### BLOCK Conditions

- Open SEV-1 gaps > 0
- Open SEV-2 gaps > 2
- Total open gaps > 20% of total issues

### WARN Conditions

- Open SEV-3 gaps > 5
- Open SEV-4 gaps > 10

### PASS Conditions

- All above conditions are false

## Pre/Post Execution Gates

GATE-04 is split into pre and post-execution checks:

### Pre-Execution Gates

1. Policy Check - Verify all policies are loaded
2. Access Control - Verify user permissions
3. Resource Availability - Check system resources
4. Input Validation - Validate input format
5. Budget Check - Verify token budget
6. Hyperparameter Check - Validate LLM parameters

### Post-Execution Gates

1. Output Structure - Validate output schema
2. Invariant Validation - Check invariants maintained
3. Change Verification - Verify expected changes
4. No Fabrication - Detect fabricated content
5. Gap Tracking - Ensure gaps are tracked

## See Also

- [Extended Gates Documentation](extended_gates.md)
- [Protocol Specification](../PROTOCOL.md)
- [Gate Manager Source](../src/policy/gate_manager.py)
