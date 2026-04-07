#!/usr/bin/env python3
"""
Checkpoint Migration Script for TITAN FUSE Protocol.

ITEM-SEC-02 Implementation:
- Migrate existing pickle checkpoints to JSON_ZSTD format
- Preserve all checkpoint data
- Create backup of original files
- Support batch migration

Usage:
    python scripts/migrate_checkpoints.py [--backup-dir ./backup] [--dry-run]

Author: TITAN FUSE Team
Version: 3.3.0
"""

import argparse
import json
import pickle
import gzip
import hashlib
import shutil
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import zstandard
try:
    import zstandard as zstd
    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False
    logger.warning("zstandard not available. Install with: pip install zstandard")


def detect_checkpoint_format(path: Path) -> str:
    """
    Detect the format of a checkpoint file.
    
    Args:
        path: Path to checkpoint file
        
    Returns:
        Format string: 'pickle', 'json', 'gzip', 'zstd', or 'unknown'
    """
    if not path.exists():
        return 'not_found'
    
    suffix = path.suffix.lower()
    
    # Check by extension first
    if suffix == '.pkl':
        return 'pickle'
    elif suffix == '.zst':
        return 'zstd'
    elif suffix == '.gz':
        return 'gzip'
    elif suffix == '.json':
        return 'json'
    
    # Try to detect by content
    try:
        with open(path, 'rb') as f:
            header = f.read(20)
            
        # Pickle files start with specific markers
        if header.startswith(b'\x80') or header.startswith(b'(lp'):
            return 'pickle'
        
        # gzip files have magic number
        if header[:2] == b'\x1f\x8b':
            return 'gzip'
        
        # zstd has its own magic
        if header[:4] == b'\x28\xb5\x2f\xfd':
            return 'zstd'
        
        # JSON files start with { or [
        try:
            text_header = header.decode('utf-8').strip()
            if text_header.startswith('{') or text_header.startswith('['):
                return 'json'
        except:
            pass
            
    except Exception as e:
        logger.error(f"Error detecting format for {path}: {e}")
    
    return 'unknown'


def load_pickle_checkpoint(path: Path) -> Tuple[Dict, bool]:
    """
    Load a pickle checkpoint (UNSAFE - only for trusted files).
    
    Args:
        path: Path to pickle file
        
    Returns:
        Tuple of (data, success)
    """
    try:
        with open(path, 'rb') as f:
            data = pickle.load(f)
        return data, True
    except Exception as e:
        logger.error(f"Failed to load pickle checkpoint {path}: {e}")
        return {}, False


def load_json_checkpoint(path: Path) -> Tuple[Dict, bool]:
    """
    Load a JSON checkpoint.
    
    Args:
        path: Path to JSON file
        
    Returns:
        Tuple of (data, success)
    """
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        return data, True
    except Exception as e:
        logger.error(f"Failed to load JSON checkpoint {path}: {e}")
        return {}, False


def load_gzip_checkpoint(path: Path) -> Tuple[Dict, bool]:
    """
    Load a gzipped JSON checkpoint.
    
    Args:
        path: Path to gzip file
        
    Returns:
        Tuple of (data, success)
    """
    try:
        with gzip.open(path, 'rt') as f:
            data = json.load(f)
        return data, True
    except Exception as e:
        logger.error(f"Failed to load gzip checkpoint {path}: {e}")
        return {}, False


def load_zstd_checkpoint(path: Path) -> Tuple[Dict, bool]:
    """
    Load a Zstd-compressed JSON checkpoint.
    
    Args:
        path: Path to zst file
        
    Returns:
        Tuple of (data, success)
    """
    if not ZSTD_AVAILABLE:
        logger.error("zstandard not available for loading .zst files")
        return {}, False
    
    try:
        with open(path, 'rb') as f:
            compressed = f.read()
        
        dctx = zstd.ZstdDecompressor()
        decompressed = dctx.decompress(compressed)
        data = json.loads(decompressed.decode('utf-8'))
        return data, True
    except Exception as e:
        logger.error(f"Failed to load zstd checkpoint {path}: {e}")
        return {}, False


