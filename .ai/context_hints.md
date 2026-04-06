# Context Hints — TITAN FUSE Protocol

## STOP Signals

🛑 **STOP** if you encounter:
- Files marked with `<!-- KEEP -->` — cannot modify
- Binary files — skip and log `[gap: binary_file]`
- `KEEP_VETO = TRUE` in ISSUE_ID — exclude from batch
- Source checksum mismatch on resume — start fresh
- GATE FAIL without resolution path

## PROCEED Signals

✅ **PROCEED** when:
- GATE-00 through GATE-05 all PASS
- All issues classified with ISSUE_ID
- No KEEP_VETO violations in plan
- Budget headroom confirmed (> 10% remaining)
- Validation loop passes all checks

## GO Signals

🚀 **GO** to next phase when:
- **PHASE 0 → PHASE 1**: NAV_MAP built, workspace isolated
- **PHASE 1 → PHASE 2**: All patterns scanned
- **PHASE 2 → PHASE 3**: All issues classified
- **PHASE 3 → PHASE 4**: Plan validated, budget confirmed
- **PHASE 4 → PHASE 5**: All validations pass OR gaps in threshold

## Warning Indicators

⚠️ **WARN** when:
- SEV-3 gaps > 5
- SEV-4 gaps > 10
- Token budget > 90% used
- Time budget > 90% used
- Version mismatch (SKILL > agent)

## Block Indicators

❌ **BLOCK** when:
- SEV-1 gaps > 0
- SEV-2 gaps > 2
- Total gaps > 20% of issues
- GATE verification fails
- KEEP_VETO violation attempted
