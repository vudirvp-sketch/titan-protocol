"""
Titan Migrate CLI for TITAN Protocol.

Unified CLI for version migrations with safety flags.

Usage:
    titan migrate --help
    titan migrate --list
    titan migrate --dry-run 4.1.0
    titan migrate --backup 4.1.0
    titan migrate --yes 4.2.0
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class Migration:
    """Represents a version migration."""
    from_version: str
    to_version: str
    description: str
    script: Optional[str] = None
    reversible: bool = True
    destructive: bool = False
    estimated_time_seconds: int = 60


@dataclass
class MigrationResult:
    """Result of a migration operation."""
    success: bool
    from_version: str
    to_version: str
    backup_id: Optional[str] = None
    changes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class TitanMigrateCLI:
    """
    Unified CLI for TITAN Protocol migrations.
    """

    MIGRATIONS: Dict[str, Migration] = {
        "3.2.0->3.2.1": Migration(
            from_version="3.2.0",
            to_version="3.2.1",
            description="Migrate config format and checkpoint serialization",
            script="scripts/migrate_config_v320_to_v321.py",
            reversible=True,
            destructive=False
        ),
        "3.2.1->4.0.0": Migration(
            from_version="3.2.1",
            to_version="4.0.0",
            description="Migrate pickle checkpoints to JSON+zstd format",
            script="scripts/migrate_checkpoints.py",
            reversible=False,
            destructive=True
        ),
        "4.0.0->4.1.0": Migration(
            from_version="4.0.0",
            to_version="4.1.0",
            description="Add TIER_7 production features",
            script=None,
            reversible=True,
            destructive=False
        ),
        "4.1.0->4.2.0": Migration(
            from_version="4.1.0",
            to_version="4.2.0",
            description="README sync infrastructure",
            script=None,
            reversible=True,
            destructive=False
        ),
    }

    def __init__(self, project_dir: Path = None, backup_dir: Path = None, config: Dict[str, Any] = None):
        self.project_dir = project_dir or Path(".")
        self.backup_dir = backup_dir or self.project_dir / "backups"
        self.config = config or {}
        self.auto_backup = self.config.get("migration", {}).get("auto_backup", True)
        self.max_backups = self.config.get("migration", {}).get("max_backups", 10)
        self.confirm_destructive = self.config.get("migration", {}).get("confirm_destructive", True)

    def detect_current_version(self) -> str:
        """Detect current project version."""
        version_file = self.project_dir / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip().split('\n')[0]
        return "0.0.0"

    def list_available_migrations(self) -> List[Migration]:
        """List available migrations from current version."""
        current = self.detect_current_version()
        return [m for key, m in self.MIGRATIONS.items() if m.from_version == current]

    def get_migration(self, target_version: str) -> Optional[Migration]:
        """Get migration to target version."""
        current = self.detect_current_version()
        return self.MIGRATIONS.get(f"{current}->{target_version}")

    def run_migration(self, target: str, dry_run: bool = False, backup: bool = False,
                      auto_fix: bool = False, yes: bool = False) -> MigrationResult:
        """Run a migration to target version."""
        current = self.detect_current_version()
        migration = self.get_migration(target)

        if not migration:
            return MigrationResult(
                success=False,
                from_version=current,
                to_version=target,
                errors=[f"No migration path from {current} to {target}"]
            )

        if migration.destructive and not yes and self.confirm_destructive:
            print(f"⚠️  WARNING: Migration {current} → {target} is DESTRUCTIVE")
            response = input("Continue? [y/N]: ")
            if response.lower() != 'y':
                return MigrationResult(success=False, from_version=current, to_version=target,
                                       errors=["Migration cancelled by user"])

        result = MigrationResult(success=True, from_version=current, to_version=target)
        start_time = datetime.utcnow()

        try:
            if backup or self.auto_backup:
                backup_id = self.create_backup()
                result.backup_id = backup_id
                result.changes.append(f"Created backup: {backup_id}")

            if dry_run:
                result.changes.append("DRY RUN - No changes applied")
                result.changes.append(f"Would migrate: {current} → {target}")
                return result

            if migration.script:
                script_path = self.project_dir / migration.script
                if script_path.exists():
                    subprocess.run([sys.executable, str(script_path)], check=True)
                    result.changes.append(f"Executed: {migration.script}")

            self._update_version(target)
            result.changes.append(f"Updated VERSION to {target}")

        except Exception as e:
            result.success = False
            result.errors.append(str(e))

        result.duration_seconds = (datetime.utcnow() - start_time).total_seconds()
        return result

    def create_backup(self) -> str:
        """Create a backup of current state."""
        backup_id = f"backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        backup_path = self.backup_dir / backup_id
        backup_path.mkdir(parents=True, exist_ok=True)

        for file in ["VERSION", "config.yaml", ".ai/nav_map.json", ".github/README_META.yaml"]:
            src = self.project_dir / file
            dst = backup_path / file
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        return backup_id

    def rollback(self, backup_id: str) -> bool:
        """Rollback to a previous backup."""
        backup_path = self.backup_dir / backup_id
        if not backup_path.exists():
            return False

        for item in backup_path.iterdir():
            dst = self.project_dir / item.name
            if dst.exists():
                dst.unlink()
            shutil.copy2(item, dst)
        return True

    def _update_version(self, version: str) -> None:
        """Update VERSION file."""
        version_file = self.project_dir / "VERSION"
        content = version_file.read_text()
        lines = content.split('\n')
        lines[0] = version
        version_file.write_text('\n'.join(lines))


def main():
    """Main entry point for titan migrate CLI."""
    parser = argparse.ArgumentParser(prog='titan migrate', description='TITAN Protocol Migration CLI')
    parser.add_argument('target', nargs='?', help='Target version')
    parser.add_argument('--list', '-l', action='store_true', help='List available migrations')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without applying')
    parser.add_argument('--backup', action='store_true', help='Create backup before migration')
    parser.add_argument('--auto-fix', action='store_true', help='Attempt automatic fixes')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompts')
    parser.add_argument('--rollback', metavar='BACKUP_ID', help='Rollback to backup')
    parser.add_argument('--project-dir', type=Path, default=Path("."), help='Project directory')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    cli = TitanMigrateCLI(project_dir=args.project_dir)

    if args.list:
        current = cli.detect_current_version()
        migrations = cli.list_available_migrations()
        print(f"Current version: {current}")
        print(f"Available migrations: {len(migrations)}")
        for m in migrations:
            flags = []
            if m.destructive:
                flags.append("DESTRUCTIVE")
            if not m.reversible:
                flags.append("IRREVERSIBLE")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            print(f"  {m.from_version} → {m.to_version}: {m.description}{flag_str}")
        return 0

    if args.rollback:
        if cli.rollback(args.rollback):
            print(f"✅ Rolled back to {args.rollback}")
            return 0
        print(f"❌ Rollback failed")
        return 1

    if args.target:
        result = cli.run_migration(args.target, args.dry_run, args.backup, args.auto_fix, args.yes)
        if result.success:
            print(f"✅ Migration successful: {result.from_version} → {result.to_version}")
            for change in result.changes:
                print(f"  - {change}")
            return 0
        else:
            print(f"❌ Migration failed")
            for error in result.errors:
                print(f"  Error: {error}")
            return 1

    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
