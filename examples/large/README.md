# Example: Large File Processing

This example demonstrates processing a large file (> 5000 lines).

## Input

File: `codebase-documentation.md` (32,450 lines)

## Processing Steps

1. **PHASE 0**:
   - Activate Environment Offload (file > 5000 lines)
   - Create chunked NAV_MAP (22 chunks)
   - Initialize session checkpoint

2. **PHASE 1**:
   - Pattern scan across all chunks
   - Found: 47 duplicates, 23 TODOs, 12 orphan refs

3. **PHASE 2**:
   - Classify 156 issues
   - Severity breakdown: SEV-1: 2, SEV-2: 18, SEV-3: 67, SEV-4: 69

4. **PHASE 3**:
   - Create 8 batches
   - Budget check: 78,432 / 100,000 tokens

5. **PHASE 4**:
   - Execute surgical patches
   - Validation loop per chunk
   - 2 chunks required gap marking

6. **PHASE 5**:
   - Document hygiene
   - Generate all artifacts
   - Full merge BLOCKED (file > 8000 lines, no override)

## Output Artifacts

```
outputs/
├── INDEX.md
├── SYMBOL_MAP.json
├── CHANGE_LOG.md
├── metrics.json
├── PATHOLOGY_REGISTRY.md
└── (no merged file - exceeds limit)
```

## Sample Metrics

```json
{
  "session": {
    "duration_seconds": 1847,
    "status": "COMPLETE"
  },
  "processing": {
    "issues_found": 156,
    "issues_fixed": 142,
    "gaps": 2
  },
  "gates": {
    "GATE-04": "WARN"
  }
}
```

## Notes

- Environment Offload critical for memory management
- Chunk-level checkpoints enable partial resumption
- GATE-04 WARN due to 2 SEV-2 gaps
- Full merge requires explicit override for files > 8000 lines
