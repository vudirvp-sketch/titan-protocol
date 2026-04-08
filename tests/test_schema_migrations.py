"""
Tests for schema migration framework.

ITEM-OPS-79: Test coverage for v4.0.0, v4.1.0, v5.0.0 migrations.
"""

import pytest
from src.schema.migrations import (
    CURRENT_SCHEMA_VERSION,
    MIGRATIONS,
    apply_migrations,
    migrate_340_to_400,
    migrate_400_to_410,
    migrate_410_to_500,
    migrate_metrics,
    CURRENT_METRICS_SCHEMA_VERSION
)


class TestCurrentVersion:
    """Tests for current version constants."""
    
    def test_current_schema_version_is_5_0_0(self):
        """Verify CURRENT_SCHEMA_VERSION is set to 5.0.0."""
        assert CURRENT_SCHEMA_VERSION == "5.0.0", \
            f"Expected CURRENT_SCHEMA_VERSION to be '5.0.0', got '{CURRENT_SCHEMA_VERSION}'"
    
    def test_metrics_schema_version_defined(self):
        """Verify metrics schema version is defined."""
        assert CURRENT_METRICS_SCHEMA_VERSION is not None
        assert isinstance(CURRENT_METRICS_SCHEMA_VERSION, str)


class TestMigrationsRegistered:
    """Tests for migration registration."""
    
    def test_all_migrations_registered(self):
        """Verify all migrations are registered in MIGRATIONS dict."""
        expected_versions = ["3.2.0", "3.2.1", "3.2.2", "3.4.0", "4.0.0", "4.1.0"]
        for version in expected_versions:
            assert version in MIGRATIONS, \
                f"Migration for version {version} not registered"
    
    def test_migration_functions_callable(self):
        """Verify all migration functions are callable."""
        for version, func in MIGRATIONS.items():
            assert callable(func), \
                f"Migration for {version} is not callable"


class TestMigrate340To400:
    """Tests for v3.4.0 to v4.0.0 migration."""
    
    def test_adds_tier_7_fields(self):
        """Verify tier_7_fields is added."""
        checkpoint = {"protocol_version": "3.4.0"}
        result = migrate_340_to_400(checkpoint)
        
        assert "tier_7_fields" in result
        assert isinstance(result["tier_7_fields"], dict)
        assert "advanced_validation" in result["tier_7_fields"]
        assert "context_zones" in result["tier_7_fields"]
        assert "escalation_protocol" in result["tier_7_fields"]
    
    def test_adds_token_attribution(self):
        """Verify token_attribution is added."""
        checkpoint = {"protocol_version": "3.4.0"}
        result = migrate_340_to_400(checkpoint)
        
        assert "token_attribution" in result
        assert result["token_attribution"]["total_tokens"] == 0
        assert "by_model" in result["token_attribution"]
        assert "by_provider" in result["token_attribution"]
        assert "by_tier" in result["token_attribution"]
    
    def test_adds_realtime_metrics_config(self):
        """Verify realtime_metrics config is added."""
        checkpoint = {"protocol_version": "3.4.0"}
        result = migrate_340_to_400(checkpoint)
        
        assert "realtime_metrics" in result
        assert result["realtime_metrics"]["enabled"] is True
        assert "collection_interval_ms" in result["realtime_metrics"]
    
    def test_adds_provider_registry_config(self):
        """Verify provider_registry_config is added."""
        checkpoint = {"protocol_version": "3.4.0"}
        result = migrate_340_to_400(checkpoint)
        
        assert "provider_registry_config" in result
        assert "default_provider" in result["provider_registry_config"]
        assert "fallback_chain" in result["provider_registry_config"]
        assert "retry_policy" in result["provider_registry_config"]
    
    def test_adds_event_sourcing_flag(self):
        """Verify event_sourcing_enabled flag is added."""
        checkpoint = {"protocol_version": "3.4.0"}
        result = migrate_340_to_400(checkpoint)
        
        assert "event_sourcing_enabled" in result
        assert result["event_sourcing_enabled"] is True
    
    def test_adds_deterministic_seed_config(self):
        """Verify deterministic_seed_config is added."""
        checkpoint = {"protocol_version": "3.4.0"}
        result = migrate_340_to_400(checkpoint)
        
        assert "deterministic_seed_config" in result
        assert "enabled" in result["deterministic_seed_config"]
        assert "seed_value" in result["deterministic_seed_config"]
    
    def test_updates_protocol_version(self):
        """Verify protocol_version is updated to 4.0.0."""
        checkpoint = {"protocol_version": "3.4.0"}
        result = migrate_340_to_400(checkpoint)
        
        assert result["protocol_version"] == "4.0.0"
    
    def test_idempotent(self):
        """Verify migration is idempotent (safe to run multiple times)."""
        checkpoint = {"protocol_version": "3.4.0"}
        
        # Run migration twice
        result1 = migrate_340_to_400(checkpoint.copy())
        result2 = migrate_340_to_400(result1.copy())
        
        # Should not change the result
        assert result2["protocol_version"] == "4.0.0"
        assert result2 == result1


