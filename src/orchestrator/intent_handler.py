"""
Intent Handler for SCOUT Integration in TITAN FUSE Protocol.

Enforces mandatory DEVIL execution for specific intents that require
critical risk and hype analysis before proceeding.

ITEM-INTENT-01: Intent-based DEVIL enforcement
Intents like EVALUATE, COMPARE, VALIDATE, and AUDIT require DEVIL
execution to ensure proper hype detection and risk flagging.

Integration with:
- ScoutPipeline for agent orchestration
- IntentRouter for policy chain selection

Author: TITAN FUSE Team
Version: 3.4.0
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..agents.scout_matrix import ScoutPipeline, AnalysisContext, ScoutOutput
    from ..policy.intent_router import IntentRouter


# =============================================================================
# Constants
# =============================================================================

MANDATORY_DEVIL_INTENTS: List[str] = [
    "EVALUATE",
    "COMPARE",
    "VALIDATE",
    "AUDIT",
]
"""
List of intents that require mandatory DEVIL agent execution.

These intents involve critical decision-making that requires:
- Hype detection and flagging
- Risk assessment and veto capability
- Readiness tier classification

DEVIL execution ensures that claims are properly scrutinized
before strategic recommendations are made.
"""


# =============================================================================
# Exceptions
# =============================================================================

class IntentConfigError(Exception):
    """
    Exception raised when intent configuration is invalid.

    This error is raised when:
    - An intent in MANDATORY_DEVIL_INTENTS is requested but DEVIL is not enabled
    - Intent configuration is missing required fields
    - Intent conflicts with pipeline configuration

    Attributes:
        intent: The intent that caused the error
        reason: Human-readable explanation of the error
        details: Additional context about the error
    """

    def __init__(
        self,
        intent: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Initialize IntentConfigError.

        Args:
            intent: The intent that caused the error
            reason: Human-readable explanation
            details: Additional context dictionary
        """
        self.intent = intent
        self.reason = reason
        self.details = details or {}
        self.timestamp = datetime.utcnow().isoformat() + "Z"

        message = f"Intent configuration error for '{intent}': {reason}"
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert error to dictionary for serialization.

        Returns:
            Dictionary containing error details
        """
        return {
            "error_type": "IntentConfigError",
            "intent": self.intent,
            "reason": self.reason,
            "details": self.details,
            "timestamp": self.timestamp,
        }


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class IntentValidationResult:
    """
    Result of intent validation.

    Attributes:
        valid: Whether the intent configuration is valid
        intent: The validated intent name
        requires_devil: Whether DEVIL execution is required
        devil_enabled: Whether DEVIL is enabled in the pipeline
        errors: List of validation errors
        warnings: List of validation warnings
    """
    valid: bool
    intent: str
    requires_devil: bool = False
    devil_enabled: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "valid": self.valid,
            "intent": self.intent,
            "requires_devil": self.requires_devil,
            "devil_enabled": self.devil_enabled,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class IntentProcessingStats:
    """
    Statistics for intent processing.

    Attributes:
        intent: The processed intent
        processing_time_ms: Time taken to process in milliseconds
        devil_executed: Whether DEVIL was executed
        pipeline_blocked: Whether the pipeline was blocked
        readiness_tier: Final readiness tier (if available)
        flag_count: Total number of flags raised
    """
    intent: str
    processing_time_ms: float = 0.0
    devil_executed: bool = False
    pipeline_blocked: bool = False
    readiness_tier: Optional[str] = None
    flag_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "intent": self.intent,
            "processing_time_ms": self.processing_time_ms,
            "devil_executed": self.devil_executed,
            "pipeline_blocked": self.pipeline_blocked,
            "readiness_tier": self.readiness_tier,
            "flag_count": self.flag_count,
        }


# =============================================================================
# Intent Handler Class
# =============================================================================

class IntentHandler:
    """
    Handler for intent-based SCOUT pipeline execution.

    Enforces mandatory DEVIL execution for specific intents and manages
    the integration between intent classification and SCOUT agent pipeline.

    The IntentHandler bridges the gap between the IntentRouter (which classifies
    user intent) and the ScoutPipeline (which executes agent analysis).

    Attributes:
        config: Configuration dictionary for the handler
        scout_pipeline: The SCOUT pipeline instance for agent execution
        intent_router: Optional IntentRouter for classification
        devil_enabled: Whether DEVIL agent is enabled
        strict_mode: If True, raises errors on validation failures

    Example:
        >>> from src.agents.scout_matrix import ScoutPipeline, AnalysisContext
        >>> from src.policy.intent_router import IntentRouter
        >>>
        >>> # Initialize components
        >>> pipeline = ScoutPipeline(include_radar=True, strict_mode=True)
        >>> router = IntentRouter()
        >>>
        >>> # Create handler
        >>> config = {"strict_mode": True}
        >>> handler = IntentHandler(config, pipeline)
        >>>
        >>> # Validate intent
        >>> if handler.validate_intent_config("EVALUATE"):
        ...     # Process intent
        ...     context = AnalysisContext(subject="Tech", domain="ai")
        ...     output = handler.process_intent("EVALUATE", context)
    """

    def __init__(
        self,
        config: Dict[str, Any],
        scout_pipeline: "ScoutPipeline",
        intent_router: Optional["IntentRouter"] = None
    ) -> None:
        """
        Initialize the IntentHandler.

        Args:
            config: Configuration dictionary with options:
                - strict_mode: If True, raise errors on validation failures
                - enable_devil: Override for DEVIL enablement
                - log_level: Logging level (default: INFO)
            scout_pipeline: ScoutPipeline instance for agent execution
            intent_router: Optional IntentRouter for intent classification
        """
        self.config = config
        self._scout_pipeline = scout_pipeline
        self._intent_router = intent_router

        # Configuration options
        self._strict_mode = config.get("strict_mode", True)
        self._log_level = config.get("log_level", "INFO")

        # Determine DEVIL enablement
        self._devil_enabled = self._determine_devil_enabled()

        # Initialize logger
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(getattr(logging, self._log_level.upper(), logging.INFO))

        # Statistics tracking
        self._processing_stats: List[IntentProcessingStats] = []

        self._logger.info(
            f"IntentHandler initialized with strict_mode={self._strict_mode}, "
            f"devil_enabled={self._devil_enabled}"
        )

    def validate_intent_config(self, intent: str) -> bool:
        """
        Validate that the intent configuration is correct.

        Checks if the intent requires DEVIL execution and whether DEVIL
        is properly enabled in the pipeline.

        Args:
            intent: The intent name to validate

        Returns:
            True if the intent configuration is valid

        Raises:
            IntentConfigError: If intent requires DEVIL but DEVIL is not enabled
        """
        self._logger.debug(f"Validating intent configuration for: {intent}")

        # Normalize intent to uppercase for comparison
        intent_upper = intent.upper()

        # Check if intent requires DEVIL
        requires_devil = intent_upper in MANDATORY_DEVIL_INTENTS

        if requires_devil and not self._devil_enabled:
            error = IntentConfigError(
                intent=intent,
                reason=(
                    f"Intent '{intent}' requires mandatory DEVIL execution, "
                    "but DEVIL is not enabled in the pipeline configuration"
                ),
                details={
                    "mandatory_devil_intents": MANDATORY_DEVIL_INTENTS,
                    "devil_enabled": self._devil_enabled,
                    "intent_requires_devil": True,
                }
            )

            self._logger.error(
                f"[IntentConfigError] Intent '{intent}' requires DEVIL but "
                "DEVIL is disabled"
            )

            if self._strict_mode:
                raise error
            return False

        self._logger.debug(
            f"Intent '{intent}' validation passed "
            f"(requires_devil={requires_devil})"
        )
        return True

    def process_intent(
        self,
        intent: str,
        context: "AnalysisContext"
    ) -> "ScoutOutput":
        """
        Process an intent through the SCOUT pipeline.

        Validates the intent configuration and executes the SCOUT pipeline
        with the provided analysis context.

        Args:
            intent: The intent to process
            context: AnalysisContext with input data for the pipeline

        Returns:
            ScoutOutput containing the analysis results

        Raises:
            IntentConfigError: If intent validation fails in strict mode
        """
        import time

        start_time = time.time()
        self._logger.info(f"Processing intent: {intent}")

        # Validate intent configuration
        self.validate_intent_config(intent)

        # Update context based on intent
        context = self._prepare_context(intent, context)

        # Execute the pipeline
        output = self._scout_pipeline.execute_pipeline(context)

        # Calculate processing time
        processing_time_ms = (time.time() - start_time) * 1000

        # Record statistics
        stats = IntentProcessingStats(
            intent=intent,
            processing_time_ms=processing_time_ms,
            devil_executed=self._is_devil_intent(intent),
            pipeline_blocked=output.blocked,
            readiness_tier=output.readiness.value if output.readiness else None,
            flag_count=len(output.hype_flags) + len(output.risk_flags),
        )
        self._processing_stats.append(stats)

        self._logger.info(
            f"Intent '{intent}' processed in {processing_time_ms:.2f}ms "
            f"(blocked={output.blocked}, readiness={output.readiness.value})"
        )

        return output

    def get_mandatory_devil_intents(self) -> List[str]:
        """
        Get the list of intents that require mandatory DEVIL execution.

        Returns:
            List of intent names that require DEVIL
        """
        return list(MANDATORY_DEVIL_INTENTS)

    def is_devil_required(self, intent: str) -> bool:
        """
        Check if an intent requires DEVIL execution.

        Args:
            intent: The intent to check

        Returns:
            True if the intent requires DEVIL execution
        """
        return intent.upper() in MANDATORY_DEVIL_INTENTS

    def get_validation_result(self, intent: str) -> IntentValidationResult:
        """
        Get detailed validation result for an intent.

        Provides a comprehensive validation result including
        any errors or warnings.

        Args:
            intent: The intent to validate

        Returns:
            IntentValidationResult with validation details
        """
        intent_upper = intent.upper()
        requires_devil = intent_upper in MANDATORY_DEVIL_INTENTS

        errors = []
        warnings = []

        if requires_devil and not self._devil_enabled:
            errors.append(
                f"DEVIL agent is required for intent '{intent}' but is not enabled"
            )

        # Check if intent is recognized
        if self._intent_router:
            known_intents = self._intent_router.list_intents()
            if intent_upper not in [i.upper() for i in known_intents]:
                warnings.append(
                    f"Intent '{intent}' is not in the known intents list"
                )

        return IntentValidationResult(
            valid=len(errors) == 0,
            intent=intent,
            requires_devil=requires_devil,
            devil_enabled=self._devil_enabled,
            errors=errors,
            warnings=warnings,
        )

    def get_processing_stats(self) -> List[IntentProcessingStats]:
        """
        Get statistics for all processed intents.

        Returns:
            List of IntentProcessingStats for each processed intent
        """
        return list(self._processing_stats)

    def get_last_processing_stats(self) -> Optional[IntentProcessingStats]:
        """
        Get statistics for the most recently processed intent.

        Returns:
            IntentProcessingStats for the last processed intent, or None
        """
        return self._processing_stats[-1] if self._processing_stats else None

    def clear_stats(self) -> None:
        """Clear all processing statistics."""
        self._processing_stats.clear()
        self._logger.debug("Processing statistics cleared")

    def get_handler_info(self) -> Dict[str, Any]:
        """
        Get information about the handler configuration.

        Returns:
            Dictionary with handler configuration details
        """
        return {
            "strict_mode": self._strict_mode,
            "devil_enabled": self._devil_enabled,
            "mandatory_devil_intents": MANDATORY_DEVIL_INTENTS,
            "has_intent_router": self._intent_router is not None,
            "total_intents_processed": len(self._processing_stats),
        }

    def _determine_devil_enabled(self) -> bool:
        """
        Determine if DEVIL agent is enabled in the pipeline.

        Checks both explicit configuration and pipeline state.

        Returns:
            True if DEVIL is enabled
        """
        # Check config override
        if "enable_devil" in self.config:
            return bool(self.config["enable_devil"])

        # Check pipeline agents
        from ..agents.scout_matrix import AgentRole

        if hasattr(self._scout_pipeline, 'agents'):
            return AgentRole.DEVIL in self._scout_pipeline.agents

        # Default to True
        return True

    def _is_devil_intent(self, intent: str) -> bool:
        """
        Check if DEVIL was executed for this intent.

        Args:
            intent: The intent to check

        Returns:
            True if DEVIL was executed
        """
        intent_upper = intent.upper()
        return intent_upper in MANDATORY_DEVIL_INTENTS

    def _prepare_context(
        self,
        intent: str,
        context: "AnalysisContext"
    ) -> "AnalysisContext":
        """
        Prepare the context based on intent type.

        Maps intent to appropriate PipelineContext for the SCOUT pipeline.

        Args:
            intent: The intent being processed
            context: The original analysis context

        Returns:
            Updated AnalysisContext with appropriate context set
        """
        from ..agents.scout_matrix import PipelineContext

        intent_upper = intent.upper()

        # Map intent to pipeline context
        context_mapping = {
            "EVALUATE": PipelineContext.EVALUATE,
            "COMPARE": PipelineContext.COMPARE,
            "VALIDATE": PipelineContext.VALIDATE,
            "AUDIT": PipelineContext.VALIDATE,  # AUDIT uses VALIDATE context
            "DISCOVER": PipelineContext.DISCOVER,
        }

        pipeline_context = context_mapping.get(intent_upper, PipelineContext.DISCOVER)

        # Update context if different
        if context.context != pipeline_context:
            self._logger.debug(
                f"Updating context from {context.context.value} to "
                f"{pipeline_context.value} for intent '{intent}'"
            )
            context.context = pipeline_context

        return context


# =============================================================================
# Factory Function
# =============================================================================

def create_intent_handler(
    config: Dict[str, Any],
    scout_pipeline: "ScoutPipeline",
    intent_router: Optional["IntentRouter"] = None
) -> IntentHandler:
    """
    Create a configured IntentHandler instance.

    Factory function for creating IntentHandler with proper configuration
    and dependency injection.

    Args:
        config: Configuration dictionary for the handler
        scout_pipeline: ScoutPipeline instance for agent execution
        intent_router: Optional IntentRouter for intent classification

    Returns:
        Configured IntentHandler instance

    Example:
        >>> pipeline = ScoutPipeline()
        >>> handler = create_intent_handler({"strict_mode": True}, pipeline)
    """
    return IntentHandler(
        config=config,
        scout_pipeline=scout_pipeline,
        intent_router=intent_router
    )


# =============================================================================
# Integration Helper
# =============================================================================

def integrate_with_intent_router(
    intent_handler: IntentHandler,
    intent_router: "IntentRouter"
) -> None:
    """
    Integrate IntentHandler with IntentRouter for seamless operation.

    Configures the IntentRouter to use the IntentHandler for processing
    intents that require SCOUT pipeline execution.

    Args:
        intent_handler: The IntentHandler instance
        intent_router: The IntentRouter instance to integrate with
    """
    # Register mandatory DEVIL intents with the router
    for intent in MANDATORY_DEVIL_INTENTS:
        if intent not in intent_router.list_intents():
            intent_router.add_custom_intent(
                intent=intent,
                chain=["scout_pipeline"],
                keywords=[intent.lower()],
                priority=9  # High priority for critical intents
            )

    logging.getLogger(__name__).info(
        f"Integrated IntentHandler with IntentRouter. "
        f"Registered intents: {MANDATORY_DEVIL_INTENTS}"
    )
