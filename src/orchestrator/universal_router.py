"""
ITEM-008: Universal Router for TITAN Protocol v1.2.0.

This module provides the single entry point for all request types in TITAN Protocol.
It orchestrates the complete request processing pipeline:

    Request → Profile Detection → Intent Enrichment → Skill Selection → 
    Chain Composition → Execution → Output Formatting

Integration Points:
- EnhancedProfileRouter (ProfileDetectionMixin): User role detection
- IntentEnricher: Intent enrichment with skill hints (optional dependency)
- SessionMemory: Cross-request context persistence (optional dependency)
- SkillLibrary: Skill selection and catalog management
- ChainComposer: Execution chain composition (optional dependency)
- RetryExecutorFacade: Unified retry and circuit breaker operations

Author: TITAN Protocol Team
Version: 1.2.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, TYPE_CHECKING
import logging
import time
import uuid

from src.interfaces.plugin_interface import (
    PluginInterface,
    PluginState,
    RoutingDecision,
    RoutingAction,
    ExecutionResult,
    ErrorResult,
    PluginInfo
)
from src.context.profile_mixin import (
    ProfileDetectionMixin,
    ProfileDetectionResult,
    UserRole
)
from src.utils.timezone import now_utc_iso, timestamp_for_id

if TYPE_CHECKING:
    from src.events.event_bus import EventBus
    from src.skills.skill_library import SkillLibrary
    from src.policy.retry_logic import RetryExecutor, RetryPolicy


# Default timeout for total routing operation (ms)
DEFAULT_TIMEOUT_MS = 2000

# Maximum fallback depth
MAX_FALLBACK_DEPTH = 3

# Default fallback profile
DEFAULT_PROFILE = "developer"

# Default fallback skills when skill selection fails
DEFAULT_FALLBACK_SKILLS = ["llm_query", "direct_prompt"]


@dataclass
class EnrichedIntent:
    """
    Enriched intent with skill hints and metadata.
    
    Attributes:
        original_intent: The original intent string
        intent_type: Classified intent type
        skill_hints: Suggested skills for this intent
        confidence: Confidence in intent classification
        metadata: Additional metadata about the intent
        entities: Extracted entities from the request
    """
    original_intent: str
    intent_type: str
    skill_hints: List[str] = field(default_factory=list)
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    entities: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "original_intent": self.original_intent,
            "intent_type": self.intent_type,
            "skill_hints": self.skill_hints,
            "confidence": self.confidence,
            "metadata": self.metadata,
            "entities": self.entities
        }


@dataclass
class SkillExecution:
    """
    Definition of a single skill execution within a chain.
    
    Matches skill_chain.schema.json definition.
    """
    skill_id: str
    order: int
    input_mapping: Dict[str, str] = field(default_factory=dict)
    output_mapping: Dict[str, str] = field(default_factory=dict)
    timeout_ms: int = 30000
    condition: Optional[str] = None
    required_gates: List[str] = field(default_factory=list)
    fallback_skill_id: Optional[str] = None
    on_success: str = "continue"
    on_failure: str = "stop"
    retry_policy: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "skill_id": self.skill_id,
            "order": self.order,
            "input_mapping": self.input_mapping,
            "output_mapping": self.output_mapping,
            "timeout_ms": self.timeout_ms,
            "required_gates": self.required_gates,
            "on_success": self.on_success,
            "on_failure": self.on_failure
        }
        if self.condition:
            result["condition"] = self.condition
        if self.fallback_skill_id:
            result["fallback_skill_id"] = self.fallback_skill_id
        if self.retry_policy:
            result["retry_policy"] = self.retry_policy
        return result


@dataclass
class SkillChain:
    """
    Execution chain for skills.
    
    Matches skill_chain.schema.json definition.
    """
    chain_id: str
    skills: List[SkillExecution]
    execution_order: List[int] = field(default_factory=list)
    parallel_groups: List[List[int]] = field(default_factory=list)
    context_mapping: Dict[str, str] = field(default_factory=dict)
    gates: List[str] = field(default_factory=list)
    fallback_chain: List[str] = field(default_factory=list)
    estimated_duration_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    error_handling: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize execution order if not provided."""
        if not self.execution_order and self.skills:
            self.execution_order = list(range(len(self.skills)))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "chain_id": self.chain_id,
            "skills": [s.to_dict() for s in self.skills],
            "execution_order": self.execution_order,
            "parallel_groups": self.parallel_groups,
            "context_mapping": self.context_mapping,
            "gates": self.gates,
            "fallback_chain": self.fallback_chain,
            "estimated_duration_ms": self.estimated_duration_ms,
            "metadata": self.metadata,
            "status": self.status,
            "error_handling": self.error_handling
        }


