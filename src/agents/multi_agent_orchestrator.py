"""
Multi-Agent Orchestrator for TITAN FUSE Protocol.

ITEM-AGENT-01: Multi-agent coordination with task dispatching,
conflict resolution, and result aggregation.

Features:
- Agent registration with capability tracking
- Priority-based task queue with capability matching
- Task dispatch to appropriate agents
- Result aggregation with confidence scoring
- Conflict resolution using existing ConflictResolver
- Heartbeat-based agent health monitoring

Author: TITAN FUSE Team
Version: 4.0.0
"""

from __future__ import annotations

import heapq
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from ..events.event_bus import EventBus
    from ..decision.conflict_resolver import ConflictResolver, ConflictMetrics

# Configure module logger
logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================

class AgentStatus(Enum):
    """
    Status of an agent in the orchestrator.
    
    Attributes:
        IDLE: Agent is available for task assignment
        BUSY: Agent is currently processing a task
        OFFLINE: Agent is not responding
        ERROR: Agent encountered an error
    """
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"
    ERROR = "error"
    
    def is_available(self) -> bool:
        """Check if agent is available for task assignment."""
        return self == AgentStatus.IDLE


class TaskStatus(Enum):
    """Status of a task in the orchestrator."""
    PENDING = "pending"
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REQUEUED = "requeued"


class TaskPriority(Enum):
    """Task priority levels."""
    CRITICAL = 0    # Highest priority
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4  # Lowest priority


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class Agent:
    """
    Represents an agent in the orchestrator.
    
    Attributes:
        id: Unique identifier for the agent
        capabilities: List of capabilities this agent possesses
        status: Current status of the agent
        last_heartbeat: Timestamp of the last heartbeat
        current_task_id: ID of the task currently being processed (if any)
        metadata: Additional agent metadata
        created_at: When the agent was registered
    """
    id: str
    capabilities: List[str]
    status: AgentStatus = AgentStatus.IDLE
    last_heartbeat: Optional[datetime] = None
    current_task_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self) -> None:
        """Initialize heartbeat if not set."""
        if self.last_heartbeat is None:
            self.last_heartbeat = datetime.utcnow()
    
    def has_capability(self, capability: str) -> bool:
        """Check if agent has a specific capability."""
        return capability in self.capabilities
    
    def has_capabilities(self, capabilities: List[str]) -> bool:
        """Check if agent has all specified capabilities."""
        return all(cap in self.capabilities for cap in capabilities)
    
    def is_healthy(self, timeout_seconds: int = 60) -> bool:
        """Check if agent is healthy based on heartbeat."""
        if self.last_heartbeat is None:
            return False
        return datetime.utcnow() - self.last_heartbeat < timedelta(seconds=timeout_seconds)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "capabilities": self.capabilities,
            "status": self.status.value,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "current_task_id": self.current_task_id,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Agent":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            capabilities=data["capabilities"],
            status=AgentStatus(data.get("status", "idle")),
            last_heartbeat=datetime.fromisoformat(data["last_heartbeat"]) if data.get("last_heartbeat") else None,
            current_task_id=data.get("current_task_id"),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
        )


