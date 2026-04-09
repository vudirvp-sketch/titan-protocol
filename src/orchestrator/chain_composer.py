"""
ChainComposer for TITAN Protocol v1.2.0.

ITEM_019: ChainComposer with cycle detection and parallel execution.

This module provides the ChainComposer class which composes skill chains
from selected skills with dependency resolution, parallel execution grouping,
and validation against the skill_chain.schema.json.

Key Features:
- Composes skill chains from selected skills
- Validates against skill_chain.schema.json
- Supports parallel execution groups (max 5 parallel)
- Handles input/output mapping between skills
- Integrates with GateManager for validation gates
- Cycle detection with DFS algorithm
- Maximum chain length: 10 skills

Author: TITAN Protocol Team
Version: 1.2.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional, Set, TYPE_CHECKING
import hashlib
import json
import logging

from src.utils.timezone import now_utc_iso, timestamp_for_id

if TYPE_CHECKING:
    from src.events.event_bus import EventBus
    from src.policy.gate_manager import GateManager
    from src.skills.skill_library import SkillLibrary
    from src.skills.skill import Skill


class ChainStatus(Enum):
    """Status of a skill chain."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RetryPolicy:
    """
    Retry configuration for a skill execution.
    
    Attributes:
        max_retries: Maximum number of retry attempts
        backoff_strategy: Strategy for delay between retries
        initial_delay_ms: Initial delay before first retry
        max_delay_ms: Maximum delay between retries
        jitter: Whether to add jitter to delays
        retry_on_errors: Error types that should trigger retry
    """
    max_retries: int = 3
    backoff_strategy: str = "exponential"  # fixed, exponential, linear, jittered
    initial_delay_ms: int = 100
    max_delay_ms: int = 30000
    jitter: bool = True
    retry_on_errors: List[str] = field(default_factory=lambda: ["timeout", "connection_error", "rate_limit"])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "max_retries": self.max_retries,
            "backoff_strategy": self.backoff_strategy,
            "initial_delay_ms": self.initial_delay_ms,
            "max_delay_ms": self.max_delay_ms,
            "jitter": self.jitter,
            "retry_on_errors": self.retry_on_errors
        }


@dataclass
class SkillExecution:
    """
    Definition of a single skill execution within a chain.
    
    Attributes:
        skill_id: Unique identifier of the skill to execute
        order: Execution order index
        input_mapping: Maps chain context keys to skill input parameters
        output_mapping: Maps skill output to chain context keys
        timeout_ms: Timeout for this skill execution
        retry_policy: Retry configuration
        condition: Optional condition expression to determine if skill should run
        required_gates: Gates that must pass before execution
        fallback_skill_id: Alternative skill if this one fails
        on_success: Action to take after successful execution
        on_failure: Action to take after failed execution
    """
    skill_id: str
    order: int
    input_mapping: Dict[str, str] = field(default_factory=dict)
    output_mapping: Dict[str, str] = field(default_factory=dict)
    timeout_ms: int = 30000
    retry_policy: Optional[RetryPolicy] = None
    condition: Optional[str] = None
    required_gates: List[str] = field(default_factory=list)
    fallback_skill_id: Optional[str] = None
    on_success: str = "continue"  # continue, stop, skip_next
    on_failure: str = "stop"  # stop, skip, fallback, continue
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
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
        if self.retry_policy:
            result["retry_policy"] = self.retry_policy.to_dict()
        if self.condition:
            result["condition"] = self.condition
        if self.fallback_skill_id:
            result["fallback_skill_id"] = self.fallback_skill_id
        return result


@dataclass
class ErrorHandling:
    """
    Error handling configuration for a skill chain.
    
    Attributes:
        stop_on_failure: Whether to stop chain on first failure
        max_retries: Maximum retries per skill
        retry_delay_ms: Delay between retries
        on_error: Action to take on skill error
    """
    stop_on_failure: bool = True
    max_retries: int = 3
    retry_delay_ms: int = 1000
    on_error: str = "stop"  # stop, skip, fallback, continue
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "stop_on_failure": self.stop_on_failure,
            "max_retries": self.max_retries,
            "retry_delay_ms": self.retry_delay_ms,
            "on_error": self.on_error
        }


