# Discrepancy Matrix

## Documentation Discrepancies

| ID | Type | File | Expected | Actual | Severity | Status |
|----|------|------|----------|--------|----------|--------|
| GAP-DOC-01 | VERSION | README.md | v5.2.0 | v5.1.0 | HIGH | PENDING |
| GAP-DOC-02 | VERSION | PROTOCOL.base.md | v5.2.0 | v3.2 | CRITICAL | PENDING |
| GAP-DOC-03 | DATA | README.md | 3117+ tests | 2796+ tests | MEDIUM | PENDING |
| GAP-DOC-04 | STATUS | README.md | TIER_7_STABLE | TIER_7_IN_PROGRESS | HIGH | PENDING |

## Path Discrepancies (from CHANGELOG v5.2.0)

| Cited Path | Actual Path | Issue | Verified |
|------------|-------------|-------|----------|
| src/patterns/canonical_schema.py | src/schema/canonical_patterns.yaml | Directory does not exist, file is YAML not Python | ✅ VERIFIED |
| src/state/gap_event.py | src/events/gap_event.py | Wrong directory | ✅ VERIFIED |
| src/patterns/gap_registry.py | src/gap_events/gap_registry.yaml | Directory does not exist, file is YAML not Python | ✅ VERIFIED |
| src/skills/skill_generator.py | src/generation/skill_generator.py | Wrong directory | ✅ VERIFIED |
| tests/determinism_guard_test.py | tests/test_determinism.py | Wrong filename | ✅ VERIFIED |

## Implementation Discrepancies

| ID | Type | Description | Severity | Status |
|----|------|-------------|----------|--------|
| GAP-IMPL-01 | PATTERNS | 11 canonical patterns deferred to v5.3.0 | HIGH | PENDING |
| GAP-IMPL-02 | REGISTRY | Gap registry expansion needed for new patterns | MEDIUM | PENDING |
| GAP-IMPL-03 | PIPELINE | ContentPipeline multi-file coordination partial | MEDIUM | PENDING |
| GAP-IMPL-04 | VALIDATION | SkillGenerator pattern composition validation needed | MEDIUM | PENDING |

## Verification Discrepancies

| ID | Type | Description | Severity | Status |
|----|------|-------------|----------|--------|
| GAP-VER-01 | PATH | Path corrections need enforcement in CHANGELOG | LOW | PENDING |
| GAP-VER-02 | SCHEMA | Schema validation for canonical patterns | MEDIUM | PENDING |
| GAP-VER-03 | COVERAGE | Integration test coverage for security subpackage | MEDIUM | PENDING |

## Summary

- Total discrepancies: 12
- Critical: 1 (GAP-DOC-02)
- High: 3
- Medium: 6
- Low: 2

## Resolution Plan

1. **PHASE_1**: Resolve all documentation discrepancies (GAP-DOC-*)
2. **PHASE_2**: Implement deferred canonical patterns (GAP-IMPL-01)
3. **PHASE_3**: Expand gap registry (GAP-IMPL-02)
4. **PHASE_4**: Enhance ContentPipeline (GAP-IMPL-03)
5. **PHASE_5**: Final validation and integration
