#!/usr/bin/env python3
"""
TITAN FUSE Protocol - Checkpoint Validation Tool
Version: 1.0.0
Purpose: Validates checkpoint.json files for integrity and resumability
"""

import json
import hashlib
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class ResumptionType(Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    FRESH = "FRESH"


class CheckpointStatus(Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    PARTIAL = "PARTIAL"
    STALE = "STALE"


@dataclass
class ValidationResult:
    status: CheckpointStatus
    resumption_type: ResumptionType
    issues: List[str]
    warnings: List[str]
    recoverable_chunks: List[str]
    lost_chunks: List[str]


def calculate_file_checksum(file_path: str) -> str:
    """Calculate SHA-256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def calculate_chunk_checksum(content: str) -> str:
    """Calculate SHA-256 checksum of a chunk."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def load_checkpoint(checkpoint_path: str) -> Optional[Dict]:
    """Load checkpoint from JSON file."""
    try:
        with open(checkpoint_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Checkpoint file not found: {checkpoint_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in checkpoint: {e}")
        return None


def validate_checkpoint_schema(checkpoint: Dict) -> Tuple[bool, List[str]]:
    """Validate checkpoint has required fields."""
    required_fields = [
        "session_id",
        "protocol_version",
        "source_file",
        "source_checksum",
        "gates_passed",
        "completed_batches",
        "timestamp"
    ]

    issues = []
    for field in required_fields:
        if field not in checkpoint:
            issues.append(f"Missing required field: {field}")

    # Validate field types
    if "gates_passed" in checkpoint and not isinstance(checkpoint["gates_passed"], list):
        issues.append("gates_passed must be a list")

    if "completed_batches" in checkpoint and not isinstance(checkpoint["completed_batches"], list):
        issues.append("completed_batches must be a list")

    return len(issues) == 0, issues


def validate_source_file(checkpoint: Dict, source_dir: str = ".") -> Tuple[bool, str, str]:
    """Validate source file exists and check checksum."""
    source_file = checkpoint.get("source_file", "")
    expected_checksum = checkpoint.get("source_checksum", "")

    # Resolve source path
    if not os.path.isabs(source_file):
        source_path = os.path.join(source_dir, source_file)
    else:
        source_path = source_file

    if not os.path.exists(source_path):
        return False, "", f"Source file not found: {source_path}"

    actual_checksum = calculate_file_checksum(source_path)
    checksum_match = actual_checksum == expected_checksum

    return checksum_match, actual_checksum, source_path


def determine_resumption_type(checkpoint: Dict, checksum_match: bool) -> ResumptionType:
    """Determine what type of resumption is possible."""
    if checksum_match:
        return ResumptionType.FULL

    # Check for chunk-level checksums
    if "chunk_checksums" in checkpoint:
        return ResumptionType.PARTIAL

    return ResumptionType.FRESH


def validate_chunk_checksums(checkpoint: Dict, source_path: str) -> Tuple[List[str], List[str]]:
    """Validate chunk-level checksums for partial resumption."""
    if "chunk_checksums" not in checkpoint:
        return [], []

    # This would require knowledge of how chunks were created
    # For now, return completed chunks as potentially recoverable
    completed = checkpoint.get("completed_chunks", [])
    return completed, []


def validate_checkpoint(checkpoint_path: str, source_dir: str = ".") -> ValidationResult:
    """Main validation function."""
    issues = []
    warnings = []
    recoverable_chunks = []
    lost_chunks = []

    # Load checkpoint
    checkpoint = load_checkpoint(checkpoint_path)
    if checkpoint is None:
        return ValidationResult(
            status=CheckpointStatus.INVALID,
            resumption_type=ResumptionType.FRESH,
            issues=["Failed to load checkpoint file"],
            warnings=[],
            recoverable_chunks=[],
            lost_chunks=[]
        )

    # Validate schema
    schema_valid, schema_issues = validate_checkpoint_schema(checkpoint)
    issues.extend(schema_issues)

    if not schema_valid:
        return ValidationResult(
            status=CheckpointStatus.INVALID,
            resumption_type=ResumptionType.FRESH,
            issues=issues,
            warnings=warnings,
            recoverable_chunks=[],
            lost_chunks=[]
        )

    # Validate source file
    checksum_match, actual_checksum, source_path = validate_source_file(checkpoint, source_dir)

    if not os.path.exists(source_path):
        issues.append(f"Source file not found: {source_path}")
    elif not checksum_match:
        warnings.append(f"Source file checksum mismatch")
        warnings.append(f"  Expected: {checkpoint.get('source_checksum', 'N/A')}")
        warnings.append(f"  Actual:   {actual_checksum}")

    # Determine resumption type
    resumption_type = determine_resumption_type(checkpoint, checksum_match)

    # Validate chunk checksums for partial resumption
    if resumption_type == ResumptionType.PARTIAL:
        recoverable, lost = validate_chunk_checksums(checkpoint, source_path)
        recoverable_chunks = recoverable
        lost_chunks = lost

    # Check timestamp
    if "timestamp" in checkpoint:
        try:
            ts = datetime.fromisoformat(checkpoint["timestamp"].replace('Z', '+00:00'))
            age = datetime.now(ts.tzinfo) - ts
            if age.days > 7:
                warnings.append(f"Checkpoint is {age.days} days old")
        except (ValueError, TypeError):
            warnings.append("Invalid timestamp format")

    # Determine overall status
    if len(issues) > 0:
        status = CheckpointStatus.INVALID
    elif not checksum_match and resumption_type == ResumptionType.FRESH:
        status = CheckpointStatus.STALE
    elif not checksum_match:
        status = CheckpointStatus.PARTIAL
    else:
        status = CheckpointStatus.VALID

    return ValidationResult(
        status=status,
        resumption_type=resumption_type,
        issues=issues,
        warnings=warnings,
        recoverable_chunks=recoverable_chunks,
        lost_chunks=lost_chunks
    )


def print_report(result: ValidationResult):
    """Print validation report."""
    print("\n" + "=" * 60)
    print("CHECKPOINT VALIDATION REPORT")
    print("=" * 60)

    # Status
    status_colors = {
        CheckpointStatus.VALID: "\033[92m",
        CheckpointStatus.PARTIAL: "\033[93m",
        CheckpointStatus.STALE: "\033[93m",
        CheckpointStatus.INVALID: "\033[91m"
    }
    color = status_colors.get(result.status, "")
    reset = "\033[0m"

    print(f"\nStatus: {color}{result.status.value}{reset}")
    print(f"Resumption Type: {result.resumption_type.value}")

    # Issues
    if result.issues:
        print(f"\n\033[91mIssues ({len(result.issues)}):\033[0m")
        for issue in result.issues:
            print(f"  - {issue}")

    # Warnings
    if result.warnings:
        print(f"\n\033[93mWarnings ({len(result.warnings)}):\033[0m")
        for warning in result.warnings:
            print(f"  - {warning}")

    # Chunk recovery info
    if result.recoverable_chunks:
        print(f"\n\033[92mRecoverable Chunks ({len(result.recoverable_chunks)}):\033[0m")
        for chunk in result.recoverable_chunks[:10]:  # Show first 10
            print(f"  - {chunk}")
        if len(result.recoverable_chunks) > 10:
            print(f"  ... and {len(result.recoverable_chunks) - 10} more")

    if result.lost_chunks:
        print(f"\n\033[91mLost Chunks ({len(result.lost_chunks)}):\033[0m")
        for chunk in result.lost_chunks[:10]:
            print(f"  - {chunk}")
        if len(result.lost_chunks) > 10:
            print(f"  ... and {len(result.lost_chunks) - 10} more")

    # Summary
    print("\n" + "-" * 60)
    if result.status == CheckpointStatus.VALID:
        print("Checkpoint is valid and can be fully resumed.")
    elif result.status == CheckpointStatus.PARTIAL:
        print("Checkpoint allows partial resumption. Some chunks may need reprocessing.")
    elif result.status == CheckpointStatus.STALE:
        print("Checkpoint is stale (source file changed). Fresh start required.")
    else:
        print("Checkpoint is invalid. Fresh start required.")
    print("-" * 60 + "\n")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python validate_checkpoint.py <checkpoint.json> [source_dir]")
        print("\nExample:")
        print("  python validate_checkpoint.py checkpoints/checkpoint.json")
        print("  python validate_checkpoint.py checkpoints/checkpoint.json inputs/")
        sys.exit(1)

    checkpoint_path = sys.argv[1]
    source_dir = sys.argv[2] if len(sys.argv) > 2 else "."

    print(f"Validating checkpoint: {checkpoint_path}")
    print(f"Source directory: {source_dir}")

    result = validate_checkpoint(checkpoint_path, source_dir)
    print_report(result)

    # Exit with appropriate code
    if result.status == CheckpointStatus.VALID:
        sys.exit(0)
    elif result.status == CheckpointStatus.PARTIAL:
        sys.exit(2)  # Partial success
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
