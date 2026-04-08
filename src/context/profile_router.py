"""
ITEM-CTX-001: ProfileRouter Enhancement for TITAN Protocol v5.0.0.

Context Adaptation Matrix profiles for runtime selection based on
execution context. Auto-detects and applies appropriate profile.

Profiles:
- single_llm_executor: Default profile for single LLM execution
- ci_cd_pipeline: Profile for CI/CD pipelines
- multi_agent_swarm: Profile for multi-agent systems
- human_in_the_loop: Profile for interactive sessions
- resource_constrained: Profile for resource-limited environments
- non_code_domain: Profile for non-software domains
- real_time_streaming: Profile for streaming operations
- small_scripts_lt1k: Profile for scripts under 1000 lines
- repo_bootstrap: Profile for repository bootstrap

Author: TITAN Protocol Team
Version: 5.0.0
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable
from enum import Enum
import os
import logging
import platform

from src.utils.timezone import now_utc_iso


class ProfileType(Enum):
    """All 9 context adaptation profiles."""
    SINGLE_LLM_EXECUTOR = "single_llm_executor"
    CI_CD_PIPELINE = "ci_cd_pipeline"
    MULTI_AGENT_SWARM = "multi_agent_swarm"
    HUMAN_IN_THE_LOOP = "human_in_the_loop"
    RESOURCE_CONSTRAINED = "resource_constrained"
    NON_CODE_DOMAIN = "non_code_domain"
    REAL_TIME_STREAMING = "real_time_streaming"
    SMALL_SCRIPTS_LT1K = "small_scripts_lt1k"
    REPO_BOOTSTRAP = "repo_bootstrap"


@dataclass
class ProfileConfig:
    """Configuration for a profile."""
    profile_type: ProfileType
    description: str
    retain_sections: List[str] = field(default_factory=list)
    modify_sections: Dict[str, Any] = field(default_factory=dict)
    remove_sections: List[str] = field(default_factory=list)
    detection_rules: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "profile_type": self.profile_type.value,
            "description": self.description,
            "retain_sections": self.retain_sections,
            "modify_sections": self.modify_sections,
            "remove_sections": self.remove_sections,
            "detection_rules": self.detection_rules
        }


# Default profiles from protocol specification
DEFAULT_PROFILES: Dict[ProfileType, ProfileConfig] = {
    ProfileType.SINGLE_LLM_EXECUTOR: ProfileConfig(
        profile_type=ProfileType.SINGLE_LLM_EXECUTOR,
        description="Default profile for single LLM execution",
        retain_sections=["validation", "output", "checkpoint"],
        modify_sections={
            "gate_sensitivity": {
                "deterministic": {"fail_on_any_gap": False}
            },
            "mode": {
                "current": "single_llm_executor"
            }
        },
        remove_sections=["multi_agent"],
        detection_rules={"agent_count": 1}
    ),
    
    ProfileType.CI_CD_PIPELINE: ProfileConfig(
        profile_type=ProfileType.CI_CD_PIPELINE,
        description="Profile for CI/CD pipelines",
        retain_sections=["validation", "security", "output"],
        modify_sections={
            "gate_sensitivity": {
                "deterministic": {"fail_on_any_gap": True}
            },
            "mode": {
                "current": "ci_cd_pipeline",
                "strict_mode": True,
                "fail_fast": True
            },
            "interactive": {"enabled": False}
        },
        remove_sections=["interactive", "approval"],
        detection_rules={"env_ci": True}
    ),
    
    ProfileType.MULTI_AGENT_SWARM: ProfileConfig(
        profile_type=ProfileType.MULTI_AGENT_SWARM,
        description="Profile for multi-agent systems",
        retain_sections=["multi_agent", "coordination", "decision"],
        modify_sections={
            "gate_sensitivity": {
                "multi_agent_swarm": {"consensus_required": True}
            },
            "mode": {
                "current": "multi_agent_swarm",
                "consensus_required": True
            }
        },
        remove_sections=[],
        detection_rules={"agent_count": (lambda x: x > 1)}
    ),
    
    ProfileType.HUMAN_IN_THE_LOOP: ProfileConfig(
        profile_type=ProfileType.HUMAN_IN_THE_LOOP,
        description="Profile for interactive human-in-the-loop sessions",
        retain_sections=["interactive", "approval", "feedback"],
        modify_sections={
            "mode": {
                "current": "guided_autonomy"
            },
            "interactive": {"enabled": True},
            "approval": {
                "mode": "interactive",
                "require_acknowledgement": True
            }
        },
        remove_sections=[],
        detection_rules={"interactive": True}
    ),
    
    ProfileType.RESOURCE_CONSTRAINED: ProfileConfig(
        profile_type=ProfileType.RESOURCE_CONSTRAINED,
        description="Profile for resource-limited environments",
        retain_sections=["validation", "output"],
        modify_sections={
            "chunking": {
                "default_size": 500,
                "large_file_size": 400
            },
            "validation_tiering": {
                "sev3_large_file_rate": 0.3,
                "sev4_large_file_rate": 0.1
            },
            "symbol_map": {
                "max_entries": 10000,
                "max_memory_mb": 100
            },
            "metrics": {"enabled": False}
        },
        remove_sections=["observability", "tracing"],
        detection_rules={
            "memory_mb": (lambda x: x < 4096),
            "cpu_cores": (lambda x: x < 4)
        }
    ),
    
    ProfileType.NON_CODE_DOMAIN: ProfileConfig(
        profile_type=ProfileType.NON_CODE_DOMAIN,
        description="Profile for non-software domains (medical, legal, narrative)",
        retain_sections=["validation", "output"],
        modify_sections={
            "scoring": {
                "adaptive_weights": {
                    "default_profile": "narrative"
                }
            },
            "fusion": {
                "type_aware": {
                    "strict_type_merge": False,
                    "low_density_policy": "unique_context_or_caveat"
                }
            },
            "chunking": {
                "boundary_markers": ["^#{1,6} ", "^---$", "^```"]
            }
        },
        remove_sections=["sandbox", "dependency_resolution"],
        detection_rules={"domain": (lambda x: x not in ["code", "software", None])}
    ),
    
    ProfileType.REAL_TIME_STREAMING: ProfileConfig(
        profile_type=ProfileType.REAL_TIME_STREAMING,
        description="Profile for real-time streaming operations",
        retain_sections=["streaming", "output"],
        modify_sections={
            "streaming": {
                "enabled": True,
                "early_termination_on_gate_fail": True,
                "buffer_size": 8192
            },
            "validation": {
                "parallel_safe_check": True,
                "max_patch_iterations": 1
            }
        },
        remove_sections=["interactive", "approval"],
        detection_rules={"streaming": True}
    ),
    
    ProfileType.SMALL_SCRIPTS_LT1K: ProfileConfig(
        profile_type=ProfileType.SMALL_SCRIPTS_LT1K,
        description="Profile for scripts under 1000 lines",
        retain_sections=["validation"],
        modify_sections={
            "chunking": {
                "default_size": 1500,
                "semantic_boundaries": False
            },
            "multi_file": {"enabled": False}
        },
        remove_sections=["multi_file", "dependency_resolution"],
        detection_rules={"file_lines": (lambda x: x < 1000)}
    ),
    
    ProfileType.REPO_BOOTSTRAP: ProfileConfig(
        profile_type=ProfileType.REPO_BOOTSTRAP,
        description="Profile for repository bootstrap and navigation",
        retain_sections=["navigation", "discovery"],
        modify_sections={
            "mode": {"current": "repo_bootstrap"}
        },
        remove_sections=["execution"],
        detection_rules={"mode": "REPO_NAVIGATE"}
    ),
}


class ProfileRouter:
    """
    ITEM-CTX-001: Auto-detect and apply context adaptation profiles.
    
    The ProfileRouter automatically detects the execution context and
    applies the appropriate configuration profile for optimal behavior.
    
    Attributes:
        _config: Optional configuration dictionary
        _profiles: Dictionary of available profiles
        _logger: Logger instance for this module
        _system_info: Cached system information for detection
    
    Example:
        >>> router = ProfileRouter()
        >>> context = {"agent_count": 3}
        >>> profile_type = router.detect_profile(context)
        >>> profile_type.value
        'multi_agent_swarm'
        >>> config = {"validation": {}, "output": {}}
        >>> modified = router.apply_profile(profile_type, config)
    """
    
    # Detection rules for auto-detection
    DETECTION_RULES: Dict[str, Callable[[Dict[str, Any]], bool]] = {
        "ci_cd_pipeline": lambda ctx: (
            os.environ.get("CI") == "true" or 
            ctx.get("ci_flag", False) or
            os.environ.get("GITHUB_ACTIONS") == "true" or
            os.environ.get("GITLAB_CI") == "true" or
            os.environ.get("JENKINS_URL") is not None
        ),
        "multi_agent_swarm": lambda ctx: ctx.get("agent_count", 1) > 1,
        "human_in_the_loop": lambda ctx: ctx.get("interactive", False),
        "resource_constrained": lambda ctx: (
            ctx.get("memory_mb", 16384) < 4096 or 
            ctx.get("cpu_cores", 8) < 4
        ),
        "real_time_streaming": lambda ctx: ctx.get("streaming", False),
        "repo_bootstrap": lambda ctx: ctx.get("mode") == "REPO_NAVIGATE",
        "small_scripts_lt1k": lambda ctx: ctx.get("file_lines", 10000) < 1000,
        "non_code_domain": lambda ctx: ctx.get("domain") not in ["code", "software", None],
        "single_llm_executor": lambda ctx: True  # Default fallback
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize ProfileRouter.
        
        Args:
            config: Optional configuration dictionary
        """
        self._config = config or {}
        self._profiles = dict(DEFAULT_PROFILES)
        self._logger = logging.getLogger(__name__)
        self._system_info = self._get_system_info()
    
    def _get_system_info(self) -> Dict[str, Any]:
        """
        Get system information for detection.
        
        Returns:
            Dictionary with system metrics (memory, cpu, platform)
        """
        memory_mb = 16384  # Default assumption
        cpu_cores = 8  # Default assumption
        
        try:
            import psutil
            memory_mb = psutil.virtual_memory().total / (1024 * 1024)
            cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count() or 8
        except ImportError:
            self._logger.debug(
                "[ITEM-CTX-001] psutil not available, using default system info"
            )
        
        return {
            "memory_mb": memory_mb,
            "cpu_cores": cpu_cores,
            "platform": platform.system()
        }
    
    def detect_profile(self, context: Optional[Dict[str, Any]] = None) -> ProfileType:
        """
        Auto-detect profile from execution context.
        
        Detection priority order:
        1. CI/CD pipeline
        2. Multi-agent swarm
        3. Human in the loop
        4. Resource constrained
        5. Real-time streaming
        6. Repo bootstrap
        7. Small scripts
        8. Non-code domain
        9. Single LLM executor (default)
        
        Args:
            context: Execution context dictionary
        
        Returns:
            ProfileType: Detected profile type
        """
        context = context or {}
        
        # Merge system info with context
        full_context = {**self._system_info, **context}
        
        # Check profiles in priority order
        priority_order = [
            ProfileType.CI_CD_PIPELINE,
            ProfileType.MULTI_AGENT_SWARM,
            ProfileType.HUMAN_IN_THE_LOOP,
            ProfileType.RESOURCE_CONSTRAINED,
            ProfileType.REAL_TIME_STREAMING,
            ProfileType.REPO_BOOTSTRAP,
            ProfileType.SMALL_SCRIPTS_LT1K,
            ProfileType.NON_CODE_DOMAIN,
            ProfileType.SINGLE_LLM_EXECUTOR
        ]
        
        for profile_type in priority_order:
            rule_name = profile_type.value
            if rule_name in self.DETECTION_RULES:
                try:
                    if self.DETECTION_RULES[rule_name](full_context):
                        self._logger.info(
                            f"[ITEM-CTX-001] Detected profile: {profile_type.value}"
                        )
                        return profile_type
                except Exception as e:
                    self._logger.warning(
                        f"[ITEM-CTX-001] Detection rule failed for {rule_name}: {e}"
                    )
        
        return ProfileType.SINGLE_LLM_EXECUTOR
    
    def apply_profile(
        self, 
        profile_type: ProfileType, 
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Apply profile transformations to configuration.
        
        Args:
            profile_type: The profile type to apply
            config: Configuration dictionary to transform
        
        Returns:
            Modified configuration dictionary
        """
        profile = self._profiles.get(profile_type)
        if not profile:
            self._logger.warning(
                f"[ITEM-CTX-001] Unknown profile: {profile_type}, returning unchanged config"
            )
            return config
        
        result = dict(config)
        
        # Remove sections
        for section in profile.remove_sections:
            if section in result:
                del result[section]
                self._logger.debug(
                    f"[ITEM-CTX-001] Removed section: {section}"
                )
        
        # Modify sections (deep merge)
        for section, changes in profile.modify_sections.items():
            if section in result:
                result[section] = self._deep_merge(result[section], changes)
            else:
                result[section] = changes
            self._logger.debug(
                f"[ITEM-CTX-001] Modified section: {section}"
            )
        
        # Log transformation summary
        self._logger.info(
            f"[ITEM-CTX-001] Applied profile {profile_type.value}: "
            f"retain={len(profile.retain_sections)}, "
            f"modify={len(profile.modify_sections)}, "
            f"remove={len(profile.remove_sections)}"
        )
        
        return result
    
    def merge_profiles(
        self, 
        base: ProfileType, 
        overlay: ProfileType
    ) -> ProfileConfig:
        """
        Merge two profiles, with overlay taking precedence.
        
        Args:
            base: Base profile type
            overlay: Overlay profile type (takes precedence)
        
        Returns:
            Merged ProfileConfig
        
        Raises:
            ValueError: If either profile type is invalid
        """
        base_profile = self._profiles.get(base)
        overlay_profile = self._profiles.get(overlay)
        
        if not base_profile:
            raise ValueError(f"Invalid base profile: {base}")
        if not overlay_profile:
            raise ValueError(f"Invalid overlay profile: {overlay}")
        
        return ProfileConfig(
            profile_type=overlay,
            description=f"Merged: {base.value} + {overlay.value}",
            retain_sections=list(
                set(base_profile.retain_sections + overlay_profile.retain_sections)
            ),
            modify_sections={
                **base_profile.modify_sections, 
                **overlay_profile.modify_sections
            },
            remove_sections=list(
                set(base_profile.remove_sections + overlay_profile.remove_sections)
            ),
            detection_rules={}
        )
    
    def _deep_merge(self, base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep merge two dictionaries.
        
        Args:
            base: Base dictionary
            overlay: Overlay dictionary (takes precedence)
        
        Returns:
            Merged dictionary
        """
        result = dict(base)
        for key, value in overlay.items():
            if (
                key in result and 
                isinstance(result[key], dict) and 
                isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    def register_profile(self, profile: ProfileConfig) -> None:
        """
        Register custom profile.
        
        Args:
            profile: ProfileConfig to register
        """
        self._profiles[profile.profile_type] = profile
        self._logger.info(
            f"[ITEM-CTX-001] Registered custom profile: {profile.profile_type.value}"
        )
    
    def unregister_profile(self, profile_type: ProfileType) -> bool:
        """
        Unregister a profile.
        
        Args:
            profile_type: Profile type to unregister
        
        Returns:
            True if profile was removed, False if not found
        """
        if profile_type in self._profiles:
            del self._profiles[profile_type]
            self._logger.info(
                f"[ITEM-CTX-001] Unregistered profile: {profile_type.value}"
            )
            return True
        return False
    
    def get_profile(self, profile_type: ProfileType) -> Optional[ProfileConfig]:
        """
        Get a specific profile configuration.
        
        Args:
            profile_type: Profile type to retrieve
        
        Returns:
            ProfileConfig or None if not found
        """
        return self._profiles.get(profile_type)
    
    def list_profiles(self) -> List[str]:
        """
        List all available profiles.
        
        Returns:
            List of profile names
        """
        return [p.value for p in self._profiles.keys()]
    
    def get_system_info(self) -> Dict[str, Any]:
        """
        Get cached system information.
        
        Returns:
            Dictionary with system metrics
        """
        return dict(self._system_info)
    
    def detect_and_apply(
        self, 
        context: Optional[Dict[str, Any]], 
        config: Dict[str, Any]
    ) -> tuple[ProfileType, Dict[str, Any]]:
        """
        Convenience method to detect profile and apply in one step.
        
        Args:
            context: Execution context dictionary
            config: Configuration dictionary to transform
        
        Returns:
            Tuple of (detected ProfileType, modified config)
        """
        profile_type = self.detect_profile(context)
        modified_config = self.apply_profile(profile_type, config)
        return profile_type, modified_config


def create_profile_router(config: Optional[Dict[str, Any]] = None) -> ProfileRouter:
    """
    Factory function to create ProfileRouter.
    
    Args:
        config: Optional configuration dictionary
    
    Returns:
        ProfileRouter instance
    """
    return ProfileRouter(config)
