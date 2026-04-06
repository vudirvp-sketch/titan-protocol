# Inputs Directory

This directory contains input files for processing by the TITAN FUSE Protocol agent.

## Supported Formats

| Format | Description | Maximum Size |
|--------|-------------|--------------|
| `.md` | Markdown files | 50k+ lines |
| `.txt` | Plain text | 50k+ lines |
| `.json` | JSON files | 50k+ lines |
| `.yaml` | YAML configuration | 50k+ lines |
| `.xml` | Repomix output | 50k+ lines |
| `.repomix` | Repomix combined format | 50k+ lines |

## Input Classification

When placing files in this directory, the agent will automatically classify them:

- **text**: Standard text files (`.md`, `.txt`, `.json`, `.yaml`)
- **repomix**: Combined repository exports (`.xml`, `.repomix`)
- **binary**: Non-text files (skipped with log entry)

## Multi-File Processing

The protocol supports processing multiple files with the following constraints:

- **Default limit**: 3 files per session
- **Exceeding limit**: Requires explicit approval via SKILL.md configuration
- **Cross-file patches**: Currently BLOCKED in v1.0 (will be supported in v2.0)

## Symbolic Links

Symbolic links are supported. The agent will:
1. Resolve the symlink to its target
2. Track the original path in `SOURCE_FILE` for checkpoint purposes
3. Process the file as if it were directly in `inputs/`

## Example Usage

```bash
# Copy a file for processing
cp /path/to/large-file.md inputs/

# Or use a symlink
ln -s /path/to/project/README.md inputs/README.md

# Multiple files
cp file1.md file2.md file3.json inputs/
```

## Checkpoint Compatibility

When resuming from a checkpoint:
- The source file checksum is verified
- If the file changed, partial resumption may be attempted (chunk-level checksums)
- Add `.gitkeep` to preserve this directory in git
