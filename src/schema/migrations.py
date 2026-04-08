"""
Schema migration framework for TITAN Protocol checkpoints.

Migrations are applied in order when checkpoint schema_version < current.

ITEM-OBS-03: Added metrics schema migration support.
ITEM-OPS-79: Added v4.0.0, v4.1.0, v5.0.0 migrations.
"""

from typing import Dict, List, Callable

# Current schema version
CURRENT_SCHEMA_VERSION = "5.0.0"

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


@migration("3.4.0")
def migrate_340_to_400(checkpoint: Dict) -> Dict:
    """
    Migrate from 3.4.0 to 4.0.0.
    
    ITEM-OPS-79: Add TIER_7 architecture fields.
    
    Changes:
    - Add tier_7_fields dict for extended tier support
    - Add token_attribution for multi-model tracking
    - Add realtime_metrics config
    - Add provider_registry_config for LLM provider management
    - Add event_sourcing_enabled flag
    - Add deterministic_seed_config for reproducibility
    """
    # Add TIER_7 fields container
    if "tier_7_fields" not in checkpoint:
        checkpoint["tier_7_fields"] = {
            "advanced_validation": {},
            "context_zones": {},
            "escalation_protocol": {}
        }
    
    # Add token attribution tracking
    if "token_attribution" not in checkpoint:
        checkpoint["token_attribution"] = {
            "total_tokens": 0,
            "by_model": {},
            "by_provider": {},
            "by_tier": {}
        }
    
    # Add realtime metrics configuration
    if "realtime_metrics" not in checkpoint:
        checkpoint["realtime_metrics"] = {
            "enabled": True,
            "collection_interval_ms": 100,
            "aggregation_window_seconds": 60,
            "export_enabled": False
        }
    
    # Add provider registry configuration
    if "provider_registry_config" not in checkpoint:
        checkpoint["provider_registry_config"] = {
            "default_provider": None,
            "fallback_chain": [],
            "health_check_interval_seconds": 30,
            "retry_policy": {
                "max_retries": 3,
                "backoff_multiplier": 2.0,
                "initial_delay_ms": 100
            }
        }
    
    # Add event sourcing flag
    if "event_sourcing_enabled" not in checkpoint:
        checkpoint["event_sourcing_enabled"] = True
    
    # Add deterministic seed configuration
    if "deterministic_seed_config" not in checkpoint:
        checkpoint["deterministic_seed_config"] = {
            "enabled": False,
            "seed_value": None,
            "propagate_to_children": True
        }
    
    # Add multi-agent orchestration support
    if "multi_agent_config" not in checkpoint:
        checkpoint["multi_agent_config"] = {
            "enabled": False,
            "max_parallel_agents": 5,
            "coordination_strategy": "sequential"
        }
    
    checkpoint["protocol_version"] = "4.0.0"
    return checkpoint


@migration("4.0.0")
def migrate_400_to_410(checkpoint: Dict) -> Dict:
    """
    Migrate from 4.0.0 to 4.1.0.
    
    ITEM-OPS-79: Add v4.1.0 architecture enhancements.
    
    Changes:
    - Add validation_tiering config
    - Add context_zones config
    - Add escalation_protocol config
    - Add adaptive_budgeting config
    - Enhance tier_7_fields with new structures
    """
    # Add validation tiering configuration
    if "validation_tiering" not in checkpoint:
        checkpoint["validation_tiering"] = {
            "enabled": True,
            "tiers": {
                "tier_1": {"validators": ["schema"], "required": True},
                "tier_2": {"validators": ["semantic"], "required": False},
                "tier_3": {"validators": ["security"], "required": True},
                "tier_4": {"validators": ["performance"], "required": False},
                "tier_5": {"validators": ["compliance"], "required": True},
                "tier_6": {"validators": ["consistency"], "required": False},
                "tier_7": {"validators": ["advanced"], "required": False}
            },
            "parallel_execution": True
        }
    
    # Add context zones configuration
    if "context_zones" not in checkpoint:
        checkpoint["context_zones"] = {
            "enabled": True,
            "zones": {
                "global": {"max_tokens": 100000, "priority": 1},
                "session": {"max_tokens": 50000, "priority": 2},
                "local": {"max_tokens": 10000, "priority": 3}
            },
            "eviction_policy": "lru"
        }
    
    # Add escalation protocol configuration
    if "escalation_protocol" not in checkpoint:
        checkpoint["escalation_protocol"] = {
            "enabled": True,
            "escalation_levels": [
                {"level": 1, "action": "retry", "max_attempts": 3},
                {"level": 2, "action": "fallback_provider", "max_attempts": 2},
                {"level": 3, "action": "reduce_scope", "max_attempts": 1},
                {"level": 4, "action": "abort", "max_attempts": 0}
            ],
            "auto_escalate": True
        }
    
    # Add adaptive budgeting configuration
    if "adaptive_budgeting" not in checkpoint:
        checkpoint["adaptive_budgeting"] = {
            "enabled": True,
            "base_budget_tokens": 100000,
            "max_budget_tokens": 500000,
            "adjustment_factor": 1.2,
            "learning_rate": 0.1,
            "history_window": 10
        }
    
    # Enhance tier_7_fields if present (idempotent)
    if "tier_7_fields" in checkpoint:
        tier_7 = checkpoint["tier_7_fields"]
        if "advanced_validation" not in tier_7:
            tier_7["advanced_validation"] = {}
        if "context_zones" not in tier_7:
            tier_7["context_zones"] = {}
        if "escalation_protocol" not in tier_7:
            tier_7["escalation_protocol"] = {}
        # Add new v4.1.0 structures
        if "budget_forecast" not in tier_7:
            tier_7["budget_forecast"] = {
                "predicted_usage": 0,
                "confidence_interval": 0.95
            }
        if "causal_ordering" not in tier_7:
            tier_7["causal_ordering"] = {
                "enabled": True,
                "dependency_graph": {}
            }
    
    checkpoint["protocol_version"] = "4.1.0"
    return checkpoint


