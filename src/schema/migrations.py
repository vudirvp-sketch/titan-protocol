"""
Schema migration framework for TITAN Protocol checkpoints.

Migrations are applied in order when checkpoint schema_version < current.
"""

from typing import Dict, List, Callable

# Current schema version
CURRENT_SCHEMA_VERSION = "3.2.2"

# Migration registry: version -> migration function
MIGRATIONS: Dict[str, Callable] = {}


def migration(from_version: str):
    """Decorator to register a migration."""
    def decorator(func: Callable):
        MIGRATIONS[from_version] = func
        return func
    return decorator


@migration("3.2.0")
def migrate_320_to_321(checkpoint: Dict) -> Dict:
    """Migrate from 3.2.0 to 3.2.1."""
    # Add cursor_state if missing
    if "cursor_state" not in checkpoint:
        checkpoint["cursor_state"] = {
            "current_file": checkpoint.get("source_file"),
            "current_line": 0,
            "current_chunk": None,
            "current_section": None,
            "offset_delta": 0
        }
    
    # Add issue_dependency_graph
    if "issue_dependency_graph" not in checkpoint:
        checkpoint["issue_dependency_graph"] = {}
    
    # Add crossref_report
    if "crossref_report" not in checkpoint:
        checkpoint["crossref_report"] = {
            "total_references": 0,
            "resolved": 0,
            "broken": 0
        }
    
    checkpoint["protocol_version"] = "3.2.1"
    return checkpoint


@migration("3.2.1")
def migrate_321_to_322(checkpoint: Dict) -> Dict:
    """Migrate from 3.2.1 to 3.2.2."""
    # Add readiness_tier
    if "readiness_tier" not in checkpoint:
        checkpoint["readiness_tier"] = "TIER_1_COMPLETE"
    
    # Add gap_objects list
    if "gap_objects" not in checkpoint:
        # Convert string gaps to objects
        gap_objects = []
        for gap_str in checkpoint.get("known_gaps", []):
            gap_objects.append({
                "id": f"GAP-{len(gap_objects)+1}",
                "raw": gap_str,
                "severity": _extract_severity(gap_str),
                "reason": _extract_reason(gap_str),
                "verified": False
            })
        checkpoint["gap_objects"] = gap_objects
    
    # Add checkpoint intervals
    if "checkpoint_interval_tokens" not in checkpoint:
        checkpoint["checkpoint_interval_tokens"] = 5000
    if "checkpoint_interval_seconds" not in checkpoint:
        checkpoint["checkpoint_interval_seconds"] = 60
    if "last_checkpoint_time" not in checkpoint:
        checkpoint["last_checkpoint_time"] = 0.0
    if "tokens_since_checkpoint" not in checkpoint:
        checkpoint["tokens_since_checkpoint"] = 0
    
    # Increase max_recursion_depth default
    if checkpoint.get("max_recursion_depth", 1) == 1:
        checkpoint["max_recursion_depth"] = 3
    
    checkpoint["protocol_version"] = "3.2.2"
    return checkpoint


def _extract_severity(gap_str: str) -> str:
    """Extract severity from gap string."""
    import re
    match = re.search(r'SEV-(\d)', gap_str)
    return f"SEV-{match.group(1)}" if match else "SEV-4"


def _extract_reason(gap_str: str) -> str:
    """Extract reason from gap string."""
    import re
    match = re.search(r'\[gap:\s*([^\]]+)\]', gap_str)
    return match.group(1) if match else gap_str


def apply_migrations(checkpoint: Dict, target_version: str = CURRENT_SCHEMA_VERSION) -> Dict:
    """Apply all migrations up to target version."""
    current = checkpoint.get("protocol_version", "3.2.0")
    
    # Define migration order
    version_order = ["3.2.0", "3.2.1", "3.2.2"]
    
    start_idx = version_order.index(current) if current in version_order else 0
    end_idx = version_order.index(target_version) if target_version in version_order else len(version_order)
    
    for i in range(start_idx, end_idx):
        from_ver = version_order[i]
        if from_ver in MIGRATIONS:
            checkpoint = MIGRATIONS[from_ver](checkpoint)
            print(f"Applied migration: {from_ver} → {checkpoint['protocol_version']}")
    
    return checkpoint
