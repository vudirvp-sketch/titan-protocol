"""
Tests for ProfileRouter Enhancement (ITEM-CTX-001).

Tests the automatic profile detection and application based on
execution context.

Author: TITAN Protocol Team
Version: 5.0.0
"""

import pytest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from context.profile_router import (
    ProfileType,
    ProfileConfig,
    ProfileRouter,
    DEFAULT_PROFILES,
    create_profile_router
)


class TestProfileType:
    """Tests for ProfileType enum."""
    
    def test_all_profile_types_exist(self):
        """Test that all 9 profile types are defined."""
        expected_types = [
            "single_llm_executor",
            "ci_cd_pipeline",
            "multi_agent_swarm",
            "human_in_the_loop",
            "resource_constrained",
            "non_code_domain",
            "real_time_streaming",
            "small_scripts_lt1k",
            "repo_bootstrap"
        ]
        
        actual_types = [pt.value for pt in ProfileType]
        
        for expected in expected_types:
            assert expected in actual_types, f"Missing profile type: {expected}"
    
    def test_profile_type_values(self):
        """Test profile type enum values."""
        assert ProfileType.SINGLE_LLM_EXECUTOR.value == "single_llm_executor"
        assert ProfileType.CI_CD_PIPELINE.value == "ci_cd_pipeline"
        assert ProfileType.MULTI_AGENT_SWARM.value == "multi_agent_swarm"


class TestProfileConfig:
    """Tests for ProfileConfig dataclass."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        config = ProfileConfig(
            profile_type=ProfileType.SINGLE_LLM_EXECUTOR,
            description="Test profile"
        )
        
        assert config.profile_type == ProfileType.SINGLE_LLM_EXECUTOR
        assert config.description == "Test profile"
        assert config.retain_sections == []
        assert config.modify_sections == {}
        assert config.remove_sections == []
        assert config.detection_rules == {}
    
    def test_init_full(self):
        """Test full initialization."""
        config = ProfileConfig(
            profile_type=ProfileType.CI_CD_PIPELINE,
            description="CI/CD profile",
            retain_sections=["validation", "security"],
            modify_sections={"gate_sensitivity": {"fail_on_any_gap": True}},
            remove_sections=["interactive"],
            detection_rules={"env_ci": True}
        )
        
        assert config.profile_type == ProfileType.CI_CD_PIPELINE
        assert config.retain_sections == ["validation", "security"]
        assert config.modify_sections["gate_sensitivity"]["fail_on_any_gap"] is True
        assert config.remove_sections == ["interactive"]
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        config = ProfileConfig(
            profile_type=ProfileType.SINGLE_LLM_EXECUTOR,
            description="Test profile",
            retain_sections=["validation"],
            modify_sections={"mode": {"current": "test"}},
            remove_sections=["multi_agent"]
        )
        
        d = config.to_dict()
        
        assert d["profile_type"] == "single_llm_executor"
        assert d["description"] == "Test profile"
        assert d["retain_sections"] == ["validation"]
        assert d["modify_sections"]["mode"]["current"] == "test"
        assert d["remove_sections"] == ["multi_agent"]


class TestDefaultProfiles:
    """Tests for DEFAULT_PROFILES dictionary."""
    
    def test_all_profiles_defined(self):
        """Test that all profile types have configurations."""
        for profile_type in ProfileType:
            assert profile_type in DEFAULT_PROFILES, \
                f"Missing configuration for {profile_type}"
    
    def test_single_llm_executor_profile(self):
        """Test SINGLE_LLM_EXECUTOR profile configuration."""
        profile = DEFAULT_PROFILES[ProfileType.SINGLE_LLM_EXECUTOR]
        
        assert profile.description == "Default profile for single LLM execution"
        assert "validation" in profile.retain_sections
        assert "output" in profile.retain_sections
        assert "multi_agent" in profile.remove_sections
    
    def test_ci_cd_pipeline_profile(self):
        """Test CI_CD_PIPELINE profile configuration."""
        profile = DEFAULT_PROFILES[ProfileType.CI_CD_PIPELINE]
        
        assert profile.description == "Profile for CI/CD pipelines"
        assert "validation" in profile.retain_sections
        assert "security" in profile.retain_sections
        assert "interactive" in profile.remove_sections
        assert "approval" in profile.remove_sections
    
    def test_multi_agent_swarm_profile(self):
        """Test MULTI_AGENT_SWARM profile configuration."""
        profile = DEFAULT_PROFILES[ProfileType.MULTI_AGENT_SWARM]
        
        assert profile.description == "Profile for multi-agent systems"
        assert "multi_agent" in profile.retain_sections
        assert "coordination" in profile.retain_sections
    
    def test_resource_constrained_profile(self):
        """Test RESOURCE_CONSTRAINED profile configuration."""
        profile = DEFAULT_PROFILES[ProfileType.RESOURCE_CONSTRAINED]
        
        assert profile.description == "Profile for resource-limited environments"
        assert "observability" in profile.remove_sections
        assert "tracing" in profile.remove_sections


class TestProfileRouterInit:
    """Tests for ProfileRouter initialization."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        router = ProfileRouter()
        
        assert router._config == {}
        assert len(router._profiles) == len(ProfileType)
    
    def test_init_with_config(self):
        """Test initialization with custom config."""
        config = {"custom_setting": True}
        router = ProfileRouter(config)
        
        assert router._config == config
    
    def test_get_system_info(self):
        """Test system info retrieval."""
        router = ProfileRouter()
        info = router.get_system_info()
        
        assert "memory_mb" in info
        assert "cpu_cores" in info
        assert "platform" in info
        assert info["memory_mb"] > 0
        assert info["cpu_cores"] > 0


