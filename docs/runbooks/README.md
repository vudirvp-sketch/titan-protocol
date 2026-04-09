# TITAN Protocol Runbooks

Operational runbooks for common alert responses and troubleshooting procedures.

---

## Table of Contents

1. [High Latency Alert](#high-latency-alert)
2. [Gate Failure](#gate-failure)
3. [GATE-04 Blocked](#gate-04-blocked)
4. [Budget Exceeded](#budget-exceeded)
5. [Security Alert](#security-alert)
6. [Checkpoint Recovery](#checkpoint-recovery)
7. [Rollback Procedure](#rollback-procedure)

---

## High Latency Alert

### Symptoms
- P99 latency > 1.0s (warning) or > 2.0s (critical)
- P95 latency > 500ms
- Session duration exceeding expected bounds

### Diagnosis Steps

1. Check chunk size configuration:
   ```bash
   grep -A5 "chunking:" config.yaml
   ```

2. Verify LLM provider response times:
   ```bash
   curl -s http://localhost:9090/metrics | grep titan_llm_response_seconds
   ```

3. Review memory usage:
   ```bash
   curl -s http://localhost:9090/metrics | grep titan_memory_mb
   ```

### Resolution

| Cause | Action |
|-------|--------|
| Large chunks | Reduce `chunking.default_size` in config.yaml |
| LLM slow | Check provider status, consider fallback model |
| Memory pressure | Reduce parallel batches, enable cleanup |
| Complex file | Use `--profile resource_constrained` |

---

## Gate Failure

### Symptoms
- Gate failure rate > 10%
- GATE-00 through GATE-05 failures in logs

### Diagnosis Steps

1. Identify failed gate:
   ```bash
   grep "GATE.*FAIL" outputs/metrics.json
   ```

2. Review gap objects:
   ```bash
   python -c "import json; print(json.dumps(json.load(open('outputs/metrics.json'))['gaps'], indent=2))"
   ```

### Resolution by Gate

#### GATE-00 (NAV_MAP)
- Cause: Missing or corrupted nav_map.json
- Fix: Run `python scripts/generate_nav_map.py`

#### GATE-01 (Patterns)
- Cause: Incomplete pattern scan
- Fix: Check `inputs/` directory, verify file accessibility

#### GATE-02 (Issues)
- Cause: Unresolved issues
- Fix: Review and address SEV-1/SEV-2 issues first

#### GATE-03 (Plan)
- Cause: KEEP_VETO violation or cycle detected
- Fix: Review plan, remove KEEP markers or break cycle

#### GATE-04 (Validation)
- Cause: Too many gaps, SEV-1/SEV-2 threshold exceeded
- Fix: Address critical issues, then re-run

#### GATE-05 (Artifacts)
- Cause: Missing or invalid artifacts
- Fix: Verify outputs/ directory, check audit_trail.sig

---

## GATE-04 Blocked

### Symptoms
- GATE-04 blocking frequently (3+ times per hour)
- SEV-1 or SEV-2 gaps present

### Immediate Actions

1. List critical gaps:
   ```bash
   python -c "
   import json
   m = json.load(open('outputs/metrics.json'))
   for g in m.get('gaps', []):
       if g.get('severity') in ['SEV-1', 'SEV-2']:
           print(f\"{g['id']}: {g['description']}\")
   "
   ```

2. Check gap thresholds:
   ```yaml
   # config.yaml
   validation:
     gate_04:
       max_sev1_gaps: 0
       max_sev2_gaps: 2
       max_total_gap_pct: 20
   ```

### Resolution

1. **SEV-1 gaps**: Must be resolved before proceeding
2. **SEV-2 gaps**: Resolve or acknowledge risk
3. **SEV-3/SEV-4**: Can be deferred with `--advisory-pass`

---

## Budget Exceeded

### Symptoms
- Token usage > 90% (warning) or > 100% (critical)
- Session terminated unexpectedly

### Diagnosis

1. Check token attribution:
   ```bash
   curl -s http://localhost:9090/metrics | grep titan_tokens_per_gate
   ```

2. Review largest consumers:
   ```bash
   python -c "
   import json
   m = json.load(open('outputs/metrics.json'))
   print(f\"Total tokens: {m['session']['tokens_used']}\")
   print(f\"Budget: {m['session']['token_budget']}\")
   "
   ```

### Resolution

1. **Short-term**: Increase budget
   ```yaml
   # config.yaml
   session:
     max_tokens: 150000
   ```

2. **Optimize**: Enable context compaction
   ```yaml
   context:
     compaction_enabled: true
     compaction_threshold: 0.8
   ```

3. **Switch models**: Use leaf model for chunks
   ```yaml
   model_routing:
     leaf_model: "gpt-3.5-turbo"
   ```

---

## Security Alert

### Symptoms
- Secrets detected in input files
- Sandbox violations

### Immediate Actions

1. **Stop processing** - do not continue
2. **Review detection**:
   ```bash
   cat .secrets.baseline 2>/dev/null || echo "No baseline found"
   ```

3. **Isolate affected files**:
   ```bash
   mv inputs/suspicious_file.md inputs/quarantine/
   ```

### Resolution

1. **False positive**: Add to baseline
   ```bash
   detect-secrets scan --baseline .secrets.baseline inputs/
   ```

2. **True positive**: Remove secret, rotate credential
   - Remove the secret from source file
   - Rotate the exposed credential immediately
   - Document in SECURITY.md

---

## Checkpoint Recovery

### Full Session Resume

```bash
python scripts/validate_checkpoint.py checkpoints/checkpoint.json
# If VALID:
python -m src.harness.orchestrator --resume checkpoints/checkpoint.json
```

### Partial Recovery

When source file changed:

```bash
python scripts/validate_checkpoint.py checkpoints/checkpoint.json
# Output: PARTIAL - Chunks C1, C2, C3 recoverable
# Restart from last valid chunk:
python -m src.harness.orchestrator --resume checkpoints/checkpoint.json --from-chunk C3
```

---

## Rollback Procedure

### Pre-Rollback Check

1. Verify checkpoint exists:
   ```bash
   ls -la checkpoints/
   ```

2. Validate checkpoint integrity:
   ```bash
   python scripts/validate_checkpoint.py checkpoints/checkpoint.json
   ```

### Execute Rollback

```bash
# Create backup of current state
cp -r outputs/ outputs.backup.$(date +%s)/

# Restore from checkpoint
python -m src.harness.orchestrator --rollback checkpoints/checkpoint.json
```

### Post-Rollback Verification

1. Run validation:
   ```bash
   python scripts/test_navigation.py
   ```

2. Verify gate status:
   ```bash
   grep -A20 "gates:" outputs/metrics.json
   ```

---

## Diagnostic Commands

### Health Check

```bash
# Full system health
python -m src.cli.titan_cli doctor

# Quick status
curl http://localhost:8080/health 2>/dev/null || echo "Health endpoint not available"
```

### Log Analysis

```bash
# Recent errors
grep -i error logs/titan.log | tail -20

# Gate failures
grep "GATE.*FAIL" logs/titan.log

# Token usage trend
grep "tokens" logs/titan.log | tail -50
```

### Metrics Export

```bash
# Prometheus format
curl http://localhost:9090/metrics > metrics.prom

# JSON format
python scripts/generate_metrics.py --output metrics.json
```

---

## Contact & Escalation

| Issue Type | Escalation Path |
|------------|-----------------|
| Security incident | Security team → Disable system |
| Data loss | Backup team → Restore from backup |
| Performance | DevOps team → Scale resources |
| Unknown error | Development team → Debug mode |

**Emergency stop**: `pkill -f titan` or `kill -9 $(cat .titan/pid)`
