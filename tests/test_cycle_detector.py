"""
Tests for CycleDetector and PlanningEngine.

ITEM-DAG-112: Cycle detection and amendment validation tests.
"""

import pytest
from typing import List, Tuple

from src.planning.cycle_detector import (
    CycleDetector,
    DAG,
    DAGNode,
    Amendment,
    AmendmentType,
    validate_dag,
    validate_dag_object
)
from src.planning.planning_engine import (
    PlanningEngine,
    EngineState,
    HaltReason,
    PlanStep,
    ValidationResult
)
from src.events.event_bus import EventBus, Event, EventSeverity, EventTypes


class TestDAGNode:
    """Tests for DAGNode dataclass."""
    
    def test_create_node(self):
        """Test creating a DAG node."""
        node = DAGNode(id="node1", data={"key": "value"})
        assert node.id == "node1"
        assert node.data == {"key": "value"}
        assert node.dependencies == []
    
    def test_node_hash(self):
        """Test node hashing."""
        node1 = DAGNode(id="node1")
        node2 = DAGNode(id="node1")
        node3 = DAGNode(id="node2")
        
        assert hash(node1) == hash(node2)
        assert hash(node1) != hash(node3)
    
    def test_node_equality(self):
        """Test node equality."""
        node1 = DAGNode(id="node1", data={"a": 1})
        node2 = DAGNode(id="node1", data={"b": 2})
        node3 = DAGNode(id="node2")
        
        assert node1 == node2  # Same ID
        assert node1 != node3  # Different ID


class TestDAG:
    """Tests for DAG dataclass."""
    
    def test_create_empty_dag(self):
        """Test creating an empty DAG."""
        dag = DAG()
        assert len(dag.nodes) == 0
        assert len(dag.edges) == 0
    
    def test_add_node(self):
        """Test adding nodes to DAG."""
        dag = DAG()
        node = DAGNode(id="node1", data={"type": "test"})
        dag.add_node(node)
        
        assert "node1" in dag.nodes
        assert dag.nodes["node1"].data["type"] == "test"
    
    def test_add_node_with_dependencies(self):
        """Test adding a node with dependencies."""
        dag = DAG()
        
        node1 = DAGNode(id="node1")
        node2 = DAGNode(id="node2", dependencies=["node1"])
        
        dag.add_node(node1)
        dag.add_node(node2)
        
        assert "node1" in dag.edges
        assert "node2" in dag.edges["node1"]
    
    def test_add_edge(self):
        """Test adding edges."""
        dag = DAG()
        dag.add_edge("A", "B")
        dag.add_edge("A", "C")
        
        assert "B" in dag.edges["A"]
        assert "C" in dag.edges["A"]
    
    def test_get_node_ids(self):
        """Test getting all node IDs."""
        dag = DAG()
        dag.add_edge("A", "B")
        dag.add_edge("B", "C")
        
        ids = dag.get_node_ids()
        assert ids == {"A", "B", "C"}
    
    def test_copy(self):
        """Test DAG copying."""
        dag1 = DAG()
        dag1.add_edge("A", "B")
        dag1.metadata["key"] = "value"
        
        dag2 = dag1.copy()
        dag2.add_edge("B", "C")
        
        assert "C" not in dag1.edges.get("B", [])
        assert "C" in dag2.edges.get("B", [])
        assert dag1.metadata["key"] == dag2.metadata["key"]
    
    def test_from_edges(self):
        """Test creating DAG from edges."""
        edges = [("A", "B"), ("B", "C"), ("A", "C")]
        dag = DAG.from_edges(edges)
        
        assert len(dag.nodes) == 3
        assert "B" in dag.edges["A"]
        assert "C" in dag.edges["B"]
        assert "C" in dag.edges["A"]


class TestAmendment:
    """Tests for Amendment dataclass."""
    
    def test_add_edge_amendment(self):
        """Test creating add edge amendment."""
        amendment = Amendment.add_edge("A", "B", {"reason": "dependency"})
        
        assert amendment.amendment_type == AmendmentType.ADD_EDGE
        assert amendment.source == "A"
        assert amendment.target == "B"
        assert amendment.metadata["reason"] == "dependency"
    
    def test_remove_edge_amendment(self):
        """Test creating remove edge amendment."""
        amendment = Amendment.remove_edge("A", "B")
        
        assert amendment.amendment_type == AmendmentType.REMOVE_EDGE
        assert amendment.source == "A"
        assert amendment.target == "B"
    
    def test_add_node_amendment(self):
        """Test creating add node amendment."""
        node = DAGNode(id="new_node")
        amendment = Amendment.add_node(node)
        
        assert amendment.amendment_type == AmendmentType.ADD_NODE
        assert amendment.node.id == "new_node"