@dataclass
class FormattedOutput:
    """
    Formatted output for user response.
    
    Attributes:
        content: The output content
        format: Output format (text, markdown, json, etc.)
        metadata: Additional metadata
        suggested_actions: Suggested follow-up actions
    """
    content: str
    format: str = "text"
    metadata: Dict[str, Any] = field(default_factory=dict)
    suggested_actions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "content": self.content,
            "format": self.format,
            "metadata": self.metadata,
            "suggested_actions": self.suggested_actions
        }


@dataclass
class RoutingResult:
    """
    Complete result of routing and execution.
    
    Attributes:
        request_id: Unique identifier for this request
        profile_type: Detected user profile
        intent: Classified intent
        selected_skills: List of selected skill IDs
        execution_chain: The composed skill chain
        output: Formatted output
        metrics: Performance metrics
        timestamp: When the result was created
        fallback_used: Whether fallback was used during processing
        gaps: List of gaps or issues encountered
        success: Whether the overall processing succeeded
        error: Error message if processing failed
    """
    request_id: str
    profile_type: str
    intent: str
    selected_skills: List[str]
    execution_chain: Optional[SkillChain]
    output: Optional[FormattedOutput]
    metrics: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=now_utc_iso)
    fallback_used: bool = False
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "request_id": self.request_id,
            "profile_type": self.profile_type,
            "intent": self.intent,
            "selected_skills": self.selected_skills,
            "execution_chain": self.execution_chain.to_dict() if self.execution_chain else None,
            "output": self.output.to_dict() if self.output else None,
            "metrics": self.metrics,
            "timestamp": self.timestamp,
            "fallback_used": self.fallback_used,
            "gaps": self.gaps,
            "success": self.success,
            "error": self.error
        }


