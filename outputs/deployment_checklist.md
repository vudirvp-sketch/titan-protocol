# TITAN Protocol - Deployment Checklist

## Pre-Deployment

### Environment
- [ ] Python 3.10+ installed
- [ ] Node.js 18+ installed (for JS validators)
- [ ] Required environment variables set:
  - [ ] `TITAN_API_KEY`
  - [ ] `TITAN_TOKEN_LIMIT`
  - [ ] `OPENAI_API_KEY` (if using OpenAI)
  - [ ] `ANTHROPIC_API_KEY` (if using Anthropic)

### Configuration
- [ ] `config.yaml` reviewed and customized
- [ ] `SKILL.md` constraints appropriate for use case
- [ ] Prometheus endpoint enabled (if monitoring required)
- [ ] Alert rules configured (if alerting required)

### Security
- [ ] `.secrets.baseline` generated
- [ ] Workspace isolation path configured
- [ ] Execution gate mode set appropriately
- [ ] No hardcoded credentials in config

---

## Deployment Steps

### 1. Clone and Setup
```bash
git clone https://github.com/vudirvp-sketch/titan-protocol.git
cd titan-protocol
./scripts/assemble_protocol.sh
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
npm install  # For JS validators
```

### 3. Validate Installation
```bash
python scripts/test_navigation.py
python scripts/validate_checkpoint.py checkpoints/checkpoint.schema.json
python -m pytest tests/test_config_validation.py -v
```

### 4. Configure
```bash
# Copy and edit config
cp config.yaml config.local.yaml
# Edit config.local.yaml as needed
```

### 5. Test Run
```bash
# Dry run with example file
python -m src.harness.orchestrator --dry-run inputs/test.md
```

---

## Post-Deployment

### Validation
- [ ] All tests pass: `pytest tests/`
- [ ] Navigation tests pass: `python scripts/test_navigation.py`
- [ ] Version sync verified: `python scripts/check_version_sync.py --strict`

### Monitoring
- [ ] Prometheus scraping `/metrics` endpoint
- [ ] Grafana dashboard imported
- [ ] Alert rules loaded
- [ ] Runbooks accessible

### Documentation
- [ ] README.md reflects current version
- [ ] CHANGELOG.md updated
- [ ] AGENTS.md entry points valid

---

## Rollback Procedure

If issues arise:

```bash
# 1. Stop processing
pkill -f titan

# 2. Restore from checkpoint
python -m src.harness.orchestrator --rollback checkpoints/checkpoint.json

# 3. Restore previous version
git checkout HEAD~1 -- .
```

---

## Health Check Commands

```bash
# Quick health
python -m src.cli.titan_cli doctor

# Full validation
python scripts/test_navigation.py
python scripts/check_version_sync.py --strict
pytest tests/test_config_validation.py -v

# Metrics
curl http://localhost:9090/metrics
```

---

## Support

- **Issues**: https://github.com/vudirvp-sketch/titan-protocol/issues
- **Documentation**: `PROTOCOL.md`, `README.md`
- **Agent Entry**: `AGENTS.md`
