---
purpose: "Version history and migration guide for TITAN FUSE Protocol"
audience: ["developers", "users"]
when_to_read: "When upgrading protocol version or understanding feature history"
related_files: ["VERSION", "README.md", "PROTOCOL.md"]
stable_sections: ["Version History Summary", "Migration Guide"]
emotional_tone: "informative, historical, practical"
ideal_reader_state: "upgrading or reviewing protocol changes"
---

# Changelog

All notable changes to the TITAN FUSE Protocol will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.2.0] - 2024-01-15

### Added
- **Chunk-level checkpoint recovery**: Extended checkpoint format to support partial resumption when source file changes
- **Enhanced llm_query with fallback chain**: Progressive fallback strategy (4 attempts with size reduction and model switching)
- **Protocol assembly script**: Deterministic assembly of PROTOCOL.md from base and extension files
- **Checkpoint validation tool**: Python script to validate checkpoint integrity and determine resumption type
- **Metrics export**: Structured metrics.json output for monitoring integration
- **Custom validators framework**: Extensible validation system with example validators (no-todos, api-version, security)
- **GitHub Actions workflow**: Automated validation of repository structure and protocol assembly
- **Interactive approval handler**: Support for human-in-the-loop approval when limits are exceeded
- **Configurable approval modes**: Interactive, callback, or auto-reject modes

### Changed
- Repository structure now aligns with TIER -1 specification
- Checkpoint format upgraded to v2.0 with chunk checksums
- Multi-file processing limit increased from 3 to 10 with approval

### Fixed
- Repository structure inconsistencies between plan and TIER -1 spec
- Missing validation of assembled PROTOCOL.md syntax
- No fallback behavior when SKILL.md is malformed or missing
- Git operations without prerequisites check

### Deprecated
- Single retry llm_query (replaced by fallback chain)

## [3.1.0] - 2024-01-01

### Added
- Session persistence with checkpoint support
- Operation budget tracking (tokens and time)
- Patch idempotency guarantee (INVAR-04)
- Expanded tool matrix (AST, binary detection, encoding, TOML)
- llm_query specification with typed results
- Parallel-safe batch validation (P1-P4 checks)
- Unified severity scale (SEV-1..4)

### Fixed
- EXECUTION_DIRECTIVE numbering
- GATE-04 threshold calculation
- Severity scale inconsistencies
- Double hygiene issue
- Checksum idempotency

## [3.0.0] - 2023-12-15

### Added
- TIER -1 Bootstrap Extension for repo-aware operations
- Entry point classification (REPO_NAVIGATE, FILE_DIRECT, REPOMIX, REPO_HOST)
- Git-backed rollback points
- Multi-file coordination stub
- Environment offload for large files (>5000 lines)
- QUICK_ORIENT header for state synchronization

### Changed
- Major architecture redesign for production-grade operations
- Workspace isolation (SOURCE_FILE = read-only)

## [2.0.0] - 2023-11-01

### Added
- Surgical Patch Engine (GUARDIAN)
- Deterministic validation loop
- Document hygiene protocol
- Verification gate protocol
- Pathology & Risk Registry

### Changed
- Improved chunking strategy (1000-1500 lines)
- Enhanced cross-reference checking

## [1.0.0] - 2023-10-01

### Added
- Initial release of TITAN FUSE Protocol
- Core tier structure (TIER 0-6)
- Hard invariants and anti-fabrication rules
- S-5 Veto for immutable content
- Zero-drift guarantee
- Basic rollback protocol
- Failsafe protocol for edge cases

---

## Version History Summary

| Version | Date | Major Features |
|---------|------|----------------|
| 3.2.0 | 2024-01-15 | Chunk-level recovery, enhanced llm_query, metrics |
| 3.1.0 | 2024-01-01 | Session persistence, budget tracking, idempotency |
| 3.0.0 | 2023-12-15 | TIER -1 Bootstrap, environment offload |
| 2.0.0 | 2023-11-01 | Patch engine, validation loop, hygiene |
| 1.0.0 | 2023-10-01 | Initial release |

## Migration Guide

### From 3.1.0 to 3.2.0

1. Update checkpoint format to include `chunk_checksums` and `resumption_type`
2. Replace single-retry llm_query calls with enhanced version
3. Add `scripts/` directory with assembly and validation tools
4. Update SKILL.md with new configuration options

### From 3.0.0 to 3.1.0

1. Add operation budget initialization in EXECUTION_DIRECTIVE
2. Update patch engine to verify idempotency
3. Add GATE-04 threshold rules to validation

### From 2.x to 3.0.0

1. Add TIER -1 bootstrap phase before standard initialization
2. Update WORK_DIR to use IN_MEMORY_BUFFER fallback
3. Add checkpoint.json for session persistence
