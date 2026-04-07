"""
Intent Router for TITAN FUSE Protocol.

Provides intent-based policy chain selection for routing
execution based on task classification.

ITEM-GATE-03: Pre-Intent Token Budget
Adds token budget checking before intent classification to prevent
resource exhaustion from overly large queries.

ITEM-FEAT-55: IntentRouter Plugin Registry
Allows config-driven registration of custom intent handlers
without modifying core IntentRouter code.

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
import re
import logging
import importlib


# Default policy chains per intent
INTENT_CHAINS = {
    "code_review": ["security_scan", "style_check", "diff_generator"],
    "refactor": ["dependency_analysis", "impact_assessment", "diff_generator"],
    "documentation": ["reference_collector", "doc_generator"],
    "debugging": ["error_analysis", "trace_collector", "fix_generator"],
    "feature_add": ["impact_assessment", "implementation_planner"],
    "test_gen": ["coverage_analysis", "test_generator"],
    "migration": ["compatibility_check", "migration_planner"],
    "optimization": ["performance_analysis", "bottleneck_detection", "optimization_planner"],
    "security_audit": ["vulnerability_scan", "compliance_check", "security_report"],
    "MANUAL": []  # Fallback mode - no automatic chain
}


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent: str
    confidence: float
    keywords_matched: List[str]
    chain: List[str]
    alternatives: List[Dict] = field(default_factory=list)
    budget_exceeded: bool = False
    budget_limit: Optional[int] = None
    token_count: Optional[int] = None
    reason: str = ""

    def to_dict(self) -> Dict:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "keywords_matched": self.keywords_matched,
            "chain": self.chain,
            "alternatives": self.alternatives,
            "budget_exceeded": self.budget_exceeded,
            "budget_limit": self.budget_limit,
            "token_count": self.token_count,
            "reason": self.reason
        }


class IntentRouter:
    """
    Select policy chain based on intent classification.

    The IntentRouter analyzes input text to determine the user's
    intent and selects the appropriate processing chain.

    ITEM-GATE-03: Pre-Intent Token Budget
    
    If a query exceeds the token budget limit, the router falls back
    to MANUAL mode, requiring explicit user guidance. This prevents
    resource exhaustion from overly large or complex queries.

    Usage:
        router = IntentRouter(config)
        result = router.classify_intent("Please review this code for security issues")
        print(result.intent)  # "code_review"
        print(result.chain)   # ["security_scan", "style_check", "diff_generator"]
        
        # Check if budget was exceeded
        if result.budget_exceeded:
            print(f"Query too large: {result.token_count} tokens > {result.budget_limit}")
    """

    KEYWORDS = {
        "code_review": [
            "review", "check", "audit", "analyze", "inspect",
            "examine", "evaluate", "assess", "look at"
        ],
        "refactor": [
            "refactor", "restructure", "reorganize", "rewrite",
            "clean up", "improve", "optimize structure"
        ],
        "documentation": [
            "document", "readme", "doc", "comment", "describe",
            "explain", "document", "write docs"
        ],
        "debugging": [
            "debug", "fix", "error", "bug", "issue", "problem",
            "broken", "not working", "crash", "exception"
        ],
        "feature_add": [
            "add", "implement", "create", "new feature", "extend",
            "build", "develop", "new functionality"
        ],
        "test_gen": [
            "test", "spec", "coverage", "unit test", "integration test",
            "testing", "test case"
        ],
        "migration": [
            "migrate", "upgrade", "port", "convert", "move to",
            "transition", "upgrade to"
        ],
        "optimization": [
            "optimize", "performance", "speed up", "faster",
            "improve performance", "reduce time", "efficiency"
        ],
        "security_audit": [
            "security", "vulnerability", "secure", "hack", "exploit",
            "security audit", "penetration", "cve"
        ]
    }

    # Priority weights for ambiguous matches
    INTENT_PRIORITY = {
        "security_audit": 10,  # Highest priority - security is critical
        "debugging": 8,
        "code_review": 7,
        "refactor": 6,
        "feature_add": 5,
        "test_gen": 4,
        "optimization": 3,
        "migration": 2,
        "documentation": 1
    }

    # ITEM-GATE-03: Default token budget
    DEFAULT_TOKEN_LIMIT = 5000
    DEFAULT_FALLBACK_MODE = "MANUAL"
    DEFAULT_AMBIGUITY_THRESHOLD = 0.5

    def __init__(self, chains: Dict[str, List[str]] = None, 
                 custom_keywords: Dict[str, List[str]] = None,
                 config: Dict = None):
        """
        Initialize IntentRouter.

        Args:
            chains: Custom policy chains (merged with defaults)
            custom_keywords: Custom keywords for classification
            config: Configuration dictionary with pre_intent settings
        """
        self.chains = {**INTENT_CHAINS, **(chains or {})}
        self.keywords = {**self.KEYWORDS, **(custom_keywords or {})}
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
        
        # ITEM-GATE-03: Load pre-intent configuration
        pre_intent_config = self.config.get("pre_intent", {})
        self.token_limit = pre_intent_config.get("token_limit", self.DEFAULT_TOKEN_LIMIT)
        self.fallback_mode = pre_intent_config.get("fallback_mode", self.DEFAULT_FALLBACK_MODE)
        self.ambiguity_threshold = pre_intent_config.get("ambiguity_threshold", self.DEFAULT_AMBIGUITY_THRESHOLD)
    
    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for a text string.
        
        Uses a simple heuristic: ~4 characters per token on average.
        This is an approximation suitable for budget checking.
        
        Args:
            text: Input text
            
        Returns:
            Estimated token count
        """
        if not text:
            return 0
        
        # Simple token estimation: ~4 chars per token
        # This is conservative and may overestimate
        char_count = len(text)
        
        # Account for whitespace and special characters
        words = text.split()
        word_count = len(words)
        
        # Use word count if available, otherwise char estimate
        if word_count > 0:
            # Average of word-based and char-based estimates
            char_estimate = char_count / 4
            word_estimate = word_count * 1.3  # Words + punctuation
            
            return int(max(char_estimate, word_estimate))
        
        return int(char_count / 4)

    def classify_intent(self, query: str) -> IntentResult:
        """
        Classify intent from query text.

        ITEM-GATE-03: Checks token budget before classification.
        If budget exceeded, falls back to MANUAL mode.

        Args:
            query: Input text to classify

        Returns:
            IntentResult with classification details
        """
        # ITEM-GATE-03: Check token budget first
        token_count = self.count_tokens(query)
        
        if token_count > self.token_limit:
            self._logger.warning(
                f"[gap: pre_intent_budget_exceeded] "
                f"Query token count ({token_count}) exceeds limit ({self.token_limit}). "
                f"Falling back to {self.fallback_mode} mode."
            )
            
            return IntentResult(
                intent=self.fallback_mode,
                confidence=0.0,
                keywords_matched=[],
                chain=self.get_chain(self.fallback_mode),
                alternatives=[],
                budget_exceeded=True,
                budget_limit=self.token_limit,
                token_count=token_count,
                reason=f"Query too large for automatic classification: "
                       f"{token_count} tokens > {self.token_limit} limit"
            )
        
        query_lower = query.lower()
        scores: Dict[str, List[str]] = {}

        # Score each intent
        for intent, keywords in self.keywords.items():
            matches = [kw for kw in keywords if kw in query_lower]
            if matches:
                scores[intent] = matches

        if not scores:
            # Default to code_review if no matches
            return IntentResult(
                intent="code_review",
                confidence=0.3,
                keywords_matched=[],
                chain=self.get_chain("code_review"),
                alternatives=[],
                token_count=token_count
            )

        # Find best match considering priority
        best_intent = max(
            scores.keys(),
            key=lambda i: (len(scores[i]) * 10 + self.INTENT_PRIORITY.get(i, 0))
        )

        # Calculate confidence
        match_count = len(scores[best_intent])
        confidence = min(1.0, match_count / 3.0 + 0.3)
        
        # ITEM-GATE-03: Check ambiguity threshold
        if confidence < self.ambiguity_threshold:
            self._logger.info(
                f"[intent_router] Low confidence ({confidence:.2f} < {self.ambiguity_threshold}). "
                f"Falling back to {self.fallback_mode} mode."
            )
            
            return IntentResult(
                intent=self.fallback_mode,
                confidence=confidence,
                keywords_matched=scores[best_intent],
                chain=self.get_chain(self.fallback_mode),
                alternatives=[
                    {"intent": i, "score": len(s)}
                    for i, s in sorted(scores.items(), key=lambda x: -len(x[1]))
                ][:3],
                token_count=token_count,
                reason=f"Low classification confidence ({confidence:.2f})"
            )

        # Get alternatives
        alternatives = [
            {"intent": i, "score": len(s)}
            for i, s in sorted(scores.items(), key=lambda x: -len(x[1]))
            if i != best_intent
        ][:3]  # Top 3 alternatives

        return IntentResult(
            intent=best_intent,
            confidence=confidence,
            keywords_matched=scores[best_intent],
            chain=self.get_chain(best_intent),
            alternatives=alternatives,
            token_count=token_count
        )

    def get_chain(self, intent: str) -> List[str]:
        """
        Get policy chain for intent type.

        Args:
            intent: Intent name

        Returns:
            List of policy steps
        """
        return self.chains.get(intent, self.chains.get("code_review", []))

    def add_custom_intent(self, intent: str, chain: List[str],
                         keywords: List[str] = None,
                         priority: int = 5) -> None:
        """
        Add custom intent with chain and optional keywords.

        Args:
            intent: Intent name
            chain: Policy chain for this intent
            keywords: Keywords for classification
            priority: Priority weight for ambiguous matches
        """
        self.chains[intent] = chain
        if keywords:
            self.keywords[intent] = keywords
        if priority:
            self.INTENT_PRIORITY[intent] = priority

    def remove_intent(self, intent: str) -> bool:
        """Remove an intent from the router."""
        if intent in self.chains:
            del self.chains[intent]
            self.keywords.pop(intent, None)
            self.INTENT_PRIORITY.pop(intent, None)
            return True
        return False

    def list_intents(self) -> List[str]:
        """List all available intents."""
        return list(self.chains.keys())

    def get_intent_info(self, intent: str) -> Dict:
        """Get detailed info about an intent."""
        return {
            "intent": intent,
            "chain": self.chains.get(intent, []),
            "keywords": self.keywords.get(intent, []),
            "priority": self.INTENT_PRIORITY.get(intent, 0)
        }
    
    def get_budget_status(self) -> Dict:
        """
        Get current token budget configuration.
        
        Returns:
            Dict with budget settings
        """
        return {
            "token_limit": self.token_limit,
            "fallback_mode": self.fallback_mode,
            "ambiguity_threshold": self.ambiguity_threshold
        }
    
    def set_token_limit(self, limit: int) -> None:
        """
        Update token budget limit.
        
        Args:
            limit: New token limit
        """
        self.token_limit = limit
        self._logger.info(f"Token limit updated to {limit}")