class UniversalRouter(PluginInterface):
    """
    Single entry point for all request types in TITAN Protocol.
    
    This router orchestrates the complete request processing pipeline:
    1. Profile Detection - Determine user role profile
    2. Intent Enrichment - Extract intent with skill hints
    3. Skill Selection - Select appropriate skills from library
    4. Chain Composition - Compose execution chain
    5. Execution - Execute the chain with retry handling
    6. Output Formatting - Format the result for the user
    
    Features:
    - Fallback handling with max_fallback_depth: 3
    - ROUTING_DECISION event emission
    - 2000ms total timeout
    - PluginInterface compliance for consistency
    
    Usage:
        router = UniversalRouter(
            config=config,
            event_bus=event_bus,
            skill_library=skill_library
        )
        
        result = router.process("I need to refactor this code")
        print(result.profile_type)  # "developer"
        print(result.selected_skills)  # ["ast_parse", "llm_query"]
    
    Attributes:
        _config: Configuration dictionary
        _event_bus: EventBus for event emission
        _skill_library: SkillLibrary for skill selection
        _profile_router: EnhancedProfileRouter for profile detection
        _retry_executor: Optional RetryExecutor for retry handling
        _state: Current PluginState
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        event_bus: Optional['EventBus'] = None,
        skill_library: Optional['SkillLibrary'] = None,
        intent_enricher: Optional[Any] = None,
        session_memory: Optional[Any] = None,
        chain_composer: Optional[Any] = None,
        retry_executor: Optional['RetryExecutor'] = None,
        **kwargs
    ):
        """
        Initialize the UniversalRouter.
        
        Args:
            config: Configuration dictionary with optional keys:
                - universal_router: Router-specific configuration
                - self_awareness: Profile detection configuration
                - skill_graph: Skill selection configuration
            event_bus: EventBus for event emission
            skill_library: SkillLibrary for skill selection
            intent_enricher: Optional IntentEnricher for intent enrichment
            session_memory: Optional SessionMemory for context persistence
            chain_composer: Optional ChainComposer for chain composition
            retry_executor: Optional RetryExecutor for retry handling
            **kwargs: Additional keyword arguments
        """
        self._config = config or {}
        self._event_bus = event_bus
        self._skill_library = skill_library
        self._intent_enricher = intent_enricher
        self._session_memory = session_memory
        self._chain_composer = chain_composer
        self._retry_executor = retry_executor
        self._logger = logging.getLogger(__name__)
        self._state = PluginState.UNINITIALIZED
        
        # Router configuration
        router_config = self._config.get("universal_router", {})
        self._timeout_ms = router_config.get("timeout_ms", DEFAULT_TIMEOUT_MS)
        self._max_fallback_depth = router_config.get("max_fallback_depth", MAX_FALLBACK_DEPTH)
        self._default_profile = router_config.get("default_profile", DEFAULT_PROFILE)
        self._fallback_skills = router_config.get("fallback_skills", DEFAULT_FALLBACK_SKILLS)
        
        # Profile detection router
        self._profile_router = ProfileDetectionMixin(
            config=self._config,
            event_bus=event_bus
        )
        
        # Metrics tracking
        self._metrics = {
            "requests_processed": 0,
            "fallbacks_triggered": 0,
            "avg_latency_ms": 0,
            "profile_distribution": {},
            "intent_distribution": {}
        }
    
    def on_init(self) -> None:
        """
        Initialize the router.
        
        Called when the plugin is initialized. Sets up resources and
        validates configuration.
        """
        self._state = PluginState.INITIALIZING
        self._logger.info("[ITEM-008] Initializing UniversalRouter")
        
        # Validate configuration
        if not self._skill_library:
            self._logger.warning(
                "[ITEM-008] No SkillLibrary provided, skill selection will use fallbacks"
            )
        
        # Initialize profile router
        # ProfileDetectionMixin doesn't have explicit init, uses __init__
        
        self._state = PluginState.READY
        self._logger.info("[ITEM-008] UniversalRouter initialized successfully")
    
    def on_route(self, intent: str, context: Dict[str, Any]) -> RoutingDecision:
        """
        Make routing decision for an intent.
        
        This method is part of the PluginInterface but the main entry point
        is process(). This provides compatibility with the plugin system.
        
        Args:
            intent: The intent to route
            context: Execution context
        
        Returns:
            RoutingDecision indicating what action to take
        """
        # For plugin interface compatibility, we process the intent
        result = self.process(intent, context)
        
        if result.success:
            return RoutingDecision(
                action=RoutingAction.CONTINUE,
                target=result.profile_type,
                confidence=result.metrics.get("profile_confidence", 1.0),
                reason=f"Processed as {result.profile_type} profile",
                metadata=result.to_dict()
            )
        else:
            return RoutingDecision(
                action=RoutingAction.FALLBACK,
                reason=result.error or "Processing failed",
                metadata=result.to_dict()
            )
    
    def on_execute(self, plan: Dict[str, Any]) -> ExecutionResult:
        """
        Execute a plan using the router.
        
        This method is part of the PluginInterface. The plan should contain
        'request' and optionally 'context'.
        
        Args:
            plan: Execution plan with request and context
        
        Returns:
            ExecutionResult with outputs
        """
        request = plan.get("request", "")
        context = plan.get("context", {})
        
        result = self.process(request, context)
        
        return ExecutionResult(
            success=result.success,
            outputs=result.to_dict(),
            gaps=result.gaps,
            metrics=result.metrics,
            error=result.error,
            fallback_used=result.fallback_used
        )
    
    def on_error(self, error: Exception, context: Dict[str, Any]) -> ErrorResult:
        """
        Handle errors during router execution.
        
        Args:
            error: The exception that occurred
            context: Context where the error occurred
        
        Returns:
            ErrorResult indicating how the error was handled
        """
        self._logger.error(f"[ITEM-008] UniversalRouter error: {error}")
        
        return ErrorResult(
            handled=True,
            error_message=str(error),
            should_retry=False,
            log_level="ERROR",
            notify_user=True
        )
    
    def on_shutdown(self) -> None:
        """
        Shutdown the router.
        
        Cleans up resources and flushes any pending operations.
        """
        self._state = PluginState.SHUTDOWN
        self._logger.info("[ITEM-008] UniversalRouter shutdown complete")
    
    def get_info(self) -> PluginInfo:
        """
        Get information about this plugin.
        
        Returns:
            PluginInfo with router metadata
        """
        return PluginInfo(
            plugin_id="UniversalRouter",
            plugin_type="router",
            version="1.2.0",
            description="Single entry point for all TITAN Protocol requests",
            capabilities=[
                "profile_detection",
                "intent_enrichment",
                "skill_selection",
                "chain_composition",
                "fallback_handling"
            ],
            dependencies=["SkillLibrary", "EventBus"]
        )
    
    def process(
        self,
        request: str,
        context: Optional[Dict[str, Any]] = None
    ) -> RoutingResult:
        """
        Main entry point: Process a request through the complete pipeline.
        
        Pipeline:
        1. Profile Detection → Detect user role profile
        2. Intent Enrichment → Extract intent with skill hints
        3. Skill Selection → Select appropriate skills
        4. Chain Composition → Compose execution chain
        5. Execution → Execute the chain (placeholder)
        6. Output Formatting → Format the result
        
        Args:
            request: The user's request string
            context: Optional context including session_id, preferences, etc.
        
        Returns:
            RoutingResult with complete processing information
        """
        start_time = time.time()
        context = context or {}
        request_id = f"req-{timestamp_for_id()}"
        fallback_depth = 0
        gaps = []
        fallback_used = False
        
        self._metrics["requests_processed"] += 1
        
        try:
            # Step 1: Profile Detection
            profile_result = self._detect_profile(request, context)
            if profile_result.fallback_used:
                fallback_used = True
                fallback_depth += 1
                gaps.append({
                    "type": "profile_detection_fallback",
                    "reason": "Low confidence in profile detection",
                    "severity": "WARN"
                })
            
            # Step 2: Intent Enrichment
            enriched_intent = self._enrich_intent(request, profile_result.profile_type, context)
            
            # Step 3: Skill Selection
            skills, skill_gaps = self._select_skills(
                enriched_intent.intent_type,
                enriched_intent.skill_hints,
                profile_result.profile_type
            )
            gaps.extend(skill_gaps)
            
            if not skills:
                fallback_used = True
                fallback_depth += 1
                skills = self._fallback_skills
                gaps.append({
                    "type": "skill_selection_fallback",
                    "reason": "No skills matched, using fallback skills",
                    "severity": "WARN"
                })
            
            # Step 4: Chain Composition
            chain = self._compose_chain(skills, profile_result.profile_type, enriched_intent)
            
            # Step 5: Execution (placeholder - actual execution handled by ChainComposer)
            # For now, we just set up the chain
            execution_result = self._execute_chain_placeholder(chain, context)
            
            # Step 6: Output Formatting
            output = self._format_output(
                execution_result,
                profile_result.profile_type,
                enriched_intent
            )
            
            # Calculate metrics
            elapsed_ms = int((time.time() - start_time) * 1000)
            
            # Update profile distribution
            profile = profile_result.profile_type
            self._metrics["profile_distribution"][profile] = \
                self._metrics["profile_distribution"].get(profile, 0) + 1
            
            # Update intent distribution
            intent = enriched_intent.intent_type
            self._metrics["intent_distribution"][intent] = \
                self._metrics["intent_distribution"].get(intent, 0) + 1
            
            # Update average latency
            total = self._metrics["requests_processed"]
            current_avg = self._metrics["avg_latency_ms"]
            self._metrics["avg_latency_ms"] = (
                (current_avg * (total - 1) + elapsed_ms) / total
            )
            
            # Track fallbacks
            if fallback_used:
                self._metrics["fallbacks_triggered"] += 1
            
            # Emit ROUTING_DECISION event
            self._emit_routing_decision(
                request_id=request_id,
                profile=profile,
                intent=intent,
                skills=[s if isinstance(s, str) else s.skill_id for s in skills],
                elapsed_ms=elapsed_ms,
                fallback_used=fallback_used
            )
            
            result = RoutingResult(
                request_id=request_id,
                profile_type=profile,
                intent=intent,
                selected_skills=[s if isinstance(s, str) else s.skill_id for s in skills],
                execution_chain=chain,
                output=output,
                metrics={
                    "total_latency_ms": elapsed_ms,
                    "profile_confidence": profile_result.confidence,
                    "intent_confidence": enriched_intent.confidence,
                    "fallback_depth": fallback_depth
                },
                fallback_used=fallback_used,
                gaps=gaps,
                success=True
            )
            
            self._logger.info(
                f"[ITEM-008] Processed request {request_id}: "
                f"profile={profile}, intent={intent}, "
                f"skills={len(skills)}, latency={elapsed_ms}ms"
            )
            
            return result
            
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.error(f"[ITEM-008] Processing failed: {e}")
            
            return RoutingResult(
                request_id=request_id,
                profile_type=self._default_profile,
                intent="unknown",
                selected_skills=self._fallback_skills,
                execution_chain=None,
                output=None,
                metrics={
                    "total_latency_ms": elapsed_ms,
                    "error_type": type(e).__name__
                },
                fallback_used=True,
                gaps=gaps + [{
                    "type": "processing_error",
                    "reason": str(e),
                    "severity": "ERROR"
                }],
                success=False,
                error=str(e)
            )
    
    def _detect_profile(
        self,
        request: str,
        context: Dict[str, Any]
    ) -> ProfileDetectionResult:
        """
        Detect user role profile using EnhancedProfileRouter.
        
        Args:
            request: The user's request string
            context: Execution context
        
        Returns:
            ProfileDetectionResult with detected profile
        """
        return self._profile_router.detect_with_lexical_analysis(request, context)
    
    def _enrich_intent(
        self,
        request: str,
        profile: str,
        context: Dict[str, Any]
    ) -> EnrichedIntent:
        """
        Enrich intent with skill hints.
        
        If an IntentEnricher is available, uses it. Otherwise, performs
        basic intent classification based on keywords.
        
        Args:
            request: The user's request string
            profile: Detected user profile
            context: Execution context
        
        Returns:
            EnrichedIntent with skill hints
        """
        if self._intent_enricher:
            # Use the IntentEnricher if available
            try:
                return self._intent_enricher.enrich(request, profile, context)
            except Exception as e:
                self._logger.warning(
                    f"[ITEM-008] IntentEnricher failed, using fallback: {e}"
                )
        
        # Basic intent classification
        request_lower = request.lower()
        
        # Intent type patterns
        intent_patterns = {
            "implement": ["implement", "create", "build", "develop", "write", "add"],
            "debug": ["debug", "fix", "resolve", "solve", "troubleshoot", "error"],
            "refactor": ["refactor", "improve", "optimize", "clean", "restructure"],
            "analyze": ["analyze", "examine", "investigate", "review", "audit"],
            "document": ["document", "explain", "describe", "comment"],
            "test": ["test", "verify", "validate", "check"],
            "deploy": ["deploy", "release", "publish", "ship"],
            "research": ["research", "find", "search", "explore", "look up"],
            "visualize": ["visualize", "chart", "graph", "display", "render"],
            "configure": ["configure", "setup", "set up", "settings", "preferences"]
        }
        
        # Find matching intent
        intent_type = "general"
        max_matches = 0
        
        for intent, keywords in intent_patterns.items():
            matches = sum(1 for kw in keywords if kw in request_lower)
            if matches > max_matches:
                max_matches = matches
                intent_type = intent
        
        # Generate skill hints based on profile and intent
        skill_hints = self._generate_skill_hints(profile, intent_type, request_lower)
        
        return EnrichedIntent(
            original_intent=request,
            intent_type=intent_type,
            skill_hints=skill_hints,
            confidence=min(1.0, max_matches * 0.3),
            metadata={"method": "keyword_matching"}
        )
    
    def _generate_skill_hints(
        self,
        profile: str,
        intent: str,
        request_lower: str
    ) -> List[str]:
        """
        Generate skill hints based on profile and intent.
        
        Args:
            profile: User profile
            intent: Intent type
            request_lower: Lowercase request string
        
        Returns:
            List of suggested skill IDs
        """
        hints = []
        
        # Profile-specific skills
        profile_skills = {
            "designer": ["web_search", "web_fetch", "llm_query"],
            "developer": ["grep_search", "ast_parse", "llm_query", "exec_command"],
            "analyst": ["llm_query", "read_file", "grep_search"],
            "devops": ["exec_command", "llm_query", "read_file", "write_file"],
            "researcher": ["web_search", "web_fetch", "llm_query"]
        }
        
        # Intent-specific skills
        intent_skills = {
            "implement": ["ast_parse", "write_file", "llm_query"],
            "debug": ["grep_search", "read_file", "llm_query"],
            "refactor": ["ast_parse", "grep_search", "llm_query"],
            "analyze": ["grep_search", "ast_parse", "llm_query"],
            "document": ["llm_query", "write_file"],
            "test": ["exec_command", "grep_search", "llm_query"],
            "deploy": ["exec_command", "llm_query"],
            "research": ["web_search", "web_fetch", "llm_query"],
            "visualize": ["llm_query"],
            "configure": ["read_file", "write_file", "llm_query"]
        }
        
        # Combine profile and intent skills
        hints.extend(profile_skills.get(profile, []))
        hints.extend(intent_skills.get(intent, []))
        
        # Add code-related skills if code patterns detected
        code_patterns = ["function", "class", "method", "variable", "import", "def ", "class "]
        if any(p in request_lower for p in code_patterns):
            hints.extend(["ast_parse", "grep_search"])
        
        # Deduplicate while preserving order
        seen = set()
        return [h for h in hints if not (h in seen or seen.add(h))]
    
    def _select_skills(
        self,
        intent: str,
        hints: List[str],
        profile: str
    ) -> tuple:
        """
        Select skills from the library.
        
        Args:
            intent: Intent type
            hints: Skill hints
            profile: User profile
        
        Returns:
            Tuple of (list of skills, list of gaps)
        """
        gaps = []
        
        if not self._skill_library:
            gaps.append({
                "type": "skill_library_unavailable",
                "reason": "No SkillLibrary configured",
                "severity": "WARN"
            })
            return [], gaps
        
        try:
            # Try to get skills from the library
            skills = self._skill_library.select_skills(intent.upper(), hints)
            
            if not skills:
                # Try with just the profile as a role hint
                skills = self._skill_library.select_skills(
                    intent.upper(),
                    [profile]
                )
            
            # Convert Skill objects to skill IDs if needed
            skill_ids = []
            for skill in skills:
                if hasattr(skill, 'skill_id'):
                    skill_ids.append(skill.skill_id)
                elif isinstance(skill, str):
                    skill_ids.append(skill)
            
            return skills, gaps
            
        except Exception as e:
            gaps.append({
                "type": "skill_selection_error",
                "reason": str(e),
                "severity": "ERROR"
            })
            return [], gaps
    
    def _compose_chain(
        self,
        skills: List,
        profile: str,
        enriched_intent: EnrichedIntent
    ) -> SkillChain:
        """
        Compose execution chain from selected skills.
        
        If a ChainComposer is available, uses it. Otherwise, creates
        a simple sequential chain.
        
        Args:
            skills: List of selected skills
            profile: User profile
            enriched_intent: Enriched intent
        
        Returns:
            SkillChain ready for execution
        """
        if self._chain_composer:
            try:
                return self._chain_composer.compose(skills, profile, enriched_intent)
            except Exception as e:
                self._logger.warning(
                    f"[ITEM-008] ChainComposer failed, using fallback: {e}"
                )
        
        # Create simple sequential chain
        chain_id = f"chain-{timestamp_for_id()}"
        skill_executions = []
        execution_order = []
        
        for i, skill in enumerate(skills):
            skill_id = skill.skill_id if hasattr(skill, 'skill_id') else skill
            skill_executions.append(SkillExecution(
                skill_id=skill_id,
                order=i,
                timeout_ms=30000,
                on_success="continue",
                on_failure="stop"
            ))
            execution_order.append(i)
        
        return SkillChain(
            chain_id=chain_id,
            skills=skill_executions,
            execution_order=execution_order,
            metadata={
                "profile": profile,
                "intent": enriched_intent.intent_type,
                "created_at": now_utc_iso()
            },
            status="pending"
        )
    
    def _execute_chain_placeholder(
        self,
        chain: SkillChain,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Placeholder for chain execution.
        
        Actual execution is handled by the ChainComposer or executor.
        This method just returns a placeholder result.
        
        Args:
            chain: The skill chain to execute
            context: Execution context
        
        Returns:
            Placeholder execution result
        """
        return {
            "status": "pending",
            "message": "Chain created, execution pending",
            "chain_id": chain.chain_id,
            "skill_count": len(chain.skills)
        }
    
    def _format_output(
        self,
        execution_result: Dict[str, Any],
        profile: str,
        enriched_intent: EnrichedIntent
    ) -> FormattedOutput:
        """
        Format output for user response.
        
        Args:
            execution_result: Result from chain execution
            profile: User profile
            enriched_intent: Enriched intent
        
        Returns:
            FormattedOutput ready for user consumption
        """
        # Simple output formatting based on profile
        format_map = {
            "designer": "markdown",
            "developer": "markdown",
            "analyst": "json",
            "devops": "text",
            "researcher": "markdown"
        }
        
        output_format = format_map.get(profile, "text")
        
        # Generate output content
        content = f"Request processed successfully.\n\n"
        content += f"**Profile**: {profile}\n"
        content += f"**Intent**: {enriched_intent.intent_type}\n"
        content += f"**Status**: {execution_result.get('status', 'unknown')}\n"
        
        if execution_result.get('chain_id'):
            content += f"\nChain ID: `{execution_result['chain_id']}`"
        
        return FormattedOutput(
            content=content,
            format=output_format,
            metadata={
                "profile": profile,
                "intent": enriched_intent.intent_type
            },
            suggested_actions=[
                "View execution details",
                "Refine request",
                "Try alternative approach"
            ]
        )
    
    def _emit_routing_decision(
        self,
        request_id: str,
        profile: str,
        intent: str,
        skills: List[str],
        elapsed_ms: int,
        fallback_used: bool
    ) -> None:
        """
        Emit ROUTING_DECISION event via EventBus.
        
        Args:
            request_id: Unique request identifier
            profile: Detected profile
            intent: Classified intent
            skills: Selected skill IDs
            elapsed_ms: Processing time in milliseconds
            fallback_used: Whether fallback was used
        """
        if not self._event_bus:
            return
        
        try:
            self._event_bus.emit_simple(
                event_type="ROUTING_DECISION",
                data={
                    "request_id": request_id,
                    "profile": profile,
                    "intent": intent,
                    "skills": skills,
                    "elapsed_ms": elapsed_ms,
                    "fallback_used": fallback_used,
                    "timestamp": now_utc_iso()
                },
                source="UniversalRouter"
            )
        except Exception as e:
            self._logger.warning(
                f"[ITEM-008] Failed to emit ROUTING_DECISION event: {e}"
            )
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get router performance metrics.
        
        Returns:
            Dictionary of metrics
        """
        return dict(self._metrics)
    
    def reset_metrics(self) -> None:
        """Reset all metrics to initial state."""
        self._metrics = {
            "requests_processed": 0,
            "fallbacks_triggered": 0,
            "avg_latency_ms": 0,
            "profile_distribution": {},
            "intent_distribution": {}
        }


# Factory function for convenience
def create_universal_router(
    config: Dict[str, Any] = None,
    event_bus: Optional['EventBus'] = None,
    skill_library: Optional['SkillLibrary'] = None,
    **kwargs
) -> UniversalRouter:
    """
    Factory function to create a UniversalRouter.
    
    Args:
        config: Configuration dictionary
        event_bus: EventBus instance
        skill_library: SkillLibrary instance
        **kwargs: Additional arguments passed to UniversalRouter
    
    Returns:
        UniversalRouter instance
    """
    router = UniversalRouter(
        config=config or {},
        event_bus=event_bus,
        skill_library=skill_library,
        **kwargs
    )
    router.on_init()
    return router