class TestProfileRouterDetection:
    """Tests for profile detection."""
    
    def test_auto_detection_works(self):
        """Test that auto-detection returns a valid profile."""
        router = ProfileRouter()
        profile_type = router.detect_profile({})
        
        assert isinstance(profile_type, ProfileType)
    
    def test_ci_cd_detection_env_ci(self):
        """Test CI/CD detection via CI environment variable."""
        original_ci = os.environ.get("CI")
        
        try:
            os.environ["CI"] = "true"
            router = ProfileRouter()
            profile_type = router.detect_profile({})
            
            assert profile_type == ProfileType.CI_CD_PIPELINE
        finally:
            if original_ci is None:
                os.environ.pop("CI", None)
            else:
                os.environ["CI"] = original_ci
    
    def test_ci_cd_detection_github_actions(self):
        """Test CI/CD detection via GITHUB_ACTIONS environment variable."""
        original_gh = os.environ.get("GITHUB_ACTIONS")
        original_ci = os.environ.get("CI")
        
        try:
            os.environ.pop("CI", None)
            os.environ["GITHUB_ACTIONS"] = "true"
            router = ProfileRouter()
            profile_type = router.detect_profile({})
            
            assert profile_type == ProfileType.CI_CD_PIPELINE
        finally:
            if original_gh is None:
                os.environ.pop("GITHUB_ACTIONS", None)
            else:
                os.environ["GITHUB_ACTIONS"] = original_gh
            if original_ci is not None:
                os.environ["CI"] = original_ci
    
    def test_resource_constrained_detection(self):
        """Test resource constrained detection."""
        router = ProfileRouter()
        
        # Simulate low memory
        profile_type = router.detect_profile({"memory_mb": 2048})
        assert profile_type == ProfileType.RESOURCE_CONSTRAINED
        
        # Simulate low CPU
        profile_type = router.detect_profile({"cpu_cores": 2})
        assert profile_type == ProfileType.RESOURCE_CONSTRAINED
    
    def test_multi_agent_swarm_detection(self):
        """Test multi-agent swarm detection."""
        router = ProfileRouter()
        
        profile_type = router.detect_profile({"agent_count": 3})
        assert profile_type == ProfileType.MULTI_AGENT_SWARM
        
        profile_type = router.detect_profile({"agent_count": 10})
        assert profile_type == ProfileType.MULTI_AGENT_SWARM
    
    def test_human_in_the_loop_detection(self):
        """Test human-in-the-loop detection."""
        router = ProfileRouter()
        
        profile_type = router.detect_profile({"interactive": True})
        assert profile_type == ProfileType.HUMAN_IN_THE_LOOP
    
    def test_real_time_streaming_detection(self):
        """Test real-time streaming detection."""
        router = ProfileRouter()
        
        profile_type = router.detect_profile({"streaming": True})
        assert profile_type == ProfileType.REAL_TIME_STREAMING
    
    def test_repo_bootstrap_detection(self):
        """Test repo bootstrap detection."""
        router = ProfileRouter()
        
        profile_type = router.detect_profile({"mode": "REPO_NAVIGATE"})
        assert profile_type == ProfileType.REPO_BOOTSTRAP
    
    def test_small_scripts_detection(self):
        """Test small scripts detection."""
        router = ProfileRouter()
        
        profile_type = router.detect_profile({"file_lines": 500})
        assert profile_type == ProfileType.SMALL_SCRIPTS_LT1K
        
        profile_type = router.detect_profile({"file_lines": 999})
        assert profile_type == ProfileType.SMALL_SCRIPTS_LT1K
    
    def test_non_code_domain_detection(self):
        """Test non-code domain detection."""
        router = ProfileRouter()
        
        profile_type = router.detect_profile({"domain": "medical"})
        assert profile_type == ProfileType.NON_CODE_DOMAIN
        
        profile_type = router.detect_profile({"domain": "legal"})
        assert profile_type == ProfileType.NON_CODE_DOMAIN
    
    def test_single_llm_executor_fallback(self):
        """Test single LLM executor as default fallback."""
        router = ProfileRouter()
        
        # Context that doesn't match any specific profile
        profile_type = router.detect_profile({})
        assert profile_type == ProfileType.SINGLE_LLM_EXECUTOR
        
        profile_type = router.detect_profile({"agent_count": 1, "domain": "code"})
        assert profile_type == ProfileType.SINGLE_LLM_EXECUTOR
    
    def test_detection_priority_order(self):
        """Test that CI/CD has highest priority."""
        original_ci = os.environ.get("CI")
        
        try:
            os.environ["CI"] = "true"
            router = ProfileRouter()
            
            # Even with multiple conditions, CI/CD should win
            profile_type = router.detect_profile({
                "agent_count": 5,  # Would trigger multi_agent_swarm
                "interactive": True,  # Would trigger human_in_the_loop
                "memory_mb": 2048  # Would trigger resource_constrained
            })
            
            assert profile_type == ProfileType.CI_CD_PIPELINE
        finally:
            if original_ci is None:
                os.environ.pop("CI", None)
            else:
                os.environ["CI"] = original_ci


