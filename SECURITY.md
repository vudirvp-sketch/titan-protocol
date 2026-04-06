# Security Guidelines

## Credential Handling

- **NEVER** store API keys in SessionState, checkpoints, or metrics
- Use environment variables: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- Or pass via CLI: `titan login --provider openai`

## Validator Sandboxing

Custom validators in `skills/validators/*.js` execute in isolated VM.
Do not grant filesystem or network access.

## Workspace Isolation

All file operations must occur within configured `workspace_path`.
Set in config.yaml:
```yaml
security:
  workspace_path: "/path/to/safe/workspace"
```

## Secret Scanning

Enable secret scanning to detect credentials in input files:
```yaml
security:
  secrets_scan: true
```

## Input File Size Limits

Protect against DoS with file size limits:
```yaml
security:
  max_input_file_size_mb: 100
  max_total_input_size_mb: 500
```

## Safe Checkpoint Loading

- JSON is the default and safe format
- Pickle checkpoints require explicit `--unsafe` flag
- Never load pickle checkpoints from untrusted sources

## Sandbox Modes

- `trusted`: No sandbox required (default for development)
- `sandbox_docker`: Docker container isolation
- `sandbox_venv`: Virtual environment isolation