class TestMigrate400To410:
    """Tests for v4.0.0 to v4.1.0 migration."""
    
    def test_adds_validation_tiering(self):
        """Verify validation_tiering config is added."""
        checkpoint = {"protocol_version": "4.0.0"}
        result = migrate_400_to_410(checkpoint)
        
        assert "validation_tiering" in result
        assert result["validation_tiering"]["enabled"] is True
        assert "tiers" in result["validation_tiering"]
        assert "tier_1" in result["validation_tiering"]["tiers"]
        assert "tier_7" in result["validation_tiering"]["tiers"]
    
    def test_adds_context_zones(self):
        """Verify context_zones config is added."""
        checkpoint = {"protocol_version": "4.0.0"}
        result = migrate_400_to_410(checkpoint)
        
        assert "context_zones" in result
        assert result["context_zones"]["enabled"] is True
        assert "zones" in result["context_zones"]
        assert "global" in result["context_zones"]["zones"]
    
    def test_adds_escalation_protocol(self):
        """Verify escalation_protocol config is added."""
        checkpoint = {"protocol_version": "4.0.0"}
        result = migrate_400_to_410(checkpoint)
        
        assert "escalation_protocol" in result
        assert result["escalation_protocol"]["enabled"] is True
        assert "escalation_levels" in result["escalation_protocol"]
        assert len(result["escalation_protocol"]["escalation_levels"]) == 4
    
    def test_adds_adaptive_budgeting(self):
        """Verify adaptive_budgeting config is added."""
        checkpoint = {"protocol_version": "4.0.0"}
        result = migrate_400_to_410(checkpoint)
        
        assert "adaptive_budgeting" in result
        assert result["adaptive_budgeting"]["enabled"] is True
        assert "base_budget_tokens" in result["adaptive_budgeting"]
        assert "learning_rate" in result["adaptive_budgeting"]
    
    def test_enhances_tier_7_fields(self):
        """Verify tier_7_fields is enhanced with new structures."""
        checkpoint = {
            "protocol_version": "4.0.0",
            "tier_7_fields": {}
        }
        result = migrate_400_to_410(checkpoint)
        
        assert "budget_forecast" in result["tier_7_fields"]
        assert "causal_ordering" in result["tier_7_fields"]
    
    def test_updates_protocol_version(self):
        """Verify protocol_version is updated to 4.1.0."""
        checkpoint = {"protocol_version": "4.0.0"}
        result = migrate_400_to_410(checkpoint)
        
        assert result["protocol_version"] == "4.1.0"
    
    def test_idempotent(self):
        """Verify migration is idempotent."""
        checkpoint = {"protocol_version": "4.0.0", "tier_7_fields": {}}
        
        result1 = migrate_400_to_410(checkpoint.copy())
        result2 = migrate_400_to_410(result1.copy())
        
        assert result2["protocol_version"] == "4.1.0"
        assert result2 == result1


