"""
ITEM_010: SkillGraphAdapter for TITAN Protocol v1.2.0.

This module implements the SkillGraphAdapter which builds and manages
a skill dependency graph from the SkillLibrary, tracks synergies,
and provides skill selection based on graph traversal.

Features:
- Build skill dependency graph from SkillLibrary
- Track skill synergies (co-occurrence, success rate)
- Skill selection based on graph traversal
- Cycle detection in skill dependencies

Integration Points:
- SkillLibrary: Source of skill definitions
- EventBus: Event emission for graph changes
- PluginInterface: Standard plugin lifecycle

Author: TITAN Protocol Team
Version: 1.2.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Set, Tuple, TYPE_CHECKING
import logging
import threading
from collections import defaultdict

from ..interfaces.plugin_interface import (
    PluginInterface,
    PluginState,
    RoutingDecision,
    RoutingAction,
    ExecutionResult,
    ErrorResult,
    PluginInfo
)

if TYPE_CHECKING:
    from ..events.event_bus import EventBus
    from .skill_library import SkillLibrary


class EdgeType(Enum):
    """Types of edges in the skill graph."""
    DEPENDS_ON = "depends_on"      # Direct dependency
    SYNERGY = "synergy"            # Co-occurrence synergy
    FALLBACK = "fallback"          # Fallback relationship
    SEQUENCE = "sequence"          # Sequential execution


@dataclass
class SkillNode:
    """
    A node in the skill graph representing a single skill.
    
    Attributes:
        skill_id: Unique identifier for the skill
        dependencies: Set of skill IDs this skill depends on
        dependents: Set of skill IDs that depend on this skill
        synergies: Map of skill_id -> synergy score
        success_rate: Historical success rate (0.0 to 1.0)
        use_count: Total times this skill has been selected
        last_used: Timestamp of last use
    """
    skill_id: str
    dependencies: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)
    synergies: Dict[str, float] = field(default_factory=dict)
    success_rate: float = 1.0
    use_count: int = 0
    last_used: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "skill_id": self.skill_id,
            "dependencies": list(self.dependencies),
            "dependents": list(self.dependents),
            "synergies": self.synergies,
            "success_rate": self.success_rate,
            "use_count": self.use_count,
            "last_used": self.last_used
        }


@dataclass
class SkillEdge:
    """
    An edge in the skill graph representing a relationship.
    
    Attributes:
        source_id: Source skill ID
        target_id: Target skill ID
        edge_type: Type of relationship
        weight: Weight/strength of the relationship
        metadata: Additional metadata
    """
    source_id: str
    target_id: str
    edge_type: EdgeType
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value,
            "weight": self.weight,
            "metadata": self.metadata
        }


@dataclass
class GraphTraversalResult:
    """
    Result of a graph traversal for skill selection.
    
    Attributes:
        selected_skills: Ordered list of selected skill IDs
        path_score: Score of the selected path
        alternatives: Alternative paths considered
        cycles_detected: List of cycles found during traversal
        fallback_used: Whether fallback skills were used
    """
    selected_skills: List[str] = field(default_factory=list)
    path_score: float = 0.0
    alternatives: List[List[str]] = field(default_factory=list)
    cycles_detected: List[List[str]] = field(default_factory=list)
    fallback_used: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "selected_skills": self.selected_skills,
            "path_score": self.path_score,
            "alternatives": self.alternatives,
            "cycles_detected": self.cycles_detected,
            "fallback_used": self.fallback_used
        }


@dataclass
class CoOccurrenceRecord:
    """
    Records co-occurrence statistics for skill pairs.
    
    Attributes:
        skill_a: First skill ID
        skill_b: Second skill ID
        co_occurrence_count: Number of times used together
        success_count: Number of successful joint executions
        last_co_occurrence: Timestamp of last co-occurrence
    """
    skill_a: str
    skill_b: str
    co_occurrence_count: int = 0
    success_count: int = 0
    last_co_occurrence: Optional[str] = None
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate for this pair."""
        if self.co_occurrence_count == 0:
            return 0.0
        return self.success_count / self.co_occurrence_count
    
    def record_use(self, success: bool) -> None:
        """Record a co-occurrence use."""
        self.co_occurrence_count += 1
        if success:
            self.success_count += 1
        self.last_co_occurrence = datetime.utcnow().isoformat() + "Z"


