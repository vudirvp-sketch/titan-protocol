# VERSION Synchronization Policy

## Overview

This document defines the policy for maintaining version consistency across the TITAN Protocol repository.

## Single Source of Truth

The `VERSION` file at repository root is the authoritative version source. All other version references MUST be derived from this file.

Current version: **5.2.0**

## Files That Reference VERSION

| File | Reference Type | Update Method |
|------|---------------|---------------|
| README.md | Header display | Manual sync |
| PROTOCOL.base.md | Header display | Manual sync |
| PROTOCOL.ext.md | Header display | Manual sync |
| CHANGELOG.md | Version entries | Manual on release |
| src/__init__.py | `__version__` variable | Manual sync |
| docs/policies/VERSION_SYNC.md | Policy reference | Manual sync |

## Files That MUST NOT Hardcode Version

- Any documentation file outside CHANGELOG.md
- Any source code file (except __init__.py)
- Configuration files (use variable substitution)

## Update Procedure

1. Update VERSION file with new version number
2. Run sync verification:
   ```bash
   python scripts/check_version_sync.py --strict
   ```
3. Update all referencing files:
   - README.md header and badges
   - PROTOCOL.base.md header
   - PROTOCOL.ext.md header
   - src/__init__.py __version__
4. Update CHANGELOG.md with release notes
5. Commit with message: `chore: bump version to X.Y.Z`
6. Tag release: `git tag vX.Y.Z`

## Version Format

Versions follow [Semantic Versioning](https://semver.org/):
- MAJOR version for incompatible API changes
- MINOR version for backwards-compatible functionality additions
- PATCH version for backwards-compatible bug fixes

Example: `5.2.0`
- MAJOR: 5
- MINOR: 2
- PATCH: 0

## Automated Sync (Future)

A CI check should verify version consistency:

```yaml
# .github/workflows/version-sync.yml
name: Version Sync Check
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check VERSION consistency
        run: |
          VERSION=$(cat VERSION)
          # Check README
          grep -q "v$VERSION" README.md || exit 1
          # Check PROTOCOL.base.md
          grep -q "v$VERSION" PROTOCOL.base.md || exit 1
          # Check src/__init__.py
          grep -q "__version__ = \"$VERSION\"" src/__init__.py || exit 1
          echo "Version sync check passed"
```

## Release Procedure

1. **Pre-release**
   - Ensure all tests pass
   - Update CHANGELOG.md with release notes
   - Update VERSION file

2. **Version bump**
   ```bash
   # Example: bump to 5.3.0
   echo "5.3.0" > VERSION
   python scripts/sync_readme_version.py
   python scripts/check_version_sync.py --strict
   ```

3. **Commit and tag**
   ```bash
   git add VERSION README.md PROTOCOL.base.md CHANGELOG.md src/__init__.py
   git commit -m "chore: bump version to 5.3.0"
   git tag v5.3.0
   git push origin main --tags
   ```

4. **Post-release**
   - Create GitHub release with CHANGELOG notes
   - Update documentation site if applicable

## Enforcement

Version sync failures should block CI pipeline. The check should be:
- Required on all PRs to main branch
- Required on all release branches
- Run as pre-commit hook (optional)

## History

| Version | Date | Changes |
|---------|------|---------|
| 5.2.0 | 2026-04-11 | Canonical patterns, ContentPipeline 6-phase, Gap registry |
| 5.1.0 | 2026-04-10 | TIER_7 exit criteria passed |
| 5.0.0 | 2026-04-08 | TIER_7 stable release |

## Contact

For questions about version synchronization, contact the TITAN FUSE Team.
