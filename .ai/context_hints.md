# Context Hints for TITAN FUSE Navigation

## STOP Signals

⛔ **STOP** if you encounter:
- Missing `SKILL.md` in repository root
- `inputs/` directory is empty
- Source file checksum mismatch on resumption
- SEV-1 gaps > 0 at GATE-04
- Budget exceeded (token or time)

## PROCEED Signals

✅ **PROCEED** when:
- All verification gates PASS
- Checkpoint validated
- Budget headroom confirmed
- No KEEP_VETO violations

## GO Signals

🚀 **GO** to next phase when:
- GATE-00 PASS → Phase 1
- GATE-01 PASS → Phase 2
- GATE-02 PASS → Phase 3
- GATE-03 PASS → Phase 4
- GATE-04 PASS/WARN → Phase 5
- GATE-05 PASS → Complete

## Warning Signals

⚠️ **WARN** when:
- SKILL version > agent version
- SEV-3 gaps > 5
- SEV-4 gaps > 10
- Confidence advisory triggered

## File Priority Order

1. `AGENTS.md` — Read FIRST
2. `SKILL.md` — Configure agent
3. `PROTOCOL.md` — Full spec
4. `config.yaml` — Runtime defaults
5. `inputs/` — Process targets

## Quick Reference

| Signal | Meaning |
|--------|---------|
| ⛔ | Block execution |
| ⚠️ | Warning but continue |
| ✅ | Clear to proceed |
| 🚀 | Advance to next phase |
