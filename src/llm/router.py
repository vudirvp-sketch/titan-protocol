"""
Model Router for TITAN FUSE Protocol.

Provides model routing with fallback chain support for
config-driven root/leaf model selection.

Author: TITAN FUSE Team
Version: 3.2.3
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging


@dataclass
class ModelConfig:
    """Configuration for a specific model."""
    provider: str
    model: str
    max_tokens: int = 4096
    fallback: List[str] = field(default_factory=list)
    temperature: float = 0.7
    supports_streaming: bool = True

    def to_dict(self) -> Dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "fallback": self.fallback,
            "temperature": self.temperature,
            "supports_streaming": self.supports_streaming
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


class ModelRouter:
    """
    Route LLM calls with fallback chain.

    Manages model selection based on processing phase and
    provides automatic fallback on errors/timeouts.

    Root model: Used for orchestration (Phases 0-3, 5)
    Leaf model: Used for chunk processing (Phase 4)

    Usage:
        config = {
            "model_routing": {
                "root_model": {"provider": "openai", "model": "gpt-4"},
                "leaf_model": {"provider": "openai", "model": "gpt-3.5-turbo"}
            },
            "model_fallback": {
                "enabled": True,
                "chain": ["claude-3", "local-model"]
            }
        }
        router = ModelRouter(config)
        model = router.get_model_for_phase(4)  # Returns leaf model
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

        # Triggers for fallback
        self.triggers = fb_config.get("triggers", {})
        self.timeout_ms = self.triggers.get("timeout_ms", 30000)
        self.error_rate_threshold = self.triggers.get("error_rate_threshold", 0.3)

        # Track usage
        self._usage_stats = {
            "root_calls": 0,
            "leaf_calls": 0,
            "fallback_calls": 0,
            "total_tokens": 0
        }

        self._logger.info(
            f"ModelRouter initialized: root={self.root_model.model}, "
            f"leaf={self.leaf_model.model}, fallback_enabled={self.fallback_enabled}"
        )

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
                supports_streaming=cfg.get("supports_streaming", True)
            )
        return ModelConfig(provider="default", model="unknown")

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

        Args:
            reason: Reason for fallback

        Returns:
            Next model in fallback chain, or None if exhausted
        """
        if not self.fallback_chain:
            self._logger.warning("Fallback requested but no fallback chain configured")
            return None

        if self.fallback_state.current_index < len(self.fallback_chain):
            next_model = self.fallback_chain[self.fallback_state.current_index]
            self.fallback_state.current_index += 1
            self.fallback_state.fallback_count += 1
            self.fallback_state.last_fallback_reason = reason
            self.fallback_state.last_fallback_time = datetime.utcnow().isoformat() + "Z"
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
            "usage_stats": self._usage_stats
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
            "fallback_rate": (
                self._usage_stats["fallback_calls"] /
                max(1, self._usage_stats["root_calls"] + self._usage_stats["leaf_calls"])
            )
        }
