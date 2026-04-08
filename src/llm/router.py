"""
Model Router for TITAN FUSE Protocol.

Provides model routing with fallback chain support for
config-driven root/leaf model selection.

ITEM-GATE-05: Model Downgrade Determinism
Controls model downgrade behavior based on execution mode.
In deterministic mode, downgrade is blocked to ensure reproducibility.

ITEM-ARCH-15: Model Version Fingerprint
Tracks provider-side model version to ensure reproducibility.
Different model versions may produce different outputs,
breaking reproducibility guarantees.

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, List, Optional, Any, Literal
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
import hashlib

from src.utils.timezone import now_utc_iso


class ExecutionStrictness(Enum):
    """Execution strictness levels."""
    DETERMINISTIC = "deterministic"
    GUIDED_AUTONOMY = "guided_autonomy"
    FAST_PROTOTYPE = "fast_prototype"


class BudgetExhaustedError(Exception):
    """Raised when budget is exhausted and downgrade is not allowed."""
    pass


class DowngradeViolationError(Exception):
    """Raised when downgrade violates deterministic constraints."""
    pass


class ModelVersionError(Exception):
    """
    ITEM-ARCH-15: Raised when model version fingerprint mismatch detected.

    This error is raised in deterministic mode when the model version
    differs from the one used in a previous session, which would break
    reproducibility guarantees.

    Attributes:
        current_fingerprint: The fingerprint of the current model version
        stored_fingerprint: The fingerprint stored from the previous session
    """
    def __init__(self, current_fingerprint: str, stored_fingerprint: str):
        self.current_fingerprint = current_fingerprint
        self.stored_fingerprint = stored_fingerprint
        super().__init__(
            f"Model version mismatch: current={current_fingerprint[:16]}..., "
            f"stored={stored_fingerprint[:16]}... "
            f"Use --fast or --guided mode to allow version drift, "
            f"or update the model version."
        )


@dataclass
class ModelConfig:
    """
    Configuration for a specific model.

    ITEM-ARCH-15: Added version tracking for reproducibility.
    - version: Model version identifier (e.g., "2024-01-15", "v1.2.3")
    - version_fingerprint: SHA-256 hash of provider:model:version
    """
    provider: str
    model: str
    max_tokens: int = 4096
    fallback: List[str] = field(default_factory=list)
    temperature: float = 0.7
    supports_streaming: bool = True
    # ITEM-ARCH-15: Version tracking fields
    version: str = "unknown"  # e.g., "2024-01-15" or "v1.2.3"
    version_fingerprint: str = field(default="", init=False)

    def __post_init__(self):
        """Compute fingerprint after initialization."""
        if not self.version_fingerprint:
            self.version_fingerprint = self.compute_fingerprint()

    def compute_fingerprint(self) -> str:
        """
        ITEM-ARCH-15: Compute SHA-256 fingerprint of model configuration.

        The fingerprint uniquely identifies the exact model version,
        ensuring reproducibility across sessions.

        Returns:
            32-character hex string (first 32 chars of SHA-256)
        """
        data = f"{self.provider}:{self.model}:{self.version}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    def to_dict(self) -> Dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "fallback": self.fallback,
            "temperature": self.temperature,
            "supports_streaming": self.supports_streaming,
            "version": self.version,
            "version_fingerprint": self.version_fingerprint
        }

    @classmethod
    def from_string(cls, model_str: str) -> 'ModelConfig':
        """Create from simple string like 'gpt-4' or 'openai:gpt-4'."""
        if ':' in model_str:
            provider, model = model_str.split(':', 1)
        else:
            provider = "default"
            model = model_str
        return cls(provider=provider, model=model)


@dataclass
class FallbackState:
    """Current fallback state."""
    current_index: int = 0
    fallback_count: int = 0
    last_fallback_reason: Optional[str] = None
    last_fallback_time: Optional[str] = None
    total_fallbacks: int = 0


@dataclass
class BudgetStatus:
    """Current budget status."""
    total_budget: int = 100000
    used: int = 0
    remaining: int = 100000
    exhausted: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "total_budget": self.total_budget,
            "used": self.used,
            "remaining": self.remaining,
            "exhausted": self.exhausted
        }


class ModelRouter:
    """
    Route LLM calls with fallback chain.

    Manages model selection based on processing phase and
    provides automatic fallback on errors/timeouts.

    Root model: Used for orchestration (Phases 0-3, 5)
    Leaf model: Used for chunk processing (Phase 4)

    ITEM-GATE-05: Model Downgrade Determinism
    
    In deterministic mode, model downgrade is blocked to ensure
    reproducible results. If budget is exhausted, the operation
    fails rather than silently downgrading.
    
    Mode-specific behavior:
    - deterministic: Blocks downgrade, raises BudgetExhaustedError
    - guided_autonomy: Allows downgrade to first fallback model
    - fast_prototype: Allows downgrade to cheapest model
    
    Usage:
        config = {
            "model_routing": {
                "root_model": {"provider": "openai", "model": "gpt-4"},
                "leaf_model": {"provider": "openai", "model": "gpt-3.5-turbo"}
            },
            "model_fallback": {
                "enabled": True,
                "chain": ["claude-3", "local-model"]
            },
            "model_downgrade_allowed": True,  # Only for fast_prototype
            "mode": {"current": "guided_autonomy"}
        }
        router = ModelRouter(config)
        model = router.get_model(strictness="deterministic", budget_status)
    """

    # Phases that use root model (orchestration)
    ROOT_PHASES = {0, 1, 2, 3, 5}
    # Phases that use leaf model (chunk processing)
    LEAF_PHASES = {4}

    def __init__(self, config: Dict):
        self.config = config
        self._logger = logging.getLogger(__name__)

        # Parse model configs
        routing = config.get("model_routing", {})
        self.root_model = self._parse_model(routing.get("root_model", {}))
        self.leaf_model = self._parse_model(routing.get("leaf_model", {}))

        # Fallback configuration
        fb_config = config.get("model_fallback", {})
        self.fallback_chain = fb_config.get("chain", [])
        self.fallback_enabled = fb_config.get("enabled", False)
        self.fallback_state = FallbackState()

        # ITEM-GATE-05: Downgrade control
        self.downgrade_allowed = config.get("model_downgrade_allowed", False)
        self.strictness = self._get_strictness_from_config()

        # ITEM-ARCH-15: Version tracking configuration
        llm_config = config.get("llm", {})
        self.strict_version_check = llm_config.get("strict_version_check", False)
        self.version_tracking_enabled = llm_config.get("version_tracking", {}).get("enabled", True)
        self.version_warn_only = llm_config.get("version_tracking", {}).get("warn_only", False)
        
        # Triggers for fallback
        self.triggers = fb_config.get("triggers", {})
        self.timeout_ms = self.triggers.get("timeout_ms", 30000)
        self.error_rate_threshold = self.triggers.get("error_rate_threshold", 0.3)

        # Track usage
        self._usage_stats = {
            "root_calls": 0,
            "leaf_calls": 0,
            "fallback_calls": 0,
            "total_tokens": 0,
            "downgrade_attempts": 0,
            "downgrade_blocks": 0,
            # ITEM-ARCH-15: Version tracking stats
            "version_mismatches": 0,
            "version_checks": 0
        }

        self._logger.info(
            f"ModelRouter initialized: root={self.root_model.model}, "
            f"leaf={self.leaf_model.model}, fallback_enabled={self.fallback_enabled}, "
            f"downgrade_allowed={self.downgrade_allowed}, strictness={self.strictness.value}, "
            f"strict_version_check={self.strict_version_check}"
        )
    
    def _get_strictness_from_config(self) -> ExecutionStrictness:
        """Get execution strictness from configuration."""
        mode = self.config.get("mode", {}).get("current", "direct")
        
        mode_mapping = {
            "deterministic": ExecutionStrictness.DETERMINISTIC,
            "guided_autonomy": ExecutionStrictness.GUIDED_AUTONOMY,
            "guided-autonomy": ExecutionStrictness.GUIDED_AUTONOMY,
            "fast_prototype": ExecutionStrictness.FAST_PROTOTYPE,
            "fast-prototype": ExecutionStrictness.FAST_PROTOTYPE,
            "fast": ExecutionStrictness.FAST_PROTOTYPE,
            "direct": ExecutionStrictness.GUIDED_AUTONOMY
        }
        
        return mode_mapping.get(mode.lower(), ExecutionStrictness.GUIDED_AUTONOMY)

    def _parse_model(self, cfg: Any) -> ModelConfig:
        """Parse model configuration from various formats."""
        if isinstance(cfg, str):
            return ModelConfig.from_string(cfg)
        if isinstance(cfg, dict):
            return ModelConfig(
                provider=cfg.get("provider", "default"),
                model=cfg.get("model", "unknown"),
                max_tokens=cfg.get("max_tokens", 4096),
                fallback=cfg.get("fallback", []),
                temperature=cfg.get("temperature", 0.7),
                supports_streaming=cfg.get("supports_streaming", True),
                version=cfg.get("version", "unknown")  # ITEM-ARCH-15
            )
        return ModelConfig(provider="default", model="unknown")

    def check_model_version(self, stored_fingerprint: str,
                            model_type: str = "root") -> bool:
        """
        ITEM-ARCH-15: Check model version against stored fingerprint.

        In deterministic mode, a mismatch raises ModelVersionError.
        In other modes, a warning is logged and the operation continues.

        Args:
            stored_fingerprint: Fingerprint stored from previous session
            model_type: "root" or "leaf" model to check

        Returns:
            True if versions match, False otherwise

        Raises:
            ModelVersionError: If strict_version_check=True and mismatch detected
        """
        if not self.version_tracking_enabled:
            return True

        self._usage_stats["version_checks"] += 1

        model = self.root_model if model_type == "root" else self.leaf_model
        current_fingerprint = model.version_fingerprint

        if current_fingerprint == stored_fingerprint:
            return True

        # Mismatch detected
        self._usage_stats["version_mismatches"] += 1

        if self.strict_version_check and self.strictness == ExecutionStrictness.DETERMINISTIC:
            self._logger.error(
                f"[gap: model_version_mismatch] "
                f"Model version changed: {model_type} model "
                f"current={current_fingerprint[:16]}... vs "
                f"stored={stored_fingerprint[:16]}... "
                f"Reproducibility cannot be guaranteed."
            )
            raise ModelVersionError(current_fingerprint, stored_fingerprint)

        # Log warning and continue
        self._logger.warning(
            f"[gap: model_version_mismatch] "
            f"Model version changed: {model_type} model "
            f"current={current_fingerprint[:16]}... vs "
            f"stored={stored_fingerprint[:16]}... "
            f"Continuing in {self.strictness.value} mode."
        )
        return False

    def get_model_fingerprints(self) -> Dict[str, str]:
        """
        ITEM-ARCH-15: Get fingerprints for both models.

        Returns:
            Dict with 'root' and 'leaf' fingerprints
        """
        return {
            "root": self.root_model.version_fingerprint,
            "leaf": self.leaf_model.version_fingerprint,
            "root_model": self.root_model.model,
            "leaf_model": self.leaf_model.model,
            "root_version": self.root_model.version,
            "leaf_version": self.leaf_model.version
        }

    def get_model_for_phase(self, phase: int) -> ModelConfig:
        """
        Get appropriate model for processing phase.

        Args:
            phase: Processing phase (0-5)

        Returns:
            ModelConfig for the appropriate model
        """
        if phase in self.ROOT_PHASES:
            self._usage_stats["root_calls"] += 1
            return self.root_model
        self._usage_stats["leaf_calls"] += 1
        return self.leaf_model
    
    def get_model(self, strictness: str = None,
                  budget_status: BudgetStatus = None) -> ModelConfig:
        """
        ITEM-GATE-05: Get model with strictness-aware downgrade control.
        
        This method enforces deterministic constraints on model selection.
        In deterministic mode, budget exhaustion results in an error rather
        than silent downgrade.
        
        Args:
            strictness: Override strictness level ("deterministic", 
                       "guided_autonomy", "fast_prototype")
            budget_status: Current budget status
            
        Returns:
            ModelConfig for the appropriate model
            
        Raises:
            BudgetExhaustedError: If budget exhausted in deterministic mode
            DowngradeViolationError: If downgrade attempted in deterministic mode
        """
        # Determine strictness level
        if strictness:
            strictness_enum = ExecutionStrictness(strictness)
        else:
            strictness_enum = self.strictness
        
        # Check budget status
        budget_exhausted = budget_status and budget_status.exhausted
        
        if budget_exhausted:
            return self._handle_budget_exhaustion(strictness_enum, budget_status)
        
        # Normal operation - return root model
        return self.root_model
    
    def _handle_budget_exhaustion(self, strictness: ExecutionStrictness,
                                   budget_status: BudgetStatus) -> ModelConfig:
        """
        Handle budget exhaustion based on strictness level.
        
        ITEM-GATE-05: Different modes handle budget exhaustion differently.
        """
        self._usage_stats["downgrade_attempts"] += 1
        
        if strictness == ExecutionStrictness.DETERMINISTIC:
            # DETERMINISTIC: Block downgrade
            self._usage_stats["downgrade_blocks"] += 1
            self._logger.error(
                "[gap: deterministic_mode_downgrade] "
                "Budget exhausted in deterministic mode. "
                "Downgrade is blocked to ensure reproducibility. "
                "Use --fast flag for auto-downgrade capability."
            )
            raise BudgetExhaustedError(
                "Budget exhausted in deterministic mode. "
                "Model downgrade is not allowed in deterministic mode to ensure "
                "reproducibility. Use a less strict mode (--guided or --fast) "
                "to enable auto-downgrade, or increase budget."
            )
        
        elif strictness == ExecutionStrictness.GUIDED_AUTONOMY:
            # GUIDED_AUTONOMY: Allow downgrade to first fallback
            if self.fallback_chain:
                self._logger.warning(
                    f"[model_downgrade] Budget exhausted. "
                    f"Downgrading to first fallback model: {self.fallback_chain[0]}"
                )
                return ModelConfig.from_string(self.fallback_chain[0])
            else:
                self._logger.error(
                    "[model_router] Budget exhausted but no fallback chain configured"
                )
                raise BudgetExhaustedError(
                    "Budget exhausted and no fallback chain available. "
                    "Configure model_fallback.chain in config.yaml."
                )
        
        elif strictness == ExecutionStrictness.FAST_PROTOTYPE:
            # FAST_PROTOTYPE: Allow downgrade to cheapest model
            if self.fallback_chain:
                cheapest = self.fallback_chain[-1]
                self._logger.info(
                    f"[model_downgrade] Budget exhausted in fast_prototype mode. "
                    f"Using cheapest fallback model: {cheapest}"
                )
                return ModelConfig.from_string(cheapest)
            else:
                self._logger.warning(
                    "[model_router] Budget exhausted, no fallback. "
                    "Continuing with root model."
                )
                return self.root_model
        
        # Default: return root model
        return self.root_model

    def should_fallback(self, error: Optional[Exception] = None,
                        latency_ms: int = 0,
                        token_budget_exceeded: bool = False) -> bool:
        """
        Determine if fallback should activate.

        Args:
            error: Exception that occurred
            latency_ms: Request latency in milliseconds
            token_budget_exceeded: Whether token budget was exceeded

        Returns:
            True if fallback should be triggered
        """
        if not self.fallback_enabled:
            return False

        # Check timeout
        if latency_ms > self.timeout_ms:
            self._logger.info(
                f"Fallback triggered: timeout ({latency_ms}ms > {self.timeout_ms}ms)"
            )
            return True

        # Check token budget
        if token_budget_exceeded:
            self._logger.info("Fallback triggered: token budget exceeded")
            return True

        # Check error
        if error:
            self._logger.info(
                f"Fallback triggered: error ({type(error).__name__}: {error})"
            )
            return True

        return False

    def activate_fallback(self, reason: str = "unknown") -> Optional[str]:
        """
        Activate next fallback model.

        ITEM-GATE-05: Checks strictness before allowing fallback.
        
        Args:
            reason: Reason for fallback

        Returns:
            Next model in fallback chain, or None if exhausted/blocked
        """
        # Check if fallback is allowed in current mode
        if self.strictness == ExecutionStrictness.DETERMINISTIC:
            if not self.downgrade_allowed:
                self._logger.error(
                    "[gap: deterministic_mode_downgrade] "
                    "Fallback blocked in deterministic mode"
                )
                return None
        
        if not self.fallback_chain:
            self._logger.warning("Fallback requested but no fallback chain configured")
            return None

        if self.fallback_state.current_index < len(self.fallback_chain):
            next_model = self.fallback_chain[self.fallback_state.current_index]
            self.fallback_state.current_index += 1
            self.fallback_state.fallback_count += 1
            self.fallback_state.last_fallback_reason = reason
            self.fallback_state.last_fallback_time = now_utc_iso()
            self.fallback_state.total_fallbacks += 1
            self._usage_stats["fallback_calls"] += 1

            self._logger.warning(
                f"Activated fallback model: {next_model} (reason: {reason}, "
                f"fallback #{self.fallback_state.fallback_count})"
            )
            return next_model

        self._logger.error("No more fallback models available")
        return None

    def reset_fallback(self) -> None:
        """Reset fallback state for new operation."""
        self.fallback_state = FallbackState()
        self._logger.debug("Fallback state reset")

    def get_status(self) -> Dict:
        """Get current router status."""
        return {
            "root_model": self.root_model.to_dict(),
            "leaf_model": self.leaf_model.to_dict(),
            "fallback_enabled": self.fallback_enabled,
            "fallback_chain": self.fallback_chain,
            "fallback_state": {
                "current_index": self.fallback_state.current_index,
                "fallback_count": self.fallback_state.fallback_count,
                "last_fallback_reason": self.fallback_state.last_fallback_reason,
                "last_fallback_time": self.fallback_state.last_fallback_time,
                "total_fallbacks": self.fallback_state.total_fallbacks
            },
            "downgrade_allowed": self.downgrade_allowed,
            "strictness": self.strictness.value,
            "usage_stats": self._usage_stats,
            # ITEM-ARCH-15: Version tracking status
            "version_tracking": {
                "enabled": self.version_tracking_enabled,
                "strict_check": self.strict_version_check,
                "fingerprints": self.get_model_fingerprints()
            }
        }

    def record_token_usage(self, tokens: int, phase: int) -> None:
        """Record token usage for tracking."""
        self._usage_stats["total_tokens"] += tokens

    def get_usage_summary(self) -> Dict:
        """Get usage summary for metrics."""
        return {
            "root_calls": self._usage_stats["root_calls"],
            "leaf_calls": self._usage_stats["leaf_calls"],
            "fallback_calls": self._usage_stats["fallback_calls"],
            "total_tokens": self._usage_stats["total_tokens"],
            "downgrade_attempts": self._usage_stats["downgrade_attempts"],
            "downgrade_blocks": self._usage_stats["downgrade_blocks"],
            # ITEM-ARCH-15: Version tracking stats
            "version_checks": self._usage_stats["version_checks"],
            "version_mismatches": self._usage_stats["version_mismatches"],
            "fallback_rate": (
                self._usage_stats["fallback_calls"] /
                max(1, self._usage_stats["root_calls"] + self._usage_stats["leaf_calls"])
            )
        }
    
    def validate_downgrade_config(self) -> List[str]:
        """
        Validate downgrade configuration for current mode.
        
        ITEM-GATE-05: Returns list of warnings/errors.
        
        Returns:
            List of validation messages
        """
        issues = []
        
        # Check deterministic mode with downgrade enabled
        if (self.strictness == ExecutionStrictness.DETERMINISTIC and 
            self.downgrade_allowed):
            issues.append(
                "[WARNING] model_downgrade_allowed=true in deterministic mode. "
                "This setting has no effect in deterministic mode - downgrade is always blocked."
            )
        
        # Check for missing fallback chain
        if self.fallback_enabled and not self.fallback_chain:
            issues.append(
                "[WARNING] Fallback enabled but no fallback chain configured. "
                "Add models to model_fallback.chain in config.yaml."
            )
        
        return issues


def create_model_router(config: Dict) -> ModelRouter:
    """
    Factory function to create a ModelRouter.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        ModelRouter instance
    """
    return ModelRouter(config)


def get_model_for_operation(strictness: str,
                            budget_status: BudgetStatus,
                            config: Dict) -> ModelConfig:
    """
    Convenience function to get model for an operation.
    
    ITEM-GATE-05: Provides strictness-aware model selection.
    
    Args:
        strictness: Execution strictness level
        budget_status: Current budget status
        config: Configuration dictionary
        
    Returns:
        ModelConfig for the operation
        
    Raises:
        BudgetExhaustedError: If budget exhausted in deterministic mode
    """
    router = ModelRouter(config)
    return router.get_model(strictness=strictness, budget_status=budget_status)