class TestMigrate410To500:
    """Tests for v4.1.0 to v5.0.0 migration."""
    
    def test_adds_context_zones_config(self):
        """Verify context_zones_config is added."""
        checkpoint = {"protocol_version": "4.1.0"}
        result = migrate_410_to_500(checkpoint)
        
        assert "context_zones_config" in result
        assert result["context_zones_config"]["version"] == "5.0.0"
        assert "zones" in result["context_zones_config"]
        assert "immediate" in result["context_zones_config"]["zones"]
        assert "working" in result["context_zones_config"]["zones"]
        assert "reference" in result["context_zones_config"]["zones"]
        assert "archival" in result["context_zones_config"]["zones"]
    
    def test_adds_checkpoint_compression(self):
        """Verify checkpoint_compression config is added."""
        checkpoint = {"protocol_version": "4.1.0"}
        result = migrate_410_to_500(checkpoint)
        
        assert "checkpoint_compression" in result
        assert result["checkpoint_compression"]["enabled"] is True
        assert result["checkpoint_compression"]["algorithm"] == "zstd"
        assert "compress_history" in result["checkpoint_compression"]
    
    def test_adds_distributed_tracing(self):
        """Verify distributed_tracing config is added."""
        checkpoint = {"protocol_version": "4.1.0"}
        result = migrate_410_to_500(checkpoint)
        
        assert "distributed_tracing" in result
        assert result["distributed_tracing"]["enabled"] is True
        assert "sampling_rate" in result["distributed_tracing"]
        assert "export_format" in result["distributed_tracing"]
    
    def test_adds_policy_staging(self):
        """Verify policy_staging config is added."""
        checkpoint = {"protocol_version": "4.1.0"}
        result = migrate_410_to_500(checkpoint)
        
        assert "policy_staging" in result
        assert result["policy_staging"]["enabled"] is True
        assert "staging_area" in result["policy_staging"]
    
    def test_adds_sandbox_health(self):
        """Verify sandbox_health config is added."""
        checkpoint = {"protocol_version": "4.1.0"}
        result = migrate_410_to_500(checkpoint)
        
        assert "sandbox_health" in result
        assert result["sandbox_health"]["enabled"] is True
        assert "metrics" in result["sandbox_health"]
    
    def test_adds_doctor_rules(self):
        """Verify doctor_rules config is added."""
        checkpoint = {"protocol_version": "4.1.0"}
        result = migrate_410_to_500(checkpoint)
        
        assert "doctor_rules" in result
        assert result["doctor_rules"]["enabled"] is True
        assert "rules" in result["doctor_rules"]
        assert "checkpointer_health" in result["doctor_rules"]["rules"]
    
    def test_adds_workspace_isolation(self):
        """Verify workspace_isolation config is added."""
        checkpoint = {"protocol_version": "4.1.0"}
        result = migrate_410_to_500(checkpoint)
        
        assert "workspace_isolation" in result
        assert result["workspace_isolation"]["enabled"] is True
        assert "isolation_level" in result["workspace_isolation"]
    
    def test_adds_streaming_config(self):
        """Verify streaming_config is added."""
        checkpoint = {"protocol_version": "4.1.0"}
        result = migrate_410_to_500(checkpoint)
        
        assert "streaming_config" in result
        assert result["streaming_config"]["enabled"] is True
        assert "chunk_size" in result["streaming_config"]
    
    def test_enhances_tier_7_fields(self):
        """Verify tier_7_fields is enhanced with v5.0.0 structures."""
        checkpoint = {
            "protocol_version": "4.1.0",
            "tier_7_fields": {}
        }
        result = migrate_410_to_500(checkpoint)
        
        assert "streaming_state" in result["tier_7_fields"]
        assert "distributed_state" in result["tier_7_fields"]
    
    def test_updates_protocol_version(self):
        """Verify protocol_version is updated to 5.0.0."""
        checkpoint = {"protocol_version": "4.1.0"}
        result = migrate_410_to_500(checkpoint)
        
        assert result["protocol_version"] == "5.0.0"
    
    def test_idempotent(self):
        """Verify migration is idempotent."""
        checkpoint = {"protocol_version": "4.1.0", "tier_7_fields": {}}
        
        result1 = migrate_410_to_500(checkpoint.copy())
        result2 = migrate_410_to_500(result1.copy())
        
        assert result2["protocol_version"] == "5.0.0"
        assert result2 == result1


class TestApplyMigrations:
    """Tests for apply_migrations function."""
    
    def test_migrates_from_320_to_500(self):
        """Verify full migration chain from 3.2.0 to 5.0.0."""
        checkpoint = {
            "protocol_version": "3.2.0",
            "source_file": "test.py"
        }
        
        result = apply_migrations(checkpoint)
        
        assert result["protocol_version"] == "5.0.0"
        # Verify key fields from each migration
        assert "cursor_state" in result  # from 3.2.0 -> 3.2.1
        assert "readiness_tier" in result  # from 3.2.1 -> 3.2.2
        assert "model_version_fingerprint" in result  # from 3.2.2 -> 3.4.0
        assert "tier_7_fields" in result  # from 3.4.0 -> 4.0.0
        assert "validation_tiering" in result  # from 4.0.0 -> 4.1.0
        assert "context_zones_config" in result  # from 4.1.0 -> 5.0.0
    
    def test_migrates_from_340_to_500(self):
        """Verify migration from 3.4.0 to 5.0.0."""
        checkpoint = {
            "protocol_version": "3.4.0",
            "model_version_fingerprint": "abc123"
        }
        
        result = apply_migrations(checkpoint)
        
        assert result["protocol_version"] == "5.0.0"
        assert result["model_version_fingerprint"] == "abc123"  # preserved
    
    def test_migrates_from_400_to_500(self):
        """Verify migration from 4.0.0 to 5.0.0."""
        checkpoint = {
            "protocol_version": "4.0.0",
            "tier_7_fields": {"existing": "data"}
        }
        
        result = apply_migrations(checkpoint)
        
        assert result["protocol_version"] == "5.0.0"
        assert result["tier_7_fields"]["existing"] == "data"  # preserved
    
    def test_migrates_from_410_to_500(self):
        """Verify migration from 4.1.0 to 5.0.0."""
        checkpoint = {
            "protocol_version": "4.1.0",
            "validation_tiering": {"enabled": True}
        }
        
        result = apply_migrations(checkpoint)
        
        assert result["protocol_version"] == "5.0.0"
        assert result["validation_tiering"]["enabled"] is True  # preserved
    
    def test_no_migration_needed_at_current_version(self):
        """Verify no migration when already at current version."""
        checkpoint = {
            "protocol_version": "5.0.0",
            "custom_field": "value"
        }
        
        result = apply_migrations(checkpoint)
        
        assert result["protocol_version"] == "5.0.0"
        assert result["custom_field"] == "value"
    
    def test_handles_unknown_version_gracefully(self):
        """Verify unknown version defaults to full migration chain."""
        checkpoint = {
            "protocol_version": "unknown"
        }
        
        result = apply_migrations(checkpoint)
        
        # Should start from beginning
        assert result["protocol_version"] == "5.0.0"
    
    def test_preserves_existing_data(self):
        """Verify existing checkpoint data is preserved during migration."""
        checkpoint = {
            "protocol_version": "3.4.0",
            "important_data": {
                "nested": {"values": [1, 2, 3]}
            },
            "known_gaps": ["gap1", "gap2"]
        }
        
        result = apply_migrations(checkpoint)
        
        assert result["important_data"]["nested"]["values"] == [1, 2, 3]
        assert result["known_gaps"] == ["gap1", "gap2"]


