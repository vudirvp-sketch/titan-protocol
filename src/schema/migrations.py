"""
Schema migration framework for TITAN Protocol checkpoints.

Migrations are applied in order when checkpoint schema_version < current.

ITEM-OBS-03: Added metrics schema migration support.
"""

from typing import Dict, List, Callable

# Current schema version
CURRENT_SCHEMA_VERSION = "3.4.0"

# Current metrics schema version (ITEM-OBS-03)
CURRENT_METRICS_SCHEMA_VERSION = "3.4.0"

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


@migration("3.2.2")
def migrate_322_to_340(checkpoint: Dict) -> Dict:
    """Migrate from 3.2.2 to 3.4.0."""
    # ITEM-ARCH-15: Add model version fingerprint fields
    if "model_version_fingerprint" not in checkpoint:
        checkpoint["model_version_fingerprint"] = None
    if "root_model_fingerprint" not in checkpoint:
        checkpoint["root_model_fingerprint"] = None
    if "leaf_model_fingerprint" not in checkpoint:
        checkpoint["leaf_model_fingerprint"] = None

    checkpoint["protocol_version"] = "3.4.0"
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
    version_order = ["3.2.0", "3.2.1", "3.2.2", "3.4.0"]

    start_idx = version_order.index(current) if current in version_order else 0
    end_idx = version_order.index(target_version) if target_version in version_order else len(version_order)

    for i in range(start_idx, end_idx):
        from_ver = version_order[i]
        if from_ver in MIGRATIONS:
            checkpoint = MIGRATIONS[from_ver](checkpoint)
            print(f"Applied migration: {from_ver} → {checkpoint['protocol_version']}")

    return checkpoint


# ITEM-OBS-03: Metrics migration functions
def migrate_metrics(data: Dict, from_version: str) -> Dict:
    """
    ITEM-OBS-03: Migrate metrics data to current schema version.

    Args:
        data: Metrics data dictionary
        from_version: Version of the input data

    Returns:
        Metrics data at current schema version
    """
    if from_version in ["unknown", "3.2.0", "3.3.0"]:
        data = _migrate_metrics_v32_to_v34(data)

    data["schema_version"] = CURRENT_METRICS_SCHEMA_VERSION
    return data


def _migrate_metrics_v32_to_v34(data: Dict) -> Dict:
    """
    Migrate metrics from v3.2.x format to v3.4.0.

    Changes:
    - Add schema_version field
    - Ensure all metric values have proper structure
    - Add namespace if missing
    """
    # Ensure namespace exists
    if "namespace" not in data:
        data["namespace"] = "titan"

    # Ensure timestamp exists
    if "timestamp" not in data:
        from datetime import datetime
        data["timestamp"] = datetime.utcnow().isoformat() + "Z"

    # Migrate counters structure if needed
    if "counters" in data:
        migrated_counters = {}
        for name, values in data["counters"].items():
            if isinstance(values, list):
                migrated_counters[name] = values
            elif isinstance(values, dict):
                # Old format: single value
                migrated_counters[name] = [{
                    "value": values.get("value", 0),
                    "timestamp": values.get("timestamp", data.get("timestamp")),
                    "labels": values.get("labels", {})
                }]
        data["counters"] = migrated_counters

    # Migrate gauges structure if needed
    if "gauges" in data:
        migrated_gauges = {}
        for name, values in data["gauges"].items():
            if isinstance(values, list):
                migrated_gauges[name] = values
            elif isinstance(values, dict):
                migrated_gauges[name] = [{
                    "value": values.get("value", 0),
                    "timestamp": values.get("timestamp", data.get("timestamp")),
                    "labels": values.get("labels", {})
                }]
        data["gauges"] = migrated_gauges

    # Migrate histograms structure if needed
    if "histograms" in data:
        for name, hist_data in data["histograms"].items():
            if isinstance(hist_data, dict):
                # Ensure required fields
                if "sum" not in hist_data:
                    hist_data["sum"] = 0.0
                if "count" not in hist_data:
                    hist_data["count"] = 0
                if "average" not in hist_data:
                    count = hist_data.get("count", 0)
                    total = hist_data.get("sum", 0.0)
                    hist_data["average"] = total / count if count > 0 else 0.0

    return data
