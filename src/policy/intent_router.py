"""
Intent Router for TITAN FUSE Protocol.

Provides intent-based policy chain selection for routing
execution based on task classification.

Author: TITAN FUSE Team
Version: 3.2.3
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
import re


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
    "security_audit": ["vulnerability_scan", "compliance_check", "security_report"]
}


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent: str
    confidence: float
    keywords_matched: List[str]
    chain: List[str]
    alternatives: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "keywords_matched": self.keywords_matched,
            "chain": self.chain,
            "alternatives": self.alternatives
        }


class IntentRouter:
    """
    Select policy chain based on intent classification.

    The IntentRouter analyzes input text to determine the user's
    intent and selects the appropriate processing chain.

    Usage:
        router = IntentRouter()
        result = router.classify_intent("Please review this code for security issues")
        print(result.intent)  # "code_review"
        print(result.chain)   # ["security_scan", "style_check", "diff_generator"]
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

    def __init__(self, chains: Dict[str, List[str]] = None, custom_keywords: Dict[str, List[str]] = None):
        """
        Initialize IntentRouter.

        Args:
            chains: Custom policy chains (merged with defaults)
            custom_keywords: Custom keywords for classification
        """
        self.chains = {**INTENT_CHAINS, **(chains or {})}
        self.keywords = {**self.KEYWORDS, **(custom_keywords or {})}

    def classify_intent(self, query: str) -> IntentResult:
        """
        Classify intent from query text.

        Args:
            query: Input text to classify

        Returns:
            IntentResult with classification details
        """
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
                alternatives=[]
            )

        # Find best match considering priority
        best_intent = max(
            scores.keys(),
            key=lambda i: (len(scores[i]) * 10 + self.INTENT_PRIORITY.get(i, 0))
        )

        # Calculate confidence
        match_count = len(scores[best_intent])
        confidence = min(1.0, match_count / 3.0 + 0.3)

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
            alternatives=alternatives
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
