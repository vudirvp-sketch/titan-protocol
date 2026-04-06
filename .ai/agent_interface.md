# Agent Interface — TITAN FUSE Protocol

## Command Specification

### Entry Points

| Command | Description | Required Args |
|---------|-------------|---------------|
| `titan init` | Initialize session | `--input <path>` |
| `titan process` | Execute pipeline | `--phase <0-5>` |
| `titan checkpoint` | Save checkpoint | `--force` |
| `titan resume` | Resume session | `--checkpoint <path>` |
| `titan validate` | Run validations | `--gate <00-05>` |
| `titan status` | Show state | `--verbose` |
| `titan rollback` | Revert changes | `--to <backup_id>` |

### Options

```
--input <path>         Input file path (required for init)
--output <path>        Output directory (default: outputs/)
--chunk-size <n>       Chunk size in lines (default: 1500)
--max-tokens <n>       Token budget (default: 100000)
--max-time <n>         Time budget in minutes (default: 60)
--clean                Strip metadata from output
--full-merge           Generate full merged file
--dry-run              Plan only, no execution
--verbose              Enable verbose logging
--force                Force operation (use with caution)
```

### Return Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | GATE failure |
| 2 | Validation error |
| 3 | Budget exceeded |
| 4 | Rollback triggered |
| 5 | User abort |
| 127 | Configuration error |

### Output Format

All commands output structured JSON to stdout:

```json
{
  "status": "success|failure|warning",
  "code": 0,
  "message": "Human-readable message",
  "data": {
    "state_snapshot": { ... },
    "gates": { ... },
    "metrics": { ... }
  }
}
```

## Integration Notes

- Agent reads `AGENTS.md` first for navigation
- `SKILL.md` provides configuration overrides
- `PROTOCOL.md` is assembled from `.base` and `.ext`
- Checkpoints enable cross-session persistence