@migration("4.1.0")
def migrate_410_to_500(checkpoint: Dict) -> Dict:
    """
    Migrate from 4.1.0 to 5.0.0.
    
    ITEM-OPS-79: Major version upgrade to v5.0.0.
    
    Changes:
    - Add context_zones_config dict
    - Add checkpoint_compression enhancements
    - Add distributed tracing support
    - Add policy staging configuration
    - Add sandbox health monitoring
    - Add doctor rules configuration
    """
    # Add context zones configuration (enhanced from v4.1.0)
    if "context_zones_config" not in checkpoint:
        checkpoint["context_zones_config"] = {
            "version": "5.0.0",
            "zones": {
                "immediate": {"max_tokens": 5000, "ttl_seconds": 300},
                "working": {"max_tokens": 20000, "ttl_seconds": 3600},
                "reference": {"max_tokens": 50000, "ttl_seconds": 86400},
                "archival": {"max_tokens": 100000, "ttl_seconds": 604800}
            },
            "zone_transitions": {
                "auto_promote": True,
                "auto_demote": True,
                "promotion_threshold": 0.8,
                "demotion_threshold": 0.2
            }
        }
    
    # Add checkpoint compression configuration
    if "checkpoint_compression" not in checkpoint:
        checkpoint["checkpoint_compression"] = {
            "enabled": True,
            "algorithm": "zstd",
            "level": 3,
            "min_size_bytes": 1024,
            "compress_history": True,
            "history_retention_count": 5
        }
    else:
        # Enhance existing compression config (idempotent)
        comp = checkpoint["checkpoint_compression"]
        if "compress_history" not in comp:
            comp["compress_history"] = True
        if "history_retention_count" not in comp:
            comp["history_retention_count"] = 5
    
    # Add distributed tracing configuration
    if "distributed_tracing" not in checkpoint:
        checkpoint["distributed_tracing"] = {
            "enabled": True,
            "sampling_rate": 1.0,
            "export_format": "otlp",
            "service_name": "titan-protocol",
            "propagation_format": "w3c"
        }
    
    # Add policy staging configuration
    if "policy_staging" not in checkpoint:
        checkpoint["policy_staging"] = {
            "enabled": True,
            "staging_area": "staging/policies",
            "validation_required": True,
            "auto_promote": False,
            "retention_days": 30
        }
    
    # Add sandbox health monitoring configuration
    if "sandbox_health" not in checkpoint:
        checkpoint["sandbox_health"] = {
            "enabled": True,
            "health_check_interval_seconds": 60,
            "metrics": {
                "memory_threshold_mb": 1024,
                "cpu_threshold_percent": 80,
                "disk_threshold_percent": 90
            },
            "alert_on_degradation": True
        }
    
    # Add doctor rules configuration
    if "doctor_rules" not in checkpoint:
        checkpoint["doctor_rules"] = {
            "enabled": True,
            "rules": {
                "checkpointer_health": {"severity": "critical", "auto_fix": True},
                "token_budget": {"severity": "warning", "auto_fix": False},
                "recursion_depth": {"severity": "warning", "auto_fix": True},
                "gap_detection": {"severity": "info", "auto_fix": False}
            },
            "run_on_startup": True
        }
    
    # Add workspace isolation configuration
    if "workspace_isolation" not in checkpoint:
        checkpoint["workspace_isolation"] = {
            "enabled": True,
            "isolation_level": "namespace",
            "shared_resources": ["models", "providers"],
            "cross_workspace_communication": False
        }
    
    # Add streaming support configuration
    if "streaming_config" not in checkpoint:
        checkpoint["streaming_config"] = {
            "enabled": True,
            "chunk_size": 4096,
            "buffer_size": 65536,
            "timeout_seconds": 30,
            "retry_on_failure": True
        }
    
    # Enhance tier_7_fields with v5.0.0 structures (idempotent)
    if "tier_7_fields" in checkpoint:
        tier_7 = checkpoint["tier_7_fields"]
        if "streaming_state" not in tier_7:
            tier_7["streaming_state"] = {
                "active_streams": 0,
                "bytes_transferred": 0
            }
        if "distributed_state" not in tier_7:
            tier_7["distributed_state"] = {
                "node_id": None,
                "cluster_size": 1
            }
    
    checkpoint["protocol_version"] = "5.0.0"
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
    """
    Apply all migrations up to target version.
    
    ITEM-OPS-79: Updated to include v4.0.0, v4.1.0, v5.0.0 migrations.
    
    Args:
        checkpoint: Checkpoint dictionary to migrate
        target_version: Target schema version (default: CURRENT_SCHEMA_VERSION)
        
    Returns:
        Migrated checkpoint dictionary
        
    Note:
        All migrations are idempotent - safe to run multiple times.
    """
    current = checkpoint.get("protocol_version", "3.2.0")

    # Define migration order (ITEM-OPS-79: added v4.0.0, v4.1.0, v5.0.0)
    version_order = [
        "3.2.0", "3.2.1", "3.2.2", "3.4.0",
        "4.0.0", "4.1.0", "5.0.0"
    ]

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