class TestCycleDetector:
    """Tests for CycleDetector class."""
    
    def test_empty_graph_no_cycle(self):
        """Test empty graph has no cycle."""
        detector = CycleDetector()
        has_cycle, path = detector.detect_cycle()
        assert not has_cycle
        assert path == []
    
    def test_single_edge_no_cycle(self):
        """Test single edge has no cycle."""
        detector = CycleDetector()
        detector.add_edge("A", "B")
        
        has_cycle, path = detector.detect_cycle()
        assert not has_cycle
    
    def test_simple_cycle(self):
        """Test detection of simple cycle A -> B -> A."""
        detector = CycleDetector()
        detector.add_edge("A", "B")
        detector.add_edge("B", "A")
        
        has_cycle, path = detector.detect_cycle()
        assert has_cycle
        assert len(path) >= 2
        # Cycle should start and end with same node
        assert path[0] == path[-1]
    
    def test_longer_cycle(self):
        """Test detection of longer cycle A -> B -> C -> A."""
        detector = CycleDetector()
        detector.add_edge("A", "B")
        detector.add_edge("B", "C")
        detector.add_edge("C", "A")
        
        has_cycle, path = detector.detect_cycle()
        assert has_cycle
        assert path[0] == path[-1]
    
    def test_self_loop(self):
        """Test detection of self-loop."""
        detector = CycleDetector()
        detector.add_edge("A", "A")
        
        has_cycle, path = detector.detect_cycle()
        assert has_cycle
    
    def test_complex_dag_no_cycle(self):
        """Test complex DAG without cycles."""
        detector = CycleDetector()
        # Diamond pattern
        detector.add_edge("A", "B")
        detector.add_edge("A", "C")
        detector.add_edge("B", "D")
        detector.add_edge("C", "D")
        
        has_cycle, path = detector.detect_cycle()
        assert not has_cycle
    
    def test_topological_sort(self):
        """Test topological sorting."""
        detector = CycleDetector()
        detector.add_edge("A", "B")
        detector.add_edge("B", "C")
        
        success, order = detector.topological_sort()
        assert success
        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("C")
    
    def test_topological_sort_with_cycle(self):
        """Test topological sort fails with cycle."""
        detector = CycleDetector()
        detector.add_edge("A", "B")
        detector.add_edge("B", "A")
        
        success, order = detector.topological_sort()
        assert not success
        assert order == []


