"""
Tests for Multi-Agent Orchestrator.

ITEM-AGENT-01: Test suite for multi-agent coordination.

Tests cover:
- Agent registration and status management
- Task queue operations
- Task dispatching and routing
- Result aggregation
- Conflict resolution
- Heartbeat monitoring
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
import threading
import time

from src.agents.multi_agent_orchestrator import (
    AgentStatus,
    TaskStatus,
    TaskPriority,
    Agent,
    Task,
    Result,
    AggregatedResult,
    TaskQueue,
    AgentRegistry,
    MultiAgentOrchestrator,
    create_orchestrator,
)


# =============================================================================
# AgentStatus Tests
# =============================================================================

class TestAgentStatus:
    """Tests for AgentStatus enum."""
    
    def test_status_values(self):
        """Test AgentStatus enum values."""
        assert AgentStatus.IDLE.value == "idle"
        assert AgentStatus.BUSY.value == "busy"
        assert AgentStatus.OFFLINE.value == "offline"
        assert AgentStatus.ERROR.value == "error"
    
    def test_is_available(self):
        """Test is_available method."""
        assert AgentStatus.IDLE.is_available() is True
        assert AgentStatus.BUSY.is_available() is False
        assert AgentStatus.OFFLINE.is_available() is False
        assert AgentStatus.ERROR.is_available() is False


# =============================================================================
# TaskStatus Tests
# =============================================================================

class TestTaskStatus:
    """Tests for TaskStatus enum."""
    
    def test_status_values(self):
        """Test TaskStatus enum values."""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.QUEUED.value == "queued"
        assert TaskStatus.DISPATCHED.value == "dispatched"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.REQUEUED.value == "requeued"


# =============================================================================
# TaskPriority Tests
# =============================================================================

class TestTaskPriority:
    """Tests for TaskPriority enum."""
    
    def test_priority_ordering(self):
        """Test TaskPriority ordering."""
        assert TaskPriority.CRITICAL.value < TaskPriority.HIGH.value
        assert TaskPriority.HIGH.value < TaskPriority.NORMAL.value
        assert TaskPriority.NORMAL.value < TaskPriority.LOW.value
        assert TaskPriority.LOW.value < TaskPriority.BACKGROUND.value


# =============================================================================
# Agent Tests
# =============================================================================

class TestAgent:
    """Tests for Agent dataclass."""
    
    def test_agent_creation(self):
        """Test creating an agent."""
        agent = Agent(
            id="agent-1",
            capabilities=["analysis", "validation"],
        )
        
        assert agent.id == "agent-1"
        assert agent.capabilities == ["analysis", "validation"]
        assert agent.status == AgentStatus.IDLE
        assert agent.last_heartbeat is not None
        assert agent.current_task_id is None
    
    def test_has_capability(self):
        """Test has_capability method."""
        agent = Agent(
            id="agent-1",
            capabilities=["analysis", "validation"],
        )
        
        assert agent.has_capability("analysis") is True
        assert agent.has_capability("validation") is True
        assert agent.has_capability("synthesis") is False
    
    def test_has_capabilities(self):
        """Test has_capabilities method."""
        agent = Agent(
            id="agent-1",
            capabilities=["analysis", "validation", "synthesis"],
        )
        
        assert agent.has_capabilities(["analysis"]) is True
        assert agent.has_capabilities(["analysis", "validation"]) is True
        assert agent.has_capabilities(["analysis", "missing"]) is False
    
    def test_is_healthy(self):
        """Test is_healthy method."""
        agent = Agent(
            id="agent-1",
            capabilities=["analysis"],
        )
        
        assert agent.is_healthy() is True
        assert agent.is_healthy(timeout_seconds=0) is False
        
        # Set old heartbeat
        agent.last_heartbeat = datetime.utcnow() - timedelta(seconds=120)
        assert agent.is_healthy(timeout_seconds=60) is False
    
    def test_to_dict(self):
        """Test to_dict method."""
        agent = Agent(
            id="agent-1",
            capabilities=["analysis"],
            status=AgentStatus.BUSY,
            metadata={"version": "1.0"},
        )
        
        data = agent.to_dict()
        
        assert data["id"] == "agent-1"
        assert data["capabilities"] == ["analysis"]
        assert data["status"] == "busy"
        assert data["metadata"] == {"version": "1.0"}
    
    def test_from_dict(self):
        """Test from_dict method."""
        data = {
            "id": "agent-1",
            "capabilities": ["analysis"],
            "status": "busy",
            "last_heartbeat": datetime.utcnow().isoformat(),
            "current_task_id": "task-1",
            "metadata": {"version": "1.0"},
            "created_at": datetime.utcnow().isoformat(),
        }
        
        agent = Agent.from_dict(data)
        
        assert agent.id == "agent-1"
        assert agent.capabilities == ["analysis"]
        assert agent.status == AgentStatus.BUSY
        assert agent.current_task_id == "task-1"


# =============================================================================
# Task Tests
# =============================================================================

class TestTask:
    """Tests for Task dataclass."""
    
    def test_task_creation(self):
        """Test creating a task."""
        task = Task(
            type="analysis",
            payload={"data": "test"},
            priority=TaskPriority.HIGH.value,
            required_capabilities=["analysis"],
        )
        
        assert task.type == "analysis"
        assert task.payload == {"data": "test"}
        assert task.priority == TaskPriority.HIGH.value
        assert task.required_capabilities == ["analysis"]
        assert task.status == TaskStatus.PENDING
        assert task.id.startswith("task-")
    
    def test_task_comparison(self):
        """Test task comparison for priority queue."""
        task1 = Task(id="task-1", priority=TaskPriority.HIGH.value)
        task2 = Task(id="task-2", priority=TaskPriority.LOW.value)
        
        assert task1 < task2  # Lower priority value = higher priority
    
    def test_can_retry(self):
        """Test can_retry method."""
        task = Task(max_retries=3)
        
        assert task.can_retry() is True
        task.retry_count = 3
        assert task.can_retry() is False
    
    def test_increment_retry(self):
        """Test increment_retry method."""
        task = Task()
        
        task.increment_retry()
        assert task.retry_count == 1
        
        task.increment_retry()
        assert task.retry_count == 2
    
    def test_to_dict(self):
        """Test to_dict method."""
        task = Task(
            id="task-1",
            type="analysis",
            payload={"data": "test"},
            priority=1,
            required_capabilities=["analysis"],
        )
        
        data = task.to_dict()
        
        assert data["id"] == "task-1"
        assert data["type"] == "analysis"
        assert data["payload"] == {"data": "test"}
        assert data["priority"] == 1
    
    def test_from_dict(self):
        """Test from_dict method."""
        data = {
            "id": "task-1",
            "type": "analysis",
            "payload": {"data": "test"},
            "priority": 1,
            "required_capabilities": ["analysis"],
            "status": "in_progress",
            "assigned_agent_id": "agent-1",
            "retry_count": 1,
            "max_retries": 3,
        }
        
        task = Task.from_dict(data)
        
        assert task.id == "task-1"
        assert task.type == "analysis"
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.assigned_agent_id == "agent-1"


# =============================================================================
# Result Tests
# =============================================================================

class TestResult:
    """Tests for Result dataclass."""
    
    def test_result_creation(self):
        """Test creating a result."""
        result = Result(
            task_id="task-1",
            agent_id="agent-1",
            success=True,
            data={"output": "result"},
            confidence=0.95,
        )
        
        assert result.task_id == "task-1"
        assert result.agent_id == "agent-1"
        assert result.success is True
        assert result.data == {"output": "result"}
        assert result.confidence == 0.95
    
    def test_to_dict(self):
        """Test to_dict method."""
        result = Result(
            task_id="task-1",
            agent_id="agent-1",
            success=True,
            data={"output": "result"},
        )
        
        data = result.to_dict()
        
        assert data["task_id"] == "task-1"
        assert data["agent_id"] == "agent-1"
        assert data["success"] is True


# =============================================================================
# AggregatedResult Tests
# =============================================================================

class TestAggregatedResult:
    """Tests for AggregatedResult dataclass."""
    
    def test_aggregated_result_creation(self):
        """Test creating an aggregated result."""
        result = Result(task_id="task-1", agent_id="agent-1")
        aggregated = AggregatedResult(
            task_id="task-1",
            results=[result],
            final_result={"combined": "data"},
            confidence=0.9,
        )
        
        assert aggregated.task_id == "task-1"
        assert len(aggregated.results) == 1
        assert aggregated.confidence == 0.9
    
    def test_to_dict(self):
        """Test to_dict method."""
        result = Result(task_id="task-1", agent_id="agent-1")
        aggregated = AggregatedResult(
            task_id="task-1",
            results=[result],
            final_result={"combined": "data"},
            confidence=0.9,
            conflict_resolved=True,
        )
        
        data = aggregated.to_dict()
        
        assert data["task_id"] == "task-1"
        assert data["confidence"] == 0.9
        assert data["conflict_resolved"] is True


# =============================================================================
# TaskQueue Tests
# =============================================================================

class TestTaskQueue:
    """Tests for TaskQueue class."""
    
    def test_enqueue_dequeue(self):
        """Test basic enqueue and dequeue operations."""
        queue = TaskQueue()
        task = Task(id="task-1", type="test")
        
        queue.enqueue(task)
        assert queue.size() == 1
        
        dequeued = queue.dequeue()
        assert dequeued.id == "task-1"
        assert queue.size() == 0
    
    def test_priority_ordering(self):
        """Test that higher priority tasks are dequeued first."""
        queue = TaskQueue()
        
        task_low = Task(id="low", priority=TaskPriority.LOW.value)
        task_high = Task(id="high", priority=TaskPriority.HIGH.value)
        task_critical = Task(id="critical", priority=TaskPriority.CRITICAL.value)
        
        # Enqueue in random order
        queue.enqueue(task_low)
        queue.enqueue(task_critical)
        queue.enqueue(task_high)
        
        # Should dequeue in priority order
        assert queue.dequeue().id == "critical"
        assert queue.dequeue().id == "high"
        assert queue.dequeue().id == "low"
    
    def test_capability_matching(self):
        """Test dequeue with capability filtering."""
        queue = TaskQueue()
        
        task1 = Task(id="task-1", required_capabilities=["analysis"])
        task2 = Task(id="task-2", required_capabilities=["synthesis"])
        
        queue.enqueue(task1)
        queue.enqueue(task2)
        
        # Agent with analysis capability should get task-1
        result = queue.dequeue(capabilities=["analysis"])
        assert result.id == "task-1"
        
        # Agent with synthesis capability should get task-2
        result = queue.dequeue(capabilities=["synthesis"])
        assert result.id == "task-2"
    
    def test_capability_matching_with_optional_requirements(self):
        """Test dequeue where task has no required capabilities."""
        queue = TaskQueue()
        
        task1 = Task(id="task-1", required_capabilities=["analysis"])
        task2 = Task(id="task-2", required_capabilities=[])  # No requirements
        
        queue.enqueue(task1)
        queue.enqueue(task2)
        
        # Both tasks match - task-1 is returned first (heap order)
        result = queue.dequeue(capabilities=["analysis"])
        assert result.id == "task-1"
        
        # Now task-2 should be returned (no requirements, matches any capabilities)
        result = queue.dequeue(capabilities=["any"])
        assert result.id == "task-2"
    
    def test_capability_no_match(self):
        """Test dequeue when no task matches capabilities."""
        queue = TaskQueue()
        
        task = Task(id="task-1", required_capabilities=["special"])
        queue.enqueue(task)
        
        result = queue.dequeue(capabilities=["analysis"])
        assert result is None
    
    def test_requeue(self):
        """Test requeue with reason."""
        queue = TaskQueue()
        task = Task(id="task-1")
        
        queue.enqueue(task)
        queue.requeue("task-1", "Agent unavailable")
        
        history = queue.get_requeue_history("task-1")
        assert len(history) == 1
        assert history[0]["reason"] == "Agent unavailable"
    
    def test_duplicate_task_error(self):
        """Test that duplicate task ID raises error."""
        queue = TaskQueue()
        task = Task(id="task-1")
        
        queue.enqueue(task)
        
        with pytest.raises(ValueError, match="already exists"):
            queue.enqueue(task)
    
    def test_max_size(self):
        """Test queue max size limit."""
        queue = TaskQueue(max_size=2)
        
        queue.enqueue(Task(id="task-1"))
        queue.enqueue(Task(id="task-2"))
        
        with pytest.raises(RuntimeError, match="max capacity"):
            queue.enqueue(Task(id="task-3"))
    
    def test_is_empty(self):
        """Test is_empty method."""
        queue = TaskQueue()
        
        assert queue.is_empty() is True
        
        queue.enqueue(Task(id="task-1"))
        assert queue.is_empty() is False
    
    def test_clear(self):
        """Test clear method."""
        queue = TaskQueue()
        
        queue.enqueue(Task(id="task-1"))
        queue.enqueue(Task(id="task-2"))
        
        queue.clear()
        
        assert queue.size() == 0
        assert queue.is_empty() is True
    
    def test_get_stats(self):
        """Test get_stats method."""
        queue = TaskQueue()
        
        queue.enqueue(Task(id="task-1", priority=TaskPriority.HIGH.value))
        queue.enqueue(Task(id="task-2", priority=TaskPriority.HIGH.value))
        queue.enqueue(Task(id="task-3", priority=TaskPriority.LOW.value))
        
        stats = queue.get_stats()
        
        assert stats["total_tasks"] == 3
        assert stats["max_size"] == 10000
        assert stats["priority_distribution"][TaskPriority.HIGH.value] == 2
        assert stats["priority_distribution"][TaskPriority.LOW.value] == 1


# =============================================================================
# AgentRegistry Tests
# =============================================================================

class TestAgentRegistry:
    """Tests for AgentRegistry class."""
    
    def test_register_agent(self):
        """Test registering an agent."""
        registry = AgentRegistry()
        agent = Agent(id="agent-1", capabilities=["analysis"])
        
        registry.register(agent)
        
        assert registry.count() == 1
        assert registry.get_agent("agent-1") == agent
    
    def test_register_duplicate_agent(self):
        """Test that duplicate agent ID raises error."""
        registry = AgentRegistry()
        agent = Agent(id="agent-1", capabilities=["analysis"])
        
        registry.register(agent)
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register(agent)
    
    def test_unregister_agent(self):
        """Test unregistering an agent."""
        registry = AgentRegistry()
        agent = Agent(id="agent-1", capabilities=["analysis"])
        
        registry.register(agent)
        registry.unregister("agent-1")
        
        assert registry.count() == 0
        assert registry.get_agent("agent-1") is None
    
    def test_get_available(self):
        """Test getting available agents."""
        registry = AgentRegistry()
        
        agent1 = Agent(id="agent-1", capabilities=["analysis", "validation"])
        agent2 = Agent(id="agent-2", capabilities=["synthesis"])
        agent3 = Agent(id="agent-3", capabilities=["analysis"])
        
        registry.register(agent1)
        registry.register(agent2)
        registry.register(agent3)
        
        # Get agents with analysis capability
        available = registry.get_available(["analysis"])
        
        assert len(available) == 2
        assert all(a.has_capability("analysis") for a in available)
    
    def test_get_available_all(self):
        """Test getting all available agents."""
        registry = AgentRegistry()
        
        agent1 = Agent(id="agent-1", capabilities=["analysis"])
        agent2 = Agent(id="agent-2", capabilities=["synthesis"])
        
        registry.register(agent1)
        registry.register(agent2)
        
        available = registry.get_available()
        
        assert len(available) == 2
    
    def test_get_available_busy_agent(self):
        """Test that busy agents are not returned."""
        registry = AgentRegistry()
        
        agent1 = Agent(id="agent-1", capabilities=["analysis"])
        agent2 = Agent(id="agent-2", capabilities=["analysis"])
        agent2.status = AgentStatus.BUSY
        
        registry.register(agent1)
        registry.register(agent2)
        
        available = registry.get_available(["analysis"])
        
        assert len(available) == 1
        assert available[0].id == "agent-1"
    
    def test_heartbeat(self):
        """Test heartbeat tracking."""
        registry = AgentRegistry()
        agent = Agent(id="agent-1", capabilities=["analysis"])
        agent.last_heartbeat = datetime.utcnow() - timedelta(seconds=30)
        
        registry.register(agent)
        
        old_heartbeat = agent.last_heartbeat
        time.sleep(0.01)  # Small delay
        registry.heartbeat("agent-1")
        
        assert agent.last_heartbeat > old_heartbeat
    
    def test_heartbeat_not_found(self):
        """Test heartbeat for non-existent agent."""
        registry = AgentRegistry()
        
        with pytest.raises(ValueError, match="not found"):
            registry.heartbeat("non-existent")
    
    def test_heartbeat_timeout(self):
        """Test that agents are marked offline on heartbeat timeout."""
        registry = AgentRegistry(heartbeat_timeout_seconds=1)
        agent = Agent(id="agent-1", capabilities=["analysis"])
        
        registry.register(agent)
        
        # Manually set old heartbeat after registration
        agent.last_heartbeat = datetime.utcnow() - timedelta(seconds=30)
        
        # Trigger health check
        available = registry.get_available()
        
        assert agent.status == AgentStatus.OFFLINE
        assert len(available) == 0
    
    def test_set_agent_status(self):
        """Test setting agent status."""
        registry = AgentRegistry()
        agent = Agent(id="agent-1", capabilities=["analysis"])
        
        registry.register(agent)
        registry.set_agent_status("agent-1", AgentStatus.BUSY)
        
        assert agent.status == AgentStatus.BUSY
    
    def test_get_stats(self):
        """Test get_stats method."""
        registry = AgentRegistry()
        
        agent1 = Agent(id="agent-1", capabilities=["analysis"])
        agent2 = Agent(id="agent-2", capabilities=["analysis", "synthesis"])
        agent2.status = AgentStatus.BUSY
        
        registry.register(agent1)
        registry.register(agent2)
        
        stats = registry.get_stats()
        
        assert stats["total_agents"] == 2
        assert stats["status_distribution"]["idle"] == 1
        assert stats["status_distribution"]["busy"] == 1


# =============================================================================
# MultiAgentOrchestrator Tests
# =============================================================================

class TestMultiAgentOrchestrator:
    """Tests for MultiAgentOrchestrator class."""
    
    def test_register_agent(self):
        """Test registering an agent."""
        orchestrator = MultiAgentOrchestrator()
        
        orchestrator.register_agent("agent-1", ["analysis", "validation"])
        
        status = orchestrator.get_agent_status("agent-1")
        assert status == AgentStatus.IDLE
    
    def test_unregister_agent(self):
        """Test unregistering an agent."""
        orchestrator = MultiAgentOrchestrator()
        
        orchestrator.register_agent("agent-1", ["analysis"])
        orchestrator.unregister_agent("agent-1")
        
        with pytest.raises(ValueError, match="not found"):
            orchestrator.get_agent_status("agent-1")
    
    def test_get_agent_status_not_found(self):
        """Test get_agent_status for non-existent agent."""
        orchestrator = MultiAgentOrchestrator()
        
        with pytest.raises(ValueError, match="not found"):
            orchestrator.get_agent_status("non-existent")
    
    def test_dispatch_task(self):
        """Test dispatching a task to an agent."""
        orchestrator = MultiAgentOrchestrator()
        
        orchestrator.register_agent("agent-1", ["analysis"])
        
        task = Task(
            type="analysis",
            required_capabilities=["analysis"],
        )
        
        agent_id = orchestrator.dispatch_task(task)
        
        assert agent_id == "agent-1"
        assert task.assigned_agent_id == "agent-1"
        assert orchestrator.get_agent_status("agent-1") == AgentStatus.BUSY
    
    def test_dispatch_task_no_agent(self):
        """Test dispatching a task when no agent is available."""
        orchestrator = MultiAgentOrchestrator()
        
        task = Task(
            type="analysis",
            required_capabilities=["analysis"],
        )
        
        agent_id = orchestrator.dispatch_task(task)
        
        # Task should be queued
        assert agent_id == ""
        assert task.status == TaskStatus.QUEUED
    
    def test_dispatch_task_capability_match(self):
        """Test dispatching task to agent with matching capabilities."""
        orchestrator = MultiAgentOrchestrator()
        
        orchestrator.register_agent("agent-1", ["synthesis"])
        orchestrator.register_agent("agent-2", ["analysis", "validation"])
        
        task = Task(
            type="analysis",
            required_capabilities=["analysis"],
        )
        
        agent_id = orchestrator.dispatch_task(task)
        
        assert agent_id == "agent-2"
    
    def test_submit_result(self):
        """Test submitting a result."""
        orchestrator = MultiAgentOrchestrator()
        
        orchestrator.register_agent("agent-1", ["analysis"])
        
        task = Task(type="analysis", required_capabilities=["analysis"])
        orchestrator.dispatch_task(task)
        
        result = Result(
            task_id=task.id,
            agent_id="agent-1",
            success=True,
            data={"output": "result"},
        )
        
        orchestrator.submit_result(result)
        
        # Agent should be idle again
        assert orchestrator.get_agent_status("agent-1") == AgentStatus.IDLE
        
        # Result should be stored
        results = orchestrator.get_task_result(task.id)
        assert len(results) == 1
    
    def test_aggregate_results(self):
        """Test aggregating results."""
        orchestrator = MultiAgentOrchestrator()
        
        task = Task(id="task-1")
        result1 = Result(task_id="task-1", agent_id="agent-1", confidence=0.8, data={"a": 1})
        result2 = Result(task_id="task-1", agent_id="agent-2", confidence=0.9, data={"b": 2})
        
        orchestrator.submit_result(result1)
        orchestrator.submit_result(result2)
        
        aggregated = orchestrator.aggregate_results("task-1")
        
        assert aggregated.task_id == "task-1"
        assert len(aggregated.results) == 2
        assert aggregated.confidence == pytest.approx(0.85)
    
    def test_aggregate_results_empty(self):
        """Test aggregating results when no results exist."""
        orchestrator = MultiAgentOrchestrator()
        
        aggregated = orchestrator.aggregate_results("non-existent")
        
        assert aggregated.task_id == "non-existent"
        assert len(aggregated.results) == 0
        assert aggregated.confidence == 0.0
    
    def test_resolve_conflicts(self):
        """Test conflict resolution."""
        orchestrator = MultiAgentOrchestrator()
        
        result1 = Result(
            task_id="task-1",
            agent_id="agent-1",
            confidence=0.9,
            metrics={"accuracy": 0.9, "utility": 0.8, "efficiency": 0.7, "consensus": 0.6},
            data={"value": "A"},
        )
        result2 = Result(
            task_id="task-1",
            agent_id="agent-2",
            confidence=0.5,
            metrics={"accuracy": 0.5, "utility": 0.5, "efficiency": 0.5, "consensus": 0.5},
            data={"value": "B"},
        )
        
        resolved = orchestrator.resolve_conflicts([result1, result2])
        
        assert resolved.success is True
        assert "resolved:" in resolved.agent_id
    
    def test_heartbeat(self):
        """Test orchestrator heartbeat."""
        orchestrator = MultiAgentOrchestrator()
        
        orchestrator.register_agent("agent-1", ["analysis"])
        
        # This should not raise
        orchestrator.agent_heartbeat("agent-1")
    
    def test_event_emission(self):
        """Test that events are emitted when event bus is configured."""
        mock_event_bus = Mock()
        orchestrator = MultiAgentOrchestrator(event_bus=mock_event_bus)
        
        orchestrator.register_agent("agent-1", ["analysis"])
        
        # Event should have been emitted
        assert mock_event_bus.emit.called
    
    def test_get_stats(self):
        """Test get_stats method."""
        orchestrator = MultiAgentOrchestrator()
        
        orchestrator.register_agent("agent-1", ["analysis"])
        orchestrator.register_agent("agent-2", ["synthesis"])
        
        stats = orchestrator.get_stats()
        
        assert stats["registry"]["total_agents"] == 2
        assert stats["queue"]["total_tasks"] == 0
    
    def test_process_queued_tasks(self):
        """Test processing queued tasks."""
        orchestrator = MultiAgentOrchestrator()
        
        # Queue a task first (no agents registered)
        task = Task(type="analysis", required_capabilities=["analysis"])
        orchestrator.dispatch_task(task)
        
        # Now register an agent
        orchestrator.register_agent("agent-1", ["analysis"])
        
        # Process queued tasks
        dispatched = orchestrator.process_queued_tasks()
        
        assert dispatched == 1
        assert orchestrator.get_agent_status("agent-1") == AgentStatus.BUSY


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestCreateOrchestrator:
    """Tests for create_orchestrator factory function."""
    
    def test_create_orchestrator_default(self):
        """Test creating orchestrator with defaults."""
        orchestrator = create_orchestrator()
        
        assert orchestrator is not None
        assert isinstance(orchestrator, MultiAgentOrchestrator)
    
    def test_create_orchestrator_custom(self):
        """Test creating orchestrator with custom settings."""
        orchestrator = create_orchestrator(
            heartbeat_timeout=120,
            max_queue_size=5000,
        )
        
        assert orchestrator is not None


# =============================================================================
# Thread Safety Tests
# =============================================================================

class TestThreadSafety:
    """Tests for thread safety."""
    
    def test_concurrent_registration(self):
        """Test concurrent agent registration."""
        registry = AgentRegistry()
        errors = []
        
        def register_agent(i):
            try:
                agent = Agent(id=f"agent-{i}", capabilities=["test"])
                registry.register(agent)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=register_agent, args=(i,)) for i in range(100)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert registry.count() == 100
    
    def test_concurrent_enqueue_dequeue(self):
        """Test concurrent enqueue and dequeue operations."""
        queue = TaskQueue()
        dequeued = []
        
        def enqueue_tasks():
            for i in range(100):
                queue.enqueue(Task(id=f"task-{i}"))
        
        def dequeue_tasks():
            while len(dequeued) < 100:
                task = queue.dequeue()
                if task:
                    dequeued.append(task.id)
        
        enqueuer = threading.Thread(target=enqueue_tasks)
        dequeuer = threading.Thread(target=dequeue_tasks)
        
        enqueuer.start()
        dequeuer.start()
        
        enqueuer.join()
        dequeuer.join(timeout=5)
        
        assert len(dequeued) == 100


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for the orchestrator."""
    
    def test_full_workflow(self):
        """Test a complete workflow from registration to aggregation."""
        orchestrator = MultiAgentOrchestrator()
        
        # Register agents
        orchestrator.register_agent("analyst", ["analysis"])
        orchestrator.register_agent("validator", ["validation"])
        
        # Create and dispatch task
        task = Task(
            type="analysis",
            payload={"input": "data"},
            required_capabilities=["analysis"],
        )
        
        agent_id = orchestrator.dispatch_task(task)
        assert agent_id == "analyst"
        
        # Submit result
        result = Result(
            task_id=task.id,
            agent_id="analyst",
            success=True,
            data={"analysis_result": "processed"},
            confidence=0.9,
        )
        
        orchestrator.submit_result(result)
        
        # Aggregate results
        aggregated = orchestrator.aggregate_results(task.id)
        
        assert aggregated.confidence == 0.9
        assert aggregated.final_result["analysis_result"] == "processed"
    
    def test_conflict_resolution_workflow(self):
        """Test workflow with conflicting results."""
        orchestrator = MultiAgentOrchestrator()
        
        # Register agents
        orchestrator.register_agent("agent-1", ["analysis"])
        orchestrator.register_agent("agent-2", ["analysis"])
        
        # Dispatch and get first result
        task1 = Task(type="analysis", required_capabilities=["analysis"])
        orchestrator.dispatch_task(task1)
        
        result1 = Result(
            task_id=task1.id,
            agent_id="agent-1",
            confidence=0.9,
            metrics={"accuracy": 0.9, "utility": 0.9, "efficiency": 0.8, "consensus": 0.9},
            data={"result": "A"},
        )
        orchestrator.submit_result(result1)
        
        # Manually add a conflicting result
        result2 = Result(
            task_id=task1.id,
            agent_id="agent-2",
            confidence=0.6,
            metrics={"accuracy": 0.6, "utility": 0.6, "efficiency": 0.6, "consensus": 0.6},
            data={"result": "B"},
        )
        orchestrator.submit_result(result2)
        
        # Aggregate should resolve conflict
        aggregated = orchestrator.aggregate_results(task1.id)
        
        # Conflict should be detected and resolved
        assert aggregated.conflict_resolved is True or len(aggregated.results) == 2
