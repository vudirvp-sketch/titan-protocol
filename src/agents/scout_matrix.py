"""
SCOUT Roles Matrix Agent Framework for TITAN FUSE Protocol.

ITEM-CAT-02: Four specialized agents with explicit roles:
- RADAR: Domain/signal classification
- DEVIL: Hype detection and risk flagging
- EVAL: Readiness assessment with veto power
- STRAT: Strategy synthesis respecting EVAL constraints

ITEM-AGENT-001: ScoutMatrix integration with RoleWeightedConsensus.
Enforces mandatory DEVIL→EVAL→STRAT pipeline with veto propagation.

Author: TITAN FUSE Team
Version: 5.0.0
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


class ScoutFindingType(Enum):
    """
    ITEM-AGENT-001: Types of findings from scout agents.
    
    Categories of findings that scouts can report:
    - SIGNAL: Positive signal detected by RADAR
    - RISK: Risk factor identified by DEVIL
    - HYPE: Hype indicator detected by DEVIL
    - VULNERABILITY: Security vulnerability found
    - BLOCKER: Blocking issue that prevents progress
    - RECOMMENDATION: Actionable recommendation
    - VETO: Veto trigger from EVAL
    - CAVEAT: Caveat from STRAT
    """
    SIGNAL = "signal"
    RISK = "risk"
    HYPE = "hype"
    VULNERABILITY = "vulnerability"
    BLOCKER = "blocker"
    RECOMMENDATION = "recommendation"
    VETO = "veto"
    CAVEAT = "caveat"


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class ScoutFinding:
    """
    ITEM-AGENT-001: A finding from a scout agent.
    
    Represents a single observation, risk, or recommendation
    from any scout agent during analysis.
    
    Attributes:
        finding_id: Unique identifier for this finding
        role: The scout role that produced this finding
        finding_type: Category of the finding
        severity: Severity level (SEV-1 to SEV-4)
        title: Brief title of the finding
        description: Detailed description
        confidence: Confidence level (0.0 - 1.0)
        impact: Impact level ("critical", "high", "medium", "low")
        recommendation: Recommended action
        metadata: Additional context data
    """
    finding_id: str
    role: AgentRole
    finding_type: ScoutFindingType
    severity: str  # SEV-1 to SEV-4
    title: str
    description: str
    confidence: float
    impact: str  # "critical", "high", "medium", "low"
    recommendation: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Validate finding attributes."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0.0, 1.0], got {self.confidence}")
        valid_severities = {"SEV-1", "SEV-2", "SEV-3", "SEV-4"}
        if self.severity not in valid_severities:
            raise ValueError(f"Severity must be one of {valid_severities}, got {self.severity}")
        valid_impacts = {"critical", "high", "medium", "low"}
        if self.impact not in valid_impacts:
            raise ValueError(f"Impact must be one of {valid_impacts}, got {self.impact}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "finding_id": self.finding_id,
            "role": self.role.value,
            "finding_type": self.finding_type.value,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "confidence": self.confidence,
            "impact": self.impact,
            "recommendation": self.recommendation,
            "metadata": self.metadata,
        }


@dataclass
class AggregatedFindings:
    """
    ITEM-AGENT-001: Aggregated findings from all scouts.
    
    Collects and summarizes findings from all scout agents
    for submission to the consensus engine.
    
    Attributes:
        radar_findings: Findings from RADAR agent
        devil_findings: Findings from DEVIL agent
        eval_findings: Findings from EVAL agent
        strat_findings: Findings from STRAT agent
        veto_active: Whether a veto is currently active
        veto_reason: Reason for veto if active
        consensus_score: Calculated consensus score (0.0 - 1.0)
        overall_readiness: Overall readiness assessment
    """
    radar_findings: List[ScoutFinding] = field(default_factory=list)
    devil_findings: List[ScoutFinding] = field(default_factory=list)
    eval_findings: List[ScoutFinding] = field(default_factory=list)
    strat_findings: List[ScoutFinding] = field(default_factory=list)
    veto_active: bool = False
    veto_reason: Optional[str] = None
    consensus_score: float = 0.0
    overall_readiness: str = "EXPERIMENTAL"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "radar_findings": [f.to_dict() for f in self.radar_findings],
            "devil_findings": [f.to_dict() for f in self.devil_findings],
            "eval_findings": [f.to_dict() for f in self.eval_findings],
            "strat_findings": [f.to_dict() for f in self.strat_findings],
            "veto_active": self.veto_active,
            "veto_reason": self.veto_reason,
            "consensus_score": self.consensus_score,
            "overall_readiness": self.overall_readiness,
        }
    
    @property
    def total_findings(self) -> int:
        """Total number of findings across all scouts."""
        return (
            len(self.radar_findings) +
            len(self.devil_findings) +
            len(self.eval_findings) +
            len(self.strat_findings)
        )
    
    @property
    def critical_findings(self) -> List[ScoutFinding]:
        """Get all critical severity findings."""
        all_findings = (
            self.radar_findings +
            self.devil_findings +
            self.eval_findings +
            self.strat_findings
        )
        return [f for f in all_findings if f.severity == "SEV-1" or f.impact == "critical"]


@dataclass
class ConsensusResult:
    """
    ITEM-AGENT-001: Result from consensus calculation.
    
    Contains the outcome of submitting scout findings
    to the RoleWeightedConsensus engine.
    
    Attributes:
        approved: Whether the consensus approves the action
        score: Final consensus score (0.0 - 1.0)
        confidence: Confidence level in the result
        veto_triggered: Whether a veto was triggered
        veto_source: Source of veto if triggered
        weighted_scores: Per-role weighted scores
        rationale: Explanation of the decision
    """
    approved: bool
    score: float
    confidence: float
    veto_triggered: bool = False
    veto_source: Optional[str] = None
    weighted_scores: Dict[str, float] = field(default_factory=dict)
    rationale: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "approved": self.approved,
            "score": self.score,
            "confidence": self.confidence,
            "veto_triggered": self.veto_triggered,
            "veto_source": self.veto_source,
            "weighted_scores": self.weighted_scores,
            "rationale": self.rationale,
        }


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
# ScoutMatrix - ITEM-AGENT-001
# =============================================================================

class ScoutMatrix:
    """
    ITEM-AGENT-001: Scout Matrix for multi-agent analysis.
    
    Collects findings from RADAR, DEVIL, EVAL, STRAT scouts and
    integrates with RoleWeightedConsensus for decision making.
    
    The ScoutMatrix provides:
    - Role-weighted consensus calculation
    - Veto rule enforcement
    - Finding aggregation across scouts
    - Integration with ConflictResolver
    
    ROLE_WEIGHTED_CONSENSUS Weights:
    - EVAL (Security): 35% - highest weight, veto power
    - DEVIL (Risk): 30% - risk identification
    - STRAT (Strategy): 20% - strategy synthesis
    - RADAR (Signal): 15% - signal detection
    
    Veto Rules:
    - SEC_VETO: CRITICAL finding or SEV-1 overrides majority
    - DVL_VETO: HYPE/ABANDONED/VULNERABILITY blocks adoption
    - S5_VETO: Security+Strategy >= 55% overrides convenience
    
    Example:
        >>> matrix = ScoutMatrix()
        >>> findings = matrix.aggregate_findings(all_scout_findings)
        >>> result = matrix.submit_to_consensus(findings)
        >>> if result.approved:
        ...     print(f"Approved with score {result.score}")
    """
    
    # Role weights for consensus - aligns with ROLE_WEIGHTED_CONSENSUS
    # SECURITY (EVAL): 35%, RELIABILITY (DEVIL): 25%, UTILITY (STRAT): 25%, CONVENIENCE (RADAR): 15%
    # Adjusted for scout roles: EVAL=35%, DEVIL=30% (reliability+risk), STRAT=20%, RADAR=15%
    ROLE_WEIGHTS: Dict[AgentRole, float] = {
        AgentRole.EVAL: 0.35,    # Security/Evaluation - highest weight, veto power
        AgentRole.DEVIL: 0.30,   # Risk identification - reliability
        AgentRole.STRAT: 0.20,   # Strategy synthesis - utility
        AgentRole.RADAR: 0.15,   # Signal detection - convenience
    }
    
    # Veto rules from protocol
    VETO_RULES: Dict[str, Any] = {
        # SEC_VETO: CRITICAL finding or SEV-1 overrides majority
        "security_veto": ["CRITICAL", "SEV-1", "critical"],
        # DVL_VETO: HYPE/ABANDONED/VULNERABILITY blocks adoption
        "devil_veto": ["HYPE", "ABANDONED", "VULNERABILITY", "hype", "vulnerability"],
        # S5_VETO: SEC+STR >= 55% overrides convenience
        "security_strategy_veto_threshold": 0.55,
    }
    
    # Consensus thresholds
    CONSENSUS_THRESHOLDS: Dict[str, float] = {
        "high_confidence": 0.80,    # High confidence approval
        "medium_confidence": 0.60,  # Medium confidence approval
        "low_confidence": 0.40,     # Low confidence, needs escalation
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the ScoutMatrix.
        
        Args:
            config: Optional configuration dictionary with:
                - custom_weights: Override default role weights
                - custom_veto_rules: Override default veto rules
                - strict_mode: Raise errors on validation failures
        """
        self.config = config or {}
        self._strict_mode = self.config.get("strict_mode", True)
        
        # Allow custom weights if provided
        if "custom_weights" in self.config:
            self._validate_weights(self.config["custom_weights"])
            self._role_weights = self.config["custom_weights"]
        else:
            self._role_weights = self.ROLE_WEIGHTS.copy()
        
        # Allow custom veto rules if provided
        self._veto_rules = self.config.get("custom_veto_rules", self.VETO_RULES.copy())
        
        # Internal state
        self._findings_cache: Dict[str, ScoutFinding] = {}
        
        logger.info(
            f"[ITEM-AGENT-001] ScoutMatrix initialized with weights: "
            f"EVAL={self._role_weights[AgentRole.EVAL]:.0%}, "
            f"DEVIL={self._role_weights[AgentRole.DEVIL]:.0%}, "
            f"STRAT={self._role_weights[AgentRole.STRAT]:.0%}, "
            f"RADAR={self._role_weights[AgentRole.RADAR]:.0%}"
        )
    
    def _validate_weights(self, weights: Dict[AgentRole, float]) -> None:
        """Validate that weights sum to 1.0 and cover all roles."""
        required_roles = {AgentRole.EVAL, AgentRole.DEVIL, AgentRole.STRAT, AgentRole.RADAR}
        provided_roles = set(weights.keys())
        
        if not required_roles.issubset(provided_roles):
            missing = required_roles - provided_roles
            raise ValueError(f"Missing role weights for: {missing}")
        
        total = sum(weights.values())
        if not 0.99 <= total <= 1.01:
            raise ValueError(f"Weights must sum to 1.0, got {total:.4f}")
    
    def collect_findings(
        self,
        scout_type: AgentRole,
        agent_result: AgentResult
    ) -> List[ScoutFinding]:
        """
        Convert agent result to scout findings.
        
        Extracts findings from an AgentResult and converts them
        to ScoutFinding objects for consensus processing.
        
        Args:
            scout_type: The role of the scout agent
            agent_result: Result from agent execution
            
        Returns:
            List of ScoutFinding objects extracted from the result
        """
        findings: List[ScoutFinding] = []
        
        if not agent_result.success:
            # Create a failure finding
            findings.append(ScoutFinding(
                finding_id=f"{scout_type.value}_failure_{id(agent_result)}",
                role=scout_type,
                finding_type=ScoutFindingType.BLOCKER,
                severity="SEV-2",
                title=f"{scout_type.value.upper()} Agent Failed",
                description=agent_result.error or "Agent execution failed",
                confidence=0.0,
                impact="high",
                recommendation="Review agent execution and retry",
                metadata={"success": False}
            ))
            return findings
        
        # Extract findings based on scout type
        output = agent_result.output or {}
        
        if scout_type == AgentRole.RADAR:
            findings.extend(self._extract_radar_findings(output))
        elif scout_type == AgentRole.DEVIL:
            findings.extend(self._extract_devil_findings(output))
        elif scout_type == AgentRole.EVAL:
            findings.extend(self._extract_eval_findings(output))
        elif scout_type == AgentRole.STRAT:
            findings.extend(self._extract_strat_findings(output))
        
        # Cache findings
        for finding in findings:
            self._findings_cache[finding.finding_id] = finding
        
        logger.debug(
            f"[ITEM-AGENT-001] Collected {len(findings)} findings from {scout_type.value}"
        )
        
        return findings
    
    def _extract_radar_findings(self, output: Dict[str, Any]) -> List[ScoutFinding]:
        """Extract findings from RADAR agent output."""
        findings: List[ScoutFinding] = []
        
        # Signal strength finding
        signal_strength = output.get("signal_strength", "MODERATE")
        domain_analysis = output.get("domain_analysis", {})
        
        findings.append(ScoutFinding(
            finding_id=f"radar_signal_{id(output)}",
            role=AgentRole.RADAR,
            finding_type=ScoutFindingType.SIGNAL,
            severity="SEV-4",
            title=f"Signal Strength: {signal_strength}",
            description=f"Domain {output.get('domain', 'unknown')} has {signal_strength} signal",
            confidence=domain_analysis.get("maturity_score", 0.5),
            impact="low",
            recommendation="Consider signal strength in adoption decision",
            metadata={"signal_strength": signal_strength, "domain": output.get("domain")}
        ))
        
        # Risk factors as findings
        for idx, risk in enumerate(domain_analysis.get("risk_factors", [])):
            findings.append(ScoutFinding(
                finding_id=f"radar_risk_{idx}_{id(output)}",
                role=AgentRole.RADAR,
                finding_type=ScoutFindingType.RISK,
                severity="SEV-3",
                title=f"Domain Risk: {risk}",
                description=f"Risk factor detected in domain analysis: {risk}",
                confidence=0.7,
                impact="medium",
                recommendation="Monitor this risk factor",
                metadata={"risk_factor": risk}
            ))
        
        return findings
    
    def _extract_devil_findings(self, output: Dict[str, Any]) -> List[ScoutFinding]:
        """Extract findings from DEVIL agent output."""
        findings: List[ScoutFinding] = []
        
        hype_score = output.get("hype_score", 0.0)
        
        # Hype flags as findings
        for idx, hype in enumerate(output.get("hype_flags", [])):
            findings.append(ScoutFinding(
                finding_id=f"devil_hype_{idx}_{id(output)}",
                role=AgentRole.DEVIL,
                finding_type=ScoutFindingType.HYPE,
                severity="SEV-3",
                title=f"Hype Detected: {hype}",
                description=f"Marketing hype indicator found: {hype}",
                confidence=min(hype_score + 0.3, 1.0),
                impact="medium",
                recommendation="Verify claims independently",
                metadata={"hype_indicator": hype, "hype_score": hype_score}
            ))
        
        # Risk flags as findings
        for idx, risk in enumerate(output.get("risk_flags", [])):
            # Determine severity based on risk type
            severity = "SEV-3"
            impact = "medium"
            if "experimental" in risk.lower() or "alpha" in risk.lower():
                severity = "SEV-2"
                impact = "high"
            
            findings.append(ScoutFinding(
                finding_id=f"devil_risk_{idx}_{id(output)}",
                role=AgentRole.DEVIL,
                finding_type=ScoutFindingType.RISK,
                severity=severity,
                title=f"Risk Factor: {risk}",
                description=f"Risk indicator detected: {risk}",
                confidence=0.8,
                impact=impact,
                recommendation="Address risk before proceeding",
                metadata={"risk_indicator": risk}
            ))
        
        # Unverified claims as findings
        for idx, claim in enumerate(output.get("unverified_claims", [])):
            findings.append(ScoutFinding(
                finding_id=f"devil_unverified_{idx}_{id(output)}",
                role=AgentRole.DEVIL,
                finding_type=ScoutFindingType.RISK,
                severity="SEV-3",
                title=f"Unverified Claim: {claim}",
                description=f"Claim requires verification: {claim}",
                confidence=0.6,
                impact="medium",
                recommendation="Seek additional evidence",
                metadata={"unverified_claim": claim}
            ))
        
        # Veto from DEVIL
        if output.get("veto_triggered"):
            findings.append(ScoutFinding(
                finding_id=f"devil_veto_{id(output)}",
                role=AgentRole.DEVIL,
                finding_type=ScoutFindingType.VETO,
                severity="SEV-1",
                title="DEVIL Veto Triggered",
                description=output.get("veto_reason", "High risk detected"),
                confidence=0.9,
                impact="critical",
                recommendation="Do not proceed without addressing risks",
                metadata={"veto_reason": output.get("veto_reason")}
            ))
        
        return findings
    
    def _extract_eval_findings(self, output: Dict[str, Any]) -> List[ScoutFinding]:
        """Extract findings from EVAL agent output."""
        findings: List[ScoutFinding] = []
        
        readiness = output.get("readiness", "EXPERIMENTAL")
        tier_details = output.get("tier_details", {})
        
        # Readiness finding
        severity = "SEV-4"
        impact = "low"
        if readiness in ("EXPERIMENTAL", "VAPORWARE"):
            severity = "SEV-2"
            impact = "high"
        elif readiness == "EARLY_ADOPTER":
            severity = "SEV-3"
            impact = "medium"
        
        findings.append(ScoutFinding(
            finding_id=f"eval_readiness_{id(output)}",
            role=AgentRole.EVAL,
            finding_type=ScoutFindingType.RECOMMENDATION,
            severity=severity,
            title=f"Readiness: {readiness}",
            description=tier_details.get("description", f"Adoption readiness: {readiness}"),
            confidence=0.85,
            impact=impact,
            recommendation=tier_details.get("recommendation", "Proceed with caution"),
            metadata={"readiness_tier": readiness, "tier_details": tier_details}
        ))
        
        # Veto from EVAL
        if output.get("veto_active"):
            findings.append(ScoutFinding(
                finding_id=f"eval_veto_{id(output)}",
                role=AgentRole.EVAL,
                finding_type=ScoutFindingType.VETO,
                severity="SEV-1",
                title="EVAL Veto Active",
                description=f"Strategy blocked due to {readiness} readiness tier",
                confidence=0.95,
                impact="critical",
                recommendation=tier_details.get("recommendation", "Do not proceed"),
                metadata={"blocking_tier": readiness}
            ))
        
        return findings
    
    def _extract_strat_findings(self, output: Dict[str, Any]) -> List[ScoutFinding]:
        """Extract findings from STRAT agent output."""
        findings: List[ScoutFinding] = []
        
        # Caveats as findings
        for idx, caveat in enumerate(output.get("caveats", [])):
            findings.append(ScoutFinding(
                finding_id=f"strat_caveat_{idx}_{id(output)}",
                role=AgentRole.STRAT,
                finding_type=ScoutFindingType.CAVEAT,
                severity="SEV-3",
                title=f"Caveat: {caveat}",
                description=f"Strategy caveat: {caveat}",
                confidence=0.75,
                impact="medium",
                recommendation="Address caveat in implementation",
                metadata={"caveat": caveat}
            ))
        
        # Strategy recommendation
        if output.get("strategy") and not output.get("vetoed"):
            findings.append(ScoutFinding(
                finding_id=f"strat_strategy_{id(output)}",
                role=AgentRole.STRAT,
                finding_type=ScoutFindingType.RECOMMENDATION,
                severity="SEV-4",
                title="Strategy Synthesized",
                description="Strategy has been synthesized and is ready for review",
                confidence=0.7,
                impact="low",
                recommendation="Review strategy and proceed with implementation",
                metadata={"strategy_generated": True}
            ))
        
        # Vetoed status
        if output.get("vetoed"):
            findings.append(ScoutFinding(
                finding_id=f"strat_blocked_{id(output)}",
                role=AgentRole.STRAT,
                finding_type=ScoutFindingType.BLOCKER,
                severity="SEV-2",
                title="STRAT Blocked",
                description=output.get("veto_reason", "Strategy synthesis blocked"),
                confidence=0.9,
                impact="high",
                recommendation="Address blocking issues before strategy synthesis",
                metadata={"blocked": True, "veto_reason": output.get("veto_reason")}
            ))
        
        return findings
    
    def aggregate_findings(
        self,
        all_findings: Dict[AgentRole, List[ScoutFinding]]
    ) -> AggregatedFindings:
        """
        Aggregate findings from all scouts.
        
        Combines findings from all scout agents and calculates
        overall metrics for consensus submission.
        
        Args:
            all_findings: Dictionary mapping scout roles to their findings
            
        Returns:
            AggregatedFindings with combined analysis
        """
        radar_findings = all_findings.get(AgentRole.RADAR, [])
        devil_findings = all_findings.get(AgentRole.DEVIL, [])
        eval_findings = all_findings.get(AgentRole.EVAL, [])
        strat_findings = all_findings.get(AgentRole.STRAT, [])
        
        # Check for veto
        veto_active, veto_reason = self._check_veto_in_findings(
            radar_findings + devil_findings + eval_findings + strat_findings
        )
        
        # Calculate consensus score
        consensus_score = self.calculate_consensus_score(all_findings)
        
        # Determine overall readiness
        overall_readiness = self._determine_readiness(
            eval_findings, devil_findings, consensus_score
        )
        
        aggregated = AggregatedFindings(
            radar_findings=radar_findings,
            devil_findings=devil_findings,
            eval_findings=eval_findings,
            strat_findings=strat_findings,
            veto_active=veto_active,
            veto_reason=veto_reason,
            consensus_score=consensus_score,
            overall_readiness=overall_readiness
        )
        
        logger.info(
            f"[ITEM-AGENT-001] Aggregated {aggregated.total_findings} findings, "
            f"consensus={consensus_score:.2f}, veto={veto_active}"
        )
        
        return aggregated
    
    def _check_veto_in_findings(
        self,
        findings: List[ScoutFinding]
    ) -> tuple[bool, Optional[str]]:
        """Check if any findings trigger a veto."""
        veto_result = self.check_veto_rules(findings)
        return (veto_result is not None, veto_result)
    
    def check_veto_rules(self, findings: List[ScoutFinding]) -> Optional[str]:
        """
        Check if any veto rules are triggered.
        
        Implements the three veto rules from the protocol:
        1. SEC_VETO: CRITICAL/SEV-1 findings from EVAL
        2. DVL_VETO: HYPE/VULNERABILITY findings from DEVIL
        3. S5_VETO: Security+Strategy combined weight >= 55%
        
        Args:
            findings: List of findings to check
            
        Returns:
            Veto reason if triggered, None otherwise
        """
        for finding in findings:
            # SEC_VETO: CRITICAL finding overrides majority
            if finding.severity in self._veto_rules["security_veto"]:
                return f"SEC_VETO: {finding.title}"
            
            if finding.impact in self._veto_rules["security_veto"]:
                return f"SEC_VETO: {finding.title}"
            
            # DVL_VETO: HYPE/ABANDONED/VULNERABILITY blocks adoption
            if finding.finding_type.value in self._veto_rules["devil_veto"]:
                return f"DVL_VETO: {finding.title}"
            
            # Check for veto finding type
            if finding.finding_type == ScoutFindingType.VETO:
                return f"SCOUT_VETO: {finding.title}"
        
        return None
    
    def calculate_consensus_score(
        self,
        findings: Dict[AgentRole, List[ScoutFinding]]
    ) -> float:
        """
        Calculate weighted consensus score.
        
        Computes a weighted average of confidence scores across
        all scout roles using the ROLE_WEIGHTS.
        
        Args:
            findings: Dictionary mapping roles to their findings
            
        Returns:
            Weighted consensus score (0.0 - 1.0)
        """
        total_score = 0.0
        total_weight = 0.0
        
        for role, role_findings in findings.items():
            if not role_findings:
                continue
            
            weight = self._role_weights.get(role, 0.0)
            
            # Calculate average confidence for this role
            avg_confidence = sum(f.confidence for f in role_findings) / len(role_findings)
            
            # Apply role weight
            total_score += avg_confidence * weight
            total_weight += weight
        
        # Normalize if not all roles had findings
        if total_weight > 0 and total_weight < 1.0:
            total_score = total_score / total_weight
        
        logger.debug(
            f"[ITEM-AGENT-001] Consensus score: {total_score:.3f} "
            f"(from {sum(len(f) for f in findings.values())} findings)"
        )
        
        return round(total_score, 3)
    
    def _determine_readiness(
        self,
        eval_findings: List[ScoutFinding],
        devil_findings: List[ScoutFinding],
        consensus_score: float
    ) -> str:
        """Determine overall readiness from findings."""
        # Check EVAL findings first
        for finding in eval_findings:
            if finding.finding_type == ScoutFindingType.RECOMMENDATION:
                readiness = finding.metadata.get("readiness_tier", "EXPERIMENTAL")
                return readiness
        
        # Fall back to consensus-based determination
        if consensus_score >= 0.75:
            return "PRODUCTION_READY"
        elif consensus_score >= 0.55:
            return "EARLY_ADOPTER"
        elif consensus_score >= 0.35:
            return "EXPERIMENTAL"
        else:
            return "VAPORWARE"
    
    def submit_to_consensus(
        self,
        aggregated: AggregatedFindings
    ) -> ConsensusResult:
        """
        Submit findings to RoleWeightedConsensus.
        
        Processes aggregated findings through the consensus engine
        to produce a final decision result.
        
        Args:
            aggregated: Aggregated findings from all scouts
            
        Returns:
            ConsensusResult with approval status and details
        """
        # Check for veto first
        if aggregated.veto_active:
            logger.warning(
                f"[ITEM-AGENT-001] Consensus blocked by veto: {aggregated.veto_reason}"
            )
            return ConsensusResult(
                approved=False,
                score=aggregated.consensus_score,
                confidence=1.0,
                veto_triggered=True,
                veto_source=aggregated.veto_reason,
                rationale=f"Veto triggered: {aggregated.veto_reason}"
            )
        
        # Calculate weighted scores per role
        weighted_scores: Dict[str, float] = {}
        
        for role in [AgentRole.EVAL, AgentRole.DEVIL, AgentRole.STRAT, AgentRole.RADAR]:
            findings_map = {
                AgentRole.EVAL: aggregated.eval_findings,
                AgentRole.DEVIL: aggregated.devil_findings,
                AgentRole.STRAT: aggregated.strat_findings,
                AgentRole.RADAR: aggregated.radar_findings,
            }
            role_findings = findings_map[role]
            weight = self._role_weights[role]
            
            if role_findings:
                avg_conf = sum(f.confidence for f in role_findings) / len(role_findings)
                weighted_scores[role.value] = round(avg_conf * weight, 3)
            else:
                weighted_scores[role.value] = 0.0
        
        # Check S5_VETO: Security+Strategy >= 55% overrides convenience
        sec_strat_score = (
            weighted_scores.get("eval", 0.0) +
            weighted_scores.get("strat", 0.0)
        )
        
        # Determine approval
        score = aggregated.consensus_score
        
        if score >= self.CONSENSUS_THRESHOLDS["high_confidence"]:
            approved = True
            confidence = 0.95
            rationale = f"High confidence approval (score: {score:.2f})"
        elif score >= self.CONSENSUS_THRESHOLDS["medium_confidence"]:
            approved = True
            confidence = 0.80
            rationale = f"Medium confidence approval (score: {score:.2f})"
        elif score >= self.CONSENSUS_THRESHOLDS["low_confidence"]:
            approved = False
            confidence = 0.60
            rationale = f"Low confidence, escalation recommended (score: {score:.2f})"
        else:
            approved = False
            confidence = 0.40
            rationale = f"Insufficient consensus (score: {score:.2f})"
        
        # S5_VETO check - if SEC+STR >= 55% and they disapprove, override
        if sec_strat_score >= self._veto_rules["security_strategy_veto_threshold"]:
            # Check if EVAL findings are negative
            eval_negative = any(
                f.severity in ("SEV-1", "SEV-2") or f.impact in ("critical", "high")
                for f in aggregated.eval_findings
            )
            if eval_negative:
                approved = False
                rationale = f"S5_VETO: Security+Strategy ({sec_strat_score:.0%}) overrides"
        
        result = ConsensusResult(
            approved=approved,
            score=score,
            confidence=confidence,
            veto_triggered=False,
            weighted_scores=weighted_scores,
            rationale=rationale
        )
        
        logger.info(
            f"[ITEM-AGENT-001] Consensus result: approved={approved}, "
            f"score={score:.2f}, confidence={confidence:.0%}"
        )
        
        return result
    
    def get_role_weights(self) -> Dict[AgentRole, float]:
        """Get current role weights."""
        return self._role_weights.copy()
    
    def get_veto_rules(self) -> Dict[str, Any]:
        """Get current veto rules."""
        return self._veto_rules.copy()


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
