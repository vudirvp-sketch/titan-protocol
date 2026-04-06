"""
TITAN FUSE Protocol - Intent Classifier v1

Rule-based intent classification for AUTO mode.
Implements weighted signal aggregation with multi-intent support.
"""

import re
import hashlib
import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
from datetime import datetime


class IntentCategory(Enum):
    """Intent classification categories."""
    ANALYSIS = "analysis"
    GENERATION = "generation"
    DEBUGGING = "debugging"
    RESEARCH = "research"
    MULTIMODAL = "multimodal"
    UNKNOWN = "unknown"


class DomainVolatility(Enum):
    """Domain volatility levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class IntentClassification:
    """Result of intent classification."""
    classification: IntentCategory
    confidence_score: float
    secondary_intents: List[IntentCategory] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    constraints: Dict = field(default_factory=dict)
    domain_volatility: DomainVolatility = DomainVolatility.MEDIUM
    output_format: Optional[str] = None
    intent_hash: Optional[str] = None
    raw_signals: Dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class IntentClassifierV1:
    """
    Rule-based intent classifier using weighted signal aggregation.
    
    Implements:
    - Keyword matching (weight: 0.3)
    - Pattern recognition (weight: 0.25)
    - Constraint clarity (weight: 0.25)
    - Output format detection (weight: 0.2)
    """
    
    # Safe separator for intent hash (avoiding collision with natural text)
    HASH_SEPARATOR = "§§"
    
    # Keywords by category
    KEYWORDS = {
        IntentCategory.ANALYSIS: [
            "analyze", "review", "audit", "examine", "inspect", "assess",
            "evaluate", "check", "verify", "validate", "compare", "contrast"
        ],
        IntentCategory.GENERATION: [
            "create", "generate", "build", "implement", "write", "develop",
            "construct", "produce", "make", "design", "draft", "compose"
        ],
        IntentCategory.DEBUGGING: [
            "fix", "debug", "resolve", "error", "bug", "issue", "problem",
            "troubleshoot", "repair", "correct", "patch", "solve"
        ],
        IntentCategory.RESEARCH: [
            "research", "find", "search", "investigate", "explore", "discover",
            "look up", "gather", "collect", "identify", "locate"
        ],
        IntentCategory.MULTIMODAL: [
            "image", "audio", "video", "process", "convert", "transcribe",
            "render", "visualize", "transcode", "extract"
        ]
    }
    
    # Known patterns for pattern recognition
    PATTERNS = [
        (r"I need (?:to )?(\w+).*?(\w+)", "generation"),
        (r"Fix (?:the )?(?:error|bug|issue) in (\w+)", "debugging"),
        (r"Review (\w+) for (\w+)", "analysis"),
        (r"Analyze (\w+)", "analysis"),
        (r"Create (?:a |an )?(\w+)", "generation"),
        (r"Generate (?:a |an )?(\w+)", "generation"),
        (r"Debug (\w+)", "debugging"),
        (r"Search for (\w+)", "research"),
        (r"Find (\w+)", "research"),
        (r"Process (?:the )?(image|audio|video)", "multimodal"),
    ]
    
    # Format markers
    FORMAT_MARKERS = {
        "json": ["JSON", "json", "as json"],
        "yaml": ["YAML", "yaml", "as yaml"],
        "markdown": ["markdown", "md", "as markdown"],
        "table": ["table", "as a table", "in a table"],
        "list": ["list", "as a list", "bullet points"],
    }
    
    # Constraint markers
    CONSTRAINT_MARKERS = ["must", "should", "required", "need", "output as", 
                          "format", "ensure", "make sure", "verify that"]
    
    def __init__(self, config: Optional[Dict] = None):
        """Initialize the classifier with optional config."""
        self.config = config or {}
        self.baseline = self.config.get("baseline", 0.5)
        
        # Weights for signal aggregation
        self.weights = {
            "keyword_match": 0.3,
            "pattern_recognition": 0.25,
            "constraint_clarity": 0.25,
            "output_format": 0.2
        }
    
    def classify(self, prompt: str) -> IntentClassification:
        """
        Classify the intent of a prompt.
        
        Args:
            prompt: User's input prompt
            
        Returns:
            IntentClassification with classification and confidence
        """
        prompt_lower = prompt.lower()
        
        # Calculate individual signals
        keyword_scores = self._calculate_keyword_match(prompt_lower)
        pattern_score, matched_pattern = self._calculate_pattern_recognition(prompt)
        constraint_score = self._calculate_constraint_clarity(prompt)
        format_score, detected_format = self._calculate_output_format(prompt_lower)
        
        # Store raw signals for transparency
        raw_signals = {
            "keyword_scores": {k.value: v for k, v in keyword_scores.items()},
            "pattern_score": pattern_score,
            "matched_pattern": matched_pattern,
            "constraint_score": constraint_score,
            "format_score": format_score,
            "detected_format": detected_format
        }
        
        # Aggregate scores
        aggregated = {}
        for category in IntentCategory:
            if category == IntentCategory.UNKNOWN:
                continue
            
            score = self.baseline
            score += keyword_scores.get(category, 0) * self.weights["keyword_match"]
            score += pattern_score.get(category.value, 0) * self.weights["pattern_recognition"]
            score += constraint_score * self.weights["constraint_clarity"]
            score += format_score * self.weights["output_format"]
            aggregated[category] = min(1.0, score)
        
        # Find primary and secondary intents
        sorted_intents = sorted(aggregated.items(), key=lambda x: x[1], reverse=True)
        primary_intent = sorted_intents[0][0] if sorted_intents else IntentCategory.UNKNOWN
        primary_confidence = sorted_intents[0][1] if sorted_intents else 0.0
        
        # Secondary intents (within 0.2 of primary)
        secondary_intents = [
            intent for intent, score in sorted_intents[1:]
            if score >= primary_confidence - 0.2 and score >= 0.5
        ]
        
        # Extract success criteria
        success_criteria = self._extract_success_criteria(prompt)
        
        # Determine domain volatility
        domain_volatility = self._determine_domain_volatility(
            prompt, primary_intent, len(success_criteria)
        )
        
        # Build constraints dict
        constraints = {
            "explicit_constraints": self._count_explicit_constraints(prompt),
            "format_requested": detected_format,
            "has_deadline": bool(re.search(r"(by|before|within)\s+\d+", prompt_lower))
        }
        
        # Generate intent hash
        intent_hash = self._generate_intent_hash(
            primary_intent.value,
            constraints,
            success_criteria
        )
        
        return IntentClassification(
            classification=primary_intent,
            confidence_score=round(primary_confidence, 3),
            secondary_intents=secondary_intents,
            success_criteria=success_criteria,
            constraints=constraints,
            domain_volatility=domain_volatility,
            output_format=detected_format,
            intent_hash=intent_hash,
            raw_signals=raw_signals
        )
    
    def _calculate_keyword_match(self, prompt_lower: str) -> Dict[IntentCategory, float]:
        """
        Calculate keyword match scores.
        
        Formula: min(1.0, matched_keywords / 3)
        """
        scores = {}
        for category, keywords in self.KEYWORDS.items():
            matched = sum(1 for kw in keywords if kw in prompt_lower)
            scores[category] = min(1.0, matched / 3)
        return scores
    
    def _calculate_pattern_recognition(self, prompt: str) -> Tuple[Dict, Optional[str]]:
        """
        Calculate pattern recognition scores.
        
        Returns binary 1.0 if pattern matches, with partial credit for near-matches.
        """
        scores = {cat.value: 0.0 for cat in IntentCategory if cat != IntentCategory.UNKNOWN}
        matched_pattern = None
        
        for pattern, category in self.PATTERNS:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                scores[category] = 1.0
                matched_pattern = pattern
                break
        
        return scores, matched_pattern
    
    def _calculate_constraint_clarity(self, prompt: str) -> float:
        """
        Calculate constraint clarity score.
        
        FIX for spec bug: Use sentence count * 0.3 as baseline for expected constraints.
        Formula: count_explicit_constraints / max(1, sentence_count * 0.3)
        """
        # Count sentences (rough approximation)
        sentences = re.split(r'[.!?]+', prompt)
        sentence_count = max(1, len([s for s in sentences if s.strip()]))
        
        # Count explicit constraint markers
        explicit_count = sum(1 for marker in self.CONSTRAINT_MARKERS 
                           if marker.lower() in prompt.lower())
        
        # Expected constraints: ~30% of sentences may contain constraints
        expected_constraints = max(1, sentence_count * 0.3)
        
        return min(1.0, explicit_count / expected_constraints)
    
    def _calculate_output_format(self, prompt_lower: str) -> Tuple[float, Optional[str]]:
        """
        Calculate output format detection score.
        
        Returns (score, detected_format).
        """
        for fmt, markers in self.FORMAT_MARKERS.items():
            for marker in markers:
                if marker in prompt_lower:
                    return 1.0, fmt
        return 0.5, None  # 0.5 = format not detected but not absent
    
    def _extract_success_criteria(self, prompt: str) -> List[str]:
        """
        Extract success criteria from prompt.
        """
        criteria = []
        
        # Pattern-based extraction
        extraction_patterns = [
            (r"I need (?:to )?(\w+).*?(?:so that|to) (.+?)(?:\.|$)", "action_result"),
            (r"Make sure (.+?)(?:\.|$)", "condition"),
            (r"Output as (.+?)(?:\.|$)", "format"),
            (r"The result should (.+?)(?:\.|$)", "requirement"),
            (r"Ensure that (.+?)(?:\.|$)", "requirement"),
        ]
        
        for pattern, _ in extraction_patterns:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                # Get the last group (the actual criterion)
                criterion = match.groups()[-1].strip()
                if criterion and len(criterion) > 3:
                    criteria.append(criterion)
        
        return criteria
    
    def _count_explicit_constraints(self, prompt: str) -> int:
        """Count explicit constraint markers in prompt."""
        count = 0
        prompt_lower = prompt.lower()
        for marker in self.CONSTRAINT_MARKERS:
            count += prompt_lower.count(marker.lower())
        return count
    
    def _determine_domain_volatility(self, prompt: str, 
                                     intent: IntentCategory,
                                     criteria_count: int) -> DomainVolatility:
        """
        Determine domain volatility based on task complexity.
        """
        # Multi-file or cross-reference detection
        has_multi_file = bool(re.search(r"(files?|modules?|components?)\s+(\w+\s*)?(and|,|\+)", prompt, re.IGNORECASE))
        has_dependencies = bool(re.search(r"(depend|reference|import|include)", prompt, re.IGNORECASE))
        
        # Check for ambiguous requirements
        ambiguous_markers = ["maybe", "might", "possibly", "somehow", "not sure"]
        has_ambiguity = any(m in prompt.lower() for m in ambiguous_markers)
        
        if has_multi_file or has_dependencies or has_ambiguity:
            return DomainVolatility.HIGH
        elif criteria_count > 2 or intent in [IntentCategory.DEBUGGING, IntentCategory.GENERATION]:
            return DomainVolatility.MEDIUM
        else:
            return DomainVolatility.LOW
    
    def _generate_intent_hash(self, classification: str, 
                              constraints: Dict, 
                              success_criteria: List[str]) -> str:
        """
        Generate intent hash for caching.
        
        Uses safe separator "§§" to avoid collisions with natural text.
        """
        # Sort constraints for consistency
        constraints_json = json.dumps(constraints, sort_keys=True)
        criteria_json = json.dumps(sorted(success_criteria), sort_keys=True)
        
        # Compose input with safe separator
        hash_input = f"{classification}{self.HASH_SEPARATOR}{constraints_json}{self.HASH_SEPARATOR}{criteria_json}"
        
        # Generate SHA-256 hash
        hash_value = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
        
        # Return first 16 characters (truncated)
        return hash_value[:16]
    
    def get_threshold_for_category(self, category: IntentCategory) -> float:
        """Get the confidence threshold for a category."""
        thresholds = self.config.get("threshold_overrides", {
            "generation": 0.9,
            "debugging": 0.8,
            "analysis": 0.7,
            "research": 0.6,
            "multimodal": 0.7
        })
        return thresholds.get(category.value, self.config.get("confidence_threshold", 0.7))


def classify_intent(prompt: str, config: Optional[Dict] = None) -> IntentClassification:
    """
    Convenience function to classify intent.
    
    Args:
        prompt: User's input prompt
        config: Optional configuration dict
        
    Returns:
        IntentClassification result
    """
    classifier = IntentClassifierV1(config)
    return classifier.classify(prompt)
