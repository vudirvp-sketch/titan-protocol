"""
ITEM_006: Intent Enrichment Pipeline for TITAN Protocol v1.2.0.

This module transforms raw_intent into enriched_intent with skill hints,
role hints, and critical gates based on intent classification and
user role profile detection.

Pipeline Stages:
1. sanitize - Security sanitization with prompt injection detection
2. normalize - Clean and normalize request text
3. classify - Run IntentRouter classification
4. detect_profile - Run EnhancedProfileRouter for user role detection
5. enrich - Add skill_hints, role_hints, critical_gates
6. emit - Emit EVENT_CONTEXT_READY event

Security Features:
- Prompt injection detection with REJECT action
- HTML escaping for XSS prevention
- Control character removal
- Max request length enforcement (10000 chars)

Integration:
- IntentRouter: Intent classification
- EnhancedProfileRouter: User role profile detection
- EventBus: Event emission for EVENT_CONTEXT_READY

Author: TITAN Protocol Team
Version: 1.2.0
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, TYPE_CHECKING
import re
import html
import logging
from enum import Enum

from src.utils.timezone import now_utc_iso

if TYPE_CHECKING:
    from src.policy.intent_router import IntentRouter, IntentResult
    from src.context.profile_mixin import EnhancedProfileRouter, ProfileDetectionResult
    from src.events.event_bus import EventBus


class SanitizationAction(Enum):
    """Actions to take when security issues are detected."""
    REJECT = "REJECT"      # Reject the request entirely
    ESCAPE = "ESCAPE"      # Escape the problematic content
    REMOVE = "REMOVE"      # Remove the problematic content
    WARN = "WARN"          # Log warning but allow


@dataclass
class SanitizationResult:
    """
    Result of input sanitization.
    
    Attributes:
        sanitized_text: The sanitized text
        was_sanitized: Whether any sanitization was applied
        security_flags: List of security issues detected
        action_taken: Action that was taken (if any)
        rejected: Whether the request was rejected
        rejection_reason: Reason for rejection (if rejected)
    """
    sanitized_text: str
    was_sanitized: bool = False
    security_flags: List[str] = field(default_factory=list)
    action_taken: Optional[str] = None
    rejected: bool = False
    rejection_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "sanitized_text": self.sanitized_text,
            "was_sanitized": self.was_sanitized,
            "security_flags": self.security_flags,
            "action_taken": self.action_taken,
            "rejected": self.rejected,
            "rejection_reason": self.rejection_reason
        }


@dataclass
class EnrichedIntent:
    """
    Enriched intent with skill hints and metadata.
    
    Attributes:
        original_request: The original user request
        normalized_request: The normalized request text
        intent: Classified intent type
        intent_confidence: Confidence of intent classification (0.0-1.0)
        profile_type: Detected user role profile
        profile_confidence: Confidence of profile detection (0.0-1.0)
        skill_hints: List of skill hints for skill selection
        role_hints: List of role hints for routing
        critical_gates: List of critical gates to check
        abstraction_contracts: Contracts for abstraction boundaries
        timestamp: When the enrichment occurred
        sanitized: Whether the request was sanitized
        security_flags: Security issues detected during sanitization
    """
    original_request: str
    normalized_request: str
    intent: str
    intent_confidence: float
    profile_type: str
    profile_confidence: float
    skill_hints: List[str] = field(default_factory=list)
    role_hints: List[str] = field(default_factory=list)
    critical_gates: List[str] = field(default_factory=list)
    abstraction_contracts: Dict[str, str] = field(default_factory=dict)
    timestamp: str = field(default_factory=now_utc_iso)
    sanitized: bool = False
    security_flags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "original_request": self.original_request,
            "normalized_request": self.normalized_request,
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "profile_type": self.profile_type,
            "profile_confidence": self.profile_confidence,
            "skill_hints": self.skill_hints,
            "role_hints": self.role_hints,
            "critical_gates": self.critical_gates,
            "abstraction_contracts": self.abstraction_contracts,
            "timestamp": self.timestamp,
            "sanitized": self.sanitized,
            "security_flags": self.security_flags
        }


# =============================================================================
# SKILL HINT MAPPING
# =============================================================================

SKILL_HINT_MAPPING: Dict[str, Dict[str, List[str]]] = {
    "developer": {
        "refactor": ["cycle_detector", "dependency_resolver", "patch_engine"],
        "debug": ["error_analyzer", "trace_collector", "fix_generator"],
        "implement": ["ast_parse", "diff_applier", "test_runner"],
        "audit": ["security_scanner", "crossref_validator", "gap_detector"],
        "code_review": ["security_scanner", "style_checker", "diff_generator"],
        "test_gen": ["coverage_analyzer", "test_generator", "mock_factory"],
        "optimization": ["performance_analyzer", "bottleneck_detector", "optimizer"],
        "migration": ["compatibility_checker", "migration_planner", "version_adapter"],
        "feature_add": ["impact_analyzer", "implementation_planner", "integration_tester"],
    },
    "designer": {
        "research": ["web_search", "doc_generator", "insight_collector"],
        "visualize": ["graph_renderer", "export_tool", "template_engine"],
        "document": ["template_engine", "doc_generator", "diagram_builder"],
        "code_review": ["ui_checker", "accessibility_auditor", "style_linter"],
        "feature_add": ["prototype_builder", "component_library", "design_system"],
    },
    "analyst": {
        "validate": ["schema_validator", "crossref_validator", "data_quality_checker"],
        "synthesize": ["data_merger", "report_generator", "insight_extractor"],
        "report": ["metrics_collector", "dashboard_builder", "export_formatter"],
        "optimization": ["bottleneck_analyzer", "trend_detector", "forecast_engine"],
        "debug": ["data_profiler", "anomaly_detector", "lineage_tracker"],
    },
    "devops": {
        "deploy": ["helm_renderer", "kubectl_runner", "health_checker"],
        "monitor": ["metrics_scraper", "alert_manager", "log_aggregator"],
        "configure": ["config_renderer", "secret_manager", "env_validator"],
        "debug": ["log_analyzer", "trace_collector", "incident_responder"],
        "migration": ["infrastructure_planner", "state_migrator", "rollback_manager"],
        "security_audit": ["vulnerability_scanner", "compliance_checker", "security_reporter"],
    },
    "researcher": {
        "explore": ["web_search", "paper_fetcher", "citation_extractor"],
        "analyze": ["data_processor", "statistical_analyzer", "visualization_engine"],
        "document": ["latex_renderer", "bibliography_manager", "figure_generator"],
        "validate": ["source_validator", "reproducibility_checker", "peer_review_helper"],
        "feature_add": ["hypothesis_tester", "experiment_runner", "result_aggregator"],
    },
}

# Default skill hints for unknown intent/profile combinations
DEFAULT_SKILL_HINTS: List[str] = ["general_processor", "output_formatter"]


# =============================================================================
# CRITICAL GATE MAPPING
# =============================================================================

CRITICAL_GATE_MAPPING: Dict[str, Dict[str, List[str]]] = {
    "developer": {
        "refactor": ["GATE-02", "GATE-04"],
        "debug": ["GATE-02"],
        "implement": ["GATE-02", "GATE-03", "GATE-04"],
        "code_review": ["GATE-02"],
        "test_gen": ["GATE-02", "GATE-04"],
        "optimization": ["GATE-02", "GATE-04"],
        "migration": ["GATE-01", "GATE-02", "GATE-04"],
        "security_audit": ["GATE-02", "GATE-04", "GATE-05"],
        "feature_add": ["GATE-02", "GATE-03"],
    },
    "designer": {
        "research": ["GATE-02"],
        "visualize": ["GATE-02"],
        "document": ["GATE-02"],
        "feature_add": ["GATE-02", "GATE-03"],
    },
    "analyst": {
        "validate": ["GATE-02", "GATE-04"],
        "report": ["GATE-02"],
        "synthesize": ["GATE-02"],
        "debug": ["GATE-02"],
    },
    "devops": {
        "deploy": ["GATE-01", "GATE-02", "GATE-05"],
        "monitor": ["GATE-02"],
        "configure": ["GATE-02", "GATE-05"],
        "debug": ["GATE-02"],
        "migration": ["GATE-01", "GATE-02", "GATE-04", "GATE-05"],
        "security_audit": ["GATE-02", "GATE-05"],
    },
    "researcher": {
        "explore": ["GATE-02"],
        "analyze": ["GATE-02", "GATE-04"],
        "document": ["GATE-02"],
        "validate": ["GATE-02", "GATE-04"],
    },
}

# Default gates for unknown combinations
DEFAULT_CRITICAL_GATES: List[str] = ["GATE-02"]


# =============================================================================
# PROMPT INJECTION PATTERNS
# =============================================================================

PROMPT_INJECTION_PATTERNS: List[str] = [
    r"ignore\s+(previous|all|above)\s+(instructions?|prompts?|rules?)",
    r"disregard\s+(all|above|previous)",
    r"system\s+prompt",
    r"you\s+are\s+now",
    r"act\s+as\s+if",
    r"forget\s+(everything|all|previous)",
    r"pretend\s+(you\s+are|to\s+be)",
    r"new\s+instructions?",
    r"override\s+(previous|all|default)",
    r"bypass\s+(all|security|restrictions?)",
    r"sudo\s+mode",
    r"developer\s+mode",
    r"debug\s+mode",
    r"admin\s+mode",
    r"<\|.*?\|>",  # Special token patterns
    r"\[SYSTEM\]",
    r"\[INST\]",
    r"\[/INST\]",
]

# Compile patterns for performance
COMPILED_INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in PROMPT_INJECTION_PATTERNS
]


# =============================================================================
# EVENT TYPE CONSTANT
# =============================================================================

EVENT_CONTEXT_READY = "EVENT_CONTEXT_READY"


class IntentEnricher:
    """
    ITEM_006: Transform raw_intent -> enriched_intent with skill hints.
    
    The IntentEnricher processes user requests through a pipeline of stages
    to produce an enriched intent with skill hints, role hints, and critical
    gates for routing decisions.
    
    Pipeline Stages:
        1. sanitize - Security sanitization
        2. normalize - Text normalization
        3. classify - Intent classification via IntentRouter
        4. detect_profile - User role detection via EnhancedProfileRouter
        5. enrich - Add hints and gates
        6. emit - Emit EVENT_CONTEXT_READY event
    
    Security Features:
        - Prompt injection detection with REJECT action
        - HTML escaping for XSS prevention
        - Control character removal
        - Max request length enforcement (10000 chars)
    
    Usage:
        from src.policy.intent_router import IntentRouter
        from src.context.profile_mixin import EnhancedProfileRouter
        from src.events.event_bus import EventBus
        
        intent_router = IntentRouter()
        profile_router = EnhancedProfileRouter()
        event_bus = EventBus()
        
        enricher = IntentEnricher(
            config=config,
            intent_router=intent_router,
            profile_router=profile_router,
            event_bus=event_bus
        )
        
        result = enricher.enrich("Refactor the authentication module")
        print(result.intent)        # "refactor"
        print(result.profile_type)  # "developer"
        print(result.skill_hints)   # ["cycle_detector", "dependency_resolver", ...]
    """
    
    # Configuration defaults
    DEFAULT_MAX_REQUEST_LENGTH = 10000
    DEFAULT_MIN_CONFIDENCE = 0.3
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        intent_router: Optional["IntentRouter"] = None,
        profile_router: Optional["EnhancedProfileRouter"] = None,
        event_bus: Optional["EventBus"] = None,
        retry_facade: Optional[Any] = None
    ):
        """
        Initialize IntentEnricher.
        
        Args:
            config: Configuration dictionary
            intent_router: IntentRouter instance for intent classification
            profile_router: EnhancedProfileRouter for user role detection
            event_bus: EventBus for event emission
            retry_facade: RetryExecutorFacade for retry handling (v1.2)
        """
        self._config = config or {}
        self._intent_router = intent_router
        self._profile_router = profile_router
        self._event_bus = event_bus
        self._retry_facade = retry_facade
        self._logger = logging.getLogger(__name__)
        
        # Load configuration
        security_config = self._config.get("security", {})
        self._max_request_length = security_config.get(
            "max_request_length", 
            self.DEFAULT_MAX_REQUEST_LENGTH
        )
        self._min_confidence = self._config.get(
            "min_confidence",
            self.DEFAULT_MIN_CONFIDENCE
        )
        
        # Detection enhancement flags
        self._detect_unicode_homoglyphs = True
        self._detect_base64 = True
        self._detect_rot13 = True
        self._detect_case_variations = True
    
    def enrich(
        self, 
        raw_request: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> EnrichedIntent:
        """
        Transform raw request into enriched intent.
        
        Pipeline: sanitize -> normalize -> classify -> detect_profile -> enrich -> emit
        
        Args:
            raw_request: The raw user request string
            context: Optional context dictionary (session_id, etc.)
        
        Returns:
            EnrichedIntent with classification, profile, and hints
        
        Raises:
            ValueError: If request is rejected due to security issues
        """
        context = context or {}
        
        # Stage 1: Sanitize
        sanitization_result = self._sanitize(raw_request)
        if sanitization_result.rejected:
            self._logger.warning(
                f"[ITEM_006] Request rejected: {sanitization_result.rejection_reason}"
            )
            raise ValueError(f"Request rejected: {sanitization_result.rejection_reason}")
        
        # Stage 2: Normalize
        normalized = self._normalize(sanitization_result.sanitized_text)
        
        # Stage 3: Classify intent
        intent_result = self._classify(normalized)
        
        # Stage 4: Detect profile
        profile_result = self._detect_profile(normalized, context)
        
        # Stage 5: Enrich with hints
        enriched = self._enrich(
            original_request=raw_request,
            normalized_request=normalized,
            intent_result=intent_result,
            profile_result=profile_result,
            sanitization_result=sanitization_result
        )
        
        # Stage 6: Emit event
        self._emit_context_ready(enriched)
        
        self._logger.info(
            f"[ITEM_006] Enriched intent: {enriched.intent} "
            f"(profile: {enriched.profile_type}, "
            f"skill_hints: {len(enriched.skill_hints)})"
        )
        
        return enriched
    
    def _sanitize(self, text: str) -> SanitizationResult:
        """
        Sanitize input for security.
        
        Checks:
        1. Max request length
        2. Prompt injection patterns
        3. HTML injection
        4. Control characters
        
        Args:
            text: Input text to sanitize
        
        Returns:
            SanitizationResult with sanitized text and flags
        """
        security_flags: List[str] = []
        sanitized = text
        was_sanitized = False
        
        # Check max length
        if len(text) > self._max_request_length:
            security_flags.append("max_length_exceeded")
            sanitized = sanitized[:self._max_request_length]
            was_sanitized = True
            self._logger.warning(
                f"[ITEM_006] Request truncated from {len(text)} to "
                f"{self._max_request_length} characters"
            )
        
        # Check for prompt injection (REJECT action)
        injection_detected = self._detect_prompt_injection(sanitized)
        if injection_detected:
            security_flags.append("prompt_injection_detected")
            self._logger.error(
                f"[ITEM_006] Prompt injection detected: {injection_detected}"
            )
            return SanitizationResult(
                sanitized_text="",
                was_sanitized=True,
                security_flags=security_flags,
                action_taken="REJECT",
                rejected=True,
                rejection_reason=f"Prompt injection detected: {injection_detected}"
            )
        
        # Check for Unicode homoglyphs (enhanced detection)
        if self._detect_unicode_homoglyphs:
            homoglyph_result = self._check_unicode_homoglyphs(sanitized)
            if homoglyph_result:
                security_flags.append("unicode_homoglyph_detected")
                self._logger.warning(
                    f"[ITEM_006] Unicode homoglyph detected: {homoglyph_result}"
                )
                # Not rejecting, just flagging
        
        # HTML escaping (ESCAPE action)
        if self._contains_html(sanitized):
            security_flags.append("html_injection_detected")
            sanitized = html.escape(sanitized)
            was_sanitized = True
        
        # Control character removal (REMOVE action)
        sanitized, control_removed = self._remove_control_characters(sanitized)
        if control_removed:
            security_flags.append("control_characters_removed")
            was_sanitized = True
        
        return SanitizationResult(
            sanitized_text=sanitized,
            was_sanitized=was_sanitized,
            security_flags=security_flags,
            action_taken="SANITIZE" if was_sanitized else None,
            rejected=False
        )
    
    def _detect_prompt_injection(self, text: str) -> Optional[str]:
        """
        Detect prompt injection patterns.
        
        Checks for common injection patterns including:
        - Direct pattern matches
        - Case variations
        - Base64 encoded variants
        - ROT13 variants
        - Unicode homoglyphs
        
        Args:
            text: Text to check
        
        Returns:
            Detected pattern description, or None if clean
        """
        text_lower = text.lower()
        
        # Direct pattern matching
        for pattern in COMPILED_INJECTION_PATTERNS:
            match = pattern.search(text)
            if match:
                return f"pattern:{match.group()}"
        
        # Case variation detection
        if self._detect_case_variations:
            # Check for mixed case versions of injection phrases
            common_injections = [
                "ignore previous instructions",
                "disregard all above",
                "system prompt",
                "you are now",
                "act as if",
                "forget everything"
            ]
            for injection in common_injections:
                # Check with various case patterns
                if injection.replace(" ", "") in text_lower.replace(" ", ""):
                    return f"case_variation:{injection}"
        
        # Base64 detection (enhanced)
        if self._detect_base64:
            base64_pattern = self._check_base64_injection(text)
            if base64_pattern:
                return f"base64_encoded:{base64_pattern}"
        
        # ROT13 detection (enhanced)
        if self._detect_rot13:
            rot13_pattern = self._check_rot13_injection(text)
            if rot13_pattern:
                return f"rot13_variant:{rot13_pattern}"
        
        return None
    
    def _check_base64_injection(self, text: str) -> Optional[str]:
        """
        Check for base64 encoded injection attempts.
        
        Args:
            text: Text to check
        
        Returns:
            Detected pattern or None
        """
        import base64
        
        # Look for potential base64 strings
        base64_pattern = re.compile(r'[A-Za-z0-9+/]{20,}={0,2}')
        matches = base64_pattern.findall(text)
        
        for match in matches:
            try:
                decoded = base64.b64decode(match).decode('utf-8', errors='ignore')
                # Check decoded content for injection patterns
                for pattern in COMPILED_INJECTION_PATTERNS:
                    if pattern.search(decoded):
                        return match[:20] + "..."
            except Exception:
                continue
        
        return None
    
    def _check_rot13_injection(self, text: str) -> Optional[str]:
        """
        Check for ROT13 encoded injection attempts.
        
        Args:
            text: Text to check
        
        Returns:
            Detected pattern or None
        """
        import codecs
        
        # Apply ROT13 and check for injection patterns
        rot13_decoded = codecs.decode(text, 'rot_13')
        
        for pattern in COMPILED_INJECTION_PATTERNS:
            if pattern.search(rot13_decoded):
                return f"rot13_detected"
        
        return None
    
    def _check_unicode_homoglyphs(self, text: str) -> Optional[str]:
        """
        Check for Unicode homoglyphs that might be used to bypass detection.
        
        Args:
            text: Text to check
        
        Returns:
            Detected homoglyph info or None
        """
        # Common homoglyph mappings
        homoglyphs = {
            '\u0430': 'a',  # Cyrillic a
            '\u0435': 'e',  # Cyrillic e
            '\u043e': 'o',  # Cyrillic o
            '\u0440': 'p',  # Cyrillic p
            '\u0441': 'c',  # Cyrillic c
            '\u0443': 'y',  # Cyrillic y
            '\u0445': 'x',  # Cyrillic x
            '\u0456': 'i',  # Cyrillic i
            '\u2010': '-',  # Hyphen
            '\u2011': '-',  # Non-breaking hyphen
            '\u2012': '-',  # Figure dash
            '\u2013': '-',  # En dash
            '\u2014': '-',  # Em dash
        }
        
        found = []
        for char in text:
            if char in homoglyphs:
                found.append(f"{char}->{homoglyphs[char]}")
        
        if found:
            return f"homoglyphs:{len(found)}"
        
        return None
    
    def _contains_html(self, text: str) -> bool:
        """
        Check if text contains HTML tags.
        
        Args:
            text: Text to check
        
        Returns:
            True if HTML tags detected
        """
        html_pattern = re.compile(r'<[^>]+>')
        return bool(html_pattern.search(text))
    
    def _remove_control_characters(self, text: str) -> tuple[str, bool]:
        """
        Remove control characters from text.
        
        Args:
            text: Text to clean
        
        Returns:
            Tuple of (cleaned_text, was_modified)
        """
        # Remove control characters except newlines and tabs
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        return cleaned, cleaned != text
    
    def _normalize(self, text: str) -> str:
        """
        Normalize text for processing.
        
        Operations:
        - Strip whitespace
        - Normalize Unicode
        - Collapse multiple spaces
        - Remove leading/trailing whitespace
        
        Args:
            text: Text to normalize
        
        Returns:
            Normalized text
        """
        import unicodedata
        
        # Normalize Unicode
        normalized = unicodedata.normalize('NFKC', text)
        
        # Collapse whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Strip
        normalized = normalized.strip()
        
        return normalized
    
    def _classify(self, text: str) -> "IntentResult":
        """
        Classify intent using IntentRouter.
        
        Args:
            text: Normalized text to classify
        
        Returns:
            IntentResult from IntentRouter
        """
        if self._intent_router:
            return self._intent_router.classify_intent(text)
        
        # Fallback: simple keyword matching
        self._logger.warning(
            "[ITEM_006] IntentRouter not available, using fallback classification"
        )
        
        # Import locally to avoid circular imports
        from src.policy.intent_router import IntentResult
        
        keywords = {
            "refactor": ["refactor", "restructure", "reorganize"],
            "debug": ["debug", "fix", "error", "bug", "issue"],
            "implement": ["implement", "add", "create", "build"],
            "code_review": ["review", "check", "audit"],
            "test_gen": ["test", "spec", "coverage"],
            "deploy": ["deploy", "release", "push"],
            "document": ["document", "readme", "doc"],
        }
        
        text_lower = text.lower()
        for intent, words in keywords.items():
            if any(word in text_lower for word in words):
                return IntentResult(
                    intent=intent,
                    confidence=0.6,
                    keywords_matched=[w for w in words if w in text_lower],
                    chain=[],
                    alternatives=[]
                )
        
        return IntentResult(
            intent="code_review",
            confidence=0.3,
            keywords_matched=[],
            chain=[],
            alternatives=[]
        )
    
    def _detect_profile(
        self, 
        text: str, 
        context: Optional[Dict[str, Any]]
    ) -> "ProfileDetectionResult":
        """
        Detect user role profile using EnhancedProfileRouter.
        
        Args:
            text: Normalized text
            context: Optional context with session_id
        
        Returns:
            ProfileDetectionResult from EnhancedProfileRouter
        """
        if self._profile_router:
            return self._profile_router.detect_with_lexical_analysis(text, context)
        
        # Fallback: simple profile detection
        self._logger.warning(
            "[ITEM_006] EnhancedProfileRouter not available, using fallback detection"
        )
        
        # Import locally
        from src.context.profile_mixin import ProfileDetectionResult
        
        profile_keywords = {
            "developer": ["code", "debug", "refactor", "implement", "function", "class"],
            "designer": ["design", "ui", "ux", "visual", "layout", "prototype"],
            "analyst": ["analyze", "report", "metric", "data", "dashboard"],
            "devops": ["deploy", "server", "config", "kubernetes", "docker"],
            "researcher": ["research", "explore", "paper", "citation", "study"],
        }
        
        text_lower = text.lower()
        scores = {}
        
        for profile, keywords in profile_keywords.items():
            matches = sum(1 for kw in keywords if kw in text_lower)
            scores[profile] = matches / len(keywords)
        
        best_profile = max(scores, key=scores.get) if scores else "developer"
        best_score = scores.get(best_profile, 0.0)
        
        return ProfileDetectionResult(
            profile_type=best_profile,
            confidence=best_score,
            detection_method="fallback",
            scores=scores,
            indicators_matched=[],
            fallback_used=True
        )
    
    def _enrich(
        self,
        original_request: str,
        normalized_request: str,
        intent_result: "IntentResult",
        profile_result: "ProfileDetectionResult",
        sanitization_result: SanitizationResult
    ) -> EnrichedIntent:
        """
        Enrich intent with skill hints and critical gates.
        
        Args:
            original_request: Original user request
            normalized_request: Normalized request
            intent_result: Result from IntentRouter
            profile_result: Result from EnhancedProfileRouter
            sanitization_result: Result from sanitization
        
        Returns:
            EnrichedIntent with all enrichment data
        """
        intent = intent_result.intent
        profile = profile_result.profile_type
        
        # Get skill hints
        skill_hints = self._get_skill_hints(intent, profile)
        
        # Get role hints
        role_hints = self._get_role_hints(intent, profile)
        
        # Get critical gates
        critical_gates = self._get_critical_gates(intent, profile)
        
        # Get abstraction contracts
        abstraction_contracts = self._get_abstraction_contracts(intent, profile)
        
        return EnrichedIntent(
            original_request=original_request,
            normalized_request=normalized_request,
            intent=intent,
            intent_confidence=intent_result.confidence,
            profile_type=profile,
            profile_confidence=profile_result.confidence,
            skill_hints=skill_hints,
            role_hints=role_hints,
            critical_gates=critical_gates,
            abstraction_contracts=abstraction_contracts,
            sanitized=sanitization_result.was_sanitized,
            security_flags=sanitization_result.security_flags
        )
    
    def _get_skill_hints(self, intent: str, profile: str) -> List[str]:
        """
        Get skill hints for intent + profile combination.
        
        Args:
            intent: Classified intent
            profile: Detected user role profile
        
        Returns:
            List of skill hints
        """
        profile_hints = SKILL_HINT_MAPPING.get(profile, {})
        hints = profile_hints.get(intent, [])
        
        if not hints:
            # Try to find similar intents
            for intent_key in profile_hints:
                if intent in intent_key or intent_key in intent:
                    hints = profile_hints[intent_key]
                    break
        
        return hints if hints else DEFAULT_SKILL_HINTS
    
    def _get_role_hints(self, intent: str, profile: str) -> List[str]:
        """
        Get role hints for routing decisions.
        
        Args:
            intent: Classified intent
            profile: Detected user role profile
        
        Returns:
            List of role hints
        """
        # Role hints are derived from profile and intent
        hints = [profile]
        
        # Add intent-based hints
        intent_role_map = {
            "deploy": "executor",
            "debug": "investigator",
            "refactor": "architect",
            "implement": "builder",
            "code_review": "reviewer",
            "test_gen": "validator",
            "document": "documenter",
            "security_audit": "auditor",
        }
        
        if intent in intent_role_map:
            hints.append(intent_role_map[intent])
        
        return hints
    
    def _get_critical_gates(self, intent: str, profile: str) -> List[str]:
        """
        Get critical gates for intent + profile combination.
        
        Args:
            intent: Classified intent
            profile: Detected user role profile
        
        Returns:
            List of critical gate IDs
        """
        profile_gates = CRITICAL_GATE_MAPPING.get(profile, {})
        gates = profile_gates.get(intent, [])
        
        return gates if gates else DEFAULT_CRITICAL_GATES
    
    def _get_abstraction_contracts(self, intent: str, profile: str) -> Dict[str, str]:
        """
        Get abstraction contracts for the operation.
        
        Abstraction contracts define what the operation expects
        from the underlying abstraction layers.
        
        Args:
            intent: Classified intent
            profile: Detected user role profile
        
        Returns:
            Dictionary of contract name -> contract specification
        """
        contracts = {}
        
        # Always require basic validation contract
        contracts["validation"] = "GATE-02:completeness_check"
        
        # Add intent-specific contracts
        if intent in ["refactor", "implement", "migration"]:
            contracts["dependency"] = "GATE-04:dependency_resolution"
        
        if intent in ["deploy", "configure"]:
            contracts["infrastructure"] = "GATE-05:deployment_safety"
        
        if intent in ["debug", "security_audit"]:
            contracts["analysis"] = "GATE-02:trace_analysis"
        
        # Add profile-specific contracts
        if profile == "devops":
            contracts["operation"] = "GATE-01:operational_safety"
        
        return contracts
    
    def _emit_context_ready(self, enriched: EnrichedIntent) -> None:
        """
        Emit EVENT_CONTEXT_READY event via EventBus.
        
        Args:
            enriched: The enriched intent to emit
        """
        if self._event_bus:
            try:
                # Import locally
                from src.events.event_bus import Event, EventSeverity
                
                event = Event(
                    event_type=EVENT_CONTEXT_READY,
                    data={
                        "intent": enriched.intent,
                        "profile": enriched.profile_type,
                        "skill_hints": enriched.skill_hints,
                        "critical_gates": enriched.critical_gates,
                        "enriched_intent": enriched.to_dict()
                    },
                    severity=EventSeverity.INFO,
                    source="IntentEnricher"
                )
                self._event_bus.emit(event)
                
                self._logger.debug(
                    f"[ITEM_006] Emitted {EVENT_CONTEXT_READY} event"
                )
            except Exception as e:
                self._logger.warning(
                    f"[ITEM_006] Failed to emit {EVENT_CONTEXT_READY}: {e}"
                )
    
    # =========================================================================
    # Configuration Methods
    # =========================================================================
    
    def configure_skill_hints(
        self, 
        profile: str, 
        intent: str, 
        hints: List[str]
    ) -> None:
        """
        Configure custom skill hints for a profile + intent combination.
        
        Args:
            profile: User role profile
            intent: Intent type
            hints: List of skill hints
        """
        if profile not in SKILL_HINT_MAPPING:
            SKILL_HINT_MAPPING[profile] = {}
        SKILL_HINT_MAPPING[profile][intent] = hints
        self._logger.info(
            f"[ITEM_006] Configured skill hints for {profile}/{intent}: {hints}"
        )
    
    def configure_critical_gates(
        self,
        profile: str,
        intent: str,
        gates: List[str]
    ) -> None:
        """
        Configure custom critical gates for a profile + intent combination.
        
        Args:
            profile: User role profile
            intent: Intent type
            gates: List of critical gate IDs
        """
        if profile not in CRITICAL_GATE_MAPPING:
            CRITICAL_GATE_MAPPING[profile] = {}
        CRITICAL_GATE_MAPPING[profile][intent] = gates
        self._logger.info(
            f"[ITEM_006] Configured critical gates for {profile}/{intent}: {gates}"
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the IntentEnricher.
        
        Returns:
            Dictionary with statistics
        """
        return {
            "max_request_length": self._max_request_length,
            "min_confidence": self._min_confidence,
            "intent_router_available": self._intent_router is not None,
            "profile_router_available": self._profile_router is not None,
            "event_bus_available": self._event_bus is not None,
            "retry_facade_available": self._retry_facade is not None,
            "skill_hint_profiles": len(SKILL_HINT_MAPPING),
            "critical_gate_profiles": len(CRITICAL_GATE_MAPPING),
            "injection_patterns": len(PROMPT_INJECTION_PATTERNS)
        }


def create_intent_enricher(
    config: Optional[Dict[str, Any]] = None,
    intent_router: Optional["IntentRouter"] = None,
    profile_router: Optional["EnhancedProfileRouter"] = None,
    event_bus: Optional["EventBus"] = None,
    retry_facade: Optional[Any] = None
) -> IntentEnricher:
    """
    Factory function to create IntentEnricher.
    
    Args:
        config: Configuration dictionary
        intent_router: IntentRouter instance
        profile_router: EnhancedProfileRouter instance
        event_bus: EventBus instance
        retry_facade: RetryExecutorFacade instance
    
    Returns:
        Configured IntentEnricher instance
    """
    return IntentEnricher(
        config=config,
        intent_router=intent_router,
        profile_router=profile_router,
        event_bus=event_bus,
        retry_facade=retry_facade
    )
