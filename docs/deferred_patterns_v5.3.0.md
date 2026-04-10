# Deferred Patterns — v5.3.0 Roadmap

The following 11 patterns were identified during Plan B analysis but deferred
from v5.2.0 to manage scope. They will be implemented in v5.3.0.

| # | Pattern ID | Priority | Rationale for Deferral |
|---|---|---|---|
| 1 | CODE_REVIEW_v2.0 | High | Requires multi-file diff analysis |
| 2 | SECURITY_SCAN_v1.0 | High | Requires external scanner integration |
| 3 | PERF_OPTIMIZE_v1.0 | Medium | Needs profiling infrastructure |
| 4 | MIGRATION_ASSIST_v1.0 | Medium | Depends on ContentPipeline stabilization |
| 5 | DOC_GEN_v2.0 | Medium | Template system needs extension |
| 6 | TEST_COVER_v1.0 | Medium | Requires coverage toolchain |
| 7 | REFACTOR_SUGGEST_v1.0 | Low | Complex AST transformation |
| 8 | CONFIG_VALIDATE_v1.0 | Low | Schema validation framework needed |
| 9 | LOG_ANALYZE_v1.0 | Low | Log parsing infrastructure needed |
| 10 | API_CONTRACT_v1.0 | Low | OpenAPI spec integration needed |
| 11 | MULTI_LANG_v1.0 | Low | Requires i18n framework |

## Implementation Timeline

| Phase | Patterns | Estimated Effort |
|---|---|---|
| v5.3.0-alpha | CODE_REVIEW_v2.0, SECURITY_SCAN_v1.0 | 2 weeks |
| v5.3.0-beta | PERF_OPTIMIZE_v1.0, MIGRATION_ASSIST_v1.0, DOC_GEN_v2.0 | 2 weeks |
| v5.3.0-rc | TEST_COVER_v1.0, REFACTOR_SUGGEST_v1.0 | 1 week |
| v5.3.0 | CONFIG_VALIDATE_v1.0, LOG_ANALYZE_v1.0, API_CONTRACT_v1.0, MULTI_LANG_v1.0 | 1 week |

## Dependencies

- CODE_REVIEW_v2.0 requires: AST diff engine, multi-file context
- SECURITY_SCAN_v1.0 requires: Bandit/Safety integration, vulnerability DB
- PERF_OPTIMIZE_v1.0 requires: cProfile integration, benchmark harness

## See Also

- `config/prompt_registry.yaml` - Current registered patterns
- `IMPLEMENTATION_STATUS.md` - Overall project status