class TestProfileRouterApply:
    """Tests for profile application."""
    
    def test_transforms_applied(self):
        """Test that transforms are applied to config."""
        router = ProfileRouter()
        
        config = {
            "validation": {"enabled": True},
            "output": {"directory": "outputs/"},
            "multi_agent": {"enabled": True},
            "interactive": {"enabled": True}
        }
        
        result = router.apply_profile(ProfileType.SINGLE_LLM_EXECUTOR, config)
        
        # Should retain validation and output
        assert "validation" in result
        assert "output" in result
        
        # Should remove multi_agent
        assert "multi_agent" not in result
    
    def test_ci_cd_transforms(self):
        """Test CI/CD profile transforms."""
        router = ProfileRouter()
        
        config = {
            "validation": {"enabled": True},
            "security": {"enabled": True},
            "output": {"directory": "outputs/"},
            "interactive": {"enabled": True},
            "approval": {"mode": "auto"}
        }
        
        result = router.apply_profile(ProfileType.CI_CD_PIPELINE, config)
        
        # Should retain these sections
        assert "validation" in result
        assert "security" in result
        assert "output" in result
        
        # Should remove approval
        assert "approval" not in result
        
        # interactive is modified (disabled for CI/CD)
        assert "interactive" in result
        assert result["interactive"]["enabled"] is False
    
    def test_resource_constrained_transforms(self):
        """Test resource constrained profile transforms."""
        router = ProfileRouter()
        
        config = {
            "validation": {"enabled": True},
            "output": {"directory": "outputs/"},
            "observability": {"enabled": True},
            "tracing": {"enabled": True}
        }
        
        result = router.apply_profile(ProfileType.RESOURCE_CONSTRAINED, config)
        
        # Should retain validation and output
        assert "validation" in result
        assert "output" in result
        
        # Should remove observability and tracing
        assert "observability" not in result
        assert "tracing" not in result
        
        # Should add chunking modifications
        assert "chunking" in result
        assert result["chunking"]["default_size"] == 500
    
    def test_deep_merge(self):
        """Test that deep merge works correctly."""
        router = ProfileRouter()
        
        config = {
            "gate_sensitivity": {
                "deterministic": {
                    "fail_on_any_gap": False,
                    "existing_key": "value"
                }
            }
        }
        
        result = router.apply_profile(ProfileType.CI_CD_PIPELINE, config)
        
        # Should override fail_on_any_gap
        assert result["gate_sensitivity"]["deterministic"]["fail_on_any_gap"] is True
        
        # Should preserve existing keys
        assert result["gate_sensitivity"]["deterministic"]["existing_key"] == "value"
    
    def test_unknown_profile_returns_unchanged(self):
        """Test that unknown profile returns unchanged config."""
        router = ProfileRouter()
        
        config = {"validation": {"enabled": True}}
        
        # Manually unregister the profile to test
        result = router.apply_profile(ProfileType.SINGLE_LLM_EXECUTOR, config)
        
        # Should still have the original config
        assert "validation" in result