@dataclass
class Task:
    """
    Represents a task to be dispatched to an agent.
    
    Attributes:
        id: Unique identifier for the task
        type: Type of task (e.g., 'analysis', 'validation', 'synthesis')
        payload: Task payload data
        priority: Task priority (lower value = higher priority)
        required_capabilities: List of capabilities required to process this task
        status: Current status of the task
        assigned_agent_id: ID of the agent assigned to this task
        created_at: When the task was created
        updated_at: When the task was last updated
        metadata: Additional task metadata
        retry_count: Number of retry attempts
        max_retries: Maximum allowed retries
    """
    id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    type: str = "generic"
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = TaskPriority.NORMAL.value
    required_capabilities: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    assigned_agent_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 3
    
    def __lt__(self, other: "Task") -> bool:
        """Compare tasks by priority for heap operations."""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at
    
    def can_retry(self) -> bool:
        """Check if task can be retried."""
        return self.retry_count < self.max_retries
    
    def increment_retry(self) -> None:
        """Increment retry count."""
        self.retry_count += 1
        self.updated_at = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "priority": self.priority,
            "required_capabilities": self.required_capabilities,
            "status": self.status.value,
            "assigned_agent_id": self.assigned_agent_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create from dictionary."""
        return cls(
            id=data.get("id", f"task-{uuid.uuid4().hex[:8]}"),
            type=data.get("type", "generic"),
            payload=data.get("payload", {}),
            priority=data.get("priority", TaskPriority.NORMAL.value),
            required_capabilities=data.get("required_capabilities", []),
            status=TaskStatus(data.get("status", "pending")),
            assigned_agent_id=data.get("assigned_agent_id"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.utcnow(),
            metadata=data.get("metadata", {}),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
        )


@dataclass
class Result:
    """
    Result from a task execution.
    
    Attributes:
        task_id: ID of the task that produced this result
        agent_id: ID of the agent that produced this result
        success: Whether the task succeeded
        data: Result data
        error: Error message if task failed
        confidence: Confidence score (0.0 - 1.0)
        metrics: Performance and quality metrics
        timestamp: When the result was produced
    """
    task_id: str
    agent_id: str
    success: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    confidence: float = 1.0
    metrics: Dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "confidence": self.confidence,
            "metrics": self.metrics,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AggregatedResult:
    """
    Aggregated result from multiple agent executions.
    
    Attributes:
        task_id: ID of the original task
        results: List of individual results from agents
        final_result: The final aggregated result data
        confidence: Overall confidence score
        conflict_resolved: Whether a conflict was resolved
        resolution_details: Details of conflict resolution if applicable
        timestamp: When aggregation was completed
    """
    task_id: str
    results: List[Result] = field(default_factory=list)
    final_result: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    conflict_resolved: bool = False
    resolution_details: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "results": [r.to_dict() for r in self.results],
            "final_result": self.final_result,
            "confidence": self.confidence,
            "conflict_resolved": self.conflict_resolved,
            "resolution_details": self.resolution_details,
            "timestamp": self.timestamp.isoformat(),
        }


# =============================================================================
# TaskQueue Class
# =============================================================================

@dataclass(order=True)
class PrioritizedTask:
    """Wrapper for priority queue tasks."""
    priority: int
    task: Task = field(compare=False)


class TaskQueue:
    """
    Priority-based task queue with capability matching.
    
    Supports:
    - Priority-based task ordering
    - Capability-based task matching
    - Task requeuing with reason tracking
    """
    
    def __init__(self, max_size: int = 10000):
        """
        Initialize the task queue.
        
        Args:
            max_size: Maximum number of tasks in the queue
        """
        self._queue: List[PrioritizedTask] = []
        self._task_index: Dict[str, Task] = {}  # task_id -> Task
        self._requeue_history: Dict[str, List[Dict[str, Any]]] = {}  # task_id -> requeue history
        self._lock = threading.RLock()
        self._max_size = max_size
        self._counter = 0  # For stable sorting
    
    def enqueue(self, task: Task, priority: Optional[int] = None) -> None:
        """
        Add a task to the queue.
        
        Args:
            task: Task to enqueue
            priority: Optional priority override (uses task.priority if not provided)
            
        Raises:
            ValueError: If task with same ID already exists
            RuntimeError: If queue is at max capacity
        """
        with self._lock:
            if task.id in self._task_index:
                raise ValueError(f"Task {task.id} already exists in queue")
            
            if len(self._queue) >= self._max_size:
                raise RuntimeError(f"Task queue at max capacity ({self._max_size})")
            
            effective_priority = priority if priority is not None else task.priority
            task.priority = effective_priority
            task.status = TaskStatus.QUEUED
            task.updated_at = datetime.utcnow()
            
            # Use counter for stable sorting (FIFO within same priority)
            prioritized = PrioritizedTask(priority=effective_priority, task=task)
            heapq.heappush(self._queue, prioritized)
            self._task_index[task.id] = task
            
            logger.debug(f"Enqueued task {task.id} with priority {effective_priority}")
    
    def dequeue(self, capabilities: Optional[List[str]] = None) -> Optional[Task]:
        """
        Get the next task that matches the given capabilities.
        
        Args:
            capabilities: Required capabilities for the task (optional)
            
        Returns:
            Task if found and matched, None otherwise
        """
        with self._lock:
            if not self._queue:
                return None
            
            # Find a task that matches capabilities
            if capabilities:
                # Search for matching task
                for i, prioritized in enumerate(self._queue):
                    task = prioritized.task
                    required = task.required_capabilities
                    # Check if agent capabilities satisfy task requirements
                    if not required or all(cap in capabilities for cap in required):
                        # Remove from heap
                        self._queue.pop(i)
                        heapq.heapify(self._queue)
                        del self._task_index[task.id]
                        task.status = TaskStatus.DISPATCHED
                        task.updated_at = datetime.utcnow()
                        logger.debug(f"Dequeued task {task.id} for capabilities {capabilities}")
                        return task
                return None
            else:
                # No capability filter, return highest priority task
                prioritized = heapq.heappop(self._queue)
                task = prioritized.task
                del self._task_index[task.id]
                task.status = TaskStatus.DISPATCHED
                task.updated_at = datetime.utcnow()
                logger.debug(f"Dequeued task {task.id}")
                return task
    
    def requeue(self, task_id: str, reason: str) -> None:
        """
        Requeue a task with a reason.
        
        Args:
            task_id: ID of the task to requeue
            reason: Reason for requeuing
            
        Raises:
            ValueError: If task not found
        """
        with self._lock:
            if task_id not in self._requeue_history:
                self._requeue_history[task_id] = []
            
            self._requeue_history[task_id].append({
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat(),
            })
            
            logger.info(f"Requeued task {task_id}: {reason}")
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self._task_index.get(task_id)
    
    def get_requeue_history(self, task_id: str) -> List[Dict[str, Any]]:
        """Get requeue history for a task."""
        return self._requeue_history.get(task_id, [])
    
    def size(self) -> int:
        """Get current queue size."""
        return len(self._queue)
    
    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return len(self._queue) == 0
    
    def clear(self) -> None:
        """Clear the queue."""
        with self._lock:
            self._queue.clear()
            self._task_index.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        with self._lock:
            priority_counts: Dict[int, int] = {}
            for prioritized in self._queue:
                p = prioritized.priority
                priority_counts[p] = priority_counts.get(p, 0) + 1
            
            return {
                "total_tasks": len(self._queue),
                "max_size": self._max_size,
                "priority_distribution": priority_counts,
                "total_requeued": len(self._requeue_history),
            }


# =============================================================================
# AgentRegistry Class
# =============================================================================

class AgentRegistry:
    """
    Registry for agents with capability-based lookup.
    
    Supports:
    - Agent registration and unregistration
    - Capability-based agent lookup
    - Heartbeat tracking for health monitoring
    """
    
    def __init__(self, heartbeat_timeout_seconds: int = 60):
        """
        Initialize the agent registry.
        
        Args:
            heartbeat_timeout_seconds: Seconds after which agent is considered offline
        """
        self._agents: Dict[str, Agent] = {}
        self._capability_index: Dict[str, Set[str]] = {}  # capability -> agent_ids
        self._lock = threading.RLock()
        self._heartbeat_timeout = heartbeat_timeout_seconds
    
    def register(self, agent: Agent) -> None:
        """
        Register an agent.
        
        Args:
            agent: Agent to register
            
        Raises:
            ValueError: If agent with same ID already exists
        """
        with self._lock:
            if agent.id in self._agents:
                raise ValueError(f"Agent {agent.id} already registered")
            
            self._agents[agent.id] = agent
            agent.last_heartbeat = datetime.utcnow()
            
            # Update capability index
            for capability in agent.capabilities:
                if capability not in self._capability_index:
                    self._capability_index[capability] = set()
                self._capability_index[capability].add(agent.id)
            
            logger.info(f"Registered agent {agent.id} with capabilities: {agent.capabilities}")
    
    def unregister(self, agent_id: str) -> None:
        """
        Unregister an agent.
        
        Args:
            agent_id: ID of agent to unregister
        """
        with self._lock:
            agent = self._agents.pop(agent_id, None)
            if agent:
                # Update capability index
                for capability in agent.capabilities:
                    if capability in self._capability_index:
                        self._capability_index[capability].discard(agent_id)
                        if not self._capability_index[capability]:
                            del self._capability_index[capability]
                logger.info(f"Unregistered agent {agent_id}")
    
    def get_available(self, capabilities: Optional[List[str]] = None) -> List[Agent]:
        """
        Get available agents that have the specified capabilities.
        
        Args:
            capabilities: Required capabilities (optional)
            
        Returns:
            List of available agents sorted by availability
        """
        with self._lock:
            # Update health status before returning
            self._update_health_status()
            
            if not capabilities:
                # Return all idle agents
                return [
                    agent for agent in self._agents.values()
                    if agent.status == AgentStatus.IDLE
                ]
            
            # Find agents with all required capabilities
            candidate_ids: Optional[Set[str]] = None
            for capability in capabilities:
                cap_agent_ids = self._capability_index.get(capability, set())
                if candidate_ids is None:
                    candidate_ids = cap_agent_ids.copy()
                else:
                    candidate_ids &= cap_agent_ids
            
            if not candidate_ids:
                return []
            
            # Filter to available agents
            available = [
                self._agents[agent_id]
                for agent_id in candidate_ids
                if agent_id in self._agents and self._agents[agent_id].status == AgentStatus.IDLE
            ]
            
            # Sort by last_heartbeat (most recent first)
            available.sort(key=lambda a: a.last_heartbeat or datetime.min, reverse=True)
            
            return available
    
    def heartbeat(self, agent_id: str) -> None:
        """
        Record a heartbeat for an agent.
        
        Args:
            agent_id: ID of the agent
            
        Raises:
            ValueError: If agent not found
        """
        with self._lock:
            if agent_id not in self._agents:
                raise ValueError(f"Agent {agent_id} not found")
            
            agent = self._agents[agent_id]
            agent.last_heartbeat = datetime.utcnow()
            
            # If agent was offline, mark as idle
            if agent.status == AgentStatus.OFFLINE:
                agent.status = AgentStatus.IDLE
                logger.info(f"Agent {agent_id} back online")
            
            logger.debug(f"Heartbeat from agent {agent_id}")
    
    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """Get an agent by ID."""
        return self._agents.get(agent_id)
    
    def set_agent_status(self, agent_id: str, status: AgentStatus) -> None:
        """
        Set the status of an agent.
        
        Args:
            agent_id: ID of the agent
            status: New status
        """
        with self._lock:
            if agent_id in self._agents:
                self._agents[agent_id].status = status
                logger.debug(f"Agent {agent_id} status set to {status.value}")
    
    def _update_health_status(self) -> None:
        """Update agent health status based on heartbeats."""
        now = datetime.utcnow()
        for agent in self._agents.values():
            if agent.status not in (AgentStatus.OFFLINE, AgentStatus.ERROR):
                if agent.last_heartbeat:
                    if now - agent.last_heartbeat > timedelta(seconds=self._heartbeat_timeout):
                        agent.status = AgentStatus.OFFLINE
                        logger.warning(f"Agent {agent.id} marked as offline (heartbeat timeout)")
    
    def get_all_agents(self) -> List[Agent]:
        """Get all registered agents."""
        return list(self._agents.values())
    
    def count(self) -> int:
        """Get total number of registered agents."""
        return len(self._agents)
    
    def count_by_status(self, status: AgentStatus) -> int:
        """Count agents with a specific status."""
        return sum(1 for a in self._agents.values() if a.status == status)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        with self._lock:
            self._update_health_status()
            
            status_counts = {}
            for status in AgentStatus:
                status_counts[status.value] = self.count_by_status(status)
            
            capability_counts = {
                cap: len(agents) for cap, agents in self._capability_index.items()
            }
            
            return {
                "total_agents": len(self._agents),
                "status_distribution": status_counts,
                "capability_distribution": capability_counts,
                "heartbeat_timeout_seconds": self._heartbeat_timeout,
            }


# =============================================================================
# MultiAgentOrchestrator Class
# =============================================================================

class MultiAgentOrchestrator:
    """
    Orchestrates multi-agent coordination with task dispatching,
    conflict resolution, and result aggregation.
    
    Features:
    - Agent registration with capability tracking
    - Priority-based task dispatching
    - Result aggregation with confidence scoring
    - Conflict resolution using ConflictResolver
    - EventBus integration for event emission
    
    Usage:
        orchestrator = MultiAgentOrchestrator(event_bus=event_bus)
        
        # Register agents
        orchestrator.register_agent("agent-1", ["analysis", "validation"])
        orchestrator.register_agent("agent-2", ["synthesis"])
        
        # Dispatch task
        task_id = orchestrator.dispatch_task(task)
        
        # Get agent status
        status = orchestrator.get_agent_status("agent-1")
        
        # Aggregate results
        aggregated = orchestrator.aggregate_results(task_id)
    """
    
    def __init__(
        self,
        event_bus: Optional["EventBus"] = None,
        conflict_resolver: Optional["ConflictResolver"] = None,
        heartbeat_timeout: int = 60,
        max_queue_size: int = 10000,
    ):
        """
        Initialize the multi-agent orchestrator.
        
        Args:
            event_bus: Optional event bus for event emission
            conflict_resolver: Optional conflict resolver (default created if None)
            heartbeat_timeout: Seconds after which agent is considered offline
            max_queue_size: Maximum task queue size
        """
        self._registry = AgentRegistry(heartbeat_timeout_seconds=heartbeat_timeout)
        self._task_queue = TaskQueue(max_size=max_queue_size)
        self._results: Dict[str, List[Result]] = {}  # task_id -> results
        self._dispatched_tasks: Dict[str, Task] = {}  # task_id -> Task
        self._event_bus = event_bus
        self._lock = threading.RLock()
        
        # Initialize conflict resolver
        if conflict_resolver is None:
            from ..decision.conflict_resolver import ConflictResolver
            self._conflict_resolver = ConflictResolver()
        else:
            self._conflict_resolver = conflict_resolver
        
        logger.info("MultiAgentOrchestrator initialized")
    
    # -------------------------------------------------------------------------
    # Agent Management
    # -------------------------------------------------------------------------
    
    def register_agent(self, agent_id: str, capabilities: List[str]) -> None:
        """
        Register an agent with capabilities.
        
        Args:
            agent_id: Unique identifier for the agent
            capabilities: List of capabilities this agent possesses
        """
        agent = Agent(id=agent_id, capabilities=capabilities)
        self._registry.register(agent)
        
        self._emit_event("AGENT_REGISTERED", {
            "agent_id": agent_id,
            "capabilities": capabilities,
        })
    
    def unregister_agent(self, agent_id: str) -> None:
        """
        Unregister an agent.
        
        Args:
            agent_id: ID of agent to unregister
        """
        self._registry.unregister(agent_id)
        
        self._emit_event("AGENT_UNREGISTERED", {
            "agent_id": agent_id,
        })
    
    def get_agent_status(self, agent_id: str) -> AgentStatus:
        """
        Get the status of an agent.
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            AgentStatus enum value
            
        Raises:
            ValueError: If agent not found
        """
        agent = self._registry.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        return agent.status
    
    def agent_heartbeat(self, agent_id: str) -> None:
        """
        Record a heartbeat for an agent.
        
        Args:
            agent_id: ID of the agent
        """
        self._registry.heartbeat(agent_id)
    
    # -------------------------------------------------------------------------
    # Task Management
    # -------------------------------------------------------------------------
    
    def dispatch_task(self, task: Task) -> str:
        """
        Dispatch a task to an appropriate agent.
        
        Args:
            task: Task to dispatch
            
        Returns:
            ID of the assigned agent
            
        Raises:
            RuntimeError: If no suitable agent is available
        """
        with self._lock:
            # Find available agent with required capabilities
            available_agents = self._registry.get_available(task.required_capabilities)
            
            if not available_agents:
                # No agent available, queue the task
                self._task_queue.enqueue(task)
                self._emit_event("TASK_QUEUED", {
                    "task_id": task.id,
                    "reason": "no_available_agent",
                })
                logger.info(f"No agent available for task {task.id}, queued")
                return ""
            
            # Select the first available agent
            selected_agent = available_agents[0]
            
            # Update agent status
            self._registry.set_agent_status(selected_agent.id, AgentStatus.BUSY)
            selected_agent.current_task_id = task.id
            
            # Update task
            task.status = TaskStatus.IN_PROGRESS
            task.assigned_agent_id = selected_agent.id
            task.updated_at = datetime.utcnow()
            
            # Store dispatched task
            self._dispatched_tasks[task.id] = task
            
            self._emit_event("TASK_DISPATCHED", {
                "task_id": task.id,
                "agent_id": selected_agent.id,
                "task_type": task.type,
            })
            
            logger.info(f"Dispatched task {task.id} to agent {selected_agent.id}")
            return selected_agent.id
    
    def submit_result(self, result: Result) -> None:
        """
        Submit a result from an agent.
        
        Args:
            result: Result to submit
        """
        with self._lock:
            if result.task_id not in self._results:
                self._results[result.task_id] = []
            self._results[result.task_id].append(result)
            
            # Update agent status
            agent = self._registry.get_agent(result.agent_id)
            if agent:
                agent.status = AgentStatus.IDLE
                agent.current_task_id = None
            
            # Update task status
            task = self._dispatched_tasks.get(result.task_id)
            if task:
                task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
                task.updated_at = datetime.utcnow()
            
            self._emit_event("RESULT_SUBMITTED", {
                "task_id": result.task_id,
                "agent_id": result.agent_id,
                "success": result.success,
            })
            
            logger.info(f"Result submitted for task {result.task_id} by agent {result.agent_id}")
    
    def get_task_result(self, task_id: str) -> Optional[List[Result]]:
        """Get results for a task."""
        return self._results.get(task_id)
    
    # -------------------------------------------------------------------------
    # Result Aggregation
    # -------------------------------------------------------------------------
    
    def aggregate_results(self, task_id: str) -> AggregatedResult:
        """
        Aggregate results from multiple agents for a task.
        
        Args:
            task_id: ID of the task
            
        Returns:
            AggregatedResult with combined results
        """
        results = self._results.get(task_id, [])
        
        if not results:
            return AggregatedResult(task_id=task_id)
        
        # Calculate confidence as weighted average
        total_confidence = sum(r.confidence for r in results)
        avg_confidence = total_confidence / len(results) if results else 0.0
        
        # Combine data from all results
        combined_data: Dict[str, Any] = {}
        for result in results:
            combined_data.update(result.data)
        
        aggregated = AggregatedResult(
            task_id=task_id,
            results=results,
            final_result=combined_data,
            confidence=avg_confidence,
        )
        
        # If multiple results with different data, check for conflicts
        if len(results) > 1:
            conflict_result = self._check_and_resolve_conflicts(results)
            if conflict_result:
                aggregated.conflict_resolved = True
                aggregated.resolution_details = conflict_result.to_dict()
                aggregated.final_result = conflict_result.data if hasattr(conflict_result, 'data') else combined_data
                aggregated.confidence = getattr(conflict_result, 'confidence', avg_confidence)
        
        self._emit_event("RESULTS_AGGREGATED", {
            "task_id": task_id,
            "result_count": len(results),
            "confidence": aggregated.confidence,
            "conflict_resolved": aggregated.conflict_resolved,
        })
        
        logger.info(
            f"Aggregated {len(results)} results for task {task_id}, "
            f"confidence: {aggregated.confidence:.2f}"
        )
        
        return aggregated
    
    def _check_and_resolve_conflicts(self, results: List[Result]) -> Optional[Result]:
        """Check for conflicts and resolve if necessary."""
        # Check if results have conflicting data
        if len(results) < 2:
            return None
        
        # Find conflicting keys
        data_keys = [set(r.data.keys()) for r in results]
        common_keys = set.intersection(*data_keys) if data_keys else set()
        
        conflicts = []
        for key in common_keys:
            values = [r.data[key] for r in results]
            if len(set(str(v) for v in values)) > 1:
                conflicts.append(key)
        
        if not conflicts:
            return None
        
        # Resolve conflicts
        return self.resolve_conflicts(results)
    
    # -------------------------------------------------------------------------
    # Conflict Resolution
    # -------------------------------------------------------------------------
    
    def resolve_conflicts(self, results: List[Result]) -> Result:
        """
        Resolve conflicts between results using ConflictResolver.
        
        Args:
            results: List of conflicting results
            
        Returns:
            Resolved Result
        """
        if len(results) == 1:
            return results[0]
        
        if len(results) == 2:
            # Use ConflictResolver for pairwise comparison
            return self._resolve_pairwise_conflict(results[0], results[1])
        
        # For more than 2 results, use tournament-style resolution
        return self._resolve_tournament_conflict(results)
    
    def _resolve_pairwise_conflict(self, result_a: Result, result_b: Result) -> Result:
        """Resolve conflict between two results."""
        from ..decision.conflict_resolver import ConflictMetrics
        
        # Create metrics from results
        metrics_a = ConflictMetrics(
            accuracy=result_a.metrics.get("accuracy", result_a.confidence),
            utility=result_a.metrics.get("utility", result_a.confidence),
            efficiency=result_a.metrics.get("efficiency", result_a.confidence),
            consensus=result_a.metrics.get("consensus", result_a.confidence),
        )
        
        metrics_b = ConflictMetrics(
            accuracy=result_b.metrics.get("accuracy", result_b.confidence),
            utility=result_b.metrics.get("utility", result_b.confidence),
            efficiency=result_b.metrics.get("efficiency", result_b.confidence),
            consensus=result_b.metrics.get("consensus", result_b.confidence),
        )
        
        decision = self._conflict_resolver.resolve(
            metrics_a, metrics_b,
            label_a=result_a.agent_id,
            label_b=result_b.agent_id
        )
        
        winner = result_a if decision.winner == result_a.agent_id else result_b
        
        # Create resolved result
        resolved = Result(
            task_id=winner.task_id,
            agent_id=f"resolved:{winner.agent_id}",
            success=True,
            data=winner.data,
            confidence=winner.confidence,
            metrics={
                "resolution_confidence": decision.confidence.value,
                "score_a": decision.score_a,
                "score_b": decision.score_b,
                "gap": decision.gap,
            },
        )
        
        logger.info(
            f"Resolved conflict: winner={decision.winner}, "
            f"confidence={decision.confidence.value}"
        )
        
        return resolved
    
    def _resolve_tournament_conflict(self, results: List[Result]) -> Result:
        """Resolve conflicts using tournament-style comparison."""
        current_winner = results[0]
        
        for i in range(1, len(results)):
            current_winner = self._resolve_pairwise_conflict(current_winner, results[i])
        
        return current_winner
    
    # -------------------------------------------------------------------------
    # Event Emission
    # -------------------------------------------------------------------------
    
    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit an event if event bus is configured."""
        if self._event_bus is not None:
            from ..events.event_bus import Event, EventSeverity
            event = Event(
                event_type=event_type,
                data=data,
                severity=EventSeverity.INFO,
                source="MultiAgentOrchestrator",
            )
            self._event_bus.emit(event)
    
    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------
    
    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        with self._lock:
            return {
                "registry": self._registry.get_stats(),
                "queue": self._task_queue.get_stats(),
                "dispatched_tasks": len(self._dispatched_tasks),
                "tasks_with_results": len(self._results),
            }
    
    # -------------------------------------------------------------------------
    # Convenience Methods
    # -------------------------------------------------------------------------
    
    def process_queued_tasks(self) -> int:
        """
        Process queued tasks by dispatching to available agents.
        
        Returns:
            Number of tasks dispatched
        """
        dispatched = 0
        
        while not self._task_queue.is_empty():
            # Get available agents
            available = self._registry.get_available()
            if not available:
                break
            
            # Get agent capabilities
            agent = available[0]
            task = self._task_queue.dequeue(agent.capabilities)
            
            if task:
                task.assigned_agent_id = agent.id
                task.status = TaskStatus.IN_PROGRESS
                agent.status = AgentStatus.BUSY
                agent.current_task_id = task.id
                self._dispatched_tasks[task.id] = task
                
                self._emit_event("TASK_DISPATCHED", {
                    "task_id": task.id,
                    "agent_id": agent.id,
                })
                
                dispatched += 1
        
        return dispatched


# =============================================================================
# Factory Function
# =============================================================================

def create_orchestrator(
    event_bus: Optional["EventBus"] = None,
    conflict_resolver: Optional["ConflictResolver"] = None,
    heartbeat_timeout: int = 60,
    max_queue_size: int = 10000,
) -> MultiAgentOrchestrator:
    """
    Create a MultiAgentOrchestrator instance.
    
    Args:
        event_bus: Optional event bus for event emission
        conflict_resolver: Optional conflict resolver
        heartbeat_timeout: Seconds after which agent is considered offline
        max_queue_size: Maximum task queue size
        
    Returns:
        Configured MultiAgentOrchestrator instance
    """
    return MultiAgentOrchestrator(
        event_bus=event_bus,
        conflict_resolver=conflict_resolver,
        heartbeat_timeout=heartbeat_timeout,
        max_queue_size=max_queue_size,
    )
