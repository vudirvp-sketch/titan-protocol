# TITAN Protocol - Agents Module
"""
SCOUT Roles Matrix Agent Framework for TITAN FUSE Protocol.

ITEM-CAT-02: Four specialized agents with explicit roles:
- RADAR: Domain/signal classification
- DEVIL: Hype detection and risk flagging
- EVAL: Readiness assessment with veto power
- STRAT: Strategy synthesis respecting EVAL constraints

Enforces mandatory DEVIL→EVAL→STRAT pipeline with veto propagation.

ITEM-AGENT-01: Multi-Agent Orchestrator for coordination.
- Agent registration with capability tracking
- Priority-based task dispatching
- Result aggregation with conflict resolution
- Heartbeat-based health monitoring

ITEM-AGENT-02: Agent Communication Protocol.
- AgentMessageType enum for standardized messages
- AgentMessage dataclass for inter-agent communication
- AgentMessageRouter for routing and broadcasting
- EventBus and DLQ integration for delivery guarantees

Version: 4.0.0
"""

from .scout_matrix import (
    AgentRole,
    AgentBase,
    RADARAgent,
    DEVILAgent,
    EVALAgent,
    STRATAgent,
    ScoutPipeline,
    AnalysisContext,
    AdoptionReadiness,
    ScoutOutput,
    create_scout_pipeline,
)

from .multi_agent_orchestrator import (
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

from .agent_protocol import (
    AgentMessageType,
    AgentMessage,
    RouterStats,
    AgentMessageRouter,
    create_message_router,
    create_heartbeat_message,
    create_task_request_message,
    create_task_result_message,
    create_context_share_message,
    create_assistance_request_message,
    create_discovery_broadcast_message,
    create_status_update_message,
)

__all__ = [
    # SCOUT Agents
    'AgentRole',
    'AgentBase',
    'RADARAgent',
    'DEVILAgent',
    'EVALAgent',
    'STRATAgent',
    'ScoutPipeline',
    'AnalysisContext',
    'AdoptionReadiness',
    'ScoutOutput',
    'create_scout_pipeline',
    # Multi-Agent Orchestrator
    'AgentStatus',
    'TaskStatus',
    'TaskPriority',
    'Agent',
    'Task',
    'Result',
    'AggregatedResult',
    'TaskQueue',
    'AgentRegistry',
    'MultiAgentOrchestrator',
    'create_orchestrator',
    # Agent Communication Protocol
    'AgentMessageType',
    'AgentMessage',
    'RouterStats',
    'AgentMessageRouter',
    'create_message_router',
    'create_heartbeat_message',
    'create_task_request_message',
    'create_task_result_message',
    'create_context_share_message',
    'create_assistance_request_message',
    'create_discovery_broadcast_message',
    'create_status_update_message',
]
