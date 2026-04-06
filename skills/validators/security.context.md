---
purpose: "Context and usage guide for security validator"
audience: ["agents", "developers"]
when_to_read: "Before running security validation or handling violations"
related_files: ["skills/validators/security.js", "PROTOCOL.base.md#PHASE-2"]
stable_sections: ["philosophy", "anti-patterns", "severity-levels"]
emotional_tone: "cautionary, security-focused, directive"
---

# security.context.md

## Philosophy

This validator detects **secrets, credentials, and sensitive data** in processed content. It is designed for **detection only** — security issues must NEVER be auto-fixed.

**Why this exists:**
- Prevent accidental exposure of secrets in outputs
- Flag credentials for human review before delivery
- Maintain security posture throughout processing

**Key principle:** Security violations are ALWAYS SEV-1 or SEV-2 and require human review. Never auto-fix.

---

## Pattern Categories

### Critical Patterns (SEV-1)

Triggers immediate halt for human review:

| Pattern | Example |
|---------|---------|
| AWS Access Keys | `AKIA...` (16 character key ID) |
| AWS Secret Keys | `aws_secret_access_key = "..."` |
| Private Keys | `-----BEGIN RSA PRIVATE KEY-----` |
| API Keys | `api_key = "sk-..."` |
| Database URLs | `mysql://user:pass@host/db` |

### Warning Patterns (SEV-2)

Potential secrets requiring review:

| Pattern | Example |
|---------|---------|
| Passwords | `password = "secret123"` |
| Tokens | `token = "eyJhbGci..."` |
| Base64 (potential) | Long base64 strings |
| Emails in config | `admin@company.com` |

### Info Patterns (SEV-3)

Sensitive data points:

| Pattern | Example |
|---------|---------|
| IP addresses | `192.168.1.1` |
| Sensitive URLs | `https://.../admin` |

---

## Anti-Patterns

### ❌ DO NOT:

1. **Auto-fix security violations**
   ```javascript
   // NEVER do this
   if (violation.type === 'critical_secret') {
     content = content.replace(pattern, 'REDACTED');
   }
   ```
   Security issues require manual review.

2. **Ignore SEV-1 violations**
   ```javascript
   // NEVER do this
   if (violations.filter(v => v.severity === 'SEV-1').length > 0) {
     continue; // Wrong!
   }
   ```
   SEV-1 violations must halt processing.

3. **Log secrets to output**
   ```javascript
   // NEVER do this
   console.log(`Found secret: ${match}`);
   ```
   Never log actual secret values.

4. **Process file with detected secrets**
   ```javascript
   // NEVER do this
   if (result.valid === false) {
     proceedAnyway(); // Wrong!
   }
   ```
   Stop and report for human review.

---

## Example Invocation

```javascript
const securityValidator = require('./security.js');

// Validate content
const result = securityValidator.validate(fileContent, {
  chunk_id: 'C2',
  file_path: 'config/settings.yaml'
});

// Check result
if (!result.valid) {
  console.log(result.summary);
  // "Found 3 potential security issue(s)"

  if (result.recommendation) {
    console.log(result.recommendation);
    // "SECURITY: Manual review required before proceeding"
  }

  // Process violations
  for (const violation of result.violations) {
    console.log(`Line ${violation.line}: [${violation.severity}] ${violation.type}`);
    console.log(securityValidator.suggestFix(violation));
  }

  // HALT for SEV-1 or SEV-2
  if (result.violations.some(v => v.severity === 'SEV-1' || v.severity === 'SEV-2')) {
    process.exit(1); // or throw error / request human review
  }
}
```

---

## Validation Result Structure

```javascript
{
  valid: false,                    // false if SEV-1 or SEV-2 found
  validator: 'security',
  violations: [
    {
      line: 42,
      type: 'critical_secret',     // critical_secret | potential_secret | sensitive_data
      pattern: '/AKIA[0-9A-Z]{16}/g',
      severity: 'SEV-1',
      autoFixable: false,          // ALWAYS false for security
      requiresHumanReview: true    // ALWAYS true for critical/warning
    }
  ],
  summary: 'Found 1 potential security issue(s)',
  recommendation: 'SECURITY: Manual review required before proceeding'
}
```

---

## Severity Mapping

| Pattern Category | Severity | Auto-Fixable | Human Review |
|------------------|----------|--------------|--------------|
| critical_secret | SEV-1 | ❌ Never | ✅ Required |
| potential_secret | SEV-2 | ❌ Never | ✅ Required |
| sensitive_data | SEV-3 | ❌ Never | ⚠️ Recommended |

---

## Protocol Integration

| Phase | Integration Point |
|-------|-------------------|
| Phase 2 | Auto-loaded with other validators |
| GATE-02 | Violations classified as ISSUE_IDs |
| Phase 3 | SEV-1/SEV-2 issues block execution |
| Phase 4 | Validation loop checks for new violations |
| GATE-04 | SEV-1 gaps > 0 causes BLOCK |

---

## Handling Workflow

```
1. Run security.validate(content)
   ↓
2. Check result.valid
   ├─ true → Continue processing
   └─ false ↓
3. Check violation severities
   ├─ SEV-1 found → STOP → Request human review
   ├─ SEV-2 found → STOP → Request human review
   └─ SEV-3 only → WARN → Continue with caution
4. Log violations (without secret values!)
5. Mark file for manual review
6. Do NOT include in output until resolved
```

---

## Configuration

The validator has no configuration options — all patterns are built-in for security.

To disable temporarily (NOT recommended for production):
```yaml
# config.yaml
validators:
  disabled:
    - security  # Only during development!
```

---

## Connections to Other Protocol Parts

| Component | Connection |
|-----------|------------|
| `PROTOCOL.base.md#PHASE-2` | Auto-loaded during classification |
| `PROTOCOL.base.md#SEV-1` | Critical violations map to SEV-1 |
| `TIER 4 — ROLLBACK` | Rollback on security halt |
| `INVAR-01` | No fabrication of secrets |
| `.ai/context_hints.md` | SEV-1 triggers STOP signal |

---

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| False positive on test data | Test credentials match patterns | Add exclusion comments or move to test fixtures |
| Missing pattern type | New secret format | Add pattern to appropriate category |
| Validator not running | Not in skills/validators/ | Check file location and .js extension |

---

**Validator Version:** 1.0.0
**Protocol Version:** 3.2.0
**Author:** TITAN FUSE Team