def save_json_zstd(data: Dict, path: Path) -> Tuple[bool, Dict]:
    """
    Save checkpoint as JSON with Zstd compression.
    
    Args:
        data: Checkpoint data
        path: Output path
        
    Returns:
        Tuple of (success, metadata)
    """
    if not ZSTD_AVAILABLE:
        # Fallback to plain JSON
        return save_json(data, path)
    
    try:
        # Add migration metadata
        data['_migration'] = {
            'migrated_at': datetime.utcnow().isoformat() + 'Z',
            'original_format': 'pickle',
            'new_format': 'json_zstd',
            'migration_version': '3.3.0'
        }
        
        # Serialize to JSON
        json_bytes = json.dumps(data, default=str, indent=2).encode('utf-8')
        original_size = len(json_bytes)
        
        # Compress with zstd
        cctx = zstd.ZstdCompressor(level=3)
        compressed = cctx.compress(json_bytes)
        
        # Write to file
        output_path = path.with_suffix('.json.zst')
        with open(output_path, 'wb') as f:
            f.write(compressed)
        
        checksum = hashlib.sha256(compressed).hexdigest()[:16]
        
        metadata = {
            'output_path': str(output_path),
            'original_size': original_size,
            'compressed_size': len(compressed),
            'compression_ratio': len(compressed) / original_size if original_size > 0 else 1.0,
            'checksum': checksum
        }
        
        return True, metadata
        
    except Exception as e:
        logger.error(f"Failed to save zstd checkpoint {path}: {e}")
        return False, {'error': str(e)}


def save_json(data: Dict, path: Path) -> Tuple[bool, Dict]:
    """
    Save checkpoint as plain JSON (fallback when zstd unavailable).
    
    Args:
        data: Checkpoint data
        path: Output path
        
    Returns:
        Tuple of (success, metadata)
    """
    try:
        # Add migration metadata
        data['_migration'] = {
            'migrated_at': datetime.utcnow().isoformat() + 'Z',
            'original_format': 'pickle',
            'new_format': 'json',
            'migration_version': '3.3.0'
        }
        
        output_path = path.with_suffix('.json')
        
        json_str = json.dumps(data, default=str, indent=2)
        json_bytes = json_str.encode('utf-8')
        
        with open(output_path, 'w') as f:
            f.write(json_str)
        
        checksum = hashlib.sha256(json_bytes).hexdigest()[:16]
        
        metadata = {
            'output_path': str(output_path),
            'size': len(json_bytes),
            'checksum': checksum
        }
        
        return True, metadata
        
    except Exception as e:
        logger.error(f"Failed to save JSON checkpoint {path}: {e}")
        return False, {'error': str(e)}


def create_backup(path: Path, backup_dir: Path) -> Optional[Path]:
    """
    Create backup of original checkpoint file.
    
    Args:
        path: Path to original file
        backup_dir: Backup directory
        
    Returns:
        Path to backup file or None on failure
    """
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Create backup with timestamp
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{path.stem}_{timestamp}{path.suffix}"
        backup_path = backup_dir / backup_name
        
        shutil.copy2(path, backup_path)
        logger.info(f"Created backup: {backup_path}")
        
        return backup_path
        
    except Exception as e:
        logger.error(f"Failed to create backup for {path}: {e}")
        return None


def scan_for_checkpoints(root_dir: Path) -> List[Path]:
    """
    Scan directory for checkpoint files.
    
    Args:
        root_dir: Root directory to scan
        
    Returns:
        List of checkpoint file paths
    """
    checkpoints = []
    
    patterns = ['**/checkpoint*.pkl', '**/checkpoint*.pickle', 
                '**/checkpoint*.json', '**/checkpoint*.gz',
                '**/checkpoint*.zst', '**/*.checkpoint']
    
    for pattern in patterns:
        checkpoints.extend(root_dir.glob(pattern))
    
    # Also check specific locations
    specific_paths = [
        root_dir / 'checkpoints' / 'checkpoint.pkl',
        root_dir / 'checkpoints' / 'checkpoint.json',
        root_dir / 'checkpoints' / 'checkpoint',
        root_dir / 'sessions' / 'current.pkl',
    ]
    
    for path in specific_paths:
        if path.exists() and path not in checkpoints:
            checkpoints.append(path)
    
    return sorted(set(checkpoints))


