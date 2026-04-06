# Outputs Directory

Generated artifacts from TITAN FUSE Protocol processing are placed here.

## Output Artifacts

| Artifact | Description |
|----------|-------------|
| `INDEX.md` | Hierarchical table of contents with line ranges |
| `SYMBOL_MAP.json` | Functions/classes/variables with locations |
| `CHANGE_LOG.md` | Record of all modifications made |
| `DECISION_RECORD.md` | Key decisions and rationale |
| `metrics.json` | Session telemetry and statistics |
| `*_merged.md` | Final merged output files |

## Directory Structure

```
outputs/
├── INDEX.md              # Navigation index
├── SYMBOL_MAP.json       # Symbol reference map
├── CHANGE_LOG.md         # Modification log
├── metrics.json          # Session metrics
└── [input_name]_merged.md  # Processed output files
```

## Metrics Format

```json
{
  "session": {
    "id": "uuid",
    "duration_seconds": 1847,
    "status": "COMPLETE"
  },
  "processing": {
    "chunks_total": 15,
    "issues_found": 47,
    "issues_fixed": 42,
    "gaps": 2
  },
  "gates": {
    "GATE-00": "PASS",
    "GATE-01": "PASS",
    "GATE-02": "PASS",
    "GATE-03": "PASS",
    "GATE-04": "WARN",
    "GATE-05": "PASS"
  }
}
```
