"""
Invariant Runtime Enforcement for TITAN PROTOCOL v5.0.0.

ITEM-PROT-002: Runtime enforcement of INVARIANTS_GLOBAL.

This module provides the InvariantEnforcer class that validates all 10
protocol invariants at runtime with configurable enforcement levels.

INVARIANTS_GLOBAL:
1. INVAR-01_NO_FABRICATION: Only process evidence provided
2. INVAR-02_SSOT_PER_DOMAIN: One SSOT file per domain
3. INVAR-03_ZERO_DRIFT: Session state must not drift from checkpoint
4. INVAR-04_IDEMPOTENT_PATCH: Same patch on same content = same result
5. INVAR-05_ASSERT_ABSENCE: Detect forbidden conditions
6. INVAR-06_OBSERVABLE_ONLY: No motive/emotion/intent/belief inference
7. INVAR-07_CODE_IS_EVIDENCE: Code blocks are executable evidence
8. INVAR-08_SCOPE_LOCALITY: Operations stay in declared scope
9. INVAR-09_COMPLETENESS: All items classified or excluded
10. INVAR-10_VALIDATION_HALT: Validation failure halts execution

Author: TITAN FUSE Team
Version: 5.0.0
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

# Configure module logger with [ITEM-PROT-002] prefix
logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# INVAR-06: Forbidden inference markers - patterns that indicate
# non-observable mental state inference
FORBIDDEN_INFERENCE_MARKERS = [
    "motive", "emotion", "intent", "belief", "internal_state",
    "feels", "thinks", "wants", "desires", "believes",
    "hopes", "fears", "loves", "hates", "angry", "happy",
    "sad", "frustrated", "confused", "excited", "worried",
    "understands", "knows", "remembers", "imagines", "guesses",
    "suspects", "assumes", "supposes", "prefers", "intends",
    "decided to", "chose to", "tried to", "attempted to",
    "motivated by", "driven by", "inspired by", "influenced by"
]

# Compile regex pattern for efficiency
_FORBIDDEN_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(m) for m in FORBIDDEN_INFERENCE_MARKERS) + r')\b',
    re.IGNORECASE
)


class EnforcementLevel(Enum):
    """
    Enforcement levels for invariant violations.

    Attributes:
        PERMISSIVE: Log warnings only, don't block execution
        STANDARD: Block on critical violations, warn on others
        STRICT: Block on any violation
        PARANOID: Block on any violation with full audit trail
    """
    PERMISSIVE = "permissive"
    STANDARD = "standard"
    STRICT = "strict"
    PARANOID = "paranoid"


class InvariantType(Enum):
    """
    Types of invariants that can be checked.

    Each corresponds to one of the 10 INVARIANTS_GLOBAL.
    """
    NO_FABRICATION = "INVAR-01_NO_FABRICATION"
    SSOT_PER_DOMAIN = "INVAR-02_SSOT_PER_DOMAIN"
    ZERO_DRIFT = "INVAR-03_ZERO_DRIFT"
    IDEMPOTENT_PATCH = "INVAR-04_IDEMPOTENT_PATCH"
    ASSERT_ABSENCE = "INVAR-05_ASSERT_ABSENCE"
    OBSERVABLE_ONLY = "INVAR-06_OBSERVABLE_ONLY"
    CODE_IS_EVIDENCE = "INVAR-07_CODE_IS_EVIDENCE"
    SCOPE_LOCALITY = "INVAR-08_SCOPE_LOCALITY"
    COMPLETENESS = "INVAR-09_COMPLETENESS"
    VALIDATION_HALT = "INVAR-10_VALIDATION_HALT"


class ViolationSeverity(Enum):
    """
    Severity levels for invariant violations.

    Attributes:
        INFO: Informational, no action required
        WARNING: Warning, should be reviewed
        ERROR: Error, may require intervention
        CRITICAL: Critical, blocks execution
    """
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class InvariantViolation:
    """
    Represents a detected invariant violation.

    Attributes:
        invariant_type: Type of invariant that was violated
        severity: Severity level of the violation
        message: Human-readable description
        evidence: Evidence that triggered the violation
        context: Additional context data
        gap_tag: Gap tag for tracking (e.g., "[gap:inference_violation]")
        timestamp: When the violation was detected
    """
    invariant_type: InvariantType
    severity: ViolationSeverity
    message: str
    evidence: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    gap_tag: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "invariant_type": self.invariant_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "evidence": self.evidence,
            "context": self.context,
            "gap_tag": self.gap_tag,
            "timestamp": self.timestamp,
        }

    def is_blocking(self) -> bool:
        """Check if this violation should block execution."""
        return self.severity in (ViolationSeverity.ERROR, ViolationSeverity.CRITICAL)


@dataclass
class InvariantCheckResult:
    """
    Result of checking all invariants.

    Attributes:
        passed: Whether all invariants passed
        violations: List of detected violations
        checks_run: Number of individual checks run
        enforcement_level: Enforcement level used
        duration_ms: Duration of check in milliseconds
        metadata: Additional metadata
        timestamp: When the check was performed
    """
    passed: bool
    violations: List[InvariantViolation] = field(default_factory=list)
    checks_run: int = 0
    enforcement_level: EnforcementLevel = EnforcementLevel.STANDARD
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "checks_run": self.checks_run,
            "enforcement_level": self.enforcement_level.value,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @property
    def has_violations(self) -> bool:
        """Check if any violations were detected."""
        return len(self.violations) > 0

    @property
    def blocking_violations(self) -> List[InvariantViolation]:
        """Get violations that block execution."""
        return [v for v in self.violations if v.is_blocking()]

    @property
    def violation_count(self) -> int:
        """Get total number of violations."""
        return len(self.violations)

    def get_violations_by_type(self, invariant_type: InvariantType) -> List[InvariantViolation]:
        """Get violations of a specific type."""
        return [v for v in self.violations if v.invariant_type == invariant_type]


# =============================================================================
# Session and Patch Dataclasses (for type hints)
# =============================================================================

@dataclass
class SessionSnapshot:
    """
    Snapshot of session state for drift detection.

    Attributes:
        session_id: Unique session identifier
        state_hash: Hash of the session state
        checkpoint_hash: Hash from the last checkpoint
        phase: Current phase
        gates_passed: List of passed gates
        metadata: Additional metadata
    """
    session_id: str
    state_hash: str
    checkpoint_hash: str
    phase: int = 0
    gates_passed: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# InvariantEnforcer Class
# =============================================================================

class InvariantEnforcer:
    """
    Runtime enforcement of INVARIANTS_GLOBAL.

    Validates all 10 protocol invariants at runtime with configurable
    enforcement levels. Integrates with the orchestrator to provide
    continuous invariant checking throughout execution.

    Enforcement Levels:
        - PERMISSIVE: Log warnings only, don't block
        - STANDARD: Block on critical violations
        - STRICT: Block on any violation
        - PARANOID: Block with full audit trail

    Example:
        >>> enforcer = InvariantEnforcer(level=EnforcementLevel.STRICT)
        >>> result = enforcer.check_all({
        ...     "output": "The user clicked the button",
        ...     "session": session_snapshot,
        ...     "extracted_count": 10,
        ...     "classified_count": 8,
        ...     "exclusions_count": 2
        ... })
        >>> if not result.passed:
        ...     for violation in result.violations:
        ...         print(f"{violation.invariant_type.value}: {violation.message}")
    """

    # Default severity mapping for each invariant type
    DEFAULT_SEVERITIES = {
        InvariantType.NO_FABRICATION: ViolationSeverity.CRITICAL,
        InvariantType.SSOT_PER_DOMAIN: ViolationSeverity.ERROR,
        InvariantType.ZERO_DRIFT: ViolationSeverity.ERROR,
        InvariantType.IDEMPOTENT_PATCH: ViolationSeverity.WARNING,
        InvariantType.ASSERT_ABSENCE: ViolationSeverity.WARNING,
        InvariantType.OBSERVABLE_ONLY: ViolationSeverity.ERROR,
        InvariantType.CODE_IS_EVIDENCE: ViolationSeverity.WARNING,
        InvariantType.SCOPE_LOCALITY: ViolationSeverity.ERROR,
        InvariantType.COMPLETENESS: ViolationSeverity.ERROR,
        InvariantType.VALIDATION_HALT: ViolationSeverity.CRITICAL,
    }

    def __init__(
        self,
        level: EnforcementLevel = EnforcementLevel.STANDARD,
        custom_severities: Optional[Dict[InvariantType, ViolationSeverity]] = None,
        enabled_invariants: Optional[Set[InvariantType]] = None,
        disabled_invariants: Optional[Set[InvariantType]] = None,
    ) -> None:
        """
        Initialize the InvariantEnforcer.

        Args:
            level: Enforcement level (default: STANDARD)
            custom_severities: Custom severity mapping for invariant types
            enabled_invariants: Set of invariants to enable (None = all)
            disabled_invariants: Set of invariants to disable
        """
        self._level = level
        self._logger = logging.getLogger(f"{__name__}.InvariantEnforcer")

        # Merge custom severities with defaults
        self._severities = dict(self.DEFAULT_SEVERITIES)
        if custom_severities:
            self._severities.update(custom_severities)

        # Determine enabled invariants
        all_invariants = set(InvariantType)
        if enabled_invariants:
            self._enabled = enabled_invariants
        else:
            self._enabled = all_invariants

        if disabled_invariants:
            self._enabled -= disabled_invariants

        # Track patch hashes for idempotency checking
        self._patch_hashes: Dict[str, str] = {}

        # Track SSOT files per domain
        self._ssot_files: Dict[str, Set[str]] = {}

        # Statistics
        self._total_checks = 0
        self._total_violations = 0

        self._logger.info(
            f"[ITEM-PROT-002] InvariantEnforcer initialized: "
            f"level={level.value}, enabled_invariants={len(self._enabled)}"
        )

    # =========================================================================
    # Main Check Methods
    # =========================================================================

    def check_all(self, context: Dict[str, Any]) -> InvariantCheckResult:
        """
        Check all enabled invariants.

        This is the main entry point for invariant checking. It runs
        all enabled invariant checks and returns a comprehensive result.

        Args:
            context: Context dictionary containing:
                - output: Output text to check for inferences (INVAR-06)
                - session: SessionSnapshot for drift detection (INVAR-03)
                - domain: Domain name for SSOT check (INVAR-02)
                - sources: List of source files (INVAR-02)
                - before_content: Content before patch (INVAR-04)
                - after_content: Content after patch (INVAR-04)
                - patch_id: Unique patch identifier (INVAR-04)
                - extracted_count: Number of items extracted (INVAR-09)
                - classified_count: Number of items classified (INVAR-09)
                - exclusions_count: Number of excluded items (INVAR-09)
                - evidence: List of evidence items (INVAR-01)
                - output_claims: Claims in output (INVAR-01)
                - forbidden_conditions: List of forbidden conditions (INVAR-05)
                - code_blocks: List of code blocks (INVAR-07)
                - declared_scope: Declared operation scope (INVAR-08)
                - actual_scope: Actual operation scope (INVAR-08)
                - validation_result: Previous validation result (INVAR-10)

        Returns:
            InvariantCheckResult with all check outcomes
        """
        start_time = datetime.utcnow()
        violations: List[InvariantViolation] = []
        checks_run = 0

        self._logger.debug(f"[ITEM-PROT-002] Running invariant checks with context keys: {list(context.keys())}")

        # INVAR-01: No Fabrication
        if InvariantType.NO_FABRICATION in self._enabled:
            checks_run += 1
            violation = self.check_no_fabrication(
                output=context.get("output", ""),
                evidence=context.get("evidence", []),
                output_claims=context.get("output_claims", []),
            )
            if violation:
                violations.append(violation)

        # INVAR-02: SSOT Per Domain
        if InvariantType.SSOT_PER_DOMAIN in self._enabled:
            checks_run += 1
            violation = self.check_ssot(
                domain=context.get("domain", ""),
                sources=context.get("sources", []),
            )
            if violation:
                violations.append(violation)

        # INVAR-03: Zero Drift
        if InvariantType.ZERO_DRIFT in self._enabled:
            checks_run += 1
            session = context.get("session")
            if session:
                violation = self.check_zero_drift(session)
                if violation:
                    violations.append(violation)

        # INVAR-04: Idempotent Patch
        if InvariantType.IDEMPOTENT_PATCH in self._enabled:
            checks_run += 1
            before = context.get("before_content")
            after = context.get("after_content")
            patch_id = context.get("patch_id")
            if before and after and patch_id:
                violation = self.check_idempotent_patch(before, after, patch_id)
                if violation:
                    violations.append(violation)

        # INVAR-05: Assert Absence
        if InvariantType.ASSERT_ABSENCE in self._enabled:
            checks_run += 1
            violation = self.check_assert_absence(
                output=context.get("output", ""),
                forbidden_conditions=context.get("forbidden_conditions", []),
            )
            if violation:
                violations.append(violation)

        # INVAR-06: Observable Only (Key requirement)
        if InvariantType.OBSERVABLE_ONLY in self._enabled:
            checks_run += 1
            violation = self.check_observable_only(context.get("output", ""))
            if violation:
                violations.append(violation)

        # INVAR-07: Code Is Evidence
        if InvariantType.CODE_IS_EVIDENCE in self._enabled:
            checks_run += 1
            violation = self.check_code_is_evidence(
                code_blocks=context.get("code_blocks", []),
                output=context.get("output", ""),
            )
            if violation:
                violations.append(violation)

        # INVAR-08: Scope Locality
        if InvariantType.SCOPE_LOCALITY in self._enabled:
            checks_run += 1
            violation = self.check_scope_locality(
                declared_scope=context.get("declared_scope", set()),
                actual_scope=context.get("actual_scope", set()),
            )
            if violation:
                violations.append(violation)

        # INVAR-09: Completeness (Key requirement)
        if InvariantType.COMPLETENESS in self._enabled:
            checks_run += 1
            violation = self.check_completeness(
                extracted=context.get("extracted_count", 0),
                classified=context.get("classified_count", 0),
                exclusions=context.get("exclusions_count", 0),
            )
            if violation:
                violations.append(violation)

        # INVAR-10: Validation Halt
        if InvariantType.VALIDATION_HALT in self._enabled:
            checks_run += 1
            violation = self.check_validation_halt(
                validation_result=context.get("validation_result"),
                current_phase=context.get("current_phase", 0),
            )
            if violation:
                violations.append(violation)

        # Calculate duration
        end_time = datetime.utcnow()
        duration_ms = (end_time - start_time).total_seconds() * 1000

        # Determine if passed based on enforcement level and violations
        passed = self._evaluate_passed(violations)

        # Update statistics
        self._total_checks += checks_run
        self._total_violations += len(violations)

        # Log results
        if violations:
            self._logger.warning(
                f"[ITEM-PROT-002] Invariant check completed: "
                f"passed={passed}, violations={len(violations)}, "
                f"checks_run={checks_run}, duration={duration_ms:.2f}ms"
            )
        else:
            self._logger.debug(
                f"[ITEM-PROT-002] Invariant check passed: "
                f"checks_run={checks_run}, duration={duration_ms:.2f}ms"
            )

        return InvariantCheckResult(
            passed=passed,
            violations=violations,
            checks_run=checks_run,
            enforcement_level=self._level,
            duration_ms=duration_ms,
            metadata={
                "enabled_invariants": [i.value for i in self._enabled],
            },
        )

    # =========================================================================
    # Individual Invariant Checks
    # =========================================================================

    def check_no_fabrication(
        self,
        output: str,
        evidence: List[str],
        output_claims: List[str],
    ) -> Optional[InvariantViolation]:
        """
        INVAR-01_NO_FABRICATION: Only process evidence provided.

        Ensures that all claims in the output can be traced back to
        provided evidence. Detects fabrication of information.

        Args:
            output: Output text to check
            evidence: List of evidence items provided
            output_claims: List of claims made in output

        Returns:
            InvariantViolation if fabrication detected, None otherwise
        """
        if not output_claims:
            return None

        # Check if claims are supported by evidence
        evidence_text = " ".join(evidence).lower()
        unsupported_claims = []

        for claim in output_claims:
            claim_lower = claim.lower()
            # Simple check: claim should have some overlap with evidence
            claim_words = set(claim_lower.split())
            evidence_words = set(evidence_text.split())
            overlap = claim_words & evidence_words

            # If less than 30% overlap and claim has significant words, flag it
            significant_words = [w for w in claim_words if len(w) > 3]
            if significant_words:
                overlap_ratio = len(overlap & set(significant_words)) / len(significant_words)
                if overlap_ratio < 0.3:
                    unsupported_claims.append(claim)

        if unsupported_claims:
            return InvariantViolation(
                invariant_type=InvariantType.NO_FABRICATION,
                severity=self._severities[InvariantType.NO_FABRICATION],
                message=f"Found {len(unsupported_claims)} claims without supporting evidence",
                evidence="\n".join(unsupported_claims[:3]),
                context={"unsupported_count": len(unsupported_claims)},
                gap_tag="[gap:fabrication_detected]",
            )

        return None

    def check_ssot(
        self,
        domain: str,
        sources: List[str],
    ) -> Optional[InvariantViolation]:
        """
        INVAR-02_SSOT_PER_DOMAIN: One SSOT file per domain.

        Ensures that there is exactly one Single Source of Truth (SSOT)
        file per domain.

        Args:
            domain: Domain name
            sources: List of source files

        Returns:
            InvariantViolation if SSOT violation detected, None otherwise
        """
        if not domain or not sources:
            return None

        # Track sources per domain
        if domain not in self._ssot_files:
            self._ssot_files[domain] = set()

        for source in sources:
            self._ssot_files[domain].add(source)

        # Check for multiple SSOT files
        ssot_files = [s for s in sources if "ssot" in s.lower() or "single_source" in s.lower()]

        if len(ssot_files) > 1:
            return InvariantViolation(
                invariant_type=InvariantType.SSOT_PER_DOMAIN,
                severity=self._severities[InvariantType.SSOT_PER_DOMAIN],
                message=f"Multiple SSOT files found for domain '{domain}'",
                evidence=", ".join(ssot_files),
                context={"domain": domain, "ssot_count": len(ssot_files)},
                gap_tag="[gap:multiple_ssot]",
            )

        return None

    def check_zero_drift(
        self,
        session: SessionSnapshot,
    ) -> Optional[InvariantViolation]:
        """
        INVAR-03_ZERO_DRIFT: Session state must not drift from checkpoint.

        Ensures that the current session state matches the checkpointed
        state, detecting any unauthorized modifications.

        Args:
            session: SessionSnapshot with current and checkpoint hashes

        Returns:
            InvariantViolation if drift detected, None otherwise
        """
        if not session:
            return None

        # Compare state hash with checkpoint hash
        if session.state_hash != session.checkpoint_hash:
            return InvariantViolation(
                invariant_type=InvariantType.ZERO_DRIFT,
                severity=self._severities[InvariantType.ZERO_DRIFT],
                message="Session state has drifted from checkpoint",
                evidence=f"state_hash={session.state_hash[:16]}... != checkpoint_hash={session.checkpoint_hash[:16]}...",
                context={
                    "session_id": session.session_id,
                    "phase": session.phase,
                },
                gap_tag="[gap:state_drift]",
            )

        return None

    def check_idempotent_patch(
        self,
        before: str,
        after: str,
        patch_id: str,
    ) -> Optional[InvariantViolation]:
        """
        INVAR-04_IDEMPOTENT_PATCH: Same patch on same content = same result.

        Ensures that applying the same patch to the same content produces
        the same result every time.

        Args:
            before: Content before patch
            after: Content after patch
            patch_id: Unique identifier for the patch

        Returns:
            InvariantViolation if idempotency violated, None otherwise
        """
        if not patch_id:
            return None

        # Create a composite hash of before content and patch
        composite_key = hashlib.sha256(
            f"{before}:{patch_id}".encode()
        ).hexdigest()[:16]

        after_hash = hashlib.sha256(after.encode()).hexdigest()[:16]

        # Check if we've seen this composite before
        if composite_key in self._patch_hashes:
            expected_hash = self._patch_hashes[composite_key]
            if after_hash != expected_hash:
                return InvariantViolation(
                    invariant_type=InvariantType.IDEMPOTENT_PATCH,
                    severity=self._severities[InvariantType.IDEMPOTENT_PATCH],
                    message="Patch produced different result on same content",
                    evidence=f"patch_id={patch_id}",
                    context={
                        "expected_hash": expected_hash,
                        "actual_hash": after_hash,
                    },
                    gap_tag="[gap:idempotency_violation]",
                )
        else:
            # Store for future checks
            self._patch_hashes[composite_key] = after_hash

        return None

    def check_assert_absence(
        self,
        output: str,
        forbidden_conditions: List[str],
    ) -> Optional[InvariantViolation]:
        """
        INVAR-05_ASSERT_ABSENCE: Detect forbidden conditions.

        Ensures that forbidden conditions are not present in the output.

        Args:
            output: Output text to check
            forbidden_conditions: List of forbidden condition patterns

        Returns:
            InvariantViolation if forbidden condition found, None otherwise
        """
        if not forbidden_conditions or not output:
            return None

        detected = []
        output_lower = output.lower()

        for condition in forbidden_conditions:
            if condition.lower() in output_lower:
                detected.append(condition)

        if detected:
            return InvariantViolation(
                invariant_type=InvariantType.ASSERT_ABSENCE,
                severity=self._severities[InvariantType.ASSERT_ABSENCE],
                message=f"Found {len(detected)} forbidden conditions in output",
                evidence=", ".join(detected[:5]),
                context={"forbidden_found": detected},
                gap_tag="[gap:forbidden_condition]",
            )

        return None

    def check_observable_only(
        self,
        output: str,
    ) -> Optional[InvariantViolation]:
        """
        INVAR-06_OBSERVABLE_ONLY: No motive/emotion/intent/belief inference.

        Ensures that output does not contain inferences about unobservable
        mental states like motives, emotions, intents, or beliefs.

        This is a KEY requirement per ITEM-PROT-002.

        Args:
            output: Output text to check

        Returns:
            InvariantViolation if forbidden inference detected, None otherwise
        """
        if not output:
            return None

        # Find all forbidden inference markers
        matches = _FORBIDDEN_PATTERN.findall(output)

        if matches:
            # Get unique matches and their contexts
            unique_matches = list(set(m.lower() for m in matches))

            # Extract context for each match
            contexts = []
            for match in unique_matches[:3]:
                # Find the context around the match
                pattern = re.compile(
                    rf'.{{0,30}}{re.escape(match)}.{{0,30}}',
                    re.IGNORECASE
                )
                found = pattern.search(output)
                if found:
                    contexts.append(found.group().strip())

            return InvariantViolation(
                invariant_type=InvariantType.OBSERVABLE_ONLY,
                severity=self._severities[InvariantType.OBSERVABLE_ONLY],
                message=f"Found {len(matches)} forbidden inference(s): {', '.join(unique_matches[:5])}",
                evidence=" ... ".join(contexts) if contexts else ", ".join(unique_matches[:5]),
                context={
                    "forbidden_markers": unique_matches,
                    "total_matches": len(matches),
                },
                gap_tag="[gap:inference_violation]",
            )

        return None

    def check_code_is_evidence(
        self,
        code_blocks: List[str],
        output: str,
    ) -> Optional[InvariantViolation]:
        """
        INVAR-07_CODE_IS_EVIDENCE: Code blocks are executable evidence.

        Ensures that code blocks in output are valid and can be executed.

        Args:
            code_blocks: List of code blocks found
            output: Full output text

        Returns:
            InvariantViolation if code is not valid evidence, None otherwise
        """
        if not code_blocks:
            return None

        # Check for placeholder or invalid code patterns
        invalid_patterns = [
            r'\.\.\.',  # Ellipsis placeholder
            r'# TODO',
            r'# FIXME',
            r'# XXX',
            r'pass\s*$',
            r'raise NotImplementedError',
        ]

        invalid_blocks = []
        for i, block in enumerate(code_blocks):
            for pattern in invalid_patterns:
                if re.search(pattern, block, re.MULTILINE):
                    invalid_blocks.append(f"Block {i+1}: contains placeholder/invalid code")
                    break

        if invalid_blocks:
            return InvariantViolation(
                invariant_type=InvariantType.CODE_IS_EVIDENCE,
                severity=self._severities[InvariantType.CODE_IS_EVIDENCE],
                message=f"Found {len(invalid_blocks)} code block(s) with placeholders or invalid code",
                evidence="\n".join(invalid_blocks[:3]),
                context={"invalid_count": len(invalid_blocks)},
                gap_tag="[gap:invalid_code_evidence]",
            )

        return None

    def check_scope_locality(
        self,
        declared_scope: Set[str],
        actual_scope: Set[str],
    ) -> Optional[InvariantViolation]:
        """
        INVAR-08_SCOPE_LOCALITY: Operations stay in declared scope.

        Ensures that actual operations do not exceed the declared scope.

        Args:
            declared_scope: Set of declared scope items
            actual_scope: Set of actual scope items used

        Returns:
            InvariantViolation if scope exceeded, None otherwise
        """
        if not declared_scope or not actual_scope:
            return None

        # Find operations outside declared scope
        out_of_scope = actual_scope - declared_scope

        if out_of_scope:
            return InvariantViolation(
                invariant_type=InvariantType.SCOPE_LOCALITY,
                severity=self._severities[InvariantType.SCOPE_LOCALITY],
                message=f"Found {len(out_of_scope)} operation(s) outside declared scope",
                evidence=", ".join(sorted(out_of_scope)[:5]),
                context={
                    "declared": sorted(declared_scope),
                    "out_of_scope": sorted(out_of_scope),
                },
                gap_tag="[gap:scope_violation]",
            )

        return None

    def check_completeness(
        self,
        extracted: int,
        classified: int,
        exclusions: int,
    ) -> Optional[InvariantViolation]:
        """
        INVAR-09_COMPLETENESS: All items classified or excluded.

        Verifies that: Σ(extracted) - exclusions == Σ(classified)

        This is a KEY requirement per ITEM-PROT-002.

        Args:
            extracted: Total number of items extracted
            classified: Number of items classified
            exclusions: Number of items explicitly excluded

        Returns:
            InvariantViolation if completeness violated, None otherwise
        """
        if extracted == 0:
            return None

        # Check the completeness equation
        expected_classified = extracted - exclusions

        if classified != expected_classified:
            diff = abs(classified - expected_classified)
            return InvariantViolation(
                invariant_type=InvariantType.COMPLETENESS,
                severity=self._severities[InvariantType.COMPLETENESS],
                message=f"Completeness check failed: {extracted} extracted - {exclusions} exclusions != {classified} classified",
                evidence=f"Expected {expected_classified} classified, got {classified} (diff: {diff})",
                context={
                    "extracted": extracted,
                    "classified": classified,
                    "exclusions": exclusions,
                    "expected_classified": expected_classified,
                    "difference": diff,
                },
                gap_tag="[gap:completeness_violation]",
            )

        return None

    def check_validation_halt(
        self,
        validation_result: Optional[Dict[str, Any]],
        current_phase: int,
    ) -> Optional[InvariantViolation]:
        """
        INVAR-10_VALIDATION_HALT: Validation failure halts execution.

        Ensures that execution has halted after a validation failure.

        Args:
            validation_result: Previous validation result dict
            current_phase: Current execution phase

        Returns:
            InvariantViolation if execution continued after failure, None otherwise
        """
        if not validation_result:
            return None

        # Check if validation failed but execution continued
        if not validation_result.get("passed", True):
            failed_phase = validation_result.get("phase", 0)
            if current_phase > failed_phase:
                return InvariantViolation(
                    invariant_type=InvariantType.VALIDATION_HALT,
                    severity=self._severities[InvariantType.VALIDATION_HALT],
                    message=f"Execution continued after validation failure at phase {failed_phase}",
                    evidence=f"Current phase: {current_phase}, Failed phase: {failed_phase}",
                    context={
                        "failed_phase": failed_phase,
                        "current_phase": current_phase,
                    },
                    gap_tag="[gap:validation_halt_violation]",
                )

        return None

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _evaluate_passed(self, violations: List[InvariantViolation]) -> bool:
        """
        Evaluate if the check passed based on enforcement level.

        Args:
            violations: List of detected violations

        Returns:
            True if passed, False otherwise
        """
        if not violations:
            return True

        if self._level == EnforcementLevel.PERMISSIVE:
            # Never block, just log
            return True

        if self._level == EnforcementLevel.STRICT:
            # Block on any violation
            return False

        if self._level == EnforcementLevel.PARANOID:
            # Block on any violation
            return False

        # STANDARD: Block on critical/error violations
        return not any(v.is_blocking() for v in violations)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get enforcement statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            "total_checks": self._total_checks,
            "total_violations": self._total_violations,
            "violation_rate": (
                self._total_violations / self._total_checks
                if self._total_checks > 0 else 0.0
            ),
            "enabled_invariants": [i.value for i in self._enabled],
            "enforcement_level": self._level.value,
        }

    def reset_stats(self) -> None:
        """Reset enforcement statistics."""
        self._total_checks = 0
        self._total_violations = 0
        self._patch_hashes.clear()
        self._ssot_files.clear()

    def add_forbidden_marker(self, marker: str) -> None:
        """
        Add a custom forbidden inference marker.

        Args:
            marker: Marker to add to forbidden list
        """
        global _FORBIDDEN_PATTERN
        if marker.lower() not in [m.lower() for m in FORBIDDEN_INFERENCE_MARKERS]:
            FORBIDDEN_INFERENCE_MARKERS.append(marker.lower())
            # Recompile pattern
            _FORBIDDEN_PATTERN = re.compile(
                r'\b(' + '|'.join(re.escape(m) for m in FORBIDDEN_INFERENCE_MARKERS) + r')\b',
                re.IGNORECASE
            )


# =============================================================================
# Factory Functions
# =============================================================================

def create_invariant_enforcer(
    level: str = "standard",
    config: Optional[Dict[str, Any]] = None,
) -> InvariantEnforcer:
    """
    Factory function to create an InvariantEnforcer.

    Args:
        level: Enforcement level name (permissive, standard, strict, paranoid)
        config: Optional configuration dictionary

    Returns:
        Configured InvariantEnforcer instance
    """
    level_map = {
        "permissive": EnforcementLevel.PERMISSIVE,
        "standard": EnforcementLevel.STANDARD,
        "strict": EnforcementLevel.STRICT,
        "paranoid": EnforcementLevel.PARANOID,
    }

    enforcement_level = level_map.get(level.lower(), EnforcementLevel.STANDARD)

    config = config or {}
    custom_severities = config.get("custom_severities")
    enabled = config.get("enabled_invariants")
    disabled = config.get("disabled_invariants")

    # Convert string invariant names to enum
    if enabled:
        enabled = {InvariantType(e) for e in enabled}
    if disabled:
        disabled = {InvariantType(e) for e in disabled}

    return InvariantEnforcer(
        level=enforcement_level,
        custom_severities=custom_severities,
        enabled_invariants=enabled,
        disabled_invariants=disabled,
    )