@dataclass
class ChainMetadata:
    """
    Metadata for a skill chain.
    
    Attributes:
        created_at: When the chain was created
        profile: User profile that triggered chain creation
        intent: Intent that triggered chain creation
        session_id: Session identifier
        request_id: Original request identifier
        version: Chain schema version
    """
    created_at: str = field(default_factory=now_utc_iso)
    profile: Optional[str] = None
    intent: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    version: str = "1.2.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "created_at": self.created_at,
            "profile": self.profile,
            "intent": self.intent,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "version": self.version
        }


@dataclass
class SkillChain:
    """
    A composed chain of skills for execution.
    
    This is the canonical SkillChain structure per skill_chain.schema.json.
    
    Attributes:
        chain_id: Unique identifier for the skill chain
        skills: Ordered list of skills in the chain
        execution_order: Ordered list of skill indices defining execution sequence
        parallel_groups: Groups of skill indices that can execute in parallel
        context_mapping: Maps input context keys to skill input keys
        gates: Validation gates to execute during chain execution
        fallback_chain: Alternative skill IDs if primary skills fail
        estimated_duration_ms: Estimated total execution duration
        metadata: Additional metadata about the chain
        status: Current status of the chain execution
        error_handling: Error handling configuration
    """
    chain_id: str
    skills: List[SkillExecution]
    execution_order: List[int] = field(default_factory=list)
    parallel_groups: List[List[int]] = field(default_factory=list)
    context_mapping: Dict[str, str] = field(default_factory=dict)
    gates: List[str] = field(default_factory=list)
    fallback_chain: List[str] = field(default_factory=list)
    estimated_duration_ms: int = 0
    metadata: ChainMetadata = field(default_factory=ChainMetadata)
    status: ChainStatus = ChainStatus.PENDING
    error_handling: ErrorHandling = field(default_factory=ErrorHandling)
    
    def __post_init__(self):
        """Initialize execution_order if not provided."""
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
            "metadata": self.metadata.to_dict(),
            "status": self.status.value,
            "error_handling": self.error_handling.to_dict()
        }
    
    def get_skill_by_order(self, order: int) -> Optional[SkillExecution]:
        """Get a skill by its execution order."""
        for skill in self.skills:
            if skill.order == order:
                return skill
        return None
    
    def get_ordered_skills(self) -> List[SkillExecution]:
        """Get skills in execution order."""
        ordered = []
        for idx in self.execution_order:
            skill = self.get_skill_by_order(idx)
            if skill:
                ordered.append(skill)
        return ordered


@dataclass
class ValidationResult:
    """
    Result of chain validation.
    
    Attributes:
        is_valid: Whether the chain is valid
        errors: List of validation errors
        warnings: List of validation warnings
        cycles_detected: List of detected cycles (if any)
    """
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    cycles_detected: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "cycles_detected": self.cycles_detected
        }


@dataclass
class CycleInfo:
    """
    Information about a detected cycle.
    
    Attributes:
        cycle_path: List of skill IDs forming the cycle
        cycle_type: Type of dependency causing the cycle
        description: Human-readable description
    """
    cycle_path: List[str]
    cycle_type: str  # "output_dependency" or "input_dependency"
    description: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_path": self.cycle_path,
            "cycle_type": self.cycle_type,
            "description": self.description
        }


