# Example: Small File Processing

This example demonstrates processing a small file (< 5000 lines).

## Input

File: `sample-document.md` (1,247 lines)

## Processing Steps

1. **PHASE 0**: Initialize session, build NAV_MAP
2. **PHASE 1**: Scan for patterns (duplicates, TODOs, orphan refs)
3. **PHASE 2**: Classify issues (found 8 issues)
4. **PHASE 3**: Create execution plan (2 batches)
5. **PHASE 4**: Execute fixes, validate
6. **PHASE 5**: Generate artifacts, apply hygiene

## Output Artifacts

```
outputs/
├── INDEX.md              # Navigation index
├── SYMBOL_MAP.json       # Symbol definitions
├── CHANGE_LOG.md         # Modifications made
├── metrics.json          # Session metrics
└── sample-document_merged.md  # Processed file
```

## Sample Metrics

```json
{
  "session": {
    "status": "COMPLETE",
    "duration_seconds": 45
  },
  "processing": {
    "issues_found": 8,
    "issues_fixed": 8,
    "gaps": 0
  }
}
```

## Notes

- Small files don't require Environment Offload
- Full merge mode is automatically enabled
- All gates passed