class IntentPluginRegistry:
    """
    Registry for intent handler plugins.
    
    ITEM-FEAT-55: IntentRouter Plugin Registry.
    
    Allows config-driven registration of custom intent handlers
    without modifying the core IntentRouter code. Plugins can
    be loaded dynamically from Python modules.
    
    Usage:
        registry = IntentPluginRegistry()
        
        # Register a plugin
        def custom_handler(query: str) -> IntentResult:
            # Custom classification logic
            return IntentResult(
                intent="custom",
                confidence=0.9,
                keywords_matched=[],
                chain=["step1", "step2"]
            )
        
        registry.register("custom_intent", custom_handler)
        
        # Get handler for an intent
        handler = registry.get_handler("custom_intent")
        result = handler("some query")
        
        # Load from config
        config = {
            "plugins": [
                {"name": "code_audit", "handler": "src.plugins.code_audit:handle"}
            ]
        }
        registry.load_from_config(config)
    """
    
    def __init__(self):
        """Initialize the plugin registry."""
        self._plugins: Dict[str, Callable[[str], IntentResult]] = {}
        self._plugin_info: Dict[str, Dict[str, Any]] = {}
        self._logger = logging.getLogger(__name__)
    
    def register(self, name: str, handler: Callable[[str], IntentResult],
                chain: List[str] = None, keywords: List[str] = None,
                priority: int = 5, description: str = "") -> None:
        """
        Register a plugin handler.
        
        Args:
            name: Plugin/intent name
            handler: Callable that takes a query string and returns IntentResult
            chain: Optional chain for this intent
            keywords: Optional keywords for classification
            priority: Priority for ambiguous matches
            description: Plugin description
        """
        self._plugins[name] = handler
        self._plugin_info[name] = {
            "name": name,
            "chain": chain or [],
            "keywords": keywords or [],
            "priority": priority,
            "description": description,
            "registered_at": logging.Formatter.default_msec_format
        }
        
        self._logger.info(f"Registered intent plugin: {name}")
    
    def unregister(self, name: str) -> bool:
        """
        Unregister a plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            True if plugin was removed
        """
        if name in self._plugins:
            del self._plugins[name]
            del self._plugin_info[name]
            self._logger.info(f"Unregistered intent plugin: {name}")
            return True
        return False
    
    def get_handler(self, intent: str) -> Optional[Callable[[str], IntentResult]]:
        """
        Get handler for an intent.
        
        Args:
            intent: Intent name
            
        Returns:
            Handler callable or None
        """
        return self._plugins.get(intent)
    
    def has_handler(self, intent: str) -> bool:
        """Check if handler exists for intent."""
        return intent in self._plugins
    
    def list_plugins(self) -> List[str]:
        """List all registered plugins."""
        return list(self._plugins.keys())
    
    def get_plugin_info(self, name: str) -> Optional[Dict]:
        """Get plugin information."""
        return self._plugin_info.get(name)
    
    def load_from_config(self, config: Dict) -> List[str]:
        """
        Load plugins from configuration.
        
        Args:
            config: Configuration with 'plugins' list
            
        Returns:
            List of successfully loaded plugin names
        """
        loaded = []
        plugins = config.get("plugins", [])
        
        for plugin_config in plugins:
            try:
                name = plugin_config.get("name")
                handler_path = plugin_config.get("handler")
                
                if not name or not handler_path:
                    self._logger.warning(
                        f"Invalid plugin config: missing name or handler"
                    )
                    continue
                
                # Load handler dynamically
                handler = self._load_handler(handler_path)
                
                if handler:
                    self.register(
                        name=name,
                        handler=handler,
                        chain=plugin_config.get("chain"),
                        keywords=plugin_config.get("keywords"),
                        priority=plugin_config.get("priority", 5),
                        description=plugin_config.get("description", "")
                    )
                    loaded.append(name)
                    
            except Exception as e:
                self._logger.error(
                    f"Failed to load plugin {plugin_config.get('name')}: {e}"
                )
        
        self._logger.info(f"Loaded {len(loaded)} plugins from config")
        return loaded
    
    def _load_handler(self, handler_path: str) -> Optional[Callable]:
        """
        Load a handler from a module path.
        
        Args:
            handler_path: Path like "module.submodule:function"
            
        Returns:
            Handler callable or None
        """
        try:
            if ":" in handler_path:
                module_path, func_name = handler_path.rsplit(":", 1)
            else:
                module_path = handler_path
                func_name = "handle"
            
            module = importlib.import_module(module_path)
            handler = getattr(module, func_name)
            
            return handler
            
        except ImportError as e:
            self._logger.error(f"Failed to import module {module_path}: {e}")
            return None
        except AttributeError as e:
            self._logger.error(f"Handler {func_name} not found in {module_path}: {e}")
            return None
    
    def classify_with_plugins(self, query: str, 
                             fallback_router: IntentRouter = None) -> IntentResult:
        """
        Classify query using registered plugins.
        
        Tries each plugin in priority order until one returns
        a confident result.
        
        Args:
            query: Query string to classify
            fallback_router: Fallback IntentRouter if no plugin matches
            
        Returns:
            IntentResult from the best matching plugin or fallback
        """
        # Sort plugins by priority
        sorted_plugins = sorted(
            self._plugin_info.items(),
            key=lambda x: x[1].get("priority", 5),
            reverse=True
        )
        
        for name, info in sorted_plugins:
            handler = self._plugins.get(name)
            if handler:
                try:
                    result = handler(query)
                    if result and result.confidence > 0.5:
                        self._logger.debug(
                            f"Plugin {name} matched with confidence {result.confidence}"
                        )
                        return result
                except Exception as e:
                    self._logger.error(f"Plugin {name} error: {e}")
        
        # Fallback to standard router
        if fallback_router:
            return fallback_router.classify_intent(query)
        
        # No match
        return IntentResult(
            intent="MANUAL",
            confidence=0.0,
            keywords_matched=[],
            chain=[],
            reason="No plugin matched and no fallback router"
        )
    
    def get_stats(self) -> Dict:
        """Get registry statistics."""
        return {
            "total_plugins": len(self._plugins),
            "plugins": list(self._plugins.keys()),
            "plugin_info": self._plugin_info
        }
    
    def clear(self) -> None:
        """Clear all registered plugins."""
        self._plugins.clear()
        self._plugin_info.clear()
        self._logger.info("Cleared all plugins")


# Global plugin registry
_global_registry: Optional[IntentPluginRegistry] = None


def get_plugin_registry() -> IntentPluginRegistry:
    """Get the global plugin registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = IntentPluginRegistry()
    return _global_registry