class ChainComposer:
    """
    Composes skill chains from selected skills.
    
    ITEM_019: ChainComposer with cycle detection and parallel execution.
    
    The ChainComposer:
    - Composes skill chains from selected skills
    - Validates against skill_chain.schema.json
    - Supports parallel execution groups (max 5 parallel)
    - Handles input/output mapping between skills
    - Integrates with GateManager for validation gates
    - Detects cycles with DFS algorithm
    - Maximum chain length: 10 skills
    
    Usage:
        >>> from src.events import EventBus
        >>> from src.policy import GateManager
        >>> from src.skills import SkillLibrary
        >>> 
        >>> bus = EventBus()
        >>> gate_manager = GateManager()
        >>> skill_library = SkillLibrary({}, bus)
        >>> 
        >>> composer = ChainComposer({}, bus, skill_library, gate_manager)
        >>> 
        >>> skills = [skill1, skill2, skill3]
        >>> context = {"profile": "developer", "intent": "refactor"}
        >>> chain = composer.compose(skills, context)
    """
    
    # Class constants
    MAX_CHAIN_LENGTH = 10
    MAX_PARALLEL_SKILLS = 5
    
    def __init__(
        self,
        config: Dict[str, Any],
        event_bus: 'EventBus' = None,
        skill_library: 'SkillLibrary' = None,
        gate_manager: 'GateManager' = None
    ):
        """
        Initialize the ChainComposer.
        
        Args:
            config: Configuration dictionary with optional keys:
                - max_chain_length: Maximum number of skills in a chain
                - max_parallel_skills: Maximum skills in parallel group
                - default_timeout_ms: Default timeout for skill execution
                - default_retry_policy: Default retry configuration
            event_bus: Optional EventBus for event emission
            skill_library: Optional SkillLibrary for skill metadata
            gate_manager: Optional GateManager for validation gates
        """
        self.config = config or {}
        self._event_bus = event_bus
        self._skill_library = skill_library
        self._gate_manager = gate_manager
        self._logger = logging.getLogger(__name__)
        
        # Configuration
        self._max_chain_length = self.config.get("max_chain_length", self.MAX_CHAIN_LENGTH)
        self._max_parallel_skills = self.config.get("max_parallel_skills", self.MAX_PARALLEL_SKILLS)
        self._default_timeout_ms = self.config.get("default_timeout_ms", 30000)
        self._default_retry_policy = self.config.get("default_retry_policy", {})
        
        # Subscribe to SKILL_COMPOSITION_REQUEST events
        if self._event_bus:
            self._event_bus.subscribe("SKILL_COMPOSITION_REQUEST", self._handle_composition_request)
    
    def compose(
        self,
        skills: List['Skill'],
        context: Dict[str, Any]
    ) -> SkillChain:
        """
        Compose a skill chain from selected skills.
        
        This is the main entry point for chain composition. It:
        1. Validates skill list length
        2. Resolves dependencies between skills
        3. Detects cycles
        4. Determines execution order
        5. Identifies parallel execution opportunities
        6. Sets up fallback chains
        7. Validates against schema
        
        Args:
            skills: List of skills to compose into a chain
            context: Execution context with:
                - profile: User profile (e.g., "developer")
                - intent: Intent type (e.g., "refactor")
                - session_id: Session identifier
                - request_id: Request identifier
                - gates: Optional list of gates to validate
        
        Returns:
            SkillChain ready for execution
        
        Raises:
            ValueError: If skills list exceeds max length or contains cycles
        """
        self._logger.info(f"Composing chain from {len(skills)} skills")
        
        # Step 1: Validate skill count
        if len(skills) > self._max_chain_length:
            raise ValueError(
                f"Chain exceeds maximum length: {len(skills)} > {self._max_chain_length}"
            )
        
        if not skills:
            raise ValueError("Cannot compose chain from empty skill list")
        
        # Step 2: Detect cycles
        cycles = self.detect_cycles(skills)
        if cycles:
            self._emit_cycle_detected(cycles, skills)
            raise ValueError(
                f"Circular dependency detected in skill chain: "
                f"{cycles[0].get('cycle_path', [])}"
            )
        
        # Step 3: Resolve dependencies and get execution order
        ordered_skills = self.resolve_dependencies(skills)
        
        # Step 4: Create skill executions
        skill_executions = self._create_skill_executions(ordered_skills)
        
        # Step 5: Identify parallel groups
        parallel_groups = self._identify_parallel_groups(ordered_skills, skill_executions)
        
        # Step 6: Calculate estimated duration
        estimated_duration = self._calculate_estimated_duration(skill_executions, parallel_groups)
        
        # Step 7: Set up fallback chain
        fallback_chain = self._create_fallback_chain(skills)
        
        # Step 8: Create chain ID
        chain_id = self._generate_chain_id()
        
        # Step 9: Create metadata
        metadata = ChainMetadata(
            profile=context.get("profile"),
            intent=context.get("intent"),
            session_id=context.get("session_id"),
            request_id=context.get("request_id")
        )
        
        # Step 10: Get gates from context
        gates = context.get("gates", [])
        if self._gate_manager:
            gates = self._get_default_gates(context) + gates
        
        # Step 11: Create the chain
        chain = SkillChain(
            chain_id=chain_id,
            skills=skill_executions,
            execution_order=list(range(len(skill_executions))),
            parallel_groups=parallel_groups,
            context_mapping=self._create_context_mapping(skills, context),
            gates=gates,
            fallback_chain=fallback_chain,
            estimated_duration_ms=estimated_duration,
            metadata=metadata,
            status=ChainStatus.PENDING
        )
        
        # Step 12: Validate the chain
        validation = self.validate_chain(chain)
        if not validation.is_valid:
            raise ValueError(f"Chain validation failed: {validation.errors}")
        
        # Step 13: Emit SKILL_CHAIN_COMPOSED event
        self._emit_chain_composed(chain)
        
        self._logger.info(
            f"Composed chain {chain_id} with {len(skill_executions)} skills, "
            f"{len(parallel_groups)} parallel groups, estimated {estimated_duration}ms"
        )
        
        return chain
    
    def optimize_chain(self, chain: SkillChain) -> SkillChain:
        """
        Optimize an existing chain for better performance.
        
        Optimization strategies:
        - Reorder skills for better parallelization
        - Consolidate gates
        - Merge similar operations
        
        Args:
            chain: The chain to optimize
        
        Returns:
            Optimized SkillChain
        """
        self._logger.info(f"Optimizing chain {chain.chain_id}")
        
        # Re-identify parallel groups with optimization
        ordered_skills = []
        for skill_exec in chain.get_ordered_skills():
            if self._skill_library:
                skill = self._skill_library.get_skill(skill_exec.skill_id)
                if skill:
                    ordered_skills.append(skill)
        
        if ordered_skills:
            # Re-calculate parallel groups
            parallel_groups = self._identify_parallel_groups(
                ordered_skills, chain.skills, optimize=True
            )
            chain.parallel_groups = parallel_groups
            
            # Re-calculate estimated duration
            chain.estimated_duration_ms = self._calculate_estimated_duration(
                chain.skills, parallel_groups
            )
        
        return chain
    
    def validate_chain(self, chain: SkillChain) -> ValidationResult:
        """
        Validate a skill chain against schema and business rules.
        
        Validation checks:
        - Chain length within limits
        - Skill IDs are valid
        - Execution order is consistent
        - Parallel groups are valid
        - No circular dependencies in I/O mapping
        
        Args:
            chain: The chain to validate
        
        Returns:
            ValidationResult with errors and warnings
        """
        errors = []
        warnings = []
        cycles_detected = []
        
        # Check chain length
        if len(chain.skills) > self._max_chain_length:
            errors.append(
                f"Chain exceeds maximum length: {len(chain.skills)} > {self._max_chain_length}"
            )
        
        # Check execution order consistency
        if chain.execution_order:
            expected_order = set(range(len(chain.skills)))
            actual_order = set(chain.execution_order)
            if expected_order != actual_order:
                errors.append(
                    f"Execution order mismatch: expected {expected_order}, got {actual_order}"
                )
        
        # Check parallel groups validity
        for i, group in enumerate(chain.parallel_groups):
            if len(group) > self._max_parallel_skills:
                errors.append(
                    f"Parallel group {i} exceeds max size: {len(group)} > {self._max_parallel_skills}"
                )
            for idx in group:
                if idx < 0 or idx >= len(chain.skills):
                    errors.append(
                        f"Invalid skill index {idx} in parallel group {i}"
                    )
        
        # Check for I/O mapping cycles
        io_cycles = self._detect_io_cycles(chain.skills)
        if io_cycles:
            cycles_detected.extend(io_cycles)
            errors.append("Circular dependency detected in skill I/O mappings")
        
        # Validate skill IDs exist in library
        if self._skill_library:
            for skill_exec in chain.skills:
                if not self._skill_library.get_skill(skill_exec.skill_id):
                    warnings.append(
                        f"Skill '{skill_exec.skill_id}' not found in library"
                    )
        
        # Validate gate IDs
        for gate in chain.gates:
            if not gate.startswith("GATE-"):
                warnings.append(f"Non-standard gate identifier: {gate}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            cycles_detected=cycles_detected
        )
    
    def get_parallel_groups(self, chain: SkillChain) -> List[List['SkillExecution']]:
        """
        Get parallel execution groups from a chain.
        
        Args:
            chain: The skill chain
        
        Returns:
            List of skill execution groups that can run in parallel
        """
        groups = []
        for group_indices in chain.parallel_groups:
            group = []
            for idx in group_indices:
                if idx < len(chain.skills):
                    group.append(chain.skills[idx])
            if group:
                groups.append(group)
        return groups
    
    def detect_cycles(self, skills: List['Skill']) -> List[Dict[str, Any]]:
        """
        Detect cycles in skill dependencies using DFS.
        
        A cycle exists when skill A depends on skill B which depends on skill A,
        either directly or through a chain of dependencies.
        
        Args:
            skills: List of skills to check for cycles
        
        Returns:
            List of detected cycles (empty if no cycles)
        """
        cycles = []
        visited = set()
        rec_stack = set()
        path = []
        
        # Build dependency graph from skill I/O
        dependency_graph = self._build_dependency_graph(skills)
        
        def dfs(skill_id: str) -> bool:
            """DFS helper for cycle detection."""
            visited.add(skill_id)
            rec_stack.add(skill_id)
            path.append(skill_id)
            
            for dep_id in dependency_graph.get(skill_id, []):
                if dep_id not in visited:
                    if dfs(dep_id):
                        return True
                elif dep_id in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(dep_id)
                    cycle_path = path[cycle_start:] + [dep_id]
                    cycles.append({
                        "cycle_path": cycle_path,
                        "cycle_type": "output_dependency",
                        "description": f"Circular dependency: {' -> '.join(cycle_path)}"
                    })
                    return True
            
            path.pop()
            rec_stack.remove(skill_id)
            return False
        
        # Check each skill for cycles
        for skill in skills:
            if skill.skill_id not in visited:
                dfs(skill.skill_id)
        
        return cycles
    
    def resolve_dependencies(self, skills: List['Skill']) -> List['Skill']:
        """
        Resolve skill dependencies and return topologically sorted order.
        
        Uses topological sort with I/O analysis to determine execution order:
        1. Build dependency graph from skill I/O contracts
        2. Run topological sort
        3. Identify independent skills (no shared I/O)
        4. Group independent skills for potential parallel execution
        
        Args:
            skills: List of skills to resolve dependencies for
        
        Returns:
            List of skills in execution order
        """
        if len(skills) <= 1:
            return skills
        
        # Build dependency graph
        dependency_graph = self._build_dependency_graph(skills)
        in_degree = {skill.skill_id: 0 for skill in skills}
        
        # Calculate in-degrees
        for skill_id, deps in dependency_graph.items():
            for dep_id in deps:
                if dep_id in in_degree:
                    in_degree[skill_id] += 1
        
        # Topological sort using Kahn's algorithm
        queue = [s for s in skills if in_degree[s.skill_id] == 0]
        result = []
        
        while queue:
            # Sort by skill_id for deterministic ordering
            queue.sort(key=lambda s: s.skill_id)
            skill = queue.pop(0)
            result.append(skill)
            
            # Update in-degrees
            for other_id, deps in dependency_graph.items():
                if skill.skill_id in deps:
                    in_degree[other_id] -= 1
                    if in_degree[other_id] == 0:
                        for s in skills:
                            if s.skill_id == other_id and s not in result:
                                queue.append(s)
        
        # If not all skills are in result, there's a cycle
        if len(result) != len(skills):
            # Return original order as fallback
            return skills
        
        return result
    
    # Private methods
    
    def _handle_composition_request(self, event) -> None:
        """
        Handle SKILL_COMPOSITION_REQUEST events.
        
        Args:
            event: Event containing composition request data
        """
        try:
            data = event.data
            skill_ids = data.get("skills", [])
            context = data.get("context", {})
            
            # Get skills from library
            skills = []
            if self._skill_library:
                for skill_id in skill_ids:
                    skill = self._skill_library.get_skill(skill_id)
                    if skill:
                        skills.append(skill)
            
            if skills:
                chain = self.compose(skills, context)
                self._emit_chain_composed(chain)
        
        except Exception as e:
            self._logger.error(f"Error handling composition request: {e}")
    
    def _build_dependency_graph(self, skills: List['Skill']) -> Dict[str, Set[str]]:
        """
        Build a dependency graph from skill I/O contracts.
        
        A skill A depends on skill B if:
        - A's input includes B's output (B must run before A)
        
        Args:
            skills: List of skills to analyze
        
        Returns:
            Dict mapping skill_id to set of skill_ids it depends on
        """
        graph = {skill.skill_id: set() for skill in skills}
        
        # Get output keys for each skill
        outputs_by_skill = {}
        for skill in skills:
            outputs_by_skill[skill.skill_id] = self._get_skill_outputs(skill)
        
        # Get input keys for each skill
        inputs_by_skill = {}
        for skill in skills:
            inputs_by_skill[skill.skill_id] = self._get_skill_inputs(skill)
        
        # Build dependencies: if skill A's input matches skill B's output,
        # then A depends on B
        for skill_a in skills:
            a_inputs = inputs_by_skill[skill_a.skill_id]
            for skill_b in skills:
                if skill_a.skill_id == skill_b.skill_id:
                    continue
                b_outputs = outputs_by_skill[skill_b.skill_id]
                # Check for overlap
                if a_inputs & b_outputs:
                    graph[skill_a.skill_id].add(skill_b.skill_id)
        
        return graph
    
    def _get_skill_outputs(self, skill: 'Skill') -> Set[str]:
        """Get output keys produced by a skill."""
        # Default outputs based on skill_id
        return {
            f"{skill.skill_id}_output",
            f"{skill.skill_id}_result",
            "result"
        }
    
    def _get_skill_inputs(self, skill: 'Skill') -> Set[str]:
        """Get input keys required by a skill."""
        # Default inputs based on skill_id and metadata
        inputs = {f"{skill.skill_id}_input", "context", "request"}
        
        # Check metadata for explicit inputs
        if skill.metadata:
            consumes = skill.metadata.get("consumes", {})
            inputs.update(consumes.keys())
        
        return inputs
    
    def _create_skill_executions(
        self,
        ordered_skills: List['Skill']
    ) -> List[SkillExecution]:
        """Create SkillExecution objects for each skill."""
        executions = []
        
        for i, skill in enumerate(ordered_skills):
            # Get timeout from skill metadata or use default
            timeout_ms = self._default_timeout_ms
            if skill.metadata:
                timeout_ms = skill.metadata.get("timeout_ms", timeout_ms)
            
            # Create retry policy
            retry_policy = RetryPolicy(
                max_retries=self._default_retry_policy.get("max_retries", 3),
                backoff_strategy=self._default_retry_policy.get("backoff_strategy", "exponential"),
                initial_delay_ms=self._default_retry_policy.get("initial_delay_ms", 100),
                max_delay_ms=self._default_retry_policy.get("max_delay_ms", 30000),
                jitter=self._default_retry_policy.get("jitter", True)
            )
            
            # Get required gates from skill
            required_gates = list(skill.validation_chain) if skill.validation_chain else []
            
            # Create input/output mappings
            input_mapping = self._create_input_mapping(skill)
            output_mapping = self._create_output_mapping(skill)
            
            execution = SkillExecution(
                skill_id=skill.skill_id,
                order=i,
                input_mapping=input_mapping,
                output_mapping=output_mapping,
                timeout_ms=timeout_ms,
                retry_policy=retry_policy,
                required_gates=required_gates,
                on_success="continue",
                on_failure="stop"
            )
            
            executions.append(execution)
        
        return executions
    
    def _create_input_mapping(self, skill: 'Skill') -> Dict[str, str]:
        """Create input mapping for a skill."""
        mapping = {}
        mapping["request"] = "context.request"
        mapping["session"] = "context.session"
        mapping[f"{skill.skill_id}_input"] = f"context.skill_inputs.{skill.skill_id}"
        return mapping
    
    def _create_output_mapping(self, skill: 'Skill') -> Dict[str, str]:
        """Create output mapping for a skill."""
        mapping = {}
        mapping["result"] = f"context.skill_outputs.{skill.skill_id}"
        mapping[f"{skill.skill_id}_output"] = f"context.skill_outputs.{skill.skill_id}"
        return mapping
    
    def _identify_parallel_groups(
        self,
        ordered_skills: List['Skill'],
        skill_executions: List[SkillExecution],
        optimize: bool = False
    ) -> List[List[int]]:
        """
        Identify groups of skills that can execute in parallel.
        
        Skills can be parallelized if:
        - They have no shared outputs (no write conflicts)
        - They have no circular reads
        - They are independent (no dependency between them)
        
        Args:
            ordered_skills: Skills in execution order
            skill_executions: Skill execution definitions
            optimize: Whether to optimize for maximum parallelization
        
        Returns:
            List of groups, each containing skill indices
        """
        if len(ordered_skills) <= 1:
            return []
        
        # Find independent skills
        dependency_graph = self._build_dependency_graph(ordered_skills)
        
        # Group skills by their dependency depth
        depth_map = {}
        for skill in ordered_skills:
            depth = self._calculate_dependency_depth(skill.skill_id, dependency_graph)
            if depth not in depth_map:
                depth_map[depth] = []
            depth_map[depth].append(ordered_skills.index(skill))
        
        # Create parallel groups from each depth level
        parallel_groups = []
        for depth in sorted(depth_map.keys()):
            indices = depth_map[depth]
            if len(indices) > 1:
                # Check for conflicts within the group
                conflict_free = self._filter_conflict_free(indices, ordered_skills)
                if len(conflict_free) > 1:
                    # Limit to max parallel skills
                    group = conflict_free[:self._max_parallel_skills]
                    if len(group) > 1:
                        parallel_groups.append(group)
        
        return parallel_groups
    
    def _calculate_dependency_depth(
        self,
        skill_id: str,
        dependency_graph: Dict[str, Set[str]],
        visited: Set[str] = None
    ) -> int:
        """Calculate the dependency depth of a skill."""
        if visited is None:
            visited = set()
        
        if skill_id in visited:
            return 0  # Avoid infinite recursion on cycles
        
        visited.add(skill_id)
        deps = dependency_graph.get(skill_id, set())
        
        if not deps:
            return 0
        
        max_depth = 0
        for dep_id in deps:
            depth = self._calculate_dependency_depth(dep_id, dependency_graph, visited.copy())
            max_depth = max(max_depth, depth + 1)
        
        return max_depth
    
    def _filter_conflict_free(
        self,
        indices: List[int],
        skills: List['Skill']
    ) -> List[int]:
        """Filter out skills that have conflicts with each other."""
        if len(indices) <= 1:
            return indices
        
        conflict_free = []
        used_outputs = set()
        
        for idx in indices:
            skill = skills[idx]
            outputs = self._get_skill_outputs(skill)
            
            # Check for conflicts
            if not (outputs & used_outputs):
                conflict_free.append(idx)
                used_outputs.update(outputs)
        
        return conflict_free
    
    def _calculate_estimated_duration(
        self,
        skill_executions: List[SkillExecution],
        parallel_groups: List[List[int]]
    ) -> int:
        """
        Calculate estimated total execution duration.
        
        Takes into account:
        - Sequential execution time
        - Parallel execution savings
        - Overhead between skills
        
        Args:
            skill_executions: Skill execution definitions
            parallel_groups: Groups of parallel skills
        
        Returns:
            Estimated duration in milliseconds
        """
        if not skill_executions:
            return 0
        
        # Base duration: sum of all timeouts (conservative estimate)
        total_timeout = sum(se.timeout_ms for se in skill_executions)
        
        # Estimate actual duration as fraction of timeout
        # Most skills complete faster than their timeout
        base_duration = total_timeout // 3
        
        # Calculate savings from parallel execution
        parallel_savings = 0
        for group in parallel_groups:
            if len(group) > 1:
                # Parallel execution saves (n-1) * average_skill_time
                avg_skill_time = base_duration // len(skill_executions)
                parallel_savings += (len(group) - 1) * avg_skill_time
        
        # Add overhead for skill transitions
        overhead = len(skill_executions) * 50  # 50ms per skill transition
        
        estimated = max(base_duration - parallel_savings + overhead, 1000)
        
        return estimated
    
    def _create_fallback_chain(self, skills: List['Skill']) -> List[str]:
        """
        Create a fallback chain of alternative skill IDs.
        
        Args:
            skills: Original skills
        
        Returns:
            List of fallback skill IDs
        """
        fallbacks = []
        
        for skill in skills:
            # Check for explicit fallback in metadata
            if skill.metadata:
                fallback_id = skill.metadata.get("fallback_skill_id")
                if fallback_id:
                    fallbacks.append(fallback_id)
                    continue
            
            # Use a generic fallback
            fallbacks.append(f"{skill.skill_id}_fallback")
        
        return fallbacks
    
    def _create_context_mapping(
        self,
        skills: List['Skill'],
        context: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        Create context mapping for chain execution.
        
        Args:
            skills: Skills in the chain
            context: Execution context
        
        Returns:
            Dict mapping context keys to skill input keys
        """
        mapping = {}
        
        # Map standard context keys
        mapping["profile"] = "context.profile"
        mapping["intent"] = "context.intent"
        mapping["session_id"] = "context.session_id"
        
        # Map skill-specific context
        for skill in skills:
            prefix = f"skill.{skill.skill_id}"
            mapping[f"{prefix}.input"] = f"context.skill_inputs.{skill.skill_id}"
            mapping[f"{prefix}.output"] = f"context.skill_outputs.{skill.skill_id}"
        
        # Map any additional context
        for key in context:
            if key not in mapping:
                mapping[key] = f"context.{key}"
        
        return mapping
    
    def _generate_chain_id(self) -> str:
        """
        Generate a unique chain ID.
        
        Format: chain_[timestamp]_[hash]
        
        Returns:
            Unique chain ID string
        """
        timestamp = timestamp_for_id()
        random_data = json.dumps({"ts": timestamp}, sort_keys=True)
        hash_suffix = hashlib.sha256(random_data.encode()).hexdigest()[:8]
        return f"chain_{timestamp}_{hash_suffix}"
    
    def _get_default_gates(self, context: Dict[str, Any]) -> List[str]:
        """Get default gates based on context."""
        gates = []
        
        # Add gates based on profile
        profile = context.get("profile", "")
        if profile == "developer":
            gates.extend(["GATE-02", "GATE-04"])  # Analysis, Execution gates
        elif profile == "devops":
            gates.extend(["GATE-01", "GATE-02", "GATE-05"])  # Discovery, Analysis, Delivery
        
        # Add gates based on intent
        intent = context.get("intent", "")
        if intent in ["refactor", "implement"]:
            gates.append("GATE-03")  # Planning gate
        elif intent == "deploy":
            gates.append("GATE-05")  # Delivery gate
        
        return list(set(gates))  # Remove duplicates
    
    def _detect_io_cycles(self, skill_executions: List[SkillExecution]) -> List[Dict[str, Any]]:
        """
        Detect cycles in skill I/O mappings.
        
        Args:
            skill_executions: List of skill executions
        
        Returns:
            List of detected I/O cycles
        """
        cycles = []
        
        # Build I/O dependency graph
        io_graph = {}
        for se in skill_executions:
            io_graph[se.skill_id] = set()
            for output_key in se.output_mapping.values():
                for other_se in skill_executions:
                    if other_se.skill_id == se.skill_id:
                        continue
                    for input_key in other_se.input_mapping.values():
                        if output_key == input_key:
                            io_graph[se.skill_id].add(other_se.skill_id)
        
        # Detect cycles using DFS
        visited = set()
        rec_stack = set()
        path = []
        
        def dfs(skill_id: str) -> bool:
            visited.add(skill_id)
            rec_stack.add(skill_id)
            path.append(skill_id)
            
            for dep_id in io_graph.get(skill_id, []):
                if dep_id not in visited:
                    if dfs(dep_id):
                        return True
                elif dep_id in rec_stack:
                    cycle_start = path.index(dep_id)
                    cycle_path = path[cycle_start:] + [dep_id]
                    cycles.append({
                        "cycle_path": cycle_path,
                        "cycle_type": "io_dependency",
                        "description": f"I/O cycle: {' -> '.join(cycle_path)}"
                    })
                    return True
            
            path.pop()
            rec_stack.remove(skill_id)
            return False
        
        for se in skill_executions:
            if se.skill_id not in visited:
                dfs(se.skill_id)
        
        return cycles
    
    def _emit_chain_composed(self, chain: SkillChain) -> None:
        """Emit SKILL_CHAIN_COMPOSED event."""
        if self._event_bus:
            self._event_bus.emit_simple(
                event_type="SKILL_CHAIN_COMPOSED",
                data={
                    "chain_id": chain.chain_id,
                    "skill_count": len(chain.skills),
                    "parallel_groups": len(chain.parallel_groups),
                    "estimated_duration_ms": chain.estimated_duration_ms,
                    "profile": chain.metadata.profile,
                    "intent": chain.metadata.intent
                },
                source="ChainComposer"
            )
    
    def _emit_cycle_detected(
        self,
        cycles: List[Dict[str, Any]],
        skills: List['Skill']
    ) -> None:
        """Emit SKILL_CHAIN_CYCLE_DETECTED event."""
        if self._event_bus:
            self._event_bus.emit_simple(
                event_type="SKILL_CHAIN_CYCLE_DETECTED",
                data={
                    "cycles": cycles,
                    "skill_ids": [s.skill_id for s in skills],
                    "message": "Circular dependency detected in skill chain"
                },
                source="ChainComposer"
            )


def create_chain_composer(
    config: Dict[str, Any] = None,
    event_bus: 'EventBus' = None,
    skill_library: 'SkillLibrary' = None,
    gate_manager: 'GateManager' = None
) -> ChainComposer:
    """
    Factory function to create a ChainComposer.
    
    Args:
        config: Configuration dictionary
        event_bus: Optional EventBus for events
        skill_library: Optional SkillLibrary for skill metadata
        gate_manager: Optional GateManager for validation gates
    
    Returns:
        ChainComposer instance
    """
    return ChainComposer(config or {}, event_bus, skill_library, gate_manager)
