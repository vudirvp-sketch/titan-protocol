"""
SCOUT Roles Matrix Agent Framework for TITAN FUSE Protocol.

ITEM-CAT-02: Four specialized agents with explicit roles:
- RADAR: Domain/signal classification
- DEVIL: Hype detection and risk flagging
- EVAL: Readiness assessment with veto power
- STRAT: Strategy synthesis respecting EVAL constraints

Enforces mandatory DEVIL→EVAL→STRAT pipeline with veto propagation.

Author: TITAN FUSE Team
Version: 3.2.3
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Literal

from ..state.assessment import SignalStrength

# Configure module logger
logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================

class AgentRole(Enum):
    """SCOUT agent roles with explicit responsibilities."""
    RADAR = "radar"    # Domain/signal classification
    DEVIL = "devil"    # Hype detection, risk flagging
    EVAL = "eval"      # Readiness assessment, veto power
    STRAT = "strat"    # Strategy synthesis


class AdoptionReadiness(Enum):
    """
    Adoption readiness tiers for technology assessment.
    
    Tiers are ordered from most ready to least ready:
    - PRODUCTION_READY: Battle-tested, safe for production use
    - EARLY_ADOPTER: Stable but needs monitoring
    - EXPERIMENTAL: Unproven, use with caution
    - VAPORWARE: No real implementation, avoid
    """
    PRODUCTION_READY = "PRODUCTION_READY"
    EARLY_ADOPTER = "EARLY_ADOPTER"
    EXPERIMENTAL = "EXPERIMENTAL"
    VAPORWARE = "VAPORWARE"

    @property
    def can_proceed(self) -> bool:
        """Check if this tier allows proceeding with adoption."""
        return self in (AdoptionReadiness.PRODUCTION_READY, AdoptionReadiness.EARLY_ADOPTER)

    @property
    def requires_caveat(self) -> bool:
        """Check if this tier requires caveats in strategy output."""
        return self in (AdoptionReadiness.EARLY_ADOPTER, AdoptionReadiness.EXPERIMENTAL)

    @property
    def blocks_strat(self) -> bool:
        """Check if this tier should block STRAT synthesis."""
        return self in (AdoptionReadiness.EXPERIMENTAL, AdoptionReadiness.VAPORWARE)


class PipelineContext(Enum):
    """Execution contexts for the ScoutPipeline."""
    DISCOVER = "discover"      # Exploration mode
    EVALUATE = "evaluate"      # Assessment mode (requires DEVIL)
    COMPARE = "compare"        # Comparison mode (requires DEVIL)
    VALIDATE = "validate"      # Validation mode (requires DEVIL)


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class AnalysisContext:
    """
    Input context for SCOUT pipeline analysis.
    
    Contains all information needed for agents to perform their analysis.
    
    Attributes:
        subject: The technology or concept being analyzed
        domain: The domain category (e.g., 'ai', 'infrastructure', 'frontend')
        volatility: Domain volatility level ('low', 'medium', 'high', 'V0'-'V3')
        confidence: Initial confidence score (0.0 - 1.0)
        context: Pipeline execution context
        metadata: Additional context data
        claims: List of claims to validate
        evidence: List of supporting evidence
        prior_art: Related prior art or similar technologies
        timestamp: When this context was created
    """
    subject: str
    domain: str
    volatility: str = "medium"
    confidence: float = 0.5
    context: PipelineContext = PipelineContext.DISCOVER
    metadata: Dict[str, Any] = field(default_factory=dict)
    claims: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    prior_art: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "subject": self.subject,
            "domain": self.domain,
            "volatility": self.volatility,
            "confidence": self.confidence,
            "context": self.context.value,
            "metadata": self.metadata,
            "claims": self.claims,
            "evidence": self.evidence,
            "prior_art": self.prior_art,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisContext":
        """Create from dictionary."""
        return cls(
            subject=data["subject"],
            domain=data["domain"],
            volatility=data.get("volatility", "medium"),
            confidence=data.get("confidence", 0.5),
            context=PipelineContext(data.get("context", "discover")),
            metadata=data.get("metadata", {}),
            claims=data.get("claims", []),
            evidence=data.get("evidence", []),
            prior_art=data.get("prior_art", []),
            timestamp=data.get("timestamp", datetime.utcnow().isoformat() + "Z"),
        )


@dataclass
class ScoutOutput:
    """
    Output from SCOUT pipeline execution.
    
    Contains the combined results from all agent analyses.
    
    Attributes:
        readiness: Final adoption readiness tier
        signal_strength: Classified signal strength
        hype_flags: Hype indicators detected by DEVIL
        risk_flags: Risk indicators detected by DEVIL
        strategy: Synthesized strategy from STRAT (if not blocked)
        caveats: Caveats added to strategy
        blocked: Whether STRAT was blocked by EVAL veto
        veto_reason: Reason for veto if blocked
        agent_outputs: Individual agent outputs
        confidence: Final confidence score
        timestamp: When this output was generated
    """
    readiness: AdoptionReadiness
    signal_strength: SignalStrength
    hype_flags: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    strategy: Optional[str] = None
    caveats: List[str] = field(default_factory=list)
    blocked: bool = False
    veto_reason: Optional[str] = None
    agent_outputs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    confidence: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "readiness": self.readiness.value,
            "signal_strength": self.signal_strength.name,
            "hype_flags": self.hype_flags,
            "risk_flags": self.risk_flags,
            "strategy": self.strategy,
            "caveats": self.caveats,
            "blocked": self.blocked,
            "veto_reason": self.veto_reason,
            "agent_outputs": self.agent_outputs,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


@dataclass
class AgentResult:
    """
    Result from a single agent execution.
    
    Attributes:
        agent_role: Role of the executing agent
        success: Whether execution succeeded
        output: Agent-specific output data
        flags: Flags raised during execution
        metadata: Additional metadata
        error: Error message if failed
    """
    agent_role: AgentRole
    success: bool = True
    output: Dict[str, Any] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "agent_role": self.agent_role.value,
            "success": self.success,
            "output": self.output,
            "flags": self.flags,
            "metadata": self.metadata,
            "error": self.error,
        }


# =============================================================================
# Agent Base Class
# =============================================================================

class AgentBase(ABC):
    """
    Abstract base class for all SCOUT agents.
    
    Provides common interface and shared functionality for agent implementations.
    
    Attributes:
        role: The agent's role identifier
        logger: Module logger for this agent
    """

    def __init__(self, role: AgentRole):
        """
        Initialize the agent.
        
        Args:
            role: The agent's role identifier
        """
        self.role = role
        self.logger = logging.getLogger(f"{__name__}.{role.value}")

    @abstractmethod
    def execute(self, context: AnalysisContext, prior_results: Dict[str, AgentResult]) -> AgentResult:
        """
        Execute the agent's analysis.
        
        Args:
            context: Analysis context with input data
            prior_results: Results from previously executed agents
            
        Returns:
            AgentResult containing the analysis output
        """
        pass

    def _log_execution(self, context: AnalysisContext) -> None:
        """Log execution start."""
        self.logger.info(
            f"Executing {self.role.value} agent for subject: {context.subject}"
        )

    def _log_completion(self, result: AgentResult) -> None:
        """Log execution completion."""
        status = "completed" if result.success else "failed"
        self.logger.info(
            f"{self.role.value} agent {status} with {len(result.flags)} flags"
        )


# =============================================================================
# RADAR Agent - Domain/Signal Classification
# =============================================================================

class RADARAgent(AgentBase):
    """
    RADAR Agent: Domain and signal classification.
    
    Responsibilities:
    - Analyze domain characteristics
    - Classify signal strength based on volatility
    - Provide domain context for other agents
    
    The RADAR agent runs first to establish baseline understanding
    of the subject's domain and signal characteristics.
    """

    # Domain volatility mapping
    DOMAIN_VOLATILITY: Dict[str, str] = {
        # Low volatility domains (stable, mature)
        "infrastructure": "low",
        "database": "low",
        "networking": "low",
        "storage": "low",
        # Medium volatility domains
        "backend": "medium",
        "api": "medium",
        "security": "medium",
        "devops": "medium",
        # High volatility domains (rapid change)
        "ai": "high",
        "ml": "high",
        "frontend": "high",
        "mobile": "high",
        "blockchain": "high",
        "quantum": "high",
    }

    # Volatility to signal strength mapping
    VOLATILITY_SIGNAL: Dict[str, SignalStrength] = {
        "low": SignalStrength.STRONG,
        "medium": SignalStrength.MODERATE,
        "high": SignalStrength.WEAK,
        "v0": SignalStrength.STRONG,
        "v1": SignalStrength.STRONG,
        "v2": SignalStrength.MODERATE,
        "v3": SignalStrength.WEAK,
    }

    def __init__(self):
        """Initialize RADAR agent."""
        super().__init__(AgentRole.RADAR)

    def execute(self, context: AnalysisContext, prior_results: Dict[str, AgentResult]) -> AgentResult:
        """
        Execute RADAR analysis.
        
        Args:
            context: Analysis context with subject and domain
            prior_results: Results from prior agents (empty for RADAR)
            
        Returns:
            AgentResult with domain analysis and signal classification
        """
        self._log_execution(context)

        try:
            # Analyze domain
            domain_analysis = self.analyze_domain(context)

            # Classify signal strength
            signal = self.classify_signal_strength(context)

            result = AgentResult(
                agent_role=self.role,
                success=True,
                output={
                    "domain": context.domain,
                    "domain_analysis": domain_analysis,
                    "signal_strength": signal.name,
                    "volatility": domain_analysis["volatility"],
                    "maturity_score": domain_analysis["maturity_score"],
                },
                flags=domain_analysis.get("risk_factors", []),
                metadata={
                    "domain_category": domain_analysis["category"],
                    "signal_value": signal.value,
                }
            )

            self._log_completion(result)
            return result

        except Exception as e:
            self.logger.error(f"RADAR agent failed: {e}")
            return AgentResult(
                agent_role=self.role,
                success=False,
                error=str(e)
            )

    def analyze_domain(self, context: AnalysisContext) -> Dict[str, Any]:
        """
        Analyze domain characteristics.
        
        Examines the domain to determine volatility, maturity,
        and risk factors that may affect adoption decisions.
        
        Args:
            context: Analysis context with domain information
            
        Returns:
            Dictionary containing:
            - volatility: Domain volatility level
            - maturity_score: Domain maturity (0.0 - 1.0)
            - category: Domain category
            - risk_factors: List of identified risk factors
        """
        domain = context.domain.lower()
        volatility = context.volatility.lower()

        # Use context volatility if provided, otherwise lookup
        if volatility not in self.VOLATILITY_SIGNAL:
            volatility = self.DOMAIN_VOLATILITY.get(domain, "medium")

        # Calculate maturity score based on volatility
        maturity_map = {"low": 0.9, "medium": 0.7, "high": 0.4}
        maturity_score = maturity_map.get(volatility, 0.7)

        # Determine domain category
        if domain in ("ai", "ml", "quantum", "blockchain"):
            category = "emerging"
        elif domain in ("infrastructure", "database", "networking"):
            category = "foundational"
        else:
            category = "practical"

        # Identify risk factors
        risk_factors = []
        if volatility == "high":
            risk_factors.append("high_domain_volatility")
        if maturity_score < 0.5:
            risk_factors.append("low_domain_maturity")
        if context.confidence < 0.5:
            risk_factors.append("low_initial_confidence")

        return {
            "volatility": volatility,
            "maturity_score": maturity_score,
            "category": category,
            "risk_factors": risk_factors,
        }

    def classify_signal_strength(self, context: AnalysisContext) -> SignalStrength:
        """
        Classify signal strength based on domain volatility.
        
        Higher domain volatility results in weaker signal strength,
        indicating less reliable predictions and recommendations.
        
        Args:
            context: Analysis context with volatility information
            
        Returns:
            SignalStrength enum value
        """
        volatility = context.volatility.lower()

        # Check explicit volatility in context
        if volatility in self.VOLATILITY_SIGNAL:
            return self.VOLATILITY_SIGNAL[volatility]

        # Fallback to domain-based classification
        domain = context.domain.lower()
        domain_vol = self.DOMAIN_VOLATILITY.get(domain, "medium")
        return self.VOLATILITY_SIGNAL[domain_vol]


# =============================================================================
# DEVIL Agent - Hype Detection and Risk Flagging
# =============================================================================

class DEVILAgent(AgentBase):
    """
    DEVIL Agent: Hype detection and risk flagging.
    
    Responsibilities:
    - Detect marketing hype vs real capability
    - Flag unverified claims
    - Veto high-risk assessments
    
    The DEVIL agent acts as a critical filter, ensuring that
    marketing claims and hype don't influence adoption decisions.
    MANDATORY in EVALUATE, COMPARE, and VALIDATE contexts.
    """

    # Hype indicators
    HYPE_PATTERNS: List[str] = [
        "revolutionary",
        "game-changing",
        "disruptive",
        "paradigm shift",
        "cutting-edge",
        "next-generation",
        "groundbreaking",
        "transformative",
        "industry-changing",
        "unprecedented",
        "best-in-class",
        "world-class",
        "best practice",
        "zero-friction",
        "effortless",
        "seamless integration",
    ]

    # Risk patterns requiring additional scrutiny
    RISK_PATTERNS: List[str] = [
        "beta",
        "preview",
        "experimental",
        "alpha",
        "coming soon",
        "planned",
        "roadmap",
        "future release",
        "under development",
        "proof of concept",
        "poc",
        "mvp",
    ]

    # Unverified claim indicators
    UNVERIFIED_PATTERNS: List[str] = [
        "up to",
        "potentially",
        "reportedly",
        "claimed to be",
        "expected to",
        "should be",
        "theoretically",
        "up to x%",
        "significant improvement",
    ]

    def __init__(self):
        """Initialize DEVIL agent."""
        super().__init__(AgentRole.DEVIL)
        self._hype_flags: List[str] = []
        self._risk_flags: List[str] = []
        self._unverified_claims: List[str] = []

    def execute(self, context: AnalysisContext, prior_results: Dict[str, AgentResult]) -> AgentResult:
        """
        Execute DEVIL analysis.
        
        Args:
            context: Analysis context with claims and evidence
            prior_results: Results from RADAR agent (optional)
            
        Returns:
            AgentResult with hype detection and risk flagging results
        """
        self._log_execution(context)
        self._hype_flags = []
        self._risk_flags = []
        self._unverified_claims = []

        try:
            # Analyze claims for hype
            self._analyze_claims(context.claims)

            # Check metadata for risk indicators
            self._analyze_metadata(context.metadata)

            # Analyze subject description if available
            subject_desc = context.metadata.get("description", context.subject)
            self._analyze_text(subject_desc)

            # Determine if veto is needed
            veto_triggered, veto_reason = self.veto_if_risk(context, prior_results)

            result = AgentResult(
                agent_role=self.role,
                success=True,
                output={
                    "hype_flags": self._hype_flags,
                    "risk_flags": self._risk_flags,
                    "unverified_claims": self._unverified_claims,
                    "veto_triggered": veto_triggered,
                    "veto_reason": veto_reason if veto_triggered else None,
                    "hype_score": self._calculate_hype_score(),
                },
                flags=self._hype_flags + self._risk_flags,
                metadata={
                    "total_hype_flags": len(self._hype_flags),
                    "total_risk_flags": len(self._risk_flags),
                    "total_unverified": len(self._unverified_claims),
                }
            )

            self._log_completion(result)
            return result

        except Exception as e:
            self.logger.error(f"DEVIL agent failed: {e}")
            return AgentResult(
                agent_role=self.role,
                success=False,
                error=str(e)
            )

    def detect_hype(self, text: str) -> List[str]:
        """
        Detect hype indicators in text.
        
        Scans text for marketing hype patterns that may indicate
        exaggerated claims or inflated expectations.
        
        Args:
            text: Text to analyze for hype indicators
            
        Returns:
            List of detected hype indicators
        """
        detected = []
        text_lower = text.lower()

        for pattern in self.HYPE_PATTERNS:
            if pattern in text_lower:
                detected.append(f"hype:{pattern}")

        return detected

    def flag_unverified(self, claims: List[str]) -> List[str]:
        """
        Flag unverified claims from a list of claims.
        
        Identifies claims that contain unverified language patterns
        or lack supporting evidence.
        
        Args:
            claims: List of claims to analyze
            
        Returns:
            List of unverified claim flags
        """
        unverified = []

        for claim in claims:
            claim_lower = claim.lower()
            for pattern in self.UNVERIFIED_PATTERNS:
                if pattern in claim_lower:
                    unverified.append(f"unverified:{pattern}")
                    break

        return unverified

    def veto_if_risk(
        self,
        context: AnalysisContext,
        prior_results: Dict[str, AgentResult]
    ) -> tuple[bool, Optional[str]]:
        """
        Determine if assessment should be vetoed due to high risk.
        
        Evaluates accumulated risk factors and triggers veto
        if risk threshold is exceeded.
        
        Args:
            context: Analysis context
            prior_results: Results from prior agents
            
        Returns:
            Tuple of (veto_triggered, veto_reason)
        """
        risk_score = 0.0
        reasons = []

        # High hype score contributes to risk
        hype_score = self._calculate_hype_score()
        if hype_score > 0.5:
            risk_score += 0.3
            reasons.append(f"high_hype_score ({hype_score:.2f})")

        # Many unverified claims
        if len(self._unverified_claims) > 3:
            risk_score += 0.3
            reasons.append(f"many_unverified_claims ({len(self._unverified_claims)})")

        # Experimental indicators without proper context
        experimental_flags = [f for f in self._risk_flags if "experimental" in f.lower()]
        if experimental_flags and context.context == PipelineContext.VALIDATE:
            risk_score += 0.2
            reasons.append("experimental_in_validation_context")

        # Low confidence with high volatility
        radar_result = prior_results.get(AgentRole.RADAR.value)
        if radar_result and radar_result.output:
            volatility = radar_result.output.get("volatility", "medium")
            if volatility == "high" and context.confidence < 0.5:
                risk_score += 0.2
                reasons.append("low_confidence_high_volatility")

        # Veto threshold
        if risk_score >= 0.6:
            return True, f"Risk threshold exceeded: {'; '.join(reasons)}"

        return False, None

    def _analyze_claims(self, claims: List[str]) -> None:
        """Analyze claims for hype and unverified content."""
        for claim in claims:
            self._hype_flags.extend(self.detect_hype(claim))
        self._unverified_claims.extend(self.flag_unverified(claims))

    def _analyze_metadata(self, metadata: Dict[str, Any]) -> None:
        """Analyze metadata for risk indicators."""
        for key, value in metadata.items():
            if isinstance(value, str):
                value_lower = value.lower()
                for pattern in self.RISK_PATTERNS:
                    if pattern in value_lower:
                        self._risk_flags.append(f"risk:{pattern}:{key}")

    def _analyze_text(self, text: str) -> None:
        """Analyze arbitrary text for all indicators."""
        self._hype_flags.extend(self.detect_hype(text))
        for pattern in self.RISK_PATTERNS:
            if pattern in text.lower():
                self._risk_flags.append(f"risk:{pattern}")

    def _calculate_hype_score(self) -> float:
        """Calculate overall hype score (0.0 - 1.0)."""
        total_indicators = len(self._hype_flags) + len(self._unverified_claims)
        # Normalize: 5+ indicators = maximum hype score
        return min(total_indicators / 5.0, 1.0)


# =============================================================================
# EVAL Agent - Readiness Assessment
# =============================================================================

class EVALAgent(AgentBase):
    """
    EVAL Agent: Readiness assessment with veto power.
    
    Responsibilities:
    - Assess adoption readiness
    - Determine if STRAT should be vetoed
    - Output readiness tier classification
    
    The EVAL agent has veto power over STRAT, blocking strategy
    synthesis for EXPERIMENTAL or VAPORWARE classifications.
    """

    def __init__(self):
        """Initialize EVAL agent."""
        super().__init__(AgentRole.EVAL)
        self._readiness: Optional[AdoptionReadiness] = None
        self._veto_active: bool = False

    def execute(self, context: AnalysisContext, prior_results: Dict[str, AgentResult]) -> AgentResult:
        """
        Execute EVAL analysis.
        
        Args:
            context: Analysis context
            prior_results: Results from RADAR and DEVIL agents
            
        Returns:
            AgentResult with readiness assessment
        """
        self._log_execution(context)
        self._veto_active = False

        try:
            # Assess readiness
            readiness = self.assess_readiness(context, prior_results)
            self._readiness = readiness

            # Check veto capability
            can_veto = self.can_veto_strat(context, prior_results)

            # Get tier output
            tier_output = self.output_readiness_tier()

            result = AgentResult(
                agent_role=self.role,
                success=True,
                output={
                    "readiness": readiness.value,
                    "can_veto_strat": can_veto,
                    "veto_active": readiness.blocks_strat,
                    "tier_details": tier_output,
                },
                flags=[f"readiness:{readiness.value}"],
                metadata={
                    "tier_order": self._get_tier_order(readiness),
                    "requires_caveat": readiness.requires_caveat,
                }
            )

            self._log_completion(result)
            return result

        except Exception as e:
            self.logger.error(f"EVAL agent failed: {e}")
            return AgentResult(
                agent_role=self.role,
                success=False,
                error=str(e)
            )

    def assess_readiness(
        self,
        context: AnalysisContext,
        prior_results: Dict[str, AgentResult]
    ) -> AdoptionReadiness:
        """
        Assess adoption readiness tier.
        
        Combines domain volatility, confidence, hype detection,
        and evidence quality to determine readiness tier.
        
        Args:
            context: Analysis context
            prior_results: Results from RADAR and DEVIL agents
            
        Returns:
            AdoptionReadiness tier
        """
        score = 0.0
        factors = []

        # Factor 1: Confidence (0-0.3)
        confidence_contrib = context.confidence * 0.3
        score += confidence_contrib
        factors.append(f"confidence:{confidence_contrib:.2f}")

        # Factor 2: Domain volatility (0-0.2)
        radar_result = prior_results.get(AgentRole.RADAR.value)
        if radar_result and radar_result.output:
            volatility = radar_result.output.get("volatility", "medium")
            vol_scores = {"low": 0.2, "medium": 0.1, "high": 0.0}
            vol_contrib = vol_scores.get(volatility, 0.1)
            score += vol_contrib
            factors.append(f"volatility:{vol_contrib:.2f}")

        # Factor 3: Hype/Risk score from DEVIL (0-0.25)
        devil_result = prior_results.get(AgentRole.DEVIL.value)
        if devil_result and devil_result.output:
            hype_score = devil_result.output.get("hype_score", 0)
            hype_contrib = (1.0 - hype_score) * 0.25
            score += hype_contrib
            factors.append(f"hype_penalty:{hype_contrib:.2f}")

            # Additional penalty for experimental flags
            risk_flags = devil_result.output.get("risk_flags", [])
            if any("experimental" in str(f).lower() for f in risk_flags):
                score -= 0.1
                factors.append("experimental_penalty:-0.10")

        # Factor 4: Evidence quality (0-0.25)
        evidence_count = len(context.evidence)
        if evidence_count >= 5:
            score += 0.25
        elif evidence_count >= 3:
            score += 0.15
        elif evidence_count >= 1:
            score += 0.05
        factors.append(f"evidence:{min(evidence_count * 0.05, 0.25):.2f}")

        # Classify based on score
        self.logger.debug(f"Readiness score: {score:.2f} from factors: {factors}")

        if score >= 0.75:
            return AdoptionReadiness.PRODUCTION_READY
        elif score >= 0.55:
            return AdoptionReadiness.EARLY_ADOPTER
        elif score >= 0.35:
            return AdoptionReadiness.EXPERIMENTAL
        else:
            return AdoptionReadiness.VAPORWARE

    def can_veto_strat(
        self,
        context: AnalysisContext,
        prior_results: Dict[str, AgentResult]
    ) -> bool:
        """
        Determine if EVAL can veto STRAT execution.
        
        EVAL has veto power when readiness is EXPERIMENTAL or VAPORWARE,
        preventing STRAT from synthesizing a strategy that might lead
        to risky adoption decisions.
        
        Args:
            context: Analysis context
            prior_results: Prior agent results
            
        Returns:
            True if veto capability is active
        """
        if self._readiness is None:
            return False

        self._veto_active = self._readiness.blocks_strat
        return self._veto_active

    def output_readiness_tier(self) -> Dict[str, Any]:
        """
        Output detailed readiness tier information.
        
        Provides structured output of the readiness assessment
        including tier, characteristics, and recommendations.
        
        Returns:
            Dictionary with tier details
        """
        if self._readiness is None:
            return {"error": "Assessment not yet performed"}

        tier_descriptions = {
            AdoptionReadiness.PRODUCTION_READY: {
                "description": "Battle-tested and safe for production use",
                "recommendation": "Proceed with standard adoption process",
                "monitoring_level": "standard",
                "rollback_required": False,
            },
            AdoptionReadiness.EARLY_ADOPTER: {
                "description": "Stable but requires monitoring",
                "recommendation": "Proceed with enhanced monitoring and fallback plans",
                "monitoring_level": "enhanced",
                "rollback_required": True,
            },
            AdoptionReadiness.EXPERIMENTAL: {
                "description": "Unproven, use with extreme caution",
                "recommendation": "Limited trials only, do not use in production",
                "monitoring_level": "intensive",
                "rollback_required": True,
            },
            AdoptionReadiness.VAPORWARE: {
                "description": "No real implementation exists",
                "recommendation": "Do not adopt, reassess when implementation available",
                "monitoring_level": "n/a",
                "rollback_required": True,
            },
        }

        details = tier_descriptions.get(self._readiness, {})
        details["tier"] = self._readiness.value
        details["veto_active"] = self._veto_active

        return details

    def _get_tier_order(self, readiness: AdoptionReadiness) -> int:
        """Get numeric order for tier (1 = best, 4 = worst)."""
        order = {
            AdoptionReadiness.PRODUCTION_READY: 1,
            AdoptionReadiness.EARLY_ADOPTER: 2,
            AdoptionReadiness.EXPERIMENTAL: 3,
            AdoptionReadiness.VAPORWARE: 4,
        }
        return order.get(readiness, 4)


# =============================================================================
# STRAT Agent - Strategy Synthesis
# =============================================================================

class STRATAgent(AgentBase):
    """
    STRAT Agent: Strategy synthesis respecting EVAL constraints.
    
    Responsibilities:
    - Synthesize adoption strategy
    - Respect EVAL veto when active
    - Add caveats for experimental/early-adopter tiers
    
    The STRAT agent produces actionable recommendations but
    is blocked when EVAL triggers a veto for risky assessments.
    """

    def __init__(self):
        """Initialize STRAT agent."""
        super().__init__(AgentRole.STRAT)
        self._caveats: List[str] = []

    def execute(self, context: AnalysisContext, prior_results: Dict[str, AgentResult]) -> AgentResult:
        """
        Execute STRAT synthesis.
        
        Args:
            context: Analysis context
            prior_results: Results from RADAR, DEVIL, and EVAL agents
            
        Returns:
            AgentResult with synthesized strategy or veto notification
        """
        self._log_execution(context)
        self._caveats = []

        try:
            # Check for EVAL veto
            eval_result = prior_results.get(AgentRole.EVAL.value)
            if eval_result and eval_result.output:
                if eval_result.output.get("veto_active", False):
                    return self._create_veto_result(eval_result)

            # Synthesize strategy
            strategy = self.synthesize_strategy(context, prior_results)

            # Add caveats if needed
            readiness = None
            if eval_result and eval_result.output:
                readiness = AdoptionReadiness(eval_result.output.get("readiness", "EXPERIMENTAL"))

            if readiness and readiness.requires_caveat:
                self.add_caveat_if_experimental(readiness, context)

            result = AgentResult(
                agent_role=self.role,
                success=True,
                output={
                    "strategy": strategy,
                    "caveats": self._caveats,
                    "readiness_tier": readiness.value if readiness else None,
                },
                flags=[f"caveat:{c}" for c in self._caveats],
                metadata={
                    "strategy_generated": True,
                    "caveat_count": len(self._caveats),
                }
            )

            self._log_completion(result)
            return result

        except Exception as e:
            self.logger.error(f"STRAT agent failed: {e}")
            return AgentResult(
                agent_role=self.role,
                success=False,
                error=str(e)
            )

    def synthesize_strategy(
        self,
        context: AnalysisContext,
        prior_results: Dict[str, AgentResult]
    ) -> str:
        """
        Synthesize adoption strategy.
        
        Creates a structured strategy based on all prior agent
        analyses and the execution context.
        
        Args:
            context: Analysis context
            prior_results: Results from all prior agents
            
        Returns:
            Strategy string with recommendations
        """
        # Gather intelligence from prior agents
        radar_result = prior_results.get(AgentRole.RADAR.value)
        devil_result = prior_results.get(AgentRole.DEVIL.value)
        eval_result = prior_results.get(AgentRole.EVAL.value)

        # Build strategy components
        components = []

        # Header
        components.append(f"## Strategy for: {context.subject}")
        components.append(f"Domain: {context.domain}")
        components.append("")

        # Domain context
        if radar_result and radar_result.output:
            domain_analysis = radar_result.output.get("domain_analysis", {})
            components.append("### Domain Analysis")
            components.append(f"- Volatility: {domain_analysis.get('volatility', 'unknown')}")
            components.append(f"- Maturity: {domain_analysis.get('maturity_score', 0):.0%}")
            components.append(f"- Category: {domain_analysis.get('category', 'unknown')}")
            components.append("")

        # Risk assessment
        if devil_result and devil_result.output:
            hype_flags = devil_result.output.get("hype_flags", [])
            risk_flags = devil_result.output.get("risk_flags", [])
            if hype_flags or risk_flags:
                components.append("### Risk Assessment")
                if hype_flags:
                    components.append(f"- Hype indicators: {len(hype_flags)}")
                if risk_flags:
                    components.append(f"- Risk factors: {len(risk_flags)}")
                components.append("")

        # Readiness
        if eval_result and eval_result.output:
            readiness = eval_result.output.get("readiness", "unknown")
            tier_details = eval_result.output.get("tier_details", {})
            components.append("### Readiness Assessment")
            components.append(f"- Tier: **{readiness}**")
            if "recommendation" in tier_details:
                components.append(f"- Recommendation: {tier_details['recommendation']}")
            components.append("")

        # Action plan
        components.append("### Recommended Actions")
        actions = self._generate_actions(context, prior_results)
        for action in actions:
            components.append(f"- {action}")

        return "\n".join(components)

    def respect_eval_veto(self, eval_result: AgentResult) -> bool:
        """
        Check if EVAL has vetoed strategy synthesis.
        
        Args:
            eval_result: Result from EVAL agent
            
        Returns:
            True if veto is active, False otherwise
        """
        if not eval_result or not eval_result.output:
            return False
        return eval_result.output.get("veto_active", False)

    def add_caveat_if_experimental(
        self,
        readiness: AdoptionReadiness,
        context: AnalysisContext
    ) -> None:
        """
        Add appropriate caveats based on readiness tier.
        
        Args:
            readiness: Current readiness tier
            context: Analysis context
        """
        if readiness == AdoptionReadiness.EARLY_ADOPTER:
            self._caveats.append("enhanced_monitoring_required")
            self._caveats.append("rollback_plan_needed")
            if context.confidence < 0.7:
                self._caveats.append("staged_rollout_recommended")

        elif readiness == AdoptionReadiness.EXPERIMENTAL:
            self._caveats.append("production_use_prohibited")
            self._caveats.append("limited_trial_recommended")
            self._caveats.append("frequent_reassessment_required")

    def _create_veto_result(self, eval_result: AgentResult) -> AgentResult:
        """Create a result indicating STRAT was vetoed."""
        readiness = eval_result.output.get("readiness", "unknown")
        tier_details = eval_result.output.get("tier_details", {})

        return AgentResult(
            agent_role=self.role,
            success=True,
            output={
                "strategy": None,
                "caveats": [],
                "vetoed": True,
                "veto_reason": f"STRAT blocked due to {readiness} readiness tier",
                "tier_recommendation": tier_details.get("recommendation", ""),
            },
            flags=["strat:vetoed"],
            metadata={
                "strategy_generated": False,
                "blocking_tier": readiness,
            }
        )

    def _generate_actions(
        self,
        context: AnalysisContext,
        prior_results: Dict[str, AgentResult]
    ) -> List[str]:
        """Generate action items based on analysis."""
        actions = []

        # Base action based on context
        if context.context == PipelineContext.DISCOVER:
            actions.append("Gather additional evidence and documentation")
            actions.append("Identify similar implementations for reference")
        elif context.context == PipelineContext.EVALUATE:
            actions.append("Complete readiness assessment checklist")
            actions.append("Document decision rationale")
        elif context.context == PipelineContext.COMPARE:
            actions.append("Create comparison matrix with alternatives")
            actions.append("Identify differentiating factors")
        elif context.context == PipelineContext.VALIDATE:
            actions.append("Verify all claims against evidence")
            actions.append("Run proof-of-concept if applicable")

        # Add monitoring actions based on domain
        radar_result = prior_results.get(AgentRole.RADAR.value)
        if radar_result and radar_result.output:
            volatility = radar_result.output.get("volatility", "medium")
            if volatility == "high":
                actions.append("Set up enhanced monitoring for rapid change detection")

        return actions


# =============================================================================
# Scout Pipeline
# =============================================================================

class ScoutPipeline:
    """
    SCOUT Pipeline orchestrator.
    
    Manages the execution of SCOUT agents in the proper sequence:
    1. RADAR (optional, provides domain context)
    2. DEVIL (mandatory in EVALUATE/COMPARE/VALIDATE contexts)
    3. EVAL (assesses readiness, can veto STRAT)
    4. STRAT (synthesizes strategy, respects EVAL veto)
    
    Attributes:
        agents: Dictionary of agent instances by role
        require_devil_contexts: Contexts requiring DEVIL execution
    """

    # Contexts where DEVIL execution is mandatory
    DEVIL_MANDATORY_CONTEXTS: Set[PipelineContext] = {
        PipelineContext.EVALUATE,
        PipelineContext.COMPARE,
        PipelineContext.VALIDATE,
    }

    def __init__(
        self,
        include_radar: bool = True,
        strict_mode: bool = True
    ):
        """
        Initialize the SCOUT pipeline.
        
        Args:
            include_radar: Whether to include RADAR in pipeline
            strict_mode: If True, raise errors on agent failures
        """
        self.agents: Dict[AgentRole, AgentBase] = {}
        self.strict_mode = strict_mode

        # Initialize agents
        if include_radar:
            self.agents[AgentRole.RADAR] = RADARAgent()
        self.agents[AgentRole.DEVIL] = DEVILAgent()
        self.agents[AgentRole.EVAL] = EVALAgent()
        self.agents[AgentRole.STRAT] = STRATAgent()

        logger.info(
            f"ScoutPipeline initialized with agents: "
            f"{[r.value for r in self.agents.keys()]}"
        )

    def execute_pipeline(self, context: AnalysisContext) -> ScoutOutput:
        """
        Execute the complete SCOUT pipeline.
        
        Runs agents in sequence: RADAR → DEVIL → EVAL → STRAT
        with proper veto propagation and error handling.
        
        Args:
            context: Analysis context with input data
            
        Returns:
            ScoutOutput containing all analysis results
        """
        logger.info(f"Starting SCOUT pipeline for: {context.subject}")
        logger.info(f"Context: {context.context.value}")

        # Track results
        results: Dict[str, AgentResult] = {}
        blocked = False
        veto_reason = None

        # Step 1: Execute RADAR (if available)
        if AgentRole.RADAR in self.agents:
            radar_result = self.agents[AgentRole.RADAR].execute(context, results)
            results[AgentRole.RADAR.value] = radar_result
            if not radar_result.success and self.strict_mode:
                return self._create_error_output(context, radar_result.error)

        # Step 2: Execute DEVIL (mandatory in certain contexts)
        if self._should_execute_devil(context):
            devil_result = self.agents[AgentRole.DEVIL].execute(context, results)
            results[AgentRole.DEVIL.value] = devil_result
            if not devil_result.success and self.strict_mode:
                return self._create_error_output(context, devil_result.error)
        else:
            logger.debug("DEVIL execution skipped for DISCOVER context")

        # Step 3: Execute EVAL
        eval_result = self.agents[AgentRole.EVAL].execute(context, results)
        results[AgentRole.EVAL.value] = eval_result
        if not eval_result.success and self.strict_mode:
            return self._create_error_output(context, eval_result.error)

        # Check for EVAL veto
        if eval_result.output and eval_result.output.get("veto_active"):
            blocked = True
            veto_reason = eval_result.output.get("tier_details", {}).get(
                "recommendation", "EVAL veto active"
            )
            logger.warning(f"EVAL veto active: {veto_reason}")
            logger.info(f"EVAL readiness tier: {eval_result.output.get('readiness')}")

        # Step 4: Execute STRAT (unless vetoed)
        strat_result: Optional[AgentResult] = None
        if not blocked:
            strat_result = self.agents[AgentRole.STRAT].execute(context, results)
            results[AgentRole.STRAT.value] = strat_result
            if not strat_result.success and self.strict_mode:
                return self._create_error_output(context, strat_result.error)

        # Build output
        output = self._build_output(
            context=context,
            results=results,
            eval_result=eval_result,
            strat_result=strat_result,
            blocked=blocked,
            veto_reason=veto_reason
        )

        logger.info(
            f"SCOUT pipeline completed: {output.readiness.value} "
            f"{'(BLOCKED)' if blocked else ''}"
        )

        return output

    def _should_execute_devil(self, context: AnalysisContext) -> bool:
        """Check if DEVIL should be executed for this context."""
        return context.context in self.DEVIL_MANDATORY_CONTEXTS

    def _create_error_output(
        self,
        context: AnalysisContext,
        error: Optional[str]
    ) -> ScoutOutput:
        """Create an error output when pipeline fails."""
        return ScoutOutput(
            readiness=AdoptionReadiness.VAPORWARE,
            signal_strength=SignalStrength.WEAK,
            blocked=True,
            veto_reason=f"Pipeline error: {error}",
            confidence=0.0,
        )

    def _build_output(
        self,
        context: AnalysisContext,
        results: Dict[str, AgentResult],
        eval_result: AgentResult,
        strat_result: Optional[AgentResult],
        blocked: bool,
        veto_reason: Optional[str]
    ) -> ScoutOutput:
        """Build the final ScoutOutput from pipeline results."""
        # Extract signal strength from RADAR
        signal = SignalStrength.MODERATE
        if AgentRole.RADAR.value in results:
            radar_output = results[AgentRole.RADAR.value].output
            if radar_output:
                signal_name = radar_output.get("signal_strength", "MODERATE")
                signal = SignalStrength[signal_name]

        # Extract readiness from EVAL
        readiness = AdoptionReadiness.EXPERIMENTAL
        if eval_result.output:
            readiness_value = eval_result.output.get("readiness", "EXPERIMENTAL")
            readiness = AdoptionReadiness(readiness_value)

        # Extract hype/risk flags from DEVIL
        hype_flags = []
        risk_flags = []
        if AgentRole.DEVIL.value in results:
            devil_output = results[AgentRole.DEVIL.value].output
            if devil_output:
                hype_flags = devil_output.get("hype_flags", [])
                risk_flags = devil_output.get("risk_flags", [])

        # Extract strategy from STRAT
        strategy = None
        caveats = []
        if strat_result and strat_result.output:
            strategy = strat_result.output.get("strategy")
            caveats = strat_result.output.get("caveats", [])

        # Build agent outputs dict
        agent_outputs = {
            role: result.to_dict() for role, result in results.items()
        }

        return ScoutOutput(
            readiness=readiness,
            signal_strength=signal,
            hype_flags=hype_flags,
            risk_flags=risk_flags,
            strategy=strategy,
            caveats=caveats,
            blocked=blocked,
            veto_reason=veto_reason,
            agent_outputs=agent_outputs,
            confidence=context.confidence,
        )


# =============================================================================
# Factory Function
# =============================================================================

def create_scout_pipeline(
    include_radar: bool = True,
    strict_mode: bool = True
) -> ScoutPipeline:
    """
    Create a configured ScoutPipeline instance.
    
    Args:
        include_radar: Whether to include RADAR agent
        strict_mode: If True, raise errors on agent failures
        
    Returns:
        Configured ScoutPipeline instance
    """
    return ScoutPipeline(
        include_radar=include_radar,
        strict_mode=strict_mode
    )