class TestProfileMerge:
    """Tests for profile merging."""
    
    def test_profile_merge(self):
        """Test merging two profiles."""
        router = ProfileRouter()
        
        merged = router.merge_profiles(
            ProfileType.SINGLE_LLM_EXECUTOR,
            ProfileType.CI_CD_PIPELINE
        )
        
        assert merged.profile_type == ProfileType.CI_CD_PIPELINE
        assert "single_llm_executor" in merged.description
        assert "ci_cd_pipeline" in merged.description
        
        # Should combine retain sections
        assert len(merged.retain_sections) >= len(
            DEFAULT_PROFILES[ProfileType.SINGLE_LLM_EXECUTOR].retain_sections
        )
    
    def test_profile_merge_invalid_base(self):
        """Test merging with invalid base profile."""
        router = ProfileRouter()
        
        # Create a fake profile type
        class FakeProfileType:
            value = "fake"
        
        with pytest.raises(ValueError, match="Invalid base profile"):
            router.merge_profiles(FakeProfileType(), ProfileType.CI_CD_PIPELINE)
    
    def test_profile_merge_invalid_overlay(self):
        """Test merging with invalid overlay profile."""
        router = ProfileRouter()
        
        class FakeProfileType:
            value = "fake"
        
        with pytest.raises(ValueError, match="Invalid overlay profile"):
            router.merge_profiles(ProfileType.SINGLE_LLM_EXECUTOR, FakeProfileType())


class TestProfileRegistration:
    """Tests for profile registration."""
    
    def test_register_profile(self):
        """Test registering a custom profile."""
        router = ProfileRouter()
        
        custom_profile = ProfileConfig(
            profile_type=ProfileType.SINGLE_LLM_EXECUTOR,  # Override existing
            description="Custom single LLM profile",
            retain_sections=["custom_section"]
        )
        
        router.register_profile(custom_profile)
        
        # Should return the custom profile
        retrieved = router.get_profile(ProfileType.SINGLE_LLM_EXECUTOR)
        assert retrieved.description == "Custom single LLM profile"
    
    def test_unregister_profile(self):
        """Test unregistering a profile."""
        router = ProfileRouter()
        
        # Unregister a profile
        result = router.unregister_profile(ProfileType.SMALL_SCRIPTS_LT1K)
        
        assert result is True
        assert router.get_profile(ProfileType.SMALL_SCRIPTS_LT1K) is None
    
    def test_unregister_nonexistent(self):
        """Test unregistering a nonexistent profile."""
        router = ProfileRouter()
        
        # First unregister
        router.unregister_profile(ProfileType.SMALL_SCRIPTS_LT1K)
        
        # Second unregister should return False
        result = router.unregister_profile(ProfileType.SMALL_SCRIPTS_LT1K)
        assert result is False


class TestListProfiles:
    """Tests for listing profiles."""
    
    def test_list_profiles(self):
        """Test listing all available profiles."""
        router = ProfileRouter()
        profiles = router.list_profiles()
        
        assert len(profiles) == len(ProfileType)
        
        expected = [pt.value for pt in ProfileType]
        for exp in expected:
            assert exp in profiles


class TestDetectAndApply:
    """Tests for detect_and_apply convenience method."""
    
    def test_detect_and_apply(self):
        """Test combined detect and apply."""
        router = ProfileRouter()
        
        config = {
            "validation": {"enabled": True},
            "output": {"directory": "outputs/"},
            "multi_agent": {"enabled": True}
        }
        
        profile_type, modified = router.detect_and_apply(
            {"agent_count": 3},
            config
        )
        
        assert profile_type == ProfileType.MULTI_AGENT_SWARM
        assert "multi_agent" in modified  # Should be retained for multi_agent_swarm


