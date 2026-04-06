# Inputs Directory

Place files to be processed by TITAN FUSE Protocol in this directory.

## Supported File Types

- **Text files**: Markdown, code files, configuration files
- **Repomix files**: XML or plaintext repository snapshots
- **Large files**: Files with 5,000+ lines are automatically chunked

## File Size Limits

| Size Category | Lines | Processing Mode |
|---------------|-------|-----------------|
| Small | < 5,000 | Direct processing |
| Medium | 5,000 - 20,000 | Chunked processing |
| Large | 20,000 - 50,000 | Aggressive chunking with checkpointing |
| Extra Large | > 50,000 | Requires explicit approval |

## Usage

1. Copy your file to this directory:
   ```bash
   cp /path/to/your/file.md inputs/
   ```

2. Run the TITAN FUSE agent
3. Results will be placed in `outputs/`

## Notes

- Binary files are automatically detected and skipped
- Files are processed in alphabetical order
- Maximum 3 files per session by default (configurable in SKILL.md)