class TestMetricsMigration:
    """Tests for metrics schema migration."""
    
    def test_migrate_metrics_from_unknown_version(self):
        """Verify metrics migration from unknown version."""
        data = {
            "counters": {"requests": {"value": 100}}
        }
        
        result = migrate_metrics(data, "unknown")
        
        assert result["schema_version"] == CURRENT_METRICS_SCHEMA_VERSION
        assert "namespace" in result
        assert "timestamp" in result
    
    def test_migrate_metrics_adds_namespace(self):
        """Verify namespace is added if missing."""
        data = {"counters": {}}
        
        result = migrate_metrics(data, "3.2.0")
        
        assert result["namespace"] == "titan"
    
    def test_migrate_metrics_converts_old_counter_format(self):
        """Verify old counter format is converted."""
        data = {
            "counters": {
                "requests": {"value": 100, "timestamp": "2024-01-01T00:00:00Z"}
            }
        }
        
        result = migrate_metrics(data, "3.2.0")
        
        assert isinstance(result["counters"]["requests"], list)
        assert len(result["counters"]["requests"]) == 1
        assert result["counters"]["requests"][0]["value"] == 100


class TestBackwardCompatibility:
    """Tests for backward compatibility."""
    
    def test_v400_checkpoint_loadable(self):
        """Verify v4.0.0 checkpoint can be migrated and loaded."""
        v400_checkpoint = {
            "protocol_version": "4.0.0",
            "tier_7_fields": {"data": "exists"},
            "token_attribution": {"total_tokens": 5000}
        }
        
        result = apply_migrations(v400_checkpoint)
        
        assert result["protocol_version"] == "5.0.0"
        assert result["tier_7_fields"]["data"] == "exists"
        assert result["token_attribution"]["total_tokens"] == 5000
    
    def test_v410_checkpoint_loadable(self):
        """Verify v4.1.0 checkpoint can be migrated and loaded."""
        v410_checkpoint = {
            "protocol_version": "4.1.0",
            "validation_tiering": {"enabled": True, "custom": "config"},
            "adaptive_budgeting": {"base_budget_tokens": 200000}
        }
        
        result = apply_migrations(v410_checkpoint)
        
        assert result["protocol_version"] == "5.0.0"
        assert result["validation_tiering"]["custom"] == "config"
        assert result["adaptive_budgeting"]["base_budget_tokens"] == 200000
    
    def test_old_checkpoint_fields_preserved(self):
        """Verify old checkpoint fields are preserved through migration."""
        old_checkpoint = {
            "protocol_version": "3.2.0",
            "source_file": "old_source.py",
            "known_gaps": ["gap1", "gap2", "gap3"],
            "cursor_state": {"current_line": 42},
            "custom_user_data": {"important": "value"}
        }
        
        result = apply_migrations(old_checkpoint)
        
        assert result["source_file"] == "old_source.py"
        assert result["known_gaps"] == ["gap1", "gap2", "gap3"]
        assert result["cursor_state"]["current_line"] == 42
        assert result["custom_user_data"]["important"] == "value"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