class SkillGraphAdapter(PluginInterface):
    """
    Adapter for skill dependency graph management.
    
    This adapter builds and maintains a graph of skill relationships,
    including dependencies, synergies, and fallback relationships.
    It provides skill selection through graph traversal algorithms.
    
    Features:
    - Build dependency graph from SkillLibrary
    - Track skill synergies based on co-occurrence
    - Graph-based skill selection with scoring
    - Cycle detection using DFS
    
    Integration Points:
    - SkillLibrary: Source of skill definitions
    - EventBus: Emits SKILL_GRAPH_UPDATED events
    - PluginInterface: Standard plugin lifecycle
    
    Example:
        >>> adapter = SkillGraphAdapter(config, event_bus)
        >>> adapter.on_init()
        >>> adapter.build_graph(skill_library)
        >>> result = adapter.select_skills_by_graph("refactor", context)
        >>> print(result.selected_skills)
    """
    
    def __init__(self, config: Dict[str, Any], event_bus: 'EventBus' = None):
        """
        Initialize the SkillGraphAdapter.
        
        Args:
            config: Configuration dictionary with optional keys:
                - max_skills_per_selection: Max skills to select (default: 5)
                - min_synergy_threshold: Min synergy score to consider (default: 0.3)
                - cycle_detection_enabled: Enable cycle detection (default: True)
                - synergy_decay_factor: Decay factor for old synergies (default: 0.95)
            event_bus: Optional EventBus for event emission
        """
        self._config = config
        self._event_bus = event_bus
        self._state = PluginState.UNINITIALIZED
        self._logger = logging.getLogger(__name__)
        
        # Graph storage
        self._nodes: Dict[str, SkillNode] = {}
        self._edges: Dict[Tuple[str, str], SkillEdge] = {}
        
        # Co-occurrence tracking
        self._co_occurrences: Dict[Tuple[str, str], CoOccurrenceRecord] = {}
        
        # Configuration
        self._max_skills_per_selection = config.get("max_skills_per_selection", 5)
        self._min_synergy_threshold = config.get("min_synergy_threshold", 0.3)
        self._cycle_detection_enabled = config.get("cycle_detection_enabled", True)
        self._synergy_decay_factor = config.get("synergy_decay_factor", 0.95)
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Metrics
        self._selection_count = 0
        self._cycle_detection_count = 0
        self._fallback_count = 0
        
        # SkillLibrary reference
        self._skill_library: Optional['SkillLibrary'] = None
    
    def on_init(self) -> None:
        """
        Initialize the adapter.
        
        Sets up graph storage and registers event handlers.
        """
        try:
            self._state = PluginState.INITIALIZING
            self._logger.info("Initializing SkillGraphAdapter")
            
            # Clear any existing data
            self._nodes.clear()
            self._edges.clear()
            self._co_occurrences.clear()
            
            self._state = PluginState.READY
            self._logger.info("SkillGraphAdapter initialized successfully")
            
        except Exception as e:
            self._state = PluginState.ERROR
            self._logger.error(f"SkillGraphAdapter initialization failed: {e}")
            raise
    
    def on_route(self, intent: str, context: Dict[str, Any]) -> RoutingDecision:
        """
        Make routing decision based on skill graph.
        
        Args:
            intent: The classified intent
            context: Execution context
        
        Returns:
            RoutingDecision with target skills
        """
        if self._state != PluginState.READY:
            return RoutingDecision.use_fallback("SkillGraphAdapter not ready")
        
        try:
            # Get task type from context
            task_type = context.get("task_type", intent)
            role_hints = context.get("role_hints", [])
            
            # Select skills via graph traversal
            result = self.select_skills_by_graph(task_type, context)
            
            if result.selected_skills:
                return RoutingDecision.redirect_to(
                    target="skill_chain",
                    confidence=result.path_score,
                    reason=f"Selected {len(result.selected_skills)} skills via graph traversal"
                )
            
            return RoutingDecision.use_fallback("No skills found in graph")
            
        except Exception as e:
            self._logger.error(f"Routing decision failed: {e}")
            return RoutingDecision.use_fallback(f"Error: {str(e)}")
    
    def on_execute(self, plan: Dict[str, Any]) -> ExecutionResult:
        """
        Execute skill graph operations.
        
        Args:
            plan: Execution plan with operation type and parameters
        
        Returns:
            ExecutionResult with operation results
        """
        start_time = datetime.utcnow()
        
        if self._state != PluginState.READY:
            return ExecutionResult.failure_result("SkillGraphAdapter not ready")
        
        try:
            operation = plan.get("operation", "select")
            
            if operation == "select":
                task_type = plan.get("task_type", "")
                context = plan.get("context", {})
                result = self.select_skills_by_graph(task_type, context)
                
                return ExecutionResult.success_result(
                    outputs={"traversal_result": result.to_dict()},
                    execution_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
            
            elif operation == "build":
                skill_library = plan.get("skill_library")
                if skill_library:
                    self.build_graph(skill_library)
                    return ExecutionResult.success_result(
                        outputs={"nodes": len(self._nodes), "edges": len(self._edges)},
                        execution_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                    )
                return ExecutionResult.failure_result("No skill_library provided")
            
            elif operation == "detect_cycles":
                cycles = self.detect_cycles()
                return ExecutionResult.success_result(
                    outputs={"cycles": cycles, "cycle_count": len(cycles)},
                    execution_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
            
            elif operation == "record_synergy":
                skill_ids = plan.get("skill_ids", [])
                success = plan.get("success", True)
                self.record_co_occurrence(skill_ids, success)
                return ExecutionResult.success_result(
                    outputs={"recorded": True},
                    execution_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
            
            else:
                return ExecutionResult.failure_result(f"Unknown operation: {operation}")
                
        except Exception as e:
            self._logger.error(f"Execution failed: {e}")
            return ExecutionResult.failure_result(str(e))
    
    def on_error(self, error: Exception, context: Dict[str, Any]) -> ErrorResult:
        """
        Handle errors during graph operations.
        
        Args:
            error: The exception that occurred
            context: Context where the error occurred
        
        Returns:
            ErrorResult indicating how to proceed
        """
        self._logger.error(f"SkillGraphAdapter error: {error}")
        
        # For graph-related errors, we can continue with degraded functionality
        if isinstance(error, (KeyError, ValueError)):
            return ErrorResult.handled_result(f"Graph operation recovered: {error}")
        
        # For other errors, escalate
        return ErrorResult.unhandled_result(
            str(error),
            RoutingAction.FALLBACK
        )
    
    def on_shutdown(self) -> None:
        """
        Shutdown the adapter and clean up resources.
        """
        self._logger.info("Shutting down SkillGraphAdapter")
        
        with self._lock:
            self._nodes.clear()
            self._edges.clear()
            self._co_occurrences.clear()
            self._state = PluginState.SHUTDOWN
        
        self._logger.info("SkillGraphAdapter shutdown complete")
    
    def get_info(self) -> PluginInfo:
        """Get plugin information."""
        return PluginInfo(
            plugin_id="SkillGraphAdapter",
            plugin_type="skill_adapter",
            version="1.2.0",
            description="Manages skill dependency graph with synergy tracking and graph-based selection",
            capabilities=[
                "graph_building",
                "synergy_tracking",
                "skill_selection",
                "cycle_detection",
                "co_occurrence_tracking"
            ],
            dependencies=["SkillLibrary"],
            priority=5
        )
    
    # =========================================================================
    # Graph Building
    # =========================================================================
    
    def build_graph(self, skill_library: 'SkillLibrary') -> Dict[str, Any]:
        """
        Build skill dependency graph from SkillLibrary.
        
        Args:
            skill_library: Source skill library
        
        Returns:
            Statistics about the built graph
        """
        with self._lock:
            self._skill_library = skill_library
            stats = {
                "nodes_added": 0,
                "edges_added": 0,
                "synergies_created": 0
            }
            
            # Create nodes for all skills
            for skill_id in skill_library.list_skills():
                if skill_id not in self._nodes:
                    self._nodes[skill_id] = SkillNode(skill_id=skill_id)
                    stats["nodes_added"] += 1
            
            # Build edges based on shared patterns and task types
            skills = [skill_library.get_skill(sid) for sid in skill_library.list_skills()]
            skills = [s for s in skills if s is not None]
            
            for i, skill_a in enumerate(skills):
                for skill_b in skills[i+1:]:
                    # Check for shared task types (synergy)
                    shared_tasks = set(skill_a.applicable_to) & set(skill_b.applicable_to)
                    if shared_tasks:
                        synergy_score = len(shared_tasks) / max(
                            len(skill_a.applicable_to), len(skill_b.applicable_to)
                        )
                        if synergy_score >= self._min_synergy_threshold:
                            self._add_synergy_edge(skill_a.skill_id, skill_b.skill_id, synergy_score)
                            stats["synergies_created"] += 1
                            stats["edges_added"] += 1
                    
                    # Check for shared patterns (dependency)
                    patterns_a = {p.pattern_name for p in skill_a.reusable_patterns}
                    patterns_b = {p.pattern_name for p in skill_b.reusable_patterns}
                    shared_patterns = patterns_a & patterns_b
                    if shared_patterns:
                        self._add_dependency_edge(skill_a.skill_id, skill_b.skill_id)
                        stats["edges_added"] += 1
            
            # Emit event
            if self._event_bus:
                self._event_bus.emit_simple(
                    event_type="SKILL_GRAPH_UPDATED",
                    data={
                        "stats": stats,
                        "total_nodes": len(self._nodes),
                        "total_edges": len(self._edges)
                    },
                    source="SkillGraphAdapter"
                )
            
            self._logger.info(f"Built skill graph: {stats}")
            return stats
    
    def _add_synergy_edge(self, skill_a: str, skill_b: str, score: float) -> None:
        """Add a synergy edge between two skills."""
        # Add to nodes
        if skill_a in self._nodes:
            self._nodes[skill_a].synergies[skill_b] = score
        if skill_b in self._nodes:
            self._nodes[skill_b].synergies[skill_a] = score
        
        # Add edge
        edge = SkillEdge(
            source_id=skill_a,
            target_id=skill_b,
            edge_type=EdgeType.SYNERGY,
            weight=score
        )
        self._edges[(skill_a, skill_b)] = edge
        self._edges[(skill_b, skill_a)] = edge
    
    def _add_dependency_edge(self, skill_a: str, skill_b: str) -> None:
        """Add a dependency edge between two skills."""
        if skill_a in self._nodes:
            self._nodes[skill_a].dependencies.add(skill_b)
        if skill_b in self._nodes:
            self._nodes[skill_b].dependents.add(skill_a)
        
        edge = SkillEdge(
            source_id=skill_a,
            target_id=skill_b,
            edge_type=EdgeType.DEPENDS_ON,
            weight=1.0
        )
        self._edges[(skill_a, skill_b)] = edge
    
    # =========================================================================
    # Skill Selection
    # =========================================================================
    
    def select_skills_by_graph(
        self,
        task_type: str,
        context: Dict[str, Any]
    ) -> GraphTraversalResult:
        """
        Select skills using graph traversal.
        
        Selection algorithm:
        1. Find candidate skills by task type
        2. Score candidates based on:
           - Task match score
           - Success rate
           - Synergy with other candidates
        3. Build optimal path through high-scoring skills
        4. Check for cycles if enabled
        
        Args:
            task_type: The task type to select skills for
            context: Additional context (role_hints, etc.)
        
        Returns:
            GraphTraversalResult with selected skills
        """
        with self._lock:
            self._selection_count += 1
            result = GraphTraversalResult()
            
            if not self._skill_library:
                result.fallback_used = True
                self._fallback_count += 1
                return result
            
            # Get candidate skills from library
            role_hints = context.get("role_hints", [])
            candidates = self._skill_library.select_skills(task_type, role_hints)
            
            if not candidates:
                result.fallback_used = True
                self._fallback_count += 1
                return result
            
            # Score candidates
            scored_candidates: List[Tuple[str, float]] = []
            for skill in candidates[:self._max_skills_per_selection * 2]:
                score = self._calculate_skill_score(skill.skill_id, task_type, context)
                scored_candidates.append((skill.skill_id, score))
            
            # Sort by score
            scored_candidates.sort(key=lambda x: x[1], reverse=True)
            
            # Select top skills
            selected = [sid for sid, _ in scored_candidates[:self._max_skills_per_selection]]
            result.selected_skills = selected
            result.path_score = sum(score for _, score in scored_candidates[:len(selected)]) / len(selected) if selected else 0.0
            
            # Generate alternatives
            for i in range(min(3, len(scored_candidates) - len(selected))):
                alt_start = len(selected) + i
                if alt_start < len(scored_candidates):
                    alt = selected[:-1] + [scored_candidates[alt_start][0]] if selected else [scored_candidates[alt_start][0]]
                    result.alternatives.append(alt)
            
            # Check for cycles
            if self._cycle_detection_enabled:
                result.cycles_detected = self.detect_cycles_in_path(selected)
                if result.cycles_detected:
                    # Remove cyclic skills
                    for cycle in result.cycles_detected:
                        for skill_id in cycle:
                            if skill_id in result.selected_skills:
                                result.selected_skills.remove(skill_id)
                    result.fallback_used = True
            
            # Update node stats
            for skill_id in result.selected_skills:
                if skill_id in self._nodes:
                    self._nodes[skill_id].use_count += 1
                    self._nodes[skill_id].last_used = datetime.utcnow().isoformat() + "Z"
            
            return result
    
    def _calculate_skill_score(
        self,
        skill_id: str,
        task_type: str,
        context: Dict[str, Any]
    ) -> float:
        """
        Calculate a score for a skill given task and context.
        
        Factors:
        - Node success rate (0.0-1.0)
        - Node use count (normalized)
        - Synergy with other selected skills
        - Role match bonus
        """
        if skill_id not in self._nodes:
            return 0.5
        
        node = self._nodes[skill_id]
        
        # Base score from success rate
        score = node.success_rate * 0.3
        
        # Use count bonus (normalized, max 0.2)
        use_bonus = min(0.2, (node.use_count / 100) * 0.2)
        score += use_bonus
        
        # Synergy bonus (0.0-0.3)
        if node.synergies:
            avg_synergy = sum(node.synergies.values()) / len(node.synergies)
            score += avg_synergy * 0.3
        
        # Role match bonus
        role_hints = context.get("role_hints", [])
        if role_hints and self._skill_library:
            skill = self._skill_library.get_skill(skill_id)
            if skill:
                for role in role_hints:
                    if skill.matches_role(role):
                        score += 0.2
                        break
        
        return min(1.0, score)
    
    # =========================================================================
    # Cycle Detection
    # =========================================================================
    
    def detect_cycles(self) -> List[List[str]]:
        """
        Detect all cycles in the dependency graph.
        
        Uses DFS with color marking:
        - WHITE: Not visited
        - GRAY: Being processed
        - BLACK: Fully processed
        
        Returns:
            List of cycles, each cycle is a list of skill IDs
        """
        with self._lock:
            self._cycle_detection_count += 1
            cycles: List[List[str]] = []
            
            # Color marking: 0=WHITE, 1=GRAY, 2=BLACK
            color: Dict[str, int] = {sid: 0 for sid in self._nodes}
            path: List[str] = []
            
            def dfs(node_id: str) -> None:
                if color[node_id] == 1:  # GRAY - cycle found
                    # Extract cycle from path
                    cycle_start = path.index(node_id)
                    cycle = path[cycle_start:] + [node_id]
                    cycles.append(cycle)
                    return
                
                if color[node_id] == 2:  # BLACK - already processed
                    return
                
                color[node_id] = 1  # Mark GRAY
                path.append(node_id)
                
                # Visit dependencies
                if node_id in self._nodes:
                    for dep_id in self._nodes[node_id].dependencies:
                        if dep_id in self._nodes:
                            dfs(dep_id)
                
                path.pop()
                color[node_id] = 2  # Mark BLACK
            
            # Start DFS from each unvisited node
            for node_id in self._nodes:
                if color[node_id] == 0:
                    dfs(node_id)
            
            if cycles:
                self._logger.warning(f"Detected {len(cycles)} cycles in skill graph")
            
            return cycles
    
    def detect_cycles_in_path(self, skill_path: List[str]) -> List[List[str]]:
        """
        Detect cycles that would be formed by a skill path.
        
        Args:
            skill_path: Ordered list of skill IDs
        
        Returns:
            List of cycles that would be formed
        """
        cycles: List[List[str]] = []
        
        # Check if any consecutive pair forms a dependency cycle
        for i, skill_id in enumerate(skill_path):
            if skill_id not in self._nodes:
                continue
            
            # Check if this skill depends on any skill that comes after it
            for j in range(i + 1, len(skill_path)):
                later_skill = skill_path[j]
                if later_skill in self._nodes[skill_id].dependencies:
                    # Check reverse dependency
                    if skill_id in self._nodes.get(later_skill, SkillNode(skill_id="")).dependencies:
                        cycles.append([skill_id, later_skill])
        
        return cycles
    
    # =========================================================================
    # Synergy Tracking
    # =========================================================================
    
    def record_co_occurrence(self, skill_ids: List[str], success: bool) -> None:
        """
        Record co-occurrence of skills in an execution.
        
        Args:
            skill_ids: List of skills that were used together
            success: Whether the execution was successful
        """
        with self._lock:
            # Record all pairs
            for i, skill_a in enumerate(skill_ids):
                for skill_b in skill_ids[i+1:]:
                    key = (min(skill_a, skill_b), max(skill_a, skill_b))
                    
                    if key not in self._co_occurrences:
                        self._co_occurrences[key] = CoOccurrenceRecord(
                            skill_a=key[0],
                            skill_b=key[1]
                        )
                    
                    self._co_occurrences[key].record_use(success)
                    
                    # Update synergy score in nodes
                    synergy_score = self._co_occurrences[key].success_rate
                    if skill_a in self._nodes:
                        self._nodes[skill_a].synergies[skill_b] = synergy_score
                    if skill_b in self._nodes:
                        self._nodes[skill_b].synergies[skill_a] = synergy_score
    
    def update_success_rate(self, skill_id: str, success: bool) -> None:
        """
        Update success rate for a skill.
        
        Args:
            skill_id: The skill to update
            success: Whether the execution was successful
        """
        with self._lock:
            if skill_id not in self._nodes:
                return
            
            node = self._nodes[skill_id]
            # Exponential moving average
            alpha = 0.1
            node.success_rate = alpha * (1.0 if success else 0.0) + (1 - alpha) * node.success_rate
            node.last_used = datetime.utcnow().isoformat() + "Z"
    
    # =========================================================================
    # Statistics and Utilities
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get adapter statistics."""
        with self._lock:
            return {
                "state": self._state.value,
                "total_nodes": len(self._nodes),
                "total_edges": len(self._edges) // 2,  # Bidirectional
                "co_occurrence_pairs": len(self._co_occurrences),
                "selection_count": self._selection_count,
                "cycle_detection_count": self._cycle_detection_count,
                "fallback_count": self._fallback_count,
                "top_synergies": self._get_top_synergies(5),
                "most_used_skills": self._get_most_used_skills(5)
            }
    
    def _get_top_synergies(self, limit: int) -> List[Dict[str, Any]]:
        """Get top synergies by score."""
        synergies = []
        for key, record in self._co_occurrences.items():
            if record.co_occurrence_count >= 2:  # Minimum occurrences
                synergies.append({
                    "skills": list(key),
                    "score": record.success_rate,
                    "count": record.co_occurrence_count
                })
        synergies.sort(key=lambda x: x["score"], reverse=True)
        return synergies[:limit]
    
    def _get_most_used_skills(self, limit: int) -> List[Dict[str, Any]]:
        """Get most used skills."""
        skills = [
            {"skill_id": sid, "use_count": node.use_count, "success_rate": node.success_rate}
            for sid, node in self._nodes.items()
        ]
        skills.sort(key=lambda x: x["use_count"], reverse=True)
        return skills[:limit]
    
    def get_node(self, skill_id: str) -> Optional[SkillNode]:
        """Get a skill node by ID."""
        return self._nodes.get(skill_id)
    
    def get_synergies(self, skill_id: str) -> Dict[str, float]:
        """Get synergies for a skill."""
        if skill_id in self._nodes:
            return self._nodes[skill_id].synergies.copy()
        return {}


# Factory function
def create_skill_graph_adapter(
    config: Dict[str, Any] = None,
    event_bus: 'EventBus' = None
) -> SkillGraphAdapter:
    """
    Factory function to create a SkillGraphAdapter.
    
    Args:
        config: Configuration dictionary
        event_bus: Optional EventBus for events
    
    Returns:
        SkillGraphAdapter instance
    """
    return SkillGraphAdapter(config or {}, event_bus)
