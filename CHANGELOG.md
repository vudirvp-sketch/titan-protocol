# TITAN FUSE Protocol Changelog

All notable changes to this project will be documented in this file.

## [3.2.1] - 2026-04-07

### Added
- **FILE_INVENTORY (Step 0.2.5)**: File metadata collection before chunking
  - Binary file detection with skip and log
  - Encoding detection (UTF-8 first, chardet fallback)
  - SHA-256 checksum for resume verification
  - File inventory JSON artifact
- **CURSOR_TRACKING**: Enhanced position tracking in STATE_SNAPSHOT
  - current_file, current_line, current_chunk, current_section
  - offset_delta for lines added/removed
  - Atomic update with checkpoint
  - Post-patch validation
- **ISSUE_DEPENDENCY_GRAPH (PHASE 3)**: DAG for issue dependencies
  - AST-based static analysis (primary method)
  - Regex-based fallback
  - DFS cycle detection with max depth 10
  - Topological ordering for processing
  - ASCII/GraphViz visualization
- **CROSSREF_VALIDATOR**: Reference validation module
  - Section, anchor, code, import reference extraction
  - REF_INDEX caching per chunk
  - Integration with GATE-00 and GATE-04
- **DIAGNOSTICS_MODULE (TIER 5)**: Systematic troubleshooting
  - Symptom → Root Cause → Solution matrix
  - Test scenarios for validation
  - Human-review fallback

### Changed
- Unified version to 3.2.1 across all files
- Updated checkpoint.schema.json with new fields
- Updated SKILL.md to version 2.1.0
- Added Russian language support (input_languages: en, ru)

### Fixed
- Version inconsistency between README.md (v3.2.0) and PROTOCOL.base.md (v3.1)

### Security
- Added workspace isolation path configuration
- Added ReDoS validation for regex patterns

## [3.2.0] - 2024-01-15

### Added
- Chunk-level checkpoint recovery for partial resumption
- Enhanced llm_query fallback with 4-attempt progressive chain
- Metrics export in JSON format for monitoring integration
- Custom validators framework in `skills/validators/`
- Navigation files in `.ai/` directory

### Changed
- Unified severity scale across all registries (SEV-1..4)
- Improved GATE-04 threshold rules

### Fixed
- Patch idempotency guarantee (INVAR-04)
- Double hygiene issue in Phase 5

## [3.1.0] - 2024-01-01

### Added
- Session persistence via checkpoints
- Operation budget tracking (tokens + time)
- Expanded tool matrix (AST, binary detection, encoding)
- llm_query specification with typed results

### Changed
- Unified severity definitions
- Parallel-safe batch validation (P1-P4)

## [3.0.0] - 2023-12-15

### Added
- TIER -1 Bootstrap phase for repository navigation
- Entry point classification (REPO_NAVIGATE, FILE_DIRECT, REPOMIX, REPO_HOST)
- Git-backed rollback points
- Multi-file coordination stub

### Changed
- Environment Offload activated for files > 5000 lines
- Workspace Isolation mandatory

## [2.0.0] - 2023-11-01

### Added
- Surgical Patch Engine (GUARDIAN)
- Deterministic Validation Loop
- Verification Gate Protocol
- Pathology & Risk Registry

### Changed
- Patch format standardization

## [1.0.0] - 2023-10-01

### Added
- Initial release
- Large file processing (5k-50k+ lines)
- Chunking strategy
- Anti-fabrication invariants
- Zero-Drift Guarantee