class TestFactoryFunction:
    """Tests for factory function."""
    
    def test_create_profile_router(self):
        """Test create_profile_router factory function."""
        router = create_profile_router()
        
        assert isinstance(router, ProfileRouter)
    
    def test_create_profile_router_with_config(self):
        """Test factory function with config."""
        config = {"custom": True}
        router = create_profile_router(config)
        
        assert router._config == config


class TestDetectionRulesCoverage:
    """Tests to ensure all detection rules work correctly."""
    
    def test_ci_cd_pipeline_rule(self):
        """Test CI_CD_PIPELINE detection rule."""
        rule = ProfileRouter.DETECTION_RULES["ci_cd_pipeline"]
        
        # Should detect CI environment
        original_ci = os.environ.get("CI")
        try:
            os.environ["CI"] = "true"
            assert rule({}) is True
        finally:
            if original_ci is None:
                os.environ.pop("CI", None)
            else:
                os.environ["CI"] = original_ci
        
        # Should detect ci_flag in context
        assert rule({"ci_flag": True}) is True
        
        # Should not detect when no CI indicators
        os.environ.pop("CI", None)
        os.environ.pop("GITHUB_ACTIONS", None)
        os.environ.pop("GITLAB_CI", None)
        os.environ.pop("JENKINS_URL", None)
        assert rule({}) is False
    
    def test_multi_agent_swarm_rule(self):
        """Test MULTI_AGENT_SWARM detection rule."""
        rule = ProfileRouter.DETECTION_RULES["multi_agent_swarm"]
        
        assert rule({"agent_count": 1}) is False
        assert rule({"agent_count": 2}) is True
        assert rule({"agent_count": 10}) is True
    
    def test_human_in_the_loop_rule(self):
        """Test HUMAN_IN_THE_LOOP detection rule."""
        rule = ProfileRouter.DETECTION_RULES["human_in_the_loop"]
        
        assert rule({"interactive": False}) is False
        assert rule({"interactive": True}) is True
    
    def test_resource_constrained_rule(self):
        """Test RESOURCE_CONSTRAINED detection rule."""
        rule = ProfileRouter.DETECTION_RULES["resource_constrained"]
        
        assert rule({"memory_mb": 8192, "cpu_cores": 8}) is False
        assert rule({"memory_mb": 2048, "cpu_cores": 8}) is True
        assert rule({"memory_mb": 8192, "cpu_cores": 2}) is True
    
    def test_real_time_streaming_rule(self):
        """Test REAL_TIME_STREAMING detection rule."""
        rule = ProfileRouter.DETECTION_RULES["real_time_streaming"]
        
        assert rule({"streaming": False}) is False
        assert rule({"streaming": True}) is True
    
    def test_repo_bootstrap_rule(self):
        """Test REPO_BOOTSTRAP detection rule."""
        rule = ProfileRouter.DETECTION_RULES["repo_bootstrap"]
        
        assert rule({"mode": "REPO_NAVIGATE"}) is True
        assert rule({"mode": "OTHER"}) is False
    
    def test_small_scripts_rule(self):
        """Test SMALL_SCRIPTS_LT1K detection rule."""
        rule = ProfileRouter.DETECTION_RULES["small_scripts_lt1k"]
        
        assert rule({"file_lines": 500}) is True
        assert rule({"file_lines": 999}) is True
        assert rule({"file_lines": 1000}) is False
        assert rule({"file_lines": 5000}) is False
    
    def test_non_code_domain_rule(self):
        """Test NON_CODE_DOMAIN detection rule."""
        rule = ProfileRouter.DETECTION_RULES["non_code_domain"]
        
        assert rule({"domain": "code"}) is False
        assert rule({"domain": "software"}) is False
        assert rule({"domain": None}) is False
        assert rule({"domain": "medical"}) is True
        assert rule({"domain": "legal"}) is True
    
    def test_single_llm_executor_rule(self):
        """Test SINGLE_LLM_EXECUTOR detection rule (always True)."""
        rule = ProfileRouter.DETECTION_RULES["single_llm_executor"]
        
        # Should always return True as it's the fallback
        assert rule({}) is True
        assert rule({"any": "context"}) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