def migrate_checkpoint(source: Path, backup_dir: Path, dry_run: bool = False) -> Dict:
    """
    Migrate a single checkpoint file.
    
    Args:
        source: Path to checkpoint file
        backup_dir: Backup directory
        dry_run: If True, don't actually migrate
        
    Returns:
        Migration result dictionary
    """
    result = {
        'source': str(source),
        'format': detect_checkpoint_format(source),
        'success': False,
        'backup_path': None,
        'output_path': None,
        'error': None
    }
    
    # Skip if already in safe format
    if result['format'] in ['zstd', 'json']:
        result['success'] = True
        result['output_path'] = str(source)
        result['note'] = f"Already in safe format: {result['format']}"
        return result
    
    # Load checkpoint data
    data = {}
    load_success = False
    
    if result['format'] == 'pickle':
        data, load_success = load_pickle_checkpoint(source)
    elif result['format'] == 'gzip':
        data, load_success = load_gzip_checkpoint(source)
    elif result['format'] == 'json':
        data, load_success = load_json_checkpoint(source)
    else:
        result['error'] = f"Unknown format: {result['format']}"
        return result
    
    if not load_success:
        result['error'] = "Failed to load checkpoint data"
        return result
    
    if dry_run:
        result['success'] = True
        result['note'] = "DRY RUN - would migrate"
        return result
    
    # Create backup
    backup_path = create_backup(source, backup_dir)
    if backup_path:
        result['backup_path'] = str(backup_path)
    
    # Save in new format
    success, metadata = save_json_zstd(data, source)
    if success:
        result['success'] = True
        result['output_path'] = metadata.get('output_path')
        result['compression_ratio'] = metadata.get('compression_ratio')
    else:
        result['error'] = metadata.get('error', 'Unknown error')
    
    return result


def main():
    """Main entry point for checkpoint migration."""
    parser = argparse.ArgumentParser(
        description='Migrate TITAN checkpoints from pickle to JSON_ZSTD format'
    )
    parser.add_argument(
        '--root-dir', '-r',
        type=Path,
        default=Path.cwd(),
        help='Root directory to scan for checkpoints (default: current directory)'
    )
    parser.add_argument(
        '--backup-dir', '-b',
        type=Path,
        default=None,
        help='Directory for backup files (default: ./checkpoint_backup)'
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--keep-original',
        action='store_true',
        help='Keep original files after migration'
    )
    
    args = parser.parse_args()
    
    # Setup backup directory
    backup_dir = args.backup_dir or (args.root_dir / 'checkpoint_backup')
    
    # Scan for checkpoints
    logger.info(f"Scanning for checkpoints in: {args.root_dir}")
    checkpoints = scan_for_checkpoints(args.root_dir)
    
    if not checkpoints:
        logger.info("No checkpoint files found")
        return 0
    
    logger.info(f"Found {len(checkpoints)} checkpoint file(s)")
    
    # Migrate each checkpoint
    results = []
    success_count = 0
    
    for checkpoint_path in checkpoints:
        logger.info(f"\nProcessing: {checkpoint_path}")
        result = migrate_checkpoint(checkpoint_path, backup_dir, args.dry_run)
        results.append(result)
        
        if result['success']:
            success_count += 1
            logger.info(f"  ✓ Migrated successfully")
            if result.get('output_path'):
                logger.info(f"  Output: {result['output_path']}")
        else:
            logger.error(f"  ✗ Migration failed: {result.get('error')}")
    
    # Summary
    print("\n" + "=" * 50)
    print("MIGRATION SUMMARY")
    print("=" * 50)
    print(f"Total checkpoints: {len(checkpoints)}")
    print(f"Successfully migrated: {success_count}")
    print(f"Failed: {len(checkpoints) - success_count}")
    
    if args.dry_run:
        print("\n[DRY RUN] No files were modified")
    
    # Save migration report
    report_path = backup_dir / 'migration_report.json'
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    with open(report_path, 'w') as f:
        json.dump({
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'root_dir': str(args.root_dir),
            'dry_run': args.dry_run,
            'total': len(checkpoints),
            'success': success_count,
            'results': results
        }, f, indent=2)
    
    logger.info(f"\nMigration report saved to: {report_path}")
    
    return 0 if success_count == len(checkpoints) else 1


if __name__ == '__main__':
    sys.exit(main())
