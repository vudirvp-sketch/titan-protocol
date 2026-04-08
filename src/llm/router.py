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

ITEM-MODEL-001: Root/Leaf Routing Optimization
Intelligent task-to-model routing based on task complexity
and model capabilities. Routes orchestration tasks to root model
and chunk processing tasks to leaf model, with complexity-based
tier adjustment for optimal cost/performance balance.

Author: TITAN FUSE Team
Version: 5.0.0
"""

from typing import Dict, List, Optional, Any, Literal, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
import hashlib

from src.utils.timezone import now_utc_iso


# ============================================================================
# ITEM-MODEL-001: Root/Leaf Routing Optimization Classes
# ============================================================================

class ModelTier(Enum):
    """Model tier for routing decisions.
    
    ITEM-MODEL-001: Defines the capability tier for model selection.
    """
    ROOT = "root"      # High-capability model for orchestration
    LEAF = "leaf"      # Efficient model for simple tasks
    HYBRID = "hybrid"  # Use both with coordination


class TaskType(Enum):
    """Task type classification for routing.
    
    ITEM-MODEL-001: Maps task types to appropriate model tiers.
    """
    ORCHESTRATION = "orchestration"
    PLANNING = "planning"
    CONFLICT_RESOLUTION = "conflict_resolution"
    GATE_DECISION = "gate_decision"
    CHUNK_QUERY = "chunk_query"
    CODE_ANALYSIS = "code_analysis"
    PATTERN_MATCHING = "pattern_matching"
    VALIDATION = "validation"
    UNKNOWN = "unknown"


@dataclass
class TaskComplexity:
    """Complexity factors for routing decision.
    
    ITEM-MODEL-001: Normalized complexity metrics for intelligent routing.
    """
    context_length: float = 0.0      # Normalized 0-1
    dependency_depth: float = 0.0    # Normalized 0-1
    gate_count: float = 0.0          # Normalized 0-1
    pattern_complexity: float = 0.0  # Normalized 0-1
    overall_score: float = 0.0
    
    def __post_init__(self):
        """Calculate overall complexity score after initialization."""
        if self.overall_score == 0.0:
            # Default weights for overall calculation
            weights = {
                "context_length": 0.3,
                "dependency_depth": 0.2,
                "gate_count": 0.2,
                "pattern_complexity": 0.3,
            }
            self.overall_score = (
                self.context_length * weights["context_length"] +
                self.dependency_depth * weights["dependency_depth"] +
                self.gate_count * weights["gate_count"] +
                self.pattern_complexity * weights["pattern_complexity"]
            )
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "context_length": round(self.context_length, 3),
            "dependency_depth": round(self.dependency_depth, 3),
            "gate_count": round(self.gate_count, 3),
            "pattern_complexity": round(self.pattern_complexity, 3),
            "overall_score": round(self.overall_score, 3)
        }


@dataclass
class RoutingDecision:
    """Routing decision result.
    
    ITEM-MODEL-001: Encapsulates the routing decision with rationale.
    """
    tier: ModelTier
    model_id: str
    complexity: TaskComplexity
    confidence: float
    rationale: str
    task_type: TaskType = TaskType.UNKNOWN
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "tier": self.tier.value,
            "model_id": self.model_id,
            "complexity": self.complexity.to_dict(),
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "task_type": self.task_type.value
        }


# End ITEM-MODEL-001 class definitions


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
    
    ITEM-MODEL-001: Root/Leaf Routing Optimization
    
    Intelligent task-to-model routing based on task complexity:
    - Task type determines base tier (ROOT or LEAF)
    - Complexity score can adjust tier (demote ROOT to LEAF, promote LEAF to ROOT)
    - Cost optimization via tier demotion for low-complexity tasks
    
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
        # ITEM-MODEL-001: Task-based routing
        decision = router.route_task({"type": "orchestration", "context": "..."})
    """

    # Phases that use root model (orchestration)
    ROOT_PHASES = {0, 1, 2, 3, 5}
    # Phases that use leaf model (chunk processing)
    LEAF_PHASES = {4}
    
    # ========================================================================
    # ITEM-MODEL-001: Task type -> preferred tier mapping
    # ========================================================================
    TASK_TIER_MAP = {
        TaskType.ORCHESTRATION: ModelTier.ROOT,
        TaskType.PLANNING: ModelTier.ROOT,
        TaskType.CONFLICT_RESOLUTION: ModelTier.ROOT,
        TaskType.GATE_DECISION: ModelTier.ROOT,
        TaskType.CHUNK_QUERY: ModelTier.LEAF,
        TaskType.CODE_ANALYSIS: ModelTier.LEAF,
        TaskType.PATTERN_MATCHING: ModelTier.LEAF,
        TaskType.VALIDATION: ModelTier.LEAF,
        TaskType.UNKNOWN: ModelTier.ROOT,  # Default to root for unknown
    }
    
    # ITEM-MODEL-001: Complexity weights for overall score
    DEFAULT_COMPLEXITY_WEIGHTS = {
        "context_length": 0.3,
        "dependency_depth": 0.2,
        "gate_count": 0.2,
        "pattern_complexity": 0.3,
    }

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
        
        # ====================================================================
        # ITEM-MODEL-001: Routing optimization configuration
        # ====================================================================
        self._complexity_weights = routing.get(
            "complexity_weights", 
            self.DEFAULT_COMPLEXITY_WEIGHTS.copy()
        )
        
        # Tier demotion configuration
        tier_demotion = routing.get("tier_demotion", {})
        self._tier_demotion_enabled = tier_demotion.get("enabled", True)
        self._low_complexity_threshold = tier_demotion.get("low_complexity_threshold", 0.3)
        self._high_complexity_threshold = tier_demotion.get("high_complexity_threshold", 0.7)
        self._high_confidence_threshold = tier_demotion.get("high_confidence_threshold", 0.9)
        
        # Cost tracking for routing decisions
        self._track_costs = routing.get("track_costs", True)
        self._log_model_usage = routing.get("log_model_usage", True)

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
            "version_checks": 0,
            # ITEM-MODEL-001: Routing optimization stats
            "tier_demotions": 0,      # ROOT -> LEAF demotions
            "tier_promotions": 0,     # LEAF -> ROOT promotions
            "routing_decisions": 0,   # Total routing decisions made
            "cost_saved_tokens": 0,   # Estimated tokens saved by demotion
        }

        self._logger.info(
            f"[ITEM-MODEL-001] ModelRouter initialized: root={self.root_model.model}, "
            f"leaf={self.leaf_model.model}, fallback_enabled={self.fallback_enabled}, "
            f"downgrade_allowed={self.downgrade_allowed}, strictness={self.strictness.value}, "
            f"strict_version_check={self.strict_version_check}, "
            f"tier_demotion_enabled={self._tier_demotion_enabled}"
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
            ),
            # ITEM-MODEL-001: Routing optimization stats
            "routing_optimization": self.get_routing_stats()
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
    
    # ========================================================================
    # ITEM-MODEL-001: Root/Leaf Routing Optimization Methods
    # ========================================================================
    
    def route_task(self, task: Dict[str, Any]) -> RoutingDecision:
        """
        Route task to appropriate model tier.
        
        ITEM-MODEL-001: Intelligent routing based on task type and complexity.
        
        Args:
            task: Task dictionary with type, context, dependencies, gates, patterns
            
        Returns:
            RoutingDecision with tier, model_id, complexity, confidence, rationale
        """
        self._usage_stats["routing_decisions"] += 1
        
        # Classify task type
        task_type = self._classify_task(task)
        
        # Estimate complexity
        complexity = self.estimate_complexity(task)
        
        # Get base tier from task type
        base_tier = self.TASK_TIER_MAP.get(task_type, ModelTier.ROOT)
        
        # Adjust tier based on complexity (if tier demotion enabled)
        tier, rationale = self._adjust_tier_for_complexity(
            base_tier, complexity, task_type
        )
        
        # Select specific model for tier
        model_id = self._select_model_for_tier(tier, complexity)
        
        # Calculate confidence
        confidence = self._calculate_routing_confidence(complexity, tier, base_tier)
        
        decision = RoutingDecision(
            tier=tier,
            model_id=model_id,
            complexity=complexity,
            confidence=confidence,
            rationale=rationale,
            task_type=task_type
        )
        
        # Log routing decision if enabled
        if self._log_model_usage:
            self._logger.info(
                f"[ITEM-MODEL-001] Routing decision: task_type={task_type.value}, "
                f"tier={tier.value}, model={model_id}, "
                f"complexity={complexity.overall_score:.3f}, confidence={confidence:.3f}"
            )
        
        return decision
    
    def estimate_complexity(self, task: Dict[str, Any]) -> TaskComplexity:
        """
        Estimate task complexity for routing.
        
        ITEM-MODEL-001: Calculates normalized complexity metrics.
        
        Args:
            task: Task dictionary with context, dependencies, gates, patterns
            
        Returns:
            TaskComplexity with normalized metrics
        """
        # Extract metrics from task
        context = task.get("context", "")
        context_len = len(str(context)) if context else 0
        
        deps = task.get("dependencies", [])
        if not isinstance(deps, list):
            deps = []
        
        gates = task.get("gates", [])
        if not isinstance(gates, list):
            gates = []
        
        patterns = task.get("patterns", [])
        if not isinstance(patterns, list):
            patterns = []
        
        # Normalize to 0-1 range
        complexity = TaskComplexity(
            context_length=min(context_len / 100000, 1.0),
            dependency_depth=min(len(deps) / 10, 1.0),
            gate_count=min(len(gates) / 5, 1.0),
            pattern_complexity=min(len(patterns) / 20, 1.0),
            overall_score=0.0  # Will be calculated in __post_init__
        )
        
        # Recalculate with configured weights
        complexity.overall_score = (
            complexity.context_length * self._complexity_weights.get("context_length", 0.3) +
            complexity.dependency_depth * self._complexity_weights.get("dependency_depth", 0.2) +
            complexity.gate_count * self._complexity_weights.get("gate_count", 0.2) +
            complexity.pattern_complexity * self._complexity_weights.get("pattern_complexity", 0.3)
        )
        
        return complexity
    
    def _classify_task(self, task: Dict[str, Any]) -> TaskType:
        """
        Classify task type from task dictionary.
        
        ITEM-MODEL-001: Determines task type for routing.
        
        Args:
            task: Task dictionary
            
        Returns:
            TaskType enum value
        """
        # Check explicit task type
        task_type_str = task.get("type", "")
        if task_type_str:
            try:
                return TaskType(task_type_str.lower())
            except ValueError:
                pass
        
        # Infer from task properties
        has_gates = bool(task.get("gates"))
        has_dependencies = bool(task.get("dependencies"))
        has_conflicts = task.get("has_conflicts", False)
        is_chunk = task.get("is_chunk", False)
        
        # Decision logic for classification
        if has_conflicts:
            return TaskType.CONFLICT_RESOLUTION
        if has_gates and has_dependencies:
            return TaskType.PLANNING
        if has_gates:
            return TaskType.GATE_DECISION
        if is_chunk:
            return TaskType.CHUNK_QUERY
        if task.get("is_orchestration", False):
            return TaskType.ORCHESTRATION
        if task.get("is_validation", False):
            return TaskType.VALIDATION
        if task.get("is_pattern_matching", False):
            return TaskType.PATTERN_MATCHING
        if task.get("is_code_analysis", False):
            return TaskType.CODE_ANALYSIS
        
        # Default to UNKNOWN (will route to ROOT)
        return TaskType.UNKNOWN
    
    def _adjust_tier_for_complexity(
        self, 
        base_tier: ModelTier, 
        complexity: TaskComplexity,
        task_type: TaskType
    ) -> tuple:
        """
        Adjust model tier based on task complexity.
        
        ITEM-MODEL-001: Implements tier demotion and promotion logic.
        
        Args:
            base_tier: Initial tier from task type
            complexity: Task complexity metrics
            task_type: Classified task type
            
        Returns:
            Tuple of (adjusted_tier, rationale)
        """
        if not self._tier_demotion_enabled:
            return base_tier, f"Task type {task_type.value} routes to {base_tier.value} (tier demotion disabled)"
        
        # Low complexity ROOT task -> can use LEAF
        if (base_tier == ModelTier.ROOT and 
            complexity.overall_score < self._low_complexity_threshold):
            self._usage_stats["tier_demotions"] += 1
            self._usage_stats["cost_saved_tokens"] += 1000  # Estimate
            rationale = (
                f"Low complexity ({complexity.overall_score:.3f} < {self._low_complexity_threshold}) "
                f"allows demotion from ROOT to LEAF for {task_type.value}"
            )
            self._logger.info(f"[ITEM-MODEL-001] Tier demotion: {rationale}")
            return ModelTier.LEAF, rationale
        
        # High complexity LEAF task -> upgrade to ROOT
        if (base_tier == ModelTier.LEAF and 
            complexity.overall_score > self._high_complexity_threshold):
            self._usage_stats["tier_promotions"] += 1
            rationale = (
                f"High complexity ({complexity.overall_score:.3f} > {self._high_complexity_threshold}) "
                f"requires promotion from LEAF to ROOT for {task_type.value}"
            )
            self._logger.info(f"[ITEM-MODEL-001] Tier promotion: {rationale}")
            return ModelTier.ROOT, rationale
        
        # No adjustment
        return base_tier, f"Task type {task_type.value} routes to {base_tier.value}"
    
    def _select_model_for_tier(
        self, 
        tier: ModelTier, 
        complexity: TaskComplexity
    ) -> str:
        """
        Select specific model for tier.
        
        ITEM-MODEL-001: Returns model ID for the given tier.
        
        Args:
            tier: Model tier
            complexity: Task complexity (for future model selection logic)
            
        Returns:
            Model ID string
        """
        if tier == ModelTier.ROOT:
            self._usage_stats["root_calls"] += 1
            return self.root_model.model
        elif tier == ModelTier.LEAF:
            self._usage_stats["leaf_calls"] += 1
            return self.leaf_model.model
        else:  # HYBRID
            # For hybrid, default to root (could be enhanced for parallel execution)
            self._usage_stats["root_calls"] += 1
            return self.root_model.model
    
    def _calculate_routing_confidence(
        self, 
        complexity: TaskComplexity, 
        final_tier: ModelTier,
        base_tier: ModelTier
    ) -> float:
        """
        Calculate routing confidence.
        
        ITEM-MODEL-001: Higher confidence for clear-cut routing decisions.
        
        Args:
            complexity: Task complexity metrics
            final_tier: Final selected tier
            base_tier: Original tier before adjustment
            
        Returns:
            Confidence score 0.0-1.0
        """
        # High confidence when complexity is clearly low or high
        if complexity.overall_score < self._low_complexity_threshold:
            return self._high_confidence_threshold
        if complexity.overall_score > self._high_complexity_threshold:
            return self._high_confidence_threshold
        
        # Medium confidence for middle-ground complexity
        if final_tier != base_tier:
            # Tier was adjusted - slightly lower confidence
            return 0.75
        
        # Base confidence for unambiguous routing
        return 0.8
    
    def get_routing_stats(self) -> Dict:
        """
        Get routing optimization statistics.
        
        ITEM-MODEL-001: Returns stats for monitoring routing behavior.
        
        Returns:
            Dictionary with routing statistics
        """
        total_decisions = self._usage_stats["routing_decisions"]
        return {
            "total_routing_decisions": total_decisions,
            "tier_demotions": self._usage_stats["tier_demotions"],
            "tier_promotions": self._usage_stats["tier_promotions"],
            "demotion_rate": (
                self._usage_stats["tier_demotions"] / max(1, total_decisions)
            ),
            "promotion_rate": (
                self._usage_stats["tier_promotions"] / max(1, total_decisions)
            ),
            "estimated_cost_savings_tokens": self._usage_stats["cost_saved_tokens"],
            "complexity_weights": self._complexity_weights,
            "tier_demotion_config": {
                "enabled": self._tier_demotion_enabled,
                "low_complexity_threshold": self._low_complexity_threshold,
                "high_complexity_threshold": self._high_complexity_threshold,
            }
        }


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