class TestCycleDetectorDAGMethods:
    """Tests for CycleDetector DAG-specific methods."""
    
    def test_detect_cycle_in_dag_no_cycle(self):
        """Test cycle detection in DAG without cycles."""
        dag = DAG.from_edges([("A", "B"), ("B", "C")])
        detector = CycleDetector()
        
        cycle = detector.detect_cycle_in_dag(dag)
        assert cycle is None
    
    def test_detect_cycle_in_dag_with_cycle(self):
        """Test cycle detection in DAG with cycle."""
        dag = DAG.from_edges([("A", "B"), ("B", "C"), ("C", "A")])
        detector = CycleDetector()
        
        cycle = detector.detect_cycle_in_dag(dag)
        assert cycle is not None
        assert cycle[0] == cycle[-1]
    
    def test_validate_amendment_add_edge_no_cycle(self):
        """Test amendment that doesn't introduce cycle."""
        dag = DAG.from_edges([("A", "B"), ("B", "C")])
        detector = CycleDetector()
        
        amendment = Amendment.add_edge("C", "D")
        assert detector.validate_amendment(dag, amendment)
    
    def test_validate_amendment_add_edge_creates_cycle(self):
        """Test amendment that would introduce cycle."""
        dag = DAG.from_edges([("A", "B"), ("B", "C")])
        detector = CycleDetector()
        
        # This would create C -> A cycle
        amendment = Amendment.add_edge("C", "A")
        assert not detector.validate_amendment(dag, amendment)
    
    def test_validate_amendment_remove_edge(self):
        """Test remove edge amendment (always valid)."""
        dag = DAG.from_edges([("A", "B"), ("B", "C")])
        detector = CycleDetector()
        
        amendment = Amendment.remove_edge("A", "B")
        assert detector.validate_amendment(dag, amendment)
    
    def test_validate_amendment_with_path(self):
        """Test amendment validation with path return."""
        dag = DAG.from_edges([("A", "B"), ("B", "C")])
        detector = CycleDetector()
        
        amendment = Amendment.add_edge("C", "A")
        valid, path = detector.validate_amendment_with_path(dag, amendment)
        
        assert not valid
        assert path is not None
        assert path[0] == path[-1]
    
    def test_topological_sort_dag(self):
        """Test topological sort of DAG object."""
        dag = DAG.from_edges([("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])
        detector = CycleDetector()
        
        success, order = detector.topological_sort_dag(dag)
        assert success
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")
    
    def test_clear(self):
        """Test clearing the detector."""
        detector = CycleDetector()
        detector.add_edge("A", "B")
        
        detector.clear()
        
        assert len(detector.nodes) == 0
        assert len(detector.graph) == 0


class TestValidateDAGFunction:
    """Tests for validate_dag function."""
    
    def test_validate_empty(self):
        """Test validating empty DAG."""
        result = validate_dag([])
        assert result["valid"]
    
    def test_validate_no_cycle(self):
        """Test validating DAG without cycle."""
        result = validate_dag([("A", "B"), ("B", "C")])
        assert result["valid"]
        assert "order" in result
    
    def test_validate_with_cycle(self):
        """Test validating DAG with cycle."""
        result = validate_dag([("A", "B"), ("B", "A")])
        assert not result["valid"]
        assert result["error"] == "[gap: dag_cycle_detected]"
        assert "cycle" in result


class TestValidateDAGObject:
    """Tests for validate_dag_object function."""
    
    def test_validate_dag_object_no_cycle(self):
        """Test validating DAG object without cycle."""
        dag = DAG.from_edges([("A", "B"), ("B", "C")])
        result = validate_dag_object(dag)
        
        assert result["valid"]
        assert "order" in result
    
    def test_validate_dag_object_with_cycle(self):
        """Test validating DAG object with cycle."""
        dag = DAG.from_edges([("A", "B"), ("B", "C"), ("C", "A")])
        result = validate_dag_object(dag)
        
        assert not result["valid"]
        assert result["error"] == "[gap: dag_cycle_detected]"


class TestPlanningEngine:
    """Tests for PlanningEngine class."""
    
    def test_create_engine(self):
        """Test creating a planning engine."""
        engine = PlanningEngine()
        assert engine.state == EngineState.IDLE
    
    def test_add_step(self):
        """Test adding steps."""
        engine = PlanningEngine()
        step = PlanStep(step_id="step1", action=lambda: None)
        
        engine.add_step(step)
        
        stats = engine.get_stats()
        assert stats["step_count"] == 1
    
    def test_build_dag_no_cycle(self):
        """Test building DAG from steps."""
        engine = PlanningEngine()
        engine.add_step(PlanStep(step_id="A", action=lambda: "A"))
        engine.add_step(PlanStep(step_id="B", action=lambda: "B", dependencies=["A"]))
        
        result = engine.build_dag()
        assert result["valid"]
    
    def test_build_dag_with_cycle(self):
        """Test building DAG with cycle in dependencies."""
        engine = PlanningEngine()
        engine.add_step(PlanStep(step_id="A", action=lambda: "A", dependencies=["B"]))
        engine.add_step(PlanStep(step_id="B", action=lambda: "B", dependencies=["A"]))
        
        result = engine.build_dag()
        assert not result["valid"]
    
    def test_detect_cycle(self):
        """Test cycle detection in engine."""
        engine = PlanningEngine()
        engine.add_step(PlanStep(step_id="A", action=lambda: None, dependencies=["B"]))
        engine.add_step(PlanStep(step_id="B", action=lambda: None, dependencies=["A"]))
        engine.build_dag()
        
        cycle = engine.detect_cycle()
        assert cycle is not None
    
    def test_validate_amendment(self):
        """Test amendment validation."""
        engine = PlanningEngine()
        engine.add_step(PlanStep(step_id="A", action=lambda: None))
        engine.add_step(PlanStep(step_id="B", action=lambda: None))
        engine.build_dag()
        
        # Valid amendment
        result = engine.validate_amendment(Amendment.add_edge("A", "B"))
        assert result.valid
        
        # Invalid amendment (would create self-loop)
        result = engine.validate_amendment(Amendment.add_edge("B", "A"))
        assert result.valid  # This is actually valid - just adds edge B->A
    
    def test_apply_amendment(self):
        """Test applying amendments."""
        engine = PlanningEngine()
        engine.add_step(PlanStep(step_id="A", action=lambda: None))
        engine.build_dag()
        
        result = engine.apply_amendment(Amendment.add_edge("A", "B"))
        assert result
        assert "B" in engine.dag.get_node_ids()
    
    def test_apply_amendment_creates_cycle(self):
        """Test applying amendment that creates cycle is rejected."""
        engine = PlanningEngine()
        engine.add_step(PlanStep(step_id="A", action=lambda: None))
        engine.add_step(PlanStep(step_id="B", action=lambda: None))
        engine.add_step(PlanStep(step_id="C", action=lambda: None))
        engine.build_dag()
        
        # Add edges A -> B -> C
        engine.apply_amendment(Amendment.add_edge("A", "B"))
        engine.apply_amendment(Amendment.add_edge("B", "C"))
        
        # Try to add C -> A (would create cycle)
        result = engine.apply_amendment(Amendment.add_edge("C", "A"))
        assert not result  # Should be rejected
    
    def test_run_no_cycle(self):
        """Test running engine without cycles."""
        engine = PlanningEngine()
        
        results = []
        engine.add_step(PlanStep(step_id="A", action=lambda: results.append("A")))
        engine.add_step(PlanStep(step_id="B", action=lambda: results.append("B"), dependencies=["A"]))
        engine.build_dag()  # Build DAG before running
        
        result = engine.run()
        
        assert result["success"]
        assert results == ["A", "B"]
    
    def test_run_with_cycle(self):
        """Test running engine with cycle halts."""
        engine = PlanningEngine()
        
        engine.add_step(PlanStep(step_id="A", action=lambda: None, dependencies=["B"]))
        engine.add_step(PlanStep(step_id="B", action=lambda: None, dependencies=["A"]))
        engine.build_dag()
        
        result = engine.run()
        
        assert not result["success"]
        assert "cycle" in result
        assert engine.state == EngineState.HALTED
        assert engine.halt_reason == HaltReason.CYCLE_DETECTED
    
    def test_pause_resume(self):
        """Test pausing and resuming."""
        engine = PlanningEngine()
        engine._state = EngineState.RUNNING
        
        assert engine.pause()
        assert engine.state == EngineState.PAUSED
        
        assert engine.resume()
        assert engine.state == EngineState.RUNNING
    
    def test_reset(self):
        """Test resetting engine."""
        engine = PlanningEngine()
        engine.add_step(PlanStep(step_id="A", action=lambda: None))
        engine.build_dag()
        engine._state = EngineState.HALTED
        engine._halt_reason = HaltReason.CYCLE_DETECTED
        
        engine.reset()
        
        assert engine.state == EngineState.IDLE
        assert engine.halt_reason is None
    
    def test_get_stats(self):
        """Test getting engine stats."""
        engine = PlanningEngine()
        engine.add_step(PlanStep(step_id="A", action=lambda: None))
        engine.build_dag()
        
        stats = engine.get_stats()
        
        assert "state" in stats
        assert "step_count" in stats
        assert "dag_nodes" in stats
        assert stats["step_count"] == 1


class TestPlanningEngineEventBusIntegration:
    """Tests for PlanningEngine EventBus integration."""
    
    def test_cycle_emits_event(self):
        """Test that cycle detection emits event."""
        bus = EventBus()
        events = []
        
        def capture_event(event: Event):
            events.append(event)
        
        bus.subscribe("DAG_CYCLE_DETECTED", capture_event)
        
        engine = PlanningEngine(event_bus=bus)
        engine.add_step(PlanStep(step_id="A", action=lambda: None, dependencies=["B"]))
        engine.add_step(PlanStep(step_id="B", action=lambda: None, dependencies=["A"]))
        engine.build_dag()
        engine.run()
        
        assert len(events) == 1
        assert events[0].event_type == "DAG_CYCLE_DETECTED"
        assert "cycle_path" in events[0].data
    
    def test_callback_on_cycle_detected(self):
        """Test callback on cycle detection."""
        engine = PlanningEngine()
        detected_cycles = []
        
        engine.set_on_cycle_detected(lambda path: detected_cycles.append(path))
        
        engine.add_step(PlanStep(step_id="A", action=lambda: None, dependencies=["B"]))
        engine.add_step(PlanStep(step_id="B", action=lambda: None, dependencies=["A"]))
        engine.build_dag()
        engine.run()
        
        assert len(detected_cycles) == 1
    
    def test_callback_on_halt(self):
        """Test callback on engine halt."""
        engine = PlanningEngine()
        halt_reasons = []
        
        engine.set_on_halt(lambda reason: halt_reasons.append(reason))
        
        engine.add_step(PlanStep(step_id="A", action=lambda: None, dependencies=["B"]))
        engine.add_step(PlanStep(step_id="B", action=lambda: None, dependencies=["A"]))
        engine.build_dag()
        engine.run()
        
        assert len(halt_reasons) == 1
        assert halt_reasons[0] == HaltReason.CYCLE_DETECTED


class TestEventBusDAGCycleEvent:
    """Tests for DAG_CYCLE_DETECTED event type."""
    
    def test_event_type_exists(self):
        """Test that DAG_CYCLE_DETECTED event type exists."""
        assert hasattr(EventTypes, "DAG_CYCLE_DETECTED")
        assert EventTypes.DAG_CYCLE_DETECTED == "DAG_CYCLE_DETECTED"
    
    def test_event_severity(self):
        """Test that DAG_CYCLE_DETECTED has correct severity."""
        from src.events.event_bus import get_severity_for_event
        
        severity = get_severity_for_event("DAG_CYCLE_DETECTED")
        assert severity == EventSeverity.WARN
    
    def test_emit_dag_cycle_event(self):
        """Test emitting DAG_CYCLE_DETECTED event."""
        bus = EventBus()
        events = []
        
        bus.subscribe("DAG_CYCLE_DETECTED", lambda e: events.append(e))
        
        bus.emit_simple(
            event_type="DAG_CYCLE_DETECTED",
            data={"cycle_path": ["A", "B", "C", "A"]}
        )
        
        assert len(events) == 1
        assert events[0].severity == EventSeverity.WARN


class TestValidationCriteria:
    """
    ITEM-DAG-112 Validation Criteria Tests.
    
    criterion: cycles_detected - "Cycles detected before execution"
    criterion: amendment_blocked - "Cycle-introducing amendments blocked"
    """
    
    def test_cycles_detected_before_execution(self):
        """
        Validation: Cycles detected before execution.
        
        Test that cycles are detected during DAG construction
        before any execution begins.
        """
        engine = PlanningEngine()
        
        # Create steps with circular dependency
        engine.add_step(PlanStep(step_id="A", action=lambda: 1/0, dependencies=["B"]))
        engine.add_step(PlanStep(step_id="B", action=lambda: 1/0, dependencies=["A"]))
        
        # Build DAG - should detect cycle
        result = engine.build_dag()
        assert not result["valid"]
        
        # Run should fail before executing any actions
        run_result = engine.run()
        assert not run_result["success"]
        assert "cycle" in run_result
    
    def test_amendment_blocked(self):
        """
        Validation: Cycle-introducing amendments blocked.
        
        Test that amendments that would introduce cycles are rejected.
        """
        engine = PlanningEngine()
        
        # Build initial DAG
        engine.add_step(PlanStep(step_id="A", action=lambda: None))
        engine.add_step(PlanStep(step_id="B", action=lambda: None))
        engine.add_step(PlanStep(step_id="C", action=lambda: None))
        engine.build_dag()
        
        # Add edges A -> B -> C
        assert engine.apply_amendment(Amendment.add_edge("A", "B"))
        assert engine.apply_amendment(Amendment.add_edge("B", "C"))
        
        # Try to add C -> A (would create cycle)
        result = engine.validate_amendment(Amendment.add_edge("C", "A"))
        assert not result.valid
        assert result.cycle_path is not None
        
        # Verify applying is blocked
        assert not engine.apply_amendment(Amendment.add_edge("C", "A"))
        
        # Verify DAG remains valid
        cycle = engine.detect_cycle()
        assert cycle is None


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing code."""
    
    def test_existing_detect_cycle_still_works(self):
        """Test that existing detect_cycle() method still works."""
        detector = CycleDetector()
        detector.add_edge("A", "B")
        detector.add_edge("B", "C")
        
        has_cycle, path = detector.detect_cycle()
        assert not has_cycle
        
        # Add cycle
        detector.add_edge("C", "A")
        has_cycle, path = detector.detect_cycle()
        assert has_cycle
    
    def test_existing_topological_sort_still_works(self):
        """Test that existing topological_sort() method still works."""
        detector = CycleDetector()
        detector.add_edge("A", "B")
        detector.add_edge("B", "C")
        
        success, order = detector.topological_sort()
        assert success
        assert len(order) == 3
    
    def test_existing_validate_dag_still_works(self):
        """Test that existing validate_dag() function still works."""
        result = validate_dag([("A", "B"), ("B", "C")])
        assert result["valid"]
        
        result = validate_dag([("A", "B"), ("B", "A")])
        assert not result["valid"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
